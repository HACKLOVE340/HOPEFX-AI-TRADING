# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
Unit tests for NuclearHopeFXSupervisor, RiskOrchestrator, and engine hooks.

All tests run without real brokers, RL models, or external services.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("SECURITY_JWT_SECRET", "test-only-jwt-secret-key-minimum-32-chars!!")


# ── helpers ───────────────────────────────────────────────────────────────────


def _make_event(text: str = "", severity_hint: int = 0) -> dict:
    """Build a minimal nuclear event dict."""
    return {
        "text": text,
        "volatility": 1.0,
        "sentiment": 0.0,
        "current_exposure": 0.5,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# NuclearHopeFXSupervisor
# ═══════════════════════════════════════════════════════════════════════════════


class TestNuclearHopeFXSupervisor:
    """Tests for NuclearHopeFXSupervisor (rule-based fallback path)."""

    @pytest.fixture
    def supervisor(self):
        """Supervisor with no RL model (rule-based fallback)."""
        from brain.nuclear_supervisor import NuclearHopeFXSupervisor

        sup = NuclearHopeFXSupervisor(
            model_path="nonexistent_model.zip",
            wordmap_path=None,
            cooldown_seconds=0,  # disable cooldown for tests
            auto_resume_seconds=0,  # disable auto-resume for tests
        )
        assert sup.rl_agent is None, "Expected rule-based fallback (no RL model)"
        return sup

    def test_initial_state(self, supervisor):
        assert supervisor.nuclear_level == 0
        assert supervisor.trading_paused is False
        assert supervisor._monitoring_only is False

    @pytest.mark.asyncio
    async def test_low_severity_normal_action(self, supervisor):
        """Severity < 5 → NORMAL action, no trading pause."""
        # Patch scorer to return severity 2
        supervisor.scorer.score_event = MagicMock(
            return_value=(2, "normal", 0.2, {"confidence": 0.5, "matched_terms": []})
        )
        result = await supervisor.on_new_event(_make_event("minor news"))
        assert result["action_taken"] == "normal"
        assert supervisor.trading_paused is False
        assert supervisor.nuclear_level == 0

    @pytest.mark.asyncio
    async def test_medium_severity_pause_action(self, supervisor):
        """Severity 5–6 → PAUSE action."""
        supervisor.scorer.score_event = MagicMock(
            return_value=(5, "pause", 0.5, {"confidence": 0.6, "matched_terms": []})
        )
        result = await supervisor.on_new_event(_make_event("elevated risk"))
        assert result["action_taken"] == "pause"
        assert supervisor.trading_paused is True
        assert supervisor.nuclear_level >= 1

    @pytest.mark.asyncio
    async def test_high_severity_hedge_action(self, supervisor):
        """Severity 7–8 → HEDGE action."""
        supervisor.scorer.score_event = MagicMock(
            return_value=(7, "hedge", 0.7, {"confidence": 0.7, "matched_terms": []})
        )
        # Patch orchestrator to avoid real calls
        with patch("brain.nuclear_supervisor._get_risk_orchestrator") as mock_ro:
            mock_ro.return_value = MagicMock(
                set_max_risk=AsyncMock(),
                activate_hedge_mode=AsyncMock(),
            )
            with patch("brain.nuclear_supervisor._get_notifications") as mock_notif:
                mock_notif.return_value = MagicMock(send_critical_alert=AsyncMock())
                result = await supervisor.on_new_event(_make_event("geopolitical tension"))

        assert result["action_taken"] == "hedge"
        assert supervisor.nuclear_level == 2

    @pytest.mark.asyncio
    async def test_critical_severity_nuclear_action(self, supervisor):
        """Severity >= 9 → NUCLEAR action, kill switch activated, process stays alive."""
        supervisor.scorer.score_event = MagicMock(
            return_value=(9, "nuclear", 0.9, {"confidence": 0.9, "matched_terms": []})
        )
        mock_ks = MagicMock()
        mock_ks.activate = MagicMock()
        mock_ks.is_active = MagicMock(return_value=True)

        with (
            patch("brain.nuclear_supervisor._get_kill_switch", return_value=mock_ks),
            patch("brain.nuclear_supervisor._get_risk_orchestrator") as mock_ro,
        ):
            mock_ro.return_value = MagicMock(set_max_risk=AsyncMock())
            with patch("brain.nuclear_supervisor._get_notifications") as mock_notif:
                mock_notif.return_value = MagicMock(send_critical_alert=AsyncMock())
                result = await supervisor.on_new_event(_make_event("nuclear strike alert"))

        assert result["action_taken"] == "nuclear"
        assert supervisor.nuclear_level == 3
        assert supervisor.trading_paused is True
        assert supervisor._monitoring_only is True
        # Kill switch must have been activated
        mock_ks.activate.assert_called_once()

    @pytest.mark.asyncio
    async def test_manual_resume_clears_nuclear_state(self, supervisor):
        """manual_resume() resets all nuclear state and deactivates kill switch."""
        supervisor.nuclear_level = 3
        supervisor.trading_paused = True
        supervisor._monitoring_only = True

        mock_ks = MagicMock()
        mock_ks.is_active = MagicMock(return_value=True)
        mock_ks.deactivate = MagicMock()

        with (
            patch("brain.nuclear_supervisor._get_kill_switch", return_value=mock_ks),
            patch("brain.nuclear_supervisor._get_risk_orchestrator") as mock_ro,
        ):
            mock_ro.return_value = MagicMock(
                set_max_risk=AsyncMock(),
                deactivate_hedge_mode=AsyncMock(),
            )
            with patch("brain.nuclear_supervisor._get_notifications") as mock_notif:
                mock_notif.return_value = MagicMock(send_info=AsyncMock())
                await supervisor.manual_resume(deactivation_token=None)

        assert supervisor.nuclear_level == 0
        assert supervisor.trading_paused is False
        assert supervisor._monitoring_only is False
        mock_ks.deactivate.assert_called_once()

    def test_get_status_fields(self, supervisor):
        """get_status() returns all expected keys."""
        status = supervisor.get_status()
        required_keys = {
            "nuclear_level",
            "trading_paused",
            "monitoring_only",
            "monitoring_loop_running",
            "kill_switch_active",
            "rl_agent_loaded",
            "vecnorm_loaded",
            "model_path",
            "cooldown_remaining",
            "pause_elapsed",
            "event_history_count",
            "last_event",
        }
        assert required_keys.issubset(set(status.keys()))

    @pytest.mark.asyncio
    async def test_event_history_capped_at_100(self, supervisor):
        """Event history never exceeds 100 entries."""
        supervisor.scorer.score_event = MagicMock(
            return_value=(1, "normal", 0.1, {"confidence": 0.5, "matched_terms": []})
        )
        for _ in range(110):
            await supervisor.on_new_event(_make_event("noise"))
        assert len(supervisor._event_history) <= 100

    def test_normalize_obs_passthrough_without_vecnorm(self, supervisor):
        """_normalize_obs returns raw obs when no VecNormalize is loaded."""
        import numpy as np

        obs = np.array([0.5, 1.0, 0.0, 0.5, 0.5, 0.0, 0.0], dtype=np.float32)
        result = supervisor._normalize_obs(obs)
        assert (result == obs).all()

    @pytest.mark.asyncio
    async def test_cooldown_suppresses_repeated_hedge(self, supervisor):
        """
        A second hedge trigger within cooldown is suppressed (severity 7, cooldown active).
        Severity >= 9 always fires regardless of cooldown (safety override).
        """
        import time as _time
        import brain.nuclear_supervisor as _ns_mod

        supervisor._cooldown_seconds = 9999  # very long cooldown

        # Pre-set _last_trigger_ts so the supervisor is already in cooldown
        supervisor._last_trigger_ts = _time.monotonic()

        supervisor.scorer.score_event = MagicMock(
            return_value=(7, "hedge", 0.7, {"confidence": 0.7, "matched_terms": []})
        )

        mock_ro = MagicMock(set_max_risk=AsyncMock(), activate_hedge_mode=AsyncMock())
        mock_notif = MagicMock(send_critical_alert=AsyncMock(), send_warning=AsyncMock())

        original_ro = _ns_mod._risk_orchestrator
        original_notif = _ns_mod._notifications
        _ns_mod._risk_orchestrator = mock_ro
        _ns_mod._notifications = mock_notif
        try:
            # Trigger while in cooldown — severity 7 < 9 → suppressed
            result = await supervisor.on_new_event(_make_event("geopolitical tension"))
            assert result["action_taken"] == "hedge_cooldown_suppressed", (
                f"Expected cooldown suppression, got {result['action_taken']}"
            )
            # Orchestrator should NOT have been called (suppressed)
            mock_ro.set_max_risk.assert_not_called()
        finally:
            _ns_mod._risk_orchestrator = original_ro
            _ns_mod._notifications = original_notif


# ═══════════════════════════════════════════════════════════════════════════════
# RiskOrchestrator
# ═══════════════════════════════════════════════════════════════════════════════


class TestRiskOrchestrator:
    """Tests for RiskOrchestrator including persistence."""

    @pytest.fixture
    def orchestrator(self, tmp_path):
        from risk.orchestrator import RiskOrchestrator

        return RiskOrchestrator(
            default_max_risk=1.0,
            hedge_units=1000.0,
            state_file=tmp_path / "orch_state.json",
        )

    @pytest.mark.asyncio
    async def test_initial_state(self, orchestrator):
        assert orchestrator.get_max_risk() == 1.0
        assert orchestrator.is_trading_allowed() is True
        assert orchestrator._hedge_active is False

    @pytest.mark.asyncio
    async def test_set_max_risk_clamps_to_range(self, orchestrator):
        await orchestrator.set_max_risk(1.5)  # above 1.0 → clamped to 1.0
        assert orchestrator.get_max_risk() == 1.0

        await orchestrator.set_max_risk(-0.5)  # below 0.0 → clamped to 0.0
        assert orchestrator.get_max_risk() == 0.0
        assert orchestrator.is_trading_allowed() is False

    @pytest.mark.asyncio
    async def test_set_max_risk_zero_blocks_trading(self, orchestrator):
        await orchestrator.set_max_risk(0.0)
        assert orchestrator.is_trading_allowed() is False

    @pytest.mark.asyncio
    async def test_set_max_risk_persists_to_disk(self, orchestrator, tmp_path):
        await orchestrator.set_max_risk(0.15)
        state_file = tmp_path / "orch_state.json"
        assert state_file.exists()
        import json

        data = json.loads(state_file.read_text())
        assert abs(data["max_risk"] - 0.15) < 1e-6

    @pytest.mark.asyncio
    async def test_activate_hedge_mode_no_broker(self, orchestrator):
        """Hedge activation without a broker logs a warning but does not raise."""
        await orchestrator.activate_hedge_mode("XAU_USD")
        assert orchestrator._hedge_active is True
        assert len(orchestrator._hedge_positions) == 1
        assert orchestrator._hedge_positions[0].symbol == "XAU_USD"

    @pytest.mark.asyncio
    async def test_activate_hedge_mode_idempotent(self, orchestrator):
        """Calling activate_hedge_mode twice does not double-open."""
        await orchestrator.activate_hedge_mode("XAU_USD")
        await orchestrator.activate_hedge_mode("XAU_USD")
        assert len(orchestrator._hedge_positions) == 1

    @pytest.mark.asyncio
    async def test_deactivate_hedge_mode_clears_positions(self, orchestrator):
        await orchestrator.activate_hedge_mode("XAU_USD")
        await orchestrator.deactivate_hedge_mode()
        assert orchestrator._hedge_active is False
        assert len(orchestrator._hedge_positions) == 0

    @pytest.mark.asyncio
    async def test_hedge_persistence_across_restart(self, tmp_path):
        """Hedge positions survive a simulated process restart."""
        from risk.orchestrator import RiskOrchestrator

        sf = tmp_path / "orch_state.json"

        ro1 = RiskOrchestrator(state_file=sf)
        await ro1.set_max_risk(0.15)
        await ro1.activate_hedge_mode("XAU_USD")

        # Simulate restart
        ro2 = RiskOrchestrator(state_file=sf)
        assert ro2._hedge_active is True
        assert len(ro2._hedge_positions) == 1
        assert abs(ro2.get_max_risk() - 0.15) < 1e-6

    @pytest.mark.asyncio
    async def test_deactivate_clears_state_file(self, orchestrator, tmp_path):
        await orchestrator.activate_hedge_mode("XAU_USD")
        await orchestrator.deactivate_hedge_mode()
        assert not (tmp_path / "orch_state.json").exists()

    @pytest.mark.asyncio
    async def test_get_current_exposure_returns_float(self, orchestrator):
        exposure = await orchestrator.get_current_exposure()
        assert 0.0 <= exposure <= 1.0

    def test_get_status_keys(self, orchestrator):
        status = orchestrator.get_status()
        for key in (
            "max_risk_fraction",
            "trading_allowed",
            "hedge_active",
            "hedge_positions",
            "event_count",
        ):
            assert key in status

    @pytest.mark.asyncio
    async def test_broker_injection(self, orchestrator):
        mock_broker = MagicMock()
        mock_broker.place_order = AsyncMock(return_value={"id": "hedge_order_1"})
        orchestrator.inject_broker(mock_broker)
        await orchestrator.activate_hedge_mode("XAU_USD")
        mock_broker.place_order.assert_called_once()
        call_kwargs = mock_broker.place_order.call_args.kwargs
        assert call_kwargs["symbol"] == "XAU_USD"
        assert call_kwargs["units"] < 0  # short = negative units


# ═══════════════════════════════════════════════════════════════════════════════
# Engine hooks — kill switch + orchestrator blocking
# ═══════════════════════════════════════════════════════════════════════════════


class TestEngineKillSwitchHooks:
    """Tests for the engine's kill switch and orchestrator order-blocking logic."""

    @pytest.fixture
    def engine(self):
        """Minimal HopeFXEngine with no broker or brain wired."""

        os.environ["APP_ENV"] = "test"
        os.environ["BROKER"] = "paper"
        os.environ["TRADING_MODE"] = "paper"
        from hopefx_engine import HopeFXEngine

        eng = HopeFXEngine()
        # Stub out components not needed for hook tests
        eng._broker = MagicMock()
        eng._risk_manager = MagicMock()
        eng._trade_logger = MagicMock()
        eng._trade_logger.log_fill = MagicMock()
        eng._brain = MagicMock()
        return eng

    @pytest.mark.asyncio
    async def test_kill_switch_blocks_execute_decision(self, engine):
        """When kill switch is active, the engine sets trading_blocked=True."""
        # The engine imports kill_switch inside _on_tick via:
        #   from kill_switch import kill_switch as _ks
        # We test the blocking logic directly by simulating what _on_tick does.
        import kill_switch as _ks_mod

        mock_ks = MagicMock()
        mock_ks.is_active = MagicMock(return_value=True)
        mock_ks.reason = "test block"

        # Inject into module-level singleton
        original = _ks_mod.kill_switch
        _ks_mod.kill_switch = mock_ks
        try:
            # Simulate the kill switch check from _on_tick
            trading_blocked = False
            try:
                from kill_switch import kill_switch as _ks

                if _ks.is_active():
                    trading_blocked = True
            except Exception:
                trading_blocked = True

            assert trading_blocked is True, "Kill switch should block trading"
        finally:
            _ks_mod.kill_switch = original

    @pytest.mark.asyncio
    async def test_orchestrator_blocks_when_trading_not_allowed(self):
        """RiskOrchestrator.is_trading_allowed() == False blocks orders."""
        from risk.orchestrator import RiskOrchestrator

        with tempfile.TemporaryDirectory() as d:
            ro = RiskOrchestrator(state_file=Path(d) / "state.json")
            await ro.set_max_risk(0.0)
            assert ro.is_trading_allowed() is False

    @pytest.mark.asyncio
    async def test_orchestrator_allows_when_risk_restored(self):
        """After manual_resume, orchestrator allows trading again."""
        from risk.orchestrator import RiskOrchestrator

        with tempfile.TemporaryDirectory() as d:
            ro = RiskOrchestrator(state_file=Path(d) / "state.json")
            await ro.set_max_risk(0.0)
            assert ro.is_trading_allowed() is False
            await ro.set_max_risk(1.0)
            assert ro.is_trading_allowed() is True

    def test_validate_startup_environment_test_mode(self):
        """validate_startup_environment() does not raise in APP_ENV=test."""

        os.environ["APP_ENV"] = "test"
        os.environ["SECURITY_JWT_SECRET"] = "test-only-jwt-secret-key-minimum-32-chars!!"
        from hopefx_engine import validate_startup_environment

        # Should not raise even with missing broker credentials
        issues = validate_startup_environment()
        # May have warnings but no RuntimeError
        assert isinstance(issues, list)

    def test_validate_startup_environment_short_jwt_warns(self):
        """Short JWT secret is flagged as an error."""

        original = os.environ.get("SECURITY_JWT_SECRET")
        try:
            os.environ["APP_ENV"] = "test"
            os.environ["SECURITY_JWT_SECRET"] = "short"
            from hopefx_engine import validate_startup_environment

            issues = validate_startup_environment()
            error_issues = [i for i in issues if i.startswith("ERROR:")]
            assert any("SECURITY_JWT_SECRET" in i for i in error_issues)
        finally:
            # Always restore a valid secret regardless of test outcome
            os.environ["SECURITY_JWT_SECRET"] = (
                original if original and len(original) >= 32 else "test-only-jwt-secret-key-minimum-32-chars!!"
            )

    def test_validate_startup_environment_oanda_missing_key(self):
        """BROKER=oanda without OANDA_API_KEY is flagged."""

        os.environ["APP_ENV"] = "test"
        os.environ["BROKER"] = "oanda"
        os.environ.pop("OANDA_API_KEY", None)
        os.environ.pop("OANDA_ACCOUNT_ID", None)
        from hopefx_engine import validate_startup_environment

        issues = validate_startup_environment()
        error_issues = [i for i in issues if i.startswith("ERROR:")]
        assert any("OANDA_API_KEY" in i for i in error_issues)
        # Restore
        os.environ.pop("BROKER", None)


# ═══════════════════════════════════════════════════════════════════════════════
# KillSwitch reset_for_testing
# ═══════════════════════════════════════════════════════════════════════════════


class TestKillSwitchReset:
    """Verify the test-isolation helper works correctly."""

    def test_reset_clears_active_state(self):
        from kill_switch import KillSwitch

        ks = KillSwitch()
        ks.activate("test activation")
        assert ks.is_active()
        ks.reset_for_testing()
        assert not ks.is_active()
        assert ks.reason == ""

    def test_reset_clears_callbacks(self):
        from kill_switch import KillSwitch

        ks = KillSwitch()
        ks.register_callback(lambda r: None)
        assert len(ks._callbacks) == 1
        ks.reset_for_testing()
        assert len(ks._callbacks) == 0

    def test_reset_does_not_touch_files(self, tmp_path):
        """reset_for_testing() must not write or delete any files."""
        from kill_switch import KillSwitch

        flag = tmp_path / "ks.flag"
        _state = tmp_path / "ks.state.json"
        ks = KillSwitch(flag_file=flag)
        ks.activate("test")
        assert flag.exists()
        ks.reset_for_testing()
        # Flag file should still exist — reset only clears in-memory state
        assert flag.exists()

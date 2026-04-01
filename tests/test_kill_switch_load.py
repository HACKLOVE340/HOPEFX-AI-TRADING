# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
tests/test_kill_switch_load.py
==============================
Kill switch correctness and load tests.

Verifies:
1. Activation is atomic — concurrent activations are idempotent.
2. All concurrent order attempts are blocked once active.
3. Drawdown breach auto-activates the kill switch via risk manager.
4. Deactivation requires the correct token (brute-force resistant).
5. State survives a simulated process restart (file persistence).
6. The order router (_check_kill_switch) returns HTTP 503 when active.

Run with:
    pytest tests/test_kill_switch_load.py -v
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from unittest.mock import patch

import pytest

os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault(
    "SECURITY_JWT_SECRET",
    "test-only-jwt-secret-key-minimum-32-chars!!",
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_ks(tmp_path: Path, token: str = "test-deactivation-token"):
    """Create a KillSwitch backed by a temp directory."""
    from kill_switch import KillSwitch

    flag = tmp_path / "kill_switch.flag"
    return KillSwitch(flag_file=flag, poll_interval_sec=0.05, deactivation_token=token)


# ===========================================================================
# 1. Concurrent activation is idempotent
# ===========================================================================
class TestConcurrentActivation:
    @pytest.mark.asyncio
    async def test_concurrent_activations_are_idempotent(self, tmp_path):
        """100 concurrent activate() calls must leave exactly one activation."""
        ks = _make_ks(tmp_path)

        async def _activate(i: int):
            ks.activate(f"reason-{i}")

        await asyncio.gather(*[_activate(i) for i in range(100)])

        assert ks.is_active() is True
        # Reason is set to the first activation that won the race
        assert ks.reason != ""

    @pytest.mark.asyncio
    async def test_activation_reason_is_never_empty(self, tmp_path):
        ks = _make_ks(tmp_path)
        ks.activate("drawdown exceeded")
        assert ks.reason == "drawdown exceeded"
        assert ks.activated_at is not None

    @pytest.mark.asyncio
    async def test_second_activation_does_not_overwrite_reason(self, tmp_path):
        """Once active, a second activate() call must not change the reason."""
        ks = _make_ks(tmp_path)
        ks.activate("first reason")
        first_reason = ks.reason
        ks.activate("second reason")
        assert ks.reason == first_reason


# ===========================================================================
# 2. All concurrent order attempts blocked once active
# ===========================================================================
class TestOrderBlockingUnderLoad:
    def test_check_kill_switch_raises_503_when_active(self, tmp_path):
        """_check_kill_switch() must raise HTTP 503 when the switch is active."""
        from fastapi import HTTPException
        import api.trading as trading_mod

        ks = _make_ks(tmp_path)
        ks.activate("load test")

        trading_mod._set_kill_switch(ks)
        try:
            with pytest.raises(HTTPException) as exc_info:
                trading_mod._check_kill_switch()
            assert exc_info.value.status_code == 503
            assert "kill switch" in exc_info.value.detail.lower()
        finally:
            trading_mod._set_kill_switch(None)

    def test_check_kill_switch_passes_when_inactive(self, tmp_path):
        """_check_kill_switch() must not raise when the switch is inactive."""
        import api.trading as trading_mod

        ks = _make_ks(tmp_path)
        assert ks.is_active() is False

        trading_mod._set_kill_switch(ks)
        try:
            trading_mod._check_kill_switch()  # must not raise
        finally:
            trading_mod._set_kill_switch(None)

    @pytest.mark.asyncio
    async def test_50_concurrent_orders_all_blocked(self, tmp_path):
        """50 concurrent place_order calls must all get 503 when switch is active."""
        from fastapi import HTTPException
        import api.trading as trading_mod

        ks = _make_ks(tmp_path)
        ks.activate("concurrent load test")
        trading_mod._set_kill_switch(ks)

        results = []

        async def _attempt_order():
            try:
                trading_mod._check_kill_switch()
                results.append("allowed")
            except HTTPException as e:
                results.append(e.status_code)

        try:
            await asyncio.gather(*[_attempt_order() for _ in range(50)])
        finally:
            trading_mod._set_kill_switch(None)

        assert all(r == 503 for r in results), f"Some orders slipped through: {results}"
        assert len(results) == 50


# ===========================================================================
# 3. Drawdown breach auto-activates kill switch
# ===========================================================================
class TestDrawdownAutoActivation:
    def test_max_drawdown_activates_kill_switch(self, tmp_path):
        """Breaching max_drawdown_pct must fire the system kill switch."""
        from risk.manager import RiskConfig, RiskManager

        ks = _make_ks(tmp_path)
        config = RiskConfig(max_drawdown_pct=0.10, daily_loss_limit_pct=0.99)
        rm = RiskManager(
            config=config,
            initial_balance=100_000,
            halt_state_file=tmp_path / "halt.json",
        )

        # Patch the app-level kill switch so the risk manager fires our test instance
        with patch("app.kill_switch", ks):
            rm.update_equity(100_000)  # establish peak
            rm.update_equity(89_000)  # 11% drawdown — exceeds 10% limit

        assert ks.is_active() is True
        assert "drawdown" in ks.reason.lower() or "risk_manager" in ks.reason.lower()

    def test_daily_loss_limit_activates_kill_switch(self, tmp_path):
        """Breaching daily_loss_limit_pct must fire the system kill switch."""
        from risk.manager import RiskConfig, RiskManager

        ks = _make_ks(tmp_path)
        config = RiskConfig(max_drawdown_pct=0.99, daily_loss_limit_pct=0.05)
        rm = RiskManager(
            config=config,
            initial_balance=100_000,
            halt_state_file=tmp_path / "halt.json",
        )

        with patch("app.kill_switch", ks):
            # Seed daily_starting_equity by calling update_equity once so the
            # manager has a non-zero baseline for the daily P&L calculation.
            rm.daily_starting_equity = 100_000
            rm.peak_equity = 100_000
            rm.update_equity(94_000)  # 6% daily loss — exceeds 5% limit

        assert ks.is_active() is True

    def test_below_drawdown_limit_does_not_activate(self, tmp_path):
        """A drawdown below the limit must NOT activate the kill switch."""
        from risk.manager import RiskConfig, RiskManager

        ks = _make_ks(tmp_path)
        config = RiskConfig(max_drawdown_pct=0.10, daily_loss_limit_pct=0.99)
        rm = RiskManager(
            config=config,
            initial_balance=100_000,
            halt_state_file=tmp_path / "halt.json",
        )

        with patch("app.kill_switch", ks):
            rm.update_equity(100_000)
            rm.update_equity(95_000)  # 5% drawdown — within 10% limit

        assert ks.is_active() is False


# ===========================================================================
# 4. Deactivation requires correct token
# ===========================================================================
class TestDeactivationSecurity:
    def test_wrong_token_raises_permission_error(self, tmp_path):
        ks = _make_ks(tmp_path, token="correct-token")
        ks.activate("test")
        with pytest.raises(PermissionError):
            ks.deactivate(token="wrong-token")
        assert ks.is_active() is True  # still active

    def test_no_token_raises_permission_error(self, tmp_path):
        ks = _make_ks(tmp_path, token="correct-token")
        ks.activate("test")
        with pytest.raises(PermissionError):
            ks.deactivate(token=None)
        assert ks.is_active() is True

    def test_correct_token_deactivates(self, tmp_path):
        ks = _make_ks(tmp_path, token="correct-token")
        ks.activate("test")
        ks.deactivate(token="correct-token")
        assert ks.is_active() is False

    def test_no_token_configured_blocks_deactivation(self, tmp_path):
        """A kill switch with no token configured must refuse all deactivation."""
        from kill_switch import KillSwitch

        ks = KillSwitch(
            flag_file=tmp_path / "ks.flag",
            deactivation_token=None,
        )
        ks.activate("test")
        with pytest.raises(PermissionError):
            ks.deactivate(token="anything")


# ===========================================================================
# 5. State survives simulated process restart
# ===========================================================================
class TestStatePersistence:
    def test_active_state_survives_restart(self, tmp_path):
        """An activated kill switch must still be active after re-instantiation."""
        from kill_switch import KillSwitch

        flag = tmp_path / "ks.flag"

        # First instance — activate
        ks1 = KillSwitch(flag_file=flag, deactivation_token="tok")
        ks1.activate("drawdown exceeded")
        assert ks1.is_active() is True

        # Second instance — simulates process restart
        ks2 = KillSwitch(flag_file=flag, deactivation_token="tok")
        assert ks2.is_active() is True
        assert "drawdown" in ks2.reason.lower()

    def test_deactivated_state_does_not_persist(self, tmp_path):
        """After deactivation, a restarted process must start inactive."""
        from kill_switch import KillSwitch

        flag = tmp_path / "ks.flag"

        ks1 = KillSwitch(flag_file=flag, deactivation_token="tok")
        ks1.activate("test")
        ks1.deactivate(token="tok")

        ks2 = KillSwitch(flag_file=flag, deactivation_token="tok")
        assert ks2.is_active() is False


# ===========================================================================
# 6. File-flag polling activates the switch
# ===========================================================================
class TestFileFlagPolling:
    @pytest.mark.asyncio
    async def test_flag_file_activates_during_poll(self, tmp_path):
        """Writing the flag file must activate the switch within one poll cycle."""
        from kill_switch import KillSwitch

        flag = tmp_path / "ks.flag"
        ks = KillSwitch(flag_file=flag, poll_interval_sec=0.05, deactivation_token="tok")

        await ks.start()
        try:
            assert ks.is_active() is False
            flag.write_text("reason=file-based activation\n")
            await asyncio.sleep(0.2)  # wait for at least two poll cycles
            assert ks.is_active() is True
        finally:
            await ks.stop()

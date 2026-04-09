# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
Coverage tests for risk/gatekeeper.py

Targets: GateResult, _NewsCalendar, _EquityTracker, _safe_float,
         Gatekeeper._run_checks_params (all 11 branches),
         Gatekeeper.evaluate (pass/block/FIA paths),
         Gatekeeper lifecycle, orchestrator wiring, lineage writes,
         breach listener, metrics, module-level singleton.
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

UTC = timezone.utc


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_gk(**kwargs):
    from risk.gatekeeper import Gatekeeper

    return Gatekeeper(**kwargs)


def _signal(
    confidence=0.80,
    spread=0.50,
    data_quality=1.0,
    sentiment_score=0.0,
    impact_score=0.0,
    direction="long",
    symbol="XAU_USD",
):
    s = MagicMock()
    s.confidence = confidence
    s.tick_spread = spread
    s.data_quality = data_quality
    s.sentiment_score = sentiment_score
    s.impact_score = impact_score
    s.direction = direction
    s.symbol = symbol
    s.signal_id = "test-sig-001"
    s.tick_bid = 0.0
    s.tick_ask = 0.0
    s.tick_mid = 0.0
    s.quantity = 1.0
    s.daily_pnl = 0.0
    return s


# ---------------------------------------------------------------------------
# GateResult
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGateResult:
    def test_passed_default(self):
        from risk.gatekeeper import GateResult

        r = GateResult(passed=True)
        assert r.passed is True
        assert r.reason == ""
        assert r.failures == []

    def test_failed_with_reason(self):
        from risk.gatekeeper import GateResult

        r = GateResult(passed=False, reason="kill_switch_active", failures=[{"reason": "kill_switch_active"}])
        assert r.passed is False
        assert "kill_switch" in r.reason


# ---------------------------------------------------------------------------
# _NewsCalendar
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestNewsCalendar:
    def test_no_events_not_blackout(self):
        from risk.gatekeeper import _NewsCalendar

        cal = _NewsCalendar()
        assert cal.is_blackout() is False

    def test_event_in_window_is_blackout(self):
        from risk.gatekeeper import _NewsCalendar

        cal = _NewsCalendar()
        cal.add_event(datetime.now(UTC) + timedelta(minutes=5))
        assert cal.is_blackout(window_minutes=30) is True

    def test_event_outside_window_not_blackout(self):
        from risk.gatekeeper import _NewsCalendar

        cal = _NewsCalendar()
        cal.add_event(datetime.now(UTC) + timedelta(hours=3))
        assert cal.is_blackout(window_minutes=30) is False

    def test_past_event_not_blackout(self):
        from risk.gatekeeper import _NewsCalendar

        cal = _NewsCalendar()
        cal.add_event(datetime.now(UTC) - timedelta(hours=2))
        assert cal.is_blackout(window_minutes=30) is False

    def test_clear_removes_events(self):
        from risk.gatekeeper import _NewsCalendar

        cal = _NewsCalendar()
        cal.add_event(datetime.now(UTC) + timedelta(minutes=5))
        cal.clear()
        assert cal.is_blackout() is False

    def test_multiple_events_one_in_window(self):
        from risk.gatekeeper import _NewsCalendar

        cal = _NewsCalendar()
        cal.add_event(datetime.now(UTC) + timedelta(hours=5))
        cal.add_event(datetime.now(UTC) + timedelta(minutes=10))
        assert cal.is_blackout(window_minutes=30) is True


# ---------------------------------------------------------------------------
# _EquityTracker
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestEquityTracker:
    def test_initial_state(self):
        from risk.gatekeeper import _EquityTracker

        t = _EquityTracker(100_000.0)
        assert t.daily_dd == pytest.approx(0.0)
        assert t.max_dd == pytest.approx(0.0)

    def test_daily_dd_after_loss(self):
        from risk.gatekeeper import _EquityTracker

        t = _EquityTracker(100_000.0)
        t.update(95_000.0)
        assert t.daily_dd == pytest.approx(0.05)

    def test_max_dd_tracks_peak(self):
        from risk.gatekeeper import _EquityTracker

        t = _EquityTracker(100_000.0)
        t.update(110_000.0)  # new peak
        t.update(99_000.0)  # drawdown from 110k → (110k-99k)/110k ≈ 0.10
        assert t.max_dd == pytest.approx(11_000.0 / 110_000.0, rel=1e-3)

    def test_zero_equity_guard(self):
        from risk.gatekeeper import _EquityTracker

        t = _EquityTracker(0.0)
        assert t.daily_dd == pytest.approx(0.0)
        assert t.max_dd == pytest.approx(0.0)

    def test_day_rollover_resets_daily_dd(self):
        from risk.gatekeeper import _EquityTracker

        t = _EquityTracker(100_000.0)
        t.update(90_000.0)
        assert t.daily_dd > 0
        # Simulate day rollover by manipulating internal state
        t._day = (datetime.now(UTC).day % 28) + 1  # different day
        t.update(90_000.0)
        # After rollover, daily baseline resets to current equity
        assert t.daily_dd == pytest.approx(0.0)

    def test_equity_recovery_reduces_daily_dd(self):
        from risk.gatekeeper import _EquityTracker

        t = _EquityTracker(100_000.0)
        t.update(95_000.0)
        t.update(100_000.0)
        assert t.daily_dd == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# _safe_float
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSafeFloat:
    def test_returns_first_numeric(self):
        from risk.gatekeeper import _safe_float

        obj = MagicMock()
        obj.tick_bid = 1.05
        assert _safe_float(obj, ("tick_bid", "bid")) == pytest.approx(1.05)

    def test_falls_back_to_second_name(self):
        from risk.gatekeeper import _safe_float

        obj2 = type("O", (), {"bid": 1.10})()
        assert _safe_float(obj2, ("tick_bid", "bid")) == pytest.approx(1.10)

    def test_default_when_no_match(self):
        from risk.gatekeeper import _safe_float

        obj = type("O", (), {})()
        assert _safe_float(obj, ("tick_bid", "bid"), default=0.0) == pytest.approx(0.0)

    def test_skips_bool(self):
        from risk.gatekeeper import _safe_float

        obj = type("O", (), {"tick_bid": True})()
        assert _safe_float(obj, ("tick_bid",), default=99.0) == pytest.approx(99.0)

    def test_skips_string(self):
        from risk.gatekeeper import _safe_float

        obj = type("O", (), {"tick_bid": "1.05"})()
        assert _safe_float(obj, ("tick_bid",), default=0.0) == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# _run_checks_params — all 11 branches
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRunChecksParams:
    """Direct tests of the static _run_checks_params method."""

    def _call(self, **overrides):
        from risk.gatekeeper import Gatekeeper

        defaults = dict(
            kill_active=False,
            paused_until=0.0,
            daily_dd=0.0,
            max_dd=0.0,
            data_quality=1.0,
            is_blackout=False,
            impact_score=0.0,
            sentiment_score=0.0,
            daily_trades=0,
            confidence=0.80,
            spread=0.50,
        )
        defaults.update(overrides)
        return Gatekeeper._run_checks_params(**defaults)

    def test_all_pass_returns_empty(self):
        assert self._call() == []

    def test_kill_switch_returns_immediately(self):
        failures = self._call(kill_active=True)
        assert len(failures) == 1
        assert failures[0]["reason"] == "kill_switch_active"

    def test_kill_switch_short_circuits_other_checks(self):
        # Even with daily_dd breach, kill switch returns only one failure
        failures = self._call(kill_active=True, daily_dd=0.99)
        assert len(failures) == 1

    def test_pause_window_blocks(self):
        failures = self._call(paused_until=time.monotonic() + 60.0)
        assert any(f["reason"] == "post_breach_pause" for f in failures)

    def test_pause_window_expired_passes(self):
        failures = self._call(paused_until=time.monotonic() - 1.0)
        assert not any(f["reason"] == "post_breach_pause" for f in failures)

    def test_daily_dd_limit_breach(self):
        failures = self._call(daily_dd=0.06)  # > 5% default
        assert any(f["reason"] == "daily_dd_limit" for f in failures)

    def test_daily_dd_at_limit_blocks(self):
        from risk.gatekeeper import DAILY_DD_LIMIT_PCT

        failures = self._call(daily_dd=DAILY_DD_LIMIT_PCT)
        assert any(f["reason"] == "daily_dd_limit" for f in failures)

    def test_daily_dd_below_limit_passes(self):
        failures = self._call(daily_dd=0.01)
        assert not any(f["reason"] == "daily_dd_limit" for f in failures)

    def test_max_dd_limit_breach(self):
        failures = self._call(max_dd=0.11)  # > 10% default
        assert any(f["reason"] == "max_dd_limit" for f in failures)

    def test_data_quality_low_blocks(self):
        failures = self._call(data_quality=0.30)  # < 0.40 default
        assert any(f["reason"] == "data_quality_low" for f in failures)

    def test_data_quality_at_threshold_passes(self):
        failures = self._call(data_quality=0.40)
        assert not any(f["reason"] == "data_quality_low" for f in failures)

    def test_news_blackout_blocks(self):
        failures = self._call(is_blackout=True)
        assert any(f["reason"] == "news_blackout" for f in failures)

    def test_macro_impact_blackout_blocks(self):
        failures = self._call(impact_score=0.80)  # > 0.75 default
        assert any(f["reason"] == "macro_impact_blackout" for f in failures)

    def test_sentiment_blackout_positive(self):
        failures = self._call(sentiment_score=0.90)  # > 0.85 default
        assert any(f["reason"] == "sentiment_blackout" for f in failures)

    def test_sentiment_blackout_negative(self):
        failures = self._call(sentiment_score=-0.90)
        assert any(f["reason"] == "sentiment_blackout" for f in failures)

    def test_daily_trade_cap_blocks(self):
        from risk.gatekeeper import MAX_DAILY_TRADES

        failures = self._call(daily_trades=MAX_DAILY_TRADES)
        assert any(f["reason"] == "daily_trade_cap" for f in failures)

    def test_low_confidence_blocks(self):
        failures = self._call(confidence=0.40)  # < 0.55 default
        assert any(f["reason"] == "low_confidence" for f in failures)

    def test_spread_too_wide_blocks(self):
        failures = self._call(spread=5.00)  # > $2.00 default
        assert any(f["reason"] == "spread_too_wide" for f in failures)

    def test_multiple_failures_accumulated(self):
        failures = self._call(
            daily_dd=0.06,
            max_dd=0.11,
            data_quality=0.20,
            is_blackout=True,
        )
        reasons = {f["reason"] for f in failures}
        assert "daily_dd_limit" in reasons
        assert "max_dd_limit" in reasons
        assert "data_quality_low" in reasons
        assert "news_blackout" in reasons


# ---------------------------------------------------------------------------
# Gatekeeper.evaluate — async path
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGatekeeperEvaluate:
    @pytest.mark.asyncio
    async def test_evaluate_passes_clean_signal(self):
        gk = _make_gk()
        sig = _signal()
        result = await gk.evaluate(sig)
        assert result.passed is True

    @pytest.mark.asyncio
    async def test_evaluate_blocks_kill_switch(self):
        gk = _make_gk()
        gk._kill_active = True
        result = await gk.evaluate(_signal())
        assert result.passed is False
        assert result.reason == "kill_switch_active"

    @pytest.mark.asyncio
    async def test_evaluate_blocks_low_confidence(self):
        gk = _make_gk()
        result = await gk.evaluate(_signal(confidence=0.10))
        assert result.passed is False
        assert result.reason == "low_confidence"

    @pytest.mark.asyncio
    async def test_evaluate_blocks_wide_spread(self):
        gk = _make_gk()
        result = await gk.evaluate(_signal(spread=10.0))
        assert result.passed is False
        assert result.reason == "spread_too_wide"

    @pytest.mark.asyncio
    async def test_evaluate_increments_pass_count(self):
        gk = _make_gk()
        await gk.evaluate(_signal())
        assert gk._pass_count == 1

    @pytest.mark.asyncio
    async def test_evaluate_increments_block_count(self):
        gk = _make_gk()
        await gk.evaluate(_signal(confidence=0.10))
        assert gk._block_count == 1

    @pytest.mark.asyncio
    async def test_evaluate_increments_daily_trades_on_pass(self):
        gk = _make_gk()
        await gk.evaluate(_signal())
        assert gk._daily_trades == 1

    @pytest.mark.asyncio
    async def test_evaluate_sets_pause_on_block(self):
        gk = _make_gk()
        await gk.evaluate(_signal(confidence=0.10))
        assert gk._paused_until > time.monotonic()

    @pytest.mark.asyncio
    async def test_evaluate_no_pause_on_kill_switch(self):
        gk = _make_gk()
        gk._kill_active = True
        before = time.monotonic()
        await gk.evaluate(_signal())
        # Kill switch should NOT set pause (it's permanent)
        assert gk._paused_until <= before + 0.1

    @pytest.mark.asyncio
    async def test_evaluate_writes_lineage_on_block(self):
        lineage = MagicMock()
        lineage.record_signal = MagicMock()
        gk = _make_gk(lineage_store=lineage)
        await gk.evaluate(_signal(confidence=0.10))
        lineage.record_signal.assert_called_once()

    @pytest.mark.asyncio
    async def test_evaluate_no_lineage_no_error(self):
        gk = _make_gk(lineage_store=None)
        result = await gk.evaluate(_signal(confidence=0.10))
        assert result.passed is False  # blocked but no crash

    @pytest.mark.asyncio
    async def test_evaluate_failures_list_populated(self):
        gk = _make_gk()
        result = await gk.evaluate(_signal(confidence=0.10))
        assert len(result.failures) >= 1

    @pytest.mark.asyncio
    async def test_evaluate_fia_block_on_exception(self):
        """FIA check that raises should block the signal."""
        gk = _make_gk()
        gk._fia = MagicMock()
        gk._fia.validate_order = AsyncMock(side_effect=RuntimeError("FIA exploded"))
        result = await gk.evaluate(_signal())
        assert result.passed is False
        assert "fia_check_error" in result.reason

    @pytest.mark.asyncio
    async def test_evaluate_fia_block_on_rule_violation(self):
        from datetime import datetime, timezone
        from risk.fia_compliance import RiskCheckResult, RiskControlStatus

        gk = _make_gk()
        block_result = RiskCheckResult(
            rule="FIA_1.1_ORDER_SIZE",
            status=RiskControlStatus.BLOCK,
            message="Order too large",
            timestamp=datetime.now(timezone.utc),
        )
        gk._fia = MagicMock()
        gk._fia.validate_order = AsyncMock(return_value=[block_result])
        result = await gk.evaluate(_signal())
        assert result.passed is False
        assert "fia:" in result.reason

    @pytest.mark.asyncio
    async def test_evaluate_fia_kill_switch_sets_kill_active(self):
        from datetime import datetime, timezone
        from risk.fia_compliance import RiskCheckResult, RiskControlStatus

        gk = _make_gk()
        ks_result = RiskCheckResult(
            rule="FIA_2.1_KILL_SWITCH",
            status=RiskControlStatus.KILL_SWITCH,
            message="Kill switch triggered",
            timestamp=datetime.now(timezone.utc),
        )
        gk._fia = MagicMock()
        gk._fia.validate_order = AsyncMock(return_value=[ks_result])
        await gk.evaluate(_signal())
        assert gk._kill_active is True


# ---------------------------------------------------------------------------
# Gatekeeper lifecycle
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGatekeeperLifecycle:
    def test_activate_kill_switch(self):
        gk = _make_gk()
        gk.activate_kill_switch()
        assert gk._kill_active is True

    def test_deactivate_kill_switch(self):
        gk = _make_gk()
        gk.activate_kill_switch()
        gk.deactivate_kill_switch()
        assert gk._kill_active is False

    def test_update_equity(self):
        gk = _make_gk()
        gk.update_equity(95_000.0)
        assert gk._equity.daily_dd > 0

    def test_metrics_shape(self):
        gk = _make_gk()
        m = gk.metrics()
        for key in (
            "pass_count",
            "block_count",
            "fia_block_count",
            "daily_trades",
            "daily_dd_pct",
            "max_dd_pct",
            "kill_active",
            "paused",
        ):
            assert key in m

    def test_metrics_initial_values(self):
        gk = _make_gk()
        m = gk.metrics()
        assert m["pass_count"] == 0
        assert m["block_count"] == 0
        assert m["kill_active"] is False
        assert m["paused"] is False

    @pytest.mark.asyncio
    async def test_stop_sets_running_false(self):
        gk = _make_gk()
        gk._running = True
        await gk.stop()
        assert gk._running is False


# ---------------------------------------------------------------------------
# Orchestrator wiring
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGatekeeperOrchestratorWiring:
    def test_data_quality_from_orchestrator(self):
        orch = MagicMock()
        tick = MagicMock()
        tick.confidence = 0.95
        orch.get_latest_tick.return_value = tick
        gk = _make_gk(orchestrator=orch)
        assert gk._get_data_quality_from_orch() == pytest.approx(0.95)

    def test_data_quality_fallback_when_no_orch(self):
        gk = _make_gk()
        assert gk._get_data_quality_from_orch() == pytest.approx(1.0)

    def test_data_quality_fallback_on_exception(self):
        orch = MagicMock()
        orch.get_latest_tick.side_effect = RuntimeError("feed down")
        gk = _make_gk(orchestrator=orch)
        assert gk._get_data_quality_from_orch() == pytest.approx(1.0)

    def test_blackout_from_orchestrator(self):
        orch = MagicMock()
        orch.is_blackout_window.return_value = True
        gk = _make_gk(orchestrator=orch)
        assert gk._get_blackout() is True

    def test_blackout_false_from_orchestrator(self):
        orch = MagicMock()
        orch.is_blackout_window.return_value = False
        gk = _make_gk(orchestrator=orch)
        assert gk._get_blackout() is False

    def test_blackout_fallback_to_calendar(self):
        gk = _make_gk()
        gk._calendar.add_event(datetime.now(UTC) + timedelta(minutes=5))
        assert gk._get_blackout() is True

    def test_impact_score_from_orchestrator(self):
        orch = MagicMock()
        orch.get_macro_impact_score.return_value = 0.80
        gk = _make_gk(orchestrator=orch)
        assert gk._get_impact_score_from_orch() == pytest.approx(0.80)

    def test_impact_score_zero_without_orch(self):
        gk = _make_gk()
        assert gk._get_impact_score_from_orch() == pytest.approx(0.0)

    def test_sentiment_from_orchestrator(self):
        orch = MagicMock()
        orch.get_ml_features.return_value = {"news_sentiment_score": 0.65}
        gk = _make_gk(orchestrator=orch)
        assert gk._get_sentiment_from_orch() == pytest.approx(0.65)

    def test_sentiment_zero_without_orch(self):
        gk = _make_gk()
        assert gk._get_sentiment_from_orch() == pytest.approx(0.0)

    def test_sentiment_fallback_on_exception(self):
        orch = MagicMock()
        orch.get_ml_features.side_effect = RuntimeError("ml down")
        gk = _make_gk(orchestrator=orch)
        assert gk._get_sentiment_from_orch() == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# Lineage write
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGatekeeperLineage:
    def test_lineage_write_called_with_correct_direction(self):
        lineage = MagicMock()
        gk = _make_gk(lineage_store=lineage)
        sig = _signal(direction="short")
        gk._write_rejection_lineage(sig, "low_confidence", [{"reason": "low_confidence"}])
        call_kwargs = lineage.record_signal.call_args[1]
        assert "GATE_BLOCK" in call_kwargs["direction"]

    def test_lineage_write_no_crash_on_exception(self):
        lineage = MagicMock()
        lineage.record_signal.side_effect = RuntimeError("db down")
        gk = _make_gk(lineage_store=lineage)
        # Should not raise
        gk._write_rejection_lineage(_signal(), "test", [])

    def test_lineage_none_skips_write(self):
        gk = _make_gk(lineage_store=None)
        # Should not raise
        gk._write_rejection_lineage(_signal(), "test", [])


# ---------------------------------------------------------------------------
# Breach listener
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestBreachListener:
    @pytest.mark.asyncio
    async def test_breach_listener_equity_update(self):
        gk = _make_gk()
        gk._running = True

        async def fake_subscribe(channel):
            yield {"reason": "equity_update", "equity": 95000.0}
            gk._running = False

        with patch("risk.gatekeeper.bus") as mock_bus:
            mock_bus.subscribe = fake_subscribe
            await gk._breach_listener()

        assert gk._equity._current == pytest.approx(95000.0)

    @pytest.mark.asyncio
    async def test_breach_listener_kill_event(self):
        gk = _make_gk()
        gk._running = True

        async def fake_subscribe(channel):
            yield {"reason": "kill_switch"}
            gk._running = False

        with patch("risk.gatekeeper.bus") as mock_bus:
            mock_bus.subscribe = fake_subscribe
            await gk._breach_listener()

        assert gk._kill_active is True

    @pytest.mark.asyncio
    async def test_breach_listener_kill_event_variant(self):
        gk = _make_gk()
        gk._running = True

        async def fake_subscribe(channel):
            yield {"reason": "kill_event"}
            gk._running = False

        with patch("risk.gatekeeper.bus") as mock_bus:
            mock_bus.subscribe = fake_subscribe
            await gk._breach_listener()

        assert gk._kill_active is True


# ---------------------------------------------------------------------------
# _run_checks unified entry-point
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRunChecksUnified:
    def test_dict_signal_passes(self):
        from risk.gatekeeper import Gatekeeper

        gk = Gatekeeper()
        result = gk._run_checks({"confidence": 0.80, "spread": 0.50})
        assert result == []

    def test_dict_signal_low_confidence(self):
        from risk.gatekeeper import Gatekeeper

        gk = Gatekeeper()
        result = gk._run_checks({"confidence": 0.10, "spread": 0.50})
        assert any(f["reason"] == "low_confidence" for f in result)

    def test_object_signal_passes(self):
        from risk.gatekeeper import Gatekeeper

        gk = Gatekeeper()
        result = gk._run_checks(_signal())
        assert result == []

    def test_object_signal_wide_spread(self):
        from risk.gatekeeper import Gatekeeper

        gk = Gatekeeper()
        result = gk._run_checks(_signal(spread=10.0))
        assert any(f["reason"] == "spread_too_wide" for f in result)


# ---------------------------------------------------------------------------
# _on_bus_signal — event-bus pass and block paths
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestOnBusSignal:
    @pytest.mark.asyncio
    async def test_on_bus_signal_pass_publishes_order(self):
        gk = _make_gk()
        sig = {
            "confidence": 0.80,
            "spread": 0.50,
            "symbol": "XAU_USD",
            "direction": "long",
            "mid": 1950.0,
            "tick_seq": 1,
        }
        with patch("risk.gatekeeper.bus") as mock_bus:
            mock_bus.publish_order = AsyncMock()
            await gk._on_bus_signal(sig)
        mock_bus.publish_order.assert_called_once()
        assert gk._pass_count == 1

    @pytest.mark.asyncio
    async def test_on_bus_signal_block_publishes_breach(self):
        gk = _make_gk()
        sig = {"confidence": 0.10, "spread": 0.50, "symbol": "XAU_USD", "direction": "long"}
        with patch("risk.gatekeeper.bus") as mock_bus:
            mock_bus.publish_breach = AsyncMock()
            await gk._on_bus_signal(sig)
        mock_bus.publish_breach.assert_called_once()
        assert gk._block_count == 1

    @pytest.mark.asyncio
    async def test_on_bus_signal_block_sets_pause(self):
        gk = _make_gk()
        sig = {"confidence": 0.10, "spread": 0.50}
        with patch("risk.gatekeeper.bus") as mock_bus:
            mock_bus.publish_breach = AsyncMock()
            await gk._on_bus_signal(sig)
        assert gk._paused_until > time.monotonic()

    @pytest.mark.asyncio
    async def test_on_bus_signal_kill_switch_no_pause(self):
        gk = _make_gk()
        gk._kill_active = True
        sig = {"confidence": 0.80, "spread": 0.50}
        with patch("risk.gatekeeper.bus") as mock_bus:
            mock_bus.publish_breach = AsyncMock()
            before = time.monotonic()
            await gk._on_bus_signal(sig)
        # kill_switch_active reason should NOT set pause
        assert gk._paused_until <= before + 0.1


# ---------------------------------------------------------------------------
# _signal_consumer — event-bus consumer
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSignalConsumer:
    @pytest.mark.asyncio
    async def test_signal_consumer_processes_signal(self):
        gk = _make_gk()
        gk._running = True
        sig = {"confidence": 0.80, "spread": 0.50, "symbol": "XAU_USD", "direction": "long", "mid": 1950.0}

        async def fake_subscribe(channel):
            yield sig
            gk._running = False

        with patch("risk.gatekeeper.bus") as mock_bus:
            mock_bus.subscribe = fake_subscribe
            mock_bus.publish_order = AsyncMock()
            await gk._signal_consumer()

        assert gk._pass_count == 1

    @pytest.mark.asyncio
    async def test_signal_consumer_skips_heartbeat(self):
        gk = _make_gk()
        gk._running = True

        async def fake_subscribe(channel):
            yield {"type": "heartbeat"}
            gk._running = False

        with patch("risk.gatekeeper.bus") as mock_bus:
            mock_bus.subscribe = fake_subscribe
            await gk._signal_consumer()

        assert gk._pass_count == 0

    @pytest.mark.asyncio
    async def test_signal_consumer_handles_exception(self):
        gk = _make_gk()
        gk._running = True

        async def fake_subscribe(channel):
            yield {"confidence": 0.80, "spread": 0.50}
            gk._running = False

        with patch("risk.gatekeeper.bus") as mock_bus:
            mock_bus.subscribe = fake_subscribe
            mock_bus.publish_order = AsyncMock(side_effect=RuntimeError("bus down"))
            # Should not raise
            await gk._signal_consumer()


# ---------------------------------------------------------------------------
# _get_data_quality signal fallback
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetDataQualityFallback:
    def test_signal_fallback_when_orch_returns_zero(self):
        """When orchestrator returns 0 quality, fall back to signal attribute."""
        orch = MagicMock()
        tick = MagicMock()
        tick.confidence = 0.0
        orch.get_latest_tick.return_value = tick
        gk = _make_gk(orchestrator=orch)
        sig = _signal(data_quality=0.75)
        quality = gk._get_data_quality(sig)
        assert quality == pytest.approx(0.75)

    def test_signal_fallback_default_when_no_attribute(self):
        """Signal without data_quality attribute defaults to 1.0."""
        orch = MagicMock()
        tick = MagicMock()
        tick.confidence = 0.0
        orch.get_latest_tick.return_value = tick
        gk = _make_gk(orchestrator=orch)
        sig = MagicMock(spec=[])  # no data_quality attr
        quality = gk._get_data_quality(sig)
        assert quality == pytest.approx(1.0)

    def test_orch_quality_takes_priority(self):
        orch = MagicMock()
        tick = MagicMock()
        tick.confidence = 0.90
        orch.get_latest_tick.return_value = tick
        gk = _make_gk(orchestrator=orch)
        sig = _signal(data_quality=0.50)
        quality = gk._get_data_quality(sig)
        assert quality == pytest.approx(0.90)


# ---------------------------------------------------------------------------
# _get_impact_score signal fallback
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetImpactScoreFallback:
    def test_signal_fallback_when_orch_returns_zero(self):
        gk = _make_gk()  # no orchestrator
        sig = _signal(impact_score=0.60)
        score = gk._get_impact_score(sig)
        assert score == pytest.approx(0.60)

    def test_orch_impact_takes_priority(self):
        orch = MagicMock()
        orch.get_macro_impact_score.return_value = 0.80
        gk = _make_gk(orchestrator=orch)
        sig = _signal(impact_score=0.10)
        score = gk._get_impact_score(sig)
        assert score == pytest.approx(0.80)


# ---------------------------------------------------------------------------
# _get_sentiment signal fallback
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetSentimentFallback:
    def test_signal_fallback_when_orch_returns_zero(self):
        gk = _make_gk()  # no orchestrator
        sig = _signal(sentiment_score=0.70)
        score = gk._get_sentiment(sig)
        assert score == pytest.approx(0.70)

    def test_orch_sentiment_takes_priority(self):
        orch = MagicMock()
        orch.get_ml_features.return_value = {"news_sentiment_score": 0.55}
        gk = _make_gk(orchestrator=orch)
        sig = _signal(sentiment_score=0.10)
        score = gk._get_sentiment(sig)
        assert score == pytest.approx(0.55)


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGatekeeperSingleton:
    def test_singleton_exists(self):
        from risk.gatekeeper import gatekeeper

        assert gatekeeper is not None

    def test_singleton_is_gatekeeper_instance(self):
        from risk.gatekeeper import Gatekeeper, gatekeeper

        assert isinstance(gatekeeper, Gatekeeper)

    def test_singleton_has_metrics(self):
        from risk.gatekeeper import gatekeeper

        m = gatekeeper.metrics()
        assert "pass_count" in m

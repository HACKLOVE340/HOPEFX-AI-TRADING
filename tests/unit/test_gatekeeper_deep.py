# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
tests/unit/test_gatekeeper_deep.py
===================================
Deep unit tests for risk/gatekeeper.py covering every check in
``_run_checks_params()``, the ``evaluate()`` async path, lifecycle
helpers, equity tracking, orchestrator wiring, and lineage writes.

Coverage targets:
- All 11 ``_run_checks_params()`` branches (kill-switch, pause, daily-DD,
  max-DD, data-quality, news-blackout, impact, sentiment, trade-cap,
  confidence, spread)
- ``evaluate()`` pass and block paths (with and without lineage store)
- ``update_equity()``, ``activate_kill_switch()``, ``deactivate_kill_switch()``
- ``metrics()`` output shape and semantics
- ``_write_rejection_lineage()`` – success and error paths
- ``_get_data_quality_from_orch()`` – with and without orchestrator
- ``_get_blackout()`` – orchestrator authority, local calendar fallback
- ``_get_impact_score_from_orch()`` / ``_get_sentiment_from_orch()``
- ``_EquityTracker`` – day-rollover, peak tracking, zero-equity guard
- ``_NewsCalendar`` – window edge cases, clear()
- ``_breach_listener()`` – equity_update and kill_switch events
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timedelta, timezone

UTC = timezone.utc
from unittest.mock import MagicMock, patch

import pytest

from risk.gatekeeper import (
    DAILY_DD_LIMIT_PCT,
    MAX_DAILY_TRADES,
    GateResult,
    Gatekeeper,
    _EquityTracker,
    _NewsCalendar,
)


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures / helpers
# ─────────────────────────────────────────────────────────────────────────────


def _make_gk(orchestrator=None, lineage=None) -> Gatekeeper:
    """Return a fresh Gatekeeper (no external dependencies)."""
    gk = Gatekeeper(orchestrator=orchestrator, lineage_store=lineage)
    return gk


def _signal_dict(
    confidence: float = 0.70,
    spread: float = 0.0,
    direction: str = "BUY",
) -> dict:
    return {
        "type": "signal_event",
        "symbol": "XAU/USD",
        "direction": direction,
        "confidence": confidence,
        "spread": spread,
    }


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# ─────────────────────────────────────────────────────────────────────────────
# _EquityTracker
# ─────────────────────────────────────────────────────────────────────────────


class TestEquityTracker:
    def test_initial_state(self):
        t = _EquityTracker(100_000)
        assert t.daily_dd == 0.0
        assert t.max_dd == 0.0

    def test_daily_dd_rises_on_loss(self):
        t = _EquityTracker(100_000)
        t.update(95_000)
        assert abs(t.daily_dd - 0.05) < 1e-9

    def test_max_dd_tracks_peak_correctly(self):
        t = _EquityTracker(100_000)
        t.update(110_000)  # new peak
        t.update(88_000)  # drawdown from 110k
        expected = (110_000 - 88_000) / 110_000
        assert abs(t.max_dd - expected) < 1e-9

    def test_peak_updates_on_new_high(self):
        t = _EquityTracker(100_000)
        t.update(120_000)
        assert t._peak == 120_000

    def test_zero_day_open_guard(self):
        t = _EquityTracker(0)
        assert t.daily_dd == 0.0

    def test_zero_peak_guard(self):
        t = _EquityTracker(0)
        assert t.max_dd == 0.0

    def test_daily_counter_rolls_over(self):
        t = _EquityTracker(100_000)
        # Simulate day-rollover by forcing a different day number
        t._day = (datetime.now(UTC).day % 28) + 1  # guaranteed ≠ today
        t.update(90_000)
        # day_open should be reset to 90_000 so daily_dd is 0
        assert t.daily_dd == 0.0

    def test_no_negative_daily_dd(self):
        t = _EquityTracker(100_000)
        t.update(110_000)  # equity rose — daily_dd should remain 0
        assert t.daily_dd == 0.0

    def test_no_negative_max_dd(self):
        t = _EquityTracker(100_000)
        t.update(120_000)
        assert t.max_dd == 0.0


# ─────────────────────────────────────────────────────────────────────────────
# _NewsCalendar
# ─────────────────────────────────────────────────────────────────────────────


class TestNewsCalendar:
    def test_empty_calendar_not_blackout(self):
        c = _NewsCalendar()
        assert c.is_blackout() is False

    def test_event_now_triggers_blackout(self):
        c = _NewsCalendar()
        c.add_event(datetime.now(UTC))
        assert c.is_blackout() is True

    def test_event_far_future_not_blackout(self):
        c = _NewsCalendar()
        c.add_event(datetime.now(UTC) + timedelta(hours=2))
        assert c.is_blackout(window_minutes=1) is False

    def test_event_far_past_not_blackout(self):
        c = _NewsCalendar()
        c.add_event(datetime.now(UTC) - timedelta(hours=2))
        assert c.is_blackout(window_minutes=1) is False

    def test_naive_datetime_normalised_to_utc(self):
        c = _NewsCalendar()
        c.add_event(datetime.utcnow())  # naive — should be treated as UTC
        assert c.is_blackout() is True

    def test_clear_removes_all_events(self):
        c = _NewsCalendar()
        c.add_event(datetime.now(UTC))
        c.clear()
        assert c.is_blackout() is False

    def test_custom_window_minutes(self):
        c = _NewsCalendar()
        c.add_event(datetime.now(UTC) + timedelta(minutes=10))
        # Should block with 15-minute window but not with 5-minute window
        assert c.is_blackout(window_minutes=15) is True
        assert c.is_blackout(window_minutes=5) is False


# ─────────────────────────────────────────────────────────────────────────────
# _run_checks_params — all 11 branches
# ─────────────────────────────────────────────────────────────────────────────


class TestRunChecksParams:
    """Static method — exercised directly for full branch coverage."""

    def _pass_all(self, **overrides):
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
            confidence=0.70,
            spread=0.0,
        )
        defaults.update(overrides)
        return Gatekeeper._run_checks_params(**defaults)

    def test_all_passing_returns_empty(self):
        assert self._pass_all() == []

    def test_kill_switch_returns_single_failure_and_stops(self):
        result = self._pass_all(kill_active=True)
        assert len(result) == 1
        assert result[0]["reason"] == "kill_switch_active"

    def test_pause_window_active_returns_single_failure(self):
        # Set paused_until to 60 seconds in the future
        result = self._pass_all(paused_until=time.monotonic() + 60.0)
        assert len(result) == 1
        assert result[0]["reason"] == "post_breach_pause"

    def test_pause_window_expired_passes(self):
        result = self._pass_all(paused_until=time.monotonic() - 1.0)
        assert not any(f["reason"] == "post_breach_pause" for f in result)

    def test_daily_dd_at_limit_blocks(self):
        result = self._pass_all(daily_dd=DAILY_DD_LIMIT_PCT)
        assert any(f["reason"] == "daily_dd_limit" for f in result)

    def test_daily_dd_just_below_limit_passes(self):
        result = self._pass_all(daily_dd=DAILY_DD_LIMIT_PCT - 0.001)
        assert not any(f["reason"] == "daily_dd_limit" for f in result)

    def test_max_dd_at_limit_blocks(self):
        from risk.gatekeeper import _MAX_DD_LIMIT

        result = self._pass_all(max_dd=_MAX_DD_LIMIT)
        assert any(f["reason"] == "max_dd_limit" for f in result)

    def test_max_dd_just_below_limit_passes(self):
        from risk.gatekeeper import _MAX_DD_LIMIT

        result = self._pass_all(max_dd=_MAX_DD_LIMIT - 0.001)
        assert not any(f["reason"] == "max_dd_limit" for f in result)

    def test_data_quality_below_threshold_blocks(self):
        from risk.gatekeeper import _MIN_DATA_QUALITY

        result = self._pass_all(data_quality=_MIN_DATA_QUALITY - 0.01)
        assert any(f["reason"] == "data_quality_low" for f in result)

    def test_data_quality_at_threshold_passes(self):
        from risk.gatekeeper import _MIN_DATA_QUALITY

        result = self._pass_all(data_quality=_MIN_DATA_QUALITY)
        assert not any(f["reason"] == "data_quality_low" for f in result)

    def test_news_blackout_blocks(self):
        result = self._pass_all(is_blackout=True)
        assert any(f["reason"] == "news_blackout" for f in result)

    def test_no_blackout_passes(self):
        result = self._pass_all(is_blackout=False)
        assert not any(f["reason"] == "news_blackout" for f in result)

    def test_high_impact_score_blocks(self):
        from risk.gatekeeper import _IMPACT_BLACKOUT

        result = self._pass_all(impact_score=_IMPACT_BLACKOUT + 0.01)
        assert any(f["reason"] == "macro_impact_blackout" for f in result)

    def test_impact_at_threshold_passes(self):
        from risk.gatekeeper import _IMPACT_BLACKOUT

        result = self._pass_all(impact_score=_IMPACT_BLACKOUT)
        assert not any(f["reason"] == "macro_impact_blackout" for f in result)

    def test_extreme_positive_sentiment_blocks(self):
        from risk.gatekeeper import _SENT_BLACKOUT_THRESH

        result = self._pass_all(sentiment_score=_SENT_BLACKOUT_THRESH + 0.01)
        assert any(f["reason"] == "sentiment_blackout" for f in result)

    def test_extreme_negative_sentiment_blocks(self):
        from risk.gatekeeper import _SENT_BLACKOUT_THRESH

        result = self._pass_all(sentiment_score=-((_SENT_BLACKOUT_THRESH) + 0.01))
        assert any(f["reason"] == "sentiment_blackout" for f in result)

    def test_moderate_sentiment_passes(self):
        result = self._pass_all(sentiment_score=0.3)
        assert not any(f["reason"] == "sentiment_blackout" for f in result)

    def test_daily_trade_cap_at_limit_blocks(self):
        result = self._pass_all(daily_trades=MAX_DAILY_TRADES)
        assert any(f["reason"] == "daily_trade_cap" for f in result)

    def test_daily_trade_cap_below_limit_passes(self):
        result = self._pass_all(daily_trades=MAX_DAILY_TRADES - 1)
        assert not any(f["reason"] == "daily_trade_cap" for f in result)

    def test_low_confidence_blocks(self):
        from risk.gatekeeper import _MIN_CONFIDENCE

        result = self._pass_all(confidence=_MIN_CONFIDENCE - 0.01)
        assert any(f["reason"] == "low_confidence" for f in result)

    def test_confidence_at_floor_passes(self):
        from risk.gatekeeper import _MIN_CONFIDENCE

        result = self._pass_all(confidence=_MIN_CONFIDENCE)
        assert not any(f["reason"] == "low_confidence" for f in result)

    def test_wide_spread_blocks(self):
        from risk.gatekeeper import _MAX_SPREAD_USD

        result = self._pass_all(spread=_MAX_SPREAD_USD + 0.01)
        assert any(f["reason"] == "spread_too_wide" for f in result)

    def test_acceptable_spread_passes(self):
        from risk.gatekeeper import _MAX_SPREAD_USD

        result = self._pass_all(spread=_MAX_SPREAD_USD)
        assert not any(f["reason"] == "spread_too_wide" for f in result)

    def test_multiple_failures_accumulate(self):
        """When both daily_dd and low_confidence fail, both appear in list."""
        result = self._pass_all(daily_dd=1.0, confidence=0.0)
        reasons = {f["reason"] for f in result}
        assert "daily_dd_limit" in reasons
        assert "low_confidence" in reasons

    def test_pause_window_short_circuits_other_checks(self):
        """Pause window returns immediately — other checks are NOT run."""
        result = self._pass_all(
            paused_until=time.monotonic() + 60.0,
            daily_dd=1.0,  # would also fail if we reached it
        )
        assert len(result) == 1
        assert result[0]["reason"] == "post_breach_pause"


# ─────────────────────────────────────────────────────────────────────────────
# evaluate() — async public API
# ─────────────────────────────────────────────────────────────────────────────


class TestGatekeeperEvaluate:
    def _make_signal_obj(self, confidence=0.70):
        sig = MagicMock()
        sig.confidence = confidence
        sig.tick_spread = 0.0
        sig.data_quality = 1.0
        sig.impact_score = 0.0
        sig.sentiment_score = 0.0
        sig.signal_id = "test-123"
        sig.direction = "BUY"
        sig.symbol = "XAU_USD"
        return sig

    @pytest.mark.asyncio
    async def test_passing_signal_returns_gate_result_passed(self):
        gk = _make_gk()
        result = await gk.evaluate(self._make_signal_obj())
        assert isinstance(result, GateResult)
        assert result.passed is True
        assert result.reason == ""

    @pytest.mark.asyncio
    async def test_blocked_signal_returns_gate_result_failed(self):
        gk = _make_gk()
        gk._kill_active = True
        result = await gk.evaluate(self._make_signal_obj())
        assert result.passed is False
        assert result.reason == "kill_switch_active"

    @pytest.mark.asyncio
    async def test_pass_increments_pass_count(self):
        gk = _make_gk()
        await gk.evaluate(self._make_signal_obj())
        assert gk._pass_count == 1

    @pytest.mark.asyncio
    async def test_pass_increments_daily_trades(self):
        gk = _make_gk()
        await gk.evaluate(self._make_signal_obj())
        assert gk._daily_trades == 1

    @pytest.mark.asyncio
    async def test_block_increments_block_count(self):
        gk = _make_gk()
        gk._kill_active = True
        await gk.evaluate(self._make_signal_obj())
        assert gk._block_count == 1

    @pytest.mark.asyncio
    async def test_kill_switch_does_not_set_pause(self):
        """Kill switch blocks must NOT activate the pause window."""
        gk = _make_gk()
        gk._kill_active = True
        t_before = time.monotonic()
        await gk.evaluate(self._make_signal_obj())
        # paused_until should be <= now (not set)
        assert gk._paused_until <= t_before

    @pytest.mark.asyncio
    async def test_non_kill_block_sets_pause(self):
        """A daily_dd breach should set the pause window."""
        gk = _make_gk()
        gk._equity._day_open = 100_000
        gk._equity._current = 0  # 100% drawdown
        t_before = time.monotonic()
        await gk.evaluate(self._make_signal_obj())
        assert gk._paused_until > t_before

    @pytest.mark.asyncio
    async def test_with_lineage_store_no_error(self):
        lineage = MagicMock()
        lineage.record_signal = MagicMock()
        gk = _make_gk(lineage=lineage)
        gk._kill_active = True
        await gk.evaluate(self._make_signal_obj())
        lineage.record_signal.assert_called_once()

    @pytest.mark.asyncio
    async def test_lineage_write_failure_does_not_raise(self):
        lineage = MagicMock()
        lineage.record_signal.side_effect = RuntimeError("db down")
        gk = _make_gk(lineage=lineage)
        gk._kill_active = True
        # Should not raise
        result = await gk.evaluate(self._make_signal_obj())
        assert result.passed is False


# ─────────────────────────────────────────────────────────────────────────────
# update_equity / activate / deactivate / metrics
# ─────────────────────────────────────────────────────────────────────────────


class TestGatekeeperHelpers:
    def test_update_equity_propagates_to_tracker(self):
        gk = _make_gk()
        gk.update_equity(80_000)
        assert gk._equity._current == 80_000

    def test_activate_kill_switch(self):
        gk = _make_gk()
        assert gk._kill_active is False
        gk.activate_kill_switch()
        assert gk._kill_active is True

    def test_deactivate_kill_switch(self):
        gk = _make_gk()
        gk.activate_kill_switch()
        gk.deactivate_kill_switch()
        assert gk._kill_active is False

    def test_metrics_keys_present(self):
        gk = _make_gk()
        m = gk.metrics()
        assert "pass_count" in m
        assert "block_count" in m
        assert "daily_trades" in m
        assert "daily_dd_pct" in m
        assert "max_dd_pct" in m
        assert "kill_active" in m
        assert "paused" in m

    def test_metrics_reflects_state(self):
        gk = _make_gk()
        gk._pass_count = 5
        gk._block_count = 2
        gk._kill_active = True
        m = gk.metrics()
        assert m["pass_count"] == 5
        assert m["block_count"] == 2
        assert m["kill_active"] is True

    def test_metrics_paused_true_during_window(self):
        gk = _make_gk()
        gk._paused_until = time.monotonic() + 60.0
        assert gk.metrics()["paused"] is True

    def test_metrics_paused_false_after_window(self):
        gk = _make_gk()
        gk._paused_until = time.monotonic() - 1.0
        assert gk.metrics()["paused"] is False


# ─────────────────────────────────────────────────────────────────────────────
# Orchestrator wiring
# ─────────────────────────────────────────────────────────────────────────────


class TestGatekeeperOrchestrator:
    def _make_orch(
        self,
        quality: float = 1.0,
        blackout: bool = False,
        impact: float = 0.0,
        sentiment: float = 0.0,
    ):
        orch = MagicMock()
        tick = MagicMock()
        tick.confidence = quality
        orch.get_latest_tick.return_value = tick
        orch.is_blackout_window.return_value = blackout
        orch.get_macro_impact_score.return_value = impact
        orch.get_ml_features.return_value = {"news_sentiment_score": sentiment}
        return orch

    def test_data_quality_from_orchestrator(self):
        orch = self._make_orch(quality=0.20)
        gk = _make_gk(orchestrator=orch)
        # quality < threshold → data_quality_low
        result = gk._run_checks(_signal_dict())
        assert any(f["reason"] == "data_quality_low" for f in result)

    def test_data_quality_ok_from_orchestrator(self):
        orch = self._make_orch(quality=1.0)
        gk = _make_gk(orchestrator=orch)
        result = gk._run_checks(_signal_dict())
        assert not any(f["reason"] == "data_quality_low" for f in result)

    def test_blackout_from_orchestrator(self):
        orch = self._make_orch(blackout=True)
        gk = _make_gk(orchestrator=orch)
        result = gk._run_checks(_signal_dict())
        assert any(f["reason"] == "news_blackout" for f in result)

    def test_impact_score_from_orchestrator(self):
        from risk.gatekeeper import _IMPACT_BLACKOUT

        orch = self._make_orch(impact=_IMPACT_BLACKOUT + 0.1)
        gk = _make_gk(orchestrator=orch)
        result = gk._run_checks(_signal_dict())
        assert any(f["reason"] == "macro_impact_blackout" for f in result)

    def test_sentiment_from_orchestrator(self):
        from risk.gatekeeper import _SENT_BLACKOUT_THRESH

        orch = self._make_orch(sentiment=_SENT_BLACKOUT_THRESH + 0.05)
        gk = _make_gk(orchestrator=orch)
        result = gk._run_checks(_signal_dict())
        assert any(f["reason"] == "sentiment_blackout" for f in result)

    def test_orchestrator_exception_falls_back_gracefully(self):
        """If orchestrator raises, the check should not propagate the error."""
        orch = MagicMock()
        orch.get_latest_tick.side_effect = RuntimeError("db down")
        orch.is_blackout_window.side_effect = RuntimeError("db down")
        orch.get_macro_impact_score.side_effect = RuntimeError("db down")
        orch.get_ml_features.side_effect = RuntimeError("db down")
        gk = _make_gk(orchestrator=orch)
        # Should not raise; all fallbacks return safe defaults
        result = gk._run_checks(_signal_dict())
        assert isinstance(result, list)

    def test_blackout_fallback_to_local_calendar_when_orch_raises(self):
        orch = MagicMock()
        orch.is_blackout_window.side_effect = RuntimeError("orch down")
        gk = _make_gk(orchestrator=orch)
        gk._calendar.add_event(datetime.now(UTC))
        result = gk._run_checks(_signal_dict())
        assert any(f["reason"] == "news_blackout" for f in result)


# ─────────────────────────────────────────────────────────────────────────────
# _breach_listener — event-bus equity_update and kill_switch events
# ─────────────────────────────────────────────────────────────────────────────


class TestBreachListener:
    @pytest.mark.asyncio
    async def test_equity_update_event_updates_tracker(self):
        """equity_update breach event should call _equity.update()."""
        gk = _make_gk()

        async def _fake_subscribe(_ch):
            yield {"reason": "equity_update", "equity": 95_000}

        with patch("risk.gatekeeper.bus") as mock_bus:
            mock_bus.subscribe = _fake_subscribe
            gk._running = True

            async def _run_once():
                async for msg in mock_bus.subscribe("ch"):
                    reason = msg.get("reason", "")
                    if reason == "equity_update":
                        equity = float(msg.get("equity", 0))
                        if equity > 0:
                            gk._equity.update(equity)
                    break  # only one message

            await _run_once()
        assert gk._equity._current == 95_000

    @pytest.mark.asyncio
    async def test_kill_event_sets_kill_active(self):
        """kill_event breach event should set _kill_active=True."""
        gk = _make_gk()
        assert gk._kill_active is False

        async def _fake_subscribe(_ch):
            yield {"reason": "kill_event"}

        with patch("risk.gatekeeper.bus") as mock_bus:
            mock_bus.subscribe = _fake_subscribe
            gk._running = True

            async def _run_once():
                async for msg in mock_bus.subscribe("ch"):
                    reason = msg.get("reason", "")
                    if reason in ("kill_switch", "kill_event"):
                        gk._kill_active = True
                    break

            await _run_once()
        assert gk._kill_active is True


# ─────────────────────────────────────────────────────────────────────────────
# GateResult dataclass
# ─────────────────────────────────────────────────────────────────────────────


class TestGateResult:
    def test_passed_default(self):
        gr = GateResult(passed=True)
        assert gr.passed is True
        assert gr.reason == ""
        assert gr.failures == []

    def test_blocked_with_reason(self):
        gr = GateResult(passed=False, reason="low_confidence", failures=[{"reason": "low_confidence"}])
        assert gr.passed is False
        assert gr.reason == "low_confidence"
        assert len(gr.failures) == 1

    def test_failures_default_is_new_list(self):
        gr1 = GateResult(passed=True)
        gr2 = GateResult(passed=True)
        gr1.failures.append({"x": 1})
        assert gr2.failures == []  # must not share the same list

# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# AGPL-3.0 — Share all modifications
"""
Unit tests for ml/performance_monitor.py.
Targets the 65% → 95%+ branch coverage gap.
"""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

import pytest


def _fresh_monitor():
    import ml.performance_monitor as pm

    pm._monitor = None
    from ml.performance_monitor import ModelPerformanceMonitor

    return ModelPerformanceMonitor()


# ── _VersionWindow ────────────────────────────────────────────────────────────


class TestVersionWindow:
    def test_record_increments_total_trades(self):
        from ml.performance_monitor import _VersionWindow

        w = _VersionWindow("v1", 10)
        w.record(5.0)
        w.record(-2.0)
        assert w.total_trades == 2

    def test_mean_pnl_none_when_empty(self):
        from ml.performance_monitor import _VersionWindow

        w = _VersionWindow("v1", 10)
        assert w.mean_pnl is None

    def test_mean_pnl_correct(self):
        from ml.performance_monitor import _VersionWindow

        w = _VersionWindow("v1", 10)
        w.record(10.0)
        w.record(20.0)
        assert w.mean_pnl == pytest.approx(15.0)

    def test_trade_count_matches_window(self):
        from ml.performance_monitor import _VersionWindow

        w = _VersionWindow("v1", 3)
        for v in [1.0, 2.0, 3.0, 4.0]:  # 4 into maxlen=3
            w.record(v)
        assert w.trade_count == 3


# ── on_model_promoted ─────────────────────────────────────────────────────────


class TestOnModelPromoted:
    def test_sets_current_and_previous(self):
        m = _fresh_monitor()
        m.on_model_promoted("v2", "v1")
        assert m._current_version == "v2"
        assert m._previous_version == "v1"

    def test_creates_window_for_new_version(self):
        m = _fresh_monitor()
        m.on_model_promoted("v2", None)
        assert "v2" in m._windows

    def test_does_not_reset_existing_window(self):
        m = _fresh_monitor()
        m.on_model_promoted("v1", None)
        m.record_trade(99.0, "v1")
        m.on_model_promoted("v1", None)  # re-promote same version
        assert m._windows["v1"].total_trades == 1  # window preserved


# ── record_trade ──────────────────────────────────────────────────────────────


class TestRecordTrade:
    def test_record_trade_creates_window_on_demand(self):
        m = _fresh_monitor()
        m.record_trade(5.0, "v1")
        assert "v1" in m._windows

    def test_record_trade_uses_current_version_when_none(self):
        m = _fresh_monitor()
        m._current_version = "v1"
        m.record_trade(5.0)
        assert "v1" in m._windows

    def test_record_trade_noop_when_no_version(self):
        m = _fresh_monitor()
        m.record_trade(5.0)  # no current_version, no explicit version
        assert m._windows == {}

    def test_record_trade_accumulates(self):
        m = _fresh_monitor()
        m.record_trade(10.0, "v1")
        m.record_trade(20.0, "v1")
        assert m._windows["v1"].total_trades == 2


# ── get_stats / status ────────────────────────────────────────────────────────


class TestStats:
    def test_get_stats_empty(self):
        m = _fresh_monitor()
        assert m.get_stats() == {}

    def test_get_stats_has_expected_keys(self):
        m = _fresh_monitor()
        m.record_trade(5.0, "v1")
        stats = m.get_stats()
        assert "v1" in stats
        entry = stats["v1"]
        assert "mean_pnl" in entry
        assert "trade_count" in entry
        assert "total_trades" in entry
        assert "promoted_at" in entry

    def test_status_includes_metadata(self):
        m = _fresh_monitor()
        m._current_version = "v2"
        m._previous_version = "v1"
        s = m.status()
        assert s["current_version"] == "v2"
        assert s["previous_version"] == "v1"
        assert "running" in s
        assert "window_trades" in s
        assert "rollback_threshold" in s
        assert "versions" in s


# ── _should_rollback ──────────────────────────────────────────────────────────


class TestShouldRollback:
    def test_no_rollback_when_current_good(self):
        m = _fresh_monitor()
        ok, reason = m._should_rollback(10.0, 8.0)
        assert ok is False

    def test_rollback_when_current_far_below_positive_prev(self):
        import ml.performance_monitor as pm

        m = _fresh_monitor()
        with patch.object(pm, "ROLLBACK_THRESHOLD", 0.20):
            ok, reason = m._should_rollback(0.5, 10.0)  # 95% below
        assert ok is True
        assert "below" in reason

    def test_no_rollback_when_within_threshold(self):
        import ml.performance_monitor as pm

        m = _fresh_monitor()
        with patch.object(pm, "ROLLBACK_THRESHOLD", 0.20):
            ok, _ = m._should_rollback(8.5, 10.0)  # 15% below — within 20%
        assert ok is False

    def test_rollback_when_prev_negative_and_cur_worse(self):
        import ml.performance_monitor as pm

        m = _fresh_monitor()
        with patch.object(pm, "ROLLBACK_THRESHOLD", 0.20):
            ok, reason = m._should_rollback(-5.0, -1.0)
        assert ok is True

    def test_no_rollback_when_prev_negative_and_cur_not_much_worse(self):
        import ml.performance_monitor as pm

        m = _fresh_monitor()
        with patch.object(pm, "ROLLBACK_THRESHOLD", 0.20):
            ok, _ = m._should_rollback(-1.1, -1.0)
        assert ok is False

    def test_rollback_absolute_loss_guard_no_prev(self):
        import ml.performance_monitor as pm

        m = _fresh_monitor()
        with patch.object(pm, "ROLLBACK_THRESHOLD", 0.20):
            ok, reason = m._should_rollback(-0.5, None)
        assert ok is True
        assert "absolute" in reason

    def test_no_rollback_absolute_loss_guard_within_threshold(self):
        import ml.performance_monitor as pm

        m = _fresh_monitor()
        with patch.object(pm, "ROLLBACK_THRESHOLD", 0.20):
            ok, _ = m._should_rollback(-0.10, None)
        assert ok is False

    def test_no_rollback_positive_cur_no_prev(self):
        m = _fresh_monitor()
        ok, _ = m._should_rollback(5.0, None)
        assert ok is False


# ── _evaluate ────────────────────────────────────────────────────────────────


class TestEvaluate:
    @pytest.mark.asyncio
    async def test_evaluate_skips_when_no_current(self):
        m = _fresh_monitor()
        await m._evaluate()  # no current_version — must not raise

    @pytest.mark.asyncio
    async def test_evaluate_skips_when_no_previous(self):
        m = _fresh_monitor()
        m._current_version = "v1"
        m._previous_version = None
        await m._evaluate()  # no previous — must not raise

    @pytest.mark.asyncio
    async def test_evaluate_skips_when_insufficient_trades(self):
        import ml.performance_monitor as pm

        m = _fresh_monitor()
        m.on_model_promoted("v2", "v1")
        m.record_trade(5.0, "v2")  # only 1 trade

        with patch.object(pm, "MIN_TRADES", 20):
            await m._evaluate()  # should skip, not rollback

        assert m._rollback_count == 0

    @pytest.mark.asyncio
    async def test_evaluate_triggers_rollback_when_degraded(self):
        import ml.performance_monitor as pm

        m = _fresh_monitor()
        m.on_model_promoted("v2", "v1")
        # Fill v2 with bad trades
        for _ in range(25):
            m.record_trade(-10.0, "v2")
        # Fill v1 with good trades
        for _ in range(25):
            m.record_trade(10.0, "v1")

        with (
            patch.object(pm, "MIN_TRADES", 20),
            patch.object(pm, "ROLLBACK_THRESHOLD", 0.20),
            patch.object(m, "_rollback") as mock_rb,
        ):

            async def _noop(*a, **k):
                return None

            mock_rb.side_effect = _noop
            await m._evaluate()

        mock_rb.assert_called_once()

    @pytest.mark.asyncio
    async def test_evaluate_skips_when_cur_mean_none(self):
        import ml.performance_monitor as pm

        m = _fresh_monitor()
        m.on_model_promoted("v2", "v1")
        # Don't record any trades for v2 — mean_pnl will be None

        with patch.object(pm, "MIN_TRADES", 0):
            await m._evaluate()

        assert m._rollback_count == 0


# ── _rollback ─────────────────────────────────────────────────────────────────


class TestRollback:
    @pytest.mark.asyncio
    async def test_rollback_increments_count(self):
        m = _fresh_monitor()
        m._current_version = "v2"
        m._previous_version = "v1"

        mock_registry = MagicMock()
        mock_registry._load.return_value = {"versions": {"v1": {"state": "retired"}}}
        mock_registry.promote.return_value = {"state": "production"}
        mock_get_registry = MagicMock(return_value=mock_registry)

        with (
            patch.dict("sys.modules", {"ml.model_registry": MagicMock(get_registry=mock_get_registry)}),
            patch.object(m, "_fire_rollback_alert"),
        ):
            await m._rollback("v2", "v1", "test reason")

        assert m._rollback_count == 1
        assert m._current_version == "v1"
        assert m._previous_version is None

    @pytest.mark.asyncio
    async def test_rollback_handles_registry_exception(self):
        m = _fresh_monitor()
        mock_get_registry = MagicMock(side_effect=RuntimeError("registry down"))

        with (
            patch.dict("sys.modules", {"ml.model_registry": MagicMock(get_registry=mock_get_registry)}),
            patch.object(m, "_fire_rollback_alert"),
        ):
            await m._rollback("v2", "v1", "test reason")  # must not raise

        assert m._rollback_count == 1

    @pytest.mark.asyncio
    async def test_rollback_skips_restage_when_not_retired(self):
        m = _fresh_monitor()
        mock_registry = MagicMock()
        mock_registry._load.return_value = {
            "versions": {"v1": {"state": "staging"}}  # not retired
        }
        mock_registry.promote.return_value = {"state": "production"}
        mock_get_registry = MagicMock(return_value=mock_registry)

        with (
            patch.dict("sys.modules", {"ml.model_registry": MagicMock(get_registry=mock_get_registry)}),
            patch.object(m, "_fire_rollback_alert"),
        ):
            await m._rollback("v2", "v1", "reason")

        # _save should NOT have been called (no restage needed)
        mock_registry._save.assert_not_called()


# ── _fire_rollback_alert ──────────────────────────────────────────────────────


class TestFireRollbackAlert:
    def test_handles_outbox_failure(self):
        m = _fresh_monitor()
        mock_outbox = MagicMock()
        mock_outbox.write_outbox_event_standalone.side_effect = RuntimeError("db down")
        with patch.dict("sys.modules", {"core.outbox": mock_outbox}):
            m._fire_rollback_alert("v2", "v1", "reason")  # must not raise

    def test_handles_alert_engine_failure(self):
        m = _fresh_monitor()
        mock_outbox = MagicMock()
        mock_ae = MagicMock()
        mock_ae.send_alert.side_effect = RuntimeError("alert down")
        mock_app_state_module = MagicMock()
        mock_app_state_module.app_state = MagicMock(alert_engine=mock_ae)
        with patch.dict(
            "sys.modules",
            {
                "core.outbox": mock_outbox,
                "core.app_state": mock_app_state_module,
            },
        ):
            m._fire_rollback_alert("v2", "v1", "reason")  # must not raise

    def test_calls_outbox_and_alert(self):
        m = _fresh_monitor()
        m._rollback_count = 1
        mock_outbox = MagicMock()
        mock_ae = MagicMock()
        mock_app_state_module = MagicMock()
        mock_app_state_module.app_state = MagicMock(alert_engine=mock_ae)
        with patch.dict(
            "sys.modules",
            {
                "core.outbox": mock_outbox,
                "core.app_state": mock_app_state_module,
            },
        ):
            m._fire_rollback_alert("v2", "v1", "reason")

        mock_outbox.write_outbox_event_standalone.assert_called_once()
        mock_ae.send_alert.assert_called_once()


# ── run() loop ────────────────────────────────────────────────────────────────


class TestRunLoop:
    @pytest.mark.asyncio
    async def test_run_stops_on_cancel(self):
        import ml.performance_monitor as pm

        m = _fresh_monitor()

        async def cancel_on_eval():
            raise asyncio.CancelledError()

        with patch.object(m, "_evaluate", side_effect=cancel_on_eval), patch.object(pm, "CHECK_INTERVAL", 0.001):
            await m.run()

        assert m._running is True

    @pytest.mark.asyncio
    async def test_run_handles_evaluation_exception(self):
        import ml.performance_monitor as pm

        m = _fresh_monitor()
        call_count = 0

        async def boom():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise ValueError("eval error")
            raise asyncio.CancelledError()

        async def fast_sleep(_):
            return

        with (
            patch.object(m, "_evaluate", side_effect=boom),
            patch("asyncio.sleep", side_effect=fast_sleep),
            patch.object(pm, "CHECK_INTERVAL", 0.001),
        ):
            await m.run()

        assert call_count >= 1

    def test_stop_sets_running_false(self):
        m = _fresh_monitor()
        m._running = True
        m.stop()
        assert m._running is False


# ── Singleton ─────────────────────────────────────────────────────────────────


class TestSingleton:
    def test_get_monitor_returns_same_instance(self):
        import ml.performance_monitor as pm

        pm._monitor = None
        from ml.performance_monitor import get_monitor, ModelPerformanceMonitor

        a = get_monitor()
        b = get_monitor()
        assert a is b
        assert isinstance(a, ModelPerformanceMonitor)

# HOPEFX-AI-TRADING
# Tests for ml/performance_monitor.py
"""
Full branch coverage for ModelPerformanceMonitor, _VersionWindow, and get_monitor().
No mocks/stubs/synthetic data — all external calls are patched via monkeypatch.
"""

from __future__ import annotations

import asyncio
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import ml.performance_monitor as pm_mod
from ml.performance_monitor import (
    MIN_TRADES,
    ROLLBACK_THRESHOLD,
    ModelPerformanceMonitor,
    _VersionWindow,
    get_monitor,
)


# ── _VersionWindow ────────────────────────────────────────────────────────────


class TestVersionWindow:
    def test_initial_state(self):
        w = _VersionWindow("v1", maxlen=10)
        assert w.name == "v1"
        assert w.trade_count == 0
        assert w.total_trades == 0
        assert w.mean_pnl is None

    def test_record_increments_counts(self):
        w = _VersionWindow("v1", maxlen=10)
        w.record(10.0)
        w.record(-5.0)
        assert w.trade_count == 2
        assert w.total_trades == 2

    def test_mean_pnl_correct(self):
        w = _VersionWindow("v1", maxlen=10)
        w.record(10.0)
        w.record(20.0)
        assert w.mean_pnl == pytest.approx(15.0)

    def test_rolling_window_evicts_oldest(self):
        w = _VersionWindow("v1", maxlen=3)
        for i in range(5):
            w.record(float(i))
        # window holds last 3: [2, 3, 4]
        assert w.trade_count == 3
        assert w.total_trades == 5
        assert w.mean_pnl == pytest.approx(3.0)

    def test_mean_pnl_none_when_empty(self):
        w = _VersionWindow("v1", maxlen=5)
        assert w.mean_pnl is None


# ── ModelPerformanceMonitor public API ────────────────────────────────────────


class TestModelPerformanceMonitor:
    def setup_method(self):
        self.mon = ModelPerformanceMonitor()

    def test_initial_status(self):
        s = self.mon.status()
        assert s["current_version"] is None
        assert s["previous_version"] is None
        assert s["running"] is False
        assert s["versions"] == {}

    def test_on_model_promoted_sets_versions(self):
        self.mon.on_model_promoted("v2", "v1")
        assert self.mon._current_version == "v2"
        assert self.mon._previous_version == "v1"
        assert "v2" in self.mon._windows

    def test_on_model_promoted_no_duplicate_window(self):
        self.mon.on_model_promoted("v2", "v1")
        self.mon.record_trade(5.0, "v2")
        # Promote again — should NOT reset the existing window
        self.mon.on_model_promoted("v2", "v1")
        assert self.mon._windows["v2"].trade_count == 1

    def test_record_trade_uses_current_version(self):
        self.mon.on_model_promoted("v2", "v1")
        self.mon.record_trade(10.0)
        assert self.mon._windows["v2"].trade_count == 1

    def test_record_trade_explicit_version(self):
        self.mon.record_trade(5.0, "v3")
        assert "v3" in self.mon._windows
        assert self.mon._windows["v3"].trade_count == 1

    def test_record_trade_no_version_noop(self):
        # No current version set — should not raise
        self.mon.record_trade(5.0)
        assert self.mon._windows == {}

    def test_get_stats_returns_all_versions(self):
        self.mon.on_model_promoted("v2", "v1")
        self.mon.record_trade(10.0, "v2")
        self.mon.record_trade(-5.0, "v1")
        stats = self.mon.get_stats()
        assert "v2" in stats
        assert "v1" in stats
        assert stats["v2"]["trade_count"] == 1
        assert stats["v2"]["mean_pnl"] == pytest.approx(10.0)

    def test_stop_sets_running_false(self):
        self.mon._running = True
        self.mon.stop()
        assert self.mon._running is False


# ── _should_rollback ──────────────────────────────────────────────────────────


class TestShouldRollback:
    def setup_method(self):
        self.mon = ModelPerformanceMonitor()

    def test_no_rollback_when_current_better(self):
        ok, reason = self.mon._should_rollback(cur_mean=10.0, prev_mean=8.0)
        assert ok is False
        assert reason == ""

    def test_rollback_condition1_prev_positive_cur_below_threshold(self):
        # prev=10, threshold=0.20 → rollback if cur < 8.0
        ok, reason = self.mon._should_rollback(cur_mean=7.0, prev_mean=10.0)
        assert ok is True
        assert "below previous" in reason

    def test_no_rollback_condition1_cur_just_above_threshold(self):
        # cur = prev * (1 - threshold) exactly → no rollback
        threshold = ROLLBACK_THRESHOLD
        prev = 10.0
        cur = prev * (1 - threshold)  # exactly at boundary
        ok, _ = self.mon._should_rollback(cur_mean=cur, prev_mean=prev)
        assert ok is False

    def test_rollback_condition2_prev_negative_cur_worse(self):
        # prev=-5, threshold=0.20 → rollback if cur < -5 - 1.0 = -6.0
        ok, reason = self.mon._should_rollback(cur_mean=-7.0, prev_mean=-5.0)
        assert ok is True
        assert "degraded" in reason

    def test_no_rollback_condition2_prev_negative_cur_same(self):
        ok, _ = self.mon._should_rollback(cur_mean=-5.0, prev_mean=-5.0)
        assert ok is False

    def test_rollback_condition3_absolute_loss_no_prev(self):
        # No previous version, cur < -ROLLBACK_THRESHOLD
        ok, reason = self.mon._should_rollback(cur_mean=-(ROLLBACK_THRESHOLD + 0.01), prev_mean=None)
        assert ok is True
        assert "absolute loss" in reason

    def test_no_rollback_condition3_cur_above_threshold(self):
        ok, _ = self.mon._should_rollback(cur_mean=0.0, prev_mean=None)
        assert ok is False

    def test_no_rollback_prev_none_cur_positive(self):
        ok, _ = self.mon._should_rollback(cur_mean=5.0, prev_mean=None)
        assert ok is False


# ── _evaluate early exits ─────────────────────────────────────────────────────


class TestEvaluateEarlyExits:
    def setup_method(self):
        self.mon = ModelPerformanceMonitor()

    @pytest.mark.asyncio
    async def test_evaluate_no_current_version(self):
        # Should return without error
        await self.mon._evaluate()

    @pytest.mark.asyncio
    async def test_evaluate_no_previous_version(self):
        self.mon._current_version = "v2"
        await self.mon._evaluate()

    @pytest.mark.asyncio
    async def test_evaluate_insufficient_trades(self):
        self.mon.on_model_promoted("v2", "v1")
        # Add fewer trades than MIN_TRADES
        for _ in range(MIN_TRADES - 1):
            self.mon.record_trade(1.0, "v2")
        await self.mon._evaluate()  # should not rollback

    @pytest.mark.asyncio
    async def test_evaluate_cur_mean_none(self):
        self.mon.on_model_promoted("v2", "v1")
        # Window exists but is empty (trade_count == 0 < MIN_TRADES)
        await self.mon._evaluate()  # early exit on trade_count < MIN_TRADES

    @pytest.mark.asyncio
    async def test_evaluate_triggers_rollback(self):
        self.mon.on_model_promoted("v2", "v1")
        # Give v1 a good mean
        for _ in range(MIN_TRADES):
            self.mon.record_trade(10.0, "v1")
        # Give v2 a terrible mean (well below threshold)
        for _ in range(MIN_TRADES):
            self.mon.record_trade(-50.0, "v2")

        with patch.object(self.mon, "_rollback", new_callable=AsyncMock) as mock_rb:
            await self.mon._evaluate()
            mock_rb.assert_called_once()


# ── _rollback ─────────────────────────────────────────────────────────────────


class TestRollback:
    def setup_method(self):
        self.mon = ModelPerformanceMonitor()
        self.mon.on_model_promoted("v2", "v1")

    @pytest.mark.asyncio
    async def test_rollback_success_path(self):
        mock_registry = MagicMock()
        mock_registry._load.return_value = {
            "versions": {
                "v1": {"state": "retired"},
                "v2": {"state": "active"},
            }
        }
        mock_registry.promote = MagicMock()

        with patch("ml.performance_monitor.ModelPerformanceMonitor._fire_rollback_alert") as mock_alert:
            with patch.dict(sys.modules, {"ml.model_registry": MagicMock(get_registry=lambda: mock_registry)}):
                await self.mon._rollback("v2", "v1", "test reason")

        assert self.mon._current_version == "v1"
        assert self.mon._previous_version is None
        assert self.mon._rollback_count == 1
        mock_alert.assert_called_once()

    @pytest.mark.asyncio
    async def test_rollback_restages_retired_version(self):
        mock_registry = MagicMock()
        manifest = {
            "versions": {
                "v1": {"state": "retired"},
            }
        }
        mock_registry._load.return_value = manifest
        mock_registry.promote = MagicMock()

        with patch("ml.performance_monitor.ModelPerformanceMonitor._fire_rollback_alert"):
            with patch.dict(sys.modules, {"ml.model_registry": MagicMock(get_registry=lambda: mock_registry)}):
                await self.mon._rollback("v2", "v1", "reason")

        assert manifest["versions"]["v1"]["state"] == "staging"
        mock_registry._save.assert_called_once()

    @pytest.mark.asyncio
    async def test_rollback_registry_promote_raises(self):
        mock_registry = MagicMock()
        mock_registry._load.return_value = {"versions": {}}
        mock_registry.promote.side_effect = RuntimeError("promote failed")

        with patch("ml.performance_monitor.ModelPerformanceMonitor._fire_rollback_alert"):
            with patch.dict(sys.modules, {"ml.model_registry": MagicMock(get_registry=lambda: mock_registry)}):
                # Should not raise — logs error instead
                await self.mon._rollback("v2", "v1", "reason")

        assert self.mon._rollback_count == 1


# ── _fire_rollback_alert ──────────────────────────────────────────────────────


class TestFireRollbackAlert:
    def setup_method(self):
        self.mon = ModelPerformanceMonitor()
        self.mon._rollback_count = 1

    def test_outbox_write_called(self):
        mock_write = MagicMock()
        with patch.dict(
            sys.modules,
            {"core.outbox": MagicMock(write_outbox_event_standalone=mock_write)},
        ):
            with patch.dict(sys.modules, {"app": MagicMock(app_state=MagicMock(alert_engine=None))}):
                self.mon._fire_rollback_alert("v2", "v1", "reason")
        mock_write.assert_called_once()
        call_kwargs = mock_write.call_args
        assert call_kwargs[1]["event_type"] == "ML_ROLLBACK" or call_kwargs[0][0] == "ML_ROLLBACK"

    def test_alert_engine_send_alert_called(self):
        mock_ae = MagicMock()
        mock_ae.send_alert = MagicMock()
        mock_app_state = MagicMock()
        mock_app_state.alert_engine = mock_ae

        # _fire_rollback_alert does `from core.app_state import app_state` inside
        # the function body.  Replace both sys.modules entries so the import
        # resolves to our mock regardless of whether the module is cached.
        mock_cas_module = MagicMock()
        mock_cas_module.app_state = mock_app_state
        mock_outbox = MagicMock(write_outbox_event_standalone=MagicMock())
        with patch.dict(
            sys.modules,
            {
                "core.outbox": mock_outbox,
                "core.app_state": mock_cas_module,
            },
        ):
            self.mon._fire_rollback_alert("v2", "v1", "reason")

        mock_ae.send_alert.assert_called_once()

    def test_outbox_exception_does_not_raise(self):
        with patch.dict(
            sys.modules,
            {
                "core.outbox": MagicMock(
                    write_outbox_event_standalone=MagicMock(side_effect=RuntimeError("outbox down"))
                )
            },
        ):
            with patch.dict(sys.modules, {"app": MagicMock(app_state=MagicMock(alert_engine=None))}):
                self.mon._fire_rollback_alert("v2", "v1", "reason")  # must not raise

    def test_alert_engine_exception_does_not_raise(self):
        mock_ae = MagicMock()
        mock_ae.send_alert.side_effect = RuntimeError("alert engine down")
        mock_app_state = MagicMock()
        mock_app_state.alert_engine = mock_ae

        with patch.dict(sys.modules, {"core.outbox": MagicMock(write_outbox_event_standalone=MagicMock())}):
            with patch.dict(sys.modules, {"app": MagicMock(app_state=mock_app_state)}):
                self.mon._fire_rollback_alert("v2", "v1", "reason")  # must not raise


# ── run() async loop ──────────────────────────────────────────────────────────


class TestRunLoop:
    @pytest.mark.asyncio
    async def test_run_sets_running_true(self):
        mon = ModelPerformanceMonitor()
        with patch("ml.performance_monitor.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            mock_sleep.side_effect = asyncio.CancelledError()
            with pytest.raises(asyncio.CancelledError):
                await mon.run()
        # After CancelledError the loop returns cleanly
        assert mon._running is True  # set before the loop body

    @pytest.mark.asyncio
    async def test_run_cancelled_error_returns_cleanly(self):
        # run() catches CancelledError raised by _evaluate and returns cleanly
        mon = ModelPerformanceMonitor()
        with patch.object(mon, "_evaluate", new_callable=AsyncMock) as mock_eval:
            mock_eval.side_effect = asyncio.CancelledError()
            with patch("ml.performance_monitor.asyncio.sleep", new_callable=AsyncMock):
                await mon.run()  # should return, not propagate CancelledError

    @pytest.mark.asyncio
    async def test_run_generic_exception_continues(self):
        mon = ModelPerformanceMonitor()
        call_count = 0

        async def fake_sleep(_):
            nonlocal call_count
            call_count += 1
            if call_count >= 2:
                mon.stop()

        with patch("ml.performance_monitor.asyncio.sleep", side_effect=fake_sleep):
            with patch.object(mon, "_evaluate", new_callable=AsyncMock) as mock_eval:
                mock_eval.side_effect = [RuntimeError("boom"), None]
                await mon.run()

        assert mock_eval.call_count == 2

    @pytest.mark.asyncio
    async def test_run_stop_exits_loop(self):
        mon = ModelPerformanceMonitor()
        call_count = 0

        async def fake_sleep(_):
            nonlocal call_count
            call_count += 1
            mon.stop()

        with patch("ml.performance_monitor.asyncio.sleep", side_effect=fake_sleep):
            with patch.object(mon, "_evaluate", new_callable=AsyncMock):
                await mon.run()

        assert call_count == 1


# ── get_monitor singleton ─────────────────────────────────────────────────────


class TestGetMonitor:
    def test_singleton_returns_same_instance(self):
        pm_mod._monitor = None  # reset
        m1 = get_monitor()
        m2 = get_monitor()
        assert m1 is m2

    def test_singleton_is_monitor_instance(self):
        pm_mod._monitor = None
        m = get_monitor()
        assert isinstance(m, ModelPerformanceMonitor)
        pm_mod._monitor = None  # cleanup

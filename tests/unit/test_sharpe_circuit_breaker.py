# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# AGPL-3.0 — Share all modifications
"""
Unit tests for ml/sharpe_circuit_breaker.py.

Covers every branch in CircuitState, SharpeCircuitBreaker, and the
module-level singleton so the 13.8% coverage gap is closed.
"""

from __future__ import annotations

import asyncio
import math
import time
from unittest.mock import MagicMock, patch

import pytest

# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_state(model_version: str = "v1", window: int = 50, min_trades: int = 20):
    """Return a fresh CircuitState with patched module-level constants."""
    from ml.sharpe_circuit_breaker import CircuitState
    import collections

    state = CircuitState(model_version=model_version)
    # Override deque maxlen to match the patched WINDOW_TRADES
    state.pnl_window = collections.deque(maxlen=window)
    return state


# ── CircuitState.record ───────────────────────────────────────────────────────


class TestCircuitStateRecord:
    def test_record_increments_total_trades(self):
        from ml.sharpe_circuit_breaker import CircuitState

        s = CircuitState(model_version="v1")
        s.record(10.0)
        s.record(-5.0)
        assert s.total_trades == 2

    def test_record_appends_to_window(self):
        from ml.sharpe_circuit_breaker import CircuitState

        s = CircuitState(model_version="v1")
        s.record(3.0)
        assert list(s.pnl_window) == [3.0]


# ── CircuitState.rolling_sharpe ───────────────────────────────────────────────


class TestRollingSharpeBranches:
    """Exercise every branch in rolling_sharpe()."""

    def _fill(self, state, values):
        for v in values:
            state.pnl_window.append(v)

    def test_returns_none_when_insufficient_trades(self):
        import ml.sharpe_circuit_breaker as scb

        with patch.object(scb, "MIN_TRADES", 20):
            from ml.sharpe_circuit_breaker import CircuitState

            s = CircuitState(model_version="v1")
            self._fill(s, [1.0] * 5)
            assert s.rolling_sharpe() is None

    def test_returns_float_when_enough_trades(self):
        import ml.sharpe_circuit_breaker as scb

        with patch.object(scb, "MIN_TRADES", 5):
            from ml.sharpe_circuit_breaker import CircuitState

            s = CircuitState(model_version="v1")
            self._fill(s, [1.0, 2.0, 3.0, 4.0, 5.0])
            result = s.rolling_sharpe()
            assert isinstance(result, float)

    def test_zero_std_positive_mean_returns_large_positive(self):
        import ml.sharpe_circuit_breaker as scb

        with patch.object(scb, "MIN_TRADES", 3), patch.object(scb, "ANNUALISE_FACTOR", math.sqrt(252)):
            from ml.sharpe_circuit_breaker import CircuitState

            s = CircuitState(model_version="v1")
            self._fill(s, [5.0, 5.0, 5.0])
            result = s.rolling_sharpe()
            assert result > 0
            assert result > 1000  # large positive

    def test_zero_std_negative_mean_returns_large_negative(self):
        import ml.sharpe_circuit_breaker as scb

        with patch.object(scb, "MIN_TRADES", 3), patch.object(scb, "ANNUALISE_FACTOR", math.sqrt(252)):
            from ml.sharpe_circuit_breaker import CircuitState

            s = CircuitState(model_version="v1")
            self._fill(s, [-5.0, -5.0, -5.0])
            result = s.rolling_sharpe()
            assert result < -1000  # large negative

    def test_zero_std_zero_mean_returns_zero(self):
        import ml.sharpe_circuit_breaker as scb

        with patch.object(scb, "MIN_TRADES", 3):
            from ml.sharpe_circuit_breaker import CircuitState

            s = CircuitState(model_version="v1")
            self._fill(s, [0.0, 0.0, 0.0])
            result = s.rolling_sharpe()
            assert result == 0.0

    def test_normal_sharpe_calculation(self):
        import ml.sharpe_circuit_breaker as scb
        import numpy as np

        with patch.object(scb, "MIN_TRADES", 5), patch.object(scb, "ANNUALISE_FACTOR", 1.0):
            from ml.sharpe_circuit_breaker import CircuitState

            s = CircuitState(model_version="v1")
            values = [1.0, 2.0, 3.0, 4.0, 5.0]
            self._fill(s, values)
            arr = np.array(values)
            expected = arr.mean() / arr.std()
            result = s.rolling_sharpe()
            assert abs(result - expected) < 1e-9


# ── SharpeCircuitBreaker public API ───────────────────────────────────────────


class TestSharpeCircuitBreakerAPI:
    def _make_cb(self):
        import ml.sharpe_circuit_breaker as scb

        # Reset singleton so tests are isolated
        scb._sharpe_cb = None
        from ml.sharpe_circuit_breaker import SharpeCircuitBreaker

        return SharpeCircuitBreaker()

    def test_record_trade_creates_state(self):
        cb = self._make_cb()
        cb.record_trade(10.0, "model_a")
        assert "model_a" in cb._states
        assert cb._states["model_a"].total_trades == 1

    def test_record_trade_multiple_versions(self):
        cb = self._make_cb()
        cb.record_trade(1.0, "v1")
        cb.record_trade(2.0, "v2")
        assert "v1" in cb._states
        assert "v2" in cb._states

    def test_is_open_returns_false_for_unknown_version(self):
        cb = self._make_cb()
        assert cb.is_open("nonexistent") is False

    def test_is_open_returns_false_when_circuit_closed(self):
        cb = self._make_cb()
        cb.record_trade(1.0, "v1")
        assert cb.is_open("v1") is False

    def test_is_open_returns_true_when_circuit_open(self):
        cb = self._make_cb()
        cb.record_trade(1.0, "v1")
        cb._states["v1"].is_open = True
        cb._states["v1"].opened_at = time.monotonic()
        assert cb.is_open("v1") is True

    def test_auto_reset_after_elapsed_time(self):
        import ml.sharpe_circuit_breaker as scb

        cb = self._make_cb()
        cb.record_trade(1.0, "v1")
        state = cb._states["v1"]
        state.is_open = True
        # Set opened_at far in the past
        state.opened_at = time.monotonic() - 9999

        with patch.object(scb, "RESET_AFTER_S", 1.0):
            result = cb.is_open("v1")

        assert result is False
        assert state.is_open is False
        assert state.opened_at is None
        assert state.consecutive_bad_windows == 0

    def test_no_auto_reset_when_reset_after_zero(self):
        import ml.sharpe_circuit_breaker as scb

        cb = self._make_cb()
        cb.record_trade(1.0, "v1")
        state = cb._states["v1"]
        state.is_open = True
        state.opened_at = time.monotonic() - 9999

        with patch.object(scb, "RESET_AFTER_S", 0.0):
            result = cb.is_open("v1")

        assert result is True  # no auto-reset

    def test_reset_clears_circuit(self):
        cb = self._make_cb()
        cb.record_trade(1.0, "v1")
        state = cb._states["v1"]
        state.is_open = True
        state.opened_at = time.monotonic()
        state.consecutive_bad_windows = 5
        state.trip_reason = "bad"

        cb.reset("v1")

        assert state.is_open is False
        assert state.opened_at is None
        assert state.consecutive_bad_windows == 0
        assert state.trip_reason == ""

    def test_reset_noop_for_unknown_version(self):
        cb = self._make_cb()
        cb.reset("nonexistent")  # must not raise

    def test_get_status_empty(self):
        cb = self._make_cb()
        assert cb.get_status() == {}

    def test_get_status_includes_all_fields(self):
        cb = self._make_cb()
        cb.record_trade(5.0, "v1")
        status = cb.get_status()
        assert "v1" in status
        entry = status["v1"]
        assert "is_open" in entry
        assert "last_sharpe" in entry
        assert "consecutive_bad_windows" in entry
        assert "total_trades" in entry
        assert "window_trades" in entry
        assert "trip_reason" in entry
        assert "opened_at" in entry
        assert "last_evaluated_at" in entry
        assert "sharpe_history" in entry

    def test_get_status_opened_at_iso_format(self):
        cb = self._make_cb()
        cb.record_trade(1.0, "v1")
        cb._states["v1"].is_open = True
        cb._states["v1"].opened_at = time.monotonic()
        status = cb.get_status()
        # opened_at should be an ISO string when set
        assert status["v1"]["opened_at"] is not None

    def test_stop_sets_running_false(self):
        cb = self._make_cb()
        cb._running = True
        cb.stop()
        assert cb._running is False


# ── SharpeCircuitBreaker._evaluate_one ───────────────────────────────────────


class TestEvaluateOne:
    """Async tests for the evaluation loop internals."""

    def _make_cb(self):
        import ml.sharpe_circuit_breaker as scb

        scb._sharpe_cb = None
        from ml.sharpe_circuit_breaker import SharpeCircuitBreaker

        return SharpeCircuitBreaker()

    @pytest.mark.asyncio
    async def test_evaluate_one_insufficient_trades_skips(self):
        import ml.sharpe_circuit_breaker as scb

        cb = self._make_cb()
        cb.record_trade(1.0, "v1")
        state = cb._states["v1"]

        with patch.object(scb, "MIN_TRADES", 100):
            await cb._evaluate_one(state)

        assert state.last_sharpe is None
        assert state.consecutive_bad_windows == 0

    @pytest.mark.asyncio
    async def test_evaluate_one_good_sharpe_resets_counter(self):
        import ml.sharpe_circuit_breaker as scb

        cb = self._make_cb()
        # Fill with positive PnL so Sharpe > MIN_SHARPE
        for _ in range(25):
            cb.record_trade(10.0, "v1")
        state = cb._states["v1"]
        state.consecutive_bad_windows = 2

        with patch.object(scb, "MIN_TRADES", 20), patch.object(scb, "MIN_SHARPE", 0.0):
            await cb._evaluate_one(state)

        assert state.consecutive_bad_windows == 0

    @pytest.mark.asyncio
    async def test_evaluate_one_bad_sharpe_increments_counter(self):
        import ml.sharpe_circuit_breaker as scb

        cb = self._make_cb()
        # Fill with negative PnL so Sharpe < 0
        for _ in range(25):
            cb.record_trade(-10.0, "v1")
        state = cb._states["v1"]

        with (
            patch.object(scb, "MIN_TRADES", 20),
            patch.object(scb, "MIN_SHARPE", 1.0),
            patch.object(scb, "CONSECUTIVE_WINDOWS", 5),
        ):
            await cb._evaluate_one(state)

        assert state.consecutive_bad_windows == 1
        assert not state.is_open  # not yet tripped

    @pytest.mark.asyncio
    async def test_evaluate_one_trips_after_consecutive_windows(self):
        import ml.sharpe_circuit_breaker as scb

        cb = self._make_cb()
        for _ in range(25):
            cb.record_trade(-10.0, "v1")
        state = cb._states["v1"]
        state.consecutive_bad_windows = 2  # one more will trip

        with (
            patch.object(scb, "MIN_TRADES", 20),
            patch.object(scb, "MIN_SHARPE", 1.0),
            patch.object(scb, "CONSECUTIVE_WINDOWS", 3),
            patch.object(cb, "_fire_trip_event", return_value=None),
            patch.object(cb, "_retire_model", return_value=None),
        ):
            await cb._evaluate_one(state)

        assert state.is_open is True
        assert state.opened_at is not None

    @pytest.mark.asyncio
    async def test_evaluate_one_does_not_re_trip_open_circuit(self):
        import ml.sharpe_circuit_breaker as scb

        cb = self._make_cb()
        for _ in range(25):
            cb.record_trade(-10.0, "v1")
        state = cb._states["v1"]
        state.is_open = True  # already open
        state.consecutive_bad_windows = 10

        with (
            patch.object(scb, "MIN_TRADES", 20),
            patch.object(scb, "MIN_SHARPE", 1.0),
            patch.object(scb, "CONSECUTIVE_WINDOWS", 3),
            patch.object(cb, "_trip") as mock_trip,
        ):
            await cb._evaluate_one(state)

        mock_trip.assert_not_called()


# ── SharpeCircuitBreaker._trip ────────────────────────────────────────────────


class TestTrip:
    def _make_cb(self):
        import ml.sharpe_circuit_breaker as scb

        scb._sharpe_cb = None
        from ml.sharpe_circuit_breaker import SharpeCircuitBreaker

        return SharpeCircuitBreaker()

    @pytest.mark.asyncio
    async def test_trip_sets_state_open(self):
        cb = self._make_cb()
        cb.record_trade(-1.0, "v1")
        state = cb._states["v1"]

        with patch.object(cb, "_fire_trip_event"), patch.object(cb, "_retire_model", return_value=None):
            await cb._trip(state, -5.0)

        assert state.is_open is True
        assert state.opened_at is not None
        assert "Rolling Sharpe" in state.trip_reason

    @pytest.mark.asyncio
    async def test_trip_calls_fire_and_retire(self):
        cb = self._make_cb()
        cb.record_trade(-1.0, "v1")
        state = cb._states["v1"]

        with (
            patch.object(cb, "_fire_trip_event") as mock_fire,
            patch.object(cb, "_retire_model", return_value=None) as mock_retire,
        ):
            await cb._trip(state, -2.0)

        mock_fire.assert_called_once_with(state)
        mock_retire.assert_called_once()


# ── _fire_trip_event ──────────────────────────────────────────────────────────


class TestFireTripEvent:
    def _make_cb(self):
        import ml.sharpe_circuit_breaker as scb

        scb._sharpe_cb = None
        from ml.sharpe_circuit_breaker import SharpeCircuitBreaker

        return SharpeCircuitBreaker()

    def test_fire_trip_event_handles_outbox_import_error(self):
        """Should not raise even when core.outbox is unavailable."""
        cb = self._make_cb()
        cb.record_trade(-1.0, "v1")
        state = cb._states["v1"]
        state.last_sharpe = -2.0
        state.trip_reason = "test"

        with patch.dict("sys.modules", {"core.outbox": None}):
            cb._fire_trip_event(state)  # must not raise

    def test_fire_trip_event_handles_alert_engine_error(self):
        """Should not raise when app_state.alert_engine raises."""
        cb = self._make_cb()
        cb.record_trade(-1.0, "v1")
        state = cb._states["v1"]
        state.last_sharpe = -2.0
        state.trip_reason = "test"

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
            cb._fire_trip_event(state)  # must not raise

    def test_fire_trip_event_calls_alert_engine_when_available(self):
        cb = self._make_cb()
        cb.record_trade(-1.0, "v1")
        state = cb._states["v1"]
        state.last_sharpe = -2.0
        state.trip_reason = "test"

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
            cb._fire_trip_event(state)

        mock_ae.send_alert.assert_called_once()


# ── _retire_model ─────────────────────────────────────────────────────────────


class TestRetireModel:
    def _make_cb(self):
        import ml.sharpe_circuit_breaker as scb

        scb._sharpe_cb = None
        from ml.sharpe_circuit_breaker import SharpeCircuitBreaker

        return SharpeCircuitBreaker()

    @pytest.mark.asyncio
    async def test_retire_model_sets_state_retired(self):
        cb = self._make_cb()

        mock_registry = MagicMock()
        mock_registry._load.return_value = {"versions": {"v1": {"state": "production"}}}
        mock_get_registry = MagicMock(return_value=mock_registry)

        with patch.dict("sys.modules", {"ml.model_registry": MagicMock(get_registry=mock_get_registry)}):
            await cb._retire_model("v1", "bad sharpe")

        mock_registry._save.assert_called_once()
        saved_manifest = mock_registry._save.call_args[0][0]
        assert saved_manifest["versions"]["v1"]["state"] == "retired"

    @pytest.mark.asyncio
    async def test_retire_model_skips_non_production(self):
        cb = self._make_cb()

        mock_registry = MagicMock()
        mock_registry._load.return_value = {"versions": {"v1": {"state": "staging"}}}
        mock_get_registry = MagicMock(return_value=mock_registry)

        with patch.dict("sys.modules", {"ml.model_registry": MagicMock(get_registry=mock_get_registry)}):
            await cb._retire_model("v1", "bad sharpe")

        mock_registry._save.assert_not_called()

    @pytest.mark.asyncio
    async def test_retire_model_handles_import_error(self):
        cb = self._make_cb()
        # Simulate ml.model_registry not importable
        with patch.dict("sys.modules", {"ml.model_registry": None}):
            await cb._retire_model("v1", "bad sharpe")  # must not raise


# ── run() loop ────────────────────────────────────────────────────────────────


class TestRunLoop:
    def _make_cb(self):
        import ml.sharpe_circuit_breaker as scb

        scb._sharpe_cb = None
        from ml.sharpe_circuit_breaker import SharpeCircuitBreaker

        return SharpeCircuitBreaker()

    @pytest.mark.asyncio
    async def test_run_stops_on_cancel(self):
        import ml.sharpe_circuit_breaker as scb

        cb = self._make_cb()

        # _evaluate_all raises CancelledError on first call, simulating task cancellation
        async def cancel_on_eval():
            raise asyncio.CancelledError()

        with patch.object(cb, "_evaluate_all", side_effect=cancel_on_eval), patch.object(scb, "EVAL_INTERVAL_S", 0.001):
            await cb.run()

        # run() returns cleanly after CancelledError
        assert cb._running is True  # run() doesn't set _running=False on cancel

    @pytest.mark.asyncio
    async def test_run_handles_evaluation_exception(self):
        import ml.sharpe_circuit_breaker as scb

        cb = self._make_cb()
        call_count = 0

        async def boom():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise ValueError("evaluation error")
            # Second call: cancel to exit the loop
            raise asyncio.CancelledError()

        # asyncio.sleep must be a coroutine that returns immediately
        async def fast_sleep(_):
            return

        with (
            patch.object(cb, "_evaluate_all", side_effect=boom),
            patch("asyncio.sleep", side_effect=fast_sleep),
            patch.object(scb, "EVAL_INTERVAL_S", 0.001),
        ):
            await cb.run()

        assert call_count >= 1


# ── _evaluate_all ─────────────────────────────────────────────────────────────


class TestEvaluateAll:
    def _make_cb(self):
        import ml.sharpe_circuit_breaker as scb

        scb._sharpe_cb = None
        from ml.sharpe_circuit_breaker import SharpeCircuitBreaker

        return SharpeCircuitBreaker()

    @pytest.mark.asyncio
    async def test_evaluate_all_calls_evaluate_one_for_each_version(self):
        cb = self._make_cb()
        cb.record_trade(1.0, "v1")
        cb.record_trade(2.0, "v2")

        called = []

        async def mock_eval_one(state):
            called.append(state.model_version)

        with patch.object(cb, "_evaluate_one", side_effect=mock_eval_one):
            await cb._evaluate_all()

        # Redis-backed state can preload additional model versions; ensure the
        # versions created in this test are always evaluated.
        assert {"v1", "v2"}.issubset(set(called))


# ── Singleton ─────────────────────────────────────────────────────────────────


class TestSingleton:
    def test_get_sharpe_cb_returns_same_instance(self):
        import ml.sharpe_circuit_breaker as scb

        scb._sharpe_cb = None  # reset
        from ml.sharpe_circuit_breaker import get_sharpe_cb

        a = get_sharpe_cb()
        b = get_sharpe_cb()
        assert a is b

    def test_get_sharpe_cb_creates_instance_on_first_call(self):
        import ml.sharpe_circuit_breaker as scb

        scb._sharpe_cb = None
        from ml.sharpe_circuit_breaker import get_sharpe_cb, SharpeCircuitBreaker

        cb = get_sharpe_cb()
        assert isinstance(cb, SharpeCircuitBreaker)

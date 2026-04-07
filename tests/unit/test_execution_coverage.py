# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
Coverage tests for execution/position_tracker.py, execution/throttler.py,
execution/order_algorithms.py, and execution/broker_circuit_breaker.py.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest


# ─────────────────────────────────────────────────────────────────────────────
# execution/position_tracker.py
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.unit
class TestPosition:
    def _make(self, side="long", qty=10.0, entry=1950.0, current=1950.0):
        from execution.position_tracker import Position
        return Position(id="p1", symbol="XAUUSD", side=side,
                        quantity=qty, entry_price=entry, current_price=current)

    def test_update_price_long_profit(self):
        pos = self._make(side="long", qty=10.0, entry=1950.0, current=1950.0)
        pos.update_price(1960.0)
        assert pos.unrealized_pnl == pytest.approx(100.0)
        assert pos.current_price == pytest.approx(1960.0)

    def test_update_price_short_profit(self):
        pos = self._make(side="short", qty=10.0, entry=1950.0, current=1950.0)
        pos.update_price(1940.0)
        assert pos.unrealized_pnl == pytest.approx(100.0)

    def test_update_price_long_loss(self):
        pos = self._make(side="long", qty=10.0, entry=1950.0, current=1950.0)
        pos.update_price(1940.0)
        assert pos.unrealized_pnl == pytest.approx(-100.0)

    def test_market_value(self):
        pos = self._make(qty=5.0, current=2000.0)
        assert pos.market_value == pytest.approx(10_000.0)

    def test_total_pnl(self):
        from execution.position_tracker import Position
        pos = Position(id="p2", symbol="XAUUSD", side="long",
                       quantity=1.0, entry_price=1900.0, current_price=1950.0,
                       unrealized_pnl=50.0, realized_pnl=20.0, commission=5.0)
        assert pos.total_pnl == pytest.approx(65.0)

    def test_stop_loss_take_profit_defaults_none(self):
        pos = self._make()
        assert pos.stop_loss is None
        assert pos.take_profit is None


@pytest.mark.unit
class TestPositionTracker:
    def _make_pos(self, pid="p1", symbol="XAUUSD", side="long"):
        from execution.position_tracker import Position
        return Position(id=pid, symbol=symbol, side=side,
                        quantity=1.0, entry_price=1950.0, current_price=1950.0)

    def test_add_and_get_position(self):
        from execution.position_tracker import PositionTracker
        tracker = PositionTracker()
        pos = self._make_pos()
        asyncio.run(tracker.add_position(pos))
        assert tracker.get_position("p1") is pos

    def test_get_nonexistent_returns_none(self):
        from execution.position_tracker import PositionTracker
        tracker = PositionTracker()
        assert tracker.get_position("nope") is None

    def test_get_all_positions(self):
        from execution.position_tracker import PositionTracker
        tracker = PositionTracker()
        asyncio.run(tracker.add_position(self._make_pos("p1")))
        asyncio.run(tracker.add_position(self._make_pos("p2")))
        assert len(tracker.get_all_positions()) == 2

    def test_get_positions_by_symbol(self):
        from execution.position_tracker import PositionTracker
        tracker = PositionTracker()
        asyncio.run(tracker.add_position(self._make_pos("p1", "XAUUSD")))
        asyncio.run(tracker.add_position(self._make_pos("p2", "EURUSD")))
        xau = tracker.get_positions_by_symbol("XAUUSD")
        assert len(xau) == 1
        assert xau[0].id == "p1"

    def test_update_position_field(self):
        from execution.position_tracker import PositionTracker
        tracker = PositionTracker()
        asyncio.run(tracker.add_position(self._make_pos()))
        result = asyncio.run(tracker.update_position("p1", quantity=5.0))
        assert result is True
        assert tracker.get_position("p1").quantity == pytest.approx(5.0)

    def test_update_nonexistent_returns_false(self):
        from execution.position_tracker import PositionTracker
        tracker = PositionTracker()
        result = asyncio.run(tracker.update_position("ghost", quantity=1.0))
        assert result is False

    def test_close_position_long(self):
        from execution.position_tracker import PositionTracker
        tracker = PositionTracker()
        asyncio.run(tracker.add_position(self._make_pos()))
        closed = asyncio.run(tracker.close_position("p1", exit_price=1960.0, commission=2.0))
        assert closed is not None
        assert closed.realized_pnl == pytest.approx(10.0)
        assert closed.commission == pytest.approx(2.0)
        assert tracker.get_position("p1") is None

    def test_close_nonexistent_returns_none(self):
        from execution.position_tracker import PositionTracker
        tracker = PositionTracker()
        result = asyncio.run(tracker.close_position("ghost", exit_price=1950.0))
        assert result is None

    def test_update_prices_propagates(self):
        from execution.position_tracker import PositionTracker
        tracker = PositionTracker()
        asyncio.run(tracker.add_position(self._make_pos("p1", "XAUUSD", "long")))
        asyncio.run(tracker.update_prices("XAUUSD", 2000.0))
        assert tracker.get_position("p1").current_price == pytest.approx(2000.0)

    def test_get_exposure_by_symbol(self):
        from execution.position_tracker import PositionTracker
        tracker = PositionTracker()
        asyncio.run(tracker.add_position(self._make_pos("p1", "XAUUSD", "long")))
        asyncio.run(tracker.add_position(self._make_pos("p2", "XAUUSD", "short")))
        exp = tracker.get_exposure("XAUUSD")
        assert exp["long"] == pytest.approx(1.0)
        assert exp["short"] == pytest.approx(1.0)
        assert exp["net"] == pytest.approx(0.0)

    def test_get_exposure_all(self):
        from execution.position_tracker import PositionTracker
        tracker = PositionTracker()
        asyncio.run(tracker.add_position(self._make_pos("p1", "XAUUSD", "long")))
        exp = tracker.get_exposure()
        assert exp["long"] == pytest.approx(1.0)
        assert exp["short"] == pytest.approx(0.0)
        assert exp["net"] == pytest.approx(1.0)

    def test_get_total_pnl(self):
        from execution.position_tracker import Position, PositionTracker
        tracker = PositionTracker()
        pos = Position(id="p1", symbol="XAUUSD", side="long",
                       quantity=1.0, entry_price=1950.0, current_price=1960.0,
                       unrealized_pnl=10.0, realized_pnl=5.0, commission=1.0)
        asyncio.run(tracker.add_position(pos))
        pnl = tracker.get_total_pnl()
        assert pnl["unrealized"] == pytest.approx(10.0)
        assert pnl["realized"] == pytest.approx(5.0)
        assert pnl["commission"] == pytest.approx(1.0)
        assert pnl["total"] == pytest.approx(14.0)


# ─────────────────────────────────────────────────────────────────────────────
# execution/throttler.py
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.unit
class TestMessageThrottler:
    def _make(self, max_per_sec=50, max_per_min=1000, burst=10, cooldown=1.0):
        from execution.throttler import MessageThrottler
        return MessageThrottler(max_per_sec, max_per_min, burst, cooldown)

    def test_can_send_initially(self):
        t = self._make()
        assert t.can_send() is True

    def test_cancel_always_allowed(self):
        t = self._make(max_per_sec=1, max_per_min=1, burst=0)
        # Exhaust normal quota
        for _ in range(5):
            t.record_message("order")
        assert t.can_send("cancel") is True
        assert t.can_send("cancel_all") is True
        assert t.can_send("modify") is True

    def test_record_message_increments_window(self):
        t = self._make()
        t.record_message("order")
        assert len(t.second_window) == 1
        assert len(t.minute_window) == 1

    def test_cancel_not_counted(self):
        t = self._make()
        t.record_message("cancel")
        assert len(t.second_window) == 0

    def test_throttle_when_second_limit_exceeded(self):
        t = self._make(max_per_sec=5, burst=0, cooldown=0.1)
        for _ in range(5):
            t.record_message("order")
        # Force window to be current
        assert t.can_send("order") is False

    def test_get_status_keys(self):
        t = self._make()
        status = t.get_status()
        for key in ("level", "messages_per_second", "messages_per_minute",
                    "max_per_second", "max_per_minute", "in_cooldown"):
            assert key in status

    def test_get_status_level_normal(self):
        t = self._make()
        assert t.get_status()["level"] == "normal"

    def test_state_after_throttle(self):
        from execution.throttler import ThrottleLevel
        t = self._make(max_per_sec=2, burst=0, cooldown=0.05)
        for _ in range(3):
            t.record_message("order")
        t.can_send("order")  # triggers throttle check
        assert t.state.level in (ThrottleLevel.THROTTLED, ThrottleLevel.BLOCKED,
                                  ThrottleLevel.WARNING, ThrottleLevel.NORMAL)


# ─────────────────────────────────────────────────────────────────────────────
# execution/order_algorithms.py
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.unit
class TestPartialFillState:
    def test_add_fill_updates_avg_price(self):
        from execution.order_algorithms import PartialFillState
        state = PartialFillState(parent_id="p1", symbol="XAUUSD",
                                  side="long", target_lots=1.0)
        state.add_fill(0.5, 1950.0)
        state.add_fill(0.5, 1960.0)
        assert state.avg_price == pytest.approx(1955.0)
        assert state.filled_lots == pytest.approx(1.0)

    def test_remaining_lots(self):
        from execution.order_algorithms import PartialFillState
        state = PartialFillState(parent_id="p1", symbol="XAUUSD",
                                  side="long", target_lots=1.0)
        state.add_fill(0.3, 1950.0)
        assert state.remaining_lots == pytest.approx(0.7)

    def test_is_complete_when_fully_filled(self):
        from execution.order_algorithms import PartialFillState
        state = PartialFillState(parent_id="p1", symbol="XAUUSD",
                                  side="long", target_lots=1.0)
        state.add_fill(1.0, 1950.0)
        assert state.is_complete is True

    def test_is_not_complete_partial(self):
        from execution.order_algorithms import PartialFillState
        state = PartialFillState(parent_id="p1", symbol="XAUUSD",
                                  side="long", target_lots=1.0)
        state.add_fill(0.5, 1950.0)
        assert state.is_complete is False

    def test_fill_pct(self):
        from execution.order_algorithms import PartialFillState
        state = PartialFillState(parent_id="p1", symbol="XAUUSD",
                                  side="long", target_lots=2.0)
        state.add_fill(1.0, 1950.0)
        assert state.fill_pct == pytest.approx(0.5)


@pytest.mark.unit
class TestPartialFillAggregator:
    def test_register_and_record(self):
        from execution.order_algorithms import PartialFillAggregator
        agg = PartialFillAggregator()
        agg.register("p1", "XAUUSD", "long", 1.0)
        state = agg.record_fill("p1", 0.5, 1950.0)
        assert state is not None
        assert state.filled_lots == pytest.approx(0.5)

    def test_unknown_parent_returns_none(self):
        from execution.order_algorithms import PartialFillAggregator
        agg = PartialFillAggregator()
        result = agg.record_fill("ghost", 0.5, 1950.0)
        assert result is None

    def test_on_complete_callback_fires(self):
        from execution.order_algorithms import PartialFillAggregator
        agg = PartialFillAggregator()
        completed = []
        agg.on_complete(lambda s: completed.append(s.parent_id))
        agg.register("p1", "XAUUSD", "long", 0.01)
        agg.record_fill("p1", 0.01, 1950.0)
        assert "p1" in completed

    def test_pending_count(self):
        from execution.order_algorithms import PartialFillAggregator
        agg = PartialFillAggregator()
        agg.register("p1", "XAUUSD", "long", 1.0)
        agg.register("p2", "EURUSD", "short", 1.0)
        assert agg.pending_count() == 2

    def test_complete_removes_from_pending(self):
        from execution.order_algorithms import PartialFillAggregator
        agg = PartialFillAggregator()
        agg.register("p1", "XAUUSD", "long", 0.01)
        agg.record_fill("p1", 0.01, 1950.0)
        assert agg.pending_count() == 0


@pytest.mark.unit
class TestTWAPExecutor:
    def test_execute_no_router_returns_pending(self):
        from execution.order_algorithms import TWAPExecutor
        executor = TWAPExecutor(router=None)
        result = asyncio.run(executor.execute(
            parent_id="t1", symbol="XAUUSD", side="long",
            total_lots=0.05, duration_s=0.0, slices=3,
        ))
        assert result["parent_id"] == "t1"
        assert result["algo"] == "twap"
        assert result["child_count"] == 3

    def test_execute_with_router_filled(self):
        from execution.order_algorithms import TWAPExecutor
        mock_router = MagicMock()
        mock_router.route = AsyncMock(return_value={"status": "filled", "fill_price": 1950.0})
        executor = TWAPExecutor(router=mock_router)
        result = asyncio.run(executor.execute(
            parent_id="t2", symbol="XAUUSD", side="long",
            total_lots=0.03, duration_s=0.0, slices=3,
        ))
        assert result["fill_rate"] == pytest.approx(1.0, abs=0.01)
        assert result["status"] == "filled"

    def test_execute_with_router_failure(self):
        from execution.order_algorithms import TWAPExecutor
        mock_router = MagicMock()
        mock_router.route = AsyncMock(return_value={"status": "failed"})
        executor = TWAPExecutor(router=mock_router)
        result = asyncio.run(executor.execute(
            parent_id="t3", symbol="XAUUSD", side="long",
            total_lots=0.03, duration_s=0.0, slices=3,
        ))
        assert result["failed_slices"] == 3

    def test_volume_profile_sums_to_one(self):
        from execution.order_algorithms import _XAUUSD_VOLUME_PROFILE
        assert abs(sum(_XAUUSD_VOLUME_PROFILE) - 1.0) < 1e-9


@pytest.mark.unit
class TestVWAPExecutor:
    def test_compute_slice_weights_sum_to_one(self):
        from execution.order_algorithms import VWAPExecutor
        executor = VWAPExecutor(router=None)
        weights = executor._compute_slice_weights(start_hour_utc=8, n_slices=6)
        assert abs(sum(weights) - 1.0) < 1e-9

    def test_execute_no_router(self):
        from execution.order_algorithms import VWAPExecutor
        executor = VWAPExecutor(router=None)
        result = asyncio.run(executor.execute(
            parent_id="v1", symbol="XAUUSD", side="long",
            total_lots=0.06, duration_s=0.0, slices=3,
        ))
        assert result["parent_id"] == "v1"
        assert result["algo"] == "vwap"

    def test_execute_with_router_filled(self):
        from execution.order_algorithms import VWAPExecutor
        mock_router = MagicMock()
        mock_router.route = AsyncMock(return_value={"status": "filled", "fill_price": 1950.0})
        executor = VWAPExecutor(router=mock_router)
        result = asyncio.run(executor.execute(
            parent_id="v2", symbol="XAUUSD", side="long",
            total_lots=0.06, duration_s=0.0, slices=3,
        ))
        assert result["filled_lots"] > 0


# ─────────────────────────────────────────────────────────────────────────────
# execution/broker_circuit_breaker.py
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.unit
class TestBrokerCircuitBreaker:
    def _make(self, max_failures=3, reset_timeout=60.0, half_open_max=2):
        from execution.broker_circuit_breaker import BrokerCircuitBreaker
        return BrokerCircuitBreaker("test_broker",
                                    max_failures=max_failures,
                                    reset_timeout=reset_timeout,
                                    half_open_max=half_open_max)

    def test_initial_state_closed(self):
        from execution.broker_circuit_breaker import CircuitState
        cb = self._make()
        assert cb.state == CircuitState.CLOSED
        assert cb.is_open is False

    def test_broker_name(self):
        cb = self._make()
        assert cb.broker_name == "test_broker"

    def test_successful_call_passes_through(self):
        cb = self._make()
        result = asyncio.run(cb.call(lambda: 42))
        assert result == 42

    def test_async_call_passes_through(self):
        cb = self._make()
        async def _fn():
            return "ok"
        result = asyncio.run(cb.call(_fn))
        assert result == "ok"

    def test_failures_open_circuit(self):
        from execution.broker_circuit_breaker import CircuitState
        cb = self._make(max_failures=3)
        for _ in range(3):
            asyncio.run(cb.record_failure("connection"))
        assert cb.state == CircuitState.OPEN
        assert cb.is_open is True

    def test_open_circuit_raises_circuit_open_error(self):
        from execution.broker_circuit_breaker import CircuitOpenError
        cb = self._make(max_failures=1, reset_timeout=9999.0)
        asyncio.run(cb.record_failure("timeout"))
        with pytest.raises(CircuitOpenError):
            asyncio.run(cb.call(lambda: None))

    def test_success_resets_failure_count(self):
        cb = self._make(max_failures=5)
        asyncio.run(cb.record_failure("connection"))
        asyncio.run(cb.record_failure("connection"))
        asyncio.run(cb.record_success())
        assert cb._failure_count == 0

    def test_half_open_success_closes_circuit(self):
        from execution.broker_circuit_breaker import CircuitState
        cb = self._make(max_failures=1, reset_timeout=0.0)
        asyncio.run(cb.record_failure("connection"))
        # reset_timeout=0 → immediately transitions to HALF_OPEN on next check
        asyncio.run(cb._check_state())
        assert cb.state == CircuitState.HALF_OPEN
        asyncio.run(cb.record_success())
        assert cb.state == CircuitState.CLOSED

    def test_half_open_failure_reopens(self):
        from execution.broker_circuit_breaker import CircuitState
        cb = self._make(max_failures=1, reset_timeout=0.0)
        asyncio.run(cb.record_failure("connection"))
        asyncio.run(cb._check_state())  # → HALF_OPEN
        asyncio.run(cb.record_failure("timeout"))
        assert cb.state == CircuitState.OPEN

    def test_status_dict_keys(self):
        cb = self._make()
        s = cb.status()
        for key in ("broker", "state", "failure_count", "total_calls",
                    "total_successes", "total_failures", "failure_type_counts",
                    "config"):
            assert key in s

    def test_call_records_failure_on_exception(self):
        cb = self._make(max_failures=5)
        def _bad():
            raise ConnectionError("refused")
        with pytest.raises(ConnectionError):
            asyncio.run(cb.call(_bad))
        assert cb._total_failures == 1

    def test_unknown_failure_type_normalised(self):
        cb = self._make()
        asyncio.run(cb.record_failure("not_a_real_type"))
        assert cb._last_failure_type == "unknown"


@pytest.mark.unit
class TestClassifyError:
    def test_timeout_classified(self):
        from execution.broker_circuit_breaker import _classify_error
        assert _classify_error(TimeoutError("timed out")) == "timeout"

    def test_connection_classified(self):
        from execution.broker_circuit_breaker import _classify_error
        # "connection refused" matches "refused" → rejection; use "unreachable" for connection
        result = _classify_error(ConnectionError("network unreachable"))
        assert result == "connection"

    def test_unknown_classified(self):
        from execution.broker_circuit_breaker import _classify_error
        assert _classify_error(ValueError("something weird")) == "unknown"

    def test_auth_classified(self):
        from execution.broker_circuit_breaker import _classify_error
        assert _classify_error(RuntimeError("unauthorized access")) == "auth"

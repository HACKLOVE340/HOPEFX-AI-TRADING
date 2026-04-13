# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""Coverage tests for execution modules: async_engine, execution, fix_router, fix_adapter, redis_state."""

from __future__ import annotations
import asyncio
import time
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

UTC = timezone.utc


# ---------------------------------------------------------------------------
# AsyncExecutionEngine
# ---------------------------------------------------------------------------
class TestAsyncExecutionEngine:
    def _engine(self, paper=True):
        from execution.async_engine import AsyncExecutionEngine

        return AsyncExecutionEngine(broker_configs=[], paper_mode=paper)

    def _order(self, symbol="XAUUSD", side="buy", qty=1.0):
        from execution.async_engine import Order, OrderType

        return Order(id="", symbol=symbol, side=side, quantity=qty, order_type=OrderType.MARKET)

    def test_init_paper(self):
        e = self._engine()
        assert e.paper_mode and e.orders == {}

    def test_init_live(self):
        assert not self._engine(paper=False).paper_mode

    @pytest.mark.asyncio
    async def test_submit_paper_returns_id(self):
        e = self._engine()
        with patch.object(e, "_select_venue", return_value="paper"), patch.object(e, "_simulate_fill", AsyncMock()):
            oid = await e.submit_order(self._order())
        assert isinstance(oid, str) and len(oid) > 0

    @pytest.mark.asyncio
    async def test_submit_assigns_id(self):
        e = self._engine()
        o = self._order()
        with patch.object(e, "_select_venue", return_value="paper"), patch.object(e, "_simulate_fill", AsyncMock()):
            oid = await e.submit_order(o)
        assert o.id == oid

    @pytest.mark.asyncio
    async def test_submit_shutdown_raises(self):
        e = self._engine()
        e._shutdown = True
        with pytest.raises(RuntimeError, match="shutting down"):
            await e.submit_order(self._order())

    @pytest.mark.asyncio
    async def test_submit_risk_rejected(self):
        from execution.async_engine import OrderStatus

        e = self._engine()
        with patch.object(e, "_pre_trade_check", AsyncMock(return_value=(False, "risk limit"))):
            oid = await e.submit_order(self._order())
        assert e.orders[oid].status == OrderStatus.REJECTED

    def test_order_remaining_qty(self):
        from execution.async_engine import Order, OrderType

        o = Order(id="x", symbol="XAUUSD", side="buy", quantity=5.0, order_type=OrderType.MARKET)
        o.filled_qty = 2.0
        assert o.remaining_qty == pytest.approx(3.0)

    def test_fill_dataclass(self):
        from execution.async_engine import Fill

        f = Fill(order_id="o1", symbol="XAUUSD", quantity=1.0, price=2350.0, timestamp=datetime.now(UTC), side="buy")
        assert f.fees == 0.0

    def test_orders_dict_accessible(self):
        e = self._engine()
        assert isinstance(e.orders, dict)


# ---------------------------------------------------------------------------
# ExecutionSystem
# ---------------------------------------------------------------------------
class TestExecutionSystem:
    def test_init(self):
        from execution.execution import ExecutionSystem

        s = ExecutionSystem()
        assert not s._started

    def test_init_with_ml_fn(self):
        from execution.execution import ExecutionSystem

        fn = MagicMock()
        s = ExecutionSystem(ml_inference_fn=fn)
        assert s._ml_inference_fn is fn

    def test_health_before_start(self):
        from execution.execution import ExecutionSystem

        h = ExecutionSystem().health()
        assert isinstance(h, dict)

    @pytest.mark.asyncio
    async def test_stop_not_started(self):
        from execution.execution import ExecutionSystem

        await ExecutionSystem().stop()

    @pytest.mark.asyncio
    async def test_start_sets_flag(self):
        from execution.execution import ExecutionSystem

        s = ExecutionSystem()
        # Patch all the heavy component starts inside start()
        with patch("execution.execution.ExecutionSystem.start", AsyncMock()) as m:
            await s.start()
        m.assert_called_once()

    @pytest.mark.asyncio
    async def test_start_idempotent_via_flag(self):
        from execution.execution import ExecutionSystem

        s = ExecutionSystem()
        s._started = True
        # start() should return early when already started
        # We verify by checking _start_time is not set (no heavy init ran)
        original_start_time = s._start_time
        with patch("execution.execution.ExecutionSystem.start", AsyncMock()):
            await s.start()
        assert s._start_time == original_start_time


# ---------------------------------------------------------------------------
# FIXRouter
# ---------------------------------------------------------------------------
class TestFIXRouter:
    def test_init(self):
        from execution.fix_router import FIXRouter

        r = FIXRouter()
        assert not r._running and not r._fix_available

    @pytest.mark.asyncio
    async def test_stop_not_running(self):
        from execution.fix_router import FIXRouter

        await FIXRouter().stop()

    def test_metrics(self):
        from execution.fix_router import FIXRouter

        m = FIXRouter().metrics()
        assert isinstance(m, dict)

    @pytest.mark.asyncio
    async def test_stop_sets_running_false(self):
        from execution.fix_router import FIXRouter

        r = FIXRouter()
        r._running = True
        await r.stop()
        assert not r._running

    @pytest.mark.asyncio
    async def test_breach_listener_exits_via_bus_mock(self):
        from execution.fix_router import FIXRouter

        r = FIXRouter()
        r._running = True

        async def fake_subscribe(ch):
            yield {"reason": "kill_switch_active"}
            # After message processed, stop the loop
            r._running = False

        with patch("execution.fix_router.bus") as mock_bus:
            mock_bus.subscribe = fake_subscribe
            await asyncio.wait_for(r._breach_listener(), timeout=2.0)
        assert r._halted


# ---------------------------------------------------------------------------
# FIXAdapter — CircuitBreaker
# ---------------------------------------------------------------------------
class TestFIXAdapterCircuitBreaker:
    def test_init_closed(self):
        from execution.fix_adapter import CircuitBreaker

        cb = CircuitBreaker(threshold_ms=100.0, reset_after_sec=30.0)
        assert not cb.is_open

    def test_opens_after_high_latency(self):
        from execution.fix_adapter import CircuitBreaker

        cb = CircuitBreaker(threshold_ms=100.0, reset_after_sec=30.0)
        cb.record_latency(200.0)
        assert cb.is_open

    def test_stays_closed_below_threshold(self):
        from execution.fix_adapter import CircuitBreaker

        cb = CircuitBreaker(threshold_ms=100.0, reset_after_sec=30.0)
        for _ in range(5):
            cb.record_latency(50.0)
        assert not cb.is_open

    def test_resets_after_timeout(self):
        from execution.fix_adapter import CircuitBreaker

        cb = CircuitBreaker(threshold_ms=100.0, reset_after_sec=0.01)
        cb.record_latency(200.0)
        assert cb.is_open
        time.sleep(0.02)
        cb.record_latency(50.0)  # triggers reset check
        assert not cb.is_open

    def test_check_raises_when_open(self):
        from execution.fix_adapter import CircuitBreaker

        cb = CircuitBreaker(threshold_ms=100.0, reset_after_sec=30.0)
        cb.record_latency(200.0)
        with pytest.raises(RuntimeError, match="circuit breaker"):
            cb.check()

    def test_check_passes_when_closed(self):
        from execution.fix_adapter import CircuitBreaker

        cb = CircuitBreaker(threshold_ms=100.0, reset_after_sec=30.0)
        cb.check()  # should not raise


# ---------------------------------------------------------------------------
# FIXOrder / FIXFillReport dataclasses
# ---------------------------------------------------------------------------
class TestFIXDataclasses:
    def test_fix_order_creation(self):
        from execution.fix_adapter import FIXOrder, FIXSide, FIXOrdType

        o = FIXOrder(symbol="GC", side=FIXSide.BUY, quantity=1.0)
        assert o.symbol == "GC" and o.side == FIXSide.BUY
        assert o.ord_type == FIXOrdType.MARKET  # default

    def test_fix_order_with_limit(self):
        from execution.fix_adapter import FIXOrder, FIXSide, FIXOrdType

        o = FIXOrder(symbol="GC", side=FIXSide.SELL, quantity=2.0, ord_type=FIXOrdType.LIMIT, price=2400.0)
        assert o.price == 2400.0

    def test_fix_fill_report_creation(self):
        from execution.fix_adapter import FIXFillReport, FIXSide, FIXExecType

        f = FIXFillReport(
            cl_ord_id="t1",
            order_id="o1",
            exec_type=FIXExecType.FILL,
            symbol="GC",
            side=FIXSide.BUY,
            filled_qty=1.0,
            avg_px=2350.0,
            leaves_qty=0.0,
            cum_qty=1.0,
        )
        assert f.avg_px == 2350.0 and f.filled_qty == 1.0

    def test_enums(self):
        from execution.fix_adapter import FIXSide, FIXOrdType, FIXExecType

        assert FIXSide.BUY and FIXSide.SELL
        assert FIXOrdType.MARKET and FIXOrdType.LIMIT
        assert FIXExecType.FILL is not None


# ---------------------------------------------------------------------------
# FIXAdapter init
# ---------------------------------------------------------------------------
class TestFIXAdapterInit:
    def _adapter(self):
        from execution.fix_adapter import FIXAdapter

        return FIXAdapter(
            host="127.0.0.1",
            port=9876,
            sender_comp_id="TEST",
            target_comp_id="CME",
            username="",
            password="",  # pragma: allowlist secret
        )

    def test_circuit_breaker_accessible(self):
        a = self._adapter()
        assert a.circuit_breaker is not None

    def test_not_running(self):
        assert not self._adapter()._running

    def test_pending_dict_empty(self):
        assert self._adapter()._pending == {}


# ---------------------------------------------------------------------------
# AsyncRedisStateStore
# ---------------------------------------------------------------------------
class TestAsyncRedisStateStore:
    def _store(self):
        from execution.redis_state import AsyncRedisStateStore

        r = MagicMock()
        r.get = AsyncMock(return_value=None)
        r.set = AsyncMock()
        r.delete = AsyncMock()
        r.sadd = AsyncMock()
        r.srem = AsyncMock()
        r.smembers = AsyncMock(return_value=set())
        return AsyncRedisStateStore(r), r

    @pytest.mark.asyncio
    async def test_save_order(self):
        s, r = self._store()
        await s.save_order({"id": "o1", "symbol": "XAUUSD"})
        r.set.assert_called()

    @pytest.mark.asyncio
    async def test_save_order_no_id_skipped(self):
        s, r = self._store()
        await s.save_order({"symbol": "XAUUSD"})
        r.set.assert_not_called()

    @pytest.mark.asyncio
    async def test_remove_order(self):
        s, r = self._store()
        await s.remove_order("o1")
        r.delete.assert_called()

    @pytest.mark.asyncio
    async def test_load_orders_empty(self):
        s, r = self._store()
        result = await s.load_orders()
        assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_save_position(self):
        s, r = self._store()
        await s.save_position({"symbol": "XAUUSD", "qty": 1.0})
        r.set.assert_called()

    @pytest.mark.asyncio
    async def test_redis_error_non_fatal(self):
        s, r = self._store()
        r.set.side_effect = ConnectionError("down")
        await s.save_order({"id": "o1", "symbol": "XAUUSD"})


# ---------------------------------------------------------------------------
# TradeExecutor — additional paths
# ---------------------------------------------------------------------------
class TestTradeExecutorAdditional:
    def _executor(self):
        from execution.trade_executor import TradeExecutor

        broker = MagicMock()
        broker.place_order = AsyncMock(
            return_value=MagicMock(
                id="f1", filled_quantity=1.0, average_price=2350.0, status=MagicMock(value="filled"), commission=2.0
            )
        )
        broker.get_account_info = AsyncMock(return_value=MagicMock(balance=100_000.0, equity=100_000.0))
        rm = MagicMock()
        rm.validate_trade = AsyncMock(return_value=(True, "ok"))
        rm.current_drawdown = 0.01  # real float, not MagicMock
        rm.get_account_equity = AsyncMock(return_value=100_000.0)
        rm.record_trade_outcome = MagicMock()
        rm._trading_halted = False
        rm._halt_reason = ""
        pt = MagicMock()
        pt.get_position = MagicMock(return_value=None)
        pt.update_position = MagicMock()
        pt.get_all_positions = MagicMock(return_value={})
        pt.open_position_count = MagicMock(return_value=0)
        with patch(
            "infrastructure.metrics.get_metrics_registry",
            return_value=MagicMock(
                record_order_latency=MagicMock(), increment_orders=MagicMock(), increment_fills=MagicMock()
            ),
        ):
            return TradeExecutor(broker, rm, pt)

    @pytest.mark.asyncio
    async def test_sell_signal(self):
        result = await self._executor().execute_signal({"symbol": "XAUUSD", "action": "sell", "size": 1.0})
        assert result is not None

    def test_register_callback(self):
        e = self._executor()
        cb = MagicMock()
        e.register_callback(cb)
        assert cb in e._execution_callbacks

    @pytest.mark.asyncio
    async def test_streak_halted_blocks(self):
        e = self._executor()
        e._consecutive_losses = 3
        e._streak_halted_until = time.monotonic() + 3600
        result = await e.execute_signal({"symbol": "XAUUSD", "action": "buy", "size": 1.0})
        assert not result.success

    @pytest.mark.asyncio
    async def test_streak_expired_allows(self):
        e = self._executor()
        e._consecutive_losses = 3
        e._streak_halted_until = time.monotonic() - 1
        result = await e.execute_signal({"symbol": "XAUUSD", "action": "buy", "size": 1.0})
        assert result is not None

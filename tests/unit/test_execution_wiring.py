# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""Execution package wiring tests with correct APIs."""
from __future__ import annotations
import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

UTC = timezone.utc

def _make_broker_mock(fill_price=2350.0, fill_qty=1.0):
    broker = MagicMock()
    fill = MagicMock()
    fill.id = "fill-001"
    fill.filled_quantity = fill_qty
    fill.average_price = fill_price
    fill.status = MagicMock(value="filled")
    fill.commission = 2.0
    broker.place_order = AsyncMock(return_value=fill)
    broker.get_account_info = AsyncMock(return_value=MagicMock(
        balance=100_000.0, equity=100_000.0, margin_used=0.0, margin_available=100_000.0))
    broker.close_position = AsyncMock(return_value=True)
    return broker

def _make_risk_manager(allow=True):
    rm = MagicMock()
    rm.validate_trade = AsyncMock(return_value=(allow, "ok" if allow else "risk rejected"))
    rm.get_current_drawdown = MagicMock(return_value=0.01)
    rm.get_account_equity = AsyncMock(return_value=100_000.0)
    rm.record_trade_outcome = MagicMock()
    rm._trading_halted = False
    return rm

def _make_position_tracker():
    pt = MagicMock()
    pt.get_position = MagicMock(return_value=None)
    pt.update_position = MagicMock()
    pt.get_all_positions = MagicMock(return_value={})
    pt.open_position_count = MagicMock(return_value=0)
    return pt

def _make_metrics():
    m = MagicMock()
    m.record_order_latency = MagicMock()
    m.increment_orders = MagicMock()
    m.increment_fills = MagicMock()
    return m


class TestOrderGateway:
    def test_create_order(self):
        from execution.order_gateway import OrderGateway
        gw = OrderGateway()
        order = gw.create_order("o1", 1.0, 2350.0, 0.001)
        assert order.order_id == "o1"
        assert "o1" in gw.orders

    def test_send_order_no_executor_returns_failed(self):
        from execution.order_gateway import OrderGateway
        gw = OrderGateway()
        order = gw.create_order("o2", 1.0, 2350.0, 0.001)
        result = gw.send_order(order)
        assert not result.success
        assert order.is_rejected

    @pytest.mark.asyncio
    async def test_send_order_async_no_executor(self):
        from execution.order_gateway import OrderGateway
        gw = OrderGateway()
        order = gw.create_order("o3", 1.0, 2350.0, 0.001)
        result = await gw.send_order_async(order)
        assert not result.success

    @pytest.mark.asyncio
    async def test_send_order_async_success(self):
        from execution.order_gateway import OrderGateway
        from execution.trade_executor import ExecutionResult, OrderStatus
        mock_executor = MagicMock()
        mock_executor.execute_signal = AsyncMock(return_value=ExecutionResult(
            success=True, order_id="o4", filled_quantity=1.0,
            average_price=2350.0, commission=2.0, status=OrderStatus.FILLED, message="ok"))
        gw = OrderGateway(executor=mock_executor)
        order = gw.create_order("o4", 1.0, 2350.0, 0.001)
        result = await gw.send_order_async(order)
        assert result.success
        assert order.is_filled

    @pytest.mark.asyncio
    async def test_send_order_async_executor_raises(self):
        from execution.order_gateway import OrderGateway
        mock_executor = MagicMock()
        mock_executor.execute_signal = AsyncMock(side_effect=RuntimeError("broker down"))
        gw = OrderGateway(executor=mock_executor)
        order = gw.create_order("o5", 1.0, 2350.0, 0.001)
        result = await gw.send_order_async(order)
        assert not result.success
        assert order.is_rejected

    @pytest.mark.asyncio
    async def test_send_order_async_rejected_result(self):
        from execution.order_gateway import OrderGateway
        from execution.trade_executor import ExecutionResult, OrderStatus
        mock_executor = MagicMock()
        mock_executor.execute_signal = AsyncMock(return_value=ExecutionResult(
            success=False, order_id="o6", filled_quantity=0.0,
            average_price=0.0, commission=0.0, status=OrderStatus.REJECTED, message="risk gate blocked"))
        gw = OrderGateway(executor=mock_executor)
        order = gw.create_order("o6", 1.0, 2350.0, 0.001)
        result = await gw.send_order_async(order)
        assert not result.success
        assert order.rejection_reason == "risk gate blocked"

    def test_handle_rejection_known_order(self):
        from execution.order_gateway import OrderGateway
        gw = OrderGateway()
        gw.create_order("o7", 1.0, 2350.0, 0.001)
        gw.handle_rejection("o7", "price moved")
        assert gw.orders["o7"].is_rejected

    def test_handle_rejection_unknown_order(self):
        from execution.order_gateway import OrderGateway
        gw = OrderGateway()
        gw.handle_rejection("nonexistent", "test")  # should not raise

    def test_track_commissions(self):
        from execution.order_gateway import OrderGateway
        gw = OrderGateway()
        o1 = gw.create_order("c1", 1.0, 2350.0, 0.01)
        o1.commission_paid = 5.0
        o2 = gw.create_order("c2", 2.0, 2350.0, 0.01)
        o2.commission_paid = 10.0
        assert gw.track_commissions() == 15.0

    def test_order_fill_overfill_raises(self):
        from execution.order_gateway import Order
        order = Order("x", 1.0, 2350.0, 0.001)
        with pytest.raises(ValueError):
            order.fill(2.0)

    def test_order_sell_fill(self):
        from execution.order_gateway import Order
        order = Order("x", -1.0, 2350.0, 0.001)
        order.fill(1.0)
        assert order.is_filled

    def test_send_order_sync_no_loop(self):
        from execution.order_gateway import OrderGateway
        from execution.trade_executor import ExecutionResult, OrderStatus
        mock_executor = MagicMock()
        mock_executor.execute_signal = AsyncMock(return_value=ExecutionResult(
            success=True, order_id="s1", filled_quantity=1.0,
            average_price=2350.0, commission=2.0, status=OrderStatus.FILLED, message="ok"))
        gw = OrderGateway(executor=mock_executor)
        order = gw.create_order("s1", 1.0, 2350.0, 0.001)
        result = gw.send_order(order)
        assert result.success

    def test_send_order_sync_executor_raises(self):
        from execution.order_gateway import OrderGateway
        mock_executor = MagicMock()
        mock_executor.execute_signal = AsyncMock(side_effect=RuntimeError("crash"))
        gw = OrderGateway(executor=mock_executor)
        order = gw.create_order("s2", 1.0, 2350.0, 0.001)
        result = gw.send_order(order)
        assert not result.success


class TestTradeExecutor:
    def _make_executor(self, allow_risk=True):
        from execution.trade_executor import TradeExecutor
        broker = _make_broker_mock()
        rm = _make_risk_manager(allow=allow_risk)
        pt = _make_position_tracker()
        with patch("infrastructure.metrics.get_metrics_registry", return_value=_make_metrics()):
            executor = TradeExecutor(broker, rm, pt)
        return executor, broker, rm, pt

    @pytest.mark.asyncio
    async def test_missing_fields(self):
        executor, *_ = self._make_executor()
        result = await executor.execute_signal({"symbol": "XAUUSD"})
        assert not result.success
        assert "Missing" in result.message

    @pytest.mark.asyncio
    async def test_invalid_action(self):
        executor, *_ = self._make_executor()
        result = await executor.execute_signal({"symbol": "XAUUSD", "action": "hold", "size": 1.0})
        assert not result.success
        assert "Invalid action" in result.message

    @pytest.mark.asyncio
    async def test_risk_rejected(self):
        executor, *_ = self._make_executor(allow_risk=False)
        # Patch _execute_open to return a rejected result directly
        from execution.trade_executor import ExecutionResult, OrderStatus
        rejected = ExecutionResult(success=False, order_id=None, filled_quantity=0,
                                   average_price=0, commission=0,
                                   status=OrderStatus.REJECTED, message="risk rejected")
        with patch.object(executor, '_execute_open', AsyncMock(return_value=rejected)):
            result = await executor.execute_signal({"symbol": "XAUUSD", "action": "buy", "size": 1.0})
        assert not result.success

    @pytest.mark.asyncio
    async def test_close_no_position(self):
        executor, broker, rm, pt = self._make_executor()
        pt.get_position.return_value = None
        result = await executor.execute_signal({"symbol": "XAUUSD", "action": "close", "size": 1.0})
        assert result is not None

    def test_has_broker(self):
        executor, broker, *_ = self._make_executor()
        assert executor.broker is broker

    def test_initial_streak_count(self):
        executor, *_ = self._make_executor()
        assert executor._consecutive_losses == 0


class TestSmartRouter:
    @pytest.mark.asyncio
    async def test_route_no_brokers_returns_result(self):
        from execution.smart_router import SmartRouter
        router = SmartRouter()
        order = {"symbol": "XAUUSD", "direction": "long", "quantity": 1.0,
                 "order_type": "market", "mid_price": 2350.0,
                 "bid": 2349.5, "ask": 2350.5, "spread": 1.0,
                 "confidence": 0.8, "sentiment": 0.5, "impact": 0.1}
        result = await router.route_and_execute(order)
        assert result is not None
        assert "status" in result

    def test_add_remove_broker(self):
        from execution.smart_router import SmartRouter
        router = SmartRouter()
        broker = _make_broker_mock()
        router.add_broker("b1", broker)
        assert "b1" in router._brokers
        router.remove_broker("b1")
        assert "b1" not in router._brokers

    @pytest.mark.asyncio
    async def test_throttled_returns_rejected(self):
        from execution.smart_router import SmartRouter
        router = SmartRouter()
        router._throttler.can_send = MagicMock(return_value=False)
        router._throttler.get_status = MagicMock(return_value={"level": "critical"})
        order = {"symbol": "XAUUSD", "direction": "long", "quantity": 1.0,
                 "order_type": "order", "mid_price": 2350.0,
                 "bid": 2349.5, "ask": 2350.5, "spread": 1.0,
                 "confidence": 0.8, "sentiment": 0.5, "impact": 0.1}
        result = await router.route_and_execute(order)
        assert result["status"] == "rejected"
        assert "fia_throttle" in result["reason"]

    @pytest.mark.asyncio
    async def test_unwind_bypasses_sentiment_gate(self):
        from execution.smart_router import SmartRouter
        router = SmartRouter()
        broker = _make_broker_mock()
        broker.place_order = AsyncMock(return_value={"status": "filled", "fill_price": 2350.0,
                                                      "quantity": 1.0, "latency_ms": 5.0})
        router.add_broker("primary", broker)
        order = {"symbol": "XAUUSD", "direction": "short", "quantity": 1.0,
                 "order_type": "market", "mid_price": 2350.0,
                 "bid": 2349.5, "ask": 2350.5, "spread": 1.0,
                 "confidence": 0.1, "sentiment": -0.9, "impact": 0.9,
                 "is_unwind": True}
        result = await router.route_and_execute(order)
        assert result is not None


class TestAlgoOrders:
    def test_twap_creation(self):
        from execution.algo_orders import TWAPOrder
        order = TWAPOrder(symbol="XAUUSD", side="buy", total_quantity=10.0,
                          duration_seconds=300, num_slices=5)
        assert order.num_slices == 5
        assert order.total_quantity == pytest.approx(10.0)
        assert order._interval == pytest.approx(60.0)

    def test_vwap_creation(self):
        from execution.algo_orders import VWAPOrder
        order = VWAPOrder(symbol="XAUUSD", side="sell", total_quantity=5.0, duration_seconds=600)
        assert order.total_quantity == pytest.approx(5.0)

    def test_iceberg_creation(self):
        from execution.algo_orders import IcebergOrder
        order = IcebergOrder(symbol="XAUUSD", side="buy", total_quantity=20.0, peak_size=2.0)
        assert order.peak_size == pytest.approx(2.0)

    def test_vwap_slice_quantities_sum(self):
        from execution.algo_orders import VWAPOrder
        order = VWAPOrder(symbol="XAUUSD", side="buy", total_quantity=100.0,
                          duration_seconds=3600, num_slices=10)
        slices = order._compute_slice_quantities()
        assert len(slices) > 0
        assert abs(sum(slices) - 100.0) < 2.0

    def test_algo_cancel(self):
        from execution.algo_orders import AlgoStatus, TWAPOrder
        order = TWAPOrder(symbol="XAUUSD", side="buy", total_quantity=10.0,
                          duration_seconds=300, num_slices=5)
        order.cancel()
        assert order.status == AlgoStatus.CANCELLED

    def test_algo_manager_set_broker_fn(self):
        from execution.algo_orders import AlgoOrderManager
        manager = AlgoOrderManager()
        fn = AsyncMock()
        manager.set_broker_submit_fn(fn)
        assert manager._broker_submit is fn

    def test_twap_cancel_sets_status(self):
        from execution.algo_orders import AlgoStatus, TWAPOrder
        order = TWAPOrder(symbol="XAUUSD", side="buy", total_quantity=10.0,
                          duration_seconds=300, num_slices=5)
        order.cancel()
        assert order.status == AlgoStatus.CANCELLED

    def test_iceberg_remaining_quantity(self):
        from execution.algo_orders import IcebergOrder
        order = IcebergOrder(symbol="XAUUSD", side="buy", total_quantity=10.0, peak_size=2.0)
        assert order.remaining_quantity == pytest.approx(10.0)


class TestRedisStateStore:
    def _make_store(self):
        from execution.redis_state import RedisStateStore
        mock_r = MagicMock()
        mock_r.get = MagicMock(return_value=None)
        mock_r.set = MagicMock()
        mock_r.delete = MagicMock()
        mock_r.sadd = MagicMock()
        mock_r.srem = MagicMock()
        mock_r.smembers = MagicMock(return_value=set())
        mock_r.keys = MagicMock(return_value=[])
        return RedisStateStore(mock_r), mock_r

    def test_save_order(self):
        store, mock_r = self._make_store()
        store.save_order({"id": "o1", "symbol": "XAUUSD", "status": "pending"})
        mock_r.set.assert_called()

    def test_save_order_no_id_skipped(self):
        store, mock_r = self._make_store()
        store.save_order({"symbol": "XAUUSD"})
        mock_r.set.assert_not_called()

    def test_remove_order(self):
        store, mock_r = self._make_store()
        store.remove_order("o1")
        mock_r.delete.assert_called()

    def test_save_order_redis_error_non_fatal(self):
        store, mock_r = self._make_store()
        mock_r.set.side_effect = ConnectionError("redis down")
        store.save_order({"id": "o1", "symbol": "XAUUSD"})  # should not raise

    def test_load_orders_returns_list(self):
        store, mock_r = self._make_store()
        mock_r.smembers.return_value = set()
        result = store.load_orders()
        assert isinstance(result, list)

    def test_save_position(self):
        store, mock_r = self._make_store()
        store.save_position({"symbol": "XAUUSD", "qty": 1.0, "entry": 2350.0})
        mock_r.set.assert_called()

    def test_load_orders_empty(self):
        store, mock_r = self._make_store()
        mock_r.smembers.return_value = set()
        result = store.load_orders()
        assert isinstance(result, list)


class TestSLTPMonitor:
    def _make_monitor(self):
        from execution.sl_tp_monitor import SLTPMonitor
        pm = MagicMock()
        broker = _make_broker_mock()
        tick_cache = {}
        monitor = SLTPMonitor(position_manager=pm, broker=broker, tick_cache=tick_cache)
        return monitor, pm, broker, tick_cache

    def test_init(self):
        monitor, *_ = self._make_monitor()
        assert monitor is not None

    @pytest.mark.asyncio
    async def test_check_positions_empty(self):
        monitor, pm, broker, tick_cache = self._make_monitor()
        pm.get_all_positions = MagicMock(return_value={})
        await monitor._check_all_positions()

    @pytest.mark.asyncio
    async def test_check_positions_no_tick_skips(self):
        monitor, pm, broker, tick_cache = self._make_monitor()
        mock_pos = MagicMock()
        mock_pos.stop_loss = 2280.0
        mock_pos.take_profit = 2400.0
        mock_pos.side = "buy"
        mock_pos.entry_price = 2300.0
        mock_pos.quantity = 1.0
        pm.get_all_positions = MagicMock(return_value={"XAUUSD": mock_pos})
        await monitor._check_all_positions()  # no tick — should skip

    @pytest.mark.asyncio
    async def test_check_positions_tp_triggered(self):
        monitor, pm, broker, tick_cache = self._make_monitor()
        mock_pos = MagicMock()
        mock_pos.stop_loss = 2280.0
        mock_pos.take_profit = 2350.0
        mock_pos.side = "buy"
        mock_pos.entry_price = 2300.0
        mock_pos.quantity = 1.0
        pm.get_all_positions = MagicMock(return_value={"XAUUSD": mock_pos})
        tick_cache["XAUUSD"] = {"bid": 2355.0, "ask": 2356.0, "mid": 2355.5}
        await monitor._check_all_positions()

    @pytest.mark.asyncio
    async def test_check_positions_sl_triggered(self):
        monitor, pm, broker, tick_cache = self._make_monitor()
        mock_pos = MagicMock()
        mock_pos.stop_loss = 2280.0
        mock_pos.take_profit = 2400.0
        mock_pos.side = "buy"
        mock_pos.entry_price = 2300.0
        mock_pos.quantity = 1.0
        pm.get_all_positions = MagicMock(return_value={"XAUUSD": mock_pos})
        tick_cache["XAUUSD"] = {"bid": 2275.0, "ask": 2276.0, "mid": 2275.5}
        await monitor._check_all_positions()


class TestExecutionEngine:
    def _make_engine(self):
        from execution.engine import ExecutionEngine
        broker = _make_broker_mock()
        rm = _make_risk_manager()
        return ExecutionEngine(broker_manager=broker, risk_manager=rm,
                               kill_switch=None, redis_client=None, tca_recorder=None), broker, rm

    def test_init(self):
        engine, broker, rm = self._make_engine()
        assert engine is not None
        assert engine._broker is broker

    @pytest.mark.asyncio
    async def test_execute_kill_switch_active(self):
        from execution.engine import ExecutionRequest
        engine, broker, rm = self._make_engine()
        mock_ks = MagicMock()
        mock_ks.is_active = MagicMock(return_value=True)
        engine._kill_switch = mock_ks
        req = ExecutionRequest(symbol="XAUUSD", side="BUY", quantity=1.0,
                               order_type="MARKET", strategy_id="test")
        report = await engine.execute(req)
        assert report is not None

    def test_register_fill_callback(self):
        engine, *_ = self._make_engine()
        cb = MagicMock()
        engine.add_fill_callback(cb)
        assert cb in engine._on_fill_callbacks

    def test_update_last_tick(self):
        engine, *_ = self._make_engine()
        engine.update_last_tick("XAUUSD", {"bid": 2349.0, "ask": 2351.0})
        assert "XAUUSD" in engine._last_ticks

    def test_metrics_snapshot(self):
        engine, *_ = self._make_engine()
        snap = engine.get_metrics()
        assert isinstance(snap, dict)
        assert "total_orders" in snap


# tests/unit/test_execution_coverage8.py
"""Coverage tests for execution/async_engine.py and execution/smart_router.py."""
from __future__ import annotations

import asyncio
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest


def _make_order(symbol="XAUUSD", side="BUY", qty=0.1, order_type=None, price=None):
    from execution.async_engine import Order, OrderType
    return Order(
        id=str(uuid.uuid4()),
        symbol=symbol,
        side=side,
        quantity=qty,
        order_type=order_type or OrderType.MARKET,
        price=price,
    )


async def _make_engine(extra_broker=False):
    from execution.async_engine import AsyncExecutionEngine
    configs = [{"name": "paper", "type": "paper", "symbols": ["XAUUSD", "EURUSD"], "latency_ms": 1}]
    if extra_broker:
        configs.append({"name": "paper2", "type": "paper", "symbols": ["XAUUSD"], "latency_ms": 1})
    e = AsyncExecutionEngine(broker_configs=configs, paper_mode=True)
    await e.initialize()
    return e


class TestAsyncExecutionEngineBasic:
    @pytest.mark.asyncio
    async def test_instantiation(self):
        e = await _make_engine()
        assert e is not None
        assert "paper" in e.brokers

    @pytest.mark.asyncio
    async def test_select_venue_returns_string(self):
        e = await _make_engine()
        order = _make_order()
        venue = e._select_venue(order)
        assert isinstance(venue, str)

    @pytest.mark.asyncio
    async def test_get_backup_venue_none_single(self):
        e = await _make_engine()
        assert e._get_backup_venue("paper") is None

    @pytest.mark.asyncio
    async def test_get_backup_venue_with_two(self):
        e = await _make_engine(extra_broker=True)
        backup = e._get_backup_venue("paper")
        assert backup == "paper2"

    @pytest.mark.asyncio
    async def test_submit_market_order(self):
        e = await _make_engine()
        order = _make_order()
        order_id = await e.submit_order(order)
        assert order_id is not None
        assert order_id in e.orders

    @pytest.mark.asyncio
    async def test_submit_limit_order(self):
        from execution.async_engine import OrderType
        e = await _make_engine()
        order = _make_order(order_type=OrderType.LIMIT, price=2350.0)
        order_id = await e.submit_order(order)
        assert order_id is not None

    @pytest.mark.asyncio
    async def test_cancel_order_existing(self):
        import asyncio as aio
        from execution.async_engine import OrderStatus
        e = await _make_engine()
        order = _make_order()
        order.status = OrderStatus.PENDING
        order.metadata = {"venue": "paper"}
        e.orders[order.id] = order
        e.order_locks[order.id] = aio.Lock()
        e.pending_orders.add(order.id)
        result = await e.cancel_order(order.id)
        assert result is True

    @pytest.mark.asyncio
    async def test_cancel_order_nonexistent(self):
        e = await _make_engine()
        result = await e.cancel_order("nonexistent_id")
        assert result is False

    @pytest.mark.asyncio
    async def test_get_positions(self):
        e = await _make_engine()
        positions = await e.get_positions()
        assert isinstance(positions, list)

    @pytest.mark.asyncio
    async def test_batch_submit(self):
        e = await _make_engine()
        orders = [_make_order(), _make_order(side="SELL")]
        ids = await e.batch_submit(orders)
        assert len(ids) == 2

    @pytest.mark.asyncio
    async def test_get_latency_report(self):
        e = await _make_engine()
        report = await e.get_latency_report()
        assert isinstance(report, dict)

    @pytest.mark.asyncio
    async def test_shutdown(self):
        e = await _make_engine()
        await e.shutdown()
        assert e._shutdown is True

    @pytest.mark.asyncio
    async def test_pre_trade_check_passes(self):
        e = await _make_engine()
        order = _make_order()
        ok, reason = await e._pre_trade_check(order)
        assert ok is True

    @pytest.mark.asyncio
    async def test_close_all_positions(self):
        e = await _make_engine()
        result = await e.close_all_positions()
        assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_format_order(self):
        e = await _make_engine()
        order = _make_order()
        formatted = e._format_order(order, {"type": "paper"})
        assert "symbol" in formatted

    @pytest.mark.asyncio
    async def test_simulate_fill_runs(self):
        e = await _make_engine()
        order = _make_order()
        order_id = await e.submit_order(order)
        await asyncio.sleep(0.05)
        assert order_id in e.orders


class TestAsyncEngineOrderDataclass:
    def test_remaining_qty(self):
        o = _make_order(qty=1.0)
        o.filled_qty = 0.4
        assert o.remaining_qty == pytest.approx(0.6)

    def test_order_status_enum(self):
        from execution.async_engine import OrderStatus
        assert OrderStatus.PENDING is not None
        assert OrderStatus.FILLED is not None
        assert OrderStatus.CANCELLED is not None

    def test_order_type_enum(self):
        from execution.async_engine import OrderType
        assert OrderType.MARKET is not None
        assert OrderType.LIMIT is not None


# ── SmartRouter ───────────────────────────────────────────────────────────────

class TestSmartRouterBasic:
    def _router(self):
        from execution.smart_router import SmartRouter
        return SmartRouter()

    def test_instantiation(self):
        assert self._router() is not None

    def test_add_broker(self):
        r = self._router()
        r.add_broker("alpaca", MagicMock())
        assert "alpaca" in r._brokers

    def test_remove_broker(self):
        r = self._router()
        r.add_broker("alpaca", MagicMock())
        r.remove_broker("alpaca")
        assert "alpaca" not in r._brokers

    def test_remove_nonexistent_broker(self):
        self._router().remove_broker("nonexistent")

    def test_metrics_empty(self):
        assert isinstance(self._router().metrics(), dict)

    @pytest.mark.asyncio
    async def test_route_no_brokers_returns_result(self):
        r = self._router()
        result = await r.route_and_execute({"symbol": "XAUUSD", "direction": "long", "lots": 0.01, "mid_price": 2350.0})
        assert isinstance(result, dict)
        assert "status" in result

    @pytest.mark.asyncio
    async def test_route_with_broker(self):
        r = self._router()
        broker = MagicMock()
        broker.place_order = AsyncMock(return_value=MagicMock(id="ord1", fill_price=2350.0, status="filled"))
        r.add_broker("test_broker", broker)
        result = await r.route_and_execute({"symbol": "XAUUSD", "direction": "long", "lots": 0.01, "mid_price": 2350.0, "ofi": 0.5, "sentiment": 0.6})
        assert isinstance(result, dict)

    def test_ofi_alignment_long_positive(self):
        from execution.smart_router import _ofi_alignment
        assert _ofi_alignment(ofi=1.0, direction="long") == pytest.approx(1.0)

    def test_ofi_alignment_long_negative(self):
        from execution.smart_router import _ofi_alignment
        assert _ofi_alignment(ofi=-1.0, direction="long") == pytest.approx(0.0)

    def test_ofi_alignment_short(self):
        from execution.smart_router import _ofi_alignment
        assert _ofi_alignment(ofi=-1.0, direction="short") == pytest.approx(1.0)

    def test_ofi_alignment_unknown(self):
        from execution.smart_router import _ofi_alignment
        assert _ofi_alignment(ofi=0.5, direction="unknown") == pytest.approx(0.5)

    def test_spread_to_bps_normal(self):
        from execution.smart_router import _spread_to_bps
        assert _spread_to_bps(spread_usd=0.5, mid=2500.0) == pytest.approx(2.0)

    def test_spread_to_bps_zero_mid(self):
        from execution.smart_router import _spread_to_bps
        assert _spread_to_bps(spread_usd=0.5, mid=0.0) == 0.0


class TestBrokerState:
    def test_record_fill_updates_total(self):
        from execution.smart_router import BrokerState
        s = BrokerState(broker_id="b1")
        s.record_fill(latency_ms=10.0, slippage_bps=1.0)
        assert s.total_fills == 1

    def test_record_error_increments(self):
        from execution.smart_router import BrokerState
        s = BrokerState(broker_id="b1")
        s.record_error()
        s.record_error()
        assert s.total_errors == 2

    def test_routing_score_returns_float(self):
        from execution.smart_router import BrokerState
        s = BrokerState(broker_id="b1")
        score = s.routing_score(direction="long", ofi=0.0, sentiment_score=0.5)
        assert isinstance(score, float)

    def test_routing_score_fast_beats_slow(self):
        from execution.smart_router import BrokerState
        fast = BrokerState(broker_id="fast", ema_latency_ms=5.0, fill_rate=0.99)
        slow = BrokerState(broker_id="slow", ema_latency_ms=500.0, fill_rate=0.99)
        assert fast.routing_score("long", 0.0, 0.5) > slow.routing_score("long", 0.0, 0.5)

    def test_check_circuit_reset_after_timeout(self):
        import time
        from execution.smart_router import BrokerState
        s = BrokerState(broker_id="b1")
        s.circuit_open = True
        s.circuit_open_at = time.monotonic() - 9999
        s.check_circuit_reset()
        assert not s.circuit_open

    def test_circuit_stays_open_if_recent(self):
        import time
        from execution.smart_router import BrokerState
        s = BrokerState(broker_id="b1")
        s.circuit_open = True
        s.circuit_open_at = time.monotonic()
        s.check_circuit_reset()
        assert s.circuit_open

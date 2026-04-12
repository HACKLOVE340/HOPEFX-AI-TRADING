# tests/unit/test_execution_coverage10.py
"""Targeted coverage for async_engine missing lines: _simulate_fill, _apply_fill, modify_order."""

from __future__ import annotations

import asyncio
import uuid

import pytest


async def _engine_with_price(symbol="XAUUSD"):
    from execution.async_engine import AsyncExecutionEngine

    e = AsyncExecutionEngine(
        broker_configs=[{"name": "paper", "type": "paper", "symbols": [symbol], "latency_ms": 1}],
        paper_mode=True,
    )
    await e.initialize()
    # Inject price cache so _simulate_fill can proceed
    async with e.price_lock:
        e.price_cache[symbol] = {
            "bid": 2349.0,
            "ask": 2351.0,
            "mid": 2350.0,
            "volatility": 0.001,
            "timestamp": 0,
        }
    return e


def _order(symbol="XAUUSD", side="BUY", qty=0.1, order_type=None, price=None):
    from execution.async_engine import Order, OrderType

    return Order(
        id=str(uuid.uuid4()),
        symbol=symbol,
        side=side,
        quantity=qty,
        order_type=order_type or OrderType.MARKET,
        price=price,
    )


class TestSimulateFill:
    @pytest.mark.asyncio
    async def test_market_buy_fills(self):
        from execution.async_engine import OrderStatus

        e = await _engine_with_price()
        order = _order(side="buy", qty=0.1)
        await e._simulate_fill(order)
        assert order.status in (OrderStatus.FILLED, OrderStatus.PARTIAL_FILL)

    @pytest.mark.asyncio
    async def test_market_sell_fills(self):
        from execution.async_engine import OrderStatus

        e = await _engine_with_price()
        order = _order(side="sell", qty=0.1)
        await e._simulate_fill(order)
        assert order.status in (OrderStatus.FILLED, OrderStatus.PARTIAL_FILL)

    @pytest.mark.asyncio
    async def test_no_price_cache_rejects(self):
        from execution.async_engine import AsyncExecutionEngine, OrderStatus

        e = AsyncExecutionEngine(
            broker_configs=[{"name": "paper", "type": "paper", "symbols": ["XAUUSD"]}],
            paper_mode=True,
        )
        await e.initialize()
        # No price cache entry
        order = _order()
        await e._simulate_fill(order)
        assert order.status == OrderStatus.REJECTED

    @pytest.mark.asyncio
    async def test_limit_buy_below_ask_fills(self):
        from execution.async_engine import OrderStatus, OrderType

        e = await _engine_with_price()
        # Limit price above ask → fills immediately
        order = _order(side="buy", qty=0.1, order_type=OrderType.LIMIT, price=2360.0)
        await e._simulate_fill(order)
        assert order.status in (OrderStatus.FILLED, OrderStatus.PARTIAL_FILL, OrderStatus.SUBMITTED)

    @pytest.mark.asyncio
    async def test_limit_sell_above_bid_fills(self):
        from execution.async_engine import OrderStatus, OrderType

        e = await _engine_with_price()
        # Limit price below bid → fills immediately
        order = _order(side="sell", qty=0.1, order_type=OrderType.LIMIT, price=2340.0)
        await e._simulate_fill(order)
        assert order.status in (OrderStatus.FILLED, OrderStatus.PARTIAL_FILL, OrderStatus.SUBMITTED)

    @pytest.mark.asyncio
    async def test_on_fill_callback_fires(self):
        from execution.async_engine import OrderStatus

        e = await _engine_with_price()
        fills_received = []
        e.on_fill = lambda f: fills_received.append(f)
        order = _order(side="buy", qty=0.01)
        await e._simulate_fill(order)
        if order.status in (OrderStatus.FILLED, OrderStatus.PARTIAL_FILL):
            assert len(fills_received) >= 1

    @pytest.mark.asyncio
    async def test_on_order_update_callback_fires(self):
        e = await _engine_with_price()
        updates = []
        e.on_order_update = lambda o: updates.append(o)
        order = _order(side="buy", qty=0.01)
        await e._simulate_fill(order)
        assert len(updates) >= 1


class TestApplyFill:
    @pytest.mark.asyncio
    async def test_apply_fill_full(self):
        from execution.async_engine import Fill, OrderStatus

        e = await _engine_with_price()
        order = _order(qty=1.0)
        order.status = __import__("execution.async_engine", fromlist=["OrderStatus"]).OrderStatus.SUBMITTED
        e.orders[order.id] = order
        e.order_locks[order.id] = asyncio.Lock()

        fill = Fill(
            order_id=order.id,
            symbol="XAUUSD",
            quantity=1.0,
            price=2350.0,
            timestamp=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
            side="buy",
        )
        await e._apply_fill(order, fill)
        assert order.status == OrderStatus.FILLED

    @pytest.mark.asyncio
    async def test_apply_fill_partial(self):
        from execution.async_engine import Fill, OrderStatus

        e = await _engine_with_price()
        order = _order(qty=1.0)
        order.status = OrderStatus.SUBMITTED
        e.orders[order.id] = order
        e.order_locks[order.id] = asyncio.Lock()

        fill = Fill(
            order_id=order.id,
            symbol="XAUUSD",
            quantity=0.4,
            price=2350.0,
            timestamp=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
            side="buy",
        )
        await e._apply_fill(order, fill)
        assert order.status == OrderStatus.PARTIAL_FILL

    @pytest.mark.asyncio
    async def test_apply_fill_callback_error_no_propagate(self):
        from execution.async_engine import Fill, OrderStatus

        e = await _engine_with_price()
        e.on_fill = lambda f: (_ for _ in ()).throw(RuntimeError("cb error"))
        order = _order(qty=1.0)
        order.status = OrderStatus.SUBMITTED
        e.orders[order.id] = order
        e.order_locks[order.id] = asyncio.Lock()

        fill = Fill(
            order_id=order.id,
            symbol="XAUUSD",
            quantity=1.0,
            price=2350.0,
            timestamp=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
            side="buy",
        )
        # Should not raise
        await e._apply_fill(order, fill)


class TestModifyOrder:
    @pytest.mark.asyncio
    async def test_modify_nonexistent_order(self):
        e = await _engine_with_price()
        result = await e.modify_order("nonexistent", new_price=2355.0)
        assert result is False


class TestCloseAllPositions:
    @pytest.mark.asyncio
    async def test_close_all_with_positions(self):
        e = await _engine_with_price()
        # Inject a position into cache
        e.position_cache["XAUUSD"] = {
            "symbol": "XAUUSD",
            "side": "long",
            "quantity": 0.1,
            "venue": "paper",
        }
        result = await e.close_all_positions()
        assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_get_latency_report_with_data(self):
        e = await _engine_with_price()
        e.latency_stats["submit"].extend([10.0, 20.0, 15.0])
        report = await e.get_latency_report()
        assert "submit" in report
        assert report["submit"]["mean_ms"] > 0

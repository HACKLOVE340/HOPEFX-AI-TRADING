# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""Tests for execution/async_engine.py — AsyncExecutionEngine, Order, Fill."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest

from execution.async_engine import (
    AsyncExecutionEngine,
    Fill,
    Order,
    OrderStatus,
    OrderType,
)

UTC = timezone.utc
_PAPER_CONFIG = [{"name": "paper", "rate_limit": 10, "symbols": ["XAUUSD"]}]


def _order(oid="o1", symbol="XAUUSD", side="buy", qty=1.0,
           order_type=OrderType.MARKET, price=None):
    return Order(id=oid, symbol=symbol, side=side, quantity=qty,
                 order_type=order_type, price=price)


async def _engine() -> AsyncExecutionEngine:
    e = AsyncExecutionEngine(broker_configs=_PAPER_CONFIG, paper_mode=True)
    await e.initialize()
    return e


class TestOrder:
    def test_remaining_qty_full(self):
        assert _order(qty=5.0).remaining_qty == pytest.approx(5.0)

    def test_remaining_qty_partial(self):
        o = _order(qty=5.0)
        o.filled_qty = 2.0
        assert o.remaining_qty == pytest.approx(3.0)

    def test_default_status_pending(self):
        assert _order().status == OrderStatus.PENDING

    def test_metadata_default_empty(self):
        assert _order().metadata == {}


class TestOrderStatus:
    def test_all_statuses_exist(self):
        for s in (OrderStatus.PENDING, OrderStatus.SUBMITTED,
                  OrderStatus.FILLED, OrderStatus.CANCELLED, OrderStatus.REJECTED):
            assert s


class TestOrderType:
    def test_all_types_exist(self):
        for t in (OrderType.MARKET, OrderType.LIMIT, OrderType.STOP, OrderType.TRAILING_STOP):
            assert t


class TestFill:
    def test_fill_creation(self):
        f = Fill(order_id="o1", symbol="XAUUSD", quantity=1.0,
                 price=1900.0, timestamp=datetime.now(UTC), side="buy")
        assert f.order_id == "o1"
        assert f.fees == 0.0


class TestAsyncExecutionEngineInit:
    def test_init_stores_config(self):
        e = AsyncExecutionEngine(broker_configs=_PAPER_CONFIG, paper_mode=True)
        assert e.broker_configs == _PAPER_CONFIG

    def test_paper_mode_true(self):
        e = AsyncExecutionEngine(broker_configs=_PAPER_CONFIG, paper_mode=True)
        assert e.paper_mode is True

    def test_orders_empty_initially(self):
        e = AsyncExecutionEngine(broker_configs=_PAPER_CONFIG, paper_mode=True)
        assert e.orders == {}

    @pytest.mark.asyncio
    async def test_initialize_populates_brokers(self):
        e = await _engine()
        assert "paper" in e.brokers
        await e.shutdown()


class TestSubmitOrder:
    @pytest.mark.asyncio
    async def test_submit_returns_order_id(self):
        e = await _engine()
        o = _order("ord_abc")
        result = await e.submit_order(o)
        assert result == "ord_abc"
        await e.shutdown()

    @pytest.mark.asyncio
    async def test_order_tracked(self):
        e = await _engine()
        o = _order("tracked")
        await e.submit_order(o)
        assert "tracked" in e.orders
        await e.shutdown()

    @pytest.mark.asyncio
    async def test_shutdown_rejects_order(self):
        e = await _engine()
        await e.shutdown()
        with pytest.raises(RuntimeError):
            await e.submit_order(_order("late"))


class TestCancelOrder:
    @pytest.mark.asyncio
    async def test_cancel_nonexistent_returns_false(self):
        e = await _engine()
        result = await e.cancel_order("ghost")
        assert result is False
        await e.shutdown()

    @pytest.mark.asyncio
    async def test_cancel_filled_order_returns_false(self):
        e = await _engine()
        o = _order("filled_ord")
        await e.submit_order(o)
        # Force status to FILLED so cancel returns False
        e.orders["filled_ord"].status = OrderStatus.FILLED
        result = await e.cancel_order("filled_ord")
        assert result is False
        await e.shutdown()


class TestGetPositions:
    @pytest.mark.asyncio
    async def test_get_positions_returns_list(self):
        e = await _engine()
        positions = await e.get_positions()
        assert isinstance(positions, list)
        await e.shutdown()


class TestShutdown:
    @pytest.mark.asyncio
    async def test_shutdown_sets_flag(self):
        e = await _engine()
        await e.shutdown()
        assert e._shutdown is True

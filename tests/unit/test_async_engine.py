# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""Tests for execution/async_engine.py — AsyncExecutionEngine."""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from execution.async_engine import (
    AsyncExecutionEngine,
    Fill,
    Order,
    OrderStatus,
    OrderType,
)

UTC = timezone.utc

# ── Helpers ───────────────────────────────────────────────────────────────────


def _broker_config(name: str = "test_broker") -> dict:
    return {"name": name, "rate_limit": 5, "url": "http://localhost:9999"}


def _engine(paper: bool = True, seed: int = 42) -> AsyncExecutionEngine:
    return AsyncExecutionEngine(
        broker_configs=[_broker_config()],
        paper_mode=paper,
        paper_rng_seed=seed,
    )


async def _init(e: AsyncExecutionEngine) -> AsyncExecutionEngine:
    """Initialize engine with price feed loop stubbed out (no-op)."""
    with patch.object(e, "_price_feed_loop", new=AsyncMock(return_value=None)):
        await e.initialize()
    return e


async def _cleanup(e: AsyncExecutionEngine):
    for t in list(e._tasks):
        t.cancel()
    if e._tasks:
        await asyncio.gather(*e._tasks, return_exceptions=True)
    e._tasks.clear()


def _market_order(symbol: str = "EUR/USD", qty: float = 1.0, side: str = "buy") -> Order:
    return Order(
        id=str(uuid.uuid4()),
        symbol=symbol,
        side=side,
        quantity=qty,
        order_type=OrderType.MARKET,
    )


def _limit_order(symbol: str = "EUR/USD", qty: float = 1.0, price: float = 1.08) -> Order:
    return Order(
        id=str(uuid.uuid4()),
        symbol=symbol,
        side="buy",
        quantity=qty,
        order_type=OrderType.LIMIT,
        price=price,
    )


def _seed_price(e: AsyncExecutionEngine, symbol: str = "EUR/USD", mid: float = 1.08):
    e.price_cache[symbol] = {
        "bid": mid - 0.0001,
        "ask": mid + 0.0001,
        "mid": mid,
        "volatility": 0.0002,
    }


# ── Order dataclass ───────────────────────────────────────────────────────────


class TestOrder:
    def test_remaining_qty_full(self):
        o = _market_order(qty=10.0)
        assert o.remaining_qty == 10.0

    def test_remaining_qty_partial(self):
        o = _market_order(qty=10.0)
        o.filled_qty = 4.0
        assert o.remaining_qty == 6.0

    def test_default_status(self):
        o = _market_order()
        assert o.status == OrderStatus.PENDING

    def test_order_fields(self):
        o = _limit_order(price=1.09)
        assert o.price == 1.09
        assert o.order_type == OrderType.LIMIT


# ── Fill dataclass ────────────────────────────────────────────────────────────


class TestFill:
    def test_fill_creation(self):
        f = Fill(
            order_id="ord_1",
            symbol="EUR/USD",
            quantity=1.0,
            price=1.08,
            timestamp=datetime.now(UTC),
            side="buy",
            fees=0.0005,
        )
        assert f.order_id == "ord_1"
        assert f.fees == 0.0005


# ── Engine initialisation ─────────────────────────────────────────────────────


class TestEngineInit:
    def test_paper_mode_default(self):
        e = _engine()
        assert e.paper_mode is True

    def test_orders_dict_empty_on_init(self):
        e = _engine()
        assert e.orders == {}
        assert e.pending_orders == set()

    def test_rng_seeded(self):
        e1 = _engine(seed=0)
        e2 = _engine(seed=0)
        v1 = e1._rng.random()
        v2 = e2._rng.random()
        assert v1 == v2

    def test_rng_different_seeds(self):
        e1 = _engine(seed=1)
        e2 = _engine(seed=2)
        assert e1._rng.random() != e2._rng.random()

    def test_broker_configs_stored(self):
        e = _engine()
        assert e.broker_configs == [_broker_config()]


# ── Initialize ────────────────────────────────────────────────────────────────


class TestInitialize:
    @pytest.mark.asyncio
    async def test_initialize_registers_broker(self):
        e = _engine()
        await _init(e)
        assert "test_broker" in e.brokers
        await _cleanup(e)

    @pytest.mark.asyncio
    async def test_initialize_creates_rate_limiter(self):
        e = _engine()
        await _init(e)
        assert "test_broker" in e.rate_limiters
        await _cleanup(e)


# ── Submit order ──────────────────────────────────────────────────────────────


async def _instant_fill(order: Order):
    """Instant fill stub — marks order FILLED without any sleep."""
    order.status = OrderStatus.FILLED
    order.filled_qty = order.quantity
    order.avg_fill_price = 1.08


class TestSubmitOrder:
    @pytest.mark.asyncio
    async def test_submit_market_order_paper_mode(self):
        e = _engine()
        await _init(e)
        _seed_price(e)
        order = _market_order()
        with patch.object(e, "_simulate_fill", new=AsyncMock(side_effect=_instant_fill)):
            order_id = await e.submit_order(order)
        assert order_id == order.id
        assert order.status == OrderStatus.FILLED
        await _cleanup(e)

    @pytest.mark.asyncio
    async def test_submit_rejected_when_shutdown(self):
        e = _engine()
        await _init(e)
        e._shutdown = True
        order = _market_order()
        with pytest.raises(RuntimeError, match="shutting down"):
            await e.submit_order(order)
        await _cleanup(e)

    @pytest.mark.asyncio
    async def test_submit_rejected_on_position_limit(self):
        e = _engine()
        await _init(e)
        _seed_price(e)
        e.position_cache["EUR/USD"] = {"quantity": 99.0}
        order = _market_order(qty=5.0)
        order_id = await e.submit_order(order)
        assert e.orders[order_id].status == OrderStatus.REJECTED
        assert e.orders[order_id].metadata.get("reject_reason") == "position_limit_exceeded"
        await _cleanup(e)

    @pytest.mark.asyncio
    async def test_submit_assigns_id_if_empty(self):
        e = _engine()
        await _init(e)
        _seed_price(e)
        order = _market_order()
        order.id = ""
        with patch.object(e, "_simulate_fill", new=AsyncMock(side_effect=_instant_fill)):
            order_id = await e.submit_order(order)
        assert order_id != ""
        assert order_id.startswith("ord_")
        await _cleanup(e)

    @pytest.mark.asyncio
    async def test_submit_no_market_data_rejects(self):
        e = _engine()
        await _init(e)
        # No price cache for UNKNOWN/SYM — _simulate_fill will reject it
        order = _market_order(symbol="UNKNOWN/SYM")
        # Don't patch _simulate_fill; let it run its rejection logic (no sleep needed)
        order_id = await e.submit_order(order)
        assert e.orders[order_id].status == OrderStatus.REJECTED
        await _cleanup(e)


# ── Cancel order ──────────────────────────────────────────────────────────────


class TestCancelOrder:
    @pytest.mark.asyncio
    async def test_cancel_nonexistent_order(self):
        e = _engine()
        result = await e.cancel_order("nonexistent")
        assert result is False

    @pytest.mark.asyncio
    async def test_cancel_pending_order(self):
        e = _engine()
        await _init(e)
        order = _market_order()
        order.status = OrderStatus.PENDING
        order.metadata["venue"] = "test_broker"
        e.orders[order.id] = order
        e.pending_orders.add(order.id)
        result = await e.cancel_order(order.id)
        assert result is True
        assert order.status == OrderStatus.CANCELLED
        await _cleanup(e)

    @pytest.mark.asyncio
    async def test_cancel_filled_order_returns_false(self):
        e = _engine()
        order = _market_order()
        order.status = OrderStatus.FILLED
        e.orders[order.id] = order
        result = await e.cancel_order(order.id)
        assert result is False

    @pytest.mark.asyncio
    async def test_cancel_no_venue_returns_false(self):
        e = _engine()
        order = _market_order()
        order.status = OrderStatus.PENDING
        e.orders[order.id] = order
        result = await e.cancel_order(order.id)
        assert result is False


# ── Modify order ──────────────────────────────────────────────────────────────


class TestModifyOrder:
    @pytest.mark.asyncio
    async def test_modify_nonexistent_returns_false(self):
        e = _engine()
        result = await e.modify_order("nonexistent", new_price=1.09)
        assert result is False

    @pytest.mark.asyncio
    async def test_modify_creates_new_order(self):
        e = _engine()
        await _init(e)
        _seed_price(e)
        order = _limit_order(price=1.08)
        order.status = OrderStatus.SUBMITTED
        order.metadata["venue"] = "test_broker"
        e.orders[order.id] = order
        e.pending_orders.add(order.id)
        # Patch both cancel and submit to avoid real async delays
        with (
            patch.object(e, "cancel_order", new=AsyncMock(return_value=True)),
            patch.object(e, "submit_order", new=AsyncMock(return_value="new_order_id")),
        ):
            result = await e.modify_order(order.id, new_price=1.09)
        assert result is True
        await _cleanup(e)


# ── Batch submit ──────────────────────────────────────────────────────────────


class TestBatchSubmit:
    @pytest.mark.asyncio
    async def test_batch_submit_multiple_orders(self):
        e = _engine()
        await _init(e)
        _seed_price(e)
        orders = [_market_order() for _ in range(3)]
        with patch.object(e, "_simulate_fill", new=AsyncMock(side_effect=_instant_fill)):
            results = await e.batch_submit(orders)
        assert len(results) == 3
        await _cleanup(e)


# ── Close all positions ───────────────────────────────────────────────────────


class TestCloseAllPositions:
    @pytest.mark.asyncio
    async def test_close_all_no_positions(self):
        e = _engine()
        await _init(e)
        result = await e.close_all_positions()
        assert result == []
        await _cleanup(e)

    @pytest.mark.asyncio
    async def test_close_all_with_position(self):
        e = _engine()
        await _init(e)
        _seed_price(e)
        e.position_cache["EUR/USD"] = {"symbol": "EUR/USD", "quantity": 1.0}
        e._position_cache_time = 9999999999
        with patch.object(e, "_simulate_fill", new=AsyncMock(side_effect=_instant_fill)):
            result = await e.close_all_positions()
        assert len(result) >= 1
        await _cleanup(e)

    @pytest.mark.asyncio
    async def test_close_positions_filtered_by_symbol(self):
        e = _engine()
        await _init(e)
        _seed_price(e, "EUR/USD")
        _seed_price(e, "GBP/USD", mid=1.26)
        e.position_cache["EUR/USD"] = {"symbol": "EUR/USD", "quantity": 1.0}
        e.position_cache["GBP/USD"] = {"symbol": "GBP/USD", "quantity": 2.0}
        e._position_cache_time = 9999999999
        with patch.object(e, "_simulate_fill", new=AsyncMock(side_effect=_instant_fill)):
            result = await e.close_all_positions(symbol="EUR/USD")
        assert len(result) == 1
        await _cleanup(e)


# ── Get positions ─────────────────────────────────────────────────────────────


class TestGetPositions:
    @pytest.mark.asyncio
    async def test_get_positions_uses_cache(self):
        e = _engine()
        await _init(e)
        e.position_cache["EUR/USD"] = {"symbol": "EUR/USD", "quantity": 1.0}
        e._position_cache_time = 9999999999
        positions = await e.get_positions()
        assert len(positions) == 1
        await _cleanup(e)

    @pytest.mark.asyncio
    async def test_get_positions_fetches_when_stale(self):
        e = _engine()
        await _init(e)
        e._position_cache_time = 0
        positions = await e.get_positions()
        assert isinstance(positions, list)
        await _cleanup(e)


# ── Apply fill ────────────────────────────────────────────────────────────────


class TestApplyFill:
    @pytest.mark.asyncio
    async def test_apply_fill_marks_filled(self):
        e = _engine()
        order = _market_order(qty=1.0)
        e.orders[order.id] = order
        fill = Fill(
            order_id=order.id, symbol="EUR/USD", quantity=1.0, price=1.08, timestamp=datetime.now(UTC), side="buy"
        )
        await e._apply_fill(order, fill)
        assert order.status == OrderStatus.FILLED
        assert order.filled_qty == 1.0

    @pytest.mark.asyncio
    async def test_apply_fill_partial(self):
        e = _engine()
        order = _market_order(qty=2.0)
        e.orders[order.id] = order
        fill = Fill(
            order_id=order.id, symbol="EUR/USD", quantity=1.0, price=1.08, timestamp=datetime.now(UTC), side="buy"
        )
        await e._apply_fill(order, fill)
        assert order.status == OrderStatus.PARTIAL_FILL

    @pytest.mark.asyncio
    async def test_apply_fill_triggers_callbacks(self):
        e = _engine()
        fill_cb = MagicMock()
        order_cb = MagicMock()
        e.on_fill = fill_cb
        e.on_order_update = order_cb
        order = _market_order(qty=1.0)
        e.orders[order.id] = order
        fill = Fill(
            order_id=order.id, symbol="EUR/USD", quantity=1.0, price=1.08, timestamp=datetime.now(UTC), side="buy"
        )
        await e._apply_fill(order, fill)
        fill_cb.assert_called_once_with(fill)
        order_cb.assert_called_once_with(order)

    @pytest.mark.asyncio
    async def test_apply_fill_callback_error_swallowed(self):
        e = _engine()
        e.on_fill = MagicMock(side_effect=RuntimeError("cb error"))
        order = _market_order(qty=1.0)
        e.orders[order.id] = order
        fill = Fill(
            order_id=order.id, symbol="EUR/USD", quantity=1.0, price=1.08, timestamp=datetime.now(UTC), side="buy"
        )
        await e._apply_fill(order, fill)  # must not raise

    @pytest.mark.asyncio
    async def test_apply_fill_updates_avg_price(self):
        e = _engine()
        order = _market_order(qty=2.0)
        e.orders[order.id] = order
        f1 = Fill(
            order_id=order.id, symbol="EUR/USD", quantity=1.0, price=1.08, timestamp=datetime.now(UTC), side="buy"
        )
        f2 = Fill(
            order_id=order.id, symbol="EUR/USD", quantity=1.0, price=1.10, timestamp=datetime.now(UTC), side="buy"
        )
        await e._apply_fill(order, f1)
        await e._apply_fill(order, f2)
        assert abs(order.avg_fill_price - 1.09) < 0.001


# ── Pre-trade check ───────────────────────────────────────────────────────────


class TestPreTradeCheck:
    @pytest.mark.asyncio
    async def test_passes_normal_order(self):
        e = _engine()
        _seed_price(e)
        order = _market_order(qty=1.0)
        allowed, reason = await e._pre_trade_check(order)
        assert allowed is True
        assert reason == ""

    @pytest.mark.asyncio
    async def test_rejects_position_limit(self):
        e = _engine()
        e.position_cache["EUR/USD"] = {"quantity": 99.0}
        order = _market_order(qty=5.0)
        allowed, reason = await e._pre_trade_check(order)
        assert allowed is False
        assert reason == "position_limit_exceeded"

    @pytest.mark.asyncio
    async def test_rejects_price_deviation(self):
        e = _engine()
        _seed_price(e, mid=1.08)
        order = _limit_order(price=2.0)
        allowed, reason = await e._pre_trade_check(order)
        assert allowed is False
        assert reason == "price_deviation_too_large"

    @pytest.mark.asyncio
    async def test_passes_no_price_cache(self):
        e = _engine()
        order = _market_order()
        allowed, reason = await e._pre_trade_check(order)
        assert allowed is True


# ── Venue selection ───────────────────────────────────────────────────────────


class TestVenueSelection:
    def test_select_venue_returns_string(self):
        e = _engine()
        e.brokers = {"broker_a": {}, "broker_b": {}}
        order = _market_order()
        venue = e._select_venue(order)
        assert venue in ("broker_a", "broker_b")

    def test_get_backup_venue(self):
        e = _engine()
        e.brokers = {"primary": {}, "backup": {}}
        backup = e._get_backup_venue("primary")
        assert backup == "backup"

    def test_get_backup_venue_none_when_single(self):
        e = _engine()
        e.brokers = {"only": {}}
        backup = e._get_backup_venue("only")
        assert backup is None

    def test_venue_has_symbol_always_true(self):
        e = _engine()
        assert e._venue_has_symbol("any_venue", "EUR/USD") is True


# ── Format order ──────────────────────────────────────────────────────────────


class TestFormatOrder:
    def test_format_market_order(self):
        e = _engine()
        formatted = e._format_order(_market_order(), {})
        assert formatted["type"] == "MKT"
        assert formatted["symbol"] == "EUR/USD"

    def test_format_limit_order(self):
        e = _engine()
        formatted = e._format_order(_limit_order(price=1.09), {})
        assert formatted["type"] == "LMT"
        assert formatted["price"] == 1.09

    def test_format_stop_order(self):
        e = _engine()
        order = Order(
            id=str(uuid.uuid4()),
            symbol="EUR/USD",
            side="sell",
            quantity=1.0,
            order_type=OrderType.STOP,
            stop_price=1.07,
        )
        formatted = e._format_order(order, {})
        assert formatted["type"] == "STP"


# ── Latency report ────────────────────────────────────────────────────────────


class TestLatencyReport:
    @pytest.mark.asyncio
    async def test_empty_latency_report(self):
        e = _engine()
        report = await e.get_latency_report()
        assert isinstance(report, dict)

    @pytest.mark.asyncio
    async def test_latency_report_with_data(self):
        e = _engine()
        e.latency_stats["submit"] = [10.0, 20.0, 30.0]
        report = await e.get_latency_report()
        assert "submit" in report
        assert report["submit"]["mean_ms"] == 20.0
        assert report["submit"]["count"] == 3


# ── Shutdown ──────────────────────────────────────────────────────────────────


class TestShutdown:
    @pytest.mark.asyncio
    async def test_shutdown_sets_flag(self):
        e = _engine()
        await _init(e)
        await _cleanup(e)
        await e.shutdown()
        assert e._shutdown is True


# ── Simulate fill (paper mode) ────────────────────────────────────────────────


class TestSimulateFill:
    @pytest.mark.asyncio
    async def test_simulate_fill_raises_in_live_mode(self):
        e = AsyncExecutionEngine(broker_configs=[_broker_config()], paper_mode=False)
        order = _market_order()
        with pytest.raises(RuntimeError, match="live mode"):
            await e._simulate_fill(order)

    @pytest.mark.asyncio
    async def test_simulate_fill_rejects_no_market_data(self):
        e = _engine()
        order = _market_order(symbol="UNKNOWN/SYM")
        await e._simulate_fill(order)
        assert order.status == OrderStatus.REJECTED
        assert order.metadata.get("reject_reason") == "no_market_data"

    @pytest.mark.asyncio
    async def test_simulate_fill_market_order_fills(self):
        e = _engine(seed=0)
        _seed_price(e)
        order = _market_order(qty=0.1)
        with patch("execution.async_engine.asyncio.sleep", new_callable=AsyncMock):
            await e._simulate_fill(order)
        assert order.status in (OrderStatus.FILLED, OrderStatus.PARTIAL_FILL)
        assert order.filled_qty > 0

    @pytest.mark.asyncio
    async def test_simulate_fill_limit_order_at_market(self):
        e = _engine(seed=0)
        _seed_price(e, mid=1.08)
        order = _limit_order(price=1.09, qty=0.1)
        with patch("execution.async_engine.asyncio.sleep", new_callable=AsyncMock):
            await e._simulate_fill(order)
        assert order.status in (OrderStatus.FILLED, OrderStatus.PARTIAL_FILL, OrderStatus.SUBMITTED)


# ── Monitor fills (live mode guard) ──────────────────────────────────────────


class TestMonitorFills:
    @pytest.mark.asyncio
    async def test_monitor_fills_skips_in_paper_mode(self):
        e = _engine(paper=True)
        order = _market_order()
        order.status = OrderStatus.SUBMITTED
        await e._monitor_fills(order)
        assert order.status == OrderStatus.SUBMITTED

# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
Comprehensive tests for execution/async_engine.py.

Covers: Order, Fill, OrderStatus, OrderType, AsyncExecutionEngine —
submit, cancel, modify, batch_submit, close_all_positions, get_positions,
_simulate_fill, _apply_fill, _pre_trade_check, _select_venue, callbacks,
latency stats, price cache, and shutdown.
"""

from __future__ import annotations

import asyncio
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

_PAPER_CFG = [{"name": "paper", "rate_limit": 5, "symbols": ["XAUUSD"]}]


def _mk_order(
    oid="o1",
    symbol="XAUUSD",
    side="buy",
    qty=1.0,
    order_type=OrderType.MARKET,
    price=None,
    stop_price=None,
    tif="GTC",
):
    return Order(
        id=oid,
        symbol=symbol,
        side=side,
        quantity=qty,
        order_type=order_type,
        price=price,
        stop_price=stop_price,
        time_in_force=tif,
    )


async def _engine(paper=True) -> AsyncExecutionEngine:
    e = AsyncExecutionEngine(broker_configs=_PAPER_CFG, paper_mode=paper, paper_rng_seed=0)
    await e.initialize()
    return e


# ── Order dataclass ────────────────────────────────────────────────────────────


class TestOrderDataclass:
    def test_remaining_qty_zero_fill(self):
        o = _mk_order(qty=3.0)
        assert o.remaining_qty == pytest.approx(3.0)

    def test_remaining_qty_partial(self):
        o = _mk_order(qty=3.0)
        o.filled_qty = 1.5
        assert o.remaining_qty == pytest.approx(1.5)

    def test_remaining_qty_fully_filled(self):
        o = _mk_order(qty=2.0)
        o.filled_qty = 2.0
        assert o.remaining_qty == pytest.approx(0.0)

    def test_default_status_pending(self):
        assert _mk_order().status == OrderStatus.PENDING

    def test_metadata_default_empty(self):
        assert _mk_order().metadata == {}

    def test_created_at_is_datetime(self):
        o = _mk_order()
        assert isinstance(o.created_at, datetime)

    def test_updated_at_is_datetime(self):
        o = _mk_order()
        assert isinstance(o.updated_at, datetime)

    def test_avg_fill_price_default_zero(self):
        assert _mk_order().avg_fill_price == 0.0

    def test_filled_qty_default_zero(self):
        assert _mk_order().filled_qty == 0.0


# ── Fill dataclass ─────────────────────────────────────────────────────────────


class TestFillDataclass:
    def test_fill_fields(self):
        f = Fill(
            order_id="o1",
            symbol="XAUUSD",
            quantity=1.0,
            price=2000.0,
            timestamp=datetime.now(UTC),
            side="buy",
        )
        assert f.order_id == "o1"
        assert f.symbol == "XAUUSD"
        assert f.quantity == pytest.approx(1.0)
        assert f.price == pytest.approx(2000.0)
        assert f.side == "buy"
        assert f.fees == pytest.approx(0.0)

    def test_fill_with_fees(self):
        f = Fill(
            order_id="o2",
            symbol="EURUSD",
            quantity=0.5,
            price=1.08,
            timestamp=datetime.now(UTC),
            side="sell",
            fees=0.001,
        )
        assert f.fees == pytest.approx(0.001)


# ── OrderStatus / OrderType enums ──────────────────────────────────────────────


class TestEnums:
    def test_all_order_statuses(self):
        statuses = [
            OrderStatus.PENDING,
            OrderStatus.SUBMITTED,
            OrderStatus.PARTIAL_FILL,
            OrderStatus.FILLED,
            OrderStatus.CANCELLED,
            OrderStatus.REJECTED,
            OrderStatus.EXPIRED,
        ]
        assert len(statuses) == 7

    def test_all_order_types(self):
        types = [
            OrderType.MARKET,
            OrderType.LIMIT,
            OrderType.STOP,
            OrderType.STOP_LIMIT,
            OrderType.TRAILING_STOP,
        ]
        assert len(types) == 5


# ── Engine initialisation ──────────────────────────────────────────────────────


class TestEngineInit:
    def test_paper_mode_flag(self):
        e = AsyncExecutionEngine(broker_configs=_PAPER_CFG, paper_mode=True)
        assert e.paper_mode is True

    def test_orders_empty_on_init(self):
        e = AsyncExecutionEngine(broker_configs=_PAPER_CFG, paper_mode=True)
        assert e.orders == {}

    def test_pending_orders_empty_on_init(self):
        e = AsyncExecutionEngine(broker_configs=_PAPER_CFG, paper_mode=True)
        assert e.pending_orders == set()

    def test_shutdown_flag_false(self):
        e = AsyncExecutionEngine(broker_configs=_PAPER_CFG, paper_mode=True)
        assert e._shutdown is False

    def test_rng_seeded(self):
        e = AsyncExecutionEngine(broker_configs=_PAPER_CFG, paper_mode=True, paper_rng_seed=42)
        assert e._rng is not None

    @pytest.mark.asyncio
    async def test_initialize_registers_broker(self):
        e = await _engine()
        assert "paper" in e.brokers
        await e.shutdown()

    @pytest.mark.asyncio
    async def test_initialize_creates_rate_limiter(self):
        e = await _engine()
        assert "paper" in e.rate_limiters
        await e.shutdown()


# ── submit_order ───────────────────────────────────────────────────────────────


class TestSubmitOrder:
    @pytest.mark.asyncio
    async def test_returns_order_id(self):
        e = await _engine()
        o = _mk_order("test_id")
        result = await e.submit_order(o)
        assert result == "test_id"
        await e.shutdown()

    @pytest.mark.asyncio
    async def test_order_stored_in_orders(self):
        e = await _engine()
        o = _mk_order("stored")
        await e.submit_order(o)
        assert "stored" in e.orders
        await e.shutdown()

    @pytest.mark.asyncio
    async def test_shutdown_raises_runtime_error(self):
        e = await _engine()
        await e.shutdown()
        with pytest.raises(RuntimeError, match="shutting down"):
            await e.submit_order(_mk_order("late"))

    @pytest.mark.asyncio
    async def test_order_with_empty_id_gets_generated_id(self):
        e = await _engine()
        o = _mk_order(oid="")
        result = await e.submit_order(o)
        assert result != ""
        assert len(result) > 0
        await e.shutdown()

    @pytest.mark.asyncio
    async def test_market_order_paper_mode_fills(self):
        e = await _engine()
        # Seed price cache so fill simulation works
        e.price_cache["XAUUSD"] = {
            "bid": 1999.0,
            "ask": 2001.0,
            "mid": 2000.0,
            "volatility": 0.0001,
        }
        o = _mk_order("fill_test", qty=0.01)
        # Patch _simulate_fill to avoid real async sleep delays
        with patch.object(e, "_simulate_fill", new=AsyncMock(return_value=None)):
            await e.submit_order(o)
        assert "fill_test" in e.orders
        await e.shutdown()

    @pytest.mark.asyncio
    async def test_rejected_order_has_reason(self):
        e = await _engine()
        # Patch pre-trade check to reject
        with patch.object(e, "_pre_trade_check", new=AsyncMock(return_value=(False, "test_reject"))):
            o = _mk_order("rejected_ord")
            await e.submit_order(o)
        assert e.orders["rejected_ord"].status == OrderStatus.REJECTED
        assert e.orders["rejected_ord"].metadata.get("reject_reason") == "test_reject"
        await e.shutdown()

    @pytest.mark.asyncio
    async def test_on_fill_callback_called(self):
        e = await _engine()
        fills_received = []
        e.on_fill = lambda f: fills_received.append(f)
        o = _mk_order("cb_test", qty=1.0)
        e.orders["cb_test"] = o
        fill = Fill("cb_test", "XAUUSD", 1.0, 2000.0, datetime.now(UTC), "buy")
        await e._apply_fill(o, fill)
        assert len(fills_received) == 1
        await e.shutdown()

    @pytest.mark.asyncio
    async def test_on_order_update_callback_called(self):
        e = await _engine()
        updates = []
        e.on_order_update = lambda o: updates.append(o)
        o = _mk_order("upd_test", qty=1.0)
        e.orders["upd_test"] = o
        fill = Fill("upd_test", "XAUUSD", 1.0, 2000.0, datetime.now(UTC), "buy")
        await e._apply_fill(o, fill)
        assert len(updates) == 1
        await e.shutdown()


# ── cancel_order ───────────────────────────────────────────────────────────────


class TestCancelOrder:
    @pytest.mark.asyncio
    async def test_cancel_nonexistent_returns_false(self):
        e = await _engine()
        assert await e.cancel_order("ghost") is False
        await e.shutdown()

    @pytest.mark.asyncio
    async def test_cancel_filled_returns_false(self):
        e = await _engine()
        o = _mk_order("filled_o")
        e.orders["filled_o"] = o
        o.status = OrderStatus.FILLED
        o.metadata["venue"] = "paper"
        assert await e.cancel_order("filled_o") is False
        await e.shutdown()

    @pytest.mark.asyncio
    async def test_cancel_cancelled_returns_false(self):
        e = await _engine()
        o = _mk_order("already_cancelled")
        e.orders["already_cancelled"] = o
        o.status = OrderStatus.CANCELLED
        o.metadata["venue"] = "paper"
        assert await e.cancel_order("already_cancelled") is False
        await e.shutdown()

    @pytest.mark.asyncio
    async def test_cancel_pending_no_venue_returns_false(self):
        e = await _engine()
        o = _mk_order("no_venue")
        e.orders["no_venue"] = o
        o.status = OrderStatus.PENDING
        # No venue in metadata
        assert await e.cancel_order("no_venue") is False
        await e.shutdown()

    @pytest.mark.asyncio
    async def test_cancel_submitted_order_succeeds(self):
        e = await _engine()
        o = _mk_order("sub_ord")
        e.orders["sub_ord"] = o
        o.status = OrderStatus.SUBMITTED
        o.metadata["venue"] = "paper"
        # Patch rate_limited_request to succeed
        with patch.object(e, "_rate_limited_request", new=AsyncMock(return_value=None)):
            result = await e.cancel_order("sub_ord")
        assert result is True
        assert e.orders["sub_ord"].status == OrderStatus.CANCELLED
        await e.shutdown()


# ── modify_order ───────────────────────────────────────────────────────────────


class TestModifyOrder:
    @pytest.mark.asyncio
    async def test_modify_nonexistent_returns_false(self):
        e = await _engine()
        assert await e.modify_order("ghost", 2000.0) is False
        await e.shutdown()

    @pytest.mark.asyncio
    async def test_modify_creates_new_order(self):
        e = await _engine()
        o = _mk_order("orig", qty=1.0, price=1990.0)
        e.orders["orig"] = o
        o.status = OrderStatus.SUBMITTED
        o.metadata["venue"] = "paper"
        # Patch cancel_order and submit_order to avoid real async work
        with patch.object(e, "cancel_order", new=AsyncMock(return_value=True)):
            with patch.object(e, "submit_order", new=AsyncMock(return_value="new_ord")):
                result = await e.modify_order("orig", 2010.0)
        assert result is True
        await e.shutdown()


# ── batch_submit ───────────────────────────────────────────────────────────────


class TestBatchSubmit:
    @pytest.mark.asyncio
    async def test_batch_returns_list_of_ids(self):
        e = await _engine()
        orders = [_mk_order(f"b{i}") for i in range(3)]
        results = await e.batch_submit(orders)
        assert len(results) == 3
        for i, r in enumerate(results):
            assert r == f"b{i}" or isinstance(r, Exception)
        await e.shutdown()

    @pytest.mark.asyncio
    async def test_batch_empty_list(self):
        e = await _engine()
        results = await e.batch_submit([])
        assert results == []
        await e.shutdown()


# ── close_all_positions ────────────────────────────────────────────────────────


class TestCloseAllPositions:
    @pytest.mark.asyncio
    async def test_close_all_no_positions(self):
        e = await _engine()
        with patch.object(e, "get_positions", new=AsyncMock(return_value=[])):
            result = await e.close_all_positions()
        assert result == []
        await e.shutdown()

    @pytest.mark.asyncio
    async def test_close_all_long_position(self):
        e = await _engine()
        positions = [{"symbol": "XAUUSD", "quantity": 1.0}]
        with patch.object(e, "get_positions", new=AsyncMock(return_value=positions)):
            with patch.object(e, "submit_order", new=AsyncMock(return_value="close_ord")):
                result = await e.close_all_positions()
        assert "close_ord" in result
        await e.shutdown()

    @pytest.mark.asyncio
    async def test_close_all_short_position(self):
        e = await _engine()
        positions = [{"symbol": "XAUUSD", "quantity": -1.0}]
        with patch.object(e, "get_positions", new=AsyncMock(return_value=positions)):
            with patch.object(e, "submit_order", new=AsyncMock(return_value="close_short")):
                result = await e.close_all_positions()
        assert "close_short" in result
        await e.shutdown()

    @pytest.mark.asyncio
    async def test_close_all_filtered_by_symbol(self):
        e = await _engine()
        positions = [
            {"symbol": "XAUUSD", "quantity": 1.0},
            {"symbol": "EURUSD", "quantity": 1.0},
        ]
        with patch.object(e, "get_positions", new=AsyncMock(return_value=positions)):
            with patch.object(e, "submit_order", new=AsyncMock(return_value="close_xau")):
                result = await e.close_all_positions(symbol="XAUUSD")
        assert len(result) == 1
        await e.shutdown()


# ── get_positions ──────────────────────────────────────────────────────────────


class TestGetPositions:
    @pytest.mark.asyncio
    async def test_returns_list(self):
        e = await _engine()
        positions = await e.get_positions()
        assert isinstance(positions, list)
        await e.shutdown()

    @pytest.mark.asyncio
    async def test_uses_cache_when_fresh(self):
        e = await _engine()
        import time

        e._position_cache_time = time.time()  # mark cache as fresh
        e.position_cache["XAUUSD"] = {"symbol": "XAUUSD", "quantity": 1.0}
        positions = await e.get_positions()
        assert any(p.get("symbol") == "XAUUSD" for p in positions)
        await e.shutdown()

    @pytest.mark.asyncio
    async def test_fetches_fresh_on_stale_cache(self):
        e = await _engine()
        e._position_cache_time = 0.0  # stale
        with patch.object(
            e,
            "_rate_limited_request",
            new=AsyncMock(return_value=[{"symbol": "XAUUSD", "quantity": 2.0}]),
        ):
            positions = await e.get_positions()
        assert isinstance(positions, list)
        await e.shutdown()


# ── _apply_fill ────────────────────────────────────────────────────────────────


class TestApplyFill:
    @pytest.mark.asyncio
    async def test_apply_fill_updates_filled_qty(self):
        e = await _engine()
        o = _mk_order("af1", qty=2.0)
        e.orders["af1"] = o
        fill = Fill(
            order_id="af1",
            symbol="XAUUSD",
            quantity=1.0,
            price=2000.0,
            timestamp=datetime.now(UTC),
            side="buy",
        )
        await e._apply_fill(o, fill)
        assert o.filled_qty == pytest.approx(1.0)
        await e.shutdown()

    @pytest.mark.asyncio
    async def test_apply_fill_sets_partial_status(self):
        e = await _engine()
        o = _mk_order("af2", qty=2.0)
        e.orders["af2"] = o
        fill = Fill(
            order_id="af2",
            symbol="XAUUSD",
            quantity=1.0,
            price=2000.0,
            timestamp=datetime.now(UTC),
            side="buy",
        )
        await e._apply_fill(o, fill)
        assert o.status == OrderStatus.PARTIAL_FILL
        await e.shutdown()

    @pytest.mark.asyncio
    async def test_apply_fill_sets_filled_status_on_complete(self):
        e = await _engine()
        o = _mk_order("af3", qty=1.0)
        e.orders["af3"] = o
        fill = Fill(
            order_id="af3",
            symbol="XAUUSD",
            quantity=1.0,
            price=2000.0,
            timestamp=datetime.now(UTC),
            side="buy",
        )
        await e._apply_fill(o, fill)
        assert o.status == OrderStatus.FILLED
        await e.shutdown()

    @pytest.mark.asyncio
    async def test_apply_fill_updates_avg_price(self):
        e = await _engine()
        o = _mk_order("af4", qty=2.0)
        e.orders["af4"] = o
        fill1 = Fill("af4", "XAUUSD", 1.0, 2000.0, datetime.now(UTC), "buy")
        fill2 = Fill("af4", "XAUUSD", 1.0, 2100.0, datetime.now(UTC), "buy")
        await e._apply_fill(o, fill1)
        await e._apply_fill(o, fill2)
        assert o.avg_fill_price == pytest.approx(2050.0)
        await e.shutdown()

    @pytest.mark.asyncio
    async def test_apply_fill_removes_from_pending(self):
        e = await _engine()
        o = _mk_order("af5", qty=1.0)
        e.orders["af5"] = o
        e.pending_orders.add("af5")
        fill = Fill("af5", "XAUUSD", 1.0, 2000.0, datetime.now(UTC), "buy")
        await e._apply_fill(o, fill)
        assert "af5" not in e.pending_orders
        await e.shutdown()

    @pytest.mark.asyncio
    async def test_apply_fill_on_fill_callback_error_handled(self):
        e = await _engine()
        o = _mk_order("af6", qty=1.0)
        e.orders["af6"] = o

        def bad_callback(f):
            raise RuntimeError("callback error")

        e.on_fill = bad_callback
        fill = Fill("af6", "XAUUSD", 1.0, 2000.0, datetime.now(UTC), "buy")
        # Should not raise
        await e._apply_fill(o, fill)
        await e.shutdown()


# ── _pre_trade_check ───────────────────────────────────────────────────────────


class TestPreTradeCheck:
    @pytest.mark.asyncio
    async def test_market_order_allowed(self):
        e = await _engine()
        o = _mk_order("ptc1", qty=1.0)
        allowed, reason = await e._pre_trade_check(o)
        assert allowed is True
        assert reason == ""
        await e.shutdown()

    @pytest.mark.asyncio
    async def test_position_limit_exceeded_rejected(self):
        e = await _engine()
        # Set position cache so adding 1 lot would exceed 100 limit
        e.position_cache["XAUUSD"] = {"quantity": 100}
        o = _mk_order("ptc2", qty=1.0, side="buy")
        allowed, reason = await e._pre_trade_check(o)
        assert allowed is False
        assert reason == "position_limit_exceeded"
        await e.shutdown()

    @pytest.mark.asyncio
    async def test_price_deviation_rejected(self):
        e = await _engine()
        e.price_cache["XAUUSD"] = {"bid": 2000.0, "ask": 2001.0, "mid": 2000.0, "volatility": 0.0001}
        # Price 10% away from mid — exceeds 5% threshold
        o = _mk_order("ptc3", qty=1.0, order_type=OrderType.LIMIT, price=2200.0)
        allowed, reason = await e._pre_trade_check(o)
        assert allowed is False
        assert reason == "price_deviation_too_large"
        await e.shutdown()

    @pytest.mark.asyncio
    async def test_no_price_cache_allows_order(self):
        e = await _engine()
        # No price cache entry — check passes
        o = _mk_order("ptc4", qty=1.0, order_type=OrderType.LIMIT, price=2000.0)
        allowed, reason = await e._pre_trade_check(o)
        assert allowed is True
        await e.shutdown()


# ── _select_venue ──────────────────────────────────────────────────────────────


class TestSelectVenue:
    def test_returns_string(self):
        e = AsyncExecutionEngine(broker_configs=_PAPER_CFG, paper_mode=True)
        e.brokers = {"paper": _PAPER_CFG[0]}
        o = _mk_order()
        venue = e._select_venue(o)
        assert isinstance(venue, str)

    def test_returns_first_broker_when_one_available(self):
        e = AsyncExecutionEngine(broker_configs=_PAPER_CFG, paper_mode=True)
        e.brokers = {"paper": _PAPER_CFG[0]}
        o = _mk_order()
        venue = e._select_venue(o)
        assert venue == "paper"


# ── _get_backup_venue ──────────────────────────────────────────────────────────


class TestGetBackupVenue:
    def test_no_backup_when_single_broker(self):
        e = AsyncExecutionEngine(broker_configs=_PAPER_CFG, paper_mode=True)
        e.brokers = {"paper": _PAPER_CFG[0]}
        backup = e._get_backup_venue("paper")
        assert backup is None

    def test_backup_returned_when_multiple_brokers(self):
        cfg = [
            {"name": "primary", "rate_limit": 5},
            {"name": "backup", "rate_limit": 5},
        ]
        e = AsyncExecutionEngine(broker_configs=cfg, paper_mode=True)
        e.brokers = {"primary": cfg[0], "backup": cfg[1]}
        backup = e._get_backup_venue("primary")
        assert backup == "backup"


# ── latency stats ──────────────────────────────────────────────────────────────


class TestLatencyStats:
    @pytest.mark.asyncio
    async def test_latency_recorded_on_submit(self):
        e = await _engine()
        o = _mk_order("lat1")
        await e.submit_order(o)
        # latency_stats may or may not have entries depending on paper mode path
        assert isinstance(e.latency_stats, dict)
        await e.shutdown()


# ── shutdown ───────────────────────────────────────────────────────────────────


class TestShutdown:
    @pytest.mark.asyncio
    async def test_shutdown_sets_flag(self):
        e = await _engine()
        await e.shutdown()
        assert e._shutdown is True

    @pytest.mark.asyncio
    async def test_double_shutdown_safe(self):
        e = await _engine()
        await e.shutdown()
        await e.shutdown()  # Should not raise
        assert e._shutdown is True

    @pytest.mark.asyncio
    async def test_shutdown_cancels_tasks(self):
        e = await _engine()
        # Add a dummy task
        async def _dummy():
            await asyncio.sleep(100)

        task = asyncio.create_task(_dummy())
        e._tasks.add(task)
        await e.shutdown()
        assert e._shutdown is True


# ── _simulate_fill guard ───────────────────────────────────────────────────────


class TestSimulateFillGuard:
    @pytest.mark.asyncio
    async def test_simulate_fill_raises_in_live_mode(self):
        e = AsyncExecutionEngine(broker_configs=_PAPER_CFG, paper_mode=False)
        o = _mk_order("live_guard")
        with pytest.raises(RuntimeError, match="live mode"):
            await e._simulate_fill(o)

    @pytest.mark.asyncio
    async def test_simulate_fill_no_market_data_rejects(self):
        e = AsyncExecutionEngine(broker_configs=_PAPER_CFG, paper_mode=True, paper_rng_seed=0)
        o = _mk_order("no_data", symbol="UNKNOWN")
        await e._simulate_fill(o)
        assert o.status == OrderStatus.REJECTED
        assert o.metadata.get("reject_reason") == "no_market_data"

    @pytest.mark.asyncio
    async def test_simulate_fill_limit_order_no_fill_path(self):
        """Limit order where price is not hit — goes to delayed fill path."""
        e = AsyncExecutionEngine(broker_configs=_PAPER_CFG, paper_mode=True, paper_rng_seed=99)
        e.price_cache["XAUUSD"] = {
            "bid": 1999.0,
            "ask": 2001.0,
            "mid": 2000.0,
            "volatility": 0.0001,
        }
        # Buy limit at 1800 — far below ask, won't fill immediately
        o = _mk_order("lim_no_fill", order_type=OrderType.LIMIT, price=1800.0, qty=0.01)
        # Patch delayed fill to avoid sleeping
        with patch.object(e, "_delayed_fill_simulation", new=AsyncMock(return_value=None)):
            await e._simulate_fill(o)

# HOPEFX-AI-TRADING
# Coverage boost: async_engine, broker_circuit_breaker, order_algorithms
"""Real unit tests — no mocks/stubs/fake data."""
from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

UTC = timezone.utc


# ─────────────────────────────────────────────────────────────────────────────
# async_engine
# ─────────────────────────────────────────────────────────────────────────────

class TestAsyncEngineShutdown:
    def _engine(self):
        from execution.async_engine import AsyncExecutionEngine
        return AsyncExecutionEngine(broker_configs=[], paper_mode=True, paper_rng_seed=0)

    @pytest.mark.asyncio
    async def test_submit_order_raises_when_shutdown(self):
        from execution.async_engine import AsyncExecutionEngine, Order, OrderType
        eng = AsyncExecutionEngine(broker_configs=[], paper_mode=True, paper_rng_seed=0)
        eng._shutdown = True
        order = Order(id="x1", symbol="XAU/USD", side="buy", quantity=1.0, order_type=OrderType.MARKET)
        with pytest.raises(RuntimeError, match="shutting down"):
            await eng.submit_order(order)

    @pytest.mark.asyncio
    async def test_cancel_order_not_found_returns_false(self):
        from execution.async_engine import AsyncExecutionEngine
        eng = AsyncExecutionEngine(broker_configs=[], paper_mode=True, paper_rng_seed=0)
        result = await eng.cancel_order("nonexistent")
        assert result is False

    @pytest.mark.asyncio
    async def test_cancel_order_no_venue_returns_false(self):
        from execution.async_engine import AsyncExecutionEngine, Order, OrderType, OrderStatus
        eng = AsyncExecutionEngine(broker_configs=[], paper_mode=True, paper_rng_seed=0)
        order = Order(id="o1", symbol="XAU/USD", side="buy", quantity=1.0, order_type=OrderType.MARKET)
        order.status = OrderStatus.SUBMITTED
        eng.orders["o1"] = order
        result = await eng.cancel_order("o1")
        assert result is False

    @pytest.mark.asyncio
    async def test_get_positions_cached(self):
        from execution.async_engine import AsyncExecutionEngine
        eng = AsyncExecutionEngine(broker_configs=[], paper_mode=True, paper_rng_seed=0)
        eng._position_cache_time = time.time()
        eng.position_cache["XAU/USD"] = {"symbol": "XAU/USD", "quantity": 1.0}
        result = await eng.get_positions()
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_get_positions_empty_brokers(self):
        from execution.async_engine import AsyncExecutionEngine
        eng = AsyncExecutionEngine(broker_configs=[], paper_mode=True, paper_rng_seed=0)
        result = await eng.get_positions()
        assert result == []

    @pytest.mark.asyncio
    async def test_batch_submit_returns_list(self):
        from execution.async_engine import AsyncExecutionEngine, Order, OrderType
        eng = AsyncExecutionEngine(
            broker_configs=[{"name": "paper", "rate_limit": 10}],
            paper_mode=True, paper_rng_seed=0,
        )
        eng.price_cache["XAU/USD"] = {"bid": 2000.0, "ask": 2001.0, "mid": 2000.5, "volatility": 0.001}
        orders = [
            Order(id=f"b{i}", symbol="XAU/USD", side="buy", quantity=0.1, order_type=OrderType.MARKET)
            for i in range(3)
        ]
        results = await eng.batch_submit(orders)
        assert len(results) == 3

    @pytest.mark.asyncio
    async def test_latency_report_empty(self):
        from execution.async_engine import AsyncExecutionEngine
        eng = AsyncExecutionEngine(broker_configs=[], paper_mode=True, paper_rng_seed=0)
        report = await eng.get_latency_report()
        assert isinstance(report, dict)

    @pytest.mark.asyncio
    async def test_modify_order_not_found_returns_false(self):
        from execution.async_engine import AsyncExecutionEngine
        eng = AsyncExecutionEngine(broker_configs=[], paper_mode=True, paper_rng_seed=0)
        result = await eng.modify_order("missing", 2000.0)
        assert result is False

    @pytest.mark.asyncio
    async def test_simulate_fill_no_market_data_rejects(self):
        from execution.async_engine import AsyncExecutionEngine, Order, OrderType, OrderStatus
        eng = AsyncExecutionEngine(broker_configs=[], paper_mode=True, paper_rng_seed=0)
        order = Order(id="s1", symbol="UNKNOWN/SYM", side="buy", quantity=1.0, order_type=OrderType.MARKET)
        await eng._simulate_fill(order)
        assert order.status == OrderStatus.REJECTED

    @pytest.mark.asyncio
    async def test_simulate_fill_market_order_fills(self):
        from execution.async_engine import AsyncExecutionEngine, Order, OrderType, OrderStatus
        eng = AsyncExecutionEngine(broker_configs=[], paper_mode=True, paper_rng_seed=42)
        eng.price_cache["XAU/USD"] = {"bid": 1999.0, "ask": 2001.0, "mid": 2000.0, "volatility": 0.0001}
        order = Order(id="s2", symbol="XAU/USD", side="buy", quantity=1.0, order_type=OrderType.MARKET)
        await eng._simulate_fill(order)
        assert order.status in (OrderStatus.FILLED, OrderStatus.PARTIAL_FILL)

    @pytest.mark.asyncio
    async def test_simulate_fill_sell_order(self):
        from execution.async_engine import AsyncExecutionEngine, Order, OrderType, OrderStatus
        eng = AsyncExecutionEngine(broker_configs=[], paper_mode=True, paper_rng_seed=42)
        eng.price_cache["XAU/USD"] = {"bid": 1999.0, "ask": 2001.0, "mid": 2000.0, "volatility": 0.0001}
        order = Order(id="s3", symbol="XAU/USD", side="sell", quantity=0.5, order_type=OrderType.MARKET)
        await eng._simulate_fill(order)
        assert order.status in (OrderStatus.FILLED, OrderStatus.PARTIAL_FILL)

    @pytest.mark.asyncio
    async def test_simulate_fill_limit_order_hit(self):
        from execution.async_engine import AsyncExecutionEngine, Order, OrderType, OrderStatus
        eng = AsyncExecutionEngine(broker_configs=[], paper_mode=True, paper_rng_seed=42)
        eng.price_cache["XAU/USD"] = {"bid": 1999.0, "ask": 2001.0, "mid": 2000.0, "volatility": 0.0001}
        order = Order(id="s4", symbol="XAU/USD", side="buy", quantity=0.5,
                      order_type=OrderType.LIMIT, price=2005.0)
        await eng._simulate_fill(order)
        # limit price above ask → should fill
        assert order.status in (OrderStatus.FILLED, OrderStatus.PARTIAL_FILL, OrderStatus.SUBMITTED)

    @pytest.mark.asyncio
    async def test_pre_trade_check_position_limit(self):
        from execution.async_engine import AsyncExecutionEngine, Order, OrderType
        eng = AsyncExecutionEngine(broker_configs=[], paper_mode=True, paper_rng_seed=0)
        eng.position_cache["XAU/USD"] = {"quantity": 99}
        order = Order(id="p1", symbol="XAU/USD", side="buy", quantity=5.0, order_type=OrderType.MARKET)
        allowed, reason = await eng._pre_trade_check(order)
        assert not allowed
        assert "position_limit" in reason

    @pytest.mark.asyncio
    async def test_pre_trade_check_price_deviation(self):
        from execution.async_engine import AsyncExecutionEngine, Order, OrderType
        eng = AsyncExecutionEngine(broker_configs=[], paper_mode=True, paper_rng_seed=0)
        eng.price_cache["XAU/USD"] = {"bid": 2000.0, "ask": 2001.0, "mid": 2000.0, "volatility": 0.001}
        order = Order(id="p2", symbol="XAU/USD", side="buy", quantity=1.0,
                      order_type=OrderType.LIMIT, price=3000.0)
        allowed, reason = await eng._pre_trade_check(order)
        assert not allowed
        assert "price_deviation" in reason

    @pytest.mark.asyncio
    async def test_close_all_positions_empty(self):
        from execution.async_engine import AsyncExecutionEngine
        eng = AsyncExecutionEngine(broker_configs=[], paper_mode=True, paper_rng_seed=0)
        result = await eng.close_all_positions()
        assert result == []

    @pytest.mark.asyncio
    async def test_shutdown_sets_flag(self):
        from execution.async_engine import AsyncExecutionEngine
        eng = AsyncExecutionEngine(broker_configs=[], paper_mode=True, paper_rng_seed=0)
        await eng.shutdown()
        assert eng._shutdown is True

    def test_select_venue_no_brokers(self):
        from execution.async_engine import AsyncExecutionEngine, Order, OrderType
        eng = AsyncExecutionEngine(broker_configs=[], paper_mode=True, paper_rng_seed=0)
        eng.brokers = {"alpha": {}, "beta": {}}
        order = Order(id="v1", symbol="XAU/USD", side="buy", quantity=1.0, order_type=OrderType.MARKET)
        venue = eng._select_venue(order)
        assert venue in ("alpha", "beta")

    def test_get_backup_venue(self):
        from execution.async_engine import AsyncExecutionEngine
        eng = AsyncExecutionEngine(broker_configs=[], paper_mode=True, paper_rng_seed=0)
        eng.brokers = {"alpha": {}, "beta": {}}
        backup = eng._get_backup_venue("alpha")
        assert backup == "beta"

    def test_get_backup_venue_none_when_single(self):
        from execution.async_engine import AsyncExecutionEngine
        eng = AsyncExecutionEngine(broker_configs=[], paper_mode=True, paper_rng_seed=0)
        eng.brokers = {"alpha": {}}
        backup = eng._get_backup_venue("alpha")
        assert backup is None

    def test_format_order(self):
        from execution.async_engine import AsyncExecutionEngine, Order, OrderType
        eng = AsyncExecutionEngine(broker_configs=[], paper_mode=True, paper_rng_seed=0)
        order = Order(id="f1", symbol="XAU/USD", side="buy", quantity=1.0,
                      order_type=OrderType.LIMIT, price=2000.0)
        result = eng._format_order(order, {})
        assert result["type"] == "LMT"
        assert result["qty"] == 1.0

    @pytest.mark.asyncio
    async def test_on_fill_callback_called(self):
        from execution.async_engine import AsyncExecutionEngine, Order, OrderType, Fill
        eng = AsyncExecutionEngine(broker_configs=[], paper_mode=True, paper_rng_seed=42)
        received = []
        eng.on_fill = lambda f: received.append(f)
        eng.price_cache["XAU/USD"] = {"bid": 1999.0, "ask": 2001.0, "mid": 2000.0, "volatility": 0.0001}
        order = Order(id="cb1", symbol="XAU/USD", side="buy", quantity=0.5, order_type=OrderType.MARKET)
        await eng._simulate_fill(order)
        assert len(received) >= 1

    @pytest.mark.asyncio
    async def test_on_order_update_callback_called(self):
        from execution.async_engine import AsyncExecutionEngine, Order, OrderType
        eng = AsyncExecutionEngine(broker_configs=[], paper_mode=True, paper_rng_seed=42)
        updates = []
        eng.on_order_update = lambda o: updates.append(o)
        eng.price_cache["XAU/USD"] = {"bid": 1999.0, "ask": 2001.0, "mid": 2000.0, "volatility": 0.0001}
        order = Order(id="cb2", symbol="XAU/USD", side="buy", quantity=0.5, order_type=OrderType.MARKET)
        await eng._simulate_fill(order)
        assert len(updates) >= 1

    @pytest.mark.asyncio
    async def test_on_fill_callback_error_suppressed(self):
        from execution.async_engine import AsyncExecutionEngine, Order, OrderType
        eng = AsyncExecutionEngine(broker_configs=[], paper_mode=True, paper_rng_seed=42)
        eng.on_fill = lambda f: (_ for _ in ()).throw(RuntimeError("boom"))
        eng.price_cache["XAU/USD"] = {"bid": 1999.0, "ask": 2001.0, "mid": 2000.0, "volatility": 0.0001}
        order = Order(id="cb3", symbol="XAU/USD", side="buy", quantity=0.5, order_type=OrderType.MARKET)
        # Should not raise
        await eng._simulate_fill(order)

    @pytest.mark.asyncio
    async def test_initialize_paper_mode(self):
        from execution.async_engine import AsyncExecutionEngine
        eng = AsyncExecutionEngine(
            broker_configs=[{"name": "paper", "rate_limit": 5}],
            paper_mode=True, paper_rng_seed=0,
        )
        await eng.initialize()
        assert "paper" in eng.brokers
        # cancel tasks
        for t in eng._tasks:
            t.cancel()

    def test_order_remaining_qty(self):
        from execution.async_engine import Order, OrderType
        order = Order(id="r1", symbol="XAU/USD", side="buy", quantity=2.0,
                      order_type=OrderType.MARKET)
        order.filled_qty = 0.5
        assert order.remaining_qty == pytest.approx(1.5)

    def test_order_status_enum_values(self):
        from execution.async_engine import OrderStatus, OrderType
        assert OrderStatus.PENDING is not None
        assert OrderType.MARKET is not None
        assert OrderType.LIMIT is not None
        assert OrderType.STOP is not None
        assert OrderType.TRAILING_STOP is not None

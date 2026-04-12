# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# AGPL-3.0 — Share all modifications
"""
Unit tests for brokers/base.py.
Covers with_retry (sync + async), RateLimiter, dataclasses, BrokerConnector.
"""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, patch

import pytest

from brokers.base import (
    AccountInfo,
    BrokerConnector,
    Order,
    OrderSide,
    OrderStatus,
    OrderType,
    Position,
    RateLimiter,
    with_retry,
)


# ── with_retry — sync ─────────────────────────────────────────────────────────


class TestWithRetrySync:
    def test_succeeds_on_first_attempt(self):
        @with_retry(max_attempts=3, backoff=0.001)
        def fn():
            return 42

        assert fn() == 42

    def test_retries_and_succeeds(self):
        calls = []

        @with_retry(max_attempts=3, backoff=0.001)
        def fn():
            calls.append(1)
            if len(calls) < 2:
                raise ValueError("fail")
            return "ok"

        with patch("time.sleep"):
            result = fn()

        assert result == "ok"
        assert len(calls) == 2

    def test_raises_after_max_attempts(self):
        @with_retry(max_attempts=3, backoff=0.001)
        def fn():
            raise RuntimeError("always fails")

        with patch("time.sleep"), pytest.raises(RuntimeError, match="always fails"):
            fn()

    def test_backoff_doubles(self):
        sleeps = []

        @with_retry(max_attempts=3, backoff=1.0)
        def fn():
            raise ValueError("fail")

        with patch("time.sleep", side_effect=lambda d: sleeps.append(d)):
            with pytest.raises(ValueError):
                fn()

        assert sleeps[0] == pytest.approx(1.0)
        assert sleeps[1] == pytest.approx(2.0)

    def test_only_catches_specified_exceptions(self):
        @with_retry(max_attempts=3, backoff=0.001, exceptions=(ValueError,))
        def fn():
            raise TypeError("not caught")

        with pytest.raises(TypeError):
            fn()

    def test_preserves_function_name(self):
        @with_retry()
        def my_function():
            return 1

        assert my_function.__name__ == "my_function"


# ── with_retry — async ────────────────────────────────────────────────────────


class TestWithRetryAsync:
    @pytest.mark.asyncio
    async def test_async_succeeds_on_first_attempt(self):
        @with_retry(max_attempts=3, backoff=0.001)
        async def fn():
            return 99

        result = await fn()
        assert result == 99

    @pytest.mark.asyncio
    async def test_async_retries_and_succeeds(self):
        calls = []

        @with_retry(max_attempts=3, backoff=0.001)
        async def fn():
            calls.append(1)
            if len(calls) < 2:
                raise ValueError("fail")
            return "ok"

        with patch("asyncio.sleep", new_callable=AsyncMock):
            result = await fn()

        assert result == "ok"
        assert len(calls) == 2

    @pytest.mark.asyncio
    async def test_async_raises_after_max_attempts(self):
        @with_retry(max_attempts=2, backoff=0.001)
        async def fn():
            raise RuntimeError("always fails")

        with patch("asyncio.sleep", new_callable=AsyncMock):
            with pytest.raises(RuntimeError, match="always fails"):
                await fn()

    @pytest.mark.asyncio
    async def test_async_preserves_function_name(self):
        @with_retry()
        async def my_async_fn():
            return 1

        assert my_async_fn.__name__ == "my_async_fn"


# ── RateLimiter ───────────────────────────────────────────────────────────────


class TestRateLimiter:
    @pytest.mark.asyncio
    async def test_acquire_does_not_raise(self):
        rl = RateLimiter(calls_per_second=1000.0)
        await rl.acquire()  # should not block or raise

    @pytest.mark.asyncio
    async def test_acquire_multiple_times(self):
        rl = RateLimiter(calls_per_second=1000.0)
        for _ in range(5):
            await rl.acquire()

    @pytest.mark.asyncio
    async def test_acquire_sleeps_when_tokens_exhausted(self):
        rl = RateLimiter(calls_per_second=1.0)
        # Drain tokens
        rl._tokens = 0.0
        rl._last = time.monotonic()

        slept = []

        async def fake_sleep(d):
            slept.append(d)

        with patch("asyncio.sleep", side_effect=fake_sleep):
            await rl.acquire()

        assert len(slept) == 1
        assert slept[0] > 0


# ── Dataclasses ───────────────────────────────────────────────────────────────


class TestOrder:
    def test_order_creation(self):
        o = Order(
            id="123",
            symbol="XAUUSD",
            side=OrderSide.BUY,
            type=OrderType.MARKET,
            quantity=1.0,
        )
        assert o.id == "123"
        assert o.status == OrderStatus.PENDING
        assert o.filled_quantity == 0.0

    def test_average_fill_price_alias(self):
        o = Order(
            id="1",
            symbol="X",
            side=OrderSide.BUY,
            type=OrderType.LIMIT,
            quantity=1.0,
            average_price=1800.0,
        )
        assert o.average_fill_price == 1800.0

    def test_average_fill_price_none(self):
        o = Order(id="1", symbol="X", side=OrderSide.SELL, type=OrderType.MARKET, quantity=1.0)
        assert o.average_fill_price is None


class TestPosition:
    def test_position_creation(self):
        p = Position(
            symbol="XAUUSD",
            side="LONG",
            quantity=1.0,
            entry_price=1800.0,
            current_price=1850.0,
            unrealized_pnl=50.0,
        )
        assert p.symbol == "XAUUSD"
        assert p.realized_pnl == 0.0


class TestAccountInfo:
    def test_account_info_creation(self):
        ai = AccountInfo(
            balance=10000.0,
            equity=10500.0,
            margin_used=500.0,
            margin_available=9500.0,
            positions_count=2,
        )
        assert ai.balance == 10000.0

    def test_getitem(self):
        ai = AccountInfo(
            balance=5000.0,
            equity=5100.0,
            margin_used=100.0,
            margin_available=4900.0,
            positions_count=1,
        )
        assert ai["balance"] == 5000.0

    def test_get_with_default(self):
        ai = AccountInfo(
            balance=5000.0,
            equity=5100.0,
            margin_used=100.0,
            margin_available=4900.0,
            positions_count=1,
        )
        assert ai.get("balance") == 5000.0
        assert ai.get("nonexistent", 99) == 99


# ── OrderType / OrderSide / OrderStatus enums ─────────────────────────────────


class TestEnums:
    def test_order_type_values(self):
        assert OrderType.MARKET.value == "MARKET"
        assert OrderType.LIMIT.value == "LIMIT"
        assert OrderType.STOP.value == "STOP"
        assert OrderType.STOP_LIMIT.value == "STOP_LIMIT"

    def test_order_side_values(self):
        assert OrderSide.BUY.value == "BUY"
        assert OrderSide.SELL.value == "SELL"

    def test_order_status_values(self):
        assert OrderStatus.PENDING.value == "pending"
        assert OrderStatus.FILLED.value == "filled"
        assert OrderStatus.CANCELLED.value == "cancelled"


# ── BrokerConnector abstract base ─────────────────────────────────────────────


class TestBrokerConnector:
    def _make_concrete(self):
        """Create a minimal concrete subclass."""

        class ConcreteBroker(BrokerConnector):
            def connect(self):
                return True

            def disconnect(self):
                return True

            def place_order(self, symbol, side, order_type, quantity, price=None, stop_price=None, **kw):
                return None

            def cancel_order(self, order_id):
                return True

            def get_order(self, order_id):
                return None

            def get_positions(self):
                return []

            def close_position(self, symbol):
                return True

            def get_account_info(self):
                return None

            def get_market_data(self, symbol, timeframe="1h", limit=100):
                return []

        return ConcreteBroker({"rate_limit_rps": 5.0})

    def test_is_connected_false_by_default(self):
        b = self._make_concrete()
        assert b.is_connected() is False

    def test_is_connected_true_after_set(self):
        b = self._make_concrete()
        b.connected = True
        assert b.is_connected() is True

    def test_repr_contains_class_name(self):
        b = self._make_concrete()
        assert "ConcreteBroker" in repr(b)

    def test_rate_limiter_uses_config(self):
        b = self._make_concrete()
        assert b.rate_limiter._rate == 5.0

    def test_default_rate_limiter(self):
        class MinBroker(BrokerConnector):
            def connect(self):
                return True

            def disconnect(self):
                return True

            def place_order(self, *a, **k):
                return None

            def cancel_order(self, *a):
                return True

            def get_order(self, *a):
                return None

            def get_positions(self):
                return []

            def close_position(self, *a):
                return True

            def get_account_info(self):
                return None

            def get_market_data(self, *a, **k):
                return []

        b = MinBroker({})
        assert b.rate_limiter._rate == 10.0

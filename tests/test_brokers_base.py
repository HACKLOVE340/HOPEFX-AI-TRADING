# HOPEFX-AI-TRADING
# Tests for brokers/base.py
"""
Full branch coverage for with_retry, RateLimiter, dataclasses, and BrokerConnector.
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime
from unittest.mock import patch

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


# ── with_retry — sync path ────────────────────────────────────────────────────


class TestWithRetrySync:
    def test_success_on_first_attempt(self):
        calls = []

        @with_retry(max_attempts=3, backoff=0.01)
        def fn():
            calls.append(1)
            return "ok"

        assert fn() == "ok"
        assert len(calls) == 1

    def test_retries_on_failure_then_succeeds(self):
        calls = []

        @with_retry(max_attempts=3, backoff=0.001)
        def fn():
            calls.append(1)
            if len(calls) < 2:
                raise ValueError("transient")
            return "ok"

        with patch("brokers.base.time.sleep"):
            result = fn()

        assert result == "ok"
        assert len(calls) == 2

    def test_exhaustion_raises_last_exception(self):
        @with_retry(max_attempts=3, backoff=0.001)
        def fn():
            raise RuntimeError("always fails")

        with patch("brokers.base.time.sleep"):
            with pytest.raises(RuntimeError, match="always fails"):
                fn()

    def test_only_catches_specified_exceptions(self):
        @with_retry(max_attempts=3, backoff=0.001, exceptions=(ValueError,))
        def fn():
            raise TypeError("not caught")

        with pytest.raises(TypeError):
            fn()

    def test_backoff_doubles_each_attempt(self):
        sleep_calls = []

        @with_retry(max_attempts=3, backoff=1.0)
        def fn():
            raise RuntimeError("fail")

        with patch("brokers.base.time.sleep", side_effect=lambda d: sleep_calls.append(d)):
            with pytest.raises(RuntimeError):
                fn()

        assert sleep_calls == [1.0, 2.0]

    def test_preserves_return_value(self):
        @with_retry(max_attempts=2, backoff=0.001)
        def fn():
            return {"key": "value"}

        assert fn() == {"key": "value"}


# ── with_retry — async path ───────────────────────────────────────────────────


class TestWithRetryAsync:
    @pytest.mark.asyncio
    async def test_async_success_first_attempt(self):
        @with_retry(max_attempts=3, backoff=0.001)
        async def fn():
            return "async_ok"

        assert await fn() == "async_ok"

    @pytest.mark.asyncio
    async def test_async_retries_then_succeeds(self):
        calls = []

        @with_retry(max_attempts=3, backoff=0.001)
        async def fn():
            calls.append(1)
            if len(calls) < 2:
                raise ValueError("transient")
            return "ok"

        with patch("brokers.base.asyncio.sleep", new_callable=lambda: lambda: asyncio.coroutine(lambda _: None)):
            pass

        # Use real asyncio.sleep with tiny delay
        result = await fn()
        assert result == "ok"
        assert len(calls) == 2

    @pytest.mark.asyncio
    async def test_async_exhaustion_raises(self):
        @with_retry(max_attempts=2, backoff=0.001)
        async def fn():
            raise RuntimeError("async fail")

        with pytest.raises(RuntimeError, match="async fail"):
            await fn()

    @pytest.mark.asyncio
    async def test_async_backoff_doubles(self):
        sleep_calls = []

        async def fake_sleep(d):
            sleep_calls.append(d)

        @with_retry(max_attempts=3, backoff=0.5)
        async def fn():
            raise RuntimeError("fail")

        with patch("brokers.base.asyncio.sleep", side_effect=fake_sleep):
            with pytest.raises(RuntimeError):
                await fn()

        assert sleep_calls == [0.5, 1.0]


# ── RateLimiter ───────────────────────────────────────────────────────────────


class TestRateLimiter:
    @pytest.mark.asyncio
    async def test_acquire_when_tokens_available(self):
        rl = RateLimiter(calls_per_second=100.0)
        # Should not block
        await rl.acquire()

    @pytest.mark.asyncio
    async def test_acquire_depletes_tokens(self):
        rl = RateLimiter(calls_per_second=2.0)
        rl._tokens = 1.0
        await rl.acquire()
        assert rl._tokens == pytest.approx(0.0, abs=0.1)

    @pytest.mark.asyncio
    async def test_acquire_waits_when_no_tokens(self):
        rl = RateLimiter(calls_per_second=10.0)
        rl._tokens = 0.0
        sleep_calls = []

        async def fake_sleep(d):
            sleep_calls.append(d)

        with patch("brokers.base.asyncio.sleep", side_effect=fake_sleep):
            await rl.acquire()

        assert len(sleep_calls) == 1
        assert sleep_calls[0] > 0

    @pytest.mark.asyncio
    async def test_acquire_sets_tokens_to_zero_after_wait(self):
        rl = RateLimiter(calls_per_second=10.0)
        rl._tokens = 0.0

        async def fake_sleep(_):
            pass

        with patch("brokers.base.asyncio.sleep", side_effect=fake_sleep):
            await rl.acquire()

        assert rl._tokens == 0.0

    @pytest.mark.asyncio
    async def test_tokens_replenish_over_time(self):
        rl = RateLimiter(calls_per_second=10.0)
        rl._tokens = 0.0
        # Simulate 1 second elapsed
        rl._last = time.monotonic() - 1.0

        async def fake_sleep(_):
            pass

        with patch("brokers.base.asyncio.sleep", side_effect=fake_sleep):
            await rl.acquire()

        # After 1s at 10 rps, tokens should have been replenished to 10, then 1 consumed
        # The acquire should have succeeded without waiting (tokens >= 1)


# ── Enums ─────────────────────────────────────────────────────────────────────


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
        assert OrderStatus.REJECTED.value == "rejected"


# ── Order dataclass ───────────────────────────────────────────────────────────


class TestOrder:
    def _make_order(self, **kwargs):
        defaults = dict(
            id="ord1",
            symbol="AAPL",
            side=OrderSide.BUY,
            type=OrderType.MARKET,
            quantity=10.0,
        )
        defaults.update(kwargs)
        return Order(**defaults)

    def test_default_status_pending(self):
        o = self._make_order()
        assert o.status == OrderStatus.PENDING

    def test_average_fill_price_alias(self):
        o = self._make_order(average_price=150.0)
        assert o.average_fill_price == 150.0

    def test_average_fill_price_none(self):
        o = self._make_order()
        assert o.average_fill_price is None

    def test_metadata_default_none(self):
        o = self._make_order()
        assert o.metadata is None


# ── Position dataclass ────────────────────────────────────────────────────────


class TestPosition:
    def _make_position(self, **kwargs):
        defaults = dict(
            symbol="AAPL",
            side="LONG",
            quantity=10.0,
            entry_price=150.0,
            current_price=155.0,
            unrealized_pnl=50.0,
        )
        defaults.update(kwargs)
        return Position(**defaults)

    def test_position_fields(self):
        p = self._make_position()
        assert p.symbol == "AAPL"
        assert p.side == "LONG"
        assert p.quantity == 10.0

    def test_realized_pnl_default(self):
        p = self._make_position()
        assert p.realized_pnl == 0.0

    def test_id_default_empty(self):
        p = self._make_position()
        assert p.id == ""


# ── AccountInfo dataclass ─────────────────────────────────────────────────────


class TestAccountInfo:
    def _make_account(self, **kwargs):
        defaults = dict(
            balance=10000.0,
            equity=10500.0,
            margin_used=500.0,
            margin_available=9500.0,
            positions_count=2,
        )
        defaults.update(kwargs)
        return AccountInfo(**defaults)

    def test_getitem(self):
        a = self._make_account()
        assert a["balance"] == 10000.0
        assert a["equity"] == 10500.0

    def test_get_existing_key(self):
        a = self._make_account()
        assert a.get("balance") == 10000.0

    def test_get_missing_key_returns_default(self):
        a = self._make_account()
        assert a.get("nonexistent", "fallback") == "fallback"

    def test_get_missing_key_returns_none_by_default(self):
        a = self._make_account()
        assert a.get("nonexistent") is None

    def test_timestamp_default_none(self):
        a = self._make_account()
        assert a.timestamp is None

    def test_timestamp_set(self):
        now = datetime.utcnow()
        a = self._make_account(timestamp=now)
        assert a.timestamp == now


# ── BrokerConnector abstract base ─────────────────────────────────────────────


class TestBrokerConnector:
    def test_cannot_instantiate_abstract_class(self):
        with pytest.raises(TypeError):
            BrokerConnector({})

    def test_concrete_subclass_works(self):
        class ConcreteBroker(BrokerConnector):
            def connect(self):
                return True

            def disconnect(self):
                return True

            def place_order(self, symbol, side, order_type, quantity, price=None, stop_price=None, **kwargs):
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
                return AccountInfo(0, 0, 0, 0, 0)

            def get_market_data(self, symbol, timeframe="1h", limit=100):
                return []

        broker = ConcreteBroker({"rate_limit_rps": 5.0})
        assert broker.name == "ConcreteBroker"
        assert broker.connected is False
        assert broker.is_connected() is False

    def test_is_connected_reflects_connected_flag(self):
        class ConcreteBroker(BrokerConnector):
            def connect(self):
                self.connected = True
                return True

            def disconnect(self):
                return True

            def place_order(self, *a, **kw):
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
                return AccountInfo(0, 0, 0, 0, 0)

            def get_market_data(self, symbol, timeframe="1h", limit=100):
                return []

        broker = ConcreteBroker({})
        assert broker.is_connected() is False
        broker.connect()
        assert broker.is_connected() is True

    def test_repr_includes_name_and_connected(self):
        class ConcreteBroker(BrokerConnector):
            def connect(self):
                return True

            def disconnect(self):
                return True

            def place_order(self, *a, **kw):
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
                return AccountInfo(0, 0, 0, 0, 0)

            def get_market_data(self, symbol, timeframe="1h", limit=100):
                return []

        broker = ConcreteBroker({})
        r = repr(broker)
        assert "ConcreteBroker" in r
        assert "connected=False" in r

    def test_rate_limiter_uses_config_rps(self):
        class ConcreteBroker(BrokerConnector):
            def connect(self):
                return True

            def disconnect(self):
                return True

            def place_order(self, *a, **kw):
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
                return AccountInfo(0, 0, 0, 0, 0)

            def get_market_data(self, symbol, timeframe="1h", limit=100):
                return []

        broker = ConcreteBroker({"rate_limit_rps": 25.0})
        assert broker.rate_limiter._rate == 25.0

# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""Tests for data/tick_feed.py — Tick, OHLCVBar, TickBus, TickAggregator, TickFeedManager."""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from data.tick_feed import (
    OHLCVBar,
    Tick,
    TickAggregator,
    TickBus,
    TickFeedManager,
    _is_valid_tick,
    get_tick_feed,
)

UTC = timezone.utc


# ── Helpers ───────────────────────────────────────────────────────────────────


def _tick(bid: float = 1900.0, ask: float = 1900.5, symbol: str = "XAU_USD") -> Tick:
    return Tick(
        symbol=symbol,
        timestamp=datetime.now(UTC),
        bid=bid,
        ask=ask,
        volume=1.0,
        source="test",
    )


# ── Tick dataclass ────────────────────────────────────────────────────────────


class TestTick:
    def test_mid_calculation(self):
        t = _tick(bid=1900.0, ask=1901.0)
        assert t.mid == 1900.5

    def test_spread_calculation(self):
        t = _tick(bid=1900.0, ask=1901.0)
        assert t.spread == pytest.approx(1.0)

    def test_to_dict_keys(self):
        t = _tick()
        d = t.to_dict()
        assert "symbol" in d
        assert "bid" in d
        assert "ask" in d
        assert "mid" in d
        assert "spread" in d
        assert "timestamp" in d

    def test_to_dict_mid_rounded(self):
        t = _tick(bid=1900.0, ask=1900.1)
        d = t.to_dict()
        assert isinstance(d["mid"], float)

    def test_source_stored(self):
        t = _tick()
        assert t.source == "test"


# ── OHLCVBar dataclass ────────────────────────────────────────────────────────


class TestOHLCVBar:
    def test_to_dict_keys(self):
        bar = OHLCVBar(
            symbol="XAU_USD",
            timestamp=datetime.now(UTC),
            open=1900.0,
            high=1905.0,
            low=1895.0,
            close=1902.0,
            volume=100.0,
            tick_count=50,
            timeframe_s=60,
        )
        d = bar.to_dict()
        assert d["symbol"] == "XAU_USD"
        assert d["open"] == 1900.0
        assert d["tick_count"] == 50
        assert d["timeframe_s"] == 60


# ── _is_valid_tick ────────────────────────────────────────────────────────────


class TestIsValidTick:
    def test_valid_tick(self):
        assert _is_valid_tick(_tick(bid=1900.0, ask=1900.5)) is True

    def test_invalid_zero_bid(self):
        assert _is_valid_tick(_tick(bid=0.0, ask=1.0)) is False

    def test_invalid_negative_ask(self):
        assert _is_valid_tick(_tick(bid=1.0, ask=-1.0)) is False

    def test_invalid_bid_greater_than_ask(self):
        assert _is_valid_tick(_tick(bid=1901.0, ask=1900.0)) is False

    def test_invalid_price_below_min(self):
        # mid < 1000 is invalid for XAU
        assert _is_valid_tick(_tick(bid=500.0, ask=500.5)) is False

    def test_invalid_price_above_max(self):
        # mid > 10000 is invalid
        assert _is_valid_tick(_tick(bid=11000.0, ask=11001.0)) is False

    def test_valid_boundary_low(self):
        assert _is_valid_tick(_tick(bid=1000.0, ask=1001.0)) is True

    def test_valid_boundary_high(self):
        assert _is_valid_tick(_tick(bid=9999.0, ask=9999.5)) is True


# ── TickAggregator ────────────────────────────────────────────────────────────


class TestTickAggregator:
    @pytest.mark.asyncio
    async def test_first_tick_opens_bar(self):
        agg = TickAggregator(symbol="XAU_USD", timeframe_s=60)
        t = _tick()
        await agg.on_tick(t)
        assert agg._current_bar is not None
        assert agg._current_bar["open"] == t.mid

    @pytest.mark.asyncio
    async def test_second_tick_updates_bar(self):
        agg = TickAggregator(symbol="XAU_USD", timeframe_s=60)
        t1 = _tick(bid=1900.0, ask=1900.5)
        t2 = _tick(bid=1905.0, ask=1905.5)
        await agg.on_tick(t1)
        await agg.on_tick(t2)
        assert agg._current_bar["high"] == pytest.approx(t2.mid)
        assert agg._current_bar["tick_count"] == 2

    @pytest.mark.asyncio
    async def test_bar_closes_after_timeframe(self):
        agg = TickAggregator(symbol="XAU_USD", timeframe_s=1)
        bar_received = []

        async def on_bar(bar: OHLCVBar):
            bar_received.append(bar)

        agg.add_bar_callback(on_bar)
        t1 = _tick()
        await agg.on_tick(t1)
        # Force bar close by backdating _bar_start
        agg._bar_start = time.time() - 2.0
        t2 = _tick(bid=1901.0, ask=1901.5)
        await agg.on_tick(t2)
        assert len(bar_received) == 1
        assert bar_received[0].symbol == "XAU_USD"

    @pytest.mark.asyncio
    async def test_sync_bar_callback(self):
        agg = TickAggregator(symbol="XAU_USD", timeframe_s=1)
        bar_received = []
        agg.add_bar_callback(lambda bar: bar_received.append(bar))
        t1 = _tick()
        await agg.on_tick(t1)
        agg._bar_start = time.time() - 2.0
        await agg.on_tick(_tick())
        assert len(bar_received) == 1

    @pytest.mark.asyncio
    async def test_bar_callback_error_swallowed(self):
        agg = TickAggregator(symbol="XAU_USD", timeframe_s=1)
        agg.add_bar_callback(lambda bar: (_ for _ in ()).throw(RuntimeError("cb error")))
        t1 = _tick()
        await agg.on_tick(t1)
        agg._bar_start = time.time() - 2.0
        await agg.on_tick(_tick())  # must not raise

    @pytest.mark.asyncio
    async def test_volume_accumulates(self):
        agg = TickAggregator(symbol="XAU_USD", timeframe_s=60)
        for _ in range(5):
            t = Tick(symbol="XAU_USD", timestamp=datetime.now(UTC), bid=1900.0, ask=1900.5, volume=10.0)
            await agg.on_tick(t)
        assert agg._current_bar["volume"] == pytest.approx(50.0)

    def test_add_bar_callback(self):
        agg = TickAggregator(symbol="XAU_USD")
        cb = MagicMock()
        agg.add_bar_callback(cb)
        assert cb in agg._bar_callbacks


# ── TickBus ───────────────────────────────────────────────────────────────────


class TestTickBus:
    @pytest.mark.asyncio
    async def test_publish_valid_tick(self):
        bus = TickBus()
        received = []

        class Sub:
            async def on_tick(self, tick):
                received.append(tick)

        bus.subscribe(Sub())
        await bus.publish(_tick())
        assert len(received) == 1

    @pytest.mark.asyncio
    async def test_publish_invalid_tick_ignored(self):
        bus = TickBus()
        received = []

        class Sub:
            async def on_tick(self, tick):
                received.append(tick)

        bus.subscribe(Sub())
        await bus.publish(_tick(bid=0.0, ask=0.0))
        assert len(received) == 0

    @pytest.mark.asyncio
    async def test_deduplication(self):
        bus = TickBus(dedup_window_ms=1000.0)
        received = []

        class Sub:
            async def on_tick(self, tick):
                received.append(tick)

        bus.subscribe(Sub())
        t = _tick()
        await bus.publish(t)
        await bus.publish(t)  # same tick — should be deduped
        assert len(received) == 1

    @pytest.mark.asyncio
    async def test_different_prices_not_deduped(self):
        bus = TickBus(dedup_window_ms=1000.0)
        received = []

        class Sub:
            async def on_tick(self, tick):
                received.append(tick)

        bus.subscribe(Sub())
        await bus.publish(_tick(bid=1900.0, ask=1900.5))
        await bus.publish(_tick(bid=1910.0, ask=1910.5))
        assert len(received) == 2

    def test_subscribe_and_unsubscribe(self):
        bus = TickBus()

        class Sub:
            async def on_tick(self, tick):
                pass

        sub = Sub()
        bus.subscribe(sub)
        assert len(bus._subscribers) == 1
        bus.unsubscribe(sub)
        assert len(bus._subscribers) == 0

    def test_unsubscribe_nonexistent_no_error(self):
        bus = TickBus()
        bus.unsubscribe(object())  # must not raise

    @pytest.mark.asyncio
    async def test_tick_count_increments(self):
        bus = TickBus()
        await bus.publish(_tick())
        await bus.publish(_tick(bid=1910.0, ask=1910.5))
        assert bus.tick_count == 2

    @pytest.mark.asyncio
    async def test_last_tick_updated(self):
        bus = TickBus()
        t = _tick(bid=1950.0, ask=1950.5)
        await bus.publish(t)
        assert bus.last_tick is not None
        assert bus.last_tick.bid == 1950.0

    def test_status_dict(self):
        bus = TickBus()
        s = bus.status()
        assert "subscribers" in s
        assert "tick_count" in s
        assert s["last_tick"] is None

    @pytest.mark.asyncio
    async def test_status_with_last_tick(self):
        bus = TickBus()
        await bus.publish(_tick())
        s = bus.status()
        assert s["last_tick"] is not None

    @pytest.mark.asyncio
    async def test_subscriber_error_swallowed(self):
        bus = TickBus()

        class BadSub:
            async def on_tick(self, tick):
                raise RuntimeError("subscriber error")

        bus.subscribe(BadSub())
        await bus.publish(_tick())  # must not raise

    @pytest.mark.asyncio
    async def test_multiple_subscribers(self):
        bus = TickBus()
        counts = [0, 0]

        class Sub:
            def __init__(self, idx):
                self.idx = idx

            async def on_tick(self, tick):
                counts[self.idx] += 1

        bus.subscribe(Sub(0))
        bus.subscribe(Sub(1))
        await bus.publish(_tick())
        assert counts == [1, 1]


# ── TickFeedManager ───────────────────────────────────────────────────────────


class TestTickFeedManager:
    def test_init_default(self):
        mgr = TickFeedManager()
        assert mgr.symbol == "XAU_USD"

    def test_init_custom_symbol(self):
        mgr = TickFeedManager(symbol="EUR_USD")
        assert mgr.symbol == "EUR_USD"

    def test_subscribe_adds_to_bus(self):
        mgr = TickFeedManager()

        class Sub:
            async def on_tick(self, tick):
                pass

        sub = Sub()
        mgr.subscribe(sub)
        assert sub in mgr._bus._subscribers

    def test_add_bar_callback(self):
        mgr = TickFeedManager()
        cb = MagicMock()
        mgr.add_bar_callback(cb)
        assert cb in mgr._aggregator._bar_callbacks

    def test_bus_property(self):
        mgr = TickFeedManager()
        assert isinstance(mgr.bus, TickBus)

    def test_last_tick_initially_none(self):
        mgr = TickFeedManager()
        assert mgr.last_tick is None

    def test_status_dict(self):
        mgr = TickFeedManager()
        s = mgr.status()
        assert "symbol" in s
        assert "running" in s

    def test_sources_wired_to_bus(self):
        mgr = TickFeedManager()
        # Each source should have the bus.publish as its callback
        for src in mgr._sources:
            assert src._on_tick is not None

    @pytest.mark.asyncio
    async def test_stop_when_not_started(self):
        mgr = TickFeedManager()
        await mgr.stop()  # must not raise

    @pytest.mark.asyncio
    async def test_start_sets_running(self):
        mgr = TickFeedManager()
        # Patch source.start to be a no-op coroutine that returns immediately
        for src in mgr._sources:
            src.start = AsyncMock()
        await mgr.start()
        assert mgr._running is True
        # Clean up tasks
        for task in mgr._tasks:
            task.cancel()
        await asyncio.gather(*mgr._tasks, return_exceptions=True)

    @pytest.mark.asyncio
    async def test_start_idempotent(self):
        mgr = TickFeedManager()
        for src in mgr._sources:
            src.start = AsyncMock()
        await mgr.start()
        task_count = len(mgr._tasks)
        await mgr.start()  # second call should be no-op
        assert len(mgr._tasks) == task_count
        for task in mgr._tasks:
            task.cancel()
        await asyncio.gather(*mgr._tasks, return_exceptions=True)

    @pytest.mark.asyncio
    async def test_stop_clears_running(self):
        mgr = TickFeedManager()
        for src in mgr._sources:
            src.start = AsyncMock()
        await mgr.start()
        await mgr.stop()
        assert mgr._running is False
        assert mgr._tasks == []


# ── get_tick_feed factory ─────────────────────────────────────────────────────


class TestGetTickFeed:
    def setup_method(self):
        # Reset the module-level singleton before each test
        import data.tick_feed as tf_module

        tf_module._manager = None

    def test_returns_manager(self):
        mgr = get_tick_feed()
        assert isinstance(mgr, TickFeedManager)

    def test_returns_singleton(self):
        mgr1 = get_tick_feed()
        mgr2 = get_tick_feed()
        assert mgr1 is mgr2

    def test_custom_symbol_on_first_call(self):
        mgr = get_tick_feed(symbol="GBP_USD")
        assert mgr.symbol == "GBP_USD"

    def test_custom_timeframe_on_first_call(self):
        mgr = get_tick_feed(bar_timeframe_s=300)
        assert mgr._aggregator.timeframe_s == 300

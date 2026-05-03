# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
tests/test_data_layer.py
=========================
Comprehensive tests for all enhanced/new data layer components.

Coverage:
  - data_feed/nuclear_streamer.py  — deduplication, gap detection, latency histogram
  - market_data/feed_handler.py    — L2 book, trade classification, normalization
  - market_data/redis_cache.py     — TTL invalidation, stampede prevention, hot-key
  - data_layer/stream/publisher.py — Redis Streams publisher / consumer
  - data_layer/aggregator/ohlcv_builder.py — OHLCV bar builder
  - database/async_connection.py   — async pool, health monitor
  - database/repositories/        — Trade, Position, Signal, MarketData, TickData
"""

from __future__ import annotations


import asyncio
import time
import uuid
from datetime import datetime, timezone

import pytest

UTC = timezone.utc


# ═══════════════════════════════════════════════════════════════════════════════
# NuclearStreamer — deduplication
# ═══════════════════════════════════════════════════════════════════════════════

class TestNuclearStreamerDedup:
    @pytest.mark.asyncio
    async def test_duplicate_discarded(self):
        from data_feed.nuclear_streamer import NuclearStreamer
        s = NuclearStreamer(prometheus_port=0)
        now = time.time()
        await s.process_tick(1900.0, now, "finnhub")
        await s.process_tick(1900.0, now, "finnhub")
        assert s._dedup_counts.get("finnhub", 0) == 1

    @pytest.mark.asyncio
    async def test_different_price_passes(self):
        from data_feed.nuclear_streamer import NuclearStreamer
        s = NuclearStreamer(prometheus_port=0)
        now = time.time()
        await s.process_tick(1900.0, now, "finnhub")
        await s.process_tick(1901.0, now, "finnhub")
        assert s._dedup_counts.get("finnhub", 0) == 0

    @pytest.mark.asyncio
    async def test_different_source_passes(self):
        from data_feed.nuclear_streamer import NuclearStreamer
        s = NuclearStreamer(prometheus_port=0)
        now = time.time()
        await s.process_tick(1900.0, now, "finnhub")
        await s.process_tick(1900.0, now, "polygon")
        assert s._dedup_counts.get("polygon", 0) == 0

    @pytest.mark.asyncio
    async def test_multiple_duplicates_counted(self):
        from data_feed.nuclear_streamer import NuclearStreamer
        s = NuclearStreamer(prometheus_port=0)
        now = time.time()
        await s.process_tick(1900.0, now, "finnhub")
        await s.process_tick(1900.0, now, "finnhub")
        await s.process_tick(1900.0, now, "finnhub")
        assert s._dedup_counts.get("finnhub", 0) == 2


# ═══════════════════════════════════════════════════════════════════════════════
# NuclearStreamer — sequence gap detection
# ═══════════════════════════════════════════════════════════════════════════════

class TestNuclearStreamerGap:
    @pytest.mark.asyncio
    async def test_gap_detected(self):
        from data_feed.nuclear_streamer import NuclearStreamer
        s = NuclearStreamer(prometheus_port=0)
        await s.process_tick(1900.0, time.time(), "finnhub", sequence=1)
        await s.process_tick(1901.0, time.time(), "finnhub", sequence=5)
        assert s._seq_gap_counts.get("finnhub", 0) == 1

    @pytest.mark.asyncio
    async def test_consecutive_no_gap(self):
        from data_feed.nuclear_streamer import NuclearStreamer
        s = NuclearStreamer(prometheus_port=0)
        await s.process_tick(1900.0, time.time(), "finnhub", sequence=1)
        await s.process_tick(1901.0, time.time(), "finnhub", sequence=2)
        assert s._seq_gap_counts.get("finnhub", 0) == 0

    @pytest.mark.asyncio
    async def test_out_of_order_discarded(self):
        from data_feed.nuclear_streamer import NuclearStreamer
        s = NuclearStreamer(prometheus_port=0)
        await s.process_tick(1900.0, time.time(), "finnhub", sequence=5)
        await s.process_tick(1901.0, time.time(), "finnhub", sequence=3)
        assert s._last_seq.get("finnhub") == 5

    @pytest.mark.asyncio
    async def test_no_sequence_no_gap(self):
        from data_feed.nuclear_streamer import NuclearStreamer
        s = NuclearStreamer(prometheus_port=0)
        await s.process_tick(1900.0, time.time(), "finnhub")
        await s.process_tick(1901.0, time.time(), "finnhub")
        assert s._seq_gap_counts.get("finnhub", 0) == 0


# ═══════════════════════════════════════════════════════════════════════════════
# NuclearStreamer — latency histogram
# ═══════════════════════════════════════════════════════════════════════════════

class TestNuclearStreamerHistogram:
    @pytest.mark.asyncio
    async def test_samples_recorded(self):
        from data_feed.nuclear_streamer import NuclearStreamer
        s = NuclearStreamer(prometheus_port=0)
        # Use distinct prices so each tick has a unique fingerprint (no dedup)
        for i in range(5):
            await s.process_tick(1900.0 + i * 0.01, time.time(), "finnhub")
        assert len(s._latency_samples.get("finnhub", [])) == 5

    @pytest.mark.asyncio
    async def test_percentile_float(self):
        from data_feed.nuclear_streamer import NuclearStreamer
        s = NuclearStreamer(prometheus_port=0)
        for i in range(10):
            await s.process_tick(1900.0 + i * 0.01, time.time(), "finnhub")
        p99 = s.latency_percentile("finnhub", 99.0)
        assert isinstance(p99, float) and p99 >= 0.0

    def test_percentile_none_no_samples(self):
        from data_feed.nuclear_streamer import NuclearStreamer
        s = NuclearStreamer(prometheus_port=0)
        assert s.latency_percentile("finnhub", 99.0) is None

    @pytest.mark.asyncio
    async def test_snapshot_keys(self):
        from data_feed.nuclear_streamer import NuclearStreamer
        s = NuclearStreamer(prometheus_port=0)
        # Unique price to avoid dedup
        await s.process_tick(1900.123, time.time(), "finnhub")
        snap = s.latency_histogram_snapshot("finnhub")
        for key in ("p50_ms", "p95_ms", "p99_ms", "p999_ms", "sample_count"):
            assert key in snap

    @pytest.mark.asyncio
    async def test_status_has_histogram(self):
        from data_feed.nuclear_streamer import NuclearStreamer
        s = NuclearStreamer(prometheus_port=0)
        await s.process_tick(1900.456, time.time(), "finnhub")
        st = s.status()
        assert "latency_histograms" in st
        assert "dedup_counts" in st
        assert "seq_gap_counts" in st


# ═══════════════════════════════════════════════════════════════════════════════
# FeedHandler — L2 order book
# ═══════════════════════════════════════════════════════════════════════════════

class TestL2OrderBook:
    def test_apply_bid(self):
        from market_data.feed_handler import L2OrderBook
        book = L2OrderBook(symbol="XAUUSD")
        book.apply_update("bid", 1900.0, 10.0)
        assert book.best_bid == 1900.0

    def test_apply_ask(self):
        from market_data.feed_handler import L2OrderBook
        book = L2OrderBook(symbol="XAUUSD")
        book.apply_update("ask", 1901.0, 8.0)
        assert book.best_ask == 1901.0

    def test_remove_level_size_zero(self):
        from market_data.feed_handler import L2OrderBook
        book = L2OrderBook(symbol="XAUUSD")
        book.apply_update("bid", 1900.0, 10.0)
        book.apply_update("bid", 1900.0, 0.0)
        assert book.best_bid == 0.0

    def test_mid_price(self):
        from market_data.feed_handler import L2OrderBook
        book = L2OrderBook(symbol="XAUUSD")
        book.apply_update("bid", 1900.0, 10.0)
        book.apply_update("ask", 1902.0, 8.0)
        assert book.mid == 1901.0

    def test_spread(self):
        from market_data.feed_handler import L2OrderBook
        book = L2OrderBook(symbol="XAUUSD")
        book.apply_update("bid", 1900.0, 10.0)
        book.apply_update("ask", 1902.0, 8.0)
        assert book.spread == 2.0

    def test_depth_imbalance_equal(self):
        from market_data.feed_handler import L2OrderBook
        book = L2OrderBook(symbol="XAUUSD")
        book.apply_update("bid", 1900.0, 10.0)
        book.apply_update("ask", 1901.0, 10.0)
        assert book.depth_imbalance == 0.0

    def test_to_dict_keys(self):
        from market_data.feed_handler import L2OrderBook
        book = L2OrderBook(symbol="XAUUSD")
        book.apply_update("bid", 1900.0, 5.0)
        book.apply_update("ask", 1901.0, 5.0)
        d = book.to_dict()
        for k in ("symbol", "best_bid", "best_ask", "mid", "spread", "bids", "asks"):
            assert k in d


class TestL2BookAggregator:
    def test_consolidated_merges_exchanges(self):
        from market_data.feed_handler import L2BookAggregator
        agg = L2BookAggregator()
        agg.apply_update("XAUUSD", "oanda", "bid", 1900.0, 10.0)
        agg.apply_update("XAUUSD", "binance", "bid", 1900.5, 5.0)
        agg.apply_update("XAUUSD", "oanda", "ask", 1901.0, 8.0)
        agg.apply_update("XAUUSD", "binance", "ask", 1901.5, 4.0)
        book = agg.consolidated_book("XAUUSD")
        assert book["best_bid"] == 1900.5
        assert book["best_ask"] == 1901.0
        assert book["exchange_count"] == 2

    def test_sizes_summed_same_price(self):
        from market_data.feed_handler import L2BookAggregator
        agg = L2BookAggregator()
        agg.apply_update("XAUUSD", "oanda", "bid", 1900.0, 10.0)
        agg.apply_update("XAUUSD", "binance", "bid", 1900.0, 5.0)
        book = agg.consolidated_book("XAUUSD")
        bid = next(b for b in book["bids"] if b["price"] == 1900.0)
        assert bid["size"] == 15.0

    def test_symbols_list(self):
        from market_data.feed_handler import L2BookAggregator
        agg = L2BookAggregator()
        agg.apply_update("XAUUSD", "oanda", "bid", 1900.0, 10.0)
        agg.apply_update("BTCUSD", "binance", "bid", 50000.0, 1.0)
        assert set(agg.symbols()) == {"XAUUSD", "BTCUSD"}


class TestTradeClassifier:
    def test_buy_above_mid(self):
        from market_data.feed_handler import TradeClassifier, TradeSide
        clf = TradeClassifier()
        assert clf.classify("XAUUSD", 1901.0, 1900.0) == TradeSide.BUY

    def test_sell_below_mid(self):
        from market_data.feed_handler import TradeClassifier, TradeSide
        clf = TradeClassifier()
        assert clf.classify("XAUUSD", 1899.0, 1900.0) == TradeSide.SELL

    def test_tick_test_uptick(self):
        from market_data.feed_handler import TradeClassifier, TradeSide
        clf = TradeClassifier()
        clf.classify("XAUUSD", 1899.0, 1900.0)
        result = clf.classify("XAUUSD", 1900.0, 1900.0)
        assert result == TradeSide.BUY

    def test_tick_test_downtick(self):
        from market_data.feed_handler import TradeClassifier, TradeSide
        clf = TradeClassifier()
        clf.classify("XAUUSD", 1901.0, 1900.0)
        result = clf.classify("XAUUSD", 1900.0, 1900.0)
        assert result == TradeSide.SELL

    def test_reset_clears_state(self):
        from market_data.feed_handler import TradeClassifier
        clf = TradeClassifier()
        clf.classify("XAUUSD", 1900.0, 1900.0)
        clf.reset("XAUUSD")
        assert clf._last_trade.get("XAUUSD") is None


class TestTickNormalizationPipeline:
    def _tick(self, bid=1900.0, ask=1901.0, age_s=0.0):
        from market_data.feed_handler import Tick
        from datetime import timedelta
        ts = datetime.now(UTC)
        if age_s:
            ts = ts - timedelta(seconds=age_s)
        return Tick("XAUUSD", ts, bid, ask, 10.0, 8.0, (bid+ask)/2, 1.0, "oanda")

    def test_valid_passes(self):
        from market_data.feed_handler import TickNormalizationPipeline
        pipe = TickNormalizationPipeline()
        assert pipe.process(self._tick()) is not None

    def test_spread_clamp_rejects(self):
        from market_data.feed_handler import TickNormalizationPipeline
        pipe = TickNormalizationPipeline(max_spread_bps=1.0)
        assert pipe.process(self._tick(bid=1900.0, ask=1910.0)) is None
        assert pipe.rejection_counts["spread_clamp"] == 1

    def test_stale_rejected(self):
        from market_data.feed_handler import TickNormalizationPipeline
        pipe = TickNormalizationPipeline(max_age_seconds=5.0)
        assert pipe.process(self._tick(age_s=10.0)) is None
        assert pipe.rejection_counts["stale"] == 1

    def test_stats_acceptance_rate(self):
        from market_data.feed_handler import TickNormalizationPipeline
        pipe = TickNormalizationPipeline()
        for _ in range(3):
            pipe.process(self._tick())
        stats = pipe.stats()
        assert stats["accepted"] == 3
        assert stats["acceptance_rate"] == 1.0


class TestFeedHandlerIntegration:
    def test_l2_update_and_consolidated(self):
        from market_data.feed_handler import FeedHandler
        fh = FeedHandler()
        fh.apply_l2_update("XAUUSD", "oanda", "bid", 1900.0, 10.0)
        fh.apply_l2_update("XAUUSD", "oanda", "ask", 1901.0, 8.0)
        book = fh.get_consolidated_book("XAUUSD")
        assert book["best_bid"] == 1900.0
        assert book["best_ask"] == 1901.0

    def test_pipeline_stats_keys(self):
        from market_data.feed_handler import FeedHandler
        fh = FeedHandler()
        stats = fh.pipeline_stats()
        assert "normalizer" in stats
        assert "ticks_processed" in stats

    def test_buy_sell_ratio_empty(self):
        from market_data.feed_handler import FeedHandler
        fh = FeedHandler()
        ratio = fh.get_buy_sell_ratio("XAUUSD")
        assert ratio["buy_ratio"] == 0.5
        assert ratio["trade_count"] == 0


# ═══════════════════════════════════════════════════════════════════════════════
# MarketDataCache — TTL invalidation, stampede prevention, hot-key detection
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.fixture
def fake_redis():
    import fakeredis
    return fakeredis.FakeRedis()


class TestMarketDataCacheTTL:
    def test_set_and_get_with_ttl(self, fake_redis):
        from market_data.redis_cache import MarketDataCache
        cache = MarketDataCache(fake_redis)
        cache.set_with_ttl("test:key", {"v": 42}, 300)
        val, ttl = cache.get_with_ttl("test:key")
        assert val == {"v": 42}
        assert ttl > 0

    def test_get_with_ttl_miss(self, fake_redis):
        from market_data.redis_cache import MarketDataCache
        cache = MarketDataCache(fake_redis)
        val, ttl = cache.get_with_ttl("missing:key")
        assert val is None
        assert ttl == -2

    def test_invalidate_key(self, fake_redis):
        from market_data.redis_cache import MarketDataCache
        cache = MarketDataCache(fake_redis)
        cache.set_with_ttl("del:key", {"x": 1}, 60)
        deleted = cache.invalidate("del:key")
        assert deleted is True
        val, _ = cache.get_with_ttl("del:key")
        assert val is None

    def test_invalidate_missing_returns_false(self, fake_redis):
        from market_data.redis_cache import MarketDataCache
        cache = MarketDataCache(fake_redis)
        assert cache.invalidate("nonexistent") is False

    def test_store_tick_and_retrieve(self, fake_redis):
        from market_data.redis_cache import MarketDataCache
        cache = MarketDataCache(fake_redis)
        tick = {"price": 1900.0, "timestamp": time.time()}
        cache.store_tick("XAUUSD", tick)
        result = cache.get_latest_tick("XAUUSD")
        assert result is not None
        assert result["price"] == 1900.0

    def test_store_bar_and_retrieve(self, fake_redis):
        from market_data.redis_cache import MarketDataCache
        cache = MarketDataCache(fake_redis)
        bar = {"bar_open_ts": time.time(), "open": 1900.0, "close": 1905.0}
        cache.store_bar("XAUUSD", "1m", bar)
        result = cache.get_latest_bar("XAUUSD", "1m")
        assert result is not None
        assert result["close"] == 1905.0


class TestMarketDataCacheStampede:
    def test_get_or_compute_calls_fn_once(self, fake_redis):
        from market_data.redis_cache import MarketDataCache
        cache = MarketDataCache(fake_redis)
        calls = [0]
        def compute():
            calls[0] += 1
            return {"computed": True}
        r1 = cache.get_or_compute("ckey", compute, 60)
        r2 = cache.get_or_compute("ckey", compute, 60)
        assert r1 == {"computed": True}
        assert r2 == {"computed": True}
        assert calls[0] == 1

    def test_get_or_compute_returns_none_on_error(self, fake_redis):
        from market_data.redis_cache import MarketDataCache
        cache = MarketDataCache(fake_redis)
        def bad_compute():
            raise RuntimeError("compute failed")
        result = cache.get_or_compute("errkey", bad_compute, 60)
        assert result is None


class TestMarketDataCacheHotKey:
    def test_hot_key_detected(self, fake_redis):
        from market_data.redis_cache import MarketDataCache
        cache = MarketDataCache(fake_redis, hot_key_threshold_rps=2.0)
        key = "hopefx:tick_cache:XAUUSD"
        # Simulate many accesses in the rolling window
        for _ in range(200):
            cache._record_access(key)
        assert key in cache.hot_keys

    def test_hot_key_report_sorted(self, fake_redis):
        from market_data.redis_cache import MarketDataCache
        cache = MarketDataCache(fake_redis, hot_key_threshold_rps=2.0)
        for _ in range(200):
            cache._record_access("hopefx:tick_cache:XAUUSD")
        report = cache.hot_key_report()
        assert isinstance(report, list)
        if len(report) > 1:
            assert report[0]["rps"] >= report[1]["rps"]

    def test_low_access_not_hot(self, fake_redis):
        from market_data.redis_cache import MarketDataCache
        cache = MarketDataCache(fake_redis, hot_key_threshold_rps=1000.0)
        cache._record_access("hopefx:tick_cache:XAUUSD")
        assert "hopefx:tick_cache:XAUUSD" not in cache.hot_keys


# ═══════════════════════════════════════════════════════════════════════════════
# TickPublisher / TickConsumer
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.fixture
async def fake_aio_redis():
    import fakeredis.aioredis as fake_aio
    return fake_aio.FakeRedis(decode_responses=True)


class TestTickPublisher:
    @pytest.mark.asyncio
    async def test_publish_returns_id(self, fake_aio_redis):
        from data_layer.stream.publisher import TickPublisher, StreamConfig
        config = StreamConfig()
        pub = TickPublisher(config)
        pub._redis = fake_aio_redis
        pub._connected = True
        msg_id = await pub.publish("XAUUSD", {"price": "1905.5", "timestamp": str(time.time())})
        assert msg_id is not None
        assert "-" in msg_id

    @pytest.mark.asyncio
    async def test_publish_increments_count(self, fake_aio_redis):
        from data_layer.stream.publisher import TickPublisher, StreamConfig
        pub = TickPublisher(StreamConfig())
        pub._redis = fake_aio_redis
        pub._connected = True
        await pub.publish("XAUUSD", {"price": "1900.0"})
        await pub.publish("XAUUSD", {"price": "1901.0"})
        assert pub.published_count == 2

    @pytest.mark.asyncio
    async def test_publish_batch(self, fake_aio_redis):
        from data_layer.stream.publisher import TickPublisher, StreamConfig
        pub = TickPublisher(StreamConfig())
        pub._redis = fake_aio_redis
        pub._connected = True
        n = await pub.publish_batch([
            ("XAUUSD", {"price": "1900.0"}),
            ("XAUUSD", {"price": "1901.0"}),
            ("XAUUSD", {"price": "1902.0"}),
        ])
        assert n == 3
        assert pub.published_count == 3

    @pytest.mark.asyncio
    async def test_publish_not_connected_raises(self):
        from data_layer.stream.publisher import TickPublisher, StreamConfig
        pub = TickPublisher(StreamConfig())
        with pytest.raises(RuntimeError, match="not connected"):
            await pub.publish("XAUUSD", {"price": "1900.0"})

    @pytest.mark.asyncio
    async def test_stats_keys(self, fake_aio_redis):
        from data_layer.stream.publisher import TickPublisher, StreamConfig
        pub = TickPublisher(StreamConfig())
        pub._redis = fake_aio_redis
        pub._connected = True
        stats = pub.stats()
        assert "published_count" in stats
        assert "error_count" in stats
        assert "connected" in stats


class TestTickConsumerFieldParsing:
    def test_numeric_coercion(self):
        from data_layer.stream.publisher import TickConsumer
        fields = {"symbol": "XAUUSD", "price": "1905.5", "volume": "2.0"}
        tick = TickConsumer._fields_to_tick(fields)
        assert tick["price"] == 1905.5
        assert tick["volume"] == 2.0

    def test_internal_fields_excluded(self):
        from data_layer.stream.publisher import TickConsumer
        fields = {"symbol": "XAUUSD", "_delivery_count": "2", "price": "1900.0"}
        tick = TickConsumer._fields_to_tick(fields)
        assert "_delivery_count" not in tick
        assert "price" in tick

    def test_empty_string_becomes_none(self):
        from data_layer.stream.publisher import TickConsumer
        fields = {"symbol": "XAUUSD", "lineage_id": ""}
        tick = TickConsumer._fields_to_tick(fields)
        assert tick["lineage_id"] is None

    def test_json_nested_decoded(self):
        import json
        from data_layer.stream.publisher import TickConsumer
        fields = {"symbol": "XAUUSD", "meta": json.dumps({"source": "finnhub"})}
        tick = TickConsumer._fields_to_tick(fields)
        assert tick["meta"] == {"source": "finnhub"}


# ═══════════════════════════════════════════════════════════════════════════════
# OHLCVBuilder
# ═══════════════════════════════════════════════════════════════════════════════

class TestOHLCVBuilder:
    @pytest.mark.asyncio
    async def test_bar_opens_on_first_tick(self):
        from data_layer.aggregator.ohlcv_builder import OHLCVBuilder
        builder = OHLCVBuilder(timeframes=["1m"])
        base = float(int(time.time() // 60) * 60)
        await builder.on_tick("XAUUSD", 1900.0, volume=1.0, timestamp=base + 1.0)
        bar = builder.get_open_bar("XAUUSD", "1m")
        assert bar is not None
        assert bar.open == 1900.0

    @pytest.mark.asyncio
    async def test_bar_high_low_tracked(self):
        from data_layer.aggregator.ohlcv_builder import OHLCVBuilder
        builder = OHLCVBuilder(timeframes=["1m"])
        base = float(int(time.time() // 60) * 60)
        await builder.on_tick("XAUUSD", 1900.0, volume=1.0, timestamp=base + 1.0)
        await builder.on_tick("XAUUSD", 1905.0, volume=1.0, timestamp=base + 2.0)
        await builder.on_tick("XAUUSD", 1895.0, volume=1.0, timestamp=base + 3.0)
        bar = builder.get_open_bar("XAUUSD", "1m")
        assert bar.high == 1905.0
        assert bar.low == 1895.0
        assert bar.close == 1895.0

    @pytest.mark.asyncio
    async def test_bar_closes_on_boundary(self):
        from data_layer.aggregator.ohlcv_builder import OHLCVBuilder
        closed = []
        builder = OHLCVBuilder(timeframes=["1s"])
        builder.register_on_bar_close(lambda b: closed.append(b))
        base = float(int(time.time()))
        await builder.on_tick("XAUUSD", 1900.0, volume=1.0, timestamp=base + 0.1)
        await builder.on_tick("XAUUSD", 1901.0, volume=1.0, timestamp=base + 1.1)
        assert len(closed) >= 1
        assert closed[0].open == 1900.0

    @pytest.mark.asyncio
    async def test_vwap_computed(self):
        from data_layer.aggregator.ohlcv_builder import OHLCVBuilder
        builder = OHLCVBuilder(timeframes=["1m"])
        base = float(int(time.time() // 60) * 60)
        await builder.on_tick("XAUUSD", 1900.0, volume=2.0, timestamp=base + 1.0)
        await builder.on_tick("XAUUSD", 1902.0, volume=2.0, timestamp=base + 2.0)
        bar = builder.get_open_bar("XAUUSD", "1m")
        assert bar.vwap == 1901.0

    @pytest.mark.asyncio
    async def test_buy_sell_volume_tracked(self):
        from data_layer.aggregator.ohlcv_builder import OHLCVBuilder
        builder = OHLCVBuilder(timeframes=["1m"])
        base = float(int(time.time() // 60) * 60)
        await builder.on_tick("XAUUSD", 1900.0, volume=3.0, timestamp=base + 1.0, trade_side="buy")
        await builder.on_tick("XAUUSD", 1901.0, volume=1.0, timestamp=base + 2.0, trade_side="sell")
        bar = builder.get_open_bar("XAUUSD", "1m")
        assert bar.buy_volume == 3.0
        assert bar.sell_volume == 1.0
        assert bar.delta == 2.0

    @pytest.mark.asyncio
    async def test_gap_fill_bars_emitted(self):
        from data_layer.aggregator.ohlcv_builder import OHLCVBuilder
        closed = []
        builder = OHLCVBuilder(timeframes=["1s"], max_gap_bars=5)
        builder.register_on_bar_close(lambda b: closed.append(b))
        base = float(int(time.time()))
        await builder.on_tick("XAUUSD", 1900.0, volume=1.0, timestamp=base + 0.1)
        await builder.on_tick("XAUUSD", 1905.0, volume=1.0, timestamp=base + 8.0)
        gap_bars = [b for b in closed if b.volume == 0.0]
        assert len(gap_bars) >= 1

    @pytest.mark.asyncio
    async def test_flush_closes_open_bars(self):
        from data_layer.aggregator.ohlcv_builder import OHLCVBuilder
        builder = OHLCVBuilder(timeframes=["1m", "5m"])
        base = float(int(time.time() // 60) * 60)
        await builder.on_tick("XAUUSD", 1900.0, volume=1.0, timestamp=base + 1.0)
        flushed = await builder.flush("XAUUSD")
        assert len(flushed) == 2

    @pytest.mark.asyncio
    async def test_multiple_timeframes(self):
        from data_layer.aggregator.ohlcv_builder import OHLCVBuilder
        builder = OHLCVBuilder(timeframes=["1s", "5s", "1m"])
        base = float(int(time.time()))
        await builder.on_tick("XAUUSD", 1900.0, volume=1.0, timestamp=base + 0.5)
        assert builder.get_open_bar("XAUUSD", "1s") is not None
        assert builder.get_open_bar("XAUUSD", "5s") is not None
        assert builder.get_open_bar("XAUUSD", "1m") is not None

    @pytest.mark.asyncio
    async def test_stats_keys(self):
        from data_layer.aggregator.ohlcv_builder import OHLCVBuilder
        builder = OHLCVBuilder(timeframes=["1m"])
        stats = builder.stats()
        for k in ("tick_count", "bars_closed", "gap_bars_emitted", "open_bars"):
            assert k in stats

    @pytest.mark.asyncio
    async def test_bar_to_dict(self):
        from data_layer.aggregator.ohlcv_builder import OHLCVBuilder
        builder = OHLCVBuilder(timeframes=["1m"])
        base = float(int(time.time() // 60) * 60)
        await builder.on_tick("XAUUSD", 1900.0, volume=1.0, timestamp=base + 1.0)
        bar = builder.get_open_bar("XAUUSD", "1m")
        d = bar.to_dict()
        for k in ("symbol", "timeframe", "open", "high", "low", "close", "volume", "vwap"):
            assert k in d


# ═══════════════════════════════════════════════════════════════════════════════
# AsyncConnectionPool / AsyncHealthMonitor
# ═══════════════════════════════════════════════════════════════════════════════

class TestAsyncConnectionPool:
    @pytest.mark.asyncio
    async def test_health_check_healthy(self):
        from database.async_connection import AsyncConnectionPool, AsyncPoolConfig
        cfg = AsyncPoolConfig(
            database_url="sqlite+aiosqlite:///:memory:",
            use_null_pool=True,
        )
        pool = AsyncConnectionPool(cfg)
        await pool.connect()
        result = await pool.health_check()
        assert result["healthy"] is True
        assert result["latency_ms"] >= 0
        await pool.close()

    @pytest.mark.asyncio
    async def test_context_manager(self):
        from database.async_connection import AsyncConnectionPool, AsyncPoolConfig
        cfg = AsyncPoolConfig(
            database_url="sqlite+aiosqlite:///:memory:",
            use_null_pool=True,
        )
        async with AsyncConnectionPool(cfg) as pool:
            result = await pool.health_check()
            assert result["healthy"] is True

    @pytest.mark.asyncio
    async def test_metrics_recorded(self):
        from database.async_connection import AsyncConnectionPool, AsyncPoolConfig
        cfg = AsyncPoolConfig(
            database_url="sqlite+aiosqlite:///:memory:",
            use_null_pool=True,
        )
        async with AsyncConnectionPool(cfg) as pool:
            await pool.health_check()
            assert pool.metrics.checkouts >= 1

    def test_url_redaction(self):
        from database.async_connection import AsyncConnectionPool
        url = "postgresql+asyncpg://user:secret@localhost/db"
        redacted = AsyncConnectionPool._redact_url(url)
        assert "secret" not in redacted
        assert "***" in redacted

    def test_pool_metrics_percentiles(self):
        from database.async_connection import AsyncPoolMetrics
        m = AsyncPoolMetrics()
        for v in [1.0, 2.0, 3.0, 100.0]:
            m.record_query_latency(v)
        assert m.query_p99_ms >= 3.0
        assert m.query_p50_ms <= 100.0


class TestAsyncHealthMonitor:
    @pytest.mark.asyncio
    async def test_monitor_runs_and_reports(self):
        from database.async_connection import (
            AsyncConnectionPool, AsyncPoolConfig, AsyncHealthMonitor
        )
        cfg = AsyncPoolConfig(
            database_url="sqlite+aiosqlite:///:memory:",
            use_null_pool=True,
        )
        async with AsyncConnectionPool(cfg) as pool:
            monitor = AsyncHealthMonitor(pool, interval_seconds=0.05)
            task = asyncio.create_task(monitor.run())
            await asyncio.sleep(0.2)
            monitor.stop()
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            snap = monitor.health_snapshot()
            assert snap.get("healthy") is True
            assert snap.get("check_count", 0) >= 1

    @pytest.mark.asyncio
    async def test_is_healthy_property(self):
        from database.async_connection import (
            AsyncConnectionPool, AsyncPoolConfig, AsyncHealthMonitor
        )
        cfg = AsyncPoolConfig(
            database_url="sqlite+aiosqlite:///:memory:",
            use_null_pool=True,
        )
        async with AsyncConnectionPool(cfg) as pool:
            monitor = AsyncHealthMonitor(pool, interval_seconds=0.05)
            task = asyncio.create_task(monitor.run())
            await asyncio.sleep(0.15)
            monitor.stop()
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            assert monitor.is_healthy is True


# ═══════════════════════════════════════════════════════════════════════════════
# Repository tests — shared SQLite fixture
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.fixture
async def db_session():
    """Async SQLite session with all tables created. Patches BigInteger PKs."""
    from sqlalchemy import Integer
    from database.models import Base, MarketData, TickData
    from database.async_connection import AsyncConnectionPool, AsyncPoolConfig

    # Patch BigInteger PKs to Integer for SQLite compatibility.
    MarketData.__table__.c.id.type = Integer()
    TickData.__table__.c.id.type = Integer()

    cfg = AsyncPoolConfig(
        database_url="sqlite+aiosqlite:///test_repos_pytest.db",
        use_null_pool=True,
    )
    pool = AsyncConnectionPool(cfg)
    await pool.connect()
    async with pool._engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    async with pool.session() as session:
        yield session

    await pool.close()
    import os
    try:
        os.unlink("test_repos_pytest.db")
    except FileNotFoundError:
        pass


class TestTradeRepository:
    @pytest.mark.asyncio
    async def test_create_and_get(self, db_session):
        from database.repositories import TradeRepository
        repo = TradeRepository()
        trade = await repo.create(
            db_session, symbol="XAUUSD", side="buy",
            entry_price=1900.0, entry_quantity=1.0,
            trade_id="T-001", user_id="u1",
        )
        assert trade.id is not None
        fetched = await repo.get_by_trade_id(db_session, "T-001")
        assert fetched is not None
        assert fetched.symbol == "XAUUSD"

    @pytest.mark.asyncio
    async def test_get_open_trades(self, db_session):
        from database.repositories import TradeRepository
        repo = TradeRepository()
        await repo.create(
            db_session, symbol="XAUUSD", side="buy",
            entry_price=1900.0, entry_quantity=1.0,
            trade_id="T-002", user_id="u1",
        )
        trades = await repo.get_open_trades(db_session, symbol="XAUUSD")
        assert len(trades) >= 1

    @pytest.mark.asyncio
    async def test_pnl_summary_empty(self, db_session):
        from database.repositories import TradeRepository
        repo = TradeRepository()
        summary = await repo.get_pnl_summary(db_session, user_id="nobody")
        assert summary["trade_count"] == 0
        assert summary["total_pnl"] == 0.0

    @pytest.mark.asyncio
    async def test_count(self, db_session):
        from database.repositories import TradeRepository
        repo = TradeRepository()
        before = await repo.count(db_session)
        await repo.create(
            db_session, symbol="XAUUSD", side="sell",
            entry_price=1905.0, entry_quantity=1.0,
            trade_id="T-003", user_id="u2",
        )
        after = await repo.count(db_session)
        assert after == before + 1


class TestMarketDataRepository:
    @pytest.mark.asyncio
    async def test_upsert_and_get(self, db_session):
        from database.repositories import MarketDataRepository
        repo = MarketDataRepository()
        bar = await repo.upsert_bar(
            db_session, "XAUUSD", "1m",
            datetime.now(UTC), 1900.0, 1905.0, 1898.0, 1903.0, 10.0,
        )
        assert bar.close == 1903.0
        bars = await repo.get_bars(db_session, "XAUUSD", "1m", limit=10)
        assert len(bars) == 1

    @pytest.mark.asyncio
    async def test_upsert_updates_existing(self, db_session):
        from database.repositories import MarketDataRepository
        repo = MarketDataRepository()
        ts = datetime.now(UTC)
        await repo.upsert_bar(db_session, "XAUUSD", "5m", ts, 1900.0, 1905.0, 1898.0, 1903.0)
        updated = await repo.upsert_bar(db_session, "XAUUSD", "5m", ts, 1900.0, 1910.0, 1898.0, 1908.0)
        assert updated.high == 1910.0

    @pytest.mark.asyncio
    async def test_get_latest_bar(self, db_session):
        from database.repositories import MarketDataRepository
        repo = MarketDataRepository()
        await repo.upsert_bar(
            db_session, "XAUUSD", "15m",
            datetime.now(UTC), 1900.0, 1905.0, 1898.0, 1903.0,
        )
        latest = await repo.get_latest_bar(db_session, "XAUUSD", "15m")
        assert latest is not None
        assert latest.close == 1903.0


class TestPositionRepository:
    @pytest.mark.asyncio
    async def test_create_and_get_open(self, db_session):
        from database.repositories import PositionRepository
        repo = PositionRepository()
        pos = await repo.create(
            db_session, symbol="XAUUSD", user_id="u1",
            entry_price=1900.0, quantity=1.0, status="open",
        )
        assert pos.id is not None
        open_pos = await repo.get_open_positions(db_session, user_id="u1")
        assert len(open_pos) >= 1

    @pytest.mark.asyncio
    async def test_portfolio_summary(self, db_session):
        from database.repositories import PositionRepository
        repo = PositionRepository()
        await repo.create(
            db_session, symbol="XAUUSD", user_id="u2",
            entry_price=1900.0, quantity=2.0, status="open",
        )
        summary = await repo.get_portfolio_summary(db_session, "u2")
        assert summary["position_count"] >= 1


class TestSignalRepository:
    @pytest.mark.asyncio
    async def test_create_and_get_pending(self, db_session):
        from database.repositories import SignalRepository
        from database.models import SignalSource
        repo = SignalRepository()
        sig = await repo.create(
            db_session, signal_id="SIG-001", symbol="XAUUSD",
            action="buy", strategy="trend",
            source=SignalSource.TREND_FOLLOWING,
        )
        assert sig.id is not None
        pending = await repo.get_pending_signals(db_session, symbol="XAUUSD")
        assert len(pending) >= 1

    @pytest.mark.asyncio
    async def test_mark_executed(self, db_session):
        from database.repositories import SignalRepository
        from database.models import SignalSource
        repo = SignalRepository()
        await repo.create(
            db_session, signal_id="SIG-002", symbol="XAUUSD",
            action="sell", strategy="mean_rev",
            source=SignalSource.MEAN_REVERSION,
        )
        updated = await repo.mark_executed(db_session, "SIG-002", "T-999")
        assert updated.executed is True
        assert updated.trade_id == "T-999"


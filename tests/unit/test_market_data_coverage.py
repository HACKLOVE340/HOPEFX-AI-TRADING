# HOPEFX-AI-TRADING
# Tests for market_data/ — feed_handler, validation, redis_cache, order_book
"""
Real unit tests for market_data modules.
No mocks/stubs — uses real class instantiation and in-process fake Redis.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

UTC = timezone.utc

# ── feed_handler ──────────────────────────────────────────────────────────────

from market_data.feed_handler import ExchangeFeed, FeedHandler, Tick


class TestTick:
    def test_mid_price_with_bid_ask(self):
        t = Tick("XAUUSD", datetime.now(UTC), 1900.0, 1901.0, 10.0, 10.0, 1900.5, 1.0, "oanda")
        assert t.mid == pytest.approx(1900.5)

    def test_mid_price_fallback_to_last(self):
        t = Tick("XAUUSD", datetime.now(UTC), 0.0, 0.0, 0.0, 0.0, 1900.0, 1.0, "oanda")
        assert t.mid == 1900.0

    def test_spread(self):
        t = Tick("XAUUSD", datetime.now(UTC), 1900.0, 1901.0, 10.0, 10.0, 1900.5, 1.0, "oanda")
        assert t.spread == pytest.approx(1.0)

    def test_spread_zero_when_no_bid_ask(self):
        t = Tick("XAUUSD", datetime.now(UTC), 0.0, 0.0, 0.0, 0.0, 1900.0, 1.0, "oanda")
        assert t.spread == 0.0

    def test_is_trade_flag(self):
        t = Tick("XAUUSD", datetime.now(UTC), 1900.0, 1901.0, 10.0, 10.0, 1900.5, 1.0, "oanda", is_trade=True)
        assert t.is_trade is True


class TestFeedHandler:
    def setup_method(self):
        self.fh = FeedHandler()

    def test_subscribe_adds_symbols(self):
        self.fh.subscribe(["XAUUSD", "EURUSD"])
        assert "XAUUSD" in self.fh.symbol_subscriptions
        assert "EURUSD" in self.fh.symbol_subscriptions

    def test_on_tick_callback_called(self):
        received = []
        self.fh.subscribe(["XAUUSD"])
        self.fh.on_tick(received.append)

        raw = {
            "instrument": "XAU_USD",
            "bids": [{"price": "1900.0", "liquidity": "100"}],
            "asks": [{"price": "1901.0", "liquidity": "100"}],
        }
        self.fh._on_exchange_tick(raw, "oanda")
        assert len(received) == 1
        assert received[0].symbol == "XAUUSD"

    def test_tick_not_delivered_for_unsubscribed_symbol(self):
        received = []
        self.fh.subscribe(["EURUSD"])
        self.fh.on_tick(received.append)

        raw = {
            "instrument": "XAU_USD",
            "bids": [{"price": "1900.0", "liquidity": "100"}],
            "asks": [{"price": "1901.0", "liquidity": "100"}],
        }
        self.fh._on_exchange_tick(raw, "oanda")
        assert len(received) == 0

    def test_stats_incremented(self):
        self.fh.subscribe(["XAUUSD"])
        raw = {
            "instrument": "XAU_USD",
            "bids": [{"price": "1900.0", "liquidity": "100"}],
            "asks": [{"price": "1901.0", "liquidity": "100"}],
        }
        self.fh._on_exchange_tick(raw, "oanda")
        assert self.fh.stats["ticks_processed"] == 1

    def test_parse_oanda(self):
        raw = {
            "instrument": "XAU_USD",
            "bids": [{"price": "1900.5", "liquidity": "50"}],
            "asks": [{"price": "1901.5", "liquidity": "50"}],
        }
        tick = self.fh._parse_oanda(raw, "oanda")
        assert tick.symbol == "XAUUSD"
        assert tick.bid == pytest.approx(1900.5)
        assert tick.ask == pytest.approx(1901.5)

    def test_parse_binance(self):
        raw = {
            "s": "BTCUSDT",
            "E": 1700000000000,
            "b": "30000.0",
            "a": "30001.0",
            "B": "1.5",
            "A": "2.0",
            "c": "30000.5",
            "v": "100.0",
            "e": "trade",
        }
        tick = self.fh._parse_binance(raw, "binance")
        assert tick.symbol == "BTCUSDT"
        assert tick.is_trade is True
        assert tick.bid == pytest.approx(30000.0)

    def test_parse_coinbase(self):
        raw = {
            "product_id": "BTC-USD",
            "time": "2024-01-01T00:00:00",
            "best_bid": "29999.0",
            "best_ask": "30001.0",
            "bid_size": "1.0",
            "ask_size": "1.0",
            "price": "30000.0",
            "last_size": "0.5",
            "type": "match",
        }
        tick = self.fh._parse_coinbase(raw, "coinbase")
        assert tick.symbol == "BTCUSD"
        assert tick.is_trade is True

    def test_parse_generic(self):
        raw = {
            "symbol": "XAUUSD",
            "bid": "1900.0",
            "ask": "1901.0",
            "bidSize": "10",
            "askSize": "10",
            "price": "1900.5",
            "size": "1",
        }
        tick = self.fh._parse_generic(raw, "generic")
        assert tick.symbol == "XAUUSD"
        assert tick.exchange == "generic"

    def test_get_l1_book_returns_latest_quote(self):
        self.fh.subscribe(["XAUUSD"])
        raw = {
            "instrument": "XAU_USD",
            "bids": [{"price": "1900.0", "liquidity": "100"}],
            "asks": [{"price": "1901.0", "liquidity": "100"}],
        }
        self.fh._on_exchange_tick(raw, "oanda")
        l1 = self.fh.get_l1_book("XAUUSD")
        assert l1 is not None
        assert l1.symbol == "XAUUSD"

    def test_get_l1_book_returns_none_for_unknown(self):
        assert self.fh.get_l1_book("UNKNOWN") is None

    def test_get_recent_trades_empty_when_no_trades(self):
        self.fh.subscribe(["XAUUSD"])
        raw = {
            "instrument": "XAU_USD",
            "bids": [{"price": "1900.0", "liquidity": "100"}],
            "asks": [{"price": "1901.0", "liquidity": "100"}],
        }
        self.fh._on_exchange_tick(raw, "oanda")
        trades = self.fh.get_recent_trades("XAUUSD")
        assert trades == []

    def test_get_recent_trades_returns_trade_ticks(self):
        self.fh.subscribe(["BTCUSDT"])
        raw = {
            "s": "BTCUSDT",
            "E": 1700000000000,
            "b": "30000.0",
            "a": "30001.0",
            "B": "1.5",
            "A": "2.0",
            "c": "30000.5",
            "v": "100.0",
            "e": "trade",
        }
        self.fh._on_exchange_tick(raw, "binance")
        trades = self.fh.get_recent_trades("BTCUSDT")
        assert len(trades) == 1

    def test_callback_exception_does_not_crash(self):
        def bad_callback(tick):
            raise RuntimeError("callback error")

        self.fh.subscribe(["XAUUSD"])
        self.fh.on_tick(bad_callback)
        raw = {
            "instrument": "XAU_USD",
            "bids": [{"price": "1900.0", "liquidity": "100"}],
            "asks": [{"price": "1901.0", "liquidity": "100"}],
        }
        # Should not raise
        self.fh._on_exchange_tick(raw, "oanda")

    def test_add_exchange(self):
        feed = ExchangeFeed("test", "ws://localhost")
        self.fh.add_exchange("test", feed)
        assert "test" in self.fh.exchanges

    def test_tick_buffer_bounded(self):
        self.fh.subscribe(["XAUUSD"])
        for i in range(10005):
            raw = {
                "instrument": "XAU_USD",
                "bids": [{"price": str(1900 + i * 0.01), "liquidity": "100"}],
                "asks": [{"price": str(1901 + i * 0.01), "liquidity": "100"}],
            }
            self.fh._on_exchange_tick(raw, "oanda")
        assert len(self.fh.tick_buffer) <= 10000

    def test_normalize_dispatches_to_correct_parser(self):
        raw_oanda = {
            "instrument": "XAU_USD",
            "bids": [{"price": "1900.0", "liquidity": "100"}],
            "asks": [{"price": "1901.0", "liquidity": "100"}],
        }
        tick = self.fh._normalize(raw_oanda, "oanda")
        assert tick.exchange == "oanda"

        raw_binance = {
            "s": "BTCUSDT",
            "E": 1700000000000,
            "b": "30000.0",
            "a": "30001.0",
            "B": "1.5",
            "A": "2.0",
            "c": "30000.5",
            "v": "100.0",
        }
        tick2 = self.fh._normalize(raw_binance, "binance")
        assert tick2.exchange == "binance"


class TestExchangeFeed:
    def test_subscribe_adds_symbols(self):
        feed = ExchangeFeed("test", "ws://localhost")
        feed.subscribe(["XAUUSD", "EURUSD"])
        assert "XAUUSD" in feed.subscribed_symbols

    def test_set_callback(self):
        feed = ExchangeFeed("test", "ws://localhost")

        def cb(d, n):
            return None

        feed.set_callback(cb)
        assert feed.callback is cb

    def test_initial_state(self):
        feed = ExchangeFeed("test", "ws://localhost")
        assert feed.connected is False
        assert feed.callback is None


# ── market_data/validation ────────────────────────────────────────────────────

from market_data.validation import DataQualityIssue, MarketDataValidator


class TestMarketDataValidator:
    def setup_method(self):
        self.validator = MarketDataValidator(
            max_staleness_seconds=5,
            max_price_jump_pct=0.02,
            min_volume=1.0,
            reference_prices={"XAUUSD": 1900.0},
        )

    def test_valid_tick_passes(self):
        tick = {
            "timestamp": datetime.now(UTC),
            "price": 1901.0,
            "volume": 10.0,
            "bid": 1900.5,
            "ask": 1901.5,
        }
        result = self.validator.validate_tick(tick, "XAUUSD")
        assert result.is_valid is True
        assert result.quality_score > 0.5

    def test_stale_tick_flagged(self):
        old_time = datetime.now(UTC) - timedelta(seconds=60)
        tick = {
            "timestamp": old_time,
            "price": 1901.0,
            "volume": 10.0,
        }
        result = self.validator.validate_tick(tick, "XAUUSD")
        issue_types = [i["type"] for i in result.issues]
        assert DataQualityIssue.STALE_DATA.value in issue_types

    def test_price_jump_flagged(self):
        tick = {
            "timestamp": datetime.now(UTC),
            "price": 2000.0,  # >2% jump from 1900
            "volume": 10.0,
        }
        result = self.validator.validate_tick(tick, "XAUUSD")
        issue_types = [i["type"] for i in result.issues]
        assert DataQualityIssue.PRICE_JUMP.value in issue_types

    def test_zero_volume_flagged(self):
        tick = {
            "timestamp": datetime.now(UTC),
            "price": 1901.0,
            "volume": 0.0,
        }
        result = self.validator.validate_tick(tick, "XAUUSD")
        issue_types = [i["type"] for i in result.issues]
        assert DataQualityIssue.ZERO_VOLUME.value in issue_types

    def test_negative_spread_flagged(self):
        tick = {
            "timestamp": datetime.now(UTC),
            "price": 1901.0,
            "volume": 10.0,
            "bid": 1902.0,
            "ask": 1900.0,  # ask < bid
        }
        result = self.validator.validate_tick(tick, "XAUUSD")
        issue_types = [i["type"] for i in result.issues]
        assert DataQualityIssue.NEGATIVE_SPREAD.value in issue_types

    def test_missing_fields_flagged(self):
        tick = {"volume": 10.0}  # no price, no timestamp
        result = self.validator.validate_tick(tick, "XAUUSD")
        issue_types = [i["type"] for i in result.issues]
        assert DataQualityIssue.MISSING_FIELDS.value in issue_types

    def test_reference_price_updated_on_valid_tick(self):
        tick = {
            "timestamp": datetime.now(UTC),
            "price": 1905.0,
            "volume": 10.0,
            "bid": 1904.5,
            "ask": 1905.5,
        }
        self.validator.validate_tick(tick, "XAUUSD")
        assert self.validator.reference_prices["XAUUSD"] == pytest.approx(1905.0)

    def test_validate_ohlc_valid_dataframe(self):
        # Use integer index to avoid pandas freq inference issues
        df = pd.DataFrame(
            {
                "open": [1900.0] * 10,
                "high": [1910.0] * 10,
                "low": [1890.0] * 10,
                "close": [1905.0] * 10,
                "volume": [100.0] * 10,
            }
        )
        result = self.validator.validate_ohlc(df, "XAUUSD")
        assert result.is_valid is True

    def test_validate_ohlc_invalid_high_low(self):
        df = pd.DataFrame(
            {
                "open": [1900.0] * 5,
                "high": [1890.0] * 5,  # high < low — invalid
                "low": [1910.0] * 5,
                "close": [1905.0] * 5,
                "volume": [100.0] * 5,
            }
        )
        result = self.validator.validate_ohlc(df, "XAUUSD")
        assert result.is_valid is False

    def test_get_quality_report_empty(self):
        v = MarketDataValidator()
        report = v.get_quality_report()
        assert "message" in report

    def test_get_quality_report_with_history(self):
        tick = {
            "timestamp": datetime.now(UTC),
            "price": 1901.0,
            "volume": 10.0,
            "bid": 1900.5,
            "ask": 1901.5,
        }
        self.validator.validate_tick(tick, "XAUUSD")
        report = self.validator.get_quality_report()
        assert "total_validations" in report
        assert report["total_validations"] >= 1

    def test_unix_timestamp_staleness(self):
        # Use a timezone-naive old timestamp so age calc works
        old_ts = datetime.now(UTC) - timedelta(seconds=60)
        tick = {"timestamp": old_ts, "price": 1901.0, "volume": 10.0}
        result = self.validator.validate_tick(tick, "XAUUSD")
        issue_types = [i["type"] for i in result.issues]
        assert DataQualityIssue.STALE_DATA.value in issue_types

    def test_no_reference_price_skips_jump_check(self):
        v = MarketDataValidator()
        tick = {"timestamp": datetime.now(UTC), "price": 9999.0, "volume": 10.0}
        result = v.validate_tick(tick, "NEWPAIR")
        issue_types = [i["type"] for i in result.issues]
        assert DataQualityIssue.PRICE_JUMP.value not in issue_types


# ── market_data/redis_cache ───────────────────────────────────────────────────

from market_data.redis_cache import MarketDataCache


class FakeRedis:
    """In-process fake Redis for testing without a live server."""

    def __init__(self):
        self._zsets: dict[str, dict[str, float]] = {}
        self._strings: dict[str, str] = {}
        self._ttls: dict[str, int] = {}

    def zadd(self, key, mapping):
        if key not in self._zsets:
            self._zsets[key] = {}
        self._zsets[key].update(mapping)

    def zrevrange(self, key, start, stop):
        if key not in self._zsets:
            return []
        items = sorted(self._zsets[key].items(), key=lambda x: -x[1])
        if stop == -1:
            return [k.encode() if isinstance(k, str) else k for k, _ in items[start:]]
        return [k.encode() if isinstance(k, str) else k for k, _ in items[start : stop + 1]]

    def zrangebyscore(self, key, min_score, max_score):
        if key not in self._zsets:
            return []
        result = []
        for k, score in sorted(self._zsets[key].items(), key=lambda x: x[1]):
            if score >= min_score:
                result.append(k.encode() if isinstance(k, str) else k)
        return result

    def zremrangebyrank(self, key, start, stop):
        pass  # simplified

    def expire(self, key, seconds):
        self._ttls[key] = seconds

    def get(self, key):
        val = self._strings.get(key)
        return val.encode() if isinstance(val, str) else val

    def set(self, key, value, ex=None):
        self._strings[key] = value

    def ping(self):
        return True


class TestMarketDataCache:
    def setup_method(self):
        self.redis = FakeRedis()
        self.cache = MarketDataCache(self.redis)

    def test_ping_returns_true(self):
        assert self.cache.ping() is True

    def test_get_latest_tick_empty(self):
        assert self.cache.get_latest_tick("XAUUSD") is None

    def test_store_and_retrieve_tick(self):
        tick = {"symbol": "XAUUSD", "price": 1900.0, "ts": time.time()}
        key = "hopefx:tick_cache:XAUUSD"
        self.redis.zadd(key, {json.dumps(tick): tick["ts"]})
        result = self.cache.get_latest_tick("XAUUSD")
        assert result is not None
        assert result["symbol"] == "XAUUSD"

    def test_get_recent_ticks_empty(self):
        result = self.cache.get_recent_ticks("XAUUSD")
        assert result == []

    def test_get_recent_ticks_returns_list(self):
        key = "hopefx:tick_cache:XAUUSD"
        for i in range(5):
            tick = {"price": 1900.0 + i, "ts": time.time() + i}
            self.redis.zadd(key, {json.dumps(tick): tick["ts"]})
        result = self.cache.get_recent_ticks("XAUUSD", n=3)
        assert len(result) <= 3

    def test_get_ticks_since(self):
        key = "hopefx:tick_cache:XAUUSD"
        now = time.time()
        for i in range(5):
            tick = {"price": 1900.0 + i, "ts": now + i}
            self.redis.zadd(key, {json.dumps(tick): now + i})
        result = self.cache.get_ticks_since("XAUUSD", now + 2)
        assert len(result) >= 1

    def test_store_bar(self):
        bar = {
            "open": 1900.0,
            "high": 1910.0,
            "low": 1890.0,
            "close": 1905.0,
            "volume": 100.0,
            "bar_open_ts": time.time(),
        }
        self.cache.store_bar("XAUUSD", "1h", bar)
        key = "hopefx:ohlcv:XAUUSD:1h"
        assert key in self.redis._zsets

    def test_get_bars_empty(self):
        result = self.cache.get_bars("XAUUSD", "1h")
        assert result == []

    def test_store_and_get_bars(self):
        now = time.time()
        for i in range(3):
            bar = {
                "open": 1900.0 + i,
                "high": 1910.0,
                "low": 1890.0,
                "close": 1905.0,
                "volume": 100.0,
                "bar_open_ts": now + i * 3600,
            }
            self.cache.store_bar("XAUUSD", "1h", bar)
        result = self.cache.get_bars("XAUUSD", "1h")
        assert len(result) == 3

    def test_get_bars_since(self):
        now = time.time()
        for i in range(5):
            bar = {
                "open": 1900.0 + i,
                "high": 1910.0,
                "low": 1890.0,
                "close": 1905.0,
                "volume": 100.0,
                "bar_open_ts": now + i * 3600,
            }
            self.cache.store_bar("XAUUSD", "1h", bar)
        result = self.cache.get_bars_since("XAUUSD", "1h", now + 2 * 3600)
        assert len(result) >= 1

    def test_get_latest_bar_none(self):
        assert self.cache.get_latest_bar("XAUUSD", "1h") is None

    def test_get_latest_bar_returns_value(self):
        bar = {"open": 1900.0, "close": 1905.0}
        self.redis._strings["hopefx:latest_bar:XAUUSD:1h"] = json.dumps(bar)
        result = self.cache.get_latest_bar("XAUUSD", "1h")
        assert result is not None
        assert result["open"] == 1900.0

    def test_get_feed_health_none(self):
        assert self.cache.get_feed_health() is None

    def test_get_feed_health_returns_value(self):
        health = {"status": "ok", "latency_ms": 5}
        self.redis._strings["hopefx:feed:health"] = json.dumps(health)
        result = self.cache.get_feed_health()
        assert result["status"] == "ok"

    def test_redis_error_returns_none_not_raises(self):
        class BrokenRedis:
            def zrevrange(self, *a, **kw):
                raise ConnectionError("Redis down")

            def ping(self):
                raise ConnectionError("Redis down")

        cache = MarketDataCache(BrokenRedis())
        assert cache.get_latest_tick("XAUUSD") is None
        assert cache.ping() is False

    def test_redis_error_get_bars_returns_empty(self):
        class BrokenRedis:
            def zrevrange(self, *a, **kw):
                raise ConnectionError("Redis down")

        cache = MarketDataCache(BrokenRedis())
        assert cache.get_bars("XAUUSD", "1h") == []

    def test_redis_error_get_ticks_since_returns_empty(self):
        class BrokenRedis:
            def zrangebyscore(self, *a, **kw):
                raise ConnectionError("Redis down")

        cache = MarketDataCache(BrokenRedis())
        assert cache.get_ticks_since("XAUUSD", 0.0) == []

    def test_store_bar_redis_error_does_not_raise(self):
        class BrokenRedis:
            def zadd(self, *a, **kw):
                raise ConnectionError("Redis down")

        cache = MarketDataCache(BrokenRedis())
        # Should not raise
        cache.store_bar("XAUUSD", "1h", {"bar_open_ts": time.time()})

    def test_custom_key_prefix(self):
        cache = MarketDataCache(self.redis, key_prefix="myapp:")
        bar = {"open": 1900.0, "bar_open_ts": time.time()}
        cache.store_bar("XAUUSD", "1h", bar)
        assert "myapp:ohlcv:XAUUSD:1h" in self.redis._zsets


# ── market_data/order_book (BookLevel, OrderBookSnapshot) ─────────────────────

from market_data.order_book import BookLevel, OrderBookSnapshot


class TestBookLevel:
    def test_creation(self):
        level = BookLevel(price=1900.0, size=10.0)
        assert level.price == 1900.0
        assert level.size == 10.0


class TestOrderBookSnapshot:
    def _make_snapshot(self, bids=None, asks=None):
        bids = bids or [BookLevel(1900.0, 10.0), BookLevel(1899.0, 20.0)]
        asks = asks or [BookLevel(1901.0, 10.0), BookLevel(1902.0, 20.0)]
        return OrderBookSnapshot(
            symbol="XAUUSD",
            timestamp=datetime.now(UTC),
            bids=bids,
            asks=asks,
            mid_price=1900.5,
            spread_bps=0.5,
        )

    def test_snapshot_creation(self):
        snap = self._make_snapshot()
        assert snap.symbol == "XAUUSD"
        assert len(snap.bids) == 2
        assert len(snap.asks) == 2

    def test_mid_price_computed(self):
        snap = self._make_snapshot()
        # __post_init__ recomputes mid from best bid/ask: (1900+1901)/2
        assert snap.mid_price == pytest.approx(1900.5)

    def test_spread_bps_computed(self):
        snap = self._make_snapshot()
        # spread_bps = (ask - bid) / mid * 10000 = 1/1900.5 * 10000 ≈ 5.26
        expected = (1901.0 - 1900.0) / 1900.5 * 10_000
        assert snap.spread_bps == pytest.approx(expected, rel=1e-3)

    def test_empty_book(self):
        snap = OrderBookSnapshot(
            symbol="XAUUSD",
            timestamp=datetime.now(UTC),
            bids=[],
            asks=[],
        )
        assert snap.bids == []
        assert snap.asks == []

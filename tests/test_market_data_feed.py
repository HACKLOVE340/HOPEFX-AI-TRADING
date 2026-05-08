# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
tests/test_market_data_feed.py

Unit tests for market_data/ibkr_feed.py and market_data/redis_cache.py.
"""

import time
from unittest.mock import MagicMock

import pytest

from market_data.ibkr_feed import (
    FeedStatus,
    IBKRMarketDataFeed,
    OHLCVAggregator,
    Tick,
    TickValidator,
)
from market_data.redis_cache import MarketDataCache

# ---------------------------------------------------------------------------
# TickValidator
# ---------------------------------------------------------------------------


class TestTickValidator:
    def setup_method(self):
        self.validator = TickValidator(
            max_jump_pct=0.02,
            max_age_sec=30.0,
            max_spread_bps=500.0,
        )

    def _make_tick(self, **overrides):
        defaults = {
            "symbol": "XAUUSD",
            "bid": 1949.0,
            "ask": 1951.0,
            "last": 1950.0,
            "timestamp": time.time(),
        }
        defaults.update(overrides)
        return Tick(**defaults)

    def test_valid_tick_passes(self):
        tick = self._make_tick()
        valid, reason = self.validator.validate(tick)
        assert valid is True
        assert reason == ""

    def test_zero_bid_rejected(self):
        tick = self._make_tick(bid=0.0)
        valid, reason = self.validator.validate(tick)
        assert valid is False
        assert "non-positive" in reason

    def test_negative_ask_rejected(self):
        tick = self._make_tick(ask=-1.0)
        valid, _ = self.validator.validate(tick)
        assert valid is False

    def test_inverted_spread_rejected(self):
        tick = self._make_tick(bid=1952.0, ask=1948.0)
        valid, reason = self.validator.validate(tick)
        assert valid is False
        assert "inverted" in reason

    def test_stale_tick_rejected(self):
        tick = self._make_tick(timestamp=time.time() - 60.0)
        valid, reason = self.validator.validate(tick)
        assert valid is False
        assert "stale" in reason

    def test_price_jump_rejected(self):
        # First tick establishes baseline
        tick1 = self._make_tick(bid=1949.0, ask=1951.0, last=1950.0)
        self.validator.validate(tick1)
        # Second tick jumps 5% — exceeds 2% limit
        tick2 = self._make_tick(bid=2046.0, ask=2048.0, last=2047.0)
        valid, reason = self.validator.validate(tick2)
        assert valid is False
        assert "jump" in reason

    def test_wide_spread_rejected(self):
        # 600bps spread > 500bps limit
        tick = self._make_tick(bid=1900.0, ask=2014.0)  # ~600bps
        valid, reason = self.validator.validate(tick)
        assert valid is False
        assert "spread" in reason.lower()


# ---------------------------------------------------------------------------
# Tick properties
# ---------------------------------------------------------------------------


class TestTickProperties:
    def test_mid_price(self):
        tick = Tick("XAUUSD", bid=1949.0, ask=1951.0, last=1950.0, timestamp=time.time())
        assert tick.mid == pytest.approx(1950.0)

    def test_spread(self):
        tick = Tick("XAUUSD", bid=1949.0, ask=1951.0, last=1950.0, timestamp=time.time())
        assert tick.spread == pytest.approx(2.0)

    def test_spread_bps(self):
        tick = Tick("XAUUSD", bid=1949.0, ask=1951.0, last=1950.0, timestamp=time.time())
        # spread=2, mid=1950 → 2/1950 * 10000 ≈ 10.26 bps
        assert tick.spread_bps == pytest.approx(10.26, rel=0.01)

    def test_to_dict_keys(self):
        tick = Tick("XAUUSD", bid=1949.0, ask=1951.0, last=1950.0, timestamp=time.time())
        d = tick.to_dict()
        assert {"symbol", "bid", "ask", "last", "mid", "spread", "timestamp"}.issubset(d.keys())


# ---------------------------------------------------------------------------
# OHLCVAggregator
# ---------------------------------------------------------------------------


class TestOHLCVAggregator:
    def _make_tick(self, price: float, ts: float) -> Tick:
        return Tick(
            symbol="XAUUSD",
            bid=price - 0.5,
            ask=price + 0.5,
            last=price,
            timestamp=ts,
        )

    def test_bar_opens_on_first_tick(self):
        agg = OHLCVAggregator("XAUUSD", ["1m"])
        ts = 1_700_000_000.0  # fixed timestamp
        agg.on_tick(self._make_tick(1950.0, ts))
        bar = agg.get_current_bar("1m")
        assert bar is not None
        assert bar.open == pytest.approx(1950.0)
        assert bar.close == pytest.approx(1950.0)

    def test_bar_high_low_updated(self):
        agg = OHLCVAggregator("XAUUSD", ["1m"])
        ts = 1_700_000_000.0
        agg.on_tick(self._make_tick(1950.0, ts))
        agg.on_tick(self._make_tick(1960.0, ts + 10))
        agg.on_tick(self._make_tick(1940.0, ts + 20))
        bar = agg.get_current_bar("1m")
        assert bar.high == pytest.approx(1960.0)
        assert bar.low == pytest.approx(1940.0)
        assert bar.close == pytest.approx(1940.0)

    def test_bar_closes_on_new_period(self):
        closed_bars = []
        agg = OHLCVAggregator("XAUUSD", ["1m"], on_bar_closed=closed_bars.append)

        ts = 1_700_000_000.0  # start of a minute
        agg.on_tick(self._make_tick(1950.0, ts))
        # Jump to next minute
        agg.on_tick(self._make_tick(1955.0, ts + 61))

        assert len(closed_bars) == 1
        assert closed_bars[0].is_closed is True
        assert closed_bars[0].open == pytest.approx(1950.0)

    def test_ignores_wrong_symbol(self):
        agg = OHLCVAggregator("XAUUSD", ["1m"])
        tick = Tick("EURUSD", bid=1.09, ask=1.091, last=1.0905, timestamp=time.time())
        agg.on_tick(tick)
        assert agg.get_current_bar("1m") is None

    def test_multiple_timeframes(self):
        agg = OHLCVAggregator("XAUUSD", ["1m", "5m"])
        ts = 1_700_000_000.0
        agg.on_tick(self._make_tick(1950.0, ts))
        assert agg.get_current_bar("1m") is not None
        assert agg.get_current_bar("5m") is not None


# ---------------------------------------------------------------------------
# IBKRMarketDataFeed
# ---------------------------------------------------------------------------


class TestIBKRMarketDataFeed:
    def _make_connector(self):
        connector = MagicMock()
        connector.subscribe_ticks = MagicMock()
        return connector

    def test_start_subscribes_to_ticks(self):
        connector = self._make_connector()
        feed = IBKRMarketDataFeed(connector, symbol="XAUUSD")
        feed.start()
        connector.subscribe_ticks.assert_called_once()
        feed.stop()

    def test_health_live_after_start(self):
        connector = self._make_connector()
        feed = IBKRMarketDataFeed(connector, symbol="XAUUSD")
        feed.start()
        health = feed.get_health()
        assert health.status == FeedStatus.LIVE
        feed.stop()

    def test_health_error_on_subscribe_failure(self):
        connector = self._make_connector()
        connector.subscribe_ticks.side_effect = RuntimeError("IBKR down")
        feed = IBKRMarketDataFeed(connector, symbol="XAUUSD")
        with pytest.raises(RuntimeError):
            feed.start()
        health = feed.get_health()
        assert health.status == FeedStatus.ERROR

    def test_valid_tick_increments_counter(self):
        connector = self._make_connector()
        feed = IBKRMarketDataFeed(connector, symbol="XAUUSD")
        feed.start()

        raw_tick = {
            "symbol": "XAUUSD",
            "bid": 1949.0,
            "ask": 1951.0,
            "last": 1950.0,
            "timestamp": time.time(),
            "source": "ibkr",
        }
        feed._on_raw_tick(raw_tick)

        health = feed.get_health()
        assert health.ticks_received == 1
        assert health.ticks_rejected == 0
        feed.stop()

    def test_invalid_tick_increments_rejected_counter(self):
        connector = self._make_connector()
        feed = IBKRMarketDataFeed(connector, symbol="XAUUSD")
        feed.start()

        raw_tick = {
            "symbol": "XAUUSD",
            "bid": -1.0,  # invalid
            "ask": -1.0,
            "last": 0.0,
            "timestamp": time.time(),
        }
        feed._on_raw_tick(raw_tick)

        health = feed.get_health()
        assert health.ticks_rejected == 1
        feed.stop()

    def test_on_tick_callback_invoked(self):
        connector = self._make_connector()
        received = []
        feed = IBKRMarketDataFeed(connector, symbol="XAUUSD", on_tick=received.append)
        feed.start()

        raw_tick = {
            "symbol": "XAUUSD",
            "bid": 1949.0,
            "ask": 1951.0,
            "last": 1950.0,
            "timestamp": time.time(),
        }
        feed._on_raw_tick(raw_tick)

        assert len(received) == 1
        assert isinstance(received[0], Tick)
        feed.stop()

    def test_callback_error_does_not_crash_feed(self):
        connector = self._make_connector()

        def bad_callback(tick):
            raise RuntimeError("callback exploded")

        feed = IBKRMarketDataFeed(connector, symbol="XAUUSD", on_tick=bad_callback)
        feed.start()

        raw_tick = {
            "symbol": "XAUUSD",
            "bid": 1949.0,
            "ask": 1951.0,
            "last": 1950.0,
            "timestamp": time.time(),
        }
        # Should not raise
        feed._on_raw_tick(raw_tick)
        feed.stop()

    def test_get_latest_tick(self):
        connector = self._make_connector()
        feed = IBKRMarketDataFeed(connector, symbol="XAUUSD")
        feed.start()

        raw_tick = {
            "symbol": "XAUUSD",
            "bid": 1949.0,
            "ask": 1951.0,
            "last": 1950.0,
            "timestamp": time.time(),
        }
        feed._on_raw_tick(raw_tick)
        latest = feed.get_latest_tick()
        assert latest is not None
        assert latest.symbol == "XAUUSD"
        feed.stop()


# ---------------------------------------------------------------------------
# MarketDataCache (Redis)
# ---------------------------------------------------------------------------


class TestMarketDataCache:
    def _make_redis(self):
        r = MagicMock()
        r.ping.return_value = True
        r.zrevrange.return_value = []
        r.zrangebyscore.return_value = []
        r.get.return_value = None
        return r

    def test_ping_returns_true(self):
        r = self._make_redis()
        cache = MarketDataCache(r)
        assert cache.ping() is True

    def test_get_latest_tick_returns_none_on_miss(self):
        r = self._make_redis()
        cache = MarketDataCache(r)
        assert cache.get_latest_tick("XAUUSD") is None

    def test_get_recent_ticks_returns_empty_on_miss(self):
        r = self._make_redis()
        cache = MarketDataCache(r)
        assert cache.get_recent_ticks("XAUUSD") == []

    def test_get_bars_returns_empty_on_miss(self):
        r = self._make_redis()
        cache = MarketDataCache(r)
        assert cache.get_bars("XAUUSD", "1m") == []

    def test_redis_error_returns_none_not_raises(self):
        r = MagicMock()
        r.zrevrange.side_effect = Exception("Redis connection lost")
        cache = MarketDataCache(r)
        # Should return None, not raise
        result = cache.get_latest_tick("XAUUSD")
        assert result is None

    def test_store_bar_calls_zadd(self):
        r = self._make_redis()
        # store_bar uses a pipeline — assert on the pipeline's zadd, not r.zadd directly.
        pipe = MagicMock()
        r.pipeline.return_value = pipe
        cache = MarketDataCache(r)
        bar = {
            "symbol": "XAUUSD",
            "timeframe": "1m",
            "open": 1950.0,
            "high": 1955.0,
            "low": 1945.0,
            "close": 1952.0,
            "volume": 100.0,
            "bar_open_ts": 1_700_000_000.0,
        }
        cache.store_bar("XAUUSD", "1m", bar)
        r.pipeline.assert_called_once()
        pipe.zadd.assert_called_once()

    def test_ping_returns_false_on_redis_error(self):
        r = MagicMock()
        r.ping.side_effect = Exception("connection refused")
        cache = MarketDataCache(r)
        assert cache.ping() is False

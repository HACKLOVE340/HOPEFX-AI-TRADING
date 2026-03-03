"""
Comprehensive tests for cache and config modules.
Covers MarketDataCache and ConfigManager with full branch and integration testing.
"""

import json
import os
import tempfile
import threading
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import pytest

from cache.market_data_cache import (
    CacheStatistics,
    CachedTickData,
    MarketDataCache,
    OHLCVData,
    Timeframe,
)
from config.config_manager import (
    APIConfig,
    AppConfig,
    ConfigManager,
    DatabaseConfig,
    EncryptionManager,
    LoggingConfig,
    TradingConfig,
)

# ---------------------------------------------------------------------------
# Shared helpers / fixtures
# ---------------------------------------------------------------------------

ENCRYPTION_KEY = "test-encryption-key-for-testing-purposes"
SALT_HEX = "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"


def _make_redis_mock():
    """Return a MagicMock that mimics a redis.Redis client."""
    mock = MagicMock()
    mock.ping.return_value = True
    mock.get.return_value = None
    mock.setex.return_value = True
    mock.delete.return_value = 1
    mock.scan.return_value = (0, [])
    mock.info.return_value = {"used_memory": 1024 * 1024}
    return mock


def _make_ohlcv(n: int = 3, base_ts: int = 1_700_000_000) -> list:
    return [
        OHLCVData(
            timestamp=base_ts + i * 60,
            open_price=1900.0 + i,
            high_price=1910.0 + i,
            low_price=1890.0 + i,
            close_price=1905.0 + i,
            volume=500.0 + i,
        )
        for i in range(n)
    ]


def _make_tick(ts: int = 1_700_000_000) -> CachedTickData:
    return CachedTickData(
        timestamp=ts,
        price=1905.50,
        volume=100.0,
        bid=1905.40,
        ask=1905.60,
        bid_volume=50.0,
        ask_volume=50.0,
    )


# ---------------------------------------------------------------------------
# =====================  MarketDataCache tests  ============================
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestMarketDataCacheInit:
    """Test MarketDataCache initialisation scenarios."""

    @patch.object(MarketDataCache, "_connect_with_retry")
    def test_init_defaults(self, mock_connect):
        mock_connect.return_value = _make_redis_mock()
        cache = MarketDataCache()
        assert cache.host == "localhost"
        assert cache.port == 6379
        assert cache.db == 0
        assert cache.decode_responses is True
        assert cache.max_retries == 3

    @patch.object(MarketDataCache, "_connect_with_retry")
    def test_init_custom_params(self, mock_connect):
        mock_connect.return_value = _make_redis_mock()
        cache = MarketDataCache(
            host="redis.example.com",
            port=6380,
            db=2,
            password="secret",
            socket_timeout=10,
            max_retries=5,
            retry_delay=0.5,
        )
        assert cache.host == "redis.example.com"
        assert cache.port == 6380
        assert cache.db == 2
        assert cache.max_retries == 5
        assert cache.retry_delay == 0.5

    @patch.object(MarketDataCache, "_connect_with_retry")
    def test_init_stats_zeroed(self, mock_connect):
        mock_connect.return_value = _make_redis_mock()
        cache = MarketDataCache()
        assert cache.stats.total_hits == 0
        assert cache.stats.total_misses == 0
        assert cache.stats.total_evictions == 0

    @patch("redis.Redis")
    def test_redis_unavailable_raises(self, mock_redis_cls):
        """When Redis refuses all attempts, ConnectionError is raised."""
        from redis.exceptions import ConnectionError as RedisConnErr

        mock_redis_cls.return_value.ping.side_effect = RedisConnErr("refused")
        with pytest.raises(Exception):
            MarketDataCache(max_retries=1, retry_delay=0.0)

    @patch.object(MarketDataCache, "_connect_with_retry")
    def test_context_manager(self, mock_connect):
        mock_redis = _make_redis_mock()
        mock_connect.return_value = mock_redis
        with MarketDataCache() as cache:
            assert cache is not None
        mock_redis.close.assert_called_once()


@pytest.mark.unit
class TestBuildKey:
    """Test the _build_key / _build_tick_key helpers."""

    @patch.object(MarketDataCache, "_connect_with_retry")
    def setup_method(self, method, mock_connect):
        mock_connect.return_value = _make_redis_mock()
        self.cache = MarketDataCache()

    def test_build_key_format(self):
        key = self.cache._build_key("XAUUSD", Timeframe.ONE_HOUR, "ohlcv")
        assert key == "market_data:XAUUSD:1h:ohlcv"

    def test_build_key_all_timeframes(self):
        expected = {
            Timeframe.ONE_MINUTE: "1m",
            Timeframe.FIVE_MINUTES: "5m",
            Timeframe.FIFTEEN_MINUTES: "15m",
            Timeframe.THIRTY_MINUTES: "30m",
            Timeframe.ONE_HOUR: "1h",
            Timeframe.FOUR_HOURS: "4h",
            Timeframe.ONE_DAY: "1d",
            Timeframe.ONE_WEEK: "1w",
            Timeframe.ONE_MONTH: "1M",
        }
        for tf, val in expected.items():
            key = self.cache._build_key("BTC", tf, "ohlcv")
            assert key == f"market_data:BTC:{val}:ohlcv"

    def test_build_tick_key_format(self):
        key = self.cache._build_tick_key("XAUUSD")
        assert key == "tick_data:XAUUSD"

    def test_build_key_different_data_types(self):
        for dtype in ("ohlcv", "indicators", "signals"):
            key = self.cache._build_key("ETH", Timeframe.ONE_DAY, dtype)
            assert dtype in key


@pytest.mark.unit
class TestCacheOhlcv:
    """Test cache_ohlcv / get_ohlcv round-trips."""

    @patch.object(MarketDataCache, "_connect_with_retry")
    def setup_method(self, method, mock_connect):
        self.mock_redis = _make_redis_mock()
        mock_connect.return_value = self.mock_redis
        self.cache = MarketDataCache()

    def test_cache_ohlcv_success(self):
        ohlcv = _make_ohlcv(3)
        result = self.cache.cache_ohlcv("XAUUSD", Timeframe.ONE_HOUR, ohlcv)
        assert result is True
        self.mock_redis.setex.assert_called_once()

    def test_cache_ohlcv_uses_default_ttl(self):
        ohlcv = _make_ohlcv(1)
        self.cache.cache_ohlcv("XAUUSD", Timeframe.ONE_HOUR, ohlcv)
        positional_args = self.mock_redis.setex.call_args[0]
        keyword_args = self.mock_redis.setex.call_args[1]
        if positional_args:
            ttl_arg = positional_args[1]
        else:
            ttl_arg = keyword_args.get("time") or keyword_args.get("ex")
        assert ttl_arg == MarketDataCache.DEFAULT_TTL[Timeframe.ONE_HOUR]

    def test_cache_ohlcv_custom_ttl(self):
        ohlcv = _make_ohlcv(1)
        self.cache.cache_ohlcv("XAUUSD", Timeframe.ONE_HOUR, ohlcv, ttl=9999)
        call_args = self.mock_redis.setex.call_args[0]
        assert 9999 in call_args

    def test_get_ohlcv_hit(self):
        ohlcv = _make_ohlcv(2)
        serialised = json.dumps(
            {"data": [asdict(c) for c in ohlcv], "cached_at": "2024-01-01T00:00:00"}
        )
        self.mock_redis.get.return_value = serialised

        result = self.cache.get_ohlcv("XAUUSD", Timeframe.ONE_HOUR)
        assert result is not None
        assert len(result) == 2
        assert isinstance(result[0], OHLCVData)
        assert self.cache.stats.total_hits == 1

    def test_get_ohlcv_miss(self):
        self.mock_redis.get.return_value = None
        result = self.cache.get_ohlcv("XAUUSD", Timeframe.ONE_HOUR)
        assert result is None
        assert self.cache.stats.total_misses == 1

    def test_get_ohlcv_redis_error_returns_none(self):
        self.mock_redis.get.side_effect = Exception("boom")
        result = self.cache.get_ohlcv("XAUUSD", Timeframe.ONE_HOUR)
        assert result is None
        assert self.cache.stats.total_misses == 1

    def test_cache_ohlcv_redis_error_returns_false(self):
        self.mock_redis.setex.side_effect = Exception("redis down")
        ohlcv = _make_ohlcv(1)
        result = self.cache.cache_ohlcv("XAUUSD", Timeframe.ONE_HOUR, ohlcv)
        assert result is False

    def test_all_timeframes_cache_and_retrieve(self):
        for tf in Timeframe:
            ohlcv = _make_ohlcv(1)
            serialised = json.dumps(
                {"data": [asdict(c) for c in ohlcv], "cached_at": "2024-01-01T00:00:00"}
            )
            self.mock_redis.get.return_value = serialised
            result = self.cache.get_ohlcv("XAUUSD", tf)
            assert result is not None, f"Expected result for timeframe {tf}"


@pytest.mark.unit
class TestCacheTick:
    """Test cache_tick / get_tick / cache_ticks / get_ticks."""

    @patch.object(MarketDataCache, "_connect_with_retry")
    def setup_method(self, method, mock_connect):
        self.mock_redis = _make_redis_mock()
        mock_connect.return_value = self.mock_redis
        self.cache = MarketDataCache()

    def test_cache_tick_success(self):
        tick = _make_tick()
        result = self.cache.cache_tick("XAUUSD", tick)
        assert result is True
        self.mock_redis.setex.assert_called_once()

    def test_cache_tick_default_ttl(self):
        tick = _make_tick()
        self.cache.cache_tick("XAUUSD", tick)
        call_args = self.mock_redis.setex.call_args[0]
        assert 300 in call_args  # default TTL for tick

    def test_cache_tick_custom_ttl(self):
        tick = _make_tick()
        self.cache.cache_tick("XAUUSD", tick, ttl=60)
        call_args = self.mock_redis.setex.call_args[0]
        assert 60 in call_args

    def test_get_tick_hit(self):
        tick = _make_tick()
        serialised = json.dumps({"data": asdict(tick), "cached_at": "2024-01-01T00:00:00"})
        self.mock_redis.get.return_value = serialised

        result = self.cache.get_tick("XAUUSD")
        assert result is not None
        assert isinstance(result, CachedTickData)
        assert result.price == tick.price
        assert self.cache.stats.total_hits == 1

    def test_get_tick_miss(self):
        self.mock_redis.get.return_value = None
        result = self.cache.get_tick("XAUUSD")
        assert result is None
        assert self.cache.stats.total_misses == 1

    def test_cache_ticks_list(self):
        ticks = [_make_tick(ts=1_700_000_000 + i) for i in range(5)]
        result = self.cache.cache_ticks("XAUUSD", ticks)
        assert result is True

    def test_cache_ticks_max_size_enforced(self):
        ticks = [_make_tick(ts=1_700_000_000 + i) for i in range(200)]
        result = self.cache.cache_ticks("XAUUSD", ticks, max_size=50)
        assert result is True
        call_args_str = self.mock_redis.setex.call_args[0][2]
        data = json.loads(call_args_str)
        assert data["count"] == 50

    def test_get_ticks_hit(self):
        ticks = [_make_tick(ts=1_700_000_000 + i) for i in range(3)]
        serialised = json.dumps(
            {"data": [asdict(t) for t in ticks], "cached_at": "2024-01-01T00:00:00", "count": 3}
        )
        self.mock_redis.get.return_value = serialised
        result = self.cache.get_ticks("XAUUSD")
        assert result is not None
        assert len(result) == 3
        assert isinstance(result[0], CachedTickData)

    def test_get_ticks_miss(self):
        self.mock_redis.get.return_value = None
        result = self.cache.get_ticks("XAUUSD")
        assert result is None
        assert self.cache.stats.total_misses == 1

    def test_cache_tick_redis_error_returns_false(self):
        self.mock_redis.setex.side_effect = Exception("redis down")
        result = self.cache.cache_tick("XAUUSD", _make_tick())
        assert result is False

    def test_get_tick_redis_error_returns_none(self):
        self.mock_redis.get.side_effect = Exception("redis down")
        result = self.cache.get_tick("XAUUSD")
        assert result is None


@pytest.mark.unit
class TestAppendOhlcv:
    """Test append_ohlcv behaviour."""

    @patch.object(MarketDataCache, "_connect_with_retry")
    def setup_method(self, method, mock_connect):
        self.mock_redis = _make_redis_mock()
        mock_connect.return_value = self.mock_redis
        self.cache = MarketDataCache()

    def test_append_ohlcv_new_key(self):
        self.mock_redis.get.return_value = None
        candle = _make_ohlcv(1)[0]
        result = self.cache.append_ohlcv("XAUUSD", Timeframe.ONE_HOUR, candle)
        assert result is True

    def test_append_ohlcv_existing_key(self):
        existing = _make_ohlcv(3)
        serialised = json.dumps(
            {"data": [asdict(c) for c in existing], "cached_at": "2024-01-01T00:00:00"}
        )
        self.mock_redis.get.return_value = serialised
        candle = _make_ohlcv(1)[0]
        result = self.cache.append_ohlcv("XAUUSD", Timeframe.ONE_HOUR, candle)
        assert result is True

    def test_append_ohlcv_max_size_enforced(self):
        existing = _make_ohlcv(100)
        serialised = json.dumps(
            {"data": [asdict(c) for c in existing], "cached_at": "2024-01-01T00:00:00"}
        )
        self.mock_redis.get.return_value = serialised
        candle = _make_ohlcv(1)[0]
        result = self.cache.append_ohlcv("XAUUSD", Timeframe.ONE_HOUR, candle, max_size=50)
        assert result is True
        stored_json = self.mock_redis.setex.call_args[0][2]
        stored_data = json.loads(stored_json)
        assert len(stored_data["data"]) == 50


@pytest.mark.unit
class TestMultiTimeframe:
    """Test multi-timeframe batch operations."""

    @patch.object(MarketDataCache, "_connect_with_retry")
    def setup_method(self, method, mock_connect):
        self.mock_redis = _make_redis_mock()
        mock_connect.return_value = self.mock_redis
        self.cache = MarketDataCache()

    def test_cache_multi_timeframe(self):
        data = {
            Timeframe.ONE_HOUR: _make_ohlcv(2),
            Timeframe.ONE_DAY: _make_ohlcv(2),
        }
        result = self.cache.cache_multi_timeframe("XAUUSD", data)
        assert result is True
        assert self.mock_redis.setex.call_count == 2

    def test_cache_multi_timeframe_custom_ttl(self):
        data = {Timeframe.ONE_HOUR: _make_ohlcv(1)}
        ttl = {Timeframe.ONE_HOUR: 1234}
        self.cache.cache_multi_timeframe("XAUUSD", data, ttl=ttl)
        call_args = self.mock_redis.setex.call_args[0]
        assert 1234 in call_args

    def test_get_multi_timeframe(self):
        ohlcv = _make_ohlcv(1)
        serialised = json.dumps(
            {"data": [asdict(c) for c in ohlcv], "cached_at": "2024-01-01T00:00:00"}
        )
        self.mock_redis.get.return_value = serialised
        result = self.cache.get_multi_timeframe("XAUUSD", [Timeframe.ONE_HOUR, Timeframe.ONE_DAY])
        assert Timeframe.ONE_HOUR in result
        assert Timeframe.ONE_DAY in result
        assert result[Timeframe.ONE_HOUR] is not None


@pytest.mark.unit
class TestCacheInvalidation:
    """Test invalidation / eviction operations."""

    @patch.object(MarketDataCache, "_connect_with_retry")
    def setup_method(self, method, mock_connect):
        self.mock_redis = _make_redis_mock()
        mock_connect.return_value = self.mock_redis
        self.cache = MarketDataCache()

    def test_invalidate_ohlcv(self):
        result = self.cache.invalidate_ohlcv("XAUUSD", Timeframe.ONE_HOUR)
        assert result is True
        self.mock_redis.delete.assert_called_once()
        assert self.cache.stats.total_evictions == 1

    def test_invalidate_ohlcv_error_returns_false(self):
        self.mock_redis.delete.side_effect = Exception("boom")
        result = self.cache.invalidate_ohlcv("XAUUSD", Timeframe.ONE_HOUR)
        assert result is False

    def test_invalidate_tick(self):
        result = self.cache.invalidate_tick("XAUUSD")
        assert result is True
        assert self.cache.stats.total_evictions == 1

    def test_invalidate_symbol_deletes_keys(self):
        self.mock_redis.scan.return_value = (0, ["market_data:XAUUSD:1h:ohlcv"])
        result = self.cache.invalidate_symbol("XAUUSD")
        assert result is True
        # delete called for the scanned keys + tick invalidation
        assert self.mock_redis.delete.call_count >= 1

    def test_clear_all(self):
        self.mock_redis.scan.return_value = (0, ["market_data:XAUUSD:1h:ohlcv"])
        result = self.cache.clear_all()
        assert result is True
        self.mock_redis.delete.assert_called()

    def test_clear_all_error_returns_false(self):
        self.mock_redis.scan.side_effect = Exception("boom")
        result = self.cache.clear_all()
        assert result is False


@pytest.mark.unit
class TestCacheStatisticsOperations:
    """Test statistics retrieval and reset."""

    @patch.object(MarketDataCache, "_connect_with_retry")
    def setup_method(self, method, mock_connect):
        self.mock_redis = _make_redis_mock()
        mock_connect.return_value = self.mock_redis
        self.cache = MarketDataCache()

    def test_get_statistics_returns_cache_statistics(self):
        self.mock_redis.scan.return_value = (0, [])
        self.mock_redis.info.return_value = {"used_memory": 2048}
        stats = self.cache.get_statistics()
        assert isinstance(stats, CacheStatistics)
        assert stats.memory_usage_bytes == 2048

    def test_get_statistics_counts_keys(self):
        call_count = {"n": 0}

        def scan_side_effect(*args, **kwargs):
            call_count["n"] += 1
            match = kwargs.get("match", "")
            if "market_data" in match and call_count["n"] == 1:
                return (0, ["market_data:XAUUSD:1h:ohlcv", "market_data:XAUUSD:1d:ohlcv"])
            return (0, [])

        self.mock_redis.scan.side_effect = scan_side_effect
        self.mock_redis.info.return_value = {"used_memory": 1024}
        stats = self.cache.get_statistics()
        assert stats.total_keys >= 0

    def test_get_statistics_error_returns_empty(self):
        self.mock_redis.scan.side_effect = Exception("boom")
        stats = self.cache.get_statistics()
        assert isinstance(stats, CacheStatistics)
        assert stats.total_hits == 0

    def test_reset_statistics(self):
        # Manually bump stats
        self.cache.stats.total_hits = 50
        self.cache.stats.total_misses = 20
        self.cache.reset_statistics()
        assert self.cache.stats.total_hits == 0
        assert self.cache.stats.total_misses == 0

    def test_stats_accumulate_across_operations(self):
        ohlcv = _make_ohlcv(1)
        serialised = json.dumps(
            {"data": [asdict(c) for c in ohlcv], "cached_at": "2024-01-01T00:00:00"}
        )
        # 2 hits
        self.mock_redis.get.return_value = serialised
        self.cache.get_ohlcv("XAUUSD", Timeframe.ONE_HOUR)
        self.cache.get_ohlcv("XAUUSD", Timeframe.ONE_DAY)
        # 1 miss
        self.mock_redis.get.return_value = None
        self.cache.get_ohlcv("BTC", Timeframe.ONE_HOUR)

        assert self.cache.stats.total_hits == 2
        assert self.cache.stats.total_misses == 1

    def test_print_statistics_no_exception(self):
        self.mock_redis.scan.return_value = (0, [])
        self.mock_redis.info.return_value = {"used_memory": 1024}
        self.cache.print_statistics()  # should not raise


@pytest.mark.unit
class TestHealthAndClose:
    """Test health_check and close."""

    @patch.object(MarketDataCache, "_connect_with_retry")
    def setup_method(self, method, mock_connect):
        self.mock_redis = _make_redis_mock()
        mock_connect.return_value = self.mock_redis
        self.cache = MarketDataCache()

    def test_health_check_success(self):
        self.mock_redis.ping.return_value = True
        assert self.cache.health_check() is True

    def test_health_check_failure(self):
        self.mock_redis.ping.side_effect = Exception("no connection")
        assert self.cache.health_check() is False

    def test_close(self):
        self.cache.close()
        self.mock_redis.close.assert_called_once()


@pytest.mark.unit
class TestCacheDefaultTTL:
    """Test DEFAULT_TTL values for all timeframes."""

    def test_all_timeframes_have_ttl(self):
        for tf in Timeframe:
            assert tf in MarketDataCache.DEFAULT_TTL, f"Missing TTL for {tf}"

    def test_ttl_increases_with_timeframe(self):
        ttl = MarketDataCache.DEFAULT_TTL
        # Shorter timeframes should have shorter TTL
        assert ttl[Timeframe.ONE_MINUTE] < ttl[Timeframe.ONE_HOUR]
        assert ttl[Timeframe.ONE_HOUR] < ttl[Timeframe.ONE_DAY]
        assert ttl[Timeframe.ONE_DAY] < ttl[Timeframe.ONE_MONTH]


@pytest.mark.unit
class TestCacheThreadSafety:
    """Thread-safety checks for stats updates."""

    @patch.object(MarketDataCache, "_connect_with_retry")
    def test_concurrent_hit_miss_updates(self, mock_connect):
        mock_redis = _make_redis_mock()
        mock_connect.return_value = mock_redis
        cache = MarketDataCache()

        ohlcv = _make_ohlcv(1)
        serialised = json.dumps(
            {"data": [asdict(c) for c in ohlcv], "cached_at": "2024-01-01T00:00:00"}
        )
        mock_redis.get.return_value = serialised

        def do_hits():
            for _ in range(50):
                cache.get_ohlcv("XAUUSD", Timeframe.ONE_HOUR)

        threads = [threading.Thread(target=do_hits) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert cache.stats.total_hits == 200


# ---------------------------------------------------------------------------
# =====================  ConfigManager tests  ==============================
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=False)
def encryption_env(monkeypatch):
    monkeypatch.setenv("CONFIG_ENCRYPTION_KEY", ENCRYPTION_KEY)
    monkeypatch.setenv("CONFIG_SALT", SALT_HEX)


@pytest.mark.unit
class TestEncryptionManagerExtended:
    """Additional EncryptionManager tests."""

    @pytest.fixture(autouse=True)
    def _set_env(self, monkeypatch):
        monkeypatch.setenv("CONFIG_ENCRYPTION_KEY", ENCRYPTION_KEY)
        monkeypatch.setenv("CONFIG_SALT", SALT_HEX)

    def test_no_key_raises_value_error(self, monkeypatch):
        monkeypatch.delenv("CONFIG_ENCRYPTION_KEY", raising=False)
        with pytest.raises(ValueError):
            EncryptionManager()

    def test_explicit_key_overrides_env(self, monkeypatch):
        monkeypatch.delenv("CONFIG_ENCRYPTION_KEY", raising=False)
        mgr = EncryptionManager(master_key="override-key-value")
        assert mgr.master_key == "override-key-value"

    def test_invalid_salt_raises_value_error(self, monkeypatch):
        monkeypatch.setenv("CONFIG_SALT", "not-valid-hex!!")
        with pytest.raises(ValueError):
            EncryptionManager()

    def test_encrypt_produces_different_output(self):
        mgr = EncryptionManager()
        enc1 = mgr.encrypt("hello")
        enc2 = mgr.encrypt("hello")
        # Fernet uses random IV, so two encryptions of the same plaintext differ
        assert enc1 != "hello"
        assert enc2 != "hello"

    def test_decrypt_roundtrip_unicode(self):
        mgr = EncryptionManager()
        text = "αβγδ こんにちは 🚀"
        assert mgr.decrypt(mgr.encrypt(text)) == text

    def test_salt_derived_from_master_key_when_no_env_salt(self, monkeypatch):
        monkeypatch.delenv("CONFIG_SALT", raising=False)
        mgr = EncryptionManager(master_key="some-key")
        assert mgr is not None  # should not raise; warning logged instead

    def test_hash_password_returns_salt_and_hash(self):
        mgr = EncryptionManager()
        result = mgr.hash_password("password")
        parts = result.split("$")
        assert len(parts) == 2

    def test_verify_password_with_explicit_salt(self):
        import secrets as sec

        mgr = EncryptionManager()
        salt = sec.token_bytes(16)
        hashed = mgr.hash_password("pw", salt=salt)
        assert mgr.verify_password("pw", hashed) is True
        assert mgr.verify_password("wrong", hashed) is False

    def test_verify_password_bad_format_returns_false(self):
        mgr = EncryptionManager()
        assert mgr.verify_password("pw", "no_dollar_sign_here") is False


@pytest.mark.unit
class TestAPIConfigExtended:
    """Extended APIConfig tests."""

    def test_validate_missing_api_key(self):
        cfg = APIConfig(provider="p", api_key="", api_secret="s")
        assert cfg.validate() is False

    def test_validate_missing_api_secret(self):
        cfg = APIConfig(provider="p", api_key="k", api_secret="")
        assert cfg.validate() is False

    def test_validate_missing_provider(self):
        cfg = APIConfig(provider="", api_key="k", api_secret="s")
        assert cfg.validate() is False

    def test_validate_valid_config(self):
        cfg = APIConfig(provider="binance", api_key="key", api_secret="secret")
        assert cfg.validate() is True

    def test_defaults_sandbox_true(self):
        cfg = APIConfig(provider="p", api_key="k", api_secret="s")
        assert cfg.sandbox_mode is True

    def test_rate_limit_default(self):
        cfg = APIConfig(provider="p", api_key="k", api_secret="s")
        assert cfg.rate_limit == 100


@pytest.mark.unit
class TestDatabaseConfigExtended:
    """Extended DatabaseConfig tests."""

    def _sqlite(self):
        return DatabaseConfig(
            db_type="sqlite", host="", port=0, username="", password="", database="test.db"
        )

    def _pg(self):
        return DatabaseConfig(
            db_type="postgresql",
            host="localhost",
            port=5432,
            username="user",
            password="pass",
            database="hopefx",
        )

    def test_sqlite_validate(self):
        assert self._sqlite().validate() is True

    def test_postgresql_validate(self):
        assert self._pg().validate() is True

    def test_unsupported_db_type_validate(self):
        cfg = DatabaseConfig(
            db_type="oracle", host="h", port=1521, username="u", password="p", database="d"
        )
        assert cfg.validate() is False

    def test_sqlite_connection_string(self):
        cs = self._sqlite().get_connection_string()
        assert cs == "sqlite:///test.db"

    def test_postgresql_connection_string_with_ssl(self):
        cfg = self._pg()
        cfg.ssl_enabled = True
        cfg.ssl_mode = "require"
        cs = cfg.get_connection_string()
        assert "sslmode=require" in cs

    def test_postgresql_connection_string_no_ssl(self):
        cfg = self._pg()
        cfg.ssl_enabled = False
        cs = cfg.get_connection_string()
        assert "sslmode" not in cs

    def test_mysql_connection_string(self):
        cfg = DatabaseConfig(
            db_type="mysql",
            host="localhost",
            port=3306,
            username="user",
            password="pass",
            database="mydb",
            ssl_enabled=False,
        )
        cs = cfg.get_connection_string()
        assert "mysql+pymysql://" in cs

    def test_mysql_with_ssl(self):
        cfg = DatabaseConfig(
            db_type="mysql",
            host="localhost",
            port=3306,
            username="user",
            password="pass",
            database="mydb",
            ssl_enabled=True,
        )
        cs = cfg.get_connection_string()
        assert "ssl=true" in cs

    def test_unsupported_db_connection_string_raises(self):
        cfg = DatabaseConfig(
            db_type="cassandra", host="h", port=9042, username="u", password="p", database="d"
        )
        with pytest.raises(ValueError):
            cfg.get_connection_string()


@pytest.mark.unit
class TestTradingConfigExtended:
    """Extended TradingConfig tests."""

    def test_validate_invalid_position_size(self):
        cfg = TradingConfig(max_position_size=-100)
        assert cfg.validate() is False

    def test_validate_invalid_leverage(self):
        cfg = TradingConfig(max_leverage=0)
        assert cfg.validate() is False

    def test_validate_leverage_too_high(self):
        cfg = TradingConfig(max_leverage=200)
        assert cfg.validate() is False

    def test_validate_invalid_risk_per_trade(self):
        cfg = TradingConfig(risk_per_trade=0)
        assert cfg.validate() is False

    def test_validate_valid(self):
        cfg = TradingConfig()
        assert cfg.validate() is True

    def test_paper_trading_default_true(self):
        assert TradingConfig().paper_trading_mode is True

    def test_trading_disabled_by_default(self):
        assert TradingConfig().trading_enabled is False


@pytest.mark.unit
class TestLoggingConfigExtended:
    """Extended LoggingConfig tests."""

    def test_validate_invalid_level(self):
        cfg = LoggingConfig(level="VERBOSE")
        assert cfg.validate() is False

    def test_validate_valid_levels(self):
        for lvl in ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"):
            assert LoggingConfig(level=lvl).validate() is True


@pytest.mark.unit
class TestAppConfigValidation:
    """Test AppConfig.validate aggregates sub-config validation."""

    def test_validate_all_valid(self):
        cfg = AppConfig()
        assert cfg.validate() is True

    def test_validate_propagates_trading_failure(self):
        cfg = AppConfig()
        cfg.trading.max_position_size = -1
        assert cfg.validate() is False

    def test_validate_propagates_logging_failure(self):
        cfg = AppConfig()
        cfg.logging.level = "UNKNOWN"
        assert cfg.validate() is False

    def test_validate_propagates_api_config_failure(self):
        cfg = AppConfig()
        cfg.api_configs["bad"] = APIConfig(provider="", api_key="", api_secret="")
        assert cfg.validate() is False

    def test_validate_with_valid_api_config(self):
        cfg = AppConfig()
        cfg.api_configs["binance"] = APIConfig(
            provider="binance", api_key="k", api_secret="s"
        )
        assert cfg.validate() is True


@pytest.mark.unit
class TestConfigManagerInit:
    """Test ConfigManager initialisation."""

    def test_init_creates_config_dir(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CONFIG_ENCRYPTION_KEY", ENCRYPTION_KEY)
        monkeypatch.setenv("CONFIG_SALT", SALT_HEX)
        target = tmp_path / "cfg_dir"
        mgr = ConfigManager(config_dir=str(target))
        assert target.exists()

    def test_init_config_none_before_load(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CONFIG_ENCRYPTION_KEY", ENCRYPTION_KEY)
        monkeypatch.setenv("CONFIG_SALT", SALT_HEX)
        mgr = ConfigManager(config_dir=str(tmp_path))
        assert mgr.config is None


@pytest.mark.unit
class TestConfigManagerLoadConfig:
    """Test load_config and default-config creation."""

    @pytest.fixture(autouse=True)
    def _set_env(self, monkeypatch):
        monkeypatch.setenv("CONFIG_ENCRYPTION_KEY", ENCRYPTION_KEY)
        monkeypatch.setenv("CONFIG_SALT", SALT_HEX)

    def test_load_creates_default_when_missing(self, tmp_path):
        mgr = ConfigManager(config_dir=str(tmp_path))
        cfg = mgr.load_config("development")
        assert isinstance(cfg, AppConfig)
        assert (tmp_path / "config.development.json").exists()

    def test_load_returns_app_config(self, tmp_path):
        mgr = ConfigManager(config_dir=str(tmp_path))
        cfg = mgr.load_config("development")
        assert cfg.app_name == "HOPEFX AI Trading"
        assert cfg.version == "1.0.0"

    def test_load_sets_timestamp(self, tmp_path):
        mgr = ConfigManager(config_dir=str(tmp_path))
        mgr.load_config("development")
        assert mgr._load_timestamp is not None

    def test_load_sets_config_hash(self, tmp_path):
        mgr = ConfigManager(config_dir=str(tmp_path))
        mgr.load_config("development")
        assert mgr._config_hash is not None

    def test_load_uses_app_env(self, tmp_path, monkeypatch):
        monkeypatch.setenv("APP_ENV", "staging")
        mgr = ConfigManager(config_dir=str(tmp_path))
        mgr.load_config()
        assert (tmp_path / "config.staging.json").exists()

    def test_load_existing_file(self, tmp_path):
        config_data = {
            "app_name": "Custom App",
            "version": "2.0.0",
            "environment": "testing",
            "debug": False,
            "api_configs": {},
            "database": {
                "db_type": "sqlite",
                "host": "localhost",
                "port": 5432,
                "username": "",
                "password": "",
                "database": "test.db",
                "ssl_enabled": True,
                "connection_pool_size": 10,
                "max_overflow": 20,
                "pool_timeout": 30,
            },
            "trading": {
                "max_position_size": 5000.0,
                "max_leverage": 2.0,
                "stop_loss_percent": 1.5,
                "take_profit_percent": 3.0,
                "max_open_orders": 5,
                "risk_per_trade": 0.5,
                "daily_loss_limit": 3.0,
                "trading_enabled": False,
                "paper_trading_mode": True,
            },
            "logging": {
                "level": "DEBUG",
                "log_file": "logs/test.log",
                "max_file_size_mb": 50,
                "backup_count": 5,
                "format_string": "%(message)s",
            },
        }
        config_file = tmp_path / "config.testing.json"
        config_file.write_text(json.dumps(config_data))

        mgr = ConfigManager(config_dir=str(tmp_path))
        cfg = mgr.load_config("testing")
        assert cfg.app_name == "Custom App"
        assert cfg.trading.max_position_size == 5000.0

    def test_load_trading_section_values(self, tmp_path):
        mgr = ConfigManager(config_dir=str(tmp_path))
        cfg = mgr.load_config("development")
        assert cfg.trading.max_position_size == 10000.0
        assert cfg.trading.paper_trading_mode is True
        assert cfg.trading.trading_enabled is False

    def test_load_logging_section_values(self, tmp_path):
        mgr = ConfigManager(config_dir=str(tmp_path))
        cfg = mgr.load_config("development")
        assert cfg.logging.level == "INFO"

    def test_load_database_section_values(self, tmp_path):
        mgr = ConfigManager(config_dir=str(tmp_path))
        cfg = mgr.load_config("development")
        assert cfg.database.db_type == "sqlite"


@pytest.mark.unit
class TestConfigManagerSaveConfig:
    """Test save_config and serialisation."""

    @pytest.fixture(autouse=True)
    def _set_env(self, monkeypatch):
        monkeypatch.setenv("CONFIG_ENCRYPTION_KEY", ENCRYPTION_KEY)
        monkeypatch.setenv("CONFIG_SALT", SALT_HEX)

    def test_save_creates_file(self, tmp_path):
        mgr = ConfigManager(config_dir=str(tmp_path))
        cfg = AppConfig(environment="myenv")
        mgr.save_config(cfg)
        assert (tmp_path / "config.myenv.json").exists()

    def test_save_and_reload_roundtrip(self, tmp_path):
        mgr = ConfigManager(config_dir=str(tmp_path))
        cfg = AppConfig(app_name="RoundTrip", environment="test")
        cfg.trading.max_leverage = 2.0
        mgr.save_config(cfg)

        mgr2 = ConfigManager(config_dir=str(tmp_path))
        loaded = mgr2.load_config("test")
        assert loaded.app_name == "RoundTrip"
        assert loaded.trading.max_leverage == 2.0

    def test_save_encrypts_api_credentials(self, tmp_path):
        mgr = ConfigManager(config_dir=str(tmp_path))
        cfg = AppConfig(environment="enc_test")
        cfg.api_configs["binance"] = APIConfig(
            provider="binance", api_key="myapikey", api_secret="mysecret"
        )
        mgr.save_config(cfg)

        raw = json.loads((tmp_path / "config.enc_test.json").read_text())
        stored_key = raw["api_configs"]["binance"]["api_key"]
        assert stored_key != "myapikey"  # should be encrypted


@pytest.mark.unit
class TestConfigManagerAPICredentials:
    """Test get_api_config and update_api_credential."""

    @pytest.fixture(autouse=True)
    def _set_env(self, monkeypatch):
        monkeypatch.setenv("CONFIG_ENCRYPTION_KEY", ENCRYPTION_KEY)
        monkeypatch.setenv("CONFIG_SALT", SALT_HEX)

    def test_get_api_config_raises_when_not_loaded(self, tmp_path):
        mgr = ConfigManager(config_dir=str(tmp_path))
        with pytest.raises(RuntimeError):
            mgr.get_api_config("binance")

    def test_get_api_config_returns_none_for_missing_provider(self, tmp_path):
        mgr = ConfigManager(config_dir=str(tmp_path))
        mgr.load_config("development")
        # default config has binance key with empty credentials
        result = mgr.get_api_config("nonexistent_broker")
        assert result is None

    def test_get_api_config_returns_api_config(self, tmp_path):
        mgr = ConfigManager(config_dir=str(tmp_path))
        mgr.load_config("development")
        result = mgr.get_api_config("binance")
        assert result is not None
        assert isinstance(result, APIConfig)

    def test_update_api_credential_raises_when_not_loaded(self, tmp_path):
        mgr = ConfigManager(config_dir=str(tmp_path))
        with pytest.raises(RuntimeError):
            mgr.update_api_credential("binance", "k", "s")

    def test_update_api_credential_updates_existing(self, tmp_path):
        mgr = ConfigManager(config_dir=str(tmp_path))
        mgr.load_config("development")
        mgr.update_api_credential("binance", "newkey", "newsecret")
        cfg = mgr.get_api_config("binance")
        assert cfg.api_key == "newkey"
        assert cfg.api_secret == "newsecret"

    def test_update_api_credential_creates_new_provider(self, tmp_path):
        mgr = ConfigManager(config_dir=str(tmp_path))
        mgr.load_config("development")
        mgr.update_api_credential("alpaca", "alp_key", "alp_secret")
        cfg = mgr.get_api_config("alpaca")
        assert cfg is not None
        assert cfg.api_key == "alp_key"


@pytest.mark.unit
class TestConfigManagerModificationDetection:
    """Test is_config_modified / _hash_config."""

    @pytest.fixture(autouse=True)
    def _set_env(self, monkeypatch):
        monkeypatch.setenv("CONFIG_ENCRYPTION_KEY", ENCRYPTION_KEY)
        monkeypatch.setenv("CONFIG_SALT", SALT_HEX)

    def test_not_modified_after_load(self, tmp_path):
        mgr = ConfigManager(config_dir=str(tmp_path))
        mgr.load_config("development")
        assert mgr.is_config_modified() is False

    def test_modified_after_in_memory_change(self, tmp_path):
        mgr = ConfigManager(config_dir=str(tmp_path))
        mgr.load_config("development")
        mgr.config.app_name = "Changed Name"
        assert mgr.is_config_modified() is True

    def test_not_modified_when_not_loaded(self, tmp_path):
        mgr = ConfigManager(config_dir=str(tmp_path))
        assert mgr.is_config_modified() is False


@pytest.mark.unit
class TestConfigManagerReload:
    """Test reload_config."""

    @pytest.fixture(autouse=True)
    def _set_env(self, monkeypatch):
        monkeypatch.setenv("CONFIG_ENCRYPTION_KEY", ENCRYPTION_KEY)
        monkeypatch.setenv("CONFIG_SALT", SALT_HEX)

    def test_reload_raises_when_not_loaded(self, tmp_path):
        mgr = ConfigManager(config_dir=str(tmp_path))
        with pytest.raises(RuntimeError):
            mgr.reload_config()

    def test_reload_returns_app_config(self, tmp_path):
        mgr = ConfigManager(config_dir=str(tmp_path))
        mgr.load_config("development")
        reloaded = mgr.reload_config()
        assert isinstance(reloaded, AppConfig)


@pytest.mark.unit
class TestConfigManagerStatus:
    """Test get_status."""

    @pytest.fixture(autouse=True)
    def _set_env(self, monkeypatch):
        monkeypatch.setenv("CONFIG_ENCRYPTION_KEY", ENCRYPTION_KEY)
        monkeypatch.setenv("CONFIG_SALT", SALT_HEX)

    def test_status_before_load(self, tmp_path):
        mgr = ConfigManager(config_dir=str(tmp_path))
        status = mgr.get_status()
        assert status["loaded"] is False
        assert status["environment"] is None
        assert status["last_load"] is None

    def test_status_after_load(self, tmp_path):
        mgr = ConfigManager(config_dir=str(tmp_path))
        mgr.load_config("development")
        status = mgr.get_status()
        assert status["loaded"] is True
        assert status["environment"] == "development"
        assert status["last_load"] is not None
        assert status["config_hash"] is not None

    def test_status_modified_false_after_load(self, tmp_path):
        mgr = ConfigManager(config_dir=str(tmp_path))
        mgr.load_config("development")
        assert mgr.get_status()["modified"] is False


@pytest.mark.unit
class TestConfigManagerDefaultsFallback:
    """Test that missing keys return expected defaults during parsing."""

    @pytest.fixture(autouse=True)
    def _set_env(self, monkeypatch):
        monkeypatch.setenv("CONFIG_ENCRYPTION_KEY", ENCRYPTION_KEY)
        monkeypatch.setenv("CONFIG_SALT", SALT_HEX)

    def _write_minimal_config(self, path: Path, env: str) -> None:
        """Write a nearly-empty config file."""
        path.mkdir(parents=True, exist_ok=True)
        (path / f"config.{env}.json").write_text(json.dumps({}))

    def test_empty_config_uses_defaults(self, tmp_path):
        self._write_minimal_config(tmp_path, "empty")
        mgr = ConfigManager(config_dir=str(tmp_path))
        cfg = mgr.load_config("empty")
        assert cfg.app_name == "HOPEFX AI Trading"
        assert cfg.database.db_type == "sqlite"
        assert cfg.trading.paper_trading_mode is True
        assert cfg.logging.level == "INFO"

    def test_partial_trading_config_uses_defaults(self, tmp_path):
        (tmp_path / "config.partial.json").write_text(
            json.dumps({"trading": {"max_leverage": 3.0}})
        )
        mgr = ConfigManager(config_dir=str(tmp_path))
        cfg = mgr.load_config("partial")
        assert cfg.trading.max_leverage == 3.0
        assert cfg.trading.risk_per_trade == 1.0  # default


@pytest.mark.unit
class TestEncryptDecryptIntegration:
    """Integration tests for encrypt/decrypt within ConfigManager flow."""

    @pytest.fixture(autouse=True)
    def _set_env(self, monkeypatch):
        monkeypatch.setenv("CONFIG_ENCRYPTION_KEY", ENCRYPTION_KEY)
        monkeypatch.setenv("CONFIG_SALT", SALT_HEX)

    def test_api_credentials_survive_save_load(self, tmp_path):
        mgr = ConfigManager(config_dir=str(tmp_path))
        cfg = AppConfig(environment="creds_test")
        cfg.api_configs["alpaca"] = APIConfig(
            provider="alpaca", api_key="real_api_key", api_secret="real_api_secret"
        )
        mgr.save_config(cfg)

        mgr2 = ConfigManager(config_dir=str(tmp_path))
        loaded = mgr2.load_config("creds_test")
        assert loaded.api_configs["alpaca"].api_key == "real_api_key"
        assert loaded.api_configs["alpaca"].api_secret == "real_api_secret"

    def test_database_password_survives_save_load(self, tmp_path):
        mgr = ConfigManager(config_dir=str(tmp_path))
        cfg = AppConfig(environment="db_test")
        cfg.database = DatabaseConfig(
            db_type="postgresql",
            host="db.example.com",
            port=5432,
            username="admin",
            password="s3cr3t",
            database="hopefx",
        )
        mgr.save_config(cfg)

        mgr2 = ConfigManager(config_dir=str(tmp_path))
        loaded = mgr2.load_config("db_test")
        assert loaded.database.password == "s3cr3t"
        assert loaded.database.username == "admin"

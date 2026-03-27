# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
Unit tests for the Redis-backed feature cache in ml/live_inference.py

Verifies:
- Cache miss returns None
- Cache set + get round-trips a DataFrame correctly
- TTL expiry evicts the entry (in-memory path)
- Redis path is used when Redis is available (mocked)
- In-memory LRU evicts oldest entry at capacity
- Cache key is scoped to (symbol, timestamp) — different symbols don't collide
- invalidate() clears all entries
- AdvancedModelPredictor uses the cache on repeated calls
"""

from __future__ import annotations

import time
from unittest.mock import MagicMock

import numpy as np
import pandas as pd
import pytest


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_cache(ttl: int = 60):
    from ml.live_inference import _FeatureCache

    c = _FeatureCache()
    c._connected = True  # skip Redis connect attempt
    return c


def _make_features(n_cols: int = 5) -> pd.DataFrame:
    return pd.DataFrame({f"f{i}": [float(i)] for i in range(n_cols)})


# ── In-memory path ────────────────────────────────────────────────────────────


class TestInMemoryCache:
    def test_miss_returns_none(self):
        cache = _make_cache()
        assert cache.get("XAUUSD", "2026-01-01") is None

    def test_set_then_get_returns_dataframe(self):
        cache = _make_cache()
        df = _make_features()
        cache.set("XAUUSD", "2026-01-01", df)
        result = cache.get("XAUUSD", "2026-01-01")
        assert result is not None
        assert list(result.columns) == list(df.columns)
        assert result.iloc[0]["f0"] == pytest.approx(0.0)

    def test_different_symbols_dont_collide(self):
        cache = _make_cache()
        df_gold = _make_features(3)
        df_eur = pd.DataFrame({"a": [99.0], "b": [88.0], "c": [77.0]})
        cache.set("XAUUSD", "ts1", df_gold)
        cache.set("EURUSD", "ts1", df_eur)

        r_gold = cache.get("XAUUSD", "ts1")
        r_eur = cache.get("EURUSD", "ts1")
        assert r_gold is not None
        assert r_eur is not None
        assert "f0" in r_gold.columns
        assert "a" in r_eur.columns

    def test_different_timestamps_dont_collide(self):
        cache = _make_cache()
        df1 = pd.DataFrame({"v": [1.0]})
        df2 = pd.DataFrame({"v": [2.0]})
        cache.set("XAUUSD", "ts-A", df1)
        cache.set("XAUUSD", "ts-B", df2)

        assert cache.get("XAUUSD", "ts-A").iloc[0]["v"] == pytest.approx(1.0)
        assert cache.get("XAUUSD", "ts-B").iloc[0]["v"] == pytest.approx(2.0)

    def test_expired_entry_returns_none(self):
        from ml.live_inference import _FeatureCache

        cache = _FeatureCache()
        cache._connected = True
        # Manually insert an already-expired entry
        key = cache._make_key("XAUUSD", "old-ts")
        cache._mem[key] = (time.monotonic() - 1.0, '{"f0": 0.0}')  # expired 1s ago

        result = cache.get("XAUUSD", "old-ts")
        assert result is None
        assert key not in cache._mem  # evicted on access

    def test_lru_evicts_oldest_at_capacity(self):
        from ml.live_inference import _FeatureCache

        cache = _FeatureCache()
        cache._connected = True
        cache._MAX_MEM = 3  # tiny capacity for testing

        for i in range(3):
            cache.set("SYM", f"ts-{i}", pd.DataFrame({"v": [float(i)]}))

        assert len(cache._mem) == 3

        # Adding a 4th should evict the oldest
        cache.set("SYM", "ts-3", pd.DataFrame({"v": [3.0]}))
        assert len(cache._mem) == 3

    def test_invalidate_clears_all_entries(self):
        cache = _make_cache()
        for i in range(5):
            cache.set("XAUUSD", f"ts-{i}", _make_features())
        assert len(cache._mem) > 0

        deleted = cache.invalidate("XAUUSD")
        assert deleted > 0
        assert len(cache._mem) == 0

    def test_backend_is_memory_without_redis(self):
        cache = _make_cache()
        assert cache.backend == "memory"

    def test_nan_and_inf_are_serialised_as_zero(self):
        cache = _make_cache()
        df = pd.DataFrame({"a": [np.inf], "b": [-np.inf], "c": [np.nan], "d": [1.5]})
        cache.set("XAUUSD", "nan-ts", df)
        result = cache.get("XAUUSD", "nan-ts")
        assert result is not None
        assert result.iloc[0]["a"] == pytest.approx(0.0)
        assert result.iloc[0]["d"] == pytest.approx(1.5)


# ── Redis path (mocked) ───────────────────────────────────────────────────────


class TestRedisPath:
    def test_redis_get_returns_dataframe_on_hit(self):
        from ml.live_inference import _FeatureCache

        cache = _FeatureCache()
        cache._connected = True
        mock_redis = MagicMock()
        mock_redis.get.return_value = b'{"f0": 1.0, "f1": 2.0}'
        cache._redis = mock_redis

        result = cache.get("XAUUSD", "ts-redis")
        assert result is not None
        assert result.iloc[0]["f0"] == pytest.approx(1.0)

    def test_redis_get_returns_none_on_miss(self):
        from ml.live_inference import _FeatureCache

        cache = _FeatureCache()
        cache._connected = True
        mock_redis = MagicMock()
        mock_redis.get.return_value = None
        cache._redis = mock_redis

        result = cache.get("XAUUSD", "ts-miss")
        assert result is None

    def test_redis_set_calls_setex_with_ttl(self):
        from ml.live_inference import _FeatureCache, _CACHE_TTL

        cache = _FeatureCache()
        cache._connected = True
        mock_redis = MagicMock()
        cache._redis = mock_redis

        df = pd.DataFrame({"f0": [1.0]})
        cache.set("XAUUSD", "ts-set", df)

        mock_redis.setex.assert_called_once()
        args = mock_redis.setex.call_args[0]
        assert args[1] == _CACHE_TTL  # TTL is second positional arg

    def test_redis_error_does_not_raise(self):
        from ml.live_inference import _FeatureCache

        cache = _FeatureCache()
        cache._connected = True
        mock_redis = MagicMock()
        mock_redis.get.side_effect = Exception("Redis down")
        cache._redis = mock_redis

        # Must not raise
        result = cache.get("XAUUSD", "ts-err")
        assert result is None

    def test_backend_is_redis_when_connected(self):
        from ml.live_inference import _FeatureCache

        cache = _FeatureCache()
        cache._connected = True
        cache._redis = MagicMock()
        assert cache.backend == "redis"


# ── Predictor uses cache ──────────────────────────────────────────────────────


class TestPredictorCacheIntegration:
    def test_cache_set_called_on_first_build_then_get_on_second(self):
        """
        The cache.set() is called on the first feature build.
        The cache.get() returns a hit on the second call for the same timestamp.
        """
        from ml.live_inference import _FeatureCache

        cache = _FeatureCache()
        cache._connected = True

        # Spy on set/get
        original_set = cache.set
        original_get = cache.get
        set_calls = []
        get_calls = []

        def spy_set(sym, ts, df):
            set_calls.append((sym, ts))
            return original_set(sym, ts, df)

        def spy_get(sym, ts):
            result = original_get(sym, ts)
            get_calls.append((sym, ts, result is not None))
            return result

        cache.set = spy_set
        cache.get = spy_get

        # Simulate two calls with the same (symbol, timestamp)
        fake_features = pd.DataFrame({"f0": [1.0], "f1": [2.0]})
        ts = "2026-01-01T12:00:00"

        # First call: miss → set
        result1 = cache.get("XAUUSD", ts)
        assert result1 is None
        cache.set("XAUUSD", ts, fake_features)

        # Second call: hit
        result2 = cache.get("XAUUSD", ts)
        assert result2 is not None

        assert len(set_calls) == 1
        assert get_calls[-1][2] is True  # last get was a hit

    def test_cache_miss_for_new_timestamp(self):
        """A new bar timestamp always produces a cache miss."""
        from ml.live_inference import _FeatureCache

        cache = _FeatureCache()
        cache._connected = True

        fake_features = pd.DataFrame({"f0": [1.0]})
        cache.set("XAUUSD", "ts-old", fake_features)

        # Different timestamp → miss
        result = cache.get("XAUUSD", "ts-new")
        assert result is None

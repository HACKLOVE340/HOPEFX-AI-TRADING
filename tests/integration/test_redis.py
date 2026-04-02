# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
Integration tests for Redis connectivity and MarketDataCache.

These tests require a running Redis instance.  When Redis is unavailable
(CI without a Redis sidecar, local dev without Docker) every test in this
module is *skipped* automatically — they never produce a failure.

Run with a live Redis::

    pytest tests/integration/test_redis.py -v

Or start a throw-away Redis in Docker::

    docker run -d -p 6379:6379 redis:7-alpine
    pytest tests/integration/test_redis.py -v
"""

from __future__ import annotations

import time
import pytest

# ---------------------------------------------------------------------------
# Optional dependency guards
# ---------------------------------------------------------------------------
try:
    import redis as redis_lib
    from redis.exceptions import ConnectionError as RedisConnectionError

    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False
    RedisConnectionError = Exception  # type: ignore[assignment,misc]

try:
    from cache.market_data_cache import MarketDataCache

    CACHE_AVAILABLE = True
except Exception:
    CACHE_AVAILABLE = False

# ---------------------------------------------------------------------------
# Module-level skip when Redis package is not installed
# ---------------------------------------------------------------------------
if not REDIS_AVAILABLE:
    pytest.skip("redis package not installed", allow_module_level=True)


# ---------------------------------------------------------------------------
# Helper: check whether a live Redis is reachable
# ---------------------------------------------------------------------------
def _redis_reachable(host: str = "localhost", port: int = 6379) -> bool:
    """Return True if a Redis server is accepting connections."""
    try:
        r = redis_lib.Redis(host=host, port=port, socket_connect_timeout=1)
        r.ping()
        r.close()
        return True
    except Exception:
        return False


REDIS_UP = _redis_reachable()

requires_redis = pytest.mark.skipif(
    not REDIS_UP,
    reason="Redis server not reachable at localhost:6379 — skipping live integration tests",
)


# ===========================================================================
# Tests that only need the redis package (no live server)
# ===========================================================================


class TestRedisPackage:
    """Smoke tests that exercise the redis package without a live server."""

    def test_redis_importable(self) -> None:
        """Verify the redis package is importable and exposes the Redis class."""
        assert hasattr(redis_lib, "Redis")

    def test_redis_exceptions_importable(self) -> None:
        """Verify common exception types are accessible."""
        from redis.exceptions import (
            ConnectionError as RedisConnError,
            TimeoutError as RedisTimeoutError,
            AuthenticationError,
        )

        assert RedisConnError
        assert RedisTimeoutError
        assert AuthenticationError

    def test_connection_refused_raises(self) -> None:
        """Connecting to a closed port raises a Redis ConnectionError."""
        from redis.exceptions import ConnectionError as RedisConnectionError

        r = redis_lib.Redis(host="localhost", port=19999, socket_connect_timeout=0.2)
        with pytest.raises((RedisConnectionError, ConnectionError, OSError)):
            r.ping()


# ===========================================================================
# Tests that need a live Redis instance
# ===========================================================================


@requires_redis
class TestRedisLive:
    """Integration tests against a real Redis server."""

    @pytest.fixture(autouse=True)
    def _client(self) -> redis_lib.Redis:  # type: ignore[name-defined]
        """Provide a clean Redis client and flush a test namespace."""
        self.r = redis_lib.Redis(host="localhost", port=6379, decode_responses=True)
        # Remove any keys we might leave behind
        for key in self.r.scan_iter("hopefx_test:*"):
            self.r.delete(key)
        yield self.r
        # Cleanup
        for key in self.r.scan_iter("hopefx_test:*"):
            self.r.delete(key)
        self.r.close()

    def test_ping(self) -> None:
        assert self.r.ping() is True

    def test_set_and_get(self) -> None:
        self.r.set("hopefx_test:hello", "world", ex=10)
        assert self.r.get("hopefx_test:hello") == "world"

    def test_key_expiry(self) -> None:
        self.r.set("hopefx_test:expire_me", "gone", px=100)  # 100 ms TTL
        assert self.r.exists("hopefx_test:expire_me") == 1
        time.sleep(0.2)
        assert self.r.exists("hopefx_test:expire_me") == 0

    def test_delete(self) -> None:
        self.r.set("hopefx_test:del_me", "value", ex=30)
        assert self.r.get("hopefx_test:del_me") is not None
        self.r.delete("hopefx_test:del_me")
        assert self.r.get("hopefx_test:del_me") is None

    def test_incr_decr(self) -> None:
        self.r.set("hopefx_test:counter", 0, ex=30)
        self.r.incr("hopefx_test:counter", 5)
        self.r.incr("hopefx_test:counter", 3)
        self.r.decr("hopefx_test:counter", 2)
        assert int(self.r.get("hopefx_test:counter")) == 6

    def test_hash_operations(self) -> None:
        key = "hopefx_test:tick"
        self.r.hset(key, mapping={"bid": "2345.50", "ask": "2345.70", "symbol": "XAUUSD"})
        self.r.expire(key, 30)
        assert self.r.hget(key, "symbol") == "XAUUSD"
        assert float(self.r.hget(key, "bid")) == pytest.approx(2345.50)
        data = self.r.hgetall(key)
        assert set(data.keys()) == {"bid", "ask", "symbol"}

    def test_list_push_pop(self) -> None:
        key = "hopefx_test:queue"
        self.r.delete(key)
        for i in range(5):
            self.r.rpush(key, f"item_{i}")
        self.r.expire(key, 30)
        assert int(self.r.llen(key)) == 5
        first = self.r.lpop(key)
        assert first == "item_0"
        assert int(self.r.llen(key)) == 4

    def test_publish_subscribe(self) -> None:
        """Verify pub/sub round-trip."""
        import threading

        received: list[str] = []
        channel = "hopefx_test:events"

        sub_client = redis_lib.Redis(host="localhost", port=6379, decode_responses=True)
        pubsub = sub_client.pubsub()
        pubsub.subscribe(channel)

        # Consume the subscription-confirmation message
        pubsub.get_message(timeout=0.5)

        def _publisher() -> None:
            time.sleep(0.05)
            pub = redis_lib.Redis(host="localhost", port=6379, decode_responses=True)
            pub.publish(channel, "trade_signal")
            pub.close()

        t = threading.Thread(target=_publisher, daemon=True)
        t.start()
        t.join(timeout=2)

        deadline = time.time() + 1.0
        while time.time() < deadline:
            msg = pubsub.get_message(timeout=0.1)
            if msg and msg["type"] == "message":
                received.append(msg["data"])
                break

        pubsub.unsubscribe(channel)
        sub_client.close()

        assert received == ["trade_signal"]


# ===========================================================================
# MarketDataCache integration tests (need live Redis + cache module)
# ===========================================================================


@requires_redis
@pytest.mark.skipif(not CACHE_AVAILABLE, reason="MarketDataCache not importable")
class TestMarketDataCacheLive:
    """Test MarketDataCache against a real Redis instance."""

    @pytest.fixture(autouse=True)
    def _cache(self) -> MarketDataCache:
        self.cache = MarketDataCache(
            host="localhost",
            port=6379,
            max_retries=2,
            retry_delay=0.1,
        )
        yield self.cache
        # Cleanup keys we might have written
        try:
            r = redis_lib.Redis(host="localhost", port=6379)
            for key in r.scan_iter(b"hopefx:*"):
                r.delete(key)
            r.close()
        except Exception:
            pass

    def test_cache_initialises(self) -> None:
        assert self.cache is not None

    def test_cache_and_retrieve_ohlcv(self) -> None:
        """Store and retrieve a single OHLCV record."""
        sample = {
            "timestamp": time.time(),
            "open": 2345.0,
            "high": 2350.0,
            "low": 2340.0,
            "close": 2347.5,
            "volume": 1500,
        }
        self.cache.cache_ohlcv("XAUUSD", "1h", [sample], ttl=60)
        result = self.cache.get_ohlcv("XAUUSD", "1h", limit=1)
        assert len(result) >= 1
        assert result[-1]["close"] == pytest.approx(2347.5)

    def test_cache_tick(self) -> None:
        """Store and retrieve a tick."""
        tick = {
            "symbol": "XAUUSD",
            "bid": 2345.50,
            "ask": 2345.70,
            "timestamp": time.time(),
        }
        self.cache.cache_tick("XAUUSD", tick, ttl=30)
        result = self.cache.get_latest_tick("XAUUSD")
        assert result is not None
        assert result.get("bid") == pytest.approx(2345.50)

    def test_stats_accessible(self) -> None:
        stats = self.cache.get_stats()
        assert isinstance(stats, dict)

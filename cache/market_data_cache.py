# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
# pylint: disable=broad-exception-caught,logging-fstring-interpolation
"""
Market Data Cache Module - PRODUCTION VERSION
Fixed: Thread safety, proper Redis connection management, circuit breaker
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import threading
import time
import urllib.parse
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone

UTC = timezone.utc
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)

try:
    import redis
    from redis import Redis
    from redis.exceptions import TimeoutError as RedisTimeoutError

    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False
    Redis = None  # type: ignore[assignment,misc]
    RedisTimeoutError = Exception  # type: ignore[assignment,misc]
    # Log at DEBUG — the in-memory fallback handles this transparently.
    logger.debug("redis package not installed — MarketDataCache will use in-memory fallback")


def _parse_redis_url(url: str) -> dict[str, Any]:
    """Parse a redis[s]://[:password@]host[:port][/db] URL into kwargs for redis.Redis."""
    parsed = urllib.parse.urlparse(url)
    kwargs: dict[str, Any] = {
        "host": parsed.hostname or "localhost",
        "port": parsed.port or 6379,
        "db": int(parsed.path.lstrip("/") or "0"),
        "password": parsed.password or None,
    }
    return kwargs


class Timeframe(Enum):
    """Supported timeframes"""

    ONE_MINUTE = "1m"
    FIVE_MINUTES = "5m"
    FIFTEEN_MINUTES = "15m"
    THIRTY_MINUTES = "30m"
    ONE_HOUR = "1h"
    FOUR_HOURS = "4h"
    ONE_DAY = "1d"
    ONE_WEEK = "1w"
    ONE_MONTH = "1M"


@dataclass
class OHLCVData:
    """OHLCV data structure"""

    timestamp: int
    open_price: float
    high_price: float
    low_price: float
    close_price: float
    volume: float

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> OHLCVData:
        return cls(**data)


@dataclass
class TickData:
    """Tick data structure"""

    timestamp: int
    price: float
    volume: float
    bid: float
    ask: float
    bid_volume: float
    ask_volume: float

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> TickData:
        return cls(**data)


@dataclass
class CacheStatistics:
    """Cache statistics"""

    total_hits: int = 0
    total_misses: int = 0
    total_evictions: int = 0
    total_keys: int = 0
    memory_usage_bytes: int = 0
    last_update: float = 0

    @property
    def hit_rate(self) -> float:
        total = self.total_hits + self.total_misses
        return (self.total_hits / total) * 100 if total > 0 else 0.0

    def to_dict(self) -> dict:
        return {
            "total_hits": self.total_hits,
            "total_misses": self.total_misses,
            "total_evictions": self.total_evictions,
            "total_keys": self.total_keys,
            "memory_usage_bytes": self.memory_usage_bytes,
            "memory_usage_mb": self.memory_usage_bytes / 1024 / 1024,
            "hit_rate_percent": round(self.hit_rate, 2),
            "last_update": self.last_update,
        }


class _InMemoryStore:
    """
    Minimal Redis-compatible in-memory store used as a fallback when Redis
    is unavailable.  Only the subset of commands used by MarketDataCache is
    implemented.
    """

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}
        self._expiry: dict[str, float] = {}
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _is_expired(self, key: str) -> bool:
        exp = self._expiry.get(key)
        if exp is None:
            return False
        return time.time() > exp

    def _clean(self, key: str) -> None:
        if self._is_expired(key):
            self._data.pop(key, None)
            self._expiry.pop(key, None)

    # ------------------------------------------------------------------
    # Redis-compatible API subset
    # ------------------------------------------------------------------

    def ping(self) -> bool:
        return True

    def setex(self, name: str, time_secs: int, value: str) -> bool:
        with self._lock:
            self._data[name] = value
            self._expiry[name] = time.time() + time_secs
        return True

    def get(self, name: str) -> str | None:
        with self._lock:
            self._clean(name)
            return self._data.get(name)

    def delete(self, *names: str) -> int:
        removed = 0
        with self._lock:
            for name in names:
                if name in self._data:
                    del self._data[name]
                    self._expiry.pop(name, None)
                    removed += 1
        return removed

    def scan(
        self,
        cursor: int = 0,  # pylint: disable=unused-argument
        match: str | None = None,
        count: int = 100,  # pylint: disable=unused-argument
    ) -> tuple[int, list[str]]:
        """Single-pass SCAN (always returns cursor=0, all matching keys). cursor/count unused in memory impl."""
        import fnmatch

        with self._lock:
            all_keys = [k for k in self._data if not self._is_expired(k)]

            if match:
                pattern = match.replace("*", "**")
                all_keys = [k for k in all_keys if fnmatch.fnmatch(k, pattern)]

            return 0, all_keys

    def info(self, section: str = "all") -> dict[str, Any]:  # pylint: disable=unused-argument
        with self._lock:
            return {"used_memory": sum(len(v) for v in self._data.values() if isinstance(v, str | bytes))}

    def close(self) -> None:
        """Release all in-memory data and expiry metadata."""
        with self._lock:
            self._data.clear()
            self._expiry.clear()


class MarketDataCache:
    """
    Redis-based cache with thread safety and circuit breaker

    Fixes applied:
    - Thread-safe statistics (threading.Lock)
    - Async support for health checks
    - Connection retry with exponential backoff
    - Graceful fallback to in-memory if Redis fails
    """

    # Default TTL values (seconds)
    DEFAULT_TTL = {
        Timeframe.ONE_MINUTE: 3600,  # 1 hour
        Timeframe.FIVE_MINUTES: 7200,  # 2 hours
        Timeframe.FIFTEEN_MINUTES: 14400,  # 4 hours
        Timeframe.THIRTY_MINUTES: 28800,  # 8 hours
        Timeframe.ONE_HOUR: 86400,  # 1 day
        Timeframe.FOUR_HOURS: 172800,  # 2 days
        Timeframe.ONE_DAY: 604800,  # 1 week
        Timeframe.ONE_WEEK: 1209600,  # 2 weeks
        Timeframe.ONE_MONTH: 2592000,  # 30 days
    }

    def __init__(
        self,
        host: str | None = None,
        port: int | None = None,
        db: int = 0,
        password: str | None = None,
        socket_timeout: float = 1,
        socket_connect_timeout: float = 1,
        decode_responses: bool = True,
        max_retries: int = 1,
        retry_delay: float = 0.5,
        enable_fallback: bool = True,
    ):
        # Resolve connection parameters: explicit args > REDIS_URL env > defaults.
        # This ensures the cache honours the same REDIS_URL used by the rest of
        # the system rather than always connecting to localhost:6379.
        _url = os.environ.get("REDIS_URL", "").strip()
        if _url and (host is None or host == "localhost"):
            _parsed = _parse_redis_url(_url)
            host = host if host not in (None, "localhost") else _parsed["host"]
            port = port if port is not None else _parsed["port"]
            db = db if db != 0 else _parsed["db"]
            password = password if password is not None else _parsed["password"]

        self.host = host or "localhost"
        self.port = port or 6379
        self.db = db
        self.password = password or os.environ.get("REDIS_PASSWORD") or None
        self.socket_timeout = socket_timeout
        self.socket_connect_timeout = socket_connect_timeout
        self.decode_responses = decode_responses
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self.enable_fallback = enable_fallback

        # Thread safety
        self._stats_lock = threading.Lock()

        # Statistics
        self._stats = CacheStatistics()

        # In-memory fallback store (Redis-compatible API subset)
        self._fallback_store: _InMemoryStore = _InMemoryStore()
        self._using_fallback = False

        # Suppress repeated "connection failed" / "using fallback" log noise.
        # After the first warning we downgrade subsequent identical messages to DEBUG.
        self._fallback_warned: bool = False

        # Redis client (initialized on first use)
        self._redis_client: Redis | None = None
        self._connection_failed = False

        # Attempt connection at init time (tests patch this method)
        self._redis_client = self._connect_with_retry()

        logger.info("MarketDataCache initialized (Redis: %s:%s)", self.host, self.port)

    def _connect_with_retry(self) -> Redis | None:
        """Attempt Redis connection with retries; return client or None on failure."""
        if not REDIS_AVAILABLE:
            self._connection_failed = True
            self._using_fallback = True
            return None

        for attempt in range(self.max_retries):
            try:
                client = redis.Redis(
                    host=self.host,
                    port=self.port,
                    db=self.db,
                    password=self.password,
                    socket_timeout=self.socket_timeout,
                    socket_connect_timeout=self.socket_connect_timeout,
                    decode_responses=self.decode_responses,
                    retry_on_error=[],
                    retry=None,
                )
                client.ping()
                self._connection_failed = False
                self._using_fallback = False
                self._fallback_warned = False
                if attempt > 0:
                    logger.info("MarketDataCache: Redis connected after %s retries", attempt)
                return client
            except Exception as exc:
                # Log first failure as WARNING; subsequent ones as DEBUG to avoid log spam.
                if not self._fallback_warned:
                    logger.warning(
                        "MarketDataCache: Redis connection attempt %d failed: %s",
                        attempt + 1,
                        exc,
                    )
                else:
                    logger.debug(
                        "MarketDataCache: Redis connection attempt %d failed (suppressed): %s",
                        attempt + 1,
                        exc,
                    )
                if attempt < self.max_retries - 1:
                    time.sleep(self.retry_delay * (2**attempt))

        self._connection_failed = True
        self._using_fallback = True
        if self.enable_fallback:
            if not self._fallback_warned:
                logger.warning("MarketDataCache: Redis unavailable — using in-memory fallback")
                self._fallback_warned = True
            else:
                logger.debug("MarketDataCache: still using in-memory fallback (suppressed repeat)")
            return None
        raise ConnectionError(f"Could not connect to Redis at {self.host}:{self.port}")

    def _get_redis(self) -> Redis | None:
        """
        Return a live Redis client, or None when Redis is unavailable.

        Priority:
          1. Circuit breaker OPEN → return None immediately (no hammering)
          2. Existing client alive → return it
          3. Reconnect attempt → return new client or None on failure

        All failures are routed to _fallback_store transparently.
        Repeated "connection failed" messages are suppressed after the first.
        """
        if not REDIS_AVAILABLE:
            self._using_fallback = True
            return None

        # Fast-fail when the circuit breaker is open
        try:
            from resilience.service_circuit_breakers import redis_breaker as _rb

            if _rb.is_open:
                self._using_fallback = True
                logger.debug(
                    "MarketDataCache: Redis circuit breaker OPEN — using in-memory fallback."
                )
                return None
        except Exception:  # nosec B110 — circuit breaker is non-fatal
            pass

        if self._connection_failed and not self.enable_fallback:
            return None

        if self._redis_client is not None:
            try:
                self._redis_client.ping()
                self._using_fallback = False
                self._fallback_warned = False
                try:
                    from resilience.service_circuit_breakers import redis_breaker as _rb
                    _rb.record_success()
                except Exception:  # nosec B110
                    pass
                return self._redis_client
            except Exception as _exc:
                logger.debug("MarketDataCache: Redis ping failed, will reconnect: %s", _exc)
                self._redis_client = None
                try:
                    from resilience.service_circuit_breakers import redis_breaker as _rb
                    _rb.record_failure(_exc)
                except Exception:  # nosec B110
                    pass

        # Reconnect attempt
        for attempt in range(self.max_retries):
            try:
                client = redis.Redis(
                    host=self.host,
                    port=self.port,
                    db=self.db,
                    password=self.password,
                    socket_timeout=self.socket_timeout,
                    socket_connect_timeout=self.socket_connect_timeout,
                    decode_responses=self.decode_responses,
                    retry_on_error=[],
                    retry=None,
                )
                client.ping()
                self._redis_client = client
                self._connection_failed = False
                self._using_fallback = False
                self._fallback_warned = False
                if attempt > 0:
                    logger.info("MarketDataCache: Redis reconnected after %d attempts", attempt)
                try:
                    from resilience.service_circuit_breakers import redis_breaker as _rb
                    _rb.record_success()
                except Exception:  # nosec B110
                    pass
                return client
            except Exception as exc:
                try:
                    from resilience.service_circuit_breakers import redis_breaker as _rb
                    _rb.record_failure(exc)
                except Exception:  # nosec B110
                    pass
                if attempt < self.max_retries - 1:
                    time.sleep(self.retry_delay * (2**attempt))

        # All retries failed — activate fallback
        self._connection_failed = True
        self._using_fallback = True
        if self.enable_fallback:
            if not self._fallback_warned:
                logger.warning(
                    "MarketDataCache: Redis unavailable — using in-memory fallback"
                )
                self._fallback_warned = True
            else:
                logger.debug(
                    "MarketDataCache: still using in-memory fallback (suppressed repeat)"
                )
            return None
        raise ConnectionError(f"Could not connect to Redis at {self.host}:{self.port}")

    def _resolve_timeframe(self, timeframe) -> str:
        """Resolve timeframe to its string value, accepting Timeframe enum or raw string."""
        if isinstance(timeframe, Timeframe):
            return timeframe.value
        # Accept plain strings like "1h", "4h", etc.
        return str(timeframe)

    def _build_key(self, symbol: str, timeframe, data_type: str) -> str:
        """Build cache key"""
        tf_str = self._resolve_timeframe(timeframe)
        return f"market_data:{symbol}:{tf_str}:{data_type}"

    def _build_tick_key(self, symbol: str) -> str:
        """Build tick data cache key"""
        return f"tick_data:{symbol}"

    def _is_local_key_valid(self, key: str) -> bool:
        """Check if a key exists and is not expired in the fallback store."""
        return self._fallback_store.get(key) is not None

    # OHLCV Operations

    def cache_ohlcv(
        self,
        symbol: str,
        timeframe,  # Timeframe enum or plain string e.g. "1h"
        ohlcv_data: list,
        ttl: int | None = None,
    ) -> bool:
        """Cache OHLCV data. Accepts Timeframe enum or plain string timeframe."""
        try:
            key = self._build_key(symbol, timeframe, "ohlcv")
            tf_key = self._resolve_timeframe(timeframe)
            # Resolve TTL: try enum lookup first, then string lookup, then default
            if ttl is None:
                try:
                    tf_enum = Timeframe(tf_key)
                    ttl = self.DEFAULT_TTL.get(tf_enum, 3600)
                except ValueError:
                    ttl = 3600

            # Serialize data — accept OHLCVData objects or plain dicts
            data_list = []
            for candle in ohlcv_data:
                if isinstance(candle, dict):
                    data_list.append(candle)
                elif hasattr(candle, "to_dict"):
                    data_list.append(candle.to_dict())
                else:
                    data_list.append(dict(candle))

            cached_data = {
                "data": data_list,
                "cached_at": datetime.now(UTC).isoformat(),
                "expiry": (datetime.now(UTC) + timedelta(seconds=ttl)).isoformat(),
            }

            # Try Redis first; fall back to _InMemoryStore on failure.
            redis_client = self._get_redis()
            serialized = json.dumps(cached_data)
            if redis_client:
                redis_client.setex(key, ttl, serialized)
            else:
                self._fallback_store.setex(key, ttl, serialized)

            logger.debug("Cached OHLCV for %s (%s): %s candles", symbol, tf_key, len(ohlcv_data))

            return True

        except Exception as e:
            logger.error("Error caching OHLCV: %s", e)

            return False

    def get_ohlcv(self, symbol: str, timeframe, limit: int | None = None) -> list | None:
        """Retrieve OHLCV data from cache.

        Args:
            symbol: Instrument symbol.
            timeframe: Timeframe enum or plain string (e.g. "1h").
            limit: If set, return only the last *limit* candles.

        Returns:
            List of candle dicts (or OHLCVData objects if stored as such), or None on miss.
        """
        try:
            key = self._build_key(symbol, timeframe, "ohlcv")

            # Try Redis first
            redis_client = self._get_redis()
            cached = None

            if redis_client:
                cached = redis_client.get(key)
            else:
                cached = self._fallback_store.get(key)

            # Update statistics
            with self._stats_lock:
                if cached:
                    self._stats.total_hits += 1
                else:
                    self._stats.total_misses += 1

            if cached:
                data = json.loads(cached)
                raw = data.get("data", [])
                # Return plain dicts so callers that stored dicts get dicts back;
                # attempt OHLCVData deserialization only when the dict has the
                # expected typed fields.
                try:
                    result = [OHLCVData.from_dict(item) for item in raw]
                except Exception:
                    result = raw  # fall back to plain dicts

                if limit is not None:
                    result = result[-limit:]
                return result

            return None

        except Exception as e:
            logger.error("Error retrieving OHLCV: %s", e)

            with self._stats_lock:
                self._stats.total_misses += 1
            return None

    # Tick Data Operations

    def cache_tick(self, symbol: str, tick_data, ttl: int = 300) -> bool:
        """Cache tick data. Accepts TickData object or plain dict."""
        try:
            key = self._build_tick_key(symbol)

            if isinstance(tick_data, dict):
                tick_dict = tick_data
            elif hasattr(tick_data, "to_dict"):
                tick_dict = tick_data.to_dict()
            else:
                tick_dict = dict(tick_data)

            cached_data = {
                "data": tick_dict,
                "cached_at": datetime.now(UTC).isoformat(),
            }

            redis_client = self._get_redis()
            serialized = json.dumps(cached_data)
            if redis_client:
                redis_client.setex(key, ttl, serialized)
            else:
                self._fallback_store.setex(key, ttl, serialized)

            logger.debug("Cached tick for %s", symbol)

            return True

        except Exception as e:
            logger.error("Error caching tick: %s", e)

            return False

    def get_tick(self, symbol: str):
        """Retrieve latest tick data. Returns TickData if possible, else plain dict."""
        try:
            key = self._build_tick_key(symbol)

            redis_client = self._get_redis()
            cached = None

            if redis_client:
                cached = redis_client.get(key)
            else:
                cached = self._fallback_store.get(key)

            with self._stats_lock:
                if cached:
                    self._stats.total_hits += 1
                else:
                    self._stats.total_misses += 1

            if cached:
                data = json.loads(cached)
                raw = data["data"]
                try:
                    return TickData.from_dict(raw)
                except Exception:
                    return raw  # plain dict fallback

            return None

        except Exception as e:
            logger.error("Error retrieving tick: %s", e)

            return None

    # Alias used by tests and external callers
    def get_latest_tick(self, symbol: str):
        """Alias for get_tick — returns the most recently cached tick."""
        return self.get_tick(symbol)

    # Cache Management

    def invalidate_symbol(self, symbol: str) -> bool:
        """Invalidate all cache for a symbol"""
        try:
            pattern = f"market_data:{symbol}:*"

            redis_client = self._get_redis()
            if redis_client:
                # Use SCAN for non-blocking iteration
                cursor = 0
                keys_to_delete = []

                while True:
                    cursor, keys = redis_client.scan(cursor=cursor, match=pattern, count=100)
                    keys_to_delete.extend(keys)
                    if cursor == 0:
                        break

                if keys_to_delete:
                    redis_client.delete(*keys_to_delete)

                # Also delete tick data
                tick_key = self._build_tick_key(symbol)
                redis_client.delete(tick_key)
            else:
                # Fallback store cleanup via SCAN
                _, keys_to_remove = self._fallback_store.scan(
                    match=f"market_data:{symbol}:*"
                )
                tick_key = self._build_tick_key(symbol)
                if self._fallback_store.get(tick_key) is not None:
                    keys_to_remove.append(tick_key)
                if keys_to_remove:
                    self._fallback_store.delete(*keys_to_remove)

            with self._stats_lock:
                self._stats.total_evictions += 1

            logger.debug("Invalidated cache for %s", symbol)

            return True

        except Exception as e:
            logger.error("Error invalidating symbol: %s", e)

            return False

    def clear_all(self) -> bool:
        """Clear all market data cache"""
        try:
            redis_client = self._get_redis()

            if redis_client:
                # Scan and delete in batches
                all_keys = []

                for pattern in ["market_data:*", "tick_data:*"]:
                    cursor = 0
                    while True:
                        cursor, keys = redis_client.scan(cursor=cursor, match=pattern, count=100)
                        all_keys.extend(keys)
                        if cursor == 0:
                            break

                # Delete in batches
                batch_size = 1000
                for i in range(0, len(all_keys), batch_size):
                    batch = all_keys[i : i + batch_size]
                    redis_client.delete(*batch)
            else:
                # Clear fallback store
                _, fb_keys = self._fallback_store.scan(match="market_data:*")
                _, tick_keys = self._fallback_store.scan(match="tick_data:*")
                all_fb_keys = fb_keys + tick_keys
                if all_fb_keys:
                    self._fallback_store.delete(*all_fb_keys)
                all_keys = all_fb_keys  # for eviction count below

            with self._stats_lock:
                self._stats.total_evictions += len(all_keys)

            logger.info("Cleared all cache")
            return True

        except Exception as e:
            logger.error("Error clearing cache: %s", e)

            return False

    # Statistics

    @property
    def stats(self) -> CacheStatistics:
        """Public accessor for cache statistics (mutable)."""
        return self._stats

    @stats.setter
    def stats(self, value: CacheStatistics) -> None:
        self._stats = value

    def get_stats(self) -> dict:
        """Return cache statistics as a plain dict."""
        with self._stats_lock:
            s = self._stats
            return {
                "total_hits": s.total_hits,
                "total_misses": s.total_misses,
                "total_evictions": s.total_evictions,
                "hit_rate": (
                    s.total_hits / (s.total_hits + s.total_misses) if (s.total_hits + s.total_misses) > 0 else 0.0
                ),
            }

    # ------------------------------------------------------------------
    # Batch / multi-timeframe helpers expected by tests
    # ------------------------------------------------------------------

    def cache_ticks(self, symbol: str, ticks: list, ttl: int = 3600, max_size: int = 1000) -> bool:
        """Cache a list of TickData objects using {"data": [...], "count": N} envelope."""
        try:
            data = [t.to_dict() if hasattr(t, "to_dict") else t for t in ticks]
            if len(data) > max_size:
                data = data[-max_size:]
            envelope = {
                "data": data,
                "cached_at": datetime.now(UTC).isoformat(),
                "count": len(data),
            }
            key = self._build_tick_key(symbol)
            serialized = json.dumps(envelope)
            redis_client = self._get_redis()
            if redis_client:
                redis_client.setex(key, ttl, serialized)
            else:
                self._fallback_store.setex(key, ttl, serialized)
            return True
        except Exception as e:
            logger.error("cache_ticks error: %s", e)

            return False

    def get_ticks(self, symbol: str) -> list | None:
        """Retrieve cached tick list; returns list of TickData or None."""
        key = self._build_tick_key(symbol)
        try:
            redis_client = self._get_redis()
            raw = None
            if redis_client:
                raw = redis_client.get(key)
            else:
                raw = self._fallback_store.get(key)
            if raw is None:
                with self._stats_lock:
                    self._stats.total_misses += 1
                return None
            with self._stats_lock:
                self._stats.total_hits += 1
            envelope = json.loads(raw)
            items = envelope.get("data", envelope) if isinstance(envelope, dict) else envelope
            return [TickData.from_dict(d) if isinstance(d, dict) else d for d in items]
        except Exception as e:
            logger.error("get_ticks error: %s", e)

            return None

    def append_ohlcv(
        self,
        symbol: str,
        timeframe: Timeframe,
        candle: OHLCVData,
        ttl: int | None = None,
        max_size: int = 1000,
    ) -> bool:
        """Append a single candle to an existing OHLCV list in cache."""
        key = self._build_key(symbol, timeframe, "ohlcv")
        if ttl is None:
            ttl = self.DEFAULT_TTL.get(timeframe, 86400)
        try:
            redis_client = self._get_redis()
            raw = None
            if redis_client:
                raw = redis_client.get(key)
            else:
                raw = self._fallback_store.get(key)
            if raw:
                envelope = json.loads(raw)
                existing = envelope.get("data", []) if isinstance(envelope, dict) else envelope
            else:
                existing = []
            existing.append(candle.to_dict() if hasattr(candle, "to_dict") else candle)
            if len(existing) > max_size:
                existing = existing[-max_size:]
            new_envelope = {
                "data": existing,
                "cached_at": datetime.now(UTC).isoformat(),
            }
            serialized = json.dumps(new_envelope)
            if redis_client:
                redis_client.setex(key, ttl, serialized)
            else:
                self._fallback_store.setex(key, ttl, serialized)
            return True
        except Exception as e:
            logger.error("append_ohlcv error: %s", e)

            return False

    def cache_multi_timeframe(self, symbol: str, data: dict, ttl=None) -> bool:
        """Cache OHLCV data for multiple timeframes.

        ttl can be an int (applied to all) or a dict mapping Timeframe -> int.
        """
        success = True
        for tf, candles in data.items():
            tf_ttl = ttl.get(tf) if isinstance(ttl, dict) else ttl
            if not self.cache_ohlcv(symbol, tf, candles, ttl=tf_ttl):
                success = False
        return success

    def get_multi_timeframe(self, symbol: str, timeframes: list) -> dict:
        """Retrieve OHLCV data for multiple timeframes."""
        return {tf: self.get_ohlcv(symbol, tf) for tf in timeframes}

    def invalidate_ohlcv(self, symbol: str, timeframe: Timeframe) -> bool:
        """Invalidate OHLCV cache for a specific symbol/timeframe."""
        key = self._build_key(symbol, timeframe, "ohlcv")
        try:
            redis_client = self._get_redis()
            deleted = False
            if redis_client:
                deleted = bool(redis_client.delete(key))
            else:
                deleted = bool(self._fallback_store.delete(key))
            if deleted:
                with self._stats_lock:
                    self._stats.total_evictions += 1
            return deleted
        except Exception as e:
            logger.error("invalidate_ohlcv error: %s", e)

            return False

    def invalidate_tick(self, symbol: str) -> bool:
        """Invalidate tick cache for a symbol."""
        key = self._build_tick_key(symbol)
        try:
            redis_client = self._get_redis()
            deleted = False
            if redis_client:
                deleted = bool(redis_client.delete(key))
            else:
                deleted = bool(self._fallback_store.delete(key))
            if deleted:
                with self._stats_lock:
                    self._stats.total_evictions += 1
            return deleted
        except Exception as e:
            logger.error("invalidate_tick error: %s", e)

            return False

    def get_statistics(self) -> CacheStatistics:
        """Get cache statistics.

        Redis I/O (INFO, SCAN) is performed *outside* the stats lock so that
        holding the lock never blocks on network I/O.  This prevents the event
        loop from freezing when this method is called from an async context.
        """
        try:
            redis_client = self._get_redis()

            # ── Collect Redis metrics outside the lock ────────────────────────
            memory_bytes = 0
            key_count = 0
            if redis_client:
                try:
                    info = redis_client.info("memory")
                    memory_bytes = int(info.get("used_memory", 0))
                    for pattern in ("market_data:*", "tick_data:*"):
                        cursor = 0
                        while True:
                            cursor, keys = redis_client.scan(cursor=cursor, match=pattern, count=100)
                            key_count += len(keys)
                            if cursor == 0:
                                break
                except Exception as e:
                    logger.error("Error getting Redis stats: %s", e)
            else:
                _, fb_keys = self._fallback_store.scan(match="*")
                key_count = len(fb_keys)
                fb_info = self._fallback_store.info()
                memory_bytes = fb_info.get("used_memory", 0)

            # ── Snapshot counters under the lock (no I/O here) ───────────────
            with self._stats_lock:
                stats = CacheStatistics(
                    total_hits=self._stats.total_hits,
                    total_misses=self._stats.total_misses,
                    total_evictions=self._stats.total_evictions,
                    total_keys=key_count,
                    memory_usage_bytes=memory_bytes,
                    last_update=time.time(),
                )
            return stats

        except Exception as e:
            logger.error("Error getting statistics: %s", e)
            return CacheStatistics()

    async def get_statistics_async(self) -> CacheStatistics:
        """Async-safe version of get_statistics.

        Runs the sync method in the thread-pool executor so Redis I/O never
        blocks the event loop.
        """
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self.get_statistics)

    def print_statistics(self) -> None:
        """Print cache statistics"""
        stats = self.get_statistics()
        logger.info("Cache Statistics:")
        for key, value in stats.to_dict().items():
            logger.info("  %s: %s", key, value)

    def reset_statistics(self) -> None:
        """Reset cache statistics"""
        with self._stats_lock:
            self._stats = CacheStatistics()
        logger.info("Cache statistics reset")

    # Connection Management

    def health_check(self) -> bool:
        """Check cache health. Returns True when Redis is reachable or in-memory fallback is active."""
        try:
            if self._redis_client:
                result = self._redis_client.ping()
                return bool(result)
            redis_client = self._get_redis()
            if redis_client:
                return bool(redis_client.ping())
            # No Redis — healthy only if fallback is enabled and active
            return self.enable_fallback and self._using_fallback
        except Exception as e:
            logger.error("Health check failed: %s", e)

            return self.enable_fallback and self._using_fallback

    async def health_check_async(self) -> bool:
        """Async version of health check"""
        # Run sync health check in thread pool
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self.health_check)

    def close(self) -> None:
        """Close Redis connection"""
        try:
            if self._redis_client:
                self._redis_client.close()
                logger.info("Redis connection closed")
        except Exception as e:
            logger.error("Error closing Redis: %s", e)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()


# Alias expected by tests
CachedTickData = TickData


# ── Write-through / read-through cache layer ──────────────────────────────────

class WriteThroughCache:
    """
    Write-through / read-through cache layer over MarketDataCache.

    Every write goes to both the cache and the backing store simultaneously.
    Reads are served from cache; on a miss the backing store is queried and
    the result is populated into the cache.

    The backing store must implement:
        get_tick(symbol: str) -> Any | None
        store_tick(symbol: str, value: Any) -> None
        get_ohlcv(symbol: str, timeframe: str, limit: int) -> list | None
        store_ohlcv(symbol: str, timeframe: str, data: list) -> None

    Usage::

        store = MyDatabaseStore()
        wt = WriteThroughCache(market_data_cache, store)

        # Write-through tick
        wt.set_tick("XAU_USD", tick_data)

        # Read-through tick (cache → store on miss)
        tick = wt.get_tick("XAU_USD")
    """

    def __init__(
        self,
        cache: MarketDataCache,
        backing_store: Any,
        default_ttl_s: int = 300,
    ) -> None:
        self._cache = cache
        self._store = backing_store
        self._default_ttl_s = default_ttl_s
        self._hits = 0
        self._misses = 0
        self._writes = 0
        self._lock = threading.Lock()

    # ── Tick ──────────────────────────────────────────────────────────────────

    def get_tick(self, symbol: str) -> Any | None:
        """Read-through: cache → backing store on miss."""
        cached = self._cache.get_tick(symbol)
        if cached is not None:
            with self._lock:
                self._hits += 1
            return cached
        with self._lock:
            self._misses += 1
        value = None
        try:
            value = self._store.get_tick(symbol)
        except Exception as exc:
            logger.warning("WriteThroughCache store.get_tick failed for %r: %s", symbol, exc)
        if value is not None:
            try:
                self._cache.cache_tick(symbol, value, ttl=self._default_ttl_s)
            except Exception as exc:
                logger.debug("WriteThroughCache populate tick failed for %r: %s", symbol, exc)
        return value

    def set_tick(self, symbol: str, value: Any, ttl_s: int | None = None) -> None:
        """Write-through: write tick to cache and backing store."""
        ttl = ttl_s or self._default_ttl_s
        try:
            self._cache.cache_tick(symbol, value, ttl=ttl)
        except Exception as exc:
            logger.warning("WriteThroughCache cache_tick failed for %r: %s", symbol, exc)
        try:
            self._store.store_tick(symbol, value)
        except Exception as exc:
            logger.warning("WriteThroughCache store_tick failed for %r: %s", symbol, exc)
        with self._lock:
            self._writes += 1

    # ── OHLCV ─────────────────────────────────────────────────────────────────

    def get_ohlcv(self, symbol: str, timeframe: str, limit: int = 200) -> list | None:
        """Read-through OHLCV: cache → backing store on miss."""
        cached = self._cache.get_ohlcv(symbol, timeframe, limit=limit)
        if cached is not None:
            with self._lock:
                self._hits += 1
            return cached
        with self._lock:
            self._misses += 1
        data = None
        try:
            data = self._store.get_ohlcv(symbol, timeframe, limit)
        except Exception as exc:
            logger.warning("WriteThroughCache store.get_ohlcv failed for %r/%s: %s", symbol, timeframe, exc)
        if data is not None:
            try:
                self._cache.cache_ohlcv(symbol, timeframe, data)
            except Exception as exc:
                logger.debug("WriteThroughCache populate ohlcv failed: %s", exc)
        return data

    def set_ohlcv(self, symbol: str, timeframe: str, data: list) -> None:
        """Write-through OHLCV: write to cache and backing store."""
        try:
            self._cache.cache_ohlcv(symbol, timeframe, data)
        except Exception as exc:
            logger.warning("WriteThroughCache cache_ohlcv failed: %s", exc)
        try:
            self._store.store_ohlcv(symbol, timeframe, data)
        except Exception as exc:
            logger.warning("WriteThroughCache store_ohlcv failed: %s", exc)
        with self._lock:
            self._writes += 1

    def stats(self) -> dict:
        with self._lock:
            total = self._hits + self._misses
            return {
                "hits": self._hits,
                "misses": self._misses,
                "writes": self._writes,
                "hit_rate_pct": round(self._hits / max(total, 1) * 100, 2),
            }


# ── Cache warming ─────────────────────────────────────────────────────────────

class CacheWarmer:
    """
    Pre-populates the cache with data from a backing store on startup.

    Warming strategies:
    - ``warm_symbols``: fetch latest tick for each symbol and cache it
    - ``warm_ohlcv``: fetch recent OHLCV bars for each symbol/timeframe pair
    - ``schedule_refresh``: background thread that re-warms at a fixed interval

    Usage::

        warmer = CacheWarmer(cache, data_source)
        warmer.warm_symbols(["XAU_USD", "EUR_USD"])
        warmer.warm_ohlcv(["XAU_USD"], [Timeframe.ONE_MINUTE, Timeframe.ONE_HOUR])
        warmer.schedule_refresh(interval_s=300)
    """

    def __init__(self, cache: MarketDataCache, data_source: Any) -> None:
        self._cache = cache
        self._source = data_source
        self._refresh_thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._warm_count = 0
        self._last_warm_at: float | None = None

    def warm_symbols(self, symbols: list[str]) -> int:
        """
        Fetch and cache the latest tick for each symbol.

        The data source must implement ``get_latest_tick(symbol) -> Any | None``.
        Returns the number of symbols successfully warmed.
        """
        warmed = 0
        for symbol in symbols:
            try:
                tick = self._source.get_latest_tick(symbol)
                if tick is not None:
                    self._cache.cache_tick(symbol, tick)
                    warmed += 1
                    logger.debug("CacheWarmer: warmed tick for %s", symbol)
            except Exception as exc:
                logger.warning("CacheWarmer.warm_symbols failed for %s: %s", symbol, exc)
        self._warm_count += warmed
        self._last_warm_at = time.time()
        logger.info("CacheWarmer: warmed %d/%d symbols", warmed, len(symbols))
        return warmed

    def warm_ohlcv(
        self,
        symbols: list[str],
        timeframes: list[Timeframe],
        bars: int = 200,
    ) -> int:
        """
        Fetch and cache recent OHLCV bars for each symbol/timeframe pair.

        The data source must implement
        ``get_ohlcv(symbol, timeframe_str, limit) -> list | None``.
        Returns the number of (symbol, timeframe) pairs successfully warmed.
        """
        warmed = 0
        for symbol in symbols:
            for tf in timeframes:
                tf_str = tf.value if isinstance(tf, Timeframe) else str(tf)
                try:
                    data = self._source.get_ohlcv(symbol, tf_str, bars)
                    if data is not None and len(data) > 0:
                        self._cache.cache_ohlcv(symbol, tf_str, data)
                        warmed += 1
                        logger.debug(
                            "CacheWarmer: warmed OHLCV %s/%s (%d bars)",
                            symbol,
                            tf_str,
                            len(data),
                        )
                except Exception as exc:
                    logger.warning(
                        "CacheWarmer.warm_ohlcv failed for %s/%s: %s",
                        symbol,
                        tf_str,
                        exc,
                    )
        self._warm_count += warmed
        self._last_warm_at = time.time()
        logger.info(
            "CacheWarmer: warmed %d/%d symbol/timeframe pairs",
            warmed,
            len(symbols) * len(timeframes),
        )
        return warmed

    def schedule_refresh(
        self,
        symbols: list[str],
        timeframes: list[Timeframe] | None = None,
        interval_s: float = 300.0,
    ) -> None:
        """
        Start a background thread that re-warms the cache every ``interval_s`` seconds.

        Stops when ``stop()`` is called.
        """
        if self._refresh_thread and self._refresh_thread.is_alive():
            logger.warning("CacheWarmer: refresh thread already running")
            return

        self._stop_event.clear()
        tfs = timeframes or [Timeframe.ONE_MINUTE, Timeframe.FIVE_MINUTES, Timeframe.ONE_HOUR]

        def _loop() -> None:
            while not self._stop_event.wait(timeout=interval_s):
                try:
                    self.warm_symbols(symbols)
                    self.warm_ohlcv(symbols, tfs)
                except Exception as exc:
                    logger.warning("CacheWarmer refresh error: %s", exc)

        self._refresh_thread = threading.Thread(
            target=_loop, daemon=True, name="cache-warmer"
        )
        self._refresh_thread.start()
        logger.info(
            "CacheWarmer: scheduled refresh every %.0fs for %d symbols",
            interval_s,
            len(symbols),
        )

    def stop(self) -> None:
        """Stop the background refresh thread."""
        self._stop_event.set()
        if self._refresh_thread:
            self._refresh_thread.join(timeout=3.0)
        logger.info("CacheWarmer: stopped")

    def stats(self) -> dict:
        return {
            "total_warmed": self._warm_count,
            "last_warm_at": self._last_warm_at,
            "refresh_running": bool(
                self._refresh_thread and self._refresh_thread.is_alive()
            ),
        }

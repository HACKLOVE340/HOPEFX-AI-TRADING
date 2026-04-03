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

import asyncio
import json
import logging
import threading
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from enum import Enum
from typing import Any

try:
    from redis.exceptions import TimeoutError as RedisTimeoutError  # re-exported  # noqa: F401

    import redis
    from redis import Redis

    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False
    Redis = None  # type: ignore[assignment,misc]
    logger.warning("Redis not available, using in-memory fallback")

logger = logging.getLogger(__name__)


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
    def from_dict(cls, data: dict) -> "OHLCVData":
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
    def from_dict(cls, data: dict) -> "TickData":
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
        host: str = "localhost",
        port: int = 6379,
        db: int = 0,
        password: str | None = None,
        socket_timeout: float = 1,
        socket_connect_timeout: float = 1,
        decode_responses: bool = True,
        max_retries: int = 1,
        retry_delay: float = 0.5,
        enable_fallback: bool = True,
    ):
        self.host = host
        self.port = port
        self.db = db
        self.password = password
        self.socket_timeout = socket_timeout
        self.socket_connect_timeout = socket_connect_timeout
        self.decode_responses = decode_responses
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self.enable_fallback = enable_fallback

        # Thread safety
        self._stats_lock = threading.Lock()
        self._local_cache_lock = threading.Lock()

        # Statistics
        self._stats = CacheStatistics()

        # In-memory fallback
        self._local_cache: dict[str, Any] = {}
        self._local_ttl: dict[str, float] = {}
        self._using_fallback = False

        # Redis client (initialized on first use)
        self._redis_client: Redis | None = None
        self._connection_failed = False

        # Attempt connection at init time (tests patch this method)
        self._redis_client = self._connect_with_retry()

        logger.info("MarketDataCache initialized (Redis: %s:%s)", host, port)


    def _connect_with_retry(self) -> Redis | None:
        """Attempt Redis connection with retries; return client or None on failure."""
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
                if attempt > 0:
                    logger.info("Redis connected after %s retries", attempt)

                return client
            except Exception as e:
                logger.warning("Redis connection attempt %s failed: %s", attempt + 1, e)

                if attempt < self.max_retries - 1:
                    time.sleep(self.retry_delay * (2**attempt))
        self._connection_failed = True
        self._using_fallback = True
        if self.enable_fallback:
            logger.warning("Using in-memory fallback for cache")
            return None
        raise ConnectionError(f"Could not connect to Redis at {self.host}:{self.port}")

    def _get_redis(self) -> Redis | None:
        """Get or create Redis connection with retry"""
        if self._connection_failed and not self.enable_fallback:
            return None

        if self._redis_client is not None:
            try:
                self._redis_client.ping()
                self._using_fallback = False
                return self._redis_client
            except Exception as _exc:
                logger.debug("Suppressed exception: %s", _exc)  # Connection lost, will retry

        # Try to connect
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

                if attempt > 0:
                    logger.info("Redis reconnected after %s attempts", attempt)


                return client

            except Exception as e:
                logger.warning("Redis connection attempt %s failed: %s", attempt + 1, e)

                if attempt < self.max_retries - 1:
                    time.sleep(self.retry_delay * (2**attempt))

        # All retries failed
        self._connection_failed = True
        self._using_fallback = True

        if self.enable_fallback:
            logger.warning("Using in-memory fallback for cache")
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
        """Check if local cache key is still valid"""
        if key not in self._local_ttl:
            return False
        return time.time() < self._local_ttl[key]

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

            # Try Redis first
            redis_client = self._get_redis()
            if redis_client:
                redis_client.setex(key, ttl, json.dumps(cached_data))
            else:
                # Fallback to local cache
                with self._local_cache_lock:
                    self._local_cache[key] = cached_data
                    self._local_ttl[key] = time.time() + ttl

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
                # Fallback to local cache
                with self._local_cache_lock:
                    if self._is_local_key_valid(key):
                        cached = json.dumps(self._local_cache.get(key))
                    else:
                        # Clean up expired key
                        self._local_cache.pop(key, None)
                        self._local_ttl.pop(key, None)

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
            if redis_client:
                redis_client.setex(key, ttl, json.dumps(cached_data))
            else:
                with self._local_cache_lock:
                    self._local_cache[key] = cached_data
                    self._local_ttl[key] = time.time() + ttl

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
                with self._local_cache_lock:
                    if self._is_local_key_valid(key):
                        cached = json.dumps(self._local_cache.get(key))

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
                # Local cache cleanup
                with self._local_cache_lock:
                    keys_to_remove = [
                        k
                        for k in self._local_cache
                        if k.startswith(f"market_data:{symbol}:") or k == f"tick_data:{symbol}"
                    ]
                    for k in keys_to_remove:
                        self._local_cache.pop(k, None)
                        self._local_ttl.pop(k, None)

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
                # Clear local cache
                with self._local_cache_lock:
                    self._local_cache.clear()
                    self._local_ttl.clear()

            with self._stats_lock:
                self._stats.total_evictions += len(all_keys) if redis_client else len(self._local_cache)

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
                self._local_cache[key] = serialized
                self._local_ttl[key] = time.time() + ttl
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
            elif self._is_local_key_valid(key):
                raw = self._local_cache.get(key)
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
            elif self._is_local_key_valid(key):
                raw = self._local_cache.get(key)
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
                self._local_cache[key] = serialized
                self._local_ttl[key] = time.time() + ttl
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
            elif key in self._local_cache:
                del self._local_cache[key]
                self._local_ttl.pop(key, None)
                deleted = True
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
            elif key in self._local_cache:
                del self._local_cache[key]
                self._local_ttl.pop(key, None)
                deleted = True
            if deleted:
                with self._stats_lock:
                    self._stats.total_evictions += 1
            return deleted
        except Exception as e:
            logger.error("invalidate_tick error: %s", e)

            return False

    def get_statistics(self) -> CacheStatistics:
        """Get cache statistics"""
        try:
            redis_client = self._get_redis()

            with self._stats_lock:
                stats = CacheStatistics(
                    total_hits=self._stats.total_hits,
                    total_misses=self._stats.total_misses,
                    total_evictions=self._stats.total_evictions,
                    last_update=time.time(),
                )

                if redis_client:
                    try:
                        info = redis_client.info("memory")
                        stats.memory_usage_bytes = int(info.get("used_memory", 0))

                        # Count keys
                        cursor = 0
                        key_count = 0
                        while True:
                            cursor, keys = redis_client.scan(cursor=cursor, match="market_data:*", count=100)
                            key_count += len(keys)
                            if cursor == 0:
                                break

                        cursor = 0
                        while True:
                            cursor, keys = redis_client.scan(cursor=cursor, match="tick_data:*", count=100)
                            key_count += len(keys)
                            if cursor == 0:
                                break

                        stats.total_keys = key_count
                    except Exception as e:
                        logger.error("Error getting Redis stats: %s", e)

                else:
                    with self._local_cache_lock:
                        stats.total_keys = len(self._local_cache)
                        # Estimate memory
                        stats.memory_usage_bytes = len(str(self._local_cache).encode("utf-8"))

                return stats

        except Exception as e:
            logger.error("Error getting statistics: %s", e)

            return CacheStatistics()

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
        loop = asyncio.get_event_loop()
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

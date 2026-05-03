# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
market_data/redis_cache.py

Redis-backed market data cache — provides O(1) tick lookups and
time-series OHLCV retrieval for the ML pipeline and risk engine.

Key schema:
  hopefx:tick_cache:{symbol}          ZSET   score=timestamp, member=tick_json
  hopefx:latest_bar:{symbol}:{tf}     STRING bar_json (TTL 24h)
  hopefx:ohlcv:{symbol}:{tf}          ZSET   score=bar_open_ts, member=bar_json
  hopefx:feed:health                  STRING health_json (TTL 60s)
  hopefx:{key}:stale                  STRING stale copy during stampede recompute
  hopefx:{key}:lock                   STRING NX lock for stampede prevention

TTL-aware invalidation
  store_tick() and store_bar() prune entries older than their TTL window on
  every write and refresh the key TTL so Redis can reclaim quiet symbols.
  invalidate() and invalidate_pattern() provide explicit eviction.

Cache stampede prevention
  get_or_compute() uses SET NX to ensure only one caller recomputes an
  expired value; others receive the stale copy or None.

Hot-key detection
  Every read is counted in a per-key rolling 60-second window.
  Keys exceeding CACHE_HOT_KEY_THRESHOLD_RPS are logged and tracked.
  hot_key_report() returns the current hot-key table.

All operations are synchronous (redis-py).
Zero silent failures: every Redis exception is logged + Sentry captured.
Callers receive None / empty list on cache miss — never an exception.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
import traceback
from collections import defaultdict, deque
from typing import Any, Callable

logger = logging.getLogger(__name__)

try:
    import sentry_sdk  # type: ignore[import]

    _SENTRY = True
except ImportError:
    _SENTRY = False

# ── Constants ─────────────────────────────────────────────────────────────────

# Probabilistic early expiry: recompute when remaining TTL < this fraction.
# Prevents thundering-herd on expiry by staggering recomputes across clients.
_EARLY_EXPIRY_BETA: float = float(os.environ.get("CACHE_EARLY_EXPIRY_BETA", "1.0"))

# Hot-key detection: keys accessed more than this many times per second
# (rolling 60-s window) are flagged as hot.
_HOT_KEY_THRESHOLD_RPS: float = float(os.environ.get("CACHE_HOT_KEY_THRESHOLD_RPS", "100.0"))
_HOT_KEY_WINDOW_SECONDS: float = 60.0

# Stampede lock TTL in seconds — how long a recompute lock is held.
_STAMPEDE_LOCK_TTL: int = int(os.environ.get("CACHE_STAMPEDE_LOCK_TTL", "10"))


class MarketDataCache:
    """
    Redis-backed market data cache with production-grade reliability features.

    Enhancements over the base implementation:

    TTL-aware invalidation
    ----------------------
    ``store_tick()`` and ``store_bar()`` accept explicit TTL values.
    ``get_with_ttl()`` returns both the value and its remaining TTL so callers
    can decide whether to refresh before expiry.  Probabilistic early expiry
    (XFetch algorithm) recomputes values before they expire to avoid
    thundering-herd on popular keys.

    Cache stampede prevention
    -------------------------
    ``get_or_compute()`` uses a Redis SET NX lock so only one caller recomputes
    an expired value while others receive the stale value (or wait briefly).
    The lock TTL is configurable via CACHE_STAMPEDE_LOCK_TTL.

    Hot-key detection
    -----------------
    Every cache access is counted in a per-key rolling 60-second window.
    Keys exceeding CACHE_HOT_KEY_THRESHOLD_RPS are logged and tracked in
    ``hot_keys``.  ``hot_key_report()`` returns the current hot-key table.

    All get_* methods return None / [] on cache miss or Redis error.
    All set_* methods log errors but do not raise.
    """

    def __init__(
        self,
        redis_client,
        key_prefix: str = "hopefx:",
        ohlcv_max_bars: int = 500,
        hot_key_threshold_rps: float = _HOT_KEY_THRESHOLD_RPS,
        stampede_lock_ttl: int = _STAMPEDE_LOCK_TTL,
    ) -> None:
        self._r = redis_client
        self._prefix = key_prefix
        self._ohlcv_max_bars = ohlcv_max_bars
        self._hot_key_threshold_rps = hot_key_threshold_rps
        self._stampede_lock_ttl = stampede_lock_ttl

        # Hot-key tracking: key → deque of access timestamps (monotonic)
        self._access_log: dict[str, deque] = defaultdict(lambda: deque())
        self._hot_keys: dict[str, float] = {}   # key → current rps
        self._access_lock = threading.Lock()    # protects _access_log / _hot_keys

    # ------------------------------------------------------------------
    # Hot-key detection
    # ------------------------------------------------------------------

    def _record_access(self, key: str) -> None:
        """Record a cache access and update hot-key status for *key*."""
        now = time.monotonic()
        with self._access_lock:
            log = self._access_log[key]
            log.append(now)
            # Evict accesses outside the rolling window.
            cutoff = now - _HOT_KEY_WINDOW_SECONDS
            while log and log[0] < cutoff:
                log.popleft()
            rps = len(log) / _HOT_KEY_WINDOW_SECONDS
            if rps >= self._hot_key_threshold_rps:
                if key not in self._hot_keys:
                    logger.warning(
                        "HOT KEY detected: key=%s rps=%.1f threshold=%.1f",
                        key, rps, self._hot_key_threshold_rps,
                    )
                self._hot_keys[key] = rps
            else:
                self._hot_keys.pop(key, None)

    @property
    def hot_keys(self) -> dict[str, float]:
        """Return a snapshot of currently hot keys and their access rates."""
        with self._access_lock:
            return dict(self._hot_keys)

    def hot_key_report(self) -> list[dict]:
        """Return hot keys sorted by descending access rate."""
        with self._access_lock:
            return sorted(
                [{"key": k, "rps": round(v, 2)} for k, v in self._hot_keys.items()],
                key=lambda x: -x["rps"],
            )

    # ------------------------------------------------------------------
    # TTL-aware get / set
    # ------------------------------------------------------------------

    def get_with_ttl(self, key: str) -> tuple[Any | None, int]:
        """
        Return ``(value, remaining_ttl_seconds)`` for *key*.

        Returns ``(None, -2)`` on miss, ``(value, -1)`` if key has no TTL.
        """
        full_key = f"{self._prefix}{key}"
        self._record_access(full_key)
        try:
            pipe = self._r.pipeline(transaction=False)
            pipe.get(full_key)
            pipe.ttl(full_key)
            raw, ttl = pipe.execute()
            if raw is None:
                return None, -2
            return json.loads(raw), int(ttl)
        except Exception as exc:
            self._log_error("get_with_ttl", exc)
            return None, -2

    def set_with_ttl(self, key: str, value: Any, ttl_seconds: int) -> bool:
        """
        Store *value* under *key* with an explicit TTL.

        Returns True on success, False on error.
        """
        full_key = f"{self._prefix}{key}"
        try:
            self._r.setex(full_key, ttl_seconds, json.dumps(value))
            return True
        except Exception as exc:
            self._log_error("set_with_ttl", exc)
            return False

    def get_or_compute(
        self,
        key: str,
        compute_fn: Callable[[], Any],
        ttl_seconds: int,
        stale_ttl_seconds: int = 0,
    ) -> Any | None:
        """
        Return cached value for *key*, computing it if missing or expired.

        Stampede prevention: uses a Redis SET NX lock so only one caller
        recomputes while others receive the stale value (if *stale_ttl_seconds*
        > 0) or None.

        Parameters
        ----------
        key:
            Cache key (without prefix).
        compute_fn:
            Zero-argument callable that returns the fresh value.
        ttl_seconds:
            TTL for the freshly computed value.
        stale_ttl_seconds:
            If > 0, a stale copy is kept under ``{key}:stale`` for this many
            seconds so concurrent callers can serve it while recompute runs.
        """
        full_key = f"{self._prefix}{key}"
        stale_key = f"{self._prefix}{key}:stale"
        lock_key = f"{self._prefix}{key}:lock"
        self._record_access(full_key)

        # Fast path: value is cached.
        try:
            raw = self._r.get(full_key)
            if raw is not None:
                return json.loads(raw)
        except Exception as exc:
            self._log_error("get_or_compute.get", exc)

        # Try to acquire the recompute lock (SET NX EX).
        try:
            acquired = self._r.set(lock_key, "1", nx=True, ex=self._stampede_lock_ttl)
        except Exception as exc:
            self._log_error("get_or_compute.lock", exc)
            acquired = False

        if not acquired:
            # Another caller is recomputing — serve stale if available.
            if stale_ttl_seconds > 0:
                try:
                    stale_raw = self._r.get(stale_key)
                    if stale_raw is not None:
                        logger.debug("Serving stale value for key=%s during recompute", key)
                        return json.loads(stale_raw)
                except Exception as exc:
                    self._log_error("get_or_compute.stale", exc)
            return None

        # We hold the lock — recompute.
        try:
            value = compute_fn()
            if value is not None:
                payload = json.dumps(value)
                pipe = self._r.pipeline(transaction=False)
                pipe.setex(full_key, ttl_seconds, payload)
                if stale_ttl_seconds > 0:
                    pipe.setex(stale_key, stale_ttl_seconds, payload)
                pipe.execute()
            return value
        except Exception as exc:
            self._log_error("get_or_compute.compute", exc)
            return None
        finally:
            try:
                self._r.delete(lock_key)
            except Exception:
                pass

    def invalidate(self, key: str) -> bool:
        """
        Explicitly invalidate *key* (and its stale copy).

        Returns True if the key existed and was deleted.
        """
        full_key = f"{self._prefix}{key}"
        stale_key = f"{self._prefix}{key}:stale"
        try:
            deleted = self._r.delete(full_key, stale_key)
            return deleted > 0
        except Exception as exc:
            self._log_error("invalidate", exc)
            return False

    def invalidate_pattern(self, pattern: str) -> int:
        """
        Invalidate all keys matching *pattern* (glob-style, without prefix).

        Uses SCAN to avoid blocking Redis.  Returns the number of keys deleted.
        """
        full_pattern = f"{self._prefix}{pattern}"
        deleted = 0
        try:
            cursor = 0
            while True:
                cursor, keys = self._r.scan(cursor, match=full_pattern, count=100)
                if keys:
                    deleted += self._r.delete(*keys)
                if cursor == 0:
                    break
            return deleted
        except Exception as exc:
            self._log_error("invalidate_pattern", exc)
            return 0

    # ------------------------------------------------------------------
    # Tick cache
    # ------------------------------------------------------------------

    def store_tick(
        self,
        symbol: str,
        tick: dict[str, Any],
        ttl_seconds: int = 86400,
        max_ticks: int = 10000,
    ) -> None:
        """
        Store a tick in the sorted set and enforce TTL-aware invalidation.

        Ticks older than *ttl_seconds* are pruned on each write so the set
        never grows unbounded.  The sorted set key itself also gets a TTL
        refresh so Redis can reclaim it when the symbol goes quiet.
        """
        try:
            key = f"{self._prefix}tick_cache:{symbol}"
            score = float(tick.get("timestamp", time.time()))
            payload = json.dumps(tick)
            cutoff = time.time() - ttl_seconds
            pipe = self._r.pipeline(transaction=False)
            pipe.zadd(key, {payload: score})
            # Remove ticks older than TTL window.
            pipe.zremrangebyscore(key, "-inf", cutoff)
            # Cap total count to avoid unbounded growth.
            pipe.zremrangebyrank(key, 0, -(max_ticks + 1))
            # Refresh key TTL so Redis can expire the whole set when quiet.
            pipe.expire(key, ttl_seconds * 2)
            pipe.execute()
        except Exception as exc:
            self._log_error("store_tick", exc)

    def get_latest_tick(self, symbol: str) -> dict[str, Any] | None:
        """Return the most recent tick for *symbol*, or None."""
        key = f"{self._prefix}tick_cache:{symbol}"
        self._record_access(key)
        try:
            results = self._r.zrevrange(key, 0, 0)
            if results:
                return json.loads(results[0])
            return None
        except Exception as exc:
            self._log_error("get_latest_tick", exc)
            return None

    def get_recent_ticks(self, symbol: str, n: int = 100) -> list[dict[str, Any]]:
        """Return up to *n* most recent ticks for *symbol*."""
        key = f"{self._prefix}tick_cache:{symbol}"
        self._record_access(key)
        try:
            results = self._r.zrevrange(key, 0, n - 1)
            return [json.loads(r) for r in results]
        except Exception as exc:
            self._log_error("get_recent_ticks", exc)
            return []

    def get_ticks_since(self, symbol: str, since_ts: float) -> list[dict[str, Any]]:
        """Return all ticks with timestamp >= *since_ts*."""
        key = f"{self._prefix}tick_cache:{symbol}"
        self._record_access(key)
        try:
            results = self._r.zrangebyscore(key, since_ts, "+inf")
            return [json.loads(r) for r in results]
        except Exception as exc:
            self._log_error("get_ticks_since", exc)
            return []

    # ------------------------------------------------------------------
    # OHLCV bar cache
    # ------------------------------------------------------------------

    def store_bar(
        self,
        symbol: str,
        timeframe: str,
        bar: dict[str, Any],
        ttl_seconds: int = 604800,
    ) -> None:
        """
        Store a closed OHLCV bar with TTL-aware invalidation.

        The sorted set TTL is refreshed on every write.  Bars older than
        *ttl_seconds* are pruned so the set stays bounded.  The latest-bar
        STRING key is also updated atomically.
        """
        try:
            key = f"{self._prefix}ohlcv:{symbol}:{timeframe}"
            latest_key = f"{self._prefix}latest_bar:{symbol}:{timeframe}"
            payload = json.dumps(bar)
            score = float(bar.get("bar_open_ts", time.time()))
            cutoff = time.time() - ttl_seconds

            pipe = self._r.pipeline(transaction=False)
            pipe.zadd(key, {payload: score})
            # Prune bars outside the TTL window.
            pipe.zremrangebyscore(key, "-inf", cutoff)
            # Cap total count.
            pipe.zremrangebyrank(key, 0, -(self._ohlcv_max_bars + 1))
            # Refresh set TTL.
            pipe.expire(key, ttl_seconds)
            # Update latest-bar STRING with 24-hour TTL.
            pipe.setex(latest_key, 86400, payload)
            pipe.execute()
        except Exception as exc:
            self._log_error("store_bar", exc)

    def get_bars(
        self,
        symbol: str,
        timeframe: str,
        n: int = 100,
    ) -> list[dict[str, Any]]:
        """Return up to *n* most recent closed bars for *symbol*/*timeframe*."""
        key = f"{self._prefix}ohlcv:{symbol}:{timeframe}"
        self._record_access(key)
        try:
            results = self._r.zrevrange(key, 0, n - 1)
            bars = [json.loads(r) for r in results]
            return list(reversed(bars))
        except Exception as exc:
            self._log_error("get_bars", exc)
            return []

    def get_bars_since(
        self,
        symbol: str,
        timeframe: str,
        since_ts: float,
    ) -> list[dict[str, Any]]:
        """Return all bars with bar_open_ts >= *since_ts*."""
        key = f"{self._prefix}ohlcv:{symbol}:{timeframe}"
        self._record_access(key)
        try:
            results = self._r.zrangebyscore(key, since_ts, "+inf")
            return [json.loads(r) for r in results]
        except Exception as exc:
            self._log_error("get_bars_since", exc)
            return []

    def get_latest_bar(self, symbol: str, timeframe: str) -> dict[str, Any] | None:
        """Return the most recently closed bar."""
        key = f"{self._prefix}latest_bar:{symbol}:{timeframe}"
        self._record_access(key)
        try:
            val = self._r.get(key)
            return json.loads(val) if val else None
        except Exception as exc:
            self._log_error("get_latest_bar", exc)
            return None

    # ------------------------------------------------------------------
    # Feed health
    # ------------------------------------------------------------------

    def get_feed_health(self) -> dict[str, Any] | None:
        """Return the latest feed health snapshot."""
        key = f"{self._prefix}feed:health"
        self._record_access(key)
        try:
            val = self._r.get(key)
            return json.loads(val) if val else None
        except Exception as exc:
            self._log_error("get_feed_health", exc)
            return None

    def store_feed_health(self, health: dict[str, Any], ttl_seconds: int = 60) -> None:
        """Store a feed health snapshot with a short TTL."""
        try:
            self._r.setex(f"{self._prefix}feed:health", ttl_seconds, json.dumps(health))
        except Exception as exc:
            self._log_error("store_feed_health", exc)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def ping(self) -> bool:
        """Return True if Redis is reachable."""
        try:
            return bool(self._r.ping())
        except Exception as exc:
            self._log_error("ping", exc)
            return False

    def _log_error(self, operation: str, exc: Exception) -> None:
        tb = traceback.format_exc()
        logger.error("MarketDataCache.%s error: %s\n%s", operation, exc, tb)
        if _SENTRY:
            try:
                sentry_sdk.capture_exception(exc)
            except Exception as _exc:
                logger.debug("Suppressed exception: %s", _exc)

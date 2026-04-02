# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
data_layer/cache/redis_store.py
=================================
DataLayerRedisStore — high-performance Redis caching for the data layer.

Key schema (all prefixed hopefx:dl:)
--------------------------------------
  hopefx:dl:tick:{symbol}              STRING  latest validated tick JSON       TTL: 30s
  hopefx:dl:tick_history:{symbol}      ZSET    score=epoch, member=tick_json    TTL: 1h (trimmed to 10k)
  hopefx:dl:ohlcv:{symbol}:{tf}        ZSET    score=bar_open_epoch, member=bar_json  TTL: per-tf
  hopefx:dl:ohlcv_latest:{symbol}:{tf} STRING  latest bar JSON                  TTL: per-tf
  hopefx:dl:micro:{symbol}             STRING  microstructure snapshot JSON      TTL: 5s
  hopefx:dl:sentiment                  STRING  sentiment signal JSON             TTL: 60s
  hopefx:dl:macro_features             STRING  macro ML features JSON            TTL: 300s
  hopefx:dl:calendar_impact            STRING  current impact score float        TTL: 60s
  hopefx:dl:quality_report:{symbol}    STRING  quality report JSON               TTL: 30s
  hopefx:dl:feed_health                STRING  feed health dict JSON             TTL: 10s

Per-instrument TTL strategy
-----------------------------
  XAU_USD tick:    30s   (gold is 24h market, ticks arrive every few seconds)
  1m OHLCV:        5m    (bar closes every minute)
  5m OHLCV:        15m
  1h OHLCV:        2h
  4h OHLCV:        8h
  1d OHLCV:        48h

Memory pressure handling
-------------------------
  - OHLCV sorted sets trimmed to DL_OHLCV_MAX_BARS (default 2000)
  - Tick history trimmed to DL_TICK_HISTORY_MAX (default 10000)
  - On Redis ENOMEM error: evict oldest OHLCV bars and retry once
  - Memory usage reported in stats()

All operations degrade gracefully — Redis unavailability never raises.
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any

logger = logging.getLogger(__name__)

_OHLCV_TTL: dict[str, int] = {
    "1m": 300,
    "5m": 900,
    "15m": 1800,
    "1h": 7200,
    "4h": 28800,
    "1d": 172800,
}

_TICK_TTL = int(os.getenv("DL_TICK_TTL_S", "30"))
_MICRO_TTL = int(os.getenv("DL_MICRO_TTL_S", "5"))
_SENTIMENT_TTL = int(os.getenv("DL_SENTIMENT_TTL_S", "60"))
_MACRO_TTL = int(os.getenv("DL_MACRO_TTL_S", "300"))
_CALENDAR_TTL = int(os.getenv("DL_CALENDAR_TTL_S", "60"))
_QUALITY_TTL = int(os.getenv("DL_QUALITY_TTL_S", "30"))
_HEALTH_TTL = int(os.getenv("DL_HEALTH_TTL_S", "10"))
_TICK_HISTORY_MAX = int(os.getenv("DL_TICK_HISTORY_MAX", "10000"))
_OHLCV_MAX_BARS = int(os.getenv("DL_OHLCV_MAX_BARS", "2000"))

_PREFIX = "hopefx:dl:"


class DataLayerRedisStore:
    """
    Redis cache for the entire data layer.

    All methods are synchronous (redis-py). Async wrappers use
    run_in_executor for use inside asyncio event loops.

    Zero silent failures: every Redis exception is caught, logged at DEBUG,
    and returns None/[] to the caller.
    """

    def __init__(self, redis_client=None) -> None:
        self._r = redis_client
        self._hits = 0
        self._misses = 0
        self._errors = 0
        self._writes = 0
        # Prometheus metrics (initialised before auto-connect so they exist
        # even when Redis is unavailable)
        self._prom_hits = None
        self._prom_misses = None
        self._prom_writes = None
        self._prom_errors = None
        self._prom_hit_rate = None
        self._prom_mem_mb = None
        self._init_prometheus()
        # Auto-connect if no client provided and REDIS_URL is set
        if self._r is None:
            self._try_auto_connect()

    def _init_prometheus(self) -> None:
        try:
            from prometheus_client import Counter, Gauge, REGISTRY

            def _counter(name: str, doc: str) -> Counter:
                try:
                    return Counter(name, doc)
                except ValueError:
                    return REGISTRY._names_to_collectors.get(name)  # type: ignore[return-value]

            def _gauge(name: str, doc: str) -> Gauge:
                try:
                    return Gauge(name, doc)
                except ValueError:
                    return REGISTRY._names_to_collectors.get(name)  # type: ignore[return-value]

            self._prom_hits = _counter("hopefx_redis_cache_hits_total", "Total Redis cache hits")
            self._prom_misses = _counter("hopefx_redis_cache_misses_total", "Total Redis cache misses")
            self._prom_writes = _counter("hopefx_redis_cache_writes_total", "Total Redis cache writes")
            self._prom_errors = _counter("hopefx_redis_cache_errors_total", "Total Redis cache errors")
            self._prom_hit_rate = _gauge("hopefx_redis_cache_hit_rate", "Rolling Redis cache hit rate [0, 1]")
            self._prom_mem_mb = _gauge("hopefx_redis_memory_rss_mb", "Redis used_memory_rss in MB")
        except Exception as _exc:
            logger.debug("DataLayerRedisStore: Prometheus init skipped: %s", _exc)

    def _try_auto_connect(self) -> None:
        """
        Attempt to connect to Redis.

        Connection priority:
          1. Redis Sentinel (REDIS_SENTINEL_HOSTS + REDIS_SENTINEL_MASTER)
          2. Standard URL (REDIS_URL, default redis://localhost:6379/0)

        Sentinel example .env:
          REDIS_SENTINEL_HOSTS=sentinel1:26379,sentinel2:26379,sentinel3:26379
          REDIS_SENTINEL_MASTER=mymaster
          REDIS_PASSWORD=secret
        """
        import os

        sentinel_hosts_raw = os.getenv("REDIS_SENTINEL_HOSTS", "")
        sentinel_master = os.getenv("REDIS_SENTINEL_MASTER", "mymaster")
        redis_password = os.getenv("REDIS_PASSWORD", "") or None

        # ── Sentinel path ────────────────────────────────────────────────────
        if sentinel_hosts_raw:
            try:
                import redis as _redis_lib
                from redis.sentinel import Sentinel  # type: ignore[import]

                sentinels = []
                for _part in sentinel_hosts_raw.split(","):
                    part = _part.strip()
                    if ":" in part:
                        host, port_s = part.rsplit(":", 1)
                        sentinels.append((host.strip(), int(port_s.strip())))
                    else:
                        sentinels.append((part, 26379))
                sentinel = Sentinel(
                    sentinels,
                    socket_connect_timeout=2,
                    socket_timeout=2,
                    password=redis_password,
                )
                client = sentinel.master_for(
                    sentinel_master,
                    socket_timeout=2,
                    decode_responses=False,
                )
                client.ping()
                self._r = client
                logger.info(
                    "DataLayerRedisStore: connected via Sentinel master=%s hosts=%s",
                    sentinel_master,
                    sentinel_hosts_raw,
                )
                # Emit startup warning if maxmemory is unlimited
                self.get_memory_info()
                return
            except Exception as exc:
                logger.warning(
                    "DataLayerRedisStore: Sentinel connect failed (%s) — falling back to REDIS_URL",
                    exc,
                )

        # ── Standard URL path ────────────────────────────────────────────────
        url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
        try:
            import redis as _redis_lib

            kwargs: dict = {
                "socket_connect_timeout": 2,
                "socket_timeout": 2,
                "decode_responses": False,
            }
            if redis_password:
                kwargs["password"] = redis_password
            client = _redis_lib.from_url(url, **kwargs)
            client.ping()
            self._r = client
            logger.debug("DataLayerRedisStore: auto-connected to %s", url)
            # Emit startup warning if maxmemory is unlimited
            self.get_memory_info()
        except Exception as exc:
            logger.debug(
                "DataLayerRedisStore: auto-connect failed (%s) — caching disabled until orchestrator injects client",
                exc,
            )

    def _key(self, *parts: str) -> str:
        return _PREFIX + ":".join(parts)

    def _safe_set(self, key: str, value: str, ttl: int) -> bool:
        if not self._r:
            return False
        try:
            self._r.setex(key, ttl, value)
            self._writes += 1
            if self._prom_writes:
                self._prom_writes.inc()
            return True
        except Exception as exc:
            self._errors += 1
            if self._prom_errors:
                self._prom_errors.inc()
            # Memory pressure: try to free space and retry once
            if "ENOMEM" in str(exc) or "OOM" in str(exc):
                logger.warning("Redis OOM — attempting eviction and retry")
                self._evict_oldest_ohlcv()
                try:
                    self._r.setex(key, ttl, value)
                    self._writes += 1
                    if self._prom_writes:
                        self._prom_writes.inc()
                    return True
                except Exception as _exc:
                    logger.debug("Redis OOM retry failed: %s", _exc)
            logger.debug("Redis set error key=%s: %s", key, exc)
            return False

    def _safe_get(self, key: str) -> str | None:
        if not self._r:
            return None
        try:
            val = self._r.get(key)
            if val:
                self._hits += 1
                if self._prom_hits:
                    self._prom_hits.inc()
                # Update hit rate gauge
                total = self._hits + self._misses
                if self._prom_hit_rate and total > 0:
                    self._prom_hit_rate.set(self._hits / total)
                return val.decode() if isinstance(val, bytes) else val
            self._misses += 1
            if self._prom_misses:
                self._prom_misses.inc()
            return None
        except Exception as exc:
            self._errors += 1
            if self._prom_errors:
                self._prom_errors.inc()
            logger.debug("Redis get error key=%s: %s", key, exc)
            return None

    def _evict_oldest_ohlcv(self) -> None:
        """Evict oldest 20% of OHLCV bars across all timeframes to free memory."""
        if not self._r:
            return
        try:
            pattern = self._key("ohlcv", "*")
            keys = self._r.keys(pattern)
            for key in keys:
                count = self._r.zcard(key)
                if count > 100:
                    evict_count = max(1, count // 5)
                    self._r.zremrangebyrank(key, 0, evict_count - 1)
                    logger.debug(
                        "Redis eviction: removed %d bars from %s",
                        evict_count,
                        key,
                    )
        except Exception as exc:
            logger.debug("Redis eviction error: %s", exc)

    # ── Tick cache ────────────────────────────────────────────────────────────

    def set_tick(self, symbol: str, tick_dict: dict[str, Any]) -> None:
        """Cache the latest validated tick and push to history."""
        key = self._key("tick", symbol)
        payload = json.dumps(tick_dict)
        self._safe_set(key, payload, _TICK_TTL)

        # Push to sorted set history (score = epoch)
        if self._r:
            try:
                score = tick_dict.get("epoch", time.time())
                hist_key = self._key("tick_history", symbol)
                pipe = self._r.pipeline(transaction=False)
                pipe.zadd(hist_key, {payload: score})
                pipe.zremrangebyrank(hist_key, 0, -(_TICK_HISTORY_MAX + 1))
                pipe.expire(hist_key, 3600)
                pipe.execute()
            except Exception as exc:
                logger.debug("Redis tick_history error: %s", exc)

    def get_tick(self, symbol: str) -> dict[str, Any] | None:
        raw = self._safe_get(self._key("tick", symbol))
        if raw:
            try:
                return json.loads(raw)
            except json.JSONDecodeError:
                return None
        return None

    def get_tick_history(self, symbol: str, limit: int = 500) -> list[dict[str, Any]]:
        """Return the last N ticks from history (oldest first)."""
        if not self._r:
            return []
        try:
            key = self._key("tick_history", symbol)
            raw_list = self._r.zrange(key, -limit, -1)
            return [json.loads(r) for r in raw_list if r]
        except Exception as exc:
            logger.debug("Redis tick_history get error: %s", exc)
            return []

    # ── OHLCV cache ───────────────────────────────────────────────────────────

    def set_ohlcv_bar(self, symbol: str, timeframe: str, bar: dict[str, Any]) -> None:
        ttl = _OHLCV_TTL.get(timeframe, 3600)

        # Latest bar string
        latest_key = self._key("ohlcv_latest", symbol, timeframe)
        self._safe_set(latest_key, json.dumps(bar), ttl)

        # Sorted set history
        if self._r:
            try:
                score = bar.get("open_epoch", time.time())
                hist_key = self._key("ohlcv", symbol, timeframe)
                pipe = self._r.pipeline(transaction=False)
                pipe.zadd(hist_key, {json.dumps(bar): score})
                pipe.zremrangebyrank(hist_key, 0, -(_OHLCV_MAX_BARS + 1))
                pipe.expire(hist_key, ttl * 2)
                pipe.execute()
            except Exception as exc:
                logger.debug("Redis ohlcv set error: %s", exc)

    def get_ohlcv_bars(self, symbol: str, timeframe: str, limit: int = 200) -> list[dict[str, Any]]:
        if not self._r:
            return []
        try:
            key = self._key("ohlcv", symbol, timeframe)
            raw_list = self._r.zrange(key, -limit, -1)
            return [json.loads(r) for r in raw_list if r]
        except Exception as exc:
            logger.debug("Redis ohlcv get error: %s", exc)
            return []

    def get_latest_bar(self, symbol: str, timeframe: str) -> dict[str, Any] | None:
        raw = self._safe_get(self._key("ohlcv_latest", symbol, timeframe))
        if raw:
            try:
                return json.loads(raw)
            except json.JSONDecodeError:
                return None
        return None

    # ── Microstructure cache ──────────────────────────────────────────────────

    def set_microstructure(self, symbol: str, snap: dict[str, Any]) -> None:
        self._safe_set(self._key("micro", symbol), json.dumps(snap), _MICRO_TTL)

    def get_microstructure(self, symbol: str) -> dict[str, Any] | None:
        raw = self._safe_get(self._key("micro", symbol))
        return json.loads(raw) if raw else None

    # ── Sentiment cache ───────────────────────────────────────────────────────

    def set_sentiment(self, signal: dict[str, float]) -> None:
        self._safe_set(self._key("sentiment"), json.dumps(signal), _SENTIMENT_TTL)

    def get_sentiment(self) -> dict[str, float] | None:
        raw = self._safe_get(self._key("sentiment"))
        return json.loads(raw) if raw else None

    # ── Macro features cache ──────────────────────────────────────────────────

    def set_macro_features(self, features: dict[str, float]) -> None:
        self._safe_set(self._key("macro_features"), json.dumps(features), _MACRO_TTL)

    def get_macro_features(self) -> dict[str, float] | None:
        raw = self._safe_get(self._key("macro_features"))
        return json.loads(raw) if raw else None

    # ── Calendar impact cache ─────────────────────────────────────────────────

    def set_calendar_impact(self, score: float) -> None:
        self._safe_set(self._key("calendar_impact"), str(score), _CALENDAR_TTL)

    def get_calendar_impact(self) -> float | None:
        raw = self._safe_get(self._key("calendar_impact"))
        try:
            return float(raw) if raw else None
        except (TypeError, ValueError):
            return None

    # ── Quality report cache ──────────────────────────────────────────────────

    def set_quality_report(self, symbol: str, report: dict[str, Any]) -> None:
        self._safe_set(self._key("quality_report", symbol), json.dumps(report), _QUALITY_TTL)

    def get_quality_report(self, symbol: str) -> dict[str, Any] | None:
        raw = self._safe_get(self._key("quality_report", symbol))
        return json.loads(raw) if raw else None

    # ── Feed health cache ─────────────────────────────────────────────────────

    def set_feed_health(self, health: dict[str, Any]) -> None:
        self._safe_set(self._key("feed_health"), json.dumps(health), _HEALTH_TTL)

    def get_feed_health(self) -> dict[str, Any] | None:
        raw = self._safe_get(self._key("feed_health"))
        return json.loads(raw) if raw else None

    # ── Memory stats ──────────────────────────────────────────────────────────

    def memory_usage_mb(self) -> float | None:
        """Return Redis used_memory_rss in MB, or None if unavailable."""
        if not self._r:
            return None
        try:
            info = self._r.info("memory")
            mb = round(info.get("used_memory_rss", 0) / 1024 / 1024, 2)
            if self._prom_mem_mb:
                self._prom_mem_mb.set(mb)
            return mb
        except Exception as exc:  # nosec B110 — memory metric is non-critical
            logger.debug("memory_mb probe failed: %s", exc)
            return None

    def stats(self) -> dict[str, Any]:
        total = self._hits + self._misses
        return {
            "hits": self._hits,
            "misses": self._misses,
            "writes": self._writes,
            "errors": self._errors,
            "hit_rate": round(self._hits / max(total, 1), 4),
            "connected": self._r is not None,
            "memory_mb": self.memory_usage_mb(),
        }

    def health(self) -> dict[str, Any]:
        """
        Return a health dict suitable for monitoring dashboards.

        Extends stats() with ping latency, key count, and memory info.
        """
        import time as _time

        t0 = _time.monotonic()
        alive = self.ping()
        ping_ms = round((_time.monotonic() - t0) * 1000, 2)
        h = self.stats()
        h.update(
            {
                "alive": alive,
                "ping_ms": ping_ms if alive else None,
                "key_count": self.key_count() if alive else 0,
                "memory_info": self.get_memory_info() if alive else {},
            }
        )
        return h

    def ping(self) -> bool:
        if not self._r:
            return False
        try:
            return bool(self._r.ping())
        except Exception as exc:  # nosec B110 — health-check resilience
            logger.debug("Redis health_check ping failed: %s", exc)
            return False

    # ── Batch / pipeline operations ───────────────────────────────────────────

    def set_many(self, items: dict[str, Any], ttl: int = 300) -> int:
        """
        Write multiple key→value pairs in a single Redis pipeline.

        Parameters
        ----------
        items : dict mapping cache key suffixes to JSON-serialisable values.
                Keys are namespaced automatically under hopefx:.
        ttl   : TTL in seconds applied to every key (default 5 min)

        Returns the number of keys successfully written.
        """
        if not self._r or not items:
            return 0
        try:
            import json

            pipe = self._r.pipeline(transaction=False)
            for suffix, value in items.items():
                full_key = self._key(suffix)
                pipe.setex(full_key, ttl, json.dumps(value, default=str))
            results = pipe.execute()
            written = sum(1 for r in results if r)
            self._writes += written
            if self._prom_writes:
                self._prom_writes.inc(written)
            return written
        except Exception as exc:
            self._errors += 1
            logger.debug("DataLayerRedisStore.set_many error: %s", exc)
            return 0

    def get_many(self, keys: list[str]) -> dict[str, Any]:
        """
        Fetch multiple keys in a single Redis pipeline.

        Parameters
        ----------
        keys : list of key suffixes (same namespace as set_many)

        Returns a dict of {suffix: value} for keys that exist.
        Missing keys are omitted from the result.
        """
        if not self._r or not keys:
            return {}
        try:
            import json

            full_keys = [self._key(k) for k in keys]
            pipe = self._r.pipeline(transaction=False)
            for fk in full_keys:
                pipe.get(fk)
            results = pipe.execute()
            out: dict[str, Any] = {}
            for suffix, raw in zip(keys, results, strict=False):
                if raw is not None:
                    try:
                        out[suffix] = json.loads(raw)
                        self._hits += 1
                    except (ValueError, TypeError):
                        self._misses += 1
                else:
                    self._misses += 1
            return out
        except Exception as exc:
            self._errors += 1
            logger.debug("DataLayerRedisStore.get_many error: %s", exc)
            return {}

    def flush_all(self, pattern: str = "hopefx:*") -> int:
        """
        Delete all keys matching `pattern` (default: all hopefx: keys).

        Returns the number of keys deleted.
        Used in testing and emergency cache invalidation.
        WARNING: in production, prefer targeted key deletion over flush_all.
        """
        if not self._r:
            return 0
        try:
            keys = self._r.keys(pattern)
            if not keys:
                return 0
            deleted = self._r.delete(*keys)
            logger.warning(
                "DataLayerRedisStore.flush_all: deleted %d keys matching '%s'",
                deleted,
                pattern,
            )
            return int(deleted)
        except Exception as exc:
            self._errors += 1
            logger.debug("DataLayerRedisStore.flush_all error: %s", exc)
            return 0

    def get_memory_info(self) -> dict[str, Any]:
        """
        Return detailed Redis memory diagnostics.

        Includes used_memory, used_memory_rss, mem_fragmentation_ratio,
        maxmemory, and maxmemory_policy.  Returns empty dict when Redis
        is unavailable.

        Emits a WARNING when maxmemory=0 (unlimited) — on a VPS this means
        Redis will consume all available RAM before the OOM killer fires.
        Set maxmemory in redis.conf or via REDIS_MAXMEMORY env var.
        """
        if not self._r:
            return {}
        try:
            info = self._r.info("memory")
            maxmemory = info.get("maxmemory", 0)
            if maxmemory == 0:
                logger.warning(
                    "Redis maxmemory is UNLIMITED (0). "
                    "Set maxmemory in redis.conf to prevent OOM on VPS/K8s. "
                    "Recommended: maxmemory 512mb maxmemory-policy allkeys-lru"
                )
            return {
                "used_memory_mb": round(info.get("used_memory", 0) / 1024 / 1024, 2),
                "used_memory_rss_mb": round(info.get("used_memory_rss", 0) / 1024 / 1024, 2),
                "mem_fragmentation": info.get("mem_fragmentation_ratio", 0.0),
                "maxmemory_mb": round(maxmemory / 1024 / 1024, 2),
                "maxmemory_policy": info.get("maxmemory_policy", "unknown"),
                "peak_used_memory_mb": round(info.get("used_memory_peak", 0) / 1024 / 1024, 2),
                "maxmemory_unlimited": maxmemory == 0,
            }
        except Exception as exc:
            logger.debug("DataLayerRedisStore.get_memory_info error: %s", exc)
            return {}

    def key_count(self, pattern: str = "hopefx:*") -> int:
        """Return the number of keys matching `pattern`."""
        if not self._r:
            return 0
        try:
            return len(self._r.keys(pattern))
        except Exception as exc:  # nosec B110 — non-critical metric fallback
            logger.debug("count_keys failed: %s", exc)
            return 0


# Module-level singleton (redis_client injected by orchestrator at startup)
dl_redis_store = DataLayerRedisStore()

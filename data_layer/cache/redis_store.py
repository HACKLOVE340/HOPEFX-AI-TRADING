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
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_OHLCV_TTL: Dict[str, int] = {
    "1m":  300,
    "5m":  900,
    "15m": 1800,
    "1h":  7200,
    "4h":  28800,
    "1d":  172800,
}

_TICK_TTL         = int(os.getenv("DL_TICK_TTL_S",        "30"))
_MICRO_TTL        = int(os.getenv("DL_MICRO_TTL_S",        "5"))
_SENTIMENT_TTL    = int(os.getenv("DL_SENTIMENT_TTL_S",   "60"))
_MACRO_TTL        = int(os.getenv("DL_MACRO_TTL_S",      "300"))
_CALENDAR_TTL     = int(os.getenv("DL_CALENDAR_TTL_S",    "60"))
_QUALITY_TTL      = int(os.getenv("DL_QUALITY_TTL_S",     "30"))
_HEALTH_TTL       = int(os.getenv("DL_HEALTH_TTL_S",      "10"))
_TICK_HISTORY_MAX = int(os.getenv("DL_TICK_HISTORY_MAX", "10000"))
_OHLCV_MAX_BARS   = int(os.getenv("DL_OHLCV_MAX_BARS",   "2000"))

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
        self._r      = redis_client
        self._hits   = 0
        self._misses = 0
        self._errors = 0
        self._writes = 0

    def _key(self, *parts: str) -> str:
        return _PREFIX + ":".join(parts)

    def _safe_set(self, key: str, value: str, ttl: int) -> bool:
        if not self._r:
            return False
        try:
            self._r.setex(key, ttl, value)
            self._writes += 1
            return True
        except Exception as exc:
            self._errors += 1
            # Memory pressure: try to free space and retry once
            if "ENOMEM" in str(exc) or "OOM" in str(exc):
                logger.warning("Redis OOM — attempting eviction and retry")
                self._evict_oldest_ohlcv()
                try:
                    self._r.setex(key, ttl, value)
                    self._writes += 1
                    return True
                except Exception:
                    pass
            logger.debug("Redis set error key=%s: %s", key, exc)
            return False

    def _safe_get(self, key: str) -> Optional[str]:
        if not self._r:
            return None
        try:
            val = self._r.get(key)
            if val:
                self._hits += 1
                return val.decode() if isinstance(val, bytes) else val
            self._misses += 1
            return None
        except Exception as exc:
            self._errors += 1
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
                        evict_count, key,
                    )
        except Exception as exc:
            logger.debug("Redis eviction error: %s", exc)

    # ── Tick cache ────────────────────────────────────────────────────────────

    def set_tick(self, symbol: str, tick_dict: Dict[str, Any]) -> None:
        """Cache the latest validated tick and push to history."""
        key = self._key("tick", symbol)
        payload = json.dumps(tick_dict)
        self._safe_set(key, payload, _TICK_TTL)

        # Push to sorted set history (score = epoch)
        if self._r:
            try:
                score    = tick_dict.get("epoch", time.time())
                hist_key = self._key("tick_history", symbol)
                pipe = self._r.pipeline(transaction=False)
                pipe.zadd(hist_key, {payload: score})
                pipe.zremrangebyrank(hist_key, 0, -(_TICK_HISTORY_MAX + 1))
                pipe.expire(hist_key, 3600)
                pipe.execute()
            except Exception as exc:
                logger.debug("Redis tick_history error: %s", exc)

    def get_tick(self, symbol: str) -> Optional[Dict[str, Any]]:
        raw = self._safe_get(self._key("tick", symbol))
        if raw:
            try:
                return json.loads(raw)
            except json.JSONDecodeError:
                return None
        return None

    def get_tick_history(
        self, symbol: str, limit: int = 500
    ) -> List[Dict[str, Any]]:
        """Return the last N ticks from history (oldest first)."""
        if not self._r:
            return []
        try:
            key      = self._key("tick_history", symbol)
            raw_list = self._r.zrange(key, -limit, -1)
            return [json.loads(r) for r in raw_list if r]
        except Exception as exc:
            logger.debug("Redis tick_history get error: %s", exc)
            return []

    # ── OHLCV cache ───────────────────────────────────────────────────────────

    def set_ohlcv_bar(self, symbol: str, timeframe: str, bar: Dict[str, Any]) -> None:
        ttl = _OHLCV_TTL.get(timeframe, 3600)

        # Latest bar string
        latest_key = self._key("ohlcv_latest", symbol, timeframe)
        self._safe_set(latest_key, json.dumps(bar), ttl)

        # Sorted set history
        if self._r:
            try:
                score    = bar.get("open_epoch", time.time())
                hist_key = self._key("ohlcv", symbol, timeframe)
                pipe = self._r.pipeline(transaction=False)
                pipe.zadd(hist_key, {json.dumps(bar): score})
                pipe.zremrangebyrank(hist_key, 0, -(_OHLCV_MAX_BARS + 1))
                pipe.expire(hist_key, ttl * 2)
                pipe.execute()
            except Exception as exc:
                logger.debug("Redis ohlcv set error: %s", exc)

    def get_ohlcv_bars(
        self, symbol: str, timeframe: str, limit: int = 200
    ) -> List[Dict[str, Any]]:
        if not self._r:
            return []
        try:
            key      = self._key("ohlcv", symbol, timeframe)
            raw_list = self._r.zrange(key, -limit, -1)
            return [json.loads(r) for r in raw_list if r]
        except Exception as exc:
            logger.debug("Redis ohlcv get error: %s", exc)
            return []

    def get_latest_bar(
        self, symbol: str, timeframe: str
    ) -> Optional[Dict[str, Any]]:
        raw = self._safe_get(self._key("ohlcv_latest", symbol, timeframe))
        if raw:
            try:
                return json.loads(raw)
            except json.JSONDecodeError:
                return None
        return None

    # ── Microstructure cache ──────────────────────────────────────────────────

    def set_microstructure(self, symbol: str, snap: Dict[str, Any]) -> None:
        self._safe_set(self._key("micro", symbol), json.dumps(snap), _MICRO_TTL)

    def get_microstructure(self, symbol: str) -> Optional[Dict[str, Any]]:
        raw = self._safe_get(self._key("micro", symbol))
        return json.loads(raw) if raw else None

    # ── Sentiment cache ───────────────────────────────────────────────────────

    def set_sentiment(self, signal: Dict[str, float]) -> None:
        self._safe_set(self._key("sentiment"), json.dumps(signal), _SENTIMENT_TTL)

    def get_sentiment(self) -> Optional[Dict[str, float]]:
        raw = self._safe_get(self._key("sentiment"))
        return json.loads(raw) if raw else None

    # ── Macro features cache ──────────────────────────────────────────────────

    def set_macro_features(self, features: Dict[str, float]) -> None:
        self._safe_set(self._key("macro_features"), json.dumps(features), _MACRO_TTL)

    def get_macro_features(self) -> Optional[Dict[str, float]]:
        raw = self._safe_get(self._key("macro_features"))
        return json.loads(raw) if raw else None

    # ── Calendar impact cache ─────────────────────────────────────────────────

    def set_calendar_impact(self, score: float) -> None:
        self._safe_set(self._key("calendar_impact"), str(score), _CALENDAR_TTL)

    def get_calendar_impact(self) -> Optional[float]:
        raw = self._safe_get(self._key("calendar_impact"))
        try:
            return float(raw) if raw else None
        except (TypeError, ValueError):
            return None

    # ── Quality report cache ──────────────────────────────────────────────────

    def set_quality_report(self, symbol: str, report: Dict[str, Any]) -> None:
        self._safe_set(
            self._key("quality_report", symbol), json.dumps(report), _QUALITY_TTL
        )

    def get_quality_report(self, symbol: str) -> Optional[Dict[str, Any]]:
        raw = self._safe_get(self._key("quality_report", symbol))
        return json.loads(raw) if raw else None

    # ── Feed health cache ─────────────────────────────────────────────────────

    def set_feed_health(self, health: Dict[str, Any]) -> None:
        self._safe_set(self._key("feed_health"), json.dumps(health), _HEALTH_TTL)

    def get_feed_health(self) -> Optional[Dict[str, Any]]:
        raw = self._safe_get(self._key("feed_health"))
        return json.loads(raw) if raw else None

    # ── Memory stats ──────────────────────────────────────────────────────────

    def memory_usage_mb(self) -> Optional[float]:
        """Return Redis used_memory_rss in MB, or None if unavailable."""
        if not self._r:
            return None
        try:
            info = self._r.info("memory")
            return round(info.get("used_memory_rss", 0) / 1024 / 1024, 2)
        except Exception:
            return None

    def stats(self) -> Dict[str, Any]:
        total = self._hits + self._misses
        return {
            "hits":         self._hits,
            "misses":       self._misses,
            "writes":       self._writes,
            "errors":       self._errors,
            "hit_rate":     round(self._hits / max(total, 1), 4),
            "connected":    self._r is not None,
            "memory_mb":    self.memory_usage_mb(),
        }

    def ping(self) -> bool:
        if not self._r:
            return False
        try:
            return bool(self._r.ping())
        except Exception:
            return False


# Module-level singleton (redis_client injected by orchestrator at startup)
dl_redis_store = DataLayerRedisStore()

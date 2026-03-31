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
  hopefx:tick_cache:{symbol}          ZSET  score=timestamp, member=tick_json
  hopefx:latest_bar:{symbol}:{tf}     STRING  bar_json (TTL 24h)
  hopefx:ohlcv:{symbol}:{tf}          ZSET  score=bar_open_ts, member=bar_json
  hopefx:feed:health                  STRING  health_json (TTL 60s)

All operations are synchronous (redis-py).  Async wrappers are provided
for use inside asyncio event loops via run_in_executor.

Zero silent failures: every Redis exception is logged + Sentry captured.
Callers receive None / empty list on cache miss — never an exception.
"""

from __future__ import annotations

import json
import logging
import time
import traceback
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

try:
    import sentry_sdk  # type: ignore[import]

    _SENTRY = True
except ImportError:
    _SENTRY = False


class MarketDataCache:
    """
    Redis-backed market data cache.

    All get_* methods return None / [] on cache miss or Redis error.
    All set_* methods log errors but do not raise.
    """

    def __init__(
        self,
        redis_client,
        key_prefix: str = "hopefx:",
        ohlcv_max_bars: int = 500,
    ) -> None:
        self._r = redis_client
        self._prefix = key_prefix
        self._ohlcv_max_bars = ohlcv_max_bars

    # ------------------------------------------------------------------
    # Tick cache
    # ------------------------------------------------------------------

    def get_latest_tick(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Return the most recent tick for *symbol*, or None."""
        try:
            key = f"{self._prefix}tick_cache:{symbol}"
            results = self._r.zrevrange(key, 0, 0)
            if results:
                return json.loads(results[0])
            return None
        except Exception as exc:
            self._log_error("get_latest_tick", exc)
            return None

    def get_recent_ticks(self, symbol: str, n: int = 100) -> List[Dict[str, Any]]:
        """Return up to *n* most recent ticks for *symbol*."""
        try:
            key = f"{self._prefix}tick_cache:{symbol}"
            results = self._r.zrevrange(key, 0, n - 1)
            return [json.loads(r) for r in results]
        except Exception as exc:
            self._log_error("get_recent_ticks", exc)
            return []

    def get_ticks_since(self, symbol: str, since_ts: float) -> List[Dict[str, Any]]:
        """Return all ticks with timestamp >= *since_ts*."""
        try:
            key = f"{self._prefix}tick_cache:{symbol}"
            results = self._r.zrangebyscore(key, since_ts, "+inf")
            return [json.loads(r) for r in results]
        except Exception as exc:
            self._log_error("get_ticks_since", exc)
            return []

    # ------------------------------------------------------------------
    # OHLCV bar cache
    # ------------------------------------------------------------------

    def store_bar(self, symbol: str, timeframe: str, bar: Dict[str, Any]) -> None:
        """Store a closed OHLCV bar."""
        try:
            key = f"{self._prefix}ohlcv:{symbol}:{timeframe}"
            payload = json.dumps(bar)
            score = float(bar.get("bar_open_ts", time.time()))
            self._r.zadd(key, {payload: score})
            # Keep only last N bars
            self._r.zremrangebyrank(key, 0, -(self._ohlcv_max_bars + 1))
            # 7-day TTL
            self._r.expire(key, 604800)
        except Exception as exc:
            self._log_error("store_bar", exc)

    def get_bars(
        self,
        symbol: str,
        timeframe: str,
        n: int = 100,
    ) -> List[Dict[str, Any]]:
        """Return up to *n* most recent closed bars for *symbol*/*timeframe*."""
        try:
            key = f"{self._prefix}ohlcv:{symbol}:{timeframe}"
            results = self._r.zrevrange(key, 0, n - 1)
            bars = [json.loads(r) for r in results]
            # Return in chronological order
            return list(reversed(bars))
        except Exception as exc:
            self._log_error("get_bars", exc)
            return []

    def get_bars_since(
        self,
        symbol: str,
        timeframe: str,
        since_ts: float,
    ) -> List[Dict[str, Any]]:
        """Return all bars with bar_open_ts >= *since_ts*."""
        try:
            key = f"{self._prefix}ohlcv:{symbol}:{timeframe}"
            results = self._r.zrangebyscore(key, since_ts, "+inf")
            return [json.loads(r) for r in results]
        except Exception as exc:
            self._log_error("get_bars_since", exc)
            return []

    def get_latest_bar(self, symbol: str, timeframe: str) -> Optional[Dict[str, Any]]:
        """Return the most recently closed bar."""
        try:
            key = f"{self._prefix}latest_bar:{symbol}:{timeframe}"
            val = self._r.get(key)
            return json.loads(val) if val else None
        except Exception as exc:
            self._log_error("get_latest_bar", exc)
            return None

    # ------------------------------------------------------------------
    # Feed health
    # ------------------------------------------------------------------

    def get_feed_health(self) -> Optional[Dict[str, Any]]:
        """Return the latest feed health snapshot."""
        try:
            val = self._r.get(f"{self._prefix}feed:health")
            return json.loads(val) if val else None
        except Exception as exc:
            self._log_error("get_feed_health", exc)
            return None

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

# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
brokers/ohlcv_store.py
======================
Thin adapter that exposes a DataFrame-returning OHLCV interface backed by
MarketDataCache (Redis) with an in-memory ring-buffer fallback.

Used by LiveInferenceLoop to fetch the rolling OHLCV window without
coupling the ML layer directly to any specific broker.

Architecture
------------
  OHLCVStore.get(symbol, bars)
    → Redis (MarketDataCache.get_bars)   — primary
    → in-memory ring buffer              — fallback when Redis is down
    → None                               — when neither has enough bars

  OHLCVStore.push(symbol, bar_dict)
    → writes to both Redis and ring buffer

The ring buffer holds up to MAX_BARS bars per symbol (default 500).
Bars are stored as dicts with keys: open, high, low, close, volume, ts.

Usage
-----
    from brokers.ohlcv_store import get_ohlcv_store

    store = get_ohlcv_store()
    df = store.get("XAU_USD", bars=150)   # returns pd.DataFrame or None
    store.push("XAU_USD", bar)            # called by tick aggregator
"""

from __future__ import annotations

import logging
import os
from collections import deque
from datetime import datetime, timezone
UTC = timezone.utc
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)

_TIMEFRAME = os.getenv("OHLCV_STORE_TIMEFRAME", "H1")
_MAX_BARS = int(os.getenv("OHLCV_STORE_MAX_BARS", "500"))
_REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")


def _bars_to_df(bars: list[dict[str, Any]]) -> pd.DataFrame | None:
    """
    Convert a list of bar dicts to a DatetimeIndex OHLCV DataFrame.

    Accepts bars with either 'ts' (ISO string or epoch float) or
    'bar_open_ts' (epoch float) as the timestamp key.
    Returns None if the list is empty or conversion fails.
    """
    if not bars:
        return None
    try:
        rows = []
        for b in bars:
            ts_raw = b.get("ts") or b.get("bar_open_ts") or b.get("timestamp")
            if ts_raw is None:
                continue
            if isinstance(ts_raw, int | float):
                ts = datetime.fromtimestamp(float(ts_raw), tz=UTC)
            else:
                ts = pd.to_datetime(ts_raw, utc=True)
            rows.append(
                {
                    "ts": ts,
                    "open": float(b.get("open", b.get("o", 0.0))),
                    "high": float(b.get("high", b.get("h", 0.0))),
                    "low": float(b.get("low", b.get("l", 0.0))),
                    "close": float(b.get("close", b.get("c", 0.0))),
                    "volume": float(b.get("volume", b.get("v", 0.0))),
                }
            )
        if not rows:
            return None
        df = pd.DataFrame(rows).set_index("ts").sort_index()
        df = df[~df.index.duplicated(keep="last")]
        return df
    except Exception as exc:
        logger.debug("OHLCVStore._bars_to_df error: %s", exc)
        return None


class OHLCVStore:
    """
    DataFrame-returning OHLCV store backed by Redis + in-memory ring buffer.

    Thread-safe for concurrent reads.  push() is called from the tick
    aggregator (single writer) so no write lock is needed.
    """

    def __init__(self, timeframe: str = _TIMEFRAME, max_bars: int = _MAX_BARS) -> None:
        self._timeframe = timeframe
        self._max_bars = max_bars
        # Per-symbol in-memory ring buffers
        self._buffers: dict[str, deque[dict[str, Any]]] = {}
        # Redis cache (lazy-connected)
        self._cache = None
        self._redis_ok = False

    # ── Redis connection ──────────────────────────────────────────────────────

    def _get_cache(self):
        """Lazy-connect to Redis and return MarketDataCache, or None."""
        if self._cache is not None:
            return self._cache
        try:
            import redis as _redis_lib
            from market_data.redis_cache import MarketDataCache

            r = _redis_lib.from_url(
                _REDIS_URL,
                socket_connect_timeout=1,
                socket_timeout=1,
                decode_responses=False,
            )
            r.ping()
            self._cache = MarketDataCache(r)
            self._redis_ok = True
            logger.debug("OHLCVStore: Redis connected at %s", _REDIS_URL)
        except Exception as exc:
            logger.debug("OHLCVStore: Redis unavailable (%s) — using ring buffer", exc)
            self._cache = None
        return self._cache

    # ── Public API ────────────────────────────────────────────────────────────

    def get(self, symbol: str, bars: int = 150) -> pd.DataFrame | None:
        """
        Return the last ``bars`` closed OHLCV bars as a DataFrame.

        Tries Redis first, falls back to the in-memory ring buffer.
        Returns None when fewer than ``bars`` are available.
        """
        # Primary: Redis
        cache = self._get_cache()
        if cache is not None:
            try:
                raw = cache.get_bars(symbol, self._timeframe, n=bars)
                if raw and len(raw) >= bars:
                    df = _bars_to_df(raw[-bars:])
                    if df is not None and len(df) >= bars:
                        return df
            except Exception as exc:
                logger.debug("OHLCVStore: Redis get_bars failed: %s", exc)

        # Fallback: in-memory ring buffer
        buf = self._buffers.get(symbol)
        if buf is None or len(buf) < bars:
            return None
        raw_list = list(buf)[-bars:]
        return _bars_to_df(raw_list)

    def push(self, symbol: str, bar: dict[str, Any]) -> None:
        """
        Store a newly closed OHLCV bar.

        Writes to both Redis (if available) and the in-memory ring buffer.
        Called by the tick aggregator on every bar close.
        """
        # Ensure bar has a timestamp key
        if "bar_open_ts" not in bar and "ts" not in bar:
            bar = dict(bar)
            bar["bar_open_ts"] = datetime.now(UTC).timestamp()

        # In-memory ring buffer
        if symbol not in self._buffers:
            self._buffers[symbol] = deque(maxlen=self._max_bars)
        self._buffers[symbol].append(bar)

        # Redis
        cache = self._get_cache()
        if cache is not None:
            try:
                cache.store_bar(symbol, self._timeframe, bar)
            except Exception as exc:
                logger.debug("OHLCVStore: Redis store_bar failed: %s", exc)

    def buffer_size(self, symbol: str) -> int:
        """Return the number of bars currently in the ring buffer for symbol."""
        buf = self._buffers.get(symbol)
        return len(buf) if buf else 0

    def symbols(self) -> list[str]:
        """Return all symbols with in-memory bars."""
        return list(self._buffers.keys())

    def health(self) -> dict[str, Any]:
        return {
            "redis_ok": self._redis_ok,
            "timeframe": self._timeframe,
            "max_bars": self._max_bars,
            "symbols": {s: self.buffer_size(s) for s in self.symbols()},
        }


# ── Module-level singleton ────────────────────────────────────────────────────

_store: OHLCVStore | None = None


def get_ohlcv_store(
    timeframe: str = _TIMEFRAME,
    max_bars: int = _MAX_BARS,
) -> OHLCVStore:
    """Return the module-level OHLCVStore singleton."""
    global _store
    if _store is None:
        _store = OHLCVStore(timeframe=timeframe, max_bars=max_bars)
    return _store

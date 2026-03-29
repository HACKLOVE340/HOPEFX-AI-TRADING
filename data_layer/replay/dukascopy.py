# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
data_layer/replay/dukascopy.py
================================
DukascopyFetcher — downloads historical tick data from Dukascopy's
public bi5 (LZMA-compressed binary) tick data files.

Dukascopy provides free historical tick data for XAU/USD going back to 2003.
No API key required. Data is served as hourly bi5 files.

URL pattern:
  https://datafeed.dukascopy.com/datafeed/{INSTRUMENT}/{YYYY}/{MM:02d}/{DD:02d}/{HH:02d}h_ticks.bi5

bi5 format (per tick, big-endian):
  - 4 bytes: milliseconds from hour start (uint32)
  - 4 bytes: ask price × 100000 (uint32)
  - 4 bytes: bid price × 100000 (uint32)
  - 4 bytes: ask volume (float32)
  - 4 bytes: bid volume (float32)
  Total: 20 bytes per tick

Instrument code for XAU/USD: XAUUSD

Usage:
    fetcher = DukascopyFetcher()
    ticks = await fetcher.fetch_ticks(
        symbol="XAUUSD",
        start=datetime(2024, 1, 1, tzinfo=timezone.utc),
        end=datetime(2024, 1, 2, tzinfo=timezone.utc),
    )
    # ticks: List[GoldTick] sorted by timestamp ascending
"""
from __future__ import annotations

import asyncio
import io
import logging
import lzma
import os
import struct
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import AsyncIterator, List, Optional, Tuple

import aiohttp

from data_layer.types import FeedSource, GoldTick

logger = logging.getLogger(__name__)

_BASE_URL   = "https://datafeed.dukascopy.com/datafeed"
_CACHE_DIR  = Path(os.getenv("DUKASCOPY_CACHE_DIR", "data/dukascopy_cache"))
_HTTP_TIMEOUT = aiohttp.ClientTimeout(total=30.0)

# XAU/USD price divisor (Dukascopy stores price × 100000 for 5 decimal places)
_PRICE_DIVISOR: dict = {
    "XAUUSD": 100.0,   # XAU/USD is quoted to 2 decimal places
}


class DukascopyFetcher:
    """
    Downloads and parses Dukascopy bi5 tick data files.

    Files are cached locally to avoid re-downloading.
    Cache path: data/dukascopy_cache/{instrument}/{YYYY}/{MM}/{DD}/{HH}.bi5
    """

    def __init__(self) -> None:
        self._session: Optional[aiohttp.ClientSession] = None
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(timeout=_HTTP_TIMEOUT)
        return self._session

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()

    # ── Public API ────────────────────────────────────────────────────────────

    async def fetch_ticks(
        self,
        symbol: str = "XAUUSD",
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
        max_ticks: int = 1_000_000,
    ) -> List[GoldTick]:
        """
        Fetch historical ticks for the given date range.

        Returns List[GoldTick] sorted by timestamp ascending.
        Ticks are tagged with FeedSource.REPLAY.
        """
        if start is None:
            start = datetime.now(timezone.utc) - timedelta(days=1)
        if end is None:
            end = datetime.now(timezone.utc)

        # Ensure UTC
        if start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
        if end.tzinfo is None:
            end = end.replace(tzinfo=timezone.utc)

        all_ticks: List[GoldTick] = []
        divisor = _PRICE_DIVISOR.get(symbol.upper(), 100.0)

        # Iterate hour by hour
        current = start.replace(minute=0, second=0, microsecond=0)
        while current < end:
            if len(all_ticks) >= max_ticks:
                break
            try:
                hour_ticks = await self._fetch_hour(symbol, current, divisor)
                # Filter to exact range
                hour_ticks = [
                    t for t in hour_ticks
                    if start <= t.timestamp <= end
                ]
                all_ticks.extend(hour_ticks)
            except Exception as exc:
                logger.debug(
                    "Dukascopy fetch error %s %s: %s",
                    symbol, current.strftime("%Y-%m-%d %H:00"), exc,
                )
            current += timedelta(hours=1)

        logger.info(
            "DukascopyFetcher: fetched %d ticks for %s [%s → %s]",
            len(all_ticks), symbol,
            start.strftime("%Y-%m-%d %H:%M"),
            end.strftime("%Y-%m-%d %H:%M"),
        )
        return all_ticks[:max_ticks]

    async def fetch_ohlcv(
        self,
        symbol: str = "XAUUSD",
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
        timeframe_minutes: int = 60,
    ) -> List[dict]:
        """
        Aggregate tick data into OHLCV bars.

        Returns list of dicts with keys: open_time, open, high, low, close, volume, tick_count.
        """
        ticks = await self.fetch_ticks(symbol, start, end)
        if not ticks:
            return []

        bars: List[dict] = []
        bar_start = ticks[0].timestamp.replace(second=0, microsecond=0)
        bar_start = bar_start.replace(
            minute=(bar_start.minute // timeframe_minutes) * timeframe_minutes
        )
        bar_end = bar_start + timedelta(minutes=timeframe_minutes)

        o = h = l = c = 0.0
        vol = 0.0
        count = 0

        for tick in ticks:
            if tick.timestamp >= bar_end:
                if count > 0:
                    bars.append({
                        "open_time":  bar_start.isoformat(),
                        "close_time": bar_end.isoformat(),
                        "open_epoch": bar_start.timestamp(),
                        "open":  round(o, 4),
                        "high":  round(h, 4),
                        "low":   round(l, 4),
                        "close": round(c, 4),
                        "volume": round(vol, 2),
                        "tick_count": count,
                        "symbol": symbol,
                        "timeframe": f"{timeframe_minutes}m",
                    })
                # Advance bar
                while tick.timestamp >= bar_end:
                    bar_start = bar_end
                    bar_end   = bar_start + timedelta(minutes=timeframe_minutes)
                o = h = l = c = tick.mid
                vol = 0.0
                count = 0

            if count == 0:
                o = tick.mid
                h = tick.mid
                l = tick.mid
            else:
                h = max(h, tick.mid)
                l = min(l, tick.mid)
            c   = tick.mid
            vol += tick.spread * 1000   # proxy volume
            count += 1

        # Final bar
        if count > 0:
            bars.append({
                "open_time":  bar_start.isoformat(),
                "close_time": bar_end.isoformat(),
                "open_epoch": bar_start.timestamp(),
                "open":  round(o, 4),
                "high":  round(h, 4),
                "low":   round(l, 4),
                "close": round(c, 4),
                "volume": round(vol, 2),
                "tick_count": count,
                "symbol": symbol,
                "timeframe": f"{timeframe_minutes}m",
            })

        return bars

    # ── Internal ──────────────────────────────────────────────────────────────

    async def _fetch_hour(
        self, symbol: str, hour: datetime, divisor: float
    ) -> List[GoldTick]:
        """Fetch and parse one hour of bi5 tick data."""
        # Check local cache first
        cached = self._load_cache(symbol, hour)
        if cached is not None:
            return self._parse_bi5(cached, hour, divisor)

        # Download
        url = self._build_url(symbol, hour)
        session = await self._get_session()

        try:
            async with session.get(url) as resp:
                if resp.status == 404:
                    # No data for this hour (weekend, holiday)
                    self._save_cache(symbol, hour, b"")
                    return []
                resp.raise_for_status()
                data = await resp.read()
        except Exception as exc:
            raise RuntimeError(f"Dukascopy download failed {url}: {exc}") from exc

        self._save_cache(symbol, hour, data)
        return self._parse_bi5(data, hour, divisor)

    def _build_url(self, symbol: str, hour: datetime) -> str:
        return (
            f"{_BASE_URL}/{symbol.upper()}/"
            f"{hour.year}/{hour.month - 1:02d}/{hour.day:02d}/"
            f"{hour.hour:02d}h_ticks.bi5"
        )

    def _parse_bi5(
        self, data: bytes, hour: datetime, divisor: float
    ) -> List[GoldTick]:
        """Parse LZMA-compressed bi5 binary tick data."""
        if not data:
            return []

        try:
            raw = lzma.decompress(data)
        except lzma.LZMAError:
            return []

        ticks: List[GoldTick] = []
        tick_size = 20
        n_ticks   = len(raw) // tick_size
        hour_epoch = hour.timestamp()

        import uuid
        for i in range(n_ticks):
            offset = i * tick_size
            chunk  = raw[offset: offset + tick_size]
            if len(chunk) < tick_size:
                break

            ms_from_hour, ask_raw, bid_raw, ask_vol, bid_vol = struct.unpack(
                ">IIIff", chunk
            )

            ask = ask_raw / divisor
            bid = bid_raw / divisor
            mid = (ask + bid) / 2.0

            if ask <= 0 or bid <= 0 or bid > ask:
                continue

            ts_epoch = hour_epoch + ms_from_hour / 1000.0
            ts = datetime.fromtimestamp(ts_epoch, tz=timezone.utc)

            ticks.append(GoldTick(
                symbol     = "XAU_USD",
                timestamp  = ts,
                bid        = round(bid, 4),
                ask        = round(ask, 4),
                mid        = round(mid, 4),
                source     = FeedSource.REPLAY,
                spread     = round(ask - bid, 4),
                lineage_id = str(uuid.uuid4()),
                raw        = {
                    "ask_vol": float(ask_vol),
                    "bid_vol": float(bid_vol),
                    "ms_from_hour": ms_from_hour,
                },
            ))

        return ticks

    def _cache_path(self, symbol: str, hour: datetime) -> Path:
        return (
            _CACHE_DIR
            / symbol.upper()
            / str(hour.year)
            / f"{hour.month:02d}"
            / f"{hour.day:02d}"
            / f"{hour.hour:02d}.bi5"
        )

    def _load_cache(self, symbol: str, hour: datetime) -> Optional[bytes]:
        path = self._cache_path(symbol, hour)
        if path.exists():
            return path.read_bytes()
        return None

    def _save_cache(self, symbol: str, hour: datetime, data: bytes) -> None:
        path = self._cache_path(symbol, hour)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)


# Module-level singleton
dukascopy_fetcher = DukascopyFetcher()

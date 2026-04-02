# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
data_layer/replay/dukascopy.py
================================
DukascopyFetcher — downloads and decodes Dukascopy historical tick data.

Dukascopy stores tick data in bi5 (LZMA-compressed binary) files.
URL format: https://datafeed.dukascopy.com/datafeed/{SYMBOL}/{YYYY}/{MM}/{DD}/{HH}h_ticks.bi5

Binary record format (20 bytes per tick):
  - 4 bytes: milliseconds from hour start (big-endian uint32)
  - 4 bytes: ask price × 100000 (big-endian uint32)
  - 4 bytes: bid price × 100000 (big-endian uint32)
  - 4 bytes: ask volume × 1000000 (big-endian float32)
  - 4 bytes: bid volume × 1000000 (big-endian float32)

Note: Dukascopy months are 0-indexed (January = 0).

Supported symbols: XAUUSD, EURUSD, GBPUSD, USDJPY, etc.
"""

from __future__ import annotations

import asyncio
import logging
import lzma
import os
import struct
from datetime import datetime, timedelta, timezone

UTC = timezone.utc
from pathlib import Path

import aiohttp
import pandas as pd

logger = logging.getLogger(__name__)

_BASE_URL = "https://datafeed.dukascopy.com/datafeed"
_CACHE_DIR = Path(os.getenv("DUKASCOPY_CACHE_DIR", "data/dukascopy_cache"))
_HTTP_TIMEOUT = aiohttp.ClientTimeout(total=30.0, connect=10.0)
_TICK_STRUCT = struct.Struct(">IIIff")  # big-endian: uint32, uint32, uint32, float32, float32
_TICK_SIZE = _TICK_STRUCT.size  # 20 bytes
_PRICE_FACTOR = 100_000.0  # Dukascopy stores price × 100000

# Timeframe string → minutes mapping.
# Accepts broker-style strings (H1, M5, D1), ISO-style (1h, 5m, 1d),
# and plain integers as strings ("60", "5").
_TF_ALIASES: dict = {
    # Minutes
    "M1": 1,
    "1m": 1,
    "1min": 1,
    "1": 1,
    "M5": 5,
    "5m": 5,
    "5min": 5,
    "5": 5,
    "M15": 15,
    "15m": 15,
    "15min": 15,
    "15": 15,
    "M30": 30,
    "30m": 30,
    "30min": 30,
    "30": 30,
    # Hours
    "H1": 60,
    "1h": 60,
    "1H": 60,
    "60": 60,
    "60min": 60,
    "H4": 240,
    "4h": 240,
    "4H": 240,
    "240": 240,
    # Daily
    "D1": 1440,
    "1d": 1440,
    "1D": 1440,
    "daily": 1440,
    "1440": 1440,
}


def _parse_timeframe(tf) -> int:
    """
    Convert a timeframe specifier to minutes.

    Accepts:
      - int  → returned as-is
      - str  → looked up in _TF_ALIASES, then tried as plain int
    Raises ValueError for unrecognised strings.
    """
    if isinstance(tf, int):
        return tf
    s = str(tf).strip()
    if s in _TF_ALIASES:
        return _TF_ALIASES[s]
    try:
        return int(s)
    except ValueError:
        raise ValueError(
            f"DukascopyFetcher: unrecognised timeframe '{tf}'. Use minutes (int) or one of: {sorted(_TF_ALIASES)}"
        ) from None


class DukascopyFetcher:
    """
    Downloads and decodes Dukascopy bi5 tick data.

    Features:
    - Disk cache: downloaded files cached in DUKASCOPY_CACHE_DIR
    - Concurrent hourly downloads for fast range fetches
    - Automatic LZMA decompression
    - Correct 0-indexed month handling
    - Returns pd.DataFrame with columns: timestamp, bid, ask, bid_vol, ask_vol
    """

    def __init__(self) -> None:
        self._session: aiohttp.ClientSession | None = None
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            connector = aiohttp.TCPConnector(limit=20, ttl_dns_cache=300)
            self._session = aiohttp.ClientSession(timeout=_HTTP_TIMEOUT, connector=connector)
        return self._session

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()

    # ── URL construction ──────────────────────────────────────────────────────

    @staticmethod
    def _build_url(symbol: str, dt: datetime) -> str:
        """
        Build Dukascopy URL for a specific hour.

        Month is 0-indexed: January=00, December=11.
        """
        y = dt.year
        m = dt.month - 1  # 0-indexed!
        d = dt.day
        h = dt.hour
        return f"{_BASE_URL}/{symbol.upper()}/{y:04d}/{m:02d}/{d:02d}/{h:02d}h_ticks.bi5"

    # ── Cache ─────────────────────────────────────────────────────────────────

    def _cache_path(self, symbol: str, hour: datetime) -> Path:
        return (
            _CACHE_DIR
            / symbol.upper()
            / f"{hour.year:04d}"
            / f"{hour.month:02d}"
            / f"{hour.day:02d}"
            / f"{hour.hour:02d}h_ticks.bi5"
        )

    def _load_cache(self, symbol: str, hour: datetime) -> bytes | None:
        path = self._cache_path(symbol, hour)
        if path.exists():
            return path.read_bytes()
        return None

    def _save_cache(self, symbol: str, hour: datetime, data: bytes) -> None:
        path = self._cache_path(symbol, hour)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    # ── Download ──────────────────────────────────────────────────────────────

    async def _fetch_hour(self, symbol: str, hour: datetime) -> bytes | None:
        """Download one hour of bi5 data. Returns raw compressed bytes or None."""
        # Check cache first
        cached = self._load_cache(symbol, hour)
        if cached is not None:
            return cached

        url = self._build_url(symbol, hour)
        session = await self._get_session()

        try:
            async with session.get(url) as resp:
                if resp.status == 404:
                    # No data for this hour (weekend, holiday) — cache empty marker
                    self._save_cache(symbol, hour, b"")
                    return None
                resp.raise_for_status()
                data = await resp.read()
                if data:
                    self._save_cache(symbol, hour, data)
                return data if data else None
        except TimeoutError:
            logger.warning("Dukascopy timeout: %s", url)
            return None
        except Exception as exc:
            logger.warning("Dukascopy fetch error %s: %s", url, exc)
            return None

    # ── Decoding ──────────────────────────────────────────────────────────────

    @staticmethod
    def _decode_bi5(data: bytes, hour: datetime) -> pd.DataFrame:
        """
        Decode a bi5 binary blob into a tick DataFrame.

        Returns DataFrame with columns: timestamp (UTC), bid, ask, bid_vol, ask_vol
        """
        if not data:
            return pd.DataFrame(columns=["timestamp", "bid", "ask", "bid_vol", "ask_vol"])

        try:
            raw = lzma.decompress(data)
        except lzma.LZMAError as exc:
            logger.warning("Dukascopy LZMA decode error: %s", exc)
            return pd.DataFrame(columns=["timestamp", "bid", "ask", "bid_vol", "ask_vol"])

        n_ticks = len(raw) // _TICK_SIZE
        if n_ticks == 0:
            return pd.DataFrame(columns=["timestamp", "bid", "ask", "bid_vol", "ask_vol"])

        records = []
        hour_epoch_ms = int(hour.timestamp() * 1000)

        for i in range(n_ticks):
            offset = i * _TICK_SIZE
            chunk = raw[offset : offset + _TICK_SIZE]
            if len(chunk) < _TICK_SIZE:
                break
            ms_from_hour, ask_raw, bid_raw, ask_vol, bid_vol = _TICK_STRUCT.unpack(chunk)
            ts_ms = hour_epoch_ms + ms_from_hour
            ask = ask_raw / _PRICE_FACTOR
            bid = bid_raw / _PRICE_FACTOR
            records.append((ts_ms, bid, ask, float(bid_vol), float(ask_vol)))

        if not records:
            return pd.DataFrame(columns=["timestamp", "bid", "ask", "bid_vol", "ask_vol"])

        df = pd.DataFrame(records, columns=["ts_ms", "bid", "ask", "bid_vol", "ask_vol"])
        df["timestamp"] = pd.to_datetime(df["ts_ms"], unit="ms", utc=True)
        df = df.drop(columns=["ts_ms"])
        df["mid"] = (df["bid"] + df["ask"]) / 2.0  # pylint: disable=unsubscriptable-object,unsupported-assignment-operation
        return df.set_index("timestamp").sort_index()

    # ── Public API ────────────────────────────────────────────────────────────

    async def fetch_ticks(
        self,
        symbol: str,
        start: datetime,
        end: datetime,
        max_concurrent: int = 8,
    ) -> pd.DataFrame:
        """
        Fetch tick data for a date range.

        Returns DataFrame with columns: bid, ask, mid, bid_vol, ask_vol
        and UTC DatetimeIndex.
        """
        # Enumerate all hours in range
        hours: list[datetime] = []
        cur = start.replace(minute=0, second=0, microsecond=0, tzinfo=UTC)
        end_utc = end.replace(tzinfo=UTC) if end.tzinfo is None else end

        while cur <= end_utc:
            hours.append(cur)
            cur += timedelta(hours=1)

        if not hours:
            return pd.DataFrame()

        # Fetch concurrently in batches
        semaphore = asyncio.Semaphore(max_concurrent)

        async def _fetch_with_sem(h: datetime) -> pd.DataFrame | None:
            async with semaphore:
                data = await self._fetch_hour(symbol, h)
                if data:
                    return self._decode_bi5(data, h)
                return None

        tasks = [_fetch_with_sem(h) for h in hours]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        frames = []
        for r in results:
            if isinstance(r, pd.DataFrame) and not r.empty:
                frames.append(r)

        if not frames:
            return pd.DataFrame()

        combined = pd.concat(frames).sort_index()
        # Filter to exact range
        combined = combined[
            (combined.index >= pd.Timestamp(start, tz="UTC")) & (combined.index <= pd.Timestamp(end, tz="UTC"))
        ]
        return combined

    async def fetch_ohlcv(
        self,
        symbol: str,
        start: datetime,
        end: datetime,
        timeframe_minutes=60,
    ) -> pd.DataFrame:
        """
        Fetch and aggregate tick data into OHLCV bars.

        Parameters
        ----------
        timeframe_minutes : int or str — bar size. Accepts integers (minutes)
            or broker-style strings: "H1", "M5", "D1", "1h", "5m", etc.

        Returns DataFrame with columns: open, high, low, close, volume
        and UTC DatetimeIndex (bar open time).
        """
        tf_min = _parse_timeframe(timeframe_minutes)
        ticks = await self.fetch_ticks(symbol, start, end)
        if ticks.empty:
            return pd.DataFrame()

        freq = f"{tf_min}min"
        mid = ticks["mid"] if "mid" in ticks.columns else (ticks["bid"] + ticks["ask"]) / 2

        ohlcv = mid.resample(freq).agg(
            open="first",
            high="max",
            low="min",
            close="last",
        )

        # Volume: sum of bid_vol + ask_vol
        if "bid_vol" in ticks.columns and "ask_vol" in ticks.columns:
            vol = (ticks["bid_vol"] + ticks["ask_vol"]).resample(freq).sum()
            ohlcv["volume"] = vol
        else:
            ohlcv["volume"] = 0.0

        ohlcv = ohlcv.dropna(subset=["open", "close"])
        return ohlcv


# Module-level singleton
dukascopy_fetcher = DukascopyFetcher()

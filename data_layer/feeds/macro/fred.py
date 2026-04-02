# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
data_layer/feeds/macro/fred.py
================================
FRED (Federal Reserve Economic Data) adapter.

Fetches the macro series that most directly drive gold prices:
  - DXY proxy (DTWEXBGS)   — Trade-weighted USD index
  - US 10Y yield (DGS10)   — Real yield proxy
  - US 2Y yield  (DGS2)    — Short-end rate
  - CPI (CPIAUCNS)         — Inflation
  - PCE (PCEPI)            — Fed's preferred inflation gauge
  - VIX (VIXCLS)           — Risk-off proxy
  - Real 10Y yield (DFII10)— TIPS yield (most direct gold driver)
  - Fed Funds Rate (FEDFUNDS)
  - M2 Money Supply (M2SL) — Monetary expansion proxy

Free tier: 120 req/day without key, 500 req/day with free key.
Get a free key at: https://fred.stlouisfed.org/docs/api/api_key.html
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone

UTC = timezone.utc

import aiohttp
import pandas as pd

logger = logging.getLogger(__name__)

_FRED_BASE = "https://api.stlouisfed.org/fred/series/observations"
_FRED_KEY = os.getenv("FRED_API_KEY", "")

# Series definitions: (series_id, human_name, gold_impact_direction)
# gold_impact_direction: +1 = rising value is bullish for gold, -1 = bearish
FRED_SERIES: dict[str, tuple[str, int]] = {
    "dxy": ("DTWEXBGS", -1),  # strong dollar → bearish gold
    "us10y": ("DGS10", -1),  # rising yields → bearish gold
    "us2y": ("DGS2", -1),
    "real10y": ("DFII10", -1),  # TIPS yield — strongest gold driver
    "cpi": ("CPIAUCNS", +1),  # inflation → bullish gold
    "pce": ("PCEPI", +1),
    "vix": ("VIXCLS", +1),  # fear → bullish gold
    "fed_funds": ("FEDFUNDS", -1),
    "m2": ("M2SL", +1),  # money supply → bullish gold
}

_HTTP_TIMEOUT = aiohttp.ClientTimeout(total=15.0)


class FREDFeed:
    """
    Async FRED data fetcher.

    Fetches the last N observations for each series and returns
    a dict of {series_name: pd.Series(float, DatetimeIndex)}.
    """

    def __init__(self) -> None:
        self._session: aiohttp.ClientSession | None = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(timeout=_HTTP_TIMEOUT)
        return self._session

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()

    async def fetch_series(
        self,
        series_id: str,
        observation_start: str | None = None,
        limit: int = 500,
    ) -> pd.Series:
        """
        Fetch a single FRED series.

        Returns pd.Series(float, DatetimeIndex[UTC]).
        Returns empty Series on error.
        """
        if not observation_start:
            start = (datetime.now(UTC) - timedelta(days=365 * 5)).strftime("%Y-%m-%d")
        else:
            start = observation_start

        # FRED requires an API key for all requests since 2024.
        # Without a key every request returns HTTP 400.
        if not _FRED_KEY:
            logger.debug("FRED fetch_series %s skipped — FRED_API_KEY not set", series_id)
            return pd.Series(dtype=float)

        params = {
            "series_id": series_id,
            "observation_start": start,
            "file_type": "json",
            "sort_order": "asc",
            "limit": limit,
            "api_key": _FRED_KEY,
        }

        try:
            session = await self._get_session()
            async with session.get(_FRED_BASE, params=params) as resp:
                resp.raise_for_status()
                data = await resp.json()

            observations = data.get("observations", [])
            records = []
            for obs in observations:
                val = obs.get("value", ".")
                if val == ".":
                    continue
                try:
                    records.append(
                        (
                            pd.Timestamp(obs["date"], tz="UTC"),
                            float(val),
                        )
                    )
                except (ValueError, KeyError):
                    continue

            if not records:
                return pd.Series(dtype=float)

            idx, vals = zip(*records, strict=False)
            return pd.Series(vals, index=pd.DatetimeIndex(idx), dtype=float)

        except Exception as exc:
            logger.warning("FRED fetch_series %s error: %s", series_id, exc)
            return pd.Series(dtype=float)

    async def fetch_all(self, observation_start: str | None = None) -> dict[str, pd.Series]:
        """
        Fetch all configured FRED series concurrently.

        Returns {series_name: pd.Series}.
        """
        tasks = {
            name: asyncio.create_task(self.fetch_series(series_id, observation_start))
            for name, (series_id, _) in FRED_SERIES.items()
        }
        results: dict[str, pd.Series] = {}
        for name, task in tasks.items():
            try:
                results[name] = await task
                logger.debug("FRED %s: %d observations", name, len(results[name]))
            except Exception as exc:
                logger.warning("FRED %s failed: %s", name, exc)
                results[name] = pd.Series(dtype=float)

        return results

    async def fetch_latest_values(self) -> dict[str, float | None]:
        """
        Return the most recent value for each series.

        Used for real-time macro snapshot injection.
        """
        all_series = await self.fetch_all(
            observation_start=(datetime.now(UTC) - timedelta(days=30)).strftime("%Y-%m-%d")
        )
        return {name: float(series.iloc[-1]) if not series.empty else None for name, series in all_series.items()}


# Module-level singleton
fred_feed = FREDFeed()

# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
data_layer/feeds/macro/baltic_dry.py
======================================
Baltic Dry Index (BDI) via FRED series BDIY.

The Baltic Dry Index measures global shipping demand and serves as a
leading indicator for industrial commodity demand and global trade.
Rising BDI correlates with reflation / risk-on environments.

Produces:
  - baltic_dry_idx    — BDI level
  - baltic_dry_chg    — Daily change
  - baltic_dry_z52    — 52-week z-score (standardized)
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone

UTC = timezone.utc

import aiohttp
import pandas as pd

logger = logging.getLogger(__name__)

_FRED_BASE = "https://api.stlouisfed.org/fred/series/observations"
_FRED_KEY = os.getenv("FRED_API_KEY", "")
_BDI_SERIES = "BDIY"  # Baltic Dry Index on FRED
_HTTP_TIMEOUT = aiohttp.ClientTimeout(total=15.0)


class BalticDryFeed:
    """
    Fetches Baltic Dry Index from FRED (BDIY series).

    Requires FRED_API_KEY environment variable.
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

    async def fetch_bdi_raw(self, lookback_years: int = 10) -> pd.Series:
        """Fetch BDI from FRED. Returns pd.Series(float, DatetimeIndex[UTC])."""
        if not _FRED_KEY:
            logger.warning(
                "Baltic Dry: FRED_API_KEY not set — skipping BDI fetch"
            )
            return pd.Series(dtype=float)

        start = (datetime.now(UTC) - timedelta(days=lookback_years * 365)).strftime(
            "%Y-%m-%d"
        )
        params = {
            "series_id": _BDI_SERIES,
            "observation_start": start,
            "file_type": "json",
            "sort_order": "asc",
            "limit": 5000,
            "api_key": _FRED_KEY,
        }
        try:
            session = await self._get_session()
            async with session.get(_FRED_BASE, params=params) as resp:
                resp.raise_for_status()
                data = await resp.json()
        except Exception as exc:
            logger.warning("Baltic Dry: FRED fetch error: %s", exc)
            return pd.Series(dtype=float)

        records = []
        for obs in data.get("observations", []):
            val = obs.get("value", ".")
            if val == ".":
                continue
            try:
                records.append((
                    pd.Timestamp(obs["date"], tz="UTC"),
                    float(val),
                ))
            except (ValueError, KeyError):
                continue

        if not records:
            return pd.Series(dtype=float)

        idx, vals = zip(*records, strict=False)
        return pd.Series(vals, index=pd.DatetimeIndex(idx), dtype=float)

    async def fetch_series(self) -> dict[str, pd.Series]:
        """Return BDI-derived series for MacroStore injection."""
        bdi = await self.fetch_bdi_raw()
        if bdi.empty:
            return {}

        result: dict[str, pd.Series] = {"baltic_dry_idx": bdi}

        # Daily change
        result["baltic_dry_chg"] = bdi.diff().dropna()

        # 52-week z-score (rolling 252 trading days approx)
        roll = bdi.rolling(window=252, min_periods=52)
        std = roll.std().replace(0, float("nan"))
        result["baltic_dry_z52"] = ((bdi - roll.mean()) / std).dropna()

        logger.info("Baltic Dry: fetched %d observations", len(bdi))
        return result

    async def inject_into_macro_store(self) -> int:
        """Inject BDI series into MacroStore. Returns count injected."""
        from ml.macro_store import macro_store  # noqa: PLC0415
        series = await self.fetch_series()
        count = 0
        for name, s in series.items():
            if not s.empty:
                macro_store._series[name] = s
                count += 1
        if count:
            logger.info("Baltic Dry: injected %d series", count)
        return count


baltic_dry_feed = BalticDryFeed()

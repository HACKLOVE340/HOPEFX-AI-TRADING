# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
"""
data_layer/feeds/macro/imf_gold.py
=====================================
IMF International Financial Statistics — central bank gold reserves.

Data source
-----------
IMF IFS API (free, no key required):
  https://dataservices.imf.org/REST/SDMX_JSON.svc/

Series used
-----------
  FAGOLD_USD  — Official gold holdings (USD value, monthly)
  FAGOLD      — Official gold holdings (fine troy ounces, monthly)

These are world-aggregate totals across all IMF-reporting central banks.
Rising CB gold reserves → structural bullish demand for gold.

Series injected into MacroStore
--------------------------------
  imf_cb_gold_tonnes   : World CB gold holdings in metric tonnes (monthly)
  imf_cb_gold_chg_qoq  : Quarter-over-quarter change in tonnes (momentum signal)

Gold signal logic
-----------------
  imf_cb_gold_chg_qoq > 0  → central banks net buyers → bullish
  imf_cb_gold_chg_qoq < 0  → central banks net sellers → bearish
  Sustained buying (3+ quarters) → strong structural support

Integration
-----------
Injected into ml.macro_store on startup and refreshed monthly.
Persisted to data/macro/imf_cb_gold_*.csv for offline fallback.

Usage
-----
    from data_layer.feeds.macro.imf_gold import imf_gold_feed
    await imf_gold_feed.fetch_and_inject()
    await imf_gold_feed.start()
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

import aiohttp
import pandas as pd

logger = logging.getLogger(__name__)

UTC = timezone.utc

# IMF SDMX JSON API — no key required
_IMF_BASE = "https://dataservices.imf.org/REST/SDMX_JSON.svc/CompactData"

# IFS dataset, world aggregate gold holdings in troy ounces
# Frequency M = monthly, Area W00 = world, indicator FAGOLD
_IMF_GOLD_OZ_URL = f"{_IMF_BASE}/IFS/M.W00.FAGOLD"

# Troy ounces → metric tonnes conversion
_OZ_PER_TONNE = 32_150.7

# Local cache
_CACHE_DIR = Path(os.getenv("IMF_CACHE_DIR", "data/macro"))
_CACHE_DIR.mkdir(parents=True, exist_ok=True)

# Years of history to fetch on first run
_HISTORY_YEARS = int(os.getenv("IMF_HISTORY_YEARS", "10"))

_HTTP_TIMEOUT = aiohttp.ClientTimeout(total=30.0)


class IMFGoldFeed:
    """
    Fetches IMF IFS world central bank gold reserve data.

    Converts troy ounces → metric tonnes and computes QoQ change.
    Injects results into ml.macro_store for use as ML features.
    """

    def __init__(self) -> None:
        self._session: aiohttp.ClientSession | None = None
        self._running = False
        self._last_fetch: datetime | None = None
        self._task: asyncio.Task | None = None
        # Suppress repeated offline warnings — log once per provider lifetime
        self._offline_warned: bool = False

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(timeout=_HTTP_TIMEOUT)
        return self._session

    async def close(self) -> None:
        self._running = False
        if self._session and not self._session.closed:
            await self._session.close()

    # ── Download ──────────────────────────────────────────────────────────────

    async def _fetch_raw(self, start_year: int) -> pd.Series:
        """
        Fetch world CB gold holdings from IMF IFS API.

        Returns pd.Series(float, DatetimeIndex[UTC]) in metric tonnes.
        """
        start_period = f"{start_year}-01"
        url = f"{_IMF_GOLD_OZ_URL}?startPeriod={start_period}"

        try:
            session = await self._get_session()
            async with session.get(url, headers={"Accept": "application/json"}) as resp:
                if resp.status != 200:
                    logger.warning("IMF gold API returned HTTP %d", resp.status)
                    return pd.Series(dtype=float)
                data = await resp.json(content_type=None)

            # Navigate SDMX-JSON structure
            # CompactData → DataSet → Series → Obs
            dataset = data.get("CompactData", {}).get("DataSet", {})
            series_data = dataset.get("Series", {})

            # Handle both dict (single series) and list (multiple)
            if isinstance(series_data, dict):
                obs_list = series_data.get("Obs", [])
            elif isinstance(series_data, list) and series_data:
                obs_list = series_data[0].get("Obs", [])
            else:
                logger.warning("IMF: unexpected DataSet structure")
                return pd.Series(dtype=float)

            if isinstance(obs_list, dict):
                obs_list = [obs_list]

            records: list[tuple[pd.Timestamp, float]] = []
            for obs in obs_list:
                period = obs.get("@TIME_PERIOD", "")
                value = obs.get("@OBS_VALUE", "")
                if not period or not value:
                    continue
                try:
                    # Monthly period: "2024-03" → end of month timestamp
                    ts = pd.Timestamp(period + "-01", tz="UTC") + pd.offsets.MonthEnd(0)
                    oz = float(value)
                    tonnes = oz / _OZ_PER_TONNE
                    records.append((ts, tonnes))
                except (ValueError, TypeError):
                    continue

            if not records:
                logger.warning("IMF: no observations parsed from response")
                return pd.Series(dtype=float)

            idx, vals = zip(*records, strict=False)
            series = pd.Series(vals, index=pd.DatetimeIndex(idx), dtype=float)
            series = series.sort_index()
            logger.info(
                "IMF: fetched %d monthly CB gold observations (latest: %.0f t on %s)",
                len(series),
                float(series.iloc[-1]),
                series.index[-1].date().isoformat(),
            )
            return series

        except Exception as exc:
            logger.debug("IMF gold fetch error: %s", exc)
            return pd.Series(dtype=float)

    # ── Compute derived series ────────────────────────────────────────────────

    def _compute_series(self, tonnes: pd.Series) -> dict[str, pd.Series]:
        """Compute CB gold holdings and QoQ change series."""
        if tonnes.empty:
            return {}

        # Quarter-over-quarter change (3-month shift on monthly data)
        qoq = tonnes.diff(3).fillna(0.0)

        return {
            "imf_cb_gold_tonnes": tonnes,
            "imf_cb_gold_chg_qoq": qoq,
        }

    # ── Inject & persist ──────────────────────────────────────────────────────

    def _inject_into_macro_store(self, series_dict: dict[str, pd.Series]) -> None:
        try:
            from ml.macro_store import macro_store

            for name, series in series_dict.items():
                if series.empty:
                    continue
                macro_store._series[name] = series.sort_index()
                logger.info(
                    "IMF: injected %s into MacroStore (%d obs, latest=%.1f on %s)",
                    name,
                    len(series),
                    float(series.iloc[-1]),
                    series.index[-1].date().isoformat(),
                )
        except Exception as exc:
            logger.warning("IMF: MacroStore injection failed: %s", exc)

    def _save_csv(self, series_dict: dict[str, pd.Series]) -> None:
        for name, series in series_dict.items():
            if series.empty:
                continue
            path = _CACHE_DIR / f"{name}.csv"
            try:
                df = series.reset_index()
                df.columns = ["date", "value"]
                df["date"] = df["date"].dt.strftime("%Y-%m-%d")
                df.to_csv(path, index=False)
                logger.debug("IMF: saved %s → %s", name, path)
            except Exception as exc:
                logger.warning("IMF: CSV save failed for %s: %s", name, exc)

    # ── Public API ────────────────────────────────────────────────────────────

    async def fetch_and_inject(self, years: int | None = None) -> dict[str, int]:
        """
        Fetch IMF CB gold data, compute series, inject into MacroStore.

        Returns dict mapping series name → number of observations.
        """
        n_years = years or _HISTORY_YEARS
        start_year = datetime.now(UTC).year - n_years

        tonnes = await self._fetch_raw(start_year)
        if tonnes.empty:
            # Fallback: try loading from CSV cache
            csv_path = _CACHE_DIR / "imf_cb_gold_tonnes.csv"
            if csv_path.exists():
                try:
                    df = pd.read_csv(csv_path, parse_dates=["date"])
                    df["date"] = pd.to_datetime(df["date"], utc=True)
                    tonnes = df.set_index("date")["value"].sort_index()
                    logger.info("IMF: loaded %d rows from CSV fallback", len(tonnes))
                except Exception as exc:
                    logger.warning("IMF: CSV fallback failed: %s", exc)

        if tonnes.empty:
            if not self._offline_warned:
                logger.warning(
                    "IMF: no data available — dataservices.imf.org unreachable and no local cache. "
                    "MacroStore not updated. Ensure outbound HTTPS access to dataservices.imf.org."
                )
                self._offline_warned = True
            return {}

        series_dict = self._compute_series(tonnes)
        self._inject_into_macro_store(series_dict)
        self._save_csv(series_dict)
        self._last_fetch = datetime.now(UTC)

        return {name: len(s) for name, s in series_dict.items()}

    async def start(self) -> None:
        """
        Fetch IMF data immediately then refresh monthly on the 5th at 06:00 UTC
        (IMF typically publishes updated IFS data in the first week of each month).
        """
        self._running = True
        await self.fetch_and_inject()
        self._task = asyncio.create_task(self._monthly_refresh_loop(), name="imf_gold_refresh")

    async def stop(self) -> None:
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
        await self.close()

    async def _monthly_refresh_loop(self) -> None:
        """Refresh on the 5th of each month at 06:00 UTC."""
        while self._running:
            now = datetime.now(UTC)
            # Next 5th at 06:00 UTC
            if now.day < 5 or (now.day == 5 and now.hour < 6):
                next_run = now.replace(day=5, hour=6, minute=0, second=0, microsecond=0)
            # Move to next month
            elif now.month == 12:
                next_run = now.replace(year=now.year + 1, month=1, day=5, hour=6, minute=0, second=0, microsecond=0)
            else:
                next_run = now.replace(month=now.month + 1, day=5, hour=6, minute=0, second=0, microsecond=0)
            wait_s = (next_run - now).total_seconds()
            logger.info(
                "IMF: next refresh in %.1f days (5th of month 06:00 UTC)",
                wait_s / 86400.0,
            )
            await asyncio.sleep(wait_s)
            if self._running:
                await self.fetch_and_inject(years=1)

    def health(self) -> dict:
        return {
            "last_fetch": self._last_fetch.isoformat() if self._last_fetch else None,
            "running": self._running,
        }


# Module-level singleton
imf_gold_feed = IMFGoldFeed()

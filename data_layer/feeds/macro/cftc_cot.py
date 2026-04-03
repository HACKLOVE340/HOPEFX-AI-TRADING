# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
"""
data_layer/feeds/macro/cftc_cot.py
====================================
CFTC Commitments of Traders (COT) feed for gold futures (COMEX 100 Troy Oz).

Data source
-----------
CFTC publishes the Disaggregated COT report every Friday at ~15:30 ET,
covering positions as of the prior Tuesday.  The data is free and public.

Download URL (current year ZIP):
  https://www.cftc.gov/files/dea/history/fut_disagg_txt_{YYYY}.zip

Historical ZIPs (2010–present) follow the same pattern.

Series extracted (COMEX Gold, contract code 088691)
----------------------------------------------------
  cot_net_spec      : Net speculative position = Large Spec Long - Large Spec Short
  cot_net_spec_pct  : Net spec as % of open interest (normalised, -1 to +1)
  cot_comm_net      : Commercial net = Comm Long - Comm Short (hedger sentiment)
  cot_open_interest : Total open interest

Gold signal logic
-----------------
  cot_net_spec rising  → large specs adding longs → bullish
  cot_net_spec falling → large specs cutting longs → bearish
  cot_comm_net rising  → hedgers covering shorts → bullish (contrarian)
  Extreme net_spec_pct (>0.8 or <-0.8) → mean-reversion warning

Integration
-----------
Results are injected into ml.macro_store via MacroStore.update() so they
flow into the ML feature pipeline automatically via align_to_hourly().

The COT series are also registered in _DEFAULT_SERIES so they persist
to data/macro/cot_*.csv for offline use.

Usage
-----
    from data_layer.feeds.macro.cftc_cot import cot_feed

    # One-shot fetch and store injection
    await cot_feed.fetch_and_inject()

    # Scheduled weekly refresh (call from orchestrator or scheduler)
    await cot_feed.start()   # starts background Friday refresh loop
    await cot_feed.stop()
"""

from __future__ import annotations

import asyncio
import io
import logging
import os
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import aiohttp
import pandas as pd

logger = logging.getLogger(__name__)

UTC = timezone.utc

# CFTC disaggregated futures COT — current year and historical
_CFTC_CURRENT_URL = "https://www.cftc.gov/files/dea/history/fut_disagg_txt_{year}.zip"
_CFTC_HIST_BASE = "https://www.cftc.gov/files/dea/history/"

# COMEX Gold futures contract code in the CFTC report
_GOLD_CONTRACT_CODE = "088691"
_GOLD_MARKET_NAME = "GOLD - COMMODITY EXCHANGE INC."

# Columns we need from the disaggregated report
_COL_MAP = {
    "Market_and_Exchange_Names": "market",
    "CFTC_Contract_MarketCode": "contract_code",
    "As_of_Date_In_Form_YYMMDD": "report_date",
    "Open_Interest_All": "open_interest",
    "Lev_Money_Positions_Long_All": "large_spec_long",
    "Lev_Money_Positions_Short_All": "large_spec_short",
    "Comm_Positions_Long_All": "comm_long",
    "Comm_Positions_Short_All": "comm_short",
}

# Local cache directory
_CACHE_DIR = Path(os.getenv("COT_CACHE_DIR", "data/macro"))
_CACHE_DIR.mkdir(parents=True, exist_ok=True)

_HTTP_TIMEOUT = aiohttp.ClientTimeout(total=60.0)

# How many years of history to fetch on first run
_HISTORY_YEARS = int(os.getenv("COT_HISTORY_YEARS", "5"))


class CFTCCOTFeed:
    """
    Downloads and parses CFTC Disaggregated COT reports for COMEX gold.

    Extracts net speculative and commercial positioning and injects them
    into ml.macro_store for use as ML features.
    """

    def __init__(self) -> None:
        self._session: aiohttp.ClientSession | None = None
        self._running = False
        self._last_fetch: datetime | None = None
        self._task: asyncio.Task | None = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(timeout=_HTTP_TIMEOUT)
        return self._session

    async def close(self) -> None:
        self._running = False
        if self._session and not self._session.closed:
            await self._session.close()

    # ── Download ──────────────────────────────────────────────────────────────

    async def _download_year(self, year: int) -> pd.DataFrame:
        """Download and parse one year of disaggregated COT data."""
        url = _CFTC_CURRENT_URL.format(year=year)
        logger.info("COT: downloading %s", url)
        try:
            session = await self._get_session()
            async with session.get(url) as resp:
                if resp.status == 404:
                    logger.debug("COT: %d data not available (404)", year)
                    return pd.DataFrame()
                resp.raise_for_status()
                raw = await resp.read()

            with zipfile.ZipFile(io.BytesIO(raw)) as zf:
                # The ZIP contains a single .txt (CSV) file
                txt_files = [n for n in zf.namelist() if n.endswith(".txt")]
                if not txt_files:
                    logger.warning("COT: no .txt in ZIP for year %d", year)
                    return pd.DataFrame()
                with zf.open(txt_files[0]) as f:
                    df = pd.read_csv(f, low_memory=False)

            return self._filter_gold(df)

        except Exception as exc:
            logger.warning("COT: download failed for year %d: %s", year, exc)
            return pd.DataFrame()

    def _filter_gold(self, df: pd.DataFrame) -> pd.DataFrame:
        """Keep only COMEX gold rows and extract relevant columns."""
        # Filter by contract code (most reliable) or market name
        mask = df.get("CFTC_Contract_MarketCode", pd.Series(dtype=str)).astype(str).str.strip() == _GOLD_CONTRACT_CODE
        gold = df[mask].copy()

        if gold.empty:
            # Fallback: filter by market name substring
            name_col = "Market_and_Exchange_Names"
            if name_col in df.columns:
                gold = df[df[name_col].astype(str).str.upper().str.contains("GOLD")].copy()

        if gold.empty:
            return pd.DataFrame()

        # Keep only columns we need (ignore missing ones gracefully)
        available = {k: v for k, v in _COL_MAP.items() if k in gold.columns}
        gold = gold[list(available.keys())].rename(columns=available)

        # Parse date — CFTC uses YYMMDD format
        if "report_date" in gold.columns:
            gold["date"] = pd.to_datetime(gold["report_date"].astype(str), format="%y%m%d", errors="coerce")
            gold = gold.dropna(subset=["date"])
            gold["date"] = gold["date"].dt.tz_localize("UTC")

        return gold

    # ── Parse ─────────────────────────────────────────────────────────────────

    def _compute_series(self, df: pd.DataFrame) -> dict[str, pd.Series]:
        """Compute COT positioning series from raw gold rows."""
        if df.empty or "date" not in df.columns:
            return {}

        df = df.sort_values("date").set_index("date")

        def _to_float(col: str) -> pd.Series:
            if col in df.columns:
                return pd.to_numeric(df[col], errors="coerce").fillna(0.0)
            return pd.Series(0.0, index=df.index)

        large_spec_long = _to_float("large_spec_long")
        large_spec_short = _to_float("large_spec_short")
        comm_long = _to_float("comm_long")
        comm_short = _to_float("comm_short")
        open_interest = _to_float("open_interest")

        net_spec = large_spec_long - large_spec_short
        comm_net = comm_long - comm_short

        # Normalise net spec by open interest (-1 to +1)
        net_spec_pct = net_spec / open_interest.replace(0, float("nan"))
        net_spec_pct = net_spec_pct.fillna(0.0).clip(-1.0, 1.0)

        return {
            "cot_net_spec": net_spec,
            "cot_net_spec_pct": net_spec_pct,
            "cot_comm_net": comm_net,
            "cot_open_interest": open_interest,
        }

    # ── Inject into MacroStore ────────────────────────────────────────────────

    def _inject_into_macro_store(self, series_dict: dict[str, pd.Series]) -> None:
        """Push computed COT series into ml.macro_store singleton."""
        try:
            from ml.macro_store import macro_store

            for name, series in series_dict.items():
                if series.empty:
                    continue
                macro_store._series[name] = series.sort_index()
                logger.info(
                    "COT: injected %s into MacroStore (%d obs, latest=%.0f on %s)",
                    name,
                    len(series),
                    float(series.iloc[-1]),
                    series.index[-1].date().isoformat(),
                )
        except Exception as exc:
            logger.warning("COT: MacroStore injection failed: %s", exc)

    def _save_csv(self, series_dict: dict[str, pd.Series]) -> None:
        """Persist COT series to data/macro/ for offline use."""
        for name, series in series_dict.items():
            if series.empty:
                continue
            path = _CACHE_DIR / f"{name}.csv"
            try:
                df = series.reset_index()
                df.columns = ["date", "value"]
                df["date"] = df["date"].dt.strftime("%Y-%m-%d")
                df.to_csv(path, index=False)
                logger.debug("COT: saved %s → %s", name, path)
            except Exception as exc:
                logger.warning("COT: CSV save failed for %s: %s", name, exc)

    # ── Public API ────────────────────────────────────────────────────────────

    async def fetch_and_inject(self, years: int | None = None) -> dict[str, int]:
        """
        Download COT history, compute series, inject into MacroStore.

        Parameters
        ----------
        years : Number of years of history to fetch (default: COT_HISTORY_YEARS)

        Returns
        -------
        Dict mapping series name → number of observations loaded.
        """
        n_years = years or _HISTORY_YEARS
        current_year = datetime.now(UTC).year
        all_frames: list[pd.DataFrame] = []

        for yr in range(current_year - n_years + 1, current_year + 1):
            df = await self._download_year(yr)
            if not df.empty:
                all_frames.append(df)

        if not all_frames:
            logger.warning("COT: no data downloaded — MacroStore not updated")
            return {}

        combined = pd.concat(all_frames, ignore_index=True)
        series_dict = self._compute_series(combined)

        self._inject_into_macro_store(series_dict)
        self._save_csv(series_dict)
        self._last_fetch = datetime.now(UTC)

        return {name: len(s) for name, s in series_dict.items()}

    async def start(self) -> None:
        """
        Fetch COT data immediately then refresh every Friday at 16:00 ET
        (21:00 UTC) — shortly after CFTC publishes the weekly report.
        """
        self._running = True
        # Initial fetch
        await self.fetch_and_inject()
        # Schedule weekly refresh
        self._task = asyncio.create_task(self._weekly_refresh_loop(), name="cftc_cot_refresh")

    async def stop(self) -> None:
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
        await self.close()

    async def _weekly_refresh_loop(self) -> None:
        """Refresh every Friday at 21:00 UTC (16:00 ET)."""
        while self._running:
            now = datetime.now(UTC)
            # Find next Friday 21:00 UTC
            days_until_friday = (4 - now.weekday()) % 7  # Friday = weekday 4
            if days_until_friday == 0 and now.hour >= 21:
                days_until_friday = 7  # already past this Friday's publish time
            next_friday = now.replace(hour=21, minute=0, second=0, microsecond=0) + timedelta(days=days_until_friday)
            wait_s = (next_friday - now).total_seconds()
            logger.info(
                "COT: next refresh in %.1f hours (Friday 21:00 UTC)",
                wait_s / 3600.0,
            )
            await asyncio.sleep(wait_s)
            if self._running:
                await self.fetch_and_inject(years=1)  # only fetch current year on refresh

    def health(self) -> dict:
        return {
            "last_fetch": self._last_fetch.isoformat() if self._last_fetch else None,
            "running": self._running,
        }


# Module-level singleton
cot_feed = CFTCCOTFeed()

# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
"""
data_layer/feeds/macro/yahoo_macro.py
========================================
Yahoo Finance macro series fetcher — cross-asset data for gold ML features.

Fetches the series that ml/macro_features.py uses but FRED does not provide:
  SPX    (^GSPC)  — S&P 500 daily close
  GLD    (GLD)    — Gold ETF daily close (cross-asset momentum)
  Copper (HG=F)   — Copper futures (global growth proxy)
  Oil    (CL=F)   — Crude oil futures (inflation / geopolitical proxy)
  USDCNY (CNY=X)  — USD/CNY exchange rate (China gold demand proxy)

These are injected into ml.macro_store alongside FRED series so that
ml/macro_features.py can compute all 122 macro features without gaps.

No API key required — uses yfinance (already in requirements.txt).

Series injected into MacroStore
--------------------------------
  spx        : S&P 500 daily close
  gold_etf   : GLD daily close
  copper     : Copper futures daily close
  oil        : Crude oil futures daily close
  usdcny     : USD/CNY daily close

Refresh schedule: daily at 22:00 UTC (after US market close).
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)

UTC = timezone.utc

_CACHE_DIR = Path(os.getenv("YAHOO_MACRO_CACHE_DIR", "data/macro"))
_CACHE_DIR.mkdir(parents=True, exist_ok=True)

_HISTORY_YEARS = int(os.getenv("YAHOO_MACRO_HISTORY_YEARS", "10"))

# Yahoo tickers → MacroStore series name
_YAHOO_SERIES: dict[str, str] = {
    "^GSPC": "spx",
    "GLD": "gold_etf",
    "HG=F": "copper",
    "CL=F": "oil",
    "CNY=X": "usdcny",
    "DX-Y.NYB": "dxy_yahoo",   # DXY cross-check against FRED DTWEXBGS
}


class YahooMacroFeed:
    """
    Fetches cross-asset macro series from Yahoo Finance via yfinance.

    Runs in a thread pool to avoid blocking the asyncio event loop
    (yfinance is synchronous).
    """

    def __init__(self) -> None:
        self._running = False
        self._last_fetch: datetime | None = None
        self._task: asyncio.Task | None = None

    def _fetch_sync(self, years: int) -> dict[str, pd.Series]:
        """Synchronous yfinance download — runs in executor."""
        try:
            import yfinance as yf
        except ImportError:
            logger.warning("yfinance not installed — Yahoo macro feed disabled. "
                           "Install with: pip install yfinance")
            return {}

        start = (datetime.now(UTC) - timedelta(days=365 * years)).strftime("%Y-%m-%d")
        results: dict[str, pd.Series] = {}

        for ticker, name in _YAHOO_SERIES.items():
            try:
                df = yf.download(ticker, start=start, progress=False, auto_adjust=True)
                if df.empty:
                    logger.warning("Yahoo: no data for %s (%s)", ticker, name)
                    continue
                close = df["Close"].squeeze()
                if isinstance(close, pd.DataFrame):
                    close = close.iloc[:, 0]
                close.index = pd.to_datetime(close.index, utc=True)
                close = close.sort_index().dropna()
                results[name] = close
                logger.info(
                    "Yahoo: fetched %s (%s) — %d obs, latest=%.4f on %s",
                    name, ticker, len(close),
                    float(close.iloc[-1]),
                    close.index[-1].date().isoformat(),
                )
            except Exception as exc:
                logger.warning("Yahoo: fetch failed for %s (%s): %s", ticker, name, exc)

        return results

    def _inject_into_macro_store(self, series_dict: dict[str, pd.Series]) -> None:
        try:
            from ml.macro_store import macro_store
            for name, series in series_dict.items():
                if series.empty:
                    continue
                macro_store._series[name] = series.sort_index()
                logger.debug("Yahoo: injected %s into MacroStore (%d obs)", name, len(series))
        except Exception as exc:
            logger.warning("Yahoo: MacroStore injection failed: %s", exc)

    def _save_csv(self, series_dict: dict[str, pd.Series]) -> None:
        for name, series in series_dict.items():
            if series.empty:
                continue
            path = _CACHE_DIR / f"{name}_daily.csv"
            try:
                df = series.reset_index()
                df.columns = ["date", "value"]
                df["date"] = df["date"].dt.strftime("%Y-%m-%d")
                df.to_csv(path, index=False)
            except Exception as exc:
                logger.warning("Yahoo: CSV save failed for %s: %s", name, exc)

    async def fetch_and_inject(self, years: int | None = None) -> dict[str, int]:
        """Fetch all Yahoo macro series and inject into MacroStore."""
        n_years = years or _HISTORY_YEARS
        loop = asyncio.get_event_loop()
        series_dict = await loop.run_in_executor(None, self._fetch_sync, n_years)

        if not series_dict:
            # Try CSV fallback
            series_dict = self._load_csv_fallback()

        self._inject_into_macro_store(series_dict)
        self._save_csv(series_dict)
        self._last_fetch = datetime.now(UTC)
        return {name: len(s) for name, s in series_dict.items()}

    def _load_csv_fallback(self) -> dict[str, pd.Series]:
        """Load from cached CSVs when yfinance is unavailable."""
        results: dict[str, pd.Series] = {}
        for name in _YAHOO_SERIES.values():
            path = _CACHE_DIR / f"{name}_daily.csv"
            if not path.exists():
                continue
            try:
                df = pd.read_csv(path, parse_dates=["date"])
                df["date"] = pd.to_datetime(df["date"], utc=True)
                results[name] = df.set_index("date")["value"].sort_index()
                logger.info("Yahoo: loaded %s from CSV fallback (%d obs)", name, len(results[name]))
            except Exception as exc:
                logger.warning("Yahoo: CSV fallback failed for %s: %s", name, exc)
        return results

    async def start(self) -> None:
        """Fetch immediately then refresh daily at 22:00 UTC."""
        self._running = True
        await self.fetch_and_inject()
        self._task = asyncio.create_task(
            self._daily_refresh_loop(), name="yahoo_macro_refresh"
        )

    async def stop(self) -> None:
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()

    async def _daily_refresh_loop(self) -> None:
        while self._running:
            now = datetime.now(UTC)
            target = now.replace(hour=22, minute=0, second=0, microsecond=0)
            if target <= now:
                target += timedelta(days=1)
            await asyncio.sleep((target - now).total_seconds())
            if self._running:
                await self.fetch_and_inject(years=1)

    def health(self) -> dict:
        return {
            "last_fetch": self._last_fetch.isoformat() if self._last_fetch else None,
            "running": self._running,
            "series": list(_YAHOO_SERIES.values()),
        }


# Module-level singleton
yahoo_macro_feed = YahooMacroFeed()

# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
ml/macro_bootstrap.py
=====================
Bootstrap and daily-refresh logic for the MacroStore.

Fetches historical and current macro data (DXY, VIX, US yields, SPX) from
yfinance and writes CSV files to data/macro/.  Called at startup by
core/startup_factories.py::init_macro_store() and on a daily schedule.

Design
------
- All fetches are best-effort: a missing series is logged and skipped.
- The store works with partial data — missing series are zero-filled at
  inference time by MacroStore.align_to_hourly().
- yfinance is an optional dependency; if unavailable the store loads from
  existing CSVs only (or stays empty, which is safe).
- The daily refresh job runs at 18:00 UTC (after US market close) so the
  store always has yesterday's closing values by the time the London session
  opens.

Environment variables
---------------------
MACRO_DATA_DIR   — directory for CSV files (default: data/macro)
MACRO_HISTORY_YEARS — years of history to fetch on first bootstrap (default: 5)
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
UTC = timezone.utc
from pathlib import Path
from typing import TYPE_CHECKING

import pandas as pd

if TYPE_CHECKING:
    from ml.macro_store import MacroStore

logger = logging.getLogger(__name__)

_MACRO_DIR = Path(os.getenv("MACRO_DATA_DIR", "data/macro"))
_HISTORY_YEARS = int(os.getenv("MACRO_HISTORY_YEARS", "5"))

# yfinance ticker → MacroStore series name → CSV filename
_SERIES_MAP: dict[str, dict[str, str]] = {
    "DX-Y.NYB": {"name": "dxy", "file": "dxy_daily.csv"},
    "^VIX": {"name": "vix", "file": "vix_daily.csv"},
    "^TNX": {"name": "us10y", "file": "us10y_daily.csv"},
    "^FVX": {"name": "us2y", "file": "us2y_daily.csv"},
    "^GSPC": {"name": "spx", "file": "spx_daily.csv"},
    "GLD": {"name": "gold_etf_flow", "file": "gold_etf_flow.csv"},
}


def _fetch_series(ticker: str, years: int = _HISTORY_YEARS) -> pd.DataFrame | None:
    """Fetch `years` of daily close data for `ticker` via yfinance."""
    try:
        import yfinance as yf

        end = datetime.now(UTC)
        start = end - timedelta(days=years * 365)
        df = yf.download(
            ticker,
            start=start.strftime("%Y-%m-%d"),
            end=end.strftime("%Y-%m-%d"),
            progress=False,
            auto_adjust=True,
        )
        if df.empty:
            logger.warning("MacroBootstrap: empty response for %s", ticker)
            return None
        close = df["Close"].dropna()
        if hasattr(close, "squeeze"):
            close = close.squeeze()
        result = close.reset_index()
        result.columns = ["date", "value"]
        result["date"] = pd.to_datetime(result["date"], utc=True).dt.date.astype(str)
        return result
    except ImportError:
        logger.debug("MacroBootstrap: yfinance not installed — skipping %s", ticker)
        return None
    except Exception as exc:
        logger.warning("MacroBootstrap: fetch failed for %s: %s", ticker, exc)
        return None


def bootstrap(force: bool = False) -> int:
    """
    Fetch historical macro data and write CSVs to MACRO_DATA_DIR.

    Parameters
    ----------
    force : bool
        Re-fetch even if the CSV already exists and is recent (< 24 h old).

    Returns
    -------
    int : number of series successfully written/updated.
    """
    _MACRO_DIR.mkdir(parents=True, exist_ok=True)
    written = 0

    for ticker, meta in _SERIES_MAP.items():
        csv_path = _MACRO_DIR / meta["file"]
        series_name = meta["name"]

        # Skip if file is fresh (< 24 h) and force=False
        if not force and csv_path.exists():
            age_hours = (datetime.now().timestamp() - csv_path.stat().st_mtime) / 3600
            if age_hours < 24:
                logger.debug(
                    "MacroBootstrap: %s is %.1f h old — skipping (use force=True to refresh)",
                    csv_path.name,
                    age_hours,
                )
                written += 1  # count as available
                continue

        df = _fetch_series(ticker)
        if df is None:
            continue

        df.to_csv(csv_path, index=False)
        logger.info(
            "MacroBootstrap: wrote %d rows for %s → %s",
            len(df),
            series_name,
            csv_path,
        )
        written += 1

    logger.info(
        "MacroBootstrap: %d/%d series available in %s",
        written,
        len(_SERIES_MAP),
        _MACRO_DIR,
    )
    return written


def daily_refresh() -> int:
    """Force-refresh all series (called by the daily scheduler job)."""
    logger.info("MacroBootstrap: running daily refresh")
    return bootstrap(force=True)


def load_into_store(store: MacroStore) -> int:
    """
    Load all available CSVs from MACRO_DATA_DIR into a MacroStore instance.

    Returns the number of series loaded.
    """
    loaded = 0
    for meta in _SERIES_MAP.values():
        csv_path = _MACRO_DIR / meta["file"]
        n = store.load_csv(csv_path, meta["name"])
        if n > 0:
            loaded += 1
    logger.info(
        "MacroBootstrap.load_into_store: %d/%d series loaded",
        loaded,
        len(_SERIES_MAP),
    )
    return loaded

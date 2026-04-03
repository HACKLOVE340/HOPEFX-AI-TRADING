# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
ml/macro_store.py
=================
Macro feature store that aligns daily macro data (DXY, yields, CPI) to
hourly OHLCV bars via forward-fill.

Problem
-------
The H1 OANDA data has OHLCV only. The advanced model's 122 features include
macro cross-asset inputs (DXY, US 10Y yield, CPI surprise) that are published
daily or monthly. At inference time these must be merged onto the hourly bars
using the last known value (forward-fill until the next macro update).

Design
------
MacroStore holds a dict of {series_name: pd.Series(daily)} and exposes:

  align_to_hourly(ohlcv_h1) → pd.DataFrame
      Returns a DataFrame with the same DatetimeIndex as ohlcv_h1 where
      each macro column is forward-filled from the last daily observation.

  update(series_name, date, value)
      Upsert a single macro observation (called by data ingestion jobs).

  load_csv(path, series_name)
      Bulk-load a CSV with columns [date, value].

  snapshot() → dict
      Return the latest value for each series (for /api/advanced_trading/cot).

Usage
-----
    from ml.macro_store import macro_store

    # At startup, load historical macro data:
    macro_store.load_csv("data/macro/dxy_daily.csv", "dxy")
    macro_store.load_csv("data/macro/us10y_daily.csv", "us10y")

    # At inference time:
    macro_df = macro_store.align_to_hourly(ohlcv_h1)
    signal = predictor.predict_signal(ohlcv_h1, macro_df=macro_df)

    # When new macro data arrives (e.g. weekly COT update):
    macro_store.update("cot_net_spec", date="2026-03-25", value=-12345.0)
"""

from __future__ import annotations

import logging
import os
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)

# Default macro data directory (override via MACRO_DATA_DIR env var)
_MACRO_DIR = Path(os.getenv("MACRO_DATA_DIR", "data/macro"))

# Known macro series and their CSV filenames (relative to _MACRO_DIR)
_DEFAULT_SERIES: dict[str, str] = {
    "dxy": "dxy_daily.csv",
    "us10y": "us10y_daily.csv",
    "us2y": "us2y_daily.csv",
    "cpi_surprise": "cpi_surprise.csv",
    "vix": "vix_daily.csv",
    "gold_etf_flow": "gold_etf_flow.csv",
    # WGC gold demand series (quarterly/monthly, forward-filled to hourly)
    # Populated by WGCFeed.inject_into_macro_store() at startup and daily refresh.
    # CSV fallback: place manually downloaded WGC exports in data/macro/
    "wgc_total_demand": "wgc_total_demand.csv",
    "wgc_investment": "wgc_investment.csv",
    "wgc_central_bank": "wgc_central_bank.csv",
    "wgc_jewellery": "wgc_jewellery.csv",
    "wgc_etf_flow": "wgc_etf_flow.csv",
}


class MacroStore:
    """
    In-memory store for daily macro series with hourly alignment.

    Thread-safe for reads. Writes (update/load_csv) should be called
    from a single scheduler thread.
    """

    def __init__(self) -> None:
        # series_name → pd.Series(float, index=DatetimeIndex[daily])
        self._series: dict[str, pd.Series] = {}

    # ── Ingestion ─────────────────────────────────────────────────────────────

    def load_csv(
        self,
        path: str | Path,
        series_name: str,
        date_col: str = "date",
        value_col: str = "value",
    ) -> int:
        """
        Load a CSV file into the store.

        Expected format:
            date,value
            2024-01-02,102.34
            2024-01-03,101.89
            ...

        Returns the number of rows loaded.
        """
        p = Path(path)
        if not p.exists():
            logger.debug("MacroStore.load_csv: %s not found — skipping %s", p, series_name)
            return 0
        try:
            df = pd.read_csv(p, parse_dates=[date_col])
            df = df[[date_col, value_col]].dropna()
            df = df.rename(columns={date_col: "date", value_col: "value"})
            df["date"] = pd.to_datetime(df["date"], utc=True)
            series = df.set_index("date")["value"].sort_index()
            self._series[series_name] = series
            logger.info("MacroStore: loaded %d rows for %s from %s", len(series), series_name, p)
            return len(series)
        except Exception as exc:
            logger.warning("MacroStore.load_csv failed for %s: %s", series_name, exc)
            return 0

    def update(
        self,
        series_name: str,
        as_of: str | date | datetime,
        value: float,
    ) -> None:
        """
        Upsert a single macro observation.

        Called by data ingestion jobs when new data arrives (e.g. weekly COT,
        monthly CPI, daily DXY close).
        """
        ts = pd.Timestamp(as_of, tz="UTC")
        if series_name not in self._series:
            self._series[series_name] = pd.Series(dtype=float, name=series_name)
        self._series[series_name][ts] = float(value)
        self._series[series_name] = self._series[series_name].sort_index()
        logger.debug("MacroStore.update: %s[%s] = %s", series_name, ts.date(), value)

    def load_defaults(self) -> None:
        """
        Attempt to load all default series from _MACRO_DIR.

        Silently skips missing files — the store works with partial data.
        """
        for name, filename in _DEFAULT_SERIES.items():
            self.load_csv(_MACRO_DIR / filename, name)

    # ── Alignment ─────────────────────────────────────────────────────────────

    def align_to_hourly(
        self,
        ohlcv_h1: pd.DataFrame,
        series: list[str] | None = None,
    ) -> pd.DataFrame:
        """
        Align daily macro series to the hourly OHLCV index.

        Each daily value is forward-filled to all hourly bars until the next
        daily observation. This is the correct causal approach for macro data:
        a DXY close of 102.34 on Monday applies to all hourly bars on
        Tuesday until Tuesday's close is published.

        bfill is intentionally NOT supported. Back-filling would propagate a
        future observation into past bars (look-ahead bias), corrupting any
        backtest or training run that uses this data.

        Parameters
        ----------
        ohlcv_h1 : DataFrame with DatetimeIndex (hourly)
        series   : List of series names to include (default: all loaded)

        Returns
        -------
        DataFrame with same index as ohlcv_h1, one column per macro series.
        Leading NaNs (before the first observation) are filled with 0.0 —
        the neutral/unknown value — rather than back-filled from the future.
        """
        if ohlcv_h1.empty:
            return pd.DataFrame(index=ohlcv_h1.index)

        # Ensure hourly index is timezone-aware
        idx = ohlcv_h1.index
        if idx.tz is None:
            idx = idx.tz_localize("UTC")

        names = series or list(self._series.keys())
        if not names:
            logger.debug("MacroStore.align_to_hourly: no series loaded — returning empty")
            return pd.DataFrame(index=ohlcv_h1.index)

        aligned_cols: dict[str, pd.Series] = {}
        for name in names:
            if name not in self._series:
                logger.debug("MacroStore: series %r not loaded — filling with 0", name)
                aligned_cols[name] = pd.Series(0.0, index=ohlcv_h1.index)
                continue

            daily = self._series[name]
            if daily.index.tz is None:
                daily = daily.tz_localize("UTC")

            # Reindex to hourly then forward-fill only.
            # Leading NaNs (before the first daily observation) are filled
            # with 0.0 — never back-filled — to avoid look-ahead bias.
            combined_idx = idx.union(daily.index)
            reindexed = daily.reindex(combined_idx).ffill()
            aligned = reindexed.reindex(idx).fillna(0.0)
            aligned_cols[name] = aligned

        result = pd.DataFrame(aligned_cols, index=ohlcv_h1.index)
        return result

    # ── Introspection ─────────────────────────────────────────────────────────

    def snapshot(self) -> dict[str, Any]:
        """Return the latest value for each loaded series."""
        out: dict[str, Any] = {}
        for name, series in self._series.items():
            if series.empty:
                out[name] = None
            else:
                last = series.iloc[-1]
                out[name] = {
                    "value": float(last),
                    "date": series.index[-1].date().isoformat(),
                    "n_observations": len(series),
                }
        return out

    def series_names(self) -> list[str]:
        """Return names of all loaded series."""
        return list(self._series.keys())

    def __len__(self) -> int:
        return len(self._series)

    def __repr__(self) -> str:
        return f"MacroStore(series={self.series_names()}, total_obs={sum(len(s) for s in self._series.values())})"


# Module-level singleton — import and use directly
macro_store = MacroStore()

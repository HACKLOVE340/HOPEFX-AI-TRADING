# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
ml/daily_aggregator.py
======================
Resamples intraday OHLCV bars to daily bars before model inference.

Problem
-------
The production model (advanced_oos.pkl) was trained on daily XAUUSD bars
(GC=F from yfinance, interval="1d").  The live strategy engine feeds it
synthetic intraday bars aggregated from raw ticks (10 ticks → 1 bar).
Feeding sub-daily bars to a daily-trained model causes a regime mismatch:
  - Rolling windows (e.g. 60-bar SMA) span minutes instead of months
  - Volatility features are scaled to intraday noise, not daily moves
  - The model's learned thresholds are calibrated to daily return magnitudes

Fix
---
Resample the intraday buffer to daily bars before calling the model.
This preserves the model's calibration without requiring a full retrain.

Usage
-----
    from ml.daily_aggregator import to_daily, needs_resampling

    if needs_resampling(ohlcv_df):
        daily_df = to_daily(ohlcv_df, min_bars=100)
        if daily_df is not None:
            signal = model.predict(daily_df)

Configuration
-------------
INFERENCE_TIMEFRAME : "daily" (default) | "intraday"
    Set to "intraday" only if the model has been retrained on intraday bars.
    When "intraday", to_daily() is a no-op pass-through.

MIN_DAILY_BARS : int (default 100)
    Minimum daily bars required after resampling. If the resampled result
    has fewer bars, returns None so the caller can abstain.
"""

from __future__ import annotations

import logging
import os

import pandas as pd

logger = logging.getLogger(__name__)

# ── Configuration ─────────────────────────────────────────────────────────────
# Set INFERENCE_TIMEFRAME=intraday only after retraining the model on H1 data.
_INFERENCE_TIMEFRAME = os.getenv("INFERENCE_TIMEFRAME", "daily").lower()
_MIN_DAILY_BARS = int(os.getenv("MIN_DAILY_BARS", "100"))

# Intraday bar detection: if median bar duration < this threshold (seconds),
# the input is considered intraday and resampling is applied.
_INTRADAY_THRESHOLD_SECONDS = 3600 * 20  # 20 hours — anything shorter than a day


def needs_resampling(ohlcv: pd.DataFrame) -> bool:
    """
    Return True when the DataFrame contains intraday bars and the model
    is configured for daily inference.

    Detection heuristic: compute the median duration between consecutive
    index timestamps.  If it is less than 20 hours, the data is intraday.
    """
    if _INFERENCE_TIMEFRAME == "intraday":
        return False  # model retrained on intraday — no resampling needed

    if not isinstance(ohlcv.index, pd.DatetimeIndex):
        return False  # can't determine frequency without a DatetimeIndex

    if len(ohlcv) < 2:  # noqa: PLR2004
        return False

    try:
        diffs = ohlcv.index.to_series().diff().dropna()
        median_seconds = diffs.median().total_seconds()
        return median_seconds < _INTRADAY_THRESHOLD_SECONDS
    except Exception as exc:
        logger.debug("needs_resampling: could not determine bar duration: %s", exc)
        return False


def to_daily(
    ohlcv: pd.DataFrame,
    min_bars: int = _MIN_DAILY_BARS,
) -> pd.DataFrame | None:
    """
    Resample an intraday OHLCV DataFrame to daily bars.

    Parameters
    ----------
    ohlcv    : DataFrame with columns [open, high, low, close, volume] and
               a DatetimeIndex (timezone-aware or naive).
    min_bars : Minimum number of daily bars required. Returns None if the
               resampled result has fewer bars (caller should abstain).

    Returns
    -------
    Daily OHLCV DataFrame, or None if resampling fails or produces too few bars.

    Notes
    -----
    - Uses calendar-day resampling ("1D") so partial days at the boundary
      are included as incomplete bars.  The last bar may be a partial day
      (intraday session in progress) — this is intentional: the model should
      see the current day's developing bar.
    - Volume is summed; open/high/low/close use standard OHLCV aggregation.
    - NaN rows (e.g. weekends with no data) are dropped.
    """
    if _INFERENCE_TIMEFRAME == "intraday":
        # Model retrained on intraday bars — pass through unchanged
        return ohlcv if len(ohlcv) >= min_bars else None

    if not isinstance(ohlcv.index, pd.DatetimeIndex):
        logger.debug("to_daily: index is not DatetimeIndex — cannot resample")
        return ohlcv if len(ohlcv) >= min_bars else None

    try:
        # Ensure timezone-aware index for consistent resampling
        if ohlcv.index.tz is None:
            ohlcv = ohlcv.copy()
            ohlcv.index = ohlcv.index.tz_localize("UTC")

        # Normalise column names to lowercase
        ohlcv = ohlcv.copy()
        ohlcv.columns = [c.lower() for c in ohlcv.columns]

        required = {"open", "high", "low", "close"}
        missing = required - set(ohlcv.columns)
        if missing:
            logger.debug("to_daily: missing columns %s — cannot resample", missing)
            return ohlcv if len(ohlcv) >= min_bars else None

        agg: dict[str, str] = {
            "open": "first",
            "high": "max",
            "low": "min",
            "close": "last",
        }
        if "volume" in ohlcv.columns:
            agg["volume"] = "sum"

        daily = ohlcv[list(agg.keys())].resample("1D").agg(agg).dropna(subset=["close"])

        if len(daily) < min_bars:
            logger.debug(
                "to_daily: only %d daily bars after resampling (need %d) — returning None so caller can abstain",
                len(daily),
                min_bars,
            )
            return None

        logger.debug(
            "to_daily: resampled %d intraday bars → %d daily bars",
            len(ohlcv),
            len(daily),
        )
        return daily

    except Exception as exc:
        logger.warning("to_daily: resampling failed: %s", exc)
        return ohlcv if len(ohlcv) >= min_bars else None


def ensure_daily(
    ohlcv: pd.DataFrame,
    min_bars: int = _MIN_DAILY_BARS,
) -> pd.DataFrame | None:
    """
    Convenience wrapper: resample to daily if needed, else return as-is.

    Returns None if the result has fewer than min_bars bars.
    """
    if needs_resampling(ohlcv):
        return to_daily(ohlcv, min_bars=min_bars)
    return ohlcv if len(ohlcv) >= min_bars else None

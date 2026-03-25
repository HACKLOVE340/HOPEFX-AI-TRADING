"""
research/pipeline/mtf_fusion.py
=================================
Multi-timeframe (MTF) fusion layer.

Concept
-------
Daily trends carry regime information (bull/bear, high/low volatility) that
intraday models cannot see from 5-min bars alone.  This module:

1. Aligns daily features to intraday bars via forward-fill (no look-ahead).
2. Computes "regime context" columns from daily data (trend direction, vol
   regime, distance from key MAs) and appends them to the intraday feature
   matrix.
3. Optionally computes 1-hour aggregates from 5-min bars and appends those
   as additional context columns (3-level MTF: daily → 1h → 5m).

The result is a single wide DataFrame where every intraday bar has access to
the current daily and hourly context — without any future leakage.

Usage
-----
    from research.pipeline.mtf_fusion import MTFFusion

    fusion = MTFFusion()
    intraday_enriched = fusion.enrich(
        intraday_df=df_5m,
        daily_df=df_1d,
        hourly_df=df_1h,   # optional
    )
"""

from __future__ import annotations

import logging
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Daily regime features
# ─────────────────────────────────────────────────────────────────────────────

def _compute_daily_regime(daily: pd.DataFrame) -> pd.DataFrame:
    """
    Derive regime context columns from daily OHLCV.

    Columns added (all prefixed `d_`)
    ----------------------------------
    d_trend_20      : close > SMA20 → 1, else -1
    d_trend_50      : close > SMA50 → 1, else -1
    d_trend_200     : close > SMA200 → 1, else -1
    d_ma_align      : all three MAs aligned (strong trend) → 1, else 0
    d_realvol_20    : 20-day realised volatility (annualised)
    d_high_vol      : realvol_20 > 75th percentile → 1
    d_rsi_14        : daily RSI(14)
    d_bb_pct        : Bollinger %B (position within bands)
    d_dist_52wh     : distance from 52-week high (normalised)
    d_dist_52wl     : distance from 52-week low (normalised)
    d_ret_1d        : yesterday's daily return
    d_ret_5d        : 5-day return
    d_ret_20d       : 20-day return
    """
    d = daily.copy()
    c = d["close"]

    # Moving averages
    sma20 = c.rolling(20).mean()
    sma50 = c.rolling(50).mean()
    sma200 = c.rolling(200).mean()

    d["d_trend_20"] = np.where(c > sma20, 1, -1)
    d["d_trend_50"] = np.where(c > sma50, 1, -1)
    d["d_trend_200"] = np.where(c > sma200, 1, -1)
    d["d_ma_align"] = ((d["d_trend_20"] == 1) & (d["d_trend_50"] == 1) & (d["d_trend_200"] == 1)).astype(int)

    # Volatility regime
    log_ret = np.log(c / c.shift(1))
    rv20 = log_ret.rolling(20).std() * np.sqrt(252)
    d["d_realvol_20"] = rv20
    d["d_high_vol"] = (rv20 > rv20.rolling(252, min_periods=60).quantile(0.75)).astype(int)

    # RSI
    delta = c.diff()
    gain = delta.clip(lower=0).ewm(com=13, adjust=False).mean()
    loss = (-delta).clip(lower=0).ewm(com=13, adjust=False).mean()
    rs = gain / loss.replace(0, np.nan)
    d["d_rsi_14"] = 100 - (100 / (1 + rs))

    # Bollinger %B
    bb_mid = c.rolling(20).mean()
    bb_std = c.rolling(20).std()
    bb_upper = bb_mid + 2 * bb_std
    bb_lower = bb_mid - 2 * bb_std
    d["d_bb_pct"] = (c - bb_lower) / (bb_upper - bb_lower).replace(0, np.nan)

    # 52-week high/low distance
    high_52w = d["high"].rolling(252, min_periods=20).max()
    low_52w = d["low"].rolling(252, min_periods=20).min()
    d["d_dist_52wh"] = (high_52w - c) / high_52w.replace(0, np.nan)
    d["d_dist_52wl"] = (c - low_52w) / low_52w.replace(0, np.nan)

    # Returns
    d["d_ret_1d"] = c.pct_change(1)
    d["d_ret_5d"] = c.pct_change(5)
    d["d_ret_20d"] = c.pct_change(20)

    # Keep only regime columns
    regime_cols = [col for col in d.columns if col.startswith("d_")]
    return d[regime_cols]


# ─────────────────────────────────────────────────────────────────────────────
# Hourly regime features (from 1h bars or resampled from 5m)
# ─────────────────────────────────────────────────────────────────────────────

def _compute_hourly_regime(hourly: pd.DataFrame) -> pd.DataFrame:
    """
    Lightweight regime features from 1-hour bars.
    Prefixed `h_`.
    """
    d = hourly.copy()
    c = d["close"]

    sma20h = c.rolling(20).mean()
    d["h_trend_20"] = np.where(c > sma20h, 1, -1)

    log_ret = np.log(c / c.shift(1))
    d["h_realvol_20"] = log_ret.rolling(20).std() * np.sqrt(252 * 6.5)  # ~6.5 trading hours/day

    delta = c.diff()
    gain = delta.clip(lower=0).ewm(com=13, adjust=False).mean()
    loss = (-delta).clip(lower=0).ewm(com=13, adjust=False).mean()
    rs = gain / loss.replace(0, np.nan)
    d["h_rsi_14"] = 100 - (100 / (1 + rs))

    d["h_ret_1h"] = c.pct_change(1)
    d["h_ret_4h"] = c.pct_change(4)

    regime_cols = [col for col in d.columns if col.startswith("h_")]
    return d[regime_cols]


# ─────────────────────────────────────────────────────────────────────────────
# Alignment helper (forward-fill, no look-ahead)
# ─────────────────────────────────────────────────────────────────────────────

def _align_to_intraday(
    intraday_idx: pd.DatetimeIndex,
    higher_tf_df: pd.DataFrame,
    shift_periods: int = 1,
) -> pd.DataFrame:
    """
    Align higher-timeframe features to intraday index.

    We shift the higher-TF data by `shift_periods` bars before aligning to
    ensure we only use *completed* bars (no look-ahead into the current bar).

    Steps
    -----
    1. Shift higher-TF DataFrame by 1 bar (use yesterday's daily close, not today's).
    2. Reindex to intraday timestamps.
    3. Forward-fill within each trading session.
    """
    shifted = higher_tf_df.shift(shift_periods)
    # Reindex: insert intraday timestamps, then ffill
    combined_idx = shifted.index.union(intraday_idx).sort_values()
    aligned = shifted.reindex(combined_idx).ffill()
    return aligned.reindex(intraday_idx)


# ─────────────────────────────────────────────────────────────────────────────
# MTF Fusion class
# ─────────────────────────────────────────────────────────────────────────────

class MTFFusion:
    """
    Enrich an intraday feature matrix with daily (and optionally hourly) context.

    Parameters
    ----------
    resample_hourly_from_5m : If True and no hourly_df is provided, resample
                              the intraday_df to 1h to generate hourly context.
    """

    def __init__(self, resample_hourly_from_5m: bool = True):
        self.resample_hourly_from_5m = resample_hourly_from_5m

    def enrich(
        self,
        intraday_df: pd.DataFrame,
        daily_df: pd.DataFrame,
        hourly_df: Optional[pd.DataFrame] = None,
    ) -> pd.DataFrame:
        """
        Merge daily and hourly regime features into the intraday DataFrame.

        Parameters
        ----------
        intraday_df : 5-min (or any sub-daily) feature matrix with DatetimeIndex (UTC)
        daily_df    : Daily OHLCV DataFrame with DatetimeIndex (UTC)
        hourly_df   : Optional 1-hour OHLCV DataFrame; auto-generated if None

        Returns
        -------
        Enriched intraday DataFrame with `d_*` and `h_*` columns appended.
        """
        # ── Daily regime ──────────────────────────────────────────────────────
        daily_regime = _compute_daily_regime(daily_df)
        daily_aligned = _align_to_intraday(intraday_df.index, daily_regime, shift_periods=1)

        # ── Hourly regime ─────────────────────────────────────────────────────
        if hourly_df is None and self.resample_hourly_from_5m:
            hourly_df = self._resample_to_hourly(intraday_df)

        if hourly_df is not None:
            hourly_regime = _compute_hourly_regime(hourly_df)
            hourly_aligned = _align_to_intraday(intraday_df.index, hourly_regime, shift_periods=1)
        else:
            hourly_aligned = pd.DataFrame(index=intraday_df.index)

        # ── Merge ─────────────────────────────────────────────────────────────
        result = pd.concat([intraday_df, daily_aligned, hourly_aligned], axis=1)

        # Fill any remaining NaNs in regime columns with 0 (early bars before warm-up)
        regime_cols = [c for c in result.columns if c.startswith(("d_", "h_"))]
        result[regime_cols] = result[regime_cols].fillna(0)

        logger.info(
            "MTF fusion complete: %d intraday bars × %d features (%d daily + %d hourly context cols)",
            len(result),
            result.shape[1],
            len([c for c in result.columns if c.startswith("d_")]),
            len([c for c in result.columns if c.startswith("h_")]),
        )
        return result

    @staticmethod
    def _resample_to_hourly(df: pd.DataFrame) -> pd.DataFrame:
        """Resample sub-hourly OHLCV to 1-hour bars."""
        agg = {
            "open": "first",
            "high": "max",
            "low": "min",
            "close": "last",
            "volume": "sum",
        }
        available = {k: v for k, v in agg.items() if k in df.columns}
        return df.resample("1h").agg(available).dropna(subset=["close"])

    @staticmethod
    def resample_to_daily(df: pd.DataFrame) -> pd.DataFrame:
        """Resample intraday OHLCV to daily bars (useful for building daily_df from 5m)."""
        agg = {
            "open": "first",
            "high": "max",
            "low": "min",
            "close": "last",
            "volume": "sum",
        }
        available = {k: v for k, v in agg.items() if k in df.columns}
        return df.resample("1D").agg(available).dropna(subset=["close"])

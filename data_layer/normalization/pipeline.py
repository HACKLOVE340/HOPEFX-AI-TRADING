# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
data_layer/normalization/pipeline.py
=======================================
NormalizationPipeline — real-time tick and OHLCV cleaning.

Steps applied to every tick (in order)
---------------------------------------
1. Timestamp normalisation  — ensure UTC, microsecond precision
2. Price rounding           — 4 decimal places for XAU/USD
3. Spread floor             — minimum spread = 0.01 (1 cent)
4. Mid recomputation        — mid = (bid + ask) / 2 (never trust raw mid)
5. Volume normalisation     — log-scale volume for ML features
6. OHLCV integrity check    — high >= max(open,close), low <= min(open,close)
7. Gap detection            — flag bars with > 3× average gap (session open)
8. Returns computation      — log returns for stationarity

All operations are vectorised (numpy) for OHLCV DataFrames.
Single-tick operations are pure Python for minimal latency.
"""
from __future__ import annotations

import logging
import math
from datetime import datetime, timezone
from typing import Optional

import numpy as np
import pandas as pd

from data_layer.types import GoldTick

logger = logging.getLogger(__name__)

_MIN_SPREAD   = 0.01    # $0.01 minimum spread for XAU/USD
_PRICE_ROUND  = 4       # decimal places
_LOG_VOL_CLIP = 20.0    # clip log volume at this value


class NormalizationPipeline:
    """
    Cleans and normalises ticks and OHLCV DataFrames.

    Stateless — safe to call from multiple threads.
    """

    # ── Tick normalisation ────────────────────────────────────────────────────

    def normalize_tick(self, tick: GoldTick) -> GoldTick:
        """
        Apply all normalisation steps to a single tick.

        Returns a new GoldTick with corrected fields.
        Never raises — returns the original tick on any error.
        """
        try:
            # 1. Ensure UTC timestamp
            ts = tick.timestamp
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)

            # 2. Round prices
            bid = round(tick.bid, _PRICE_ROUND)
            ask = round(tick.ask, _PRICE_ROUND)

            # 3. Spread floor
            if ask - bid < _MIN_SPREAD:
                half = _MIN_SPREAD / 2
                mid  = (bid + ask) / 2
                bid  = round(mid - half, _PRICE_ROUND)
                ask  = round(mid + half, _PRICE_ROUND)

            # 4. Recompute mid
            mid    = round((bid + ask) / 2, _PRICE_ROUND)
            spread = round(ask - bid, _PRICE_ROUND)

            return GoldTick(
                symbol     = tick.symbol,
                timestamp  = ts,
                bid        = bid,
                ask        = ask,
                mid        = mid,
                source     = tick.source,
                quality    = tick.quality,
                confidence = tick.confidence,
                spread     = spread,
                lineage_id = tick.lineage_id,
                raw        = tick.raw,
            )
        except Exception as exc:
            logger.debug("NormalizationPipeline.normalize_tick error: %s", exc)
            return tick

    # ── OHLCV DataFrame normalisation ─────────────────────────────────────────

    def normalize_ohlcv(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Clean and normalise an OHLCV DataFrame.

        Expected columns: open, high, low, close, volume
        Expected index:   DatetimeIndex (UTC)

        Returns a cleaned DataFrame with additional columns:
          log_return, log_volume, gap_flag, ohlcv_valid
        """
        if df.empty:
            return df

        df = df.copy()

        # 1. Ensure UTC index
        if df.index.tz is None:
            df.index = df.index.tz_localize("UTC")
        else:
            df.index = df.index.tz_convert("UTC")

        # 2. Sort ascending (causal order)
        df = df.sort_index()

        # 3. Drop rows with zero/negative prices
        price_cols = [c for c in ("open", "high", "low", "close") if c in df.columns]
        for col in price_cols:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        df = df.dropna(subset=price_cols)
        df = df[(df[price_cols] > 0).all(axis=1)]

        # 4. OHLCV integrity: high >= max(open,close), low <= min(open,close)
        if all(c in df.columns for c in ("open", "high", "low", "close")):
            df["high"]  = df[["high", "open", "close"]].max(axis=1)
            df["low"]   = df[["low",  "open", "close"]].min(axis=1)
            df["ohlcv_valid"] = (
                (df["high"] >= df["open"]) &
                (df["high"] >= df["close"]) &
                (df["low"]  <= df["open"]) &
                (df["low"]  <= df["close"])
            ).astype(float)

        # 5. Volume normalisation
        if "volume" in df.columns:
            df["volume"]     = pd.to_numeric(df["volume"], errors="coerce").fillna(0)
            df["log_volume"] = np.log1p(df["volume"]).clip(upper=_LOG_VOL_CLIP)

        # 6. Log returns (stationary, causal)
        if "close" in df.columns:
            df["log_return"] = np.log(df["close"] / df["close"].shift(1)).fillna(0)

        # 7. Gap detection (session open gaps)
        if "close" in df.columns and "open" in df.columns:
            gap_pct = (df["open"] - df["close"].shift(1)).abs() / df["close"].shift(1)
            avg_gap = gap_pct.rolling(20).mean().fillna(0)
            df["gap_flag"] = (gap_pct > avg_gap * 3).astype(float)

        # 8. Remove duplicate index entries (keep last)
        df = df[~df.index.duplicated(keep="last")]

        return df

    def compute_returns(self, df: pd.DataFrame, periods: list = None) -> pd.DataFrame:
        """
        Add multi-period log return columns to an OHLCV DataFrame.

        periods: list of bar counts, e.g. [1, 5, 10, 20]
        """
        if df.empty or "close" not in df.columns:
            return df

        periods = periods or [1, 5, 10, 20]
        df = df.copy()
        for p in periods:
            df[f"ret_{p}"] = np.log(
                df["close"] / df["close"].shift(p)
            ).fillna(0)
        return df


# Module-level singleton
normalization_pipeline = NormalizationPipeline()

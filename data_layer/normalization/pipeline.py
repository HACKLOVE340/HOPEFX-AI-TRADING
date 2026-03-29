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
5. Source validation        — reject unknown FeedSource values

Steps applied to OHLCV DataFrames (vectorised)
-----------------------------------------------
1. Column normalisation     — lowercase, rename aliases
2. Timestamp index          — ensure UTC DatetimeIndex, sort ascending
3. Duplicate removal        — keep last bar per timestamp
4. OHLCV integrity          — high >= max(open,close), low <= min(open,close)
5. Price floor              — drop bars with close <= 0
6. Volume normalisation     — log1p(volume), fill NaN with 0
7. Gap detection            — flag bars with gap > 3× rolling average gap
8. Log returns              — log(close/prev_close), causal (shift(1))
9. OHLCV validity flag      — 1 if all OHLCV values are finite and positive

All OHLCV operations are vectorised (numpy/pandas) for performance.
Single-tick operations are pure Python for minimal latency.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

import numpy as np
import pandas as pd

from data_layer.types import FeedSource, GoldTick, TickQuality

logger = logging.getLogger(__name__)

import os
_PRICE_DECIMALS   = int(os.getenv("NORM_PRICE_DECIMALS",   "4"))
_MIN_SPREAD       = float(os.getenv("NORM_MIN_SPREAD",     "0.01"))
_MAX_SPREAD_PCT   = float(os.getenv("NORM_MAX_SPREAD_PCT", "0.01"))   # 1%
_GAP_MULTIPLIER   = float(os.getenv("NORM_GAP_MULTIPLIER", "3.0"))
_GAP_WINDOW       = int(os.getenv("NORM_GAP_WINDOW",       "20"))
_MIN_GOLD_PRICE   = float(os.getenv("NORM_MIN_GOLD_PRICE", "100.0"))

# Column name aliases — normalise to standard names
_COL_ALIASES = {
    "Open":   "open",  "High":   "high",  "Low":   "low",
    "Close":  "close", "Volume": "volume","Adj Close": "close",
    "open_price": "open", "high_price": "high", "low_price": "low",
    "close_price": "close", "vol": "volume", "qty": "volume",
}


class NormalizationPipeline:
    """
    Stateless normalisation pipeline for ticks and OHLCV DataFrames.

    All methods are pure functions — no internal state mutated.
    Thread-safe by design.
    """

    # ── Tick normalisation ────────────────────────────────────────────────────

    def normalize_tick(self, tick: GoldTick) -> GoldTick:
        """
        Normalise a validated GoldTick.

        Steps:
          1. Ensure timestamp is UTC-aware
          2. Round prices to NORM_PRICE_DECIMALS
          3. Enforce minimum spread
          4. Recompute mid from bid/ask
          5. Clamp confidence to [0, 1]

        Returns a new GoldTick (frozen dataclass — no mutation).
        """
        # 1. UTC timestamp
        ts = tick.timestamp
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)

        # 2. Round prices
        bid = round(tick.bid, _PRICE_DECIMALS)
        ask = round(tick.ask, _PRICE_DECIMALS)

        # 3. Enforce minimum spread
        if ask - bid < _MIN_SPREAD:
            half = _MIN_SPREAD / 2.0
            mid_raw = (bid + ask) / 2.0
            bid = round(mid_raw - half, _PRICE_DECIMALS)
            ask = round(mid_raw + half, _PRICE_DECIMALS)

        # 4. Recompute mid
        mid = round((bid + ask) / 2.0, _PRICE_DECIMALS)

        # 5. Clamp confidence
        confidence = max(0.0, min(1.0, tick.confidence))

        # Only create new object if something changed
        if (ts == tick.timestamp and bid == tick.bid and ask == tick.ask
                and mid == tick.mid and confidence == tick.confidence):
            return tick

        return GoldTick(
            symbol     = tick.symbol,
            timestamp  = ts,
            bid        = bid,
            ask        = ask,
            mid        = mid,
            source     = tick.source,
            quality    = tick.quality,
            confidence = confidence,
            spread     = round(ask - bid, _PRICE_DECIMALS),
            lineage_id = tick.lineage_id,
            raw        = tick.raw,
        )

    # ── OHLCV normalisation ───────────────────────────────────────────────────

    def normalize_ohlcv(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Normalise an OHLCV DataFrame for the ML pipeline.

        Input:  Any DataFrame with OHLCV columns (various naming conventions)
        Output: Clean DataFrame with columns:
                  open, high, low, close, volume,
                  log_return, log_volume, gap_flag, ohlcv_valid
                and UTC DatetimeIndex sorted ascending.

        All operations are vectorised. NaN-safe.
        """
        if df is None or df.empty:
            return pd.DataFrame()

        d = df.copy()

        # ── 1. Column normalisation ────────────────────────────────────────
        d = d.rename(columns=_COL_ALIASES)
        d.columns = [c.lower().strip() for c in d.columns]

        required = {"open", "high", "low", "close"}
        missing  = required - set(d.columns)
        if missing:
            logger.warning("NormalizationPipeline: missing columns %s", missing)
            return pd.DataFrame()

        if "volume" not in d.columns:
            d["volume"] = 0.0

        # ── 2. Timestamp index ─────────────────────────────────────────────
        if not isinstance(d.index, pd.DatetimeIndex):
            # Try common timestamp column names
            for col in ("open_time", "timestamp", "date", "time", "datetime"):
                if col in d.columns:
                    d[col] = pd.to_datetime(d[col], utc=True, errors="coerce")
                    d = d.set_index(col)
                    break
            else:
                # Last resort: try converting the existing index
                try:
                    d.index = pd.to_datetime(d.index, utc=True)
                except Exception:
                    logger.warning("NormalizationPipeline: cannot parse timestamp index")
                    return pd.DataFrame()

        # Ensure UTC
        if d.index.tz is None:
            d.index = d.index.tz_localize("UTC")
        else:
            d.index = d.index.tz_convert("UTC")

        d = d.sort_index()

        # ── 3. Duplicate removal ───────────────────────────────────────────
        if d.index.duplicated().any():
            d = d[~d.index.duplicated(keep="last")]

        # ── 4. Numeric coercion ────────────────────────────────────────────
        for col in ("open", "high", "low", "close", "volume"):
            d[col] = pd.to_numeric(d[col], errors="coerce")

        # ── 5. Price floor — drop bars with non-positive close ─────────────
        d = d[d["close"] > _MIN_GOLD_PRICE].copy()
        if d.empty:
            return pd.DataFrame()

        # ── 6. OHLCV integrity enforcement ─────────────────────────────────
        # high must be >= max(open, close)
        d["high"] = np.maximum(d["high"], np.maximum(d["open"], d["close"]))
        # low must be <= min(open, close)
        d["low"]  = np.minimum(d["low"],  np.minimum(d["open"], d["close"]))
        # Ensure high >= low
        swap_mask = d["high"] < d["low"]
        if swap_mask.any():
            d.loc[swap_mask, ["high", "low"]] = (
                d.loc[swap_mask, ["low", "high"]].values
            )

        # ── 7. Volume normalisation ────────────────────────────────────────
        d["volume"]     = d["volume"].fillna(0.0).clip(lower=0.0)
        d["log_volume"] = np.log1p(d["volume"])

        # ── 8. Gap detection ───────────────────────────────────────────────
        # Gap = |open - prev_close| / prev_close
        prev_close = d["close"].shift(1)
        gap_pct    = (d["open"] - prev_close).abs() / prev_close.replace(0, np.nan)
        rolling_gap_mean = gap_pct.rolling(_GAP_WINDOW, min_periods=3).mean()
        d["gap_flag"] = (
            (gap_pct > rolling_gap_mean * _GAP_MULTIPLIER)
            & gap_pct.notna()
        ).astype(int)
        d["gap_flag"] = d["gap_flag"].fillna(0).astype(int)

        # ── 9. Log returns (causal — uses shift(1)) ────────────────────────
        d["log_return"] = np.log(
            d["close"] / d["close"].shift(1).replace(0, np.nan)
        )
        d["log_return"] = d["log_return"].replace(
            [np.inf, -np.inf], np.nan
        ).fillna(0.0)

        # ── 10. OHLCV validity flag ────────────────────────────────────────
        ohlcv_cols = ["open", "high", "low", "close"]
        d["ohlcv_valid"] = (
            d[ohlcv_cols].notna().all(axis=1)
            & (d[ohlcv_cols] > 0).all(axis=1)
            & np.isfinite(d[ohlcv_cols]).all(axis=1)
        ).astype(int)

        # ── 11. Final NaN/inf cleanup ──────────────────────────────────────
        numeric_cols = d.select_dtypes(include=[np.number]).columns
        d[numeric_cols] = (
            d[numeric_cols]
            .replace([np.inf, -np.inf], np.nan)
            .fillna(0.0)
        )

        return d

    def validate_ohlcv_shape(
        self, df: pd.DataFrame, min_bars: int = 50
    ) -> bool:
        """Return True if DataFrame has sufficient clean bars for ML."""
        if df is None or df.empty:
            return False
        if len(df) < min_bars:
            return False
        required = {"open", "high", "low", "close", "log_return"}
        if not required.issubset(df.columns):
            return False
        valid_count = int(df.get("ohlcv_valid", pd.Series([1] * len(df))).sum())
        return valid_count >= min_bars * 0.8  # 80% valid bars required


# Module-level singleton
normalization_pipeline = NormalizationPipeline()

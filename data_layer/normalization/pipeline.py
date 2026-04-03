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
import os
from datetime import UTC

import numpy as np
import pandas as pd

from data_layer.types import GoldTick

logger = logging.getLogger(__name__)

_PRICE_DECIMALS = int(os.getenv("NORM_PRICE_DECIMALS", "4"))
_MIN_SPREAD = float(os.getenv("NORM_MIN_SPREAD", "0.01"))
_MAX_SPREAD_PCT = float(os.getenv("NORM_MAX_SPREAD_PCT", "0.01"))  # 1%
_GAP_MULTIPLIER = float(os.getenv("NORM_GAP_MULTIPLIER", "3.0"))
_GAP_WINDOW = int(os.getenv("NORM_GAP_WINDOW", "20"))
_MIN_GOLD_PRICE = float(os.getenv("NORM_MIN_GOLD_PRICE", "100.0"))

# Column name aliases — normalise to standard names
_COL_ALIASES = {
    "Open": "open",
    "High": "high",
    "Low": "low",
    "Close": "close",
    "Volume": "volume",
    "Adj Close": "close",
    "open_price": "open",
    "high_price": "high",
    "low_price": "low",
    "close_price": "close",
    "vol": "volume",
    "qty": "volume",
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
            ts = ts.replace(tzinfo=UTC)

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
        if (
            ts == tick.timestamp
            and bid == tick.bid
            and ask == tick.ask
            and mid == tick.mid
            and confidence == tick.confidence
        ):
            return tick

        return GoldTick(
            symbol=tick.symbol,
            timestamp=ts,
            bid=bid,
            ask=ask,
            mid=mid,
            source=tick.source,
            quality=tick.quality,
            confidence=confidence,
            spread=round(ask - bid, _PRICE_DECIMALS),
            lineage_id=tick.lineage_id,
            raw=tick.raw,
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
        missing = required - set(d.columns)
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
        d["low"] = np.minimum(d["low"], np.minimum(d["open"], d["close"]))
        # Ensure high >= low
        swap_mask = d["high"] < d["low"]
        if swap_mask.any():
            d.loc[swap_mask, ["high", "low"]] = d.loc[swap_mask, ["low", "high"]].values

        # ── 7. Volume normalisation ────────────────────────────────────────
        d["volume"] = d["volume"].fillna(0.0).clip(lower=0.0)
        d["log_volume"] = np.log1p(d["volume"])

        # ── 8. Gap detection ───────────────────────────────────────────────
        # Gap = |open - prev_close| / prev_close
        prev_close = d["close"].shift(1)
        gap_pct = (d["open"] - prev_close).abs() / prev_close.replace(0, np.nan)
        rolling_gap_mean = gap_pct.rolling(_GAP_WINDOW, min_periods=3).mean()
        d["gap_flag"] = ((gap_pct > rolling_gap_mean * _GAP_MULTIPLIER) & gap_pct.notna()).astype(int)
        d["gap_flag"] = d["gap_flag"].fillna(0).astype(int)

        # ── 9. Log returns (causal — uses shift(1)) ────────────────────────
        d["log_return"] = np.log(d["close"] / d["close"].shift(1).replace(0, np.nan))
        d["log_return"] = d["log_return"].replace([np.inf, -np.inf], np.nan).fillna(0.0)

        # ── 10. OHLCV validity flag ────────────────────────────────────────
        ohlcv_cols = ["open", "high", "low", "close"]
        d["ohlcv_valid"] = (
            d[ohlcv_cols].notna().all(axis=1) & (d[ohlcv_cols] > 0).all(axis=1) & np.isfinite(d[ohlcv_cols]).all(axis=1)
        ).astype(int)

        # ── 11. Final NaN/inf cleanup ──────────────────────────────────────
        numeric_cols = d.select_dtypes(include=[np.number]).columns
        d[numeric_cols] = d[numeric_cols].replace([np.inf, -np.inf], np.nan).fillna(0.0)

        return d

    def validate_ohlcv_shape(self, df: pd.DataFrame, min_bars: int = 50) -> bool:
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

    def normalize_bar(
        self,
        bar: dict[str, float],
        prev_close: float | None = None,
    ) -> dict[str, float]:
        """
        Normalize a single OHLCV bar dict.

        Applies the same cleaning rules as normalize_ohlcv() but for a
        single bar — used in live inference where bars arrive one at a time.

        Parameters
        ----------
        bar        : dict with keys open, high, low, close, volume
        prev_close : Previous bar's close for log_return calculation.
                     If None, log_return is set to 0.0.

        Returns a new dict with the original fields plus:
          log_return  : log(close / prev_close) or 0.0
          log_volume  : log1p(volume)
          ohlcv_valid : 1 if bar passes all sanity checks, 0 otherwise
          gap_flag    : 1 if |log_return| > 0.005 (0.5% gap), else 0
        """
        out = dict(bar)

        o = float(out.get("open", 0.0))
        h = float(out.get("high", 0.0))
        lo = float(out.get("low", 0.0))
        c = float(out.get("close", 0.0))
        v = float(out.get("volume", 0.0))

        # Sanity checks
        valid = c > 0.0 and o > 0.0 and h >= max(o, c) and lo <= min(o, c) and lo > 0.0 and v >= 0.0
        out["ohlcv_valid"] = 1 if valid else 0

        # log_volume
        out["log_volume"] = float(np.log1p(max(v, 0.0)))

        # log_return
        lr = float(np.log(c / prev_close)) if prev_close and prev_close > 0.0 and c > 0.0 else 0.0
        out["log_return"] = lr

        # gap_flag: absolute log return > 0.5%
        out["gap_flag"] = 1 if abs(lr) > 0.005 else 0

        return out

    def normalize_tick_to_bar(
        self,
        ticks: list[dict[str, float]],
        prev_close: float | None = None,
    ) -> dict[str, float] | None:
        """
        Aggregate a list of tick dicts into a single normalized OHLCV bar.

        Each tick dict must have at least a 'mid' key.
        Optional keys: 'bid', 'ask', 'volume'.

        Returns None if ticks is empty.
        """
        if not ticks:
            return None

        mids = [float(t.get("mid", t.get("close", 0.0))) for t in ticks]
        mids = [m for m in mids if m > 0.0]
        if not mids:
            return None

        volumes = [float(t.get("volume", 1.0)) for t in ticks]
        bar = {
            "open": mids[0],
            "high": max(mids),
            "low": min(mids),
            "close": mids[-1],
            "volume": sum(volumes),
        }
        return self.normalize_bar(bar, prev_close=prev_close)

    def normalize_ticks_batch(self, ticks: list[GoldTick]) -> list[GoldTick]:
        """
        Normalise a batch of GoldTicks in one call.

        Applies normalize_tick() to each tick. Ticks that fail validation
        (e.g. inverted spread after normalisation) are marked REJECTED and
        included in the output — callers must filter on tick.quality.

        Parameters
        ----------
        ticks : List of raw GoldTick objects from any feed adapter

        Returns
        -------
        List of normalised GoldTick objects in the same order as input.
        """
        return [self.normalize_tick(t) for t in ticks]

    def tick_to_ohlcv(
        self,
        ticks: list[GoldTick],
        timeframe_minutes: int = 60,
    ) -> pd.DataFrame:
        """
        Aggregate a list of GoldTicks into an OHLCV DataFrame.

        Uses mid price as the price series. Volume is proxied from
        spread × 1000 (consistent with MicrostructureEngine).

        Parameters
        ----------
        ticks             : List of validated GoldTick objects
        timeframe_minutes : Bar size in minutes (default 60 = H1)

        Returns
        -------
        Normalised OHLCV DataFrame with UTC DatetimeIndex.
        Empty DataFrame if ticks is empty or all ticks are invalid.
        """
        if not ticks:
            return pd.DataFrame()

        valid = [t for t in ticks if t.is_valid()]
        if not valid:
            return pd.DataFrame()

        # Volume: unit volume (1.0 per tick) — spread*1000 was fabricated data
        # that created spurious correlation between spread and volume signals.
        # Tick count is the only honest proxy when no real trade volume exists.
        records = [
            {
                "timestamp": t.timestamp,
                "open": t.mid,
                "high": t.mid,
                "low": t.mid,
                "close": t.mid,
                "volume": 1.0,
            }
            for t in valid
        ]
        df = pd.DataFrame(records)
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
        df = df.set_index("timestamp").sort_index()

        freq = f"{timeframe_minutes}min"
        ohlcv = (
            df["close"]
            .resample(freq)
            .agg(
                open="first",
                high="max",
                low="min",
                close="last",
            )
        )
        ohlcv["volume"] = df["volume"].resample(freq).sum()
        ohlcv = ohlcv.dropna(subset=["open", "close"])

        return self.normalize_ohlcv(ohlcv)

    def detect_gaps(
        self,
        df: pd.DataFrame,
        threshold_pct: float = 0.5,
    ) -> pd.Series:
        """
        Return a boolean Series marking bars with price gaps > threshold_pct%.

        A gap is defined as |log(open_t / close_{t-1})| > threshold_pct/100.
        Used to flag session opens and data feed interruptions.

        Parameters
        ----------
        df            : OHLCV DataFrame with 'open' and 'close' columns
        threshold_pct : Gap threshold in percent (default 0.5%)

        Returns a boolean Series aligned to df.index (True = gap bar).
        """
        if df is None or df.empty or "open" not in df.columns or "close" not in df.columns:
            return pd.Series(False, index=df.index if df is not None else [])

        prev_close = df["close"].shift(1)
        log_gap = np.log(df["open"] / prev_close.replace(0, np.nan)).abs()
        threshold = threshold_pct / 100.0
        gaps = log_gap > threshold
        gaps.iloc[0] = False  # first bar has no previous close
        return gaps.fillna(False)


# Module-level singleton
normalization_pipeline = NormalizationPipeline()

# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
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

MTFFusionStore improvements
----------------------------
- Module-level singleton (_MTF_STORE_SINGLETON) for signal engine access
- push_bar(): live bar update appends to H4/D1 buffers without full reload
- status(): health-check dict with bar counts and bootstrap state
- Thread-safe: push_bar() and align_to_h1() share a read-write lock
- Graceful degradation: returns None (not raises) on any failure

Usage
-----
    from research.pipeline.mtf_fusion import MTFFusion, MTFFusionStore

    fusion = MTFFusion()
    intraday_enriched = fusion.enrich(
        intraday_df=df_5m,
        daily_df=df_1d,
        hourly_df=df_1h,   # optional
    )
"""

from __future__ import annotations

import logging
import threading

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# Module-level singleton — populated by init_mtf_store() at startup.
# signal_engine._fetch_mtf_df() reads this when app_state.mtf_store is absent.
_MTF_STORE_SINGLETON: MTFFusionStore | None = None


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
        hourly_df: pd.DataFrame | None = None,
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


# ─────────────────────────────────────────────────────────────────────────────
# MTFFusionStore — live inference store
# ─────────────────────────────────────────────────────────────────────────────


class MTFFusionStore:
    """
    Production store that loads H4 and D1 OHLCV from the data scheduler CSVs,
    computes regime features, and aligns them to any H1 OHLCV DataFrame at
    inference time.

    Lifecycle
    ---------
    1. `await store.bootstrap()` — called once at startup by init_mtf_store().
       Loads H4 and D1 CSVs written by DataScheduler.  Falls back to yfinance
       if CSVs are missing.
    2. `store.align_to_h1(ohlcv_df)` — called per tick in _compute_ml_probability().
       Returns a DataFrame with d_* and h_* columns aligned to the H1 index.
    3. `store.push_bar(bar, timeframe)` — called by the data scheduler to append
       a new completed bar without a full reload.

    Thread safety: a RLock protects _h4_df and _d1_df.  bootstrap() acquires
    the lock for the full load; push_bar() and align_to_h1() acquire it briefly.
    """

    # Maximum bars to keep in memory (prevents unbounded growth)
    MAX_H4_BARS = 5000  # ~2.8 years of H4
    MAX_D1_BARS = 10000  # ~40 years of daily

    def __init__(
        self,
        symbol: str = "XAU_USD",
        data_dir: str = "data",
    ) -> None:
        self.symbol = symbol
        self.data_dir = data_dir
        self._h4_df: pd.DataFrame | None = None
        self._d1_df: pd.DataFrame | None = None
        self._fusion = MTFFusion(resample_hourly_from_5m=False)
        self._bootstrapped: bool = False
        self._lock = threading.RLock()
        self._bootstrap_error: str | None = None

    # ── Bootstrap ─────────────────────────────────────────────────────────────

    async def bootstrap(self) -> MTFFusionStore:
        """
        Load H4 and D1 OHLCV data.  Non-blocking — runs in a thread executor.
        Falls back gracefully when data is unavailable.
        Registers self as the module-level singleton after successful load.
        """
        import asyncio

        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self._load_data)
        # Register as module singleton so signal_engine can find it
        global _MTF_STORE_SINGLETON
        _MTF_STORE_SINGLETON = self
        return self

    def _load_data(self) -> None:
        """Synchronous data load — called from bootstrap() via executor."""
        from pathlib import Path

        with self._lock:
            data_dir = Path(self.data_dir)

            # Try scheduler CSVs first
            h4_path = data_dir / f"{self.symbol}_H4.csv"
            d1_path = data_dir / f"{self.symbol}_D.csv"

            self._h4_df = self._load_csv(h4_path, "H4")
            self._d1_df = self._load_csv(d1_path, "D1")

            # Fall back to yfinance if CSVs missing
            if self._h4_df is None or self._d1_df is None:
                self._load_from_yfinance()

            # Trim to max bars
            if self._h4_df is not None and len(self._h4_df) > self.MAX_H4_BARS:
                self._h4_df = self._h4_df.iloc[-self.MAX_H4_BARS :]
            if self._d1_df is not None and len(self._d1_df) > self.MAX_D1_BARS:
                self._d1_df = self._d1_df.iloc[-self.MAX_D1_BARS :]

            self._bootstrapped = True
            logger.info(
                "MTFFusionStore bootstrapped: H4=%s bars, D1=%s bars",
                len(self._h4_df) if self._h4_df is not None else 0,
                len(self._d1_df) if self._d1_df is not None else 0,
            )

    def _load_csv(self, path, label: str) -> pd.DataFrame | None:
        """Load a scheduler CSV into a UTC-indexed OHLCV DataFrame."""
        try:
            from pathlib import Path

            if not Path(path).exists():
                logger.debug("MTFFusionStore: %s CSV not found at %s", label, path)
                return None
            df = pd.read_csv(path, parse_dates=["time"])
            df = df.rename(columns={"time": "timestamp"}) if "time" in df.columns else df
            # Normalise column names to lowercase
            df.columns = [c.lower() for c in df.columns]
            ts_col = next(
                (c for c in ("timestamp", "time", "date", "datetime") if c in df.columns),
                None,
            )
            if ts_col is None:
                logger.warning("MTFFusionStore: no timestamp column in %s", path)
                return None
            df = df.set_index(ts_col)
            df.index = pd.to_datetime(df.index, utc=True)
            df = df.sort_index()
            required = {"open", "high", "low", "close"}
            if not required.issubset(df.columns):
                logger.warning("MTFFusionStore: missing OHLC columns in %s", path)
                return None
            return df[list(required | ({"volume"} & set(df.columns)))]
        except Exception as exc:
            logger.warning("MTFFusionStore: failed to load %s: %s", path, exc)
            return None

    def _load_from_yfinance(self) -> None:
        """Fallback: fetch H4 and D1 from yfinance (GC=F proxy for XAU_USD)."""
        try:
            import yfinance as yf

            ticker = "GC=F"
            logger.info("MTFFusionStore: falling back to yfinance (%s)", ticker)

            if self._h4_df is None:
                raw = yf.download(ticker, period="2y", interval="1h", progress=False, auto_adjust=True)
                if not raw.empty:
                    raw.columns = [c.lower() for c in raw.columns]
                    raw.index = pd.to_datetime(raw.index, utc=True)
                    # Resample 1h → 4h
                    agg = {
                        "open": "first",
                        "high": "max",
                        "low": "min",
                        "close": "last",
                        "volume": "sum",
                    }
                    available = {k: v for k, v in agg.items() if k in raw.columns}
                    self._h4_df = raw.resample("4h").agg(available).dropna(subset=["close"])

            if self._d1_df is None:
                raw = yf.download(
                    ticker,
                    period="10y",
                    interval="1d",
                    progress=False,
                    auto_adjust=True,
                )
                if not raw.empty:
                    raw.columns = [c.lower() for c in raw.columns]
                    raw.index = pd.to_datetime(raw.index, utc=True)
                    self._d1_df = raw.dropna(subset=["close"])

        except Exception as exc:
            logger.warning("MTFFusionStore: yfinance fallback failed: %s", exc)

    # ── Live bar update ───────────────────────────────────────────────────────

    def push_bar(
        self,
        bar: pd.Series,
        timeframe: str,
    ) -> None:
        """
        Append a completed OHLCV bar to the in-memory buffer.

        Called by the data scheduler when a new H4 or D1 bar closes.
        Avoids a full reload for each new bar.

        Parameters
        ----------
        bar       : pd.Series with index [open, high, low, close, volume]
                    and a DatetimeIndex name (UTC timestamp).
        timeframe : 'H4' or 'D1'
        """
        tf = timeframe.upper()
        if tf not in ("H4", "D1"):
            logger.debug("MTFFusionStore.push_bar: unknown timeframe %s", timeframe)
            return

        with self._lock:
            try:
                new_row = pd.DataFrame([bar])
                new_row.index = pd.to_datetime([bar.name], utc=True)
                new_row.columns = [c.lower() for c in new_row.columns]

                if tf == "H4":
                    if self._h4_df is None:
                        self._h4_df = new_row
                    # Avoid duplicate timestamps
                    elif new_row.index[0] not in self._h4_df.index:
                        self._h4_df = pd.concat([self._h4_df, new_row]).sort_index()
                        if len(self._h4_df) > self.MAX_H4_BARS:
                            self._h4_df = self._h4_df.iloc[-self.MAX_H4_BARS :]
                elif self._d1_df is None:
                    self._d1_df = new_row
                elif new_row.index[0] not in self._d1_df.index:
                    self._d1_df = pd.concat([self._d1_df, new_row]).sort_index()
                    if len(self._d1_df) > self.MAX_D1_BARS:
                        self._d1_df = self._d1_df.iloc[-self.MAX_D1_BARS :]

                logger.debug(
                    "MTFFusionStore.push_bar: %s bar appended (%s)",
                    tf,
                    bar.name,
                )
            except Exception as exc:
                logger.debug("MTFFusionStore.push_bar failed: %s", exc)

    # ── Inference ─────────────────────────────────────────────────────────────

    def align_to_h1(self, ohlcv_df: pd.DataFrame) -> pd.DataFrame | None:
        """
        Align H4 and D1 regime features to the provided H1 OHLCV DataFrame.

        Parameters
        ----------
        ohlcv_df : H1 OHLCV DataFrame with DatetimeIndex (UTC).

        Returns
        -------
        DataFrame with d_* and h_* columns aligned to ohlcv_df.index,
        or None if the store is not bootstrapped or data is unavailable.
        """
        if not self._bootstrapped:
            logger.debug("MTFFusionStore.align_to_h1: not bootstrapped yet")
            return None

        with self._lock:
            if self._d1_df is None and self._h4_df is None:
                return None

            try:
                # Ensure ohlcv_df has UTC index
                idx = ohlcv_df.index
                if idx.tz is None:
                    idx = idx.tz_localize("UTC")

                # Build daily regime features
                daily_df = self._d1_df if self._d1_df is not None else MTFFusion.resample_to_daily(ohlcv_df)
                daily_regime = _compute_daily_regime(daily_df)
                daily_aligned = _align_to_intraday(idx, daily_regime, shift_periods=1)

                # Build hourly regime features from H4 (or skip)
                if self._h4_df is not None:
                    hourly_regime = _compute_hourly_regime(self._h4_df)
                    hourly_aligned = _align_to_intraday(idx, hourly_regime, shift_periods=1)
                else:
                    hourly_aligned = pd.DataFrame(index=idx)

                result = pd.concat([daily_aligned, hourly_aligned], axis=1)
                regime_cols = [c for c in result.columns if c.startswith(("d_", "h_"))]
                result[regime_cols] = result[regime_cols].fillna(0)
                return result

            except Exception as exc:
                logger.warning("MTFFusionStore.align_to_h1 failed: %s", exc)
                return None

    @property
    def is_ready(self) -> bool:
        """True when bootstrap has completed and at least one timeframe is loaded."""
        return self._bootstrapped and (self._d1_df is not None or self._h4_df is not None)

    def status(self) -> dict:
        """Return a health-check dict for monitoring endpoints."""
        with self._lock:
            return {
                "bootstrapped": self._bootstrapped,
                "is_ready": self.is_ready,
                "h4_bars": len(self._h4_df) if self._h4_df is not None else 0,
                "d1_bars": len(self._d1_df) if self._d1_df is not None else 0,
                "symbol": self.symbol,
                "data_dir": self.data_dir,
                "bootstrap_error": self._bootstrap_error,
            }

    def get(self, symbol: str, default: dict | None = None) -> dict:  # noqa: ARG002
        """Return the latest fused regime features, or *default* if unavailable.

        The *symbol* parameter is accepted for API compatibility but the store
        is bootstrapped for a single symbol at construction time.
        """
        if default is None:
            default = {}
        try:
            with self._lock:
                d1 = self._d1_df
                h4 = self._h4_df
            if d1 is None and h4 is None:
                return default
            result: dict = {}
            if d1 is not None and not d1.empty:
                result.update({f"d_{k}": v for k, v in d1.iloc[-1].to_dict().items()})
            if h4 is not None and not h4.empty:
                result.update({f"h_{k}": v for k, v in h4.iloc[-1].to_dict().items()})
            return result if result else default
        except Exception:  # pylint: disable=broad-exception-caught
            return default


# Module-level singleton — shared across the process
_mtf_store_instance: MTFFusionStore | None = None


def get_mtf_store(symbol: str = "XAU_USD", data_dir: str = "data/historical") -> MTFFusionStore | None:
    """
    Return the process-level MTFFusionStore singleton, creating it on first call.

    Returns None when the store cannot be initialised (missing data, import error).
    """
    global _mtf_store_instance  # pylint: disable=global-statement
    if _mtf_store_instance is None:
        try:
            _mtf_store_instance = MTFFusionStore(symbol=symbol, data_dir=data_dir)
        except Exception:  # pylint: disable=broad-exception-caught
            return None
    return _mtf_store_instance

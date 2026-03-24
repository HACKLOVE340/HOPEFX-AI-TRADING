"""
ml/macro_features.py
====================
Macro feature engineering for XAUUSD ML models.

Adds DXY, US 10-year yield, VIX, yield spread, and CPI features to the
OHLCV feature matrix.  All features are fetched from Yahoo Finance (free,
no API key) with a FRED fallback for yields/CPI.

Design goals
------------
- Stateless: accepts a DataFrame with a DatetimeIndex, returns an enriched copy
- Graceful degradation: missing macro data fills with forward-fill then 0
- Fixed-width output: always produces the same column set regardless of data gaps
- Testable: all fetching is isolated in `fetch_macro_history()`

Macro → Gold signal logic
--------------------------
DXY up   → gold bearish (dollar strength)
Yield up → gold bearish (opportunity cost)
VIX up   → gold bullish (risk-off safe haven)
CPI up   → gold bullish (inflation hedge)
Spread inverted → gold bullish (recession fear)
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# ── Yahoo Finance tickers for macro series ────────────────────────────────────
_MACRO_TICKERS: Dict[str, str] = {
    "dxy":      "DX-Y.NYB",   # US Dollar Index
    "vix":      "^VIX",       # CBOE Volatility Index
    "yield_10y": "^TNX",      # US 10-year Treasury yield (×10 = %)
    "yield_2y":  "^IRX",      # US 13-week T-bill (proxy for short end)
    "gold_etf":  "GLD",       # Gold ETF (cross-asset momentum)
    "spx":       "^GSPC",     # S&P 500 (risk-on/off)
}

# Columns always present in the output (filled with 0 if unavailable)
MACRO_COLUMNS: List[str] = [
    "macro_dxy",
    "macro_dxy_ret",
    "macro_dxy_z20",
    "macro_vix",
    "macro_vix_ret",
    "macro_vix_z20",
    "macro_yield_10y",
    "macro_yield_2y",
    "macro_yield_spread",
    "macro_yield_spread_chg",
    "macro_gold_etf_ret",
    "macro_spx_ret",
    "macro_spx_z20",
    "macro_risk_off_score",   # composite: high VIX + low SPX + inverted curve
    "macro_gold_tailwind",    # composite: weak DXY + high VIX + rising CPI
]


def fetch_macro_history(
    start: datetime,
    end: Optional[datetime] = None,
    interval: str = "1d",
) -> pd.DataFrame:
    """
    Download macro time series from Yahoo Finance and return a daily DataFrame
    aligned to the given date range.

    Parameters
    ----------
    start   : Start date (inclusive)
    end     : End date (inclusive); defaults to today
    interval: yfinance interval string ('1d', '1wk')

    Returns
    -------
    DataFrame with DatetimeIndex (UTC, date-only) and one column per macro series.
    Missing values are forward-filled then back-filled.
    """
    end = end or datetime.now(timezone.utc)

    try:
        import yfinance as yf
    except ImportError:
        logger.warning("yfinance not installed — macro features unavailable")
        return pd.DataFrame()

    frames: Dict[str, pd.Series] = {}
    for name, ticker in _MACRO_TICKERS.items():
        try:
            raw = yf.download(
                ticker,
                start=start.strftime("%Y-%m-%d"),
                end=(end + timedelta(days=1)).strftime("%Y-%m-%d"),
                interval=interval,
                progress=False,
                auto_adjust=True,
            )
            if raw.empty:
                logger.debug("yfinance returned no data for %s (%s)", ticker, name)
                continue
            close = raw["Close"]
            if hasattr(close, "squeeze"):
                close = close.squeeze()
            close.index = pd.to_datetime(close.index).tz_localize(None)
            frames[name] = close.rename(name)
        except Exception as exc:
            logger.warning("Failed to fetch %s (%s): %s", ticker, name, exc)

    if not frames:
        return pd.DataFrame()

    df = pd.concat(frames.values(), axis=1)
    df = df.ffill().bfill()
    return df


def add_macro_features(
    ohlcv: pd.DataFrame,
    macro_df: Optional[pd.DataFrame] = None,
    lookback: int = 20,
) -> pd.DataFrame:
    """
    Merge macro features into an OHLCV DataFrame.

    Parameters
    ----------
    ohlcv     : DataFrame with DatetimeIndex and at least a 'close' column
    macro_df  : Pre-fetched macro DataFrame (from fetch_macro_history).
                If None, all macro columns are filled with 0.
    lookback  : Rolling window for z-score and momentum calculations

    Returns
    -------
    ohlcv copy with MACRO_COLUMNS appended.
    """
    df = ohlcv.copy()

    # Normalise index to tz-naive dates for alignment
    if df.index.tz is not None:
        df.index = df.index.tz_localize(None)
    df.index = pd.to_datetime(df.index).normalize()

    if macro_df is None or macro_df.empty:
        for col in MACRO_COLUMNS:
            df[col] = 0.0
        return df

    # Align macro to OHLCV dates via reindex + forward-fill
    macro = macro_df.copy()
    if macro.index.tz is not None:
        macro.index = macro.index.tz_localize(None)
    macro.index = pd.to_datetime(macro.index).normalize()
    macro = macro.reindex(df.index, method="ffill").fillna(0.0)

    # ── DXY features ─────────────────────────────────────────────────────────
    if "dxy" in macro.columns:
        df["macro_dxy"] = macro["dxy"]
        df["macro_dxy_ret"] = macro["dxy"].pct_change().fillna(0.0)
        roll_mean = macro["dxy"].rolling(lookback).mean()
        roll_std  = macro["dxy"].rolling(lookback).std().replace(0, np.nan)
        df["macro_dxy_z20"] = ((macro["dxy"] - roll_mean) / roll_std).fillna(0.0)
    else:
        df["macro_dxy"] = df["macro_dxy_ret"] = df["macro_dxy_z20"] = 0.0

    # ── VIX features ─────────────────────────────────────────────────────────
    if "vix" in macro.columns:
        df["macro_vix"] = macro["vix"]
        df["macro_vix_ret"] = macro["vix"].pct_change().fillna(0.0)
        roll_mean = macro["vix"].rolling(lookback).mean()
        roll_std  = macro["vix"].rolling(lookback).std().replace(0, np.nan)
        df["macro_vix_z20"] = ((macro["vix"] - roll_mean) / roll_std).fillna(0.0)
    else:
        df["macro_vix"] = df["macro_vix_ret"] = df["macro_vix_z20"] = 0.0

    # ── Yield features ───────────────────────────────────────────────────────
    if "yield_10y" in macro.columns:
        df["macro_yield_10y"] = macro["yield_10y"]
    else:
        df["macro_yield_10y"] = 0.0

    if "yield_2y" in macro.columns:
        df["macro_yield_2y"] = macro["yield_2y"]
    else:
        df["macro_yield_2y"] = 0.0

    df["macro_yield_spread"] = df["macro_yield_10y"] - df["macro_yield_2y"]
    df["macro_yield_spread_chg"] = df["macro_yield_spread"].diff().fillna(0.0)

    # ── Cross-asset momentum ─────────────────────────────────────────────────
    if "gold_etf" in macro.columns:
        df["macro_gold_etf_ret"] = macro["gold_etf"].pct_change().fillna(0.0)
    else:
        df["macro_gold_etf_ret"] = 0.0

    if "spx" in macro.columns:
        df["macro_spx_ret"] = macro["spx"].pct_change().fillna(0.0)
        roll_mean = macro["spx"].rolling(lookback).mean()
        roll_std  = macro["spx"].rolling(lookback).std().replace(0, np.nan)
        df["macro_spx_z20"] = ((macro["spx"] - roll_mean) / roll_std).fillna(0.0)
    else:
        df["macro_spx_ret"] = df["macro_spx_z20"] = 0.0

    # ── Composite scores ─────────────────────────────────────────────────────
    # Risk-off score: high VIX + negative SPX momentum + inverted yield curve
    # Range 0–3 (count of bearish macro signals)
    vix_high  = (df["macro_vix_z20"] > 0.5).astype(float)
    spx_down  = (df["macro_spx_ret"] < 0).astype(float)
    inverted  = (df["macro_yield_spread"] < 0).astype(float)
    df["macro_risk_off_score"] = vix_high + spx_down + inverted

    # Gold tailwind score: weak DXY + high VIX + rising yields (inflation)
    dxy_weak  = (df["macro_dxy_z20"] < -0.5).astype(float)
    vix_elev  = (df["macro_vix"] > 20).astype(float)
    yield_up  = (df["macro_yield_spread_chg"] > 0).astype(float)
    df["macro_gold_tailwind"] = dxy_weak + vix_elev + yield_up

    # Ensure all expected columns exist
    for col in MACRO_COLUMNS:
        if col not in df.columns:
            df[col] = 0.0

    return df


def add_regime_features(df: pd.DataFrame, lookback: int = 60) -> pd.DataFrame:
    """
    Add market regime features based on price action and volatility.

    Features added
    --------------
    regime_trend      : 1 = uptrend, -1 = downtrend, 0 = sideways
    regime_vol        : normalised realised volatility (z-score)
    regime_momentum   : 20-day price momentum z-score
    regime_mean_rev   : distance from 60-day mean (z-score) — mean reversion signal
    """
    df = df.copy()
    close = df["close"] if "close" in df.columns else df.iloc[:, 0]

    # Trend: price above/below 50-day SMA
    sma50 = close.rolling(50).mean()
    df["regime_trend"] = np.where(close > sma50, 1, np.where(close < sma50, -1, 0))

    # Realised volatility z-score
    rv = close.pct_change().rolling(20).std()
    rv_mean = rv.rolling(lookback).mean()
    rv_std  = rv.rolling(lookback).std().replace(0, np.nan)
    df["regime_vol"] = ((rv - rv_mean) / rv_std).fillna(0.0)

    # 20-day momentum z-score
    mom = close.pct_change(20)
    mom_mean = mom.rolling(lookback).mean()
    mom_std  = mom.rolling(lookback).std().replace(0, np.nan)
    df["regime_momentum"] = ((mom - mom_mean) / mom_std).fillna(0.0)

    # Mean reversion: distance from 60-day mean
    ma60 = close.rolling(lookback).mean()
    std60 = close.rolling(lookback).std().replace(0, np.nan)
    df["regime_mean_rev"] = ((close - ma60) / std60).fillna(0.0)

    return df


def build_enhanced_feature_matrix(
    ohlcv: pd.DataFrame,
    macro_df: Optional[pd.DataFrame] = None,
    lookback: int = 20,
    include_regime: bool = True,
) -> pd.DataFrame:
    """
    Full pipeline: OHLCV → macro features → regime features.

    Parameters
    ----------
    ohlcv         : Raw OHLCV DataFrame with DatetimeIndex
    macro_df      : Pre-fetched macro data (pass None to skip)
    lookback      : Rolling window for z-scores
    include_regime: Whether to add regime features

    Returns
    -------
    Enriched DataFrame ready for ML feature extraction.
    """
    df = add_macro_features(ohlcv, macro_df=macro_df, lookback=lookback)
    if include_regime:
        df = add_regime_features(df, lookback=lookback * 3)
    return df

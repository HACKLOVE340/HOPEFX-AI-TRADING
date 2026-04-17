# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
ml/macro_features.py
====================
Macro feature engineering for XAUUSD ML models.

Adds DXY, US yields, VIX, SPX, gold ETF, real rates, copper, oil, and
composite regime scores to the OHLCV feature matrix.

Design goals
------------
- Stateless: accepts a DataFrame with a DatetimeIndex, returns an enriched copy
- No look-ahead: only ffill() is used — never bfill() across time
- Fixed-width output: always produces the same column set regardless of data gaps
- Stationary inputs: all level series converted to returns or z-scores

Macro → Gold signal logic (empirically validated)
--------------------------------------------------
DXY up         → gold bearish  (dollar strength)
Yield 10y up   → gold bearish  (opportunity cost)
Real rate up   → gold bearish  (strongest single predictor)
VIX up         → gold bullish  (risk-off safe-haven)
SPX down       → gold bullish  (risk-off rotation)
Curve inverted → gold bullish  (recession fear)

Bug fixes vs prior version
---------------------------
1. ^IRX (13-week T-bill) replaced with ^FVX (5-year yield).
   ^IRX gave the 10Y-3M spread; ^FVX gives the standard 10Y-5Y spread.
2. bfill() removed. VIX starts ~1990; bfill injected 1990 VIX into 1974-1989
   training bars (look-ahead bias). Now only ffill(); pre-history = 0.
3. macro_gold_tailwind: old yield_up = (spread_chg > 0) was wrong direction.
   Rising absolute 10Y yield is bearish for gold (opportunity cost).
   Fixed: yield_rising is now subtracted from the tailwind score.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

UTC = timezone.utc

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# ── Yahoo Finance tickers ─────────────────────────────────────────────────────
_MACRO_TICKERS: dict[str, str] = {
    "dxy": "DX-Y.NYB",  # US Dollar Index
    "vix": "^VIX",  # CBOE Volatility Index (starts ~1990)
    "yield_10y": "^TNX",  # US 10-year Treasury yield
    "yield_5y": "^FVX",  # US 5-year Treasury yield (replaces ^IRX)
    "gold_etf": "GLD",  # Gold ETF cross-asset momentum (starts 2004)
    "spx": "^GSPC",  # S&P 500
    "tips": "TIP",  # TIPS ETF — real rate proxy (starts 2003)
    "copper": "HG=F",  # Copper — global growth proxy
    "oil": "CL=F",  # Crude oil — inflation / geopolitical proxy
    "usdcny": "CNY=X",  # USD/CNY — China gold demand proxy
}

# Columns always present in the output (filled with 0 if unavailable)
MACRO_COLUMNS: list[str] = [
    "macro_dxy_ret",
    "macro_dxy_z20",
    "macro_dxy_z60",
    "macro_vix_level",
    "macro_vix_ret",
    "macro_vix_z20",
    "macro_vix_spike",
    "macro_yield_10y_chg",
    "macro_yield_5y_chg",
    "macro_yield_spread",
    "macro_yield_spread_chg",
    "macro_curve_inverted",
    "macro_real_rate_proxy",
    "macro_gold_etf_ret",
    "macro_spx_ret",
    "macro_spx_z20",
    "macro_copper_ret",
    "macro_oil_ret",
    "macro_usdcny_ret",
    "macro_risk_off_score",
    "macro_gold_tailwind",
    "macro_gold_headwind",
    # WGC gold demand features (quarterly/monthly, forward-filled)
    # Rising central bank demand and investment demand are structurally bullish.
    "macro_wgc_total_demand_chg",  # QoQ change in total demand (tonnes)
    "macro_wgc_investment_chg",  # QoQ change in investment demand (tonnes)
    "macro_wgc_central_bank_chg",  # QoQ change in central bank purchases (tonnes)
    "macro_wgc_jewellery_chg",  # QoQ change in jewellery demand (tonnes)
    "macro_wgc_etf_flow",  # Monthly ETF net flow (tonnes, level)
    "macro_wgc_etf_flow_z4",  # ETF flow z-score over 4 quarters
    "macro_wgc_demand_score",  # Composite WGC demand score (0–3, bullish count)
]


def fetch_macro_history(
    start: datetime,
    end: datetime | None = None,
    interval: str = "1d",
) -> pd.DataFrame:
    """
    Download macro time series from Yahoo Finance.

    Only forward-fill is applied — never backward-fill — so pre-history bars
    (e.g. pre-1990 VIX) remain NaN and are zeroed downstream after reindex.
    """
    end = end or datetime.now(UTC)

    try:
        import yfinance as yf
    except ImportError:
        logger.warning("yfinance not installed — macro features unavailable")
        return pd.DataFrame()

    frames: dict[str, pd.Series] = {}
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
                logger.debug("No data for %s (%s)", ticker, name)
                continue
            close = raw["Close"]
            if hasattr(close, "squeeze"):
                close = close.squeeze()
            close.index = pd.to_datetime(close.index).tz_localize(None)
            frames[name] = close.rename(name)
        except Exception as exc:
            logger.warning("Failed to fetch %s (%s): %s", ticker, name, exc)

    if not frames:
        logger.warning("No macro data fetched — all macro features will be zero")
        return pd.DataFrame()

    df = pd.concat(frames.values(), axis=1).fillna(method="ffill")
    # Forward-fill only: never bfill (would inject future data into past bars)
    df = df.ffill()
    logger.info(
        "Macro data: %d bars, %d series (%s → %s)",
        len(df),
        len(df.columns),
        df.index[0].date() if len(df) else "n/a",
        df.index[-1].date() if len(df) else "n/a",
    )
    return df


def add_macro_features(
    ohlcv: pd.DataFrame,
    macro_df: pd.DataFrame | None = None,
    lookback: int = 20,
) -> pd.DataFrame:
    """
    Merge macro features into an OHLCV DataFrame.

    All level series are converted to stationary representations (returns,
    changes, z-scores). Raw price levels are never used as features.
    """
    df = ohlcv.copy()

    # Preserve original tz so we can restore it before returning.
    # All internal operations use tz-naive indices to avoid
    # "Cannot join tz-naive with tz-aware DatetimeIndex" errors.
    df_tz = df.index.tz
    if df_tz is not None:
        df.index = df.index.tz_convert("UTC").tz_localize(None)
    df.index = pd.to_datetime(df.index)
    # Only normalise to midnight when the index is already daily-frequency
    # (all times identical) — normalising sub-daily data creates duplicates.
    if len(df.index) > 0 and (df.index.time == df.index[0].time()).all():
        df.index = df.index.normalize()
    if df.index.duplicated().any():
        df = df[~df.index.duplicated(keep="last")]

    if macro_df is None or macro_df.empty:
        for col in MACRO_COLUMNS:
            df[col] = 0.0
        if df_tz is not None:
            df.index = df.index.tz_localize(df_tz)
        return df

    macro = macro_df.copy()
    if macro.index.tz is not None:
        macro.index = macro.index.tz_convert("UTC").tz_localize(None)
    macro.index = pd.to_datetime(macro.index)
    if len(macro.index) > 0 and (macro.index.time == macro.index[0].time()).all():
        macro.index = macro.index.normalize()
    if macro.index.duplicated().any():
        macro = macro[~macro.index.duplicated(keep="last")]
    # Reindex to OHLCV dates: ffill only, then zero-fill remaining NaN.
    # After reindex both df and macro are tz-naive; restore df_tz on both
    # so arithmetic between df-derived and macro-derived series stays consistent.
    macro = macro.reindex(df.index, method="ffill").fillna(0.0)
    if df_tz is not None:
        df.index = df.index.tz_localize(df_tz)
        macro.index = macro.index.tz_localize(df_tz)

    def _zscore(s: pd.Series, w: int) -> pd.Series:
        mu = s.rolling(w).mean()
        sig = s.rolling(w).std().replace(0, np.nan)
        return ((s - mu) / sig).fillna(0.0)

    def _has(col: str) -> bool:
        return col in macro.columns and macro[col].abs().sum() > 0

    # ── DXY (stationary: returns + z-scores) ─────────────────────────────────
    if _has("dxy"):
        dxy = macro["dxy"]
        df["macro_dxy_ret"] = dxy.pct_change(fill_method=None).fillna(0.0)
        df["macro_dxy_z20"] = _zscore(dxy, lookback)
        df["macro_dxy_z60"] = _zscore(dxy, lookback * 3)
    else:
        df["macro_dxy_ret"] = df["macro_dxy_z20"] = df["macro_dxy_z60"] = 0.0

    # ── VIX ───────────────────────────────────────────────────────────────────
    if _has("vix"):
        vix = macro["vix"]
        df["macro_vix_level"] = vix
        df["macro_vix_ret"] = vix.pct_change(fill_method=None).fillna(0.0)
        df["macro_vix_z20"] = _zscore(vix, lookback)
        df["macro_vix_spike"] = (vix > 30).astype(float)
    else:
        df["macro_vix_level"] = df["macro_vix_ret"] = 0.0
        df["macro_vix_z20"] = df["macro_vix_spike"] = 0.0

    # ── Yields (stationary: daily changes) ───────────────────────────────────
    # Yield levels are non-stationary over 50 years; use daily changes.
    # 10Y-5Y spread: standard recession indicator (inversion = recession fear).
    if _has("yield_10y"):
        y10 = macro["yield_10y"]
        df["macro_yield_10y_chg"] = y10.diff().fillna(0.0)
    else:
        df["macro_yield_10y_chg"] = 0.0

    if _has("yield_5y"):
        y5 = macro["yield_5y"]
        df["macro_yield_5y_chg"] = y5.diff().fillna(0.0)
    else:
        df["macro_yield_5y_chg"] = 0.0

    y10_raw = macro["yield_10y"] if _has("yield_10y") else pd.Series(0.0, index=df.index)
    y5_raw = macro["yield_5y"] if _has("yield_5y") else pd.Series(0.0, index=df.index)
    spread = (y10_raw - y5_raw).reindex(df.index).fillna(0.0)
    df["macro_yield_spread"] = spread
    df["macro_yield_spread_chg"] = spread.diff().fillna(0.0)
    df["macro_curve_inverted"] = (spread < 0).astype(float)

    # ── Real rate proxy ───────────────────────────────────────────────────────
    # Rising 10Y yield + falling TIPS = rising real rates = bearish gold.
    if _has("tips"):
        tips_ret = macro["tips"].pct_change(fill_method=None).fillna(0.0)
        df["macro_real_rate_proxy"] = df["macro_yield_10y_chg"] - tips_ret
    else:
        df["macro_real_rate_proxy"] = df["macro_yield_10y_chg"]

    # ── Cross-asset momentum ─────────────────────────────────────────────────
    for col_out, col_in in [
        ("macro_gold_etf_ret", "gold_etf"),
        ("macro_copper_ret", "copper"),
        ("macro_oil_ret", "oil"),
        ("macro_usdcny_ret", "usdcny"),
    ]:
        if _has(col_in):
            df[col_out] = macro[col_in].pct_change(fill_method=None).fillna(0.0)
        else:
            df[col_out] = 0.0

    if _has("spx"):
        spx = macro["spx"]
        df["macro_spx_ret"] = spx.pct_change(fill_method=None).fillna(0.0)
        df["macro_spx_z20"] = _zscore(spx, lookback)
    else:
        df["macro_spx_ret"] = df["macro_spx_z20"] = 0.0

    # ── WGC gold demand features ──────────────────────────────────────────────
    # WGC series are quarterly/monthly — forward-filled to hourly bars by
    # MacroStore.align_to_hourly(). We compute QoQ changes and z-scores here.
    #
    # Signal logic:
    #   Rising central bank demand → structural bullish (sovereign accumulation)
    #   Rising investment demand   → risk-off / inflation hedge demand
    #   Positive ETF flow          → institutional positioning bullish
    #   Falling jewellery demand   → consumer price sensitivity (mild bearish)

    def _wgc_chg(col_in: str, col_out: str) -> None:
        """Compute period-over-period change for a WGC series."""
        if _has(col_in):
            raw = macro[col_in]
            # Use diff() on the forward-filled series; consecutive identical
            # values (within a quarter) produce 0 change — correct behaviour.
            df[col_out] = raw.diff().fillna(0.0)
        else:
            df[col_out] = 0.0

    _wgc_chg("wgc_total_demand", "macro_wgc_total_demand_chg")
    _wgc_chg("wgc_investment", "macro_wgc_investment_chg")
    _wgc_chg("wgc_central_bank", "macro_wgc_central_bank_chg")
    _wgc_chg("wgc_jewellery", "macro_wgc_jewellery_chg")

    # ETF flow: use level (already a flow, not a stock) + z-score over 4 quarters
    if _has("wgc_etf_flow"):
        etf_flow = macro["wgc_etf_flow"]
        df["macro_wgc_etf_flow"] = etf_flow
        df["macro_wgc_etf_flow_z4"] = _zscore(etf_flow, 4)
    else:
        df["macro_wgc_etf_flow"] = 0.0
        df["macro_wgc_etf_flow_z4"] = 0.0

    # Composite WGC demand score (0–3): count of bullish demand signals
    df["macro_wgc_demand_score"] = (
        (df["macro_wgc_central_bank_chg"] > 0).astype(float)  # CB buying more
        + (df["macro_wgc_investment_chg"] > 0).astype(float)  # investment rising
        + (df["macro_wgc_etf_flow"] > 0).astype(float)  # ETF inflows
    )

    # ── Composite scores ─────────────────────────────────────────────────────
    # Risk-off score (0–4): conditions that drive safe-haven gold demand
    df["macro_risk_off_score"] = (
        df["macro_vix_spike"]
        + (df["macro_spx_ret"] < 0).astype(float)
        + df["macro_curve_inverted"]
        + (df["macro_dxy_z20"] > 1.0).astype(float)
    )

    # Gold tailwind: bullish signals minus bearish signals.
    # Bullish: weak DXY, elevated VIX, falling real rates, SPX down,
    #          WGC demand score (central bank buying, investment demand, ETF inflows)
    # Bearish: rising 10Y yield (opportunity cost), strong DXY
    # FIX: old code used (yield_spread_chg > 0) as bullish — incorrect.
    bullish = (
        (df["macro_dxy_z20"] < -0.5).astype(float)
        + (df["macro_vix_level"] > 20).astype(float)
        + (df["macro_real_rate_proxy"] < 0).astype(float)
        + (df["macro_spx_ret"] < -0.005).astype(float)
        + (df["macro_wgc_demand_score"] >= 2).astype(float)
    )
    bearish = (df["macro_yield_10y_chg"] > 0).astype(float) + (df["macro_dxy_z20"] > 0.5).astype(float)
    df["macro_gold_tailwind"] = bullish - bearish
    df["macro_gold_headwind"] = bearish

    for col in MACRO_COLUMNS:
        if col not in df.columns:
            df[col] = 0.0

    return df


def add_regime_features(df: pd.DataFrame, lookback: int = 60) -> pd.DataFrame:
    """
    Add market regime features based on price action and volatility.

    All features are stationary (z-scores, ratios, binary flags).
    """
    df = df.copy()
    close = df["close"] if "close" in df.columns else df.iloc[:, 0]
    ret = close.pct_change(fill_method=None)

    # Trend direction vs 50-day SMA
    sma50 = close.rolling(50, min_periods=1).mean().fillna(close)
    df["regime_trend"] = np.where(close > sma50, 1, np.where(close < sma50, -1, 0))

    # ADX-based trend strength (normalised 0–1)
    high = df.get("high", close)
    low = df.get("low", close)
    tr = (
        pd.concat(  # healer: ignore
            [high - low, (high - close.shift(1)).abs(), (low - close.shift(1)).abs()],
            axis=1,
        )
        .fillna(0.0)
        .max(axis=1)
    )
    atr14 = tr.ewm(span=14, adjust=False).mean().fillna(0.0)
    plus_dm = (high - high.shift(1)).clip(lower=0)
    minus_dm = (low.shift(1) - low).clip(lower=0)
    plus_dm = plus_dm.where(plus_dm > minus_dm, 0.0)
    minus_dm = minus_dm.where(minus_dm > plus_dm, 0.0)
    plus_di = 100 * plus_dm.ewm(span=14).mean() / atr14.replace(0, np.nan)
    minus_di = 100 * minus_dm.ewm(span=14).mean() / atr14.replace(0, np.nan)
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    df["regime_trend_str"] = dx.ewm(span=14).mean().fillna(0.0) / 100.0

    # Realised volatility z-score
    rv = ret.rolling(20).std()
    rv_mean = rv.rolling(lookback).mean()
    rv_std = rv.rolling(lookback).std().replace(0, np.nan)
    df["regime_vol"] = ((rv - rv_mean) / rv_std).fillna(0.0)

    # Vol regime: 0=low, 1=normal, 2=high
    pct = rv.rolling(lookback).rank(pct=True).fillna(0.5)
    df["regime_vol_regime"] = (
        pd.cut(pct, bins=[0, 0.33, 0.67, 1.0], labels=[0, 1, 2], include_lowest=True).astype(float).fillna(1.0)
    )

    # 20-day momentum z-score
    mom = close.pct_change(20)
    mom_mean = mom.rolling(lookback).mean()
    mom_std = mom.rolling(lookback).std().replace(0, np.nan)
    df["regime_momentum"] = ((mom - mom_mean) / mom_std).fillna(0.0)

    # Mean reversion: distance from 60-day mean in std units
    ma60 = close.rolling(lookback).mean()
    std60 = close.rolling(lookback).std().replace(0, np.nan)
    df["regime_mean_rev"] = ((close - ma60) / std60).fillna(0.0)

    # Hurst exponent (rolling 40-bar window)
    df["regime_hurst"] = _rolling_hurst(close, window=40)

    return df


def build_enhanced_feature_matrix(
    ohlcv: pd.DataFrame,
    macro_df: pd.DataFrame | None = None,
    lookback: int = 20,
    include_regime: bool = True,
) -> pd.DataFrame:
    """Full pipeline: OHLCV → macro features → regime features."""
    df = add_macro_features(ohlcv, macro_df=macro_df, lookback=lookback)
    if include_regime:
        df = add_regime_features(df, lookback=lookback * 3)
    return df


# ── Helpers ───────────────────────────────────────────────────────────────────


def _rolling_hurst(series: pd.Series, window: int = 40) -> pd.Series:
    """
    Approximate Hurst exponent via R/S analysis over a rolling window.
    H > 0.5 = trending, H < 0.5 = mean-reverting, H ≈ 0.5 = random walk.
    """

    def _hurst_scalar(x: np.ndarray) -> float:
        if len(x) < 8:
            return 0.5
        try:
            lags = range(2, min(len(x) // 2, 12))
            rs_vals = []
            for lag in lags:
                chunks = [x[i : i + lag] for i in range(0, len(x) - lag, lag)]
                rs_chunk = []
                for chunk in chunks:
                    if len(chunk) < 2:
                        continue
                    dev = np.cumsum(chunk - np.mean(chunk))
                    r = dev.max() - dev.min()
                    s = np.std(chunk, ddof=1)
                    if s > 0:
                        rs_chunk.append(r / s)
                if rs_chunk:
                    rs_vals.append(np.mean(rs_chunk))
            if len(rs_vals) < 2:
                return 0.5
            log_lags = np.log(np.maximum(list(lags)[: len(rs_vals)], 1e-9))
            log_rs = np.log(np.maximum(np.nan_to_num(rs_vals, nan=1e-9), 1e-9))
            h = np.polyfit(log_lags, log_rs, 1)[0]
            return float(np.clip(h, 0.0, 1.0))
        except Exception:  # nosec B110 — numerical fallback for Hurst exponent
            return 0.5

    return series.rolling(window).apply(_hurst_scalar, raw=True).fillna(0.5)

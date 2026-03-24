"""
ml/advanced_features.py
=======================
Advanced feature engineering for XAUUSD ML models targeting 85-90% accuracy.

Techniques used:
- Price action patterns (candlestick, swing highs/lows, fractals)
- Multi-timeframe momentum (5/10/20/60 bar)
- Volatility regime features (GARCH-proxy, realized vol ratio)
- Market microstructure (spread proxy, efficiency ratio)
- Cross-asset momentum (gold vs DXY, gold vs bonds)
- Calendar/seasonality features
- Target engineering: filtered signal (only trade high-confidence bars)
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from typing import Optional


# ─────────────────────────────────────────────────────────────────────────────
# Price-action & candlestick features
# ─────────────────────────────────────────────────────────────────────────────

def add_price_action_features(df: pd.DataFrame) -> pd.DataFrame:
    """Candlestick body/wick ratios, engulfing, doji, pin-bar."""
    d = df.copy()
    o, h, l, c = d["open"], d["high"], d["low"], d["close"]

    body = (c - o).abs()
    candle_range = (h - l).replace(0, np.nan)

    d["pa_body_ratio"]   = body / candle_range          # 0=doji, 1=marubozu
    d["pa_upper_wick"]   = (h - pd.concat([o, c], axis=1).max(axis=1)) / candle_range
    d["pa_lower_wick"]   = (pd.concat([o, c], axis=1).min(axis=1) - l) / candle_range
    d["pa_bull_candle"]  = (c > o).astype(int)
    d["pa_doji"]         = (d["pa_body_ratio"] < 0.1).astype(int)
    d["pa_pin_bar_bull"] = ((d["pa_lower_wick"] > 0.6) & (d["pa_body_ratio"] < 0.3)).astype(int)
    d["pa_pin_bar_bear"] = ((d["pa_upper_wick"] > 0.6) & (d["pa_body_ratio"] < 0.3)).astype(int)

    # Engulfing
    prev_body = (d["close"].shift(1) - d["open"].shift(1)).abs()
    d["pa_bull_engulf"] = (
        (c > o) & (o < d["close"].shift(1)) & (c > d["open"].shift(1)) & (body > prev_body)
    ).astype(int)
    d["pa_bear_engulf"] = (
        (c < o) & (o > d["close"].shift(1)) & (c < d["open"].shift(1)) & (body > prev_body)
    ).astype(int)

    # 3-bar momentum
    d["pa_3bar_bull"] = ((c > c.shift(1)) & (c.shift(1) > c.shift(2))).astype(int)
    d["pa_3bar_bear"] = ((c < c.shift(1)) & (c.shift(1) < c.shift(2))).astype(int)

    return d


# ─────────────────────────────────────────────────────────────────────────────
# Swing highs/lows and fractal levels
# ─────────────────────────────────────────────────────────────────────────────

def add_swing_features(df: pd.DataFrame, window: int = 5) -> pd.DataFrame:
    """Detect swing highs/lows; distance from price to nearest swing level."""
    d = df.copy()
    h, l, c = d["high"], d["low"], d["close"]

    # Fractal high: highest in window on each side
    d["swing_high"] = h[(h == h.rolling(window * 2 + 1, center=True).max())].reindex(d.index)
    d["swing_low"]  = l[(l == l.rolling(window * 2 + 1, center=True).min())].reindex(d.index)

    # Forward-fill to get "last known" swing level
    d["last_swing_high"] = d["swing_high"].ffill()
    d["last_swing_low"]  = d["swing_low"].ffill()

    # Distance from current close to swing levels (normalised by ATR)
    atr = _atr(d, 14)
    d["dist_to_swing_high"] = (d["last_swing_high"] - c) / atr.replace(0, np.nan)
    d["dist_to_swing_low"]  = (c - d["last_swing_low"]) / atr.replace(0, np.nan)

    # Near support/resistance (within 0.5 ATR)
    d["near_swing_high"] = (d["dist_to_swing_high"].abs() < 0.5).astype(int)
    d["near_swing_low"]  = (d["dist_to_swing_low"].abs() < 0.5).astype(int)

    # Drop intermediate columns
    d.drop(columns=["swing_high", "swing_low", "last_swing_high", "last_swing_low"], inplace=True)
    return d


# ─────────────────────────────────────────────────────────────────────────────
# Multi-timeframe momentum
# ─────────────────────────────────────────────────────────────────────────────

def add_mtf_momentum(df: pd.DataFrame) -> pd.DataFrame:
    """Momentum at 5, 10, 20, 60 bar horizons; alignment score."""
    d = df.copy()
    c = d["close"]

    for n in [5, 10, 20, 60]:
        ret = c.pct_change(n)
        d[f"mom_{n}"]      = ret
        d[f"mom_{n}_sign"] = np.sign(ret)

    # Alignment: how many timeframes agree on direction
    signs = [d[f"mom_{n}_sign"] for n in [5, 10, 20, 60]]
    d["mtf_alignment"] = sum(signs) / 4.0   # -1 = all bearish, +1 = all bullish

    # Momentum acceleration (short vs long)
    d["mom_accel"] = d["mom_5"] - d["mom_20"]

    return d


# ─────────────────────────────────────────────────────────────────────────────
# Volatility regime
# ─────────────────────────────────────────────────────────────────────────────

def add_volatility_regime(df: pd.DataFrame) -> pd.DataFrame:
    """Realized vol, vol-of-vol, GARCH-proxy, vol regime label."""
    d = df.copy()
    ret = d["close"].pct_change()

    # Realized vol at multiple windows
    for w in [5, 10, 20, 60]:
        d[f"rvol_{w}"] = ret.rolling(w).std() * np.sqrt(252)

    # Vol ratio: short/long (>1 = expanding, <1 = contracting)
    d["vol_ratio_5_20"]  = d["rvol_5"]  / d["rvol_20"].replace(0, np.nan)
    d["vol_ratio_10_60"] = d["rvol_10"] / d["rvol_60"].replace(0, np.nan)

    # Vol-of-vol (second-order uncertainty)
    d["vol_of_vol"] = d["rvol_20"].rolling(20).std()

    # GARCH-proxy: exponentially weighted variance
    ewm_var = ret.ewm(span=20).var()
    d["garch_proxy"] = np.sqrt(ewm_var) * np.sqrt(252)

    # Vol regime: 0=low, 1=normal, 2=high (based on 60-bar percentile)
    pct = d["rvol_20"].rolling(60).rank(pct=True)
    d["vol_regime"] = pd.cut(pct, bins=[0, 0.33, 0.67, 1.0], labels=[0, 1, 2]).astype(float)

    return d


# ─────────────────────────────────────────────────────────────────────────────
# Market efficiency / microstructure
# ─────────────────────────────────────────────────────────────────────────────

def add_microstructure_features(df: pd.DataFrame) -> pd.DataFrame:
    """Efficiency ratio, fractal dimension proxy, spread proxy."""
    d = df.copy()
    c = d["close"]

    # Kaufman Efficiency Ratio: directional move / path length
    for w in [10, 20]:
        direction = (c - c.shift(w)).abs()
        path = c.diff().abs().rolling(w).sum()
        d[f"efficiency_{w}"] = direction / path.replace(0, np.nan)

    # High-low spread proxy (normalised)
    d["hl_spread"] = (d["high"] - d["low"]) / d["close"]

    # Amihud illiquidity proxy (if volume available)
    if "volume" in d.columns and d["volume"].sum() > 0:
        ret_abs = c.pct_change().abs()
        d["amihud"] = (ret_abs / d["volume"].replace(0, np.nan)).rolling(20).mean()
    else:
        d["amihud"] = 0.0

    return d


# ─────────────────────────────────────────────────────────────────────────────
# Calendar / seasonality
# ─────────────────────────────────────────────────────────────────────────────

def add_calendar_features(df: pd.DataFrame) -> pd.DataFrame:
    """Day-of-week, month, quarter, end-of-month effects."""
    d = df.copy()
    idx = pd.DatetimeIndex(d.index)

    d["cal_dow"]     = idx.dayofweek          # 0=Mon … 4=Fri
    d["cal_month"]   = idx.month
    d["cal_quarter"] = idx.quarter
    d["cal_eom"]     = (idx.is_month_end).astype(int)
    d["cal_eow"]     = (idx.dayofweek == 4).astype(int)   # Friday
    d["cal_monday"]  = (idx.dayofweek == 0).astype(int)

    # Cyclical encoding (avoids ordinal assumption)
    d["cal_dow_sin"]   = np.sin(2 * np.pi * d["cal_dow"] / 5)
    d["cal_dow_cos"]   = np.cos(2 * np.pi * d["cal_dow"] / 5)
    d["cal_month_sin"] = np.sin(2 * np.pi * d["cal_month"] / 12)
    d["cal_month_cos"] = np.cos(2 * np.pi * d["cal_month"] / 12)

    return d


# ─────────────────────────────────────────────────────────────────────────────
# Mean-reversion / trend strength
# ─────────────────────────────────────────────────────────────────────────────

def add_trend_features(df: pd.DataFrame) -> pd.DataFrame:
    """ADX, trend strength, mean-reversion z-score."""
    d = df.copy()
    h, l, c = d["high"], d["low"], d["close"]

    # ADX (simplified)
    atr14 = _atr(d, 14)
    plus_dm  = (h - h.shift(1)).clip(lower=0)
    minus_dm = (l.shift(1) - l).clip(lower=0)
    plus_dm  = plus_dm.where(plus_dm > minus_dm, 0)
    minus_dm = minus_dm.where(minus_dm > plus_dm, 0)

    plus_di  = 100 * plus_dm.ewm(span=14).mean()  / atr14.replace(0, np.nan)
    minus_di = 100 * minus_dm.ewm(span=14).mean() / atr14.replace(0, np.nan)
    dx = (100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan))
    d["adx_14"]      = dx.ewm(span=14).mean()
    d["plus_di_14"]  = plus_di
    d["minus_di_14"] = minus_di
    d["di_diff"]     = plus_di - minus_di   # positive = bullish trend

    # Mean-reversion z-score (distance from 20-bar mean in std units)
    for w in [10, 20, 50]:
        mu  = c.rolling(w).mean()
        sig = c.rolling(w).std()
        d[f"zscore_{w}"] = (c - mu) / sig.replace(0, np.nan)

    # Hurst exponent proxy (R/S over 20 bars)
    d["hurst_proxy"] = _rolling_hurst(c, 20)

    return d


# ─────────────────────────────────────────────────────────────────────────────
# Target engineering: filtered high-confidence signal
# ─────────────────────────────────────────────────────────────────────────────

def build_filtered_target(
    df: pd.DataFrame,
    horizon: int = 1,
    min_move_atr: float = 0.3,
) -> pd.Series:
    """
    Binary direction target that only labels bars where the move is
    meaningful (>= min_move_atr × ATR14).  Bars below the threshold
    are labelled NaN and dropped — this forces the model to learn
    high-conviction setups rather than noise.
    """
    c   = df["close"]
    atr = _atr(df, 14)

    future_ret = c.pct_change(horizon).shift(-horizon)
    future_move = (c.shift(-horizon) - c).abs()

    # Only label bars where the move exceeds the threshold
    threshold = min_move_atr * atr
    mask = future_move >= threshold

    y = pd.Series(np.nan, index=df.index)
    y[mask] = (future_ret[mask] > 0).astype(int)
    return y


# ─────────────────────────────────────────────────────────────────────────────
# Master builder
# ─────────────────────────────────────────────────────────────────────────────

def build_advanced_features(
    ohlcv: pd.DataFrame,
    macro_df: Optional[pd.DataFrame] = None,
    horizon: int = 1,
    use_filtered_target: bool = True,
    min_move_atr: float = 0.25,
) -> tuple[pd.DataFrame, pd.Series]:
    """
    Build the full advanced feature matrix and target.

    Parameters
    ----------
    ohlcv              : OHLCV DataFrame with columns open/high/low/close/volume
    macro_df           : Optional macro DataFrame (DXY, VIX, yields, SPX)
    horizon            : Prediction horizon in bars
    use_filtered_target: If True, drop low-conviction bars from training
    min_move_atr       : Minimum move (in ATR units) to include a bar

    Returns
    -------
    X : Feature DataFrame (no NaN)
    y : Binary target Series (0=down, 1=up)
    """
    d = ohlcv.copy()
    d.columns = [c.lower() for c in d.columns]

    # Ensure required columns
    for col in ["open", "high", "low", "close"]:
        if col not in d.columns:
            raise ValueError(f"Missing required column: {col}")
    if "volume" not in d.columns:
        d["volume"] = 0.0

    # ── Feature layers ────────────────────────────────────────────────────────
    d = add_price_action_features(d)
    d = add_swing_features(d, window=5)
    d = add_mtf_momentum(d)
    d = add_volatility_regime(d)
    d = add_microstructure_features(d)
    d = add_calendar_features(d)
    d = add_trend_features(d)

    # ── Macro features ────────────────────────────────────────────────────────
    if macro_df is not None and not macro_df.empty:
        try:
            from ml.macro_features import add_macro_features, add_regime_features
            d = add_macro_features(d, macro_df=macro_df, lookback=20)
            d = add_regime_features(d, lookback=60)
        except Exception as exc:
            import logging
            logging.getLogger(__name__).warning("Macro features skipped: %s", exc)

    # ── Target ────────────────────────────────────────────────────────────────
    if use_filtered_target:
        y_raw = build_filtered_target(d, horizon=horizon, min_move_atr=min_move_atr)
    else:
        future_ret = d["close"].pct_change(horizon).shift(-horizon)
        y_raw = (future_ret > 0).astype(float)
        y_raw[y_raw.isna()] = np.nan

    d["_target"] = y_raw

    # ── Drop OHLCV and NaN ────────────────────────────────────────────────────
    exclude = {"open", "high", "low", "close", "volume", "_target"}
    feature_cols = [c for c in d.columns if c not in exclude]

    d = d[feature_cols + ["_target"]].dropna()

    X = d[feature_cols]
    y = d["_target"].astype(int)

    return X, y


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    h, l, c = df["high"], df["low"], df["close"]
    tr = pd.concat([h - l, (h - c.shift(1)).abs(), (l - c.shift(1)).abs()], axis=1).max(axis=1)
    return tr.ewm(span=period, adjust=False).mean()


def _rolling_hurst(series: pd.Series, window: int = 20) -> pd.Series:
    """
    Approximate Hurst exponent via R/S analysis over a rolling window.
    H > 0.5 = trending, H < 0.5 = mean-reverting, H ≈ 0.5 = random walk.
    """
    def _hurst(x: np.ndarray) -> float:
        if len(x) < 8:
            return 0.5
        try:
            lags = range(2, min(len(x) // 2, 10))
            rs_vals = []
            for lag in lags:
                chunks = [x[i:i+lag] for i in range(0, len(x) - lag, lag)]
                rs_chunk = []
                for chunk in chunks:
                    if len(chunk) < 2:
                        continue
                    mean_c = np.mean(chunk)
                    dev = np.cumsum(chunk - mean_c)
                    r = dev.max() - dev.min()
                    s = np.std(chunk, ddof=1)
                    if s > 0:
                        rs_chunk.append(r / s)
                if rs_chunk:
                    rs_vals.append(np.mean(rs_chunk))
            if len(rs_vals) < 2:
                return 0.5
            log_lags = np.log(list(lags)[:len(rs_vals)])
            log_rs   = np.log(rs_vals)
            h = np.polyfit(log_lags, log_rs, 1)[0]
            return float(np.clip(h, 0.0, 1.0))
        except Exception:
            return 0.5

    return series.rolling(window).apply(_hurst, raw=True)

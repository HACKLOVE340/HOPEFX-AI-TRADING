"""
research/pipeline/feature_engineering.py
==========================================
Wide, deep feature engineering for the prediction pipeline.

Feature groups
--------------
1. Technical indicators  — RSI, MACD, Bollinger, ATR, OBV, Stochastic, CCI,
                           Williams %R, Ichimoku cloud, VWAP deviation
2. Lag features          — returns at 1/2/3/5/10/20/60 bars
3. Rolling statistics    — mean, std, skew, kurtosis over multiple windows
4. Fourier features      — dominant frequency components of close price
5. Candlestick patterns  — body/wick ratios, engulfing, pin-bar, doji
6. Volatility regime     — GARCH-proxy (squared returns), realised vol ratio
7. Sentiment             — attached from RSS (see data_ingestion.py)
8. Calendar              — hour, day-of-week, month, quarter, is_month_end

All functions accept a DataFrame with columns open/high/low/close/volume
and return an enriched copy.  NaN rows introduced by look-back windows are
dropped at the end of `build_feature_matrix()`.
"""

from __future__ import annotations

import logging
from typing import List, Optional

import numpy as np
import pandas as pd
from scipy.fft import rfft, rfftfreq  # scipy is a transitive dep of sklearn

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Low-level indicator helpers
# ─────────────────────────────────────────────────────────────────────────────

def _ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False).mean()


def _sma(series: pd.Series, window: int) -> pd.Series:
    return series.rolling(window).mean()


def _true_range(df: pd.DataFrame) -> pd.Series:
    h, l, c = df["high"], df["low"], df["close"]
    tr = pd.concat(
        [h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1
    ).max(axis=1)
    return tr


# ─────────────────────────────────────────────────────────────────────────────
# 1. Technical indicators
# ─────────────────────────────────────────────────────────────────────────────

def add_technical_indicators(df: pd.DataFrame) -> pd.DataFrame:
    d = df.copy()
    c = d["close"]
    h, l, v = d["high"], d["low"], d["volume"]

    # ── RSI (14) ──────────────────────────────────────────────────────────────
    delta = c.diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)
    avg_gain = gain.ewm(com=13, adjust=False).mean()
    avg_loss = loss.ewm(com=13, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    d["rsi_14"] = 100 - (100 / (1 + rs))

    # RSI at multiple periods
    for period in [7, 21]:
        ag = gain.ewm(com=period - 1, adjust=False).mean()
        al = loss.ewm(com=period - 1, adjust=False).mean()
        rs_p = ag / al.replace(0, np.nan)
        d[f"rsi_{period}"] = 100 - (100 / (1 + rs_p))

    # ── MACD ─────────────────────────────────────────────────────────────────
    ema12 = _ema(c, 12)
    ema26 = _ema(c, 26)
    d["macd_line"] = ema12 - ema26
    d["macd_signal"] = _ema(d["macd_line"], 9)
    d["macd_hist"] = d["macd_line"] - d["macd_signal"]
    d["macd_hist_chg"] = d["macd_hist"].diff()

    # ── Bollinger Bands (20, 2σ) ──────────────────────────────────────────────
    bb_mid = _sma(c, 20)
    bb_std = c.rolling(20).std()
    d["bb_upper"] = bb_mid + 2 * bb_std
    d["bb_lower"] = bb_mid - 2 * bb_std
    d["bb_mid"] = bb_mid
    d["bb_width"] = (d["bb_upper"] - d["bb_lower"]) / bb_mid.replace(0, np.nan)
    d["bb_pct"] = (c - d["bb_lower"]) / (d["bb_upper"] - d["bb_lower"]).replace(0, np.nan)

    # ── ATR ───────────────────────────────────────────────────────────────────
    tr = _true_range(d)
    d["atr_14"] = tr.ewm(com=13, adjust=False).mean()
    d["atr_pct"] = d["atr_14"] / c.replace(0, np.nan)

    # ── Stochastic %K / %D ────────────────────────────────────────────────────
    low14 = l.rolling(14).min()
    high14 = h.rolling(14).max()
    d["stoch_k"] = 100 * (c - low14) / (high14 - low14).replace(0, np.nan)
    d["stoch_d"] = d["stoch_k"].rolling(3).mean()

    # ── CCI ───────────────────────────────────────────────────────────────────
    typical = (h + l + c) / 3
    cci_sma = typical.rolling(20).mean()
    cci_mad = typical.rolling(20).apply(lambda x: np.mean(np.abs(x - x.mean())), raw=True)
    d["cci_20"] = (typical - cci_sma) / (0.015 * cci_mad.replace(0, np.nan))

    # ── Williams %R ───────────────────────────────────────────────────────────
    d["williams_r"] = -100 * (high14 - c) / (high14 - low14).replace(0, np.nan)

    # ── OBV ───────────────────────────────────────────────────────────────────
    obv = (np.sign(c.diff()) * v).fillna(0).cumsum()
    d["obv"] = obv
    d["obv_ema"] = _ema(obv, 20)
    d["obv_divergence"] = obv - d["obv_ema"]

    # ── VWAP deviation ────────────────────────────────────────────────────────
    if "vwap" in d.columns:
        d["vwap_dev"] = (c - d["vwap"]) / d["vwap"].replace(0, np.nan)

    # ── Ichimoku Cloud ────────────────────────────────────────────────────────
    tenkan = (h.rolling(9).max() + l.rolling(9).min()) / 2
    kijun = (h.rolling(26).max() + l.rolling(26).min()) / 2
    d["ichimoku_tenkan"] = tenkan
    d["ichimoku_kijun"] = kijun
    d["ichimoku_diff"] = tenkan - kijun
    senkou_a = ((tenkan + kijun) / 2).shift(26)
    senkou_b = ((h.rolling(52).max() + l.rolling(52).min()) / 2).shift(26)
    d["ichimoku_cloud_top"] = pd.concat([senkou_a, senkou_b], axis=1).max(axis=1)
    d["ichimoku_cloud_bot"] = pd.concat([senkou_a, senkou_b], axis=1).min(axis=1)
    d["ichimoku_above_cloud"] = (c > d["ichimoku_cloud_top"]).astype(int)

    # ── Moving average crossovers ─────────────────────────────────────────────
    for fast, slow in [(10, 50), (20, 100), (50, 200)]:
        d[f"sma_{fast}"] = _sma(c, fast)
        d[f"sma_{slow}"] = _sma(c, slow)
        d[f"ma_cross_{fast}_{slow}"] = (d[f"sma_{fast}"] > d[f"sma_{slow}"]).astype(int)

    return d


# ─────────────────────────────────────────────────────────────────────────────
# 2. Lag features
# ─────────────────────────────────────────────────────────────────────────────

LAG_PERIODS = [1, 2, 3, 5, 10, 20, 60]


def add_lag_features(df: pd.DataFrame, periods: List[int] = LAG_PERIODS) -> pd.DataFrame:
    d = df.copy()
    c = d["close"]

    for p in periods:
        d[f"ret_{p}"] = c.pct_change(p)
        d[f"log_ret_{p}"] = np.log(c / c.shift(p))
        d[f"close_lag_{p}"] = c.shift(p)

    if "volume" in d.columns:
        for p in [1, 5, 20]:
            d[f"vol_lag_{p}"] = d["volume"].shift(p)
            d[f"vol_ret_{p}"] = d["volume"].pct_change(p)

    return d


# ─────────────────────────────────────────────────────────────────────────────
# 3. Rolling statistics
# ─────────────────────────────────────────────────────────────────────────────

ROLLING_WINDOWS = [5, 10, 20, 50, 100]


def add_rolling_stats(df: pd.DataFrame, windows: List[int] = ROLLING_WINDOWS) -> pd.DataFrame:
    d = df.copy()
    log_ret = np.log(d["close"] / d["close"].shift(1))

    for w in windows:
        d[f"roll_mean_{w}"] = log_ret.rolling(w).mean()
        d[f"roll_std_{w}"] = log_ret.rolling(w).std()
        d[f"roll_skew_{w}"] = log_ret.rolling(w).skew()
        d[f"roll_kurt_{w}"] = log_ret.rolling(w).kurt()
        d[f"roll_min_{w}"] = d["close"].rolling(w).min()
        d[f"roll_max_{w}"] = d["close"].rolling(w).max()
        d[f"roll_range_{w}"] = (d[f"roll_max_{w}"] - d[f"roll_min_{w}"]) / d["close"].replace(0, np.nan)
        # Z-score of close within window
        d[f"zscore_{w}"] = (d["close"] - d[f"roll_mean_{w}"].shift(1)) / d[f"roll_std_{w}"].shift(1).replace(0, np.nan)

    return d


# ─────────────────────────────────────────────────────────────────────────────
# 4. Fourier transform features
# ─────────────────────────────────────────────────────────────────────────────

def add_fourier_features(
    df: pd.DataFrame,
    window: int = 128,
    n_components: int = 5,
) -> pd.DataFrame:
    """
    Rolling FFT over `window` bars of log-returns.
    Extracts the top-N dominant frequency amplitudes and phases.
    These capture cyclical patterns (weekly, monthly, quarterly rhythms).
    """
    d = df.copy()
    log_ret = np.log(d["close"] / d["close"].shift(1)).fillna(0).values
    n = len(log_ret)

    amps = np.zeros((n, n_components))
    phases = np.zeros((n, n_components))

    for i in range(window, n):
        segment = log_ret[i - window: i]
        fft_vals = rfft(segment)
        freqs = rfftfreq(window)
        magnitudes = np.abs(fft_vals)
        # Ignore DC component (index 0)
        top_idx = np.argsort(magnitudes[1:])[-n_components:] + 1
        for k, idx in enumerate(sorted(top_idx)):
            amps[i, k] = magnitudes[idx]
            phases[i, k] = np.angle(fft_vals[idx])

    for k in range(n_components):
        d[f"fft_amp_{k}"] = amps[:, k]
        d[f"fft_phase_{k}"] = phases[:, k]

    return d


# ─────────────────────────────────────────────────────────────────────────────
# 5. Candlestick pattern features
# ─────────────────────────────────────────────────────────────────────────────

def add_candlestick_features(df: pd.DataFrame) -> pd.DataFrame:
    d = df.copy()
    o, h, l, c = d["open"], d["high"], d["low"], d["close"]
    candle_range = (h - l).replace(0, np.nan)
    body = (c - o).abs()

    d["cs_body_ratio"] = body / candle_range
    d["cs_upper_wick"] = (h - pd.concat([o, c], axis=1).max(axis=1)) / candle_range
    d["cs_lower_wick"] = (pd.concat([o, c], axis=1).min(axis=1) - l) / candle_range
    d["cs_bull"] = (c > o).astype(int)
    d["cs_doji"] = (d["cs_body_ratio"] < 0.1).astype(int)
    d["cs_pin_bull"] = ((d["cs_lower_wick"] > 0.6) & (d["cs_body_ratio"] < 0.3)).astype(int)
    d["cs_pin_bear"] = ((d["cs_upper_wick"] > 0.6) & (d["cs_body_ratio"] < 0.3)).astype(int)

    prev_body = (d["close"].shift(1) - d["open"].shift(1)).abs()
    d["cs_engulf_bull"] = (
        (c > o) & (o < d["close"].shift(1)) & (c > d["open"].shift(1)) & (body > prev_body)
    ).astype(int)
    d["cs_engulf_bear"] = (
        (c < o) & (o > d["close"].shift(1)) & (c < d["open"].shift(1)) & (body > prev_body)
    ).astype(int)

    # 3-bar momentum
    d["cs_3bull"] = ((c > c.shift(1)) & (c.shift(1) > c.shift(2))).astype(int)
    d["cs_3bear"] = ((c < c.shift(1)) & (c.shift(1) < c.shift(2))).astype(int)

    return d


# ─────────────────────────────────────────────────────────────────────────────
# 6. Volatility regime features
# ─────────────────────────────────────────────────────────────────────────────

def add_volatility_regime(df: pd.DataFrame) -> pd.DataFrame:
    d = df.copy()
    log_ret = np.log(d["close"] / d["close"].shift(1))

    # GARCH-proxy: squared returns
    d["sq_ret"] = log_ret ** 2

    # Realised volatility at multiple horizons
    for w in [5, 20, 60]:
        rv = log_ret.rolling(w).std() * np.sqrt(252)
        d[f"realvol_{w}"] = rv

    # Volatility ratio (short / long) — regime indicator
    d["vol_ratio_5_20"] = d["realvol_5"] / d["realvol_20"].replace(0, np.nan)
    d["vol_ratio_20_60"] = d["realvol_20"] / d["realvol_60"].replace(0, np.nan)

    # High-vol regime flag (top quartile of 60-day realised vol)
    rv60 = d["realvol_60"]
    d["high_vol_regime"] = (rv60 > rv60.rolling(252, min_periods=60).quantile(0.75)).astype(int)

    return d


# ─────────────────────────────────────────────────────────────────────────────
# 7. Calendar / seasonality features
# ─────────────────────────────────────────────────────────────────────────────

def add_calendar_features(df: pd.DataFrame) -> pd.DataFrame:
    d = df.copy()
    idx = d.index

    if hasattr(idx, "hour"):
        d["cal_hour"] = idx.hour
        d["cal_hour_sin"] = np.sin(2 * np.pi * idx.hour / 24)
        d["cal_hour_cos"] = np.cos(2 * np.pi * idx.hour / 24)

    d["cal_dow"] = idx.dayofweek
    d["cal_dow_sin"] = np.sin(2 * np.pi * idx.dayofweek / 5)
    d["cal_dow_cos"] = np.cos(2 * np.pi * idx.dayofweek / 5)
    d["cal_month"] = idx.month
    d["cal_month_sin"] = np.sin(2 * np.pi * idx.month / 12)
    d["cal_month_cos"] = np.cos(2 * np.pi * idx.month / 12)
    d["cal_quarter"] = idx.quarter
    d["cal_is_month_end"] = idx.is_month_end.astype(int)
    d["cal_is_quarter_end"] = idx.is_quarter_end.astype(int)

    return d


# ─────────────────────────────────────────────────────────────────────────────
# Master builder
# ─────────────────────────────────────────────────────────────────────────────

def build_feature_matrix(
    df: pd.DataFrame,
    fourier_window: int = 128,
    fourier_components: int = 5,
    lag_periods: Optional[List[int]] = None,
    rolling_windows: Optional[List[int]] = None,
    drop_na: bool = True,
) -> pd.DataFrame:
    """
    Apply all feature groups in sequence and return a clean DataFrame.

    Parameters
    ----------
    df                 : OHLCV DataFrame (DatetimeIndex, UTC)
    fourier_window     : Look-back window for rolling FFT
    fourier_components : Number of dominant FFT components to keep
    lag_periods        : Override default lag periods
    rolling_windows    : Override default rolling windows
    drop_na            : Drop rows with any NaN (from look-back warm-up)

    Returns
    -------
    Feature-rich DataFrame ready for ML ingestion.
    """
    logger.info("Building feature matrix  shape=%s", df.shape)

    d = df.copy()
    d = add_technical_indicators(d)
    d = add_lag_features(d, periods=lag_periods or LAG_PERIODS)
    d = add_rolling_stats(d, windows=rolling_windows or ROLLING_WINDOWS)
    d = add_fourier_features(d, window=fourier_window, n_components=fourier_components)
    d = add_candlestick_features(d)
    d = add_volatility_regime(d)
    d = add_calendar_features(d)

    if drop_na:
        before = len(d)
        d.dropna(inplace=True)
        logger.info("Dropped %d NaN rows (warm-up); final shape=%s", before - len(d), d.shape)

    return d


# ─────────────────────────────────────────────────────────────────────────────
# Target engineering
# ─────────────────────────────────────────────────────────────────────────────

def add_targets(
    df: pd.DataFrame,
    horizon: int = 1,
    threshold: float = 0.0,
    regression: bool = False,
) -> pd.DataFrame:
    """
    Append prediction targets.

    Parameters
    ----------
    horizon    : Bars ahead to predict
    threshold  : Minimum return magnitude to label as directional signal
                 (bars below threshold are labelled 0 = "no trade")
    regression : If True, add continuous forward-return target

    Adds columns
    ------------
    target_ret      : Forward log-return (always added)
    target_dir      : 1=up, -1=down, 0=flat  (classification)
    target_bin      : 1=up, 0=down/flat       (binary classification)
    """
    d = df.copy()
    fwd_ret = np.log(d["close"].shift(-horizon) / d["close"])
    d["target_ret"] = fwd_ret

    d["target_dir"] = 0
    d.loc[fwd_ret > threshold, "target_dir"] = 1
    d.loc[fwd_ret < -threshold, "target_dir"] = -1

    d["target_bin"] = (fwd_ret > threshold).astype(int)

    return d

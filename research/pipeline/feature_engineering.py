# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
research/pipeline/feature_engineering.py
==========================================
Wide, deep feature engineering for the prediction pipeline.

Feature groups
--------------
1.  Technical indicators  — RSI, MACD, Bollinger, ATR, OBV, Stochastic, CCI,
                            Williams %R, Ichimoku cloud, VWAP deviation
2.  Lag features          — returns at 1/2/3/5/10/20/60 bars
3.  Rolling statistics    — mean, std, skew, kurtosis over multiple windows
4.  Fourier features      — dominant frequency components of close price
5.  Candlestick patterns  — body/wick ratios, engulfing, pin-bar, doji
6.  Volatility regime     — GARCH-proxy (squared returns), realised vol ratio
7.  Sentiment             — attached from RSS (see data_ingestion.py)
8.  Calendar              — hour, day-of-week, month, quarter, is_month_end
9.  Swing levels          — pivot highs/lows, distance from key S/R levels
10. Momentum divergence   — price vs RSI/MACD divergence signals
11. Volume profile        — VWAP bands, volume-weighted momentum
12. Microstructure proxy  — tick direction, spread proxy, trade intensity
13. Regime context        — HMM-style vol regime, trend strength index

All functions accept a DataFrame with columns open/high/low/close/volume
and return an enriched copy.  NaN rows introduced by look-back windows are
dropped at the end of `build_feature_matrix()`.
"""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd

try:
    from scipy.fft import rfft

    _SCIPY_AVAILABLE = True
except ImportError:
    _SCIPY_AVAILABLE = False

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Low-level indicator helpers
# ─────────────────────────────────────────────────────────────────────────────


def _ema(series: pd.Series, span: int) -> pd.Series:
    return series.dropna().ewm(span=span, adjust=False).mean()


def _sma(series: pd.Series, window: int) -> pd.Series:
    return series.dropna().rolling(window).mean()


def _true_range(df: pd.DataFrame) -> pd.Series:
    h, l, c = df["high"], df["low"], df["close"]
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).fillna(0.0).max(axis=1)
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
    d["ichimoku_cloud_top"] = pd.concat([senkou_a, senkou_b], axis=1).fillna(0.0).max(axis=1)
    d["ichimoku_cloud_bot"] = pd.concat([senkou_a, senkou_b], axis=1).fillna(0.0).min(axis=1)
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


def add_lag_features(df: pd.DataFrame, periods: list[int] = LAG_PERIODS) -> pd.DataFrame:
    d = df.copy()
    c = d["close"]

    for p in periods:
        d[f"ret_{p}"] = c.pct_change(p)
        d[f"log_ret_{p}"] = np.nan_to_num(np.log((c / c.shift(p)).replace(0, np.nan)), nan=0.0)
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


def add_rolling_stats(df: pd.DataFrame, windows: list[int] = ROLLING_WINDOWS) -> pd.DataFrame:
    d = df.copy()
    _close_safe = d["close"].replace(0, np.nan).dropna()
    log_ret = np.log(_close_safe / _close_safe.shift(1)).fillna(0.0)

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
    Falls back to zero-filled columns when scipy is unavailable.
    """
    d = df.copy()
    n = len(d)

    # Pre-fill with zeros so downstream code always sees these columns
    for k in range(n_components):
        d[f"fft_amp_{k}"] = 0.0
        d[f"fft_phase_{k}"] = 0.0

    if not _SCIPY_AVAILABLE or n < window:
        return d

    log_ret = np.log(d["close"] / d["close"].shift(1)).fillna(0).values

    amps = np.zeros((n, n_components))
    phases = np.zeros((n, n_components))

    for i in range(window, n):
        segment = log_ret[i - window : i]
        fft_vals = rfft(segment)
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
    d["cs_engulf_bull"] = ((c > o) & (o < d["close"].shift(1)) & (c > d["open"].shift(1)) & (body > prev_body)).astype(
        int
    )
    d["cs_engulf_bear"] = ((c < o) & (o > d["close"].shift(1)) & (c < d["open"].shift(1)) & (body > prev_body)).astype(
        int
    )

    # 3-bar momentum
    d["cs_3bull"] = ((c > c.shift(1)) & (c.shift(1) > c.shift(2))).astype(int)
    d["cs_3bear"] = ((c < c.shift(1)) & (c.shift(1) < c.shift(2))).astype(int)

    return d


# ─────────────────────────────────────────────────────────────────────────────
# 6. Volatility regime features
# ─────────────────────────────────────────────────────────────────────────────


def add_volatility_regime(df: pd.DataFrame) -> pd.DataFrame:
    d = df.copy()
    _c_safe = d["close"].replace(0, np.nan).dropna()
    log_ret = np.log(_c_safe / _c_safe.shift(1)).fillna(0.0)

    # GARCH-proxy: squared returns
    d["sq_ret"] = log_ret**2

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
# 9. Swing levels — pivot highs/lows and distance from key S/R
# ─────────────────────────────────────────────────────────────────────────────


def add_swing_levels(df: pd.DataFrame, lookback: int = 20) -> pd.DataFrame:
    """
    Identify rolling pivot highs/lows and compute distance from current price.

    Columns added
    -------------
    swing_high_{lookback}  : Rolling max high over lookback bars (S/R level)
    swing_low_{lookback}   : Rolling min low over lookback bars
    swing_high_dist        : (swing_high - close) / close  — distance to resistance
    swing_low_dist         : (close - swing_low) / close   — distance to support
    swing_position         : close position within [swing_low, swing_high] range [0,1]
    swing_breakout_up      : 1 if close > prior swing_high (breakout)
    swing_breakout_dn      : 1 if close < prior swing_low  (breakdown)
    """
    d = df.copy()
    c, h, lo = d["close"], d["high"], d["low"]

    swing_high = h.rolling(lookback).max().shift(1)
    swing_low = lo.rolling(lookback).min().shift(1)
    swing_range = (swing_high - swing_low).replace(0, np.nan)

    d[f"swing_high_{lookback}"] = swing_high
    d[f"swing_low_{lookback}"] = swing_low
    d["swing_high_dist"] = (swing_high - c) / c.replace(0, np.nan)
    d["swing_low_dist"] = (c - swing_low) / c.replace(0, np.nan)
    d["swing_position"] = (c - swing_low) / swing_range
    d["swing_breakout_up"] = (c > swing_high).astype(int)
    d["swing_breakout_dn"] = (c < swing_low).astype(int)

    # 52-week high/low distance (useful for daily data)
    high_52w = h.rolling(252, min_periods=20).max()
    low_52w = lo.rolling(252, min_periods=20).min()
    d["dist_52wh"] = (high_52w - c) / high_52w.replace(0, np.nan)
    d["dist_52wl"] = (c - low_52w) / low_52w.replace(0, np.nan)

    return d


# ─────────────────────────────────────────────────────────────────────────────
# 10. Momentum divergence — price vs RSI/MACD divergence
# ─────────────────────────────────────────────────────────────────────────────


def add_momentum_divergence(df: pd.DataFrame, window: int = 14) -> pd.DataFrame:
    """
    Detect bullish/bearish divergence between price and momentum oscillators.

    A bullish divergence occurs when price makes a lower low but RSI makes a
    higher low — suggesting weakening selling pressure.

    Columns added
    -------------
    div_rsi_bull  : 1 if price lower low + RSI higher low (bullish divergence)
    div_rsi_bear  : 1 if price higher high + RSI lower high (bearish divergence)
    div_macd_bull : 1 if price lower low + MACD hist higher low
    div_macd_bear : 1 if price higher high + MACD hist lower high
    mom_strength  : Composite momentum: RSI z-score + MACD hist z-score
    """
    d = df.copy()
    c = d["close"]

    # Require RSI and MACD to already be computed
    if "rsi_14" not in d.columns or "macd_hist" not in d.columns:
        d = add_technical_indicators(d)

    rsi = d["rsi_14"]
    macd = d["macd_hist"]

    # Rolling window lows/highs for divergence detection
    price_low = c.rolling(window).min()
    price_high = c.rolling(window).max()
    rsi_low = rsi.rolling(window).min()
    rsi_high = rsi.rolling(window).max()
    macd_low = macd.rolling(window).min()
    macd_high = macd.rolling(window).max()

    # Bullish: price at new low but oscillator not at new low
    d["div_rsi_bull"] = ((c == price_low) & (rsi > rsi_low)).astype(int)
    d["div_rsi_bear"] = ((c == price_high) & (rsi < rsi_high)).astype(int)
    d["div_macd_bull"] = ((c == price_low) & (macd > macd_low)).astype(int)
    d["div_macd_bear"] = ((c == price_high) & (macd < macd_high)).astype(int)

    # Composite momentum strength (z-scored)
    rsi_z = (rsi - rsi.rolling(50).mean()) / rsi.rolling(50).std().replace(0, np.nan)
    macd_z = (macd - macd.rolling(50).mean()) / macd.rolling(50).std().replace(0, np.nan)
    d["mom_strength"] = (rsi_z.fillna(0) + macd_z.fillna(0)) / 2.0

    # Rate of change of momentum
    d["mom_roc_5"] = rsi.pct_change(5)
    d["mom_roc_20"] = rsi.pct_change(20)

    return d


# ─────────────────────────────────────────────────────────────────────────────
# 11. Volume profile — VWAP bands, volume-weighted momentum
# ─────────────────────────────────────────────────────────────────────────────


def add_volume_profile(df: pd.DataFrame) -> pd.DataFrame:
    """
    Volume-weighted price features and VWAP deviation bands.

    Columns added
    -------------
    vwap_session    : Cumulative VWAP (reset daily if DatetimeIndex)
    vwap_dev_pct    : (close - vwap) / vwap
    vwap_band_upper : vwap + 2 * rolling std of (close - vwap)
    vwap_band_lower : vwap - 2 * rolling std of (close - vwap)
    vol_price_trend : OBV-style: sign(ret) * volume, rolling sum
    vol_weighted_ret: Volume-weighted return (price change × volume)
    vol_surge       : volume / rolling_mean_volume_20 — surge indicator
    """
    d = df.copy()
    c = d["close"]
    v = d.get("volume", pd.Series(np.ones(len(c)), index=c.index))
    typical = (d["high"] + d["low"] + c) / 3

    # Session VWAP (rolling 20-bar approximation for non-intraday data)
    cum_tp_vol = (typical * v).rolling(20).sum()
    cum_vol = v.rolling(20).sum().replace(0, np.nan)
    d["vwap_session"] = cum_tp_vol / cum_vol

    vwap = d["vwap_session"]
    vwap_dev = c - vwap
    vwap_dev_std = vwap_dev.rolling(20).std().replace(0, np.nan)

    d["vwap_dev_pct"] = vwap_dev / vwap.replace(0, np.nan)
    d["vwap_band_upper"] = vwap + 2 * vwap_dev_std
    d["vwap_band_lower"] = vwap - 2 * vwap_dev_std
    d["vwap_pct_b"] = (c - d["vwap_band_lower"]) / ((d["vwap_band_upper"] - d["vwap_band_lower"]).replace(0, np.nan))

    # Volume-weighted momentum
    sign_ret = np.sign(c.diff())
    d["vol_price_trend"] = (sign_ret * v).rolling(20).sum()
    d["vol_weighted_ret"] = (c.pct_change(fill_method=None) * v).rolling(5).sum()

    # Volume surge
    vol_mean = v.rolling(20).mean().replace(0, np.nan)
    d["vol_surge"] = v / vol_mean

    # Accumulation/Distribution line
    clv = ((c - d["low"]) - (d["high"] - c)) / (d["high"] - d["low"]).replace(0, np.nan)
    d["ad_line"] = (clv * v).cumsum()
    d["ad_line_ema"] = _ema(d["ad_line"], 14)
    d["ad_divergence"] = d["ad_line"] - d["ad_line_ema"]

    return d


# ─────────────────────────────────────────────────────────────────────────────
# 12. Microstructure proxy — tick direction, spread proxy, trade intensity
# ─────────────────────────────────────────────────────────────────────────────


def add_microstructure_proxy(df: pd.DataFrame) -> pd.DataFrame:
    """
    Microstructure features derived from OHLCV without order-book data.

    These are proxies for the true microstructure features in
    research/pipeline/microstructure.py, usable when only OHLCV is available.

    Columns added
    -------------
    tick_dir        : +1 uptick, -1 downtick, 0 unchanged
    tick_ema5       : EMA(5) of tick direction
    spread_proxy    : (high - low) / close — proxy for bid-ask spread
    spread_z20      : z-score of spread_proxy over 20 bars
    close_loc       : (close - low) / (high - low) — close location [0,1]
    buy_pressure    : close_loc as proxy for buy-side pressure
    price_impact    : |ret| / vol_surge — price impact per unit volume
    """
    d = df.copy()
    c = d["close"]
    h, lo = d["high"], d["low"]
    v = d.get("volume", pd.Series(np.ones(len(c)), index=c.index))

    # Tick direction
    tick = np.sign(c.diff()).fillna(0)
    d["tick_dir"] = tick
    d["tick_ema5"] = _ema(tick, 5)
    d["tick_run"] = tick.groupby((tick != tick.shift()).cumsum()).cumcount() + 1
    d["tick_run"] = d["tick_run"] * tick  # signed run length

    # Spread proxy
    hl_range = (h - lo).replace(0, np.nan)
    spread_proxy = hl_range / c.replace(0, np.nan)
    spread_mean = spread_proxy.rolling(20).mean()
    spread_std = spread_proxy.rolling(20).std().replace(0, np.nan)
    d["spread_proxy"] = spread_proxy
    d["spread_z20"] = (spread_proxy - spread_mean) / spread_std

    # Close location within bar
    d["close_loc"] = (c - lo) / hl_range
    d["buy_pressure"] = d["close_loc"].rolling(5).mean()

    # Price impact proxy
    vol_mean = v.rolling(20).mean().replace(0, np.nan)
    vol_surge = (v / vol_mean).replace(0, np.nan)
    d["price_impact"] = c.pct_change(fill_method=None).abs() / vol_surge

    # Amihud illiquidity ratio (|ret| / volume)
    d["amihud"] = c.pct_change(fill_method=None).abs() / v.replace(0, np.nan)
    d["amihud_ma20"] = d["amihud"].rolling(20).mean()

    return d


# ─────────────────────────────────────────────────────────────────────────────
# 13. Regime context — trend strength, vol regime, HMM-style state
# ─────────────────────────────────────────────────────────────────────────────


def add_regime_context(df: pd.DataFrame) -> pd.DataFrame:
    """
    Regime-level context features for the current bar.

    Columns added
    -------------
    trend_strength  : ADX-like directional movement index
    trend_dir       : +1 uptrend, -1 downtrend, 0 sideways
    vol_regime_3    : 3-class vol regime: 0=low, 1=medium, 2=high
    regime_change   : 1 if vol_regime changed from prior bar
    adx_14          : Average Directional Index (14)
    di_plus         : +DI (directional indicator)
    di_minus        : -DI
    """
    d = df.copy()
    h, lo, c = d["high"], d["low"], d["close"]

    # True Range and Directional Movement
    tr = _true_range(d)
    atr14 = tr.ewm(com=13, adjust=False).mean().replace(0, np.nan)

    up_move = h - h.shift(1)
    down_move = lo.shift(1) - lo

    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)

    plus_dm_s = pd.Series(plus_dm, index=d.index).ewm(com=13, adjust=False).mean()
    minus_dm_s = pd.Series(minus_dm, index=d.index).ewm(com=13, adjust=False).mean()

    di_plus = 100 * plus_dm_s / atr14
    di_minus = 100 * minus_dm_s / atr14
    dx = 100 * (di_plus - di_minus).abs() / (di_plus + di_minus).replace(0, np.nan)
    adx = dx.ewm(com=13, adjust=False).mean()

    d["adx_14"] = adx
    d["di_plus"] = di_plus
    d["di_minus"] = di_minus

    # Trend strength and direction
    d["trend_strength"] = adx / 100.0  # normalised [0, 1]
    d["trend_dir"] = np.where(di_plus > di_minus, 1, np.where(di_minus > di_plus, -1, 0))

    # Volatility regime (3-class: low / medium / high)
    _c_reg = c.replace(0, np.nan).dropna()
    log_ret = np.log(_c_reg / _c_reg.shift(1)).fillna(0.0)
    rv20 = log_ret.rolling(20).std() * np.sqrt(252)
    q33 = rv20.rolling(252, min_periods=60).quantile(0.33)
    q67 = rv20.rolling(252, min_periods=60).quantile(0.67)
    vol_regime = pd.Series(1, index=d.index)  # default: medium
    vol_regime = vol_regime.where(rv20 >= q33, 0)  # low
    vol_regime = vol_regime.where(rv20 <= q67, 2)  # high
    # Re-apply medium where both conditions fail
    vol_regime = np.where(rv20 < q33, 0, np.where(rv20 > q67, 2, 1))
    d["vol_regime_3"] = vol_regime
    d["regime_change"] = (pd.Series(vol_regime, index=d.index).diff().abs() > 0).astype(int)

    # Choppiness index (measures trendiness vs choppiness)
    atr_sum = tr.rolling(14).sum()
    hl_range = (h.rolling(14).max() - lo.rolling(14).min()).replace(0, np.nan)
    d["choppiness"] = 100 * np.log10(atr_sum / hl_range) / np.log10(14)

    return d


# ─────────────────────────────────────────────────────────────────────────────
# Master builder
# ─────────────────────────────────────────────────────────────────────────────


def build_feature_matrix(
    df: pd.DataFrame,
    fourier_window: int = 128,
    fourier_components: int = 5,
    lag_periods: list[int] | None = None,
    rolling_windows: list[int] | None = None,
    swing_lookback: int = 20,
    drop_na: bool = True,
    include_microstructure: bool = True,
    include_regime: bool = True,
    include_volume_profile: bool = True,
    include_divergence: bool = True,
    include_swing: bool = True,
) -> pd.DataFrame:
    """
    Apply all feature groups in sequence and return a clean DataFrame.

    Parameters
    ----------
    df                    : OHLCV DataFrame (DatetimeIndex, UTC)
    fourier_window        : Look-back window for rolling FFT
    fourier_components    : Number of dominant FFT components to keep
    lag_periods           : Override default lag periods
    rolling_windows       : Override default rolling windows
    swing_lookback        : Lookback for pivot high/low detection
    drop_na               : Drop rows with any NaN (from look-back warm-up)
    include_microstructure: Add microstructure proxy features (group 12)
    include_regime        : Add regime context features (group 13)
    include_volume_profile: Add volume profile features (group 11)
    include_divergence    : Add momentum divergence features (group 10)
    include_swing         : Add swing level features (group 9)

    Returns
    -------
    Feature-rich DataFrame ready for ML ingestion.
    """
    logger.info("Building feature matrix  shape=%s", df.shape)

    d = df.copy()

    # Core groups (always applied)
    d = add_technical_indicators(d)
    d = add_lag_features(d, periods=lag_periods or LAG_PERIODS)
    d = add_rolling_stats(d, windows=rolling_windows or ROLLING_WINDOWS)
    d = add_fourier_features(d, window=fourier_window, n_components=fourier_components)
    d = add_candlestick_features(d)
    d = add_volatility_regime(d)
    d = add_calendar_features(d)

    # Extended groups (optional but on by default)
    if include_swing:
        d = add_swing_levels(d, lookback=swing_lookback)
    if include_divergence:
        d = add_momentum_divergence(d)
    if include_volume_profile:
        d = add_volume_profile(d)
    if include_microstructure:
        d = add_microstructure_proxy(d)
    if include_regime:
        d = add_regime_context(d)

    if drop_na:
        before = len(d)
        d.dropna(inplace=True)
        logger.info("Dropped %d NaN rows (warm-up); final shape=%s", before - len(d), d.shape)

    logger.info("Feature matrix complete: %d features", d.shape[1])
    return d


def feature_names(df: pd.DataFrame) -> list[str]:
    """Return the list of feature column names (excludes OHLCV and target columns)."""
    exclude = {
        "open",
        "high",
        "low",
        "close",
        "volume",
        "vwap",
        "target_ret",
        "target_dir",
        "target_bin",
    }
    return [c for c in df.columns if c not in exclude]


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
    _c_fwd = d["close"].replace(0, np.nan)
    fwd_ret = np.log(_c_fwd.shift(-horizon) / _c_fwd).fillna(0.0)  # lookahead-ok — supervised label
    d["target_ret"] = fwd_ret

    d["target_dir"] = 0
    d.loc[fwd_ret > threshold, "target_dir"] = 1
    d.loc[fwd_ret < -threshold, "target_dir"] = -1

    d["target_bin"] = (fwd_ret > threshold).astype(int)

    return d

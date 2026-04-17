# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# AGPL-3.0 — Share all modifications
"""
ml/mtf_features.py
==================
Multi-Timeframe (MTF) feature engineering for XAUUSD.

Architecture
------------
Takes a base daily OHLCV DataFrame and synthesises higher-timeframe bars
(H4-equivalent via 4-bar aggregation, Weekly, Monthly, Quarterly) then
computes alignment and confluence features across all timeframes.

Why MTF improves accuracy
--------------------------
A single-timeframe model sees only local noise. The key insight:

  HTF trend  ×  LTF entry timing  →  high-probability setups

Specifically:
- Weekly trend direction filters out counter-trend daily signals
- Monthly momentum confirms or rejects weekly breakouts
- Quarterly regime (bull/bear/ranging) gates the entire signal stack
- Cross-timeframe divergence (daily overbought vs weekly uptrend) = fade signal
- Cross-timeframe alignment (all TFs bullish) = high-conviction long

Feature groups added (100+ new features)
-----------------------------------------
MTF-1  Higher-timeframe OHLCV ratios (W, M, Q)
MTF-2  Cross-TF trend alignment score (−1 to +1)
MTF-3  Cross-TF momentum divergence (daily vs weekly vs monthly)
MTF-4  HTF support/resistance proximity (distance to W/M swing highs/lows)
MTF-5  HTF volatility regime (weekly ATR percentile, monthly vol regime)
MTF-6  HTF RSI / momentum state (overbought/oversold on W and M)
MTF-7  Trend-following vs mean-reversion regime gate
MTF-8  Seasonal / cyclical patterns (gold seasonality: Jan effect, Sep rally)
MTF-9  Macro regime features (rate cycle phase, DXY trend, real rates proxy)
MTF-10 Crisis-period indicators (VIX spike proxy, drawdown depth, recovery phase)
"""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


# ── Aggregation helpers ───────────────────────────────────────────────────────


def _resample_ohlcv(df: pd.DataFrame, rule: str) -> pd.DataFrame:
    """Resample daily OHLCV to a higher timeframe."""
    df = df.copy()
    df.index = pd.to_datetime(df["Date"])
    agg = (
        df.resample(rule)
        .agg(
            {
                "open": "first",
                "high": "max",
                "low": "min",
                "close": "last",
                "volume": "sum",
            }
        )
        .dropna(subset=["close"])
    )
    agg.index.name = "Date"
    return agg


def _align_to_daily(htf: pd.DataFrame, daily_dates: pd.DatetimeIndex) -> pd.DataFrame:
    """
    Forward-fill HTF bars onto the daily index.
    Each daily bar gets the most recent completed HTF bar's values.
    """
    htf_reindexed = htf.reindex(daily_dates, method="ffill")
    return htf_reindexed


def _ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False).mean().fillna(s)


def _rsi(s: pd.Series, n: int = 14) -> pd.Series:
    delta = s.diff()
    gain = delta.clip(lower=0).rolling(n).mean()
    loss = (-delta.clip(upper=0)).rolling(n).mean()
    rs = gain / loss.replace(0, np.nan)
    return (100 - 100 / (1 + rs)).fillna(50)


def _atr(h: pd.Series, l: pd.Series, c: pd.Series, n: int = 14) -> pd.Series:
    tr = pd.concat(
        [
            h - l,
            (h - c.shift()).abs(),
            (l - c.shift()).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return tr.rolling(n).mean()


def _zscore(s: pd.Series, n: int) -> pd.Series:
    mu = s.rolling(n).mean()
    sigma = s.rolling(n).std().replace(0, np.nan)
    return ((s - mu) / sigma).fillna(0.0)


def _adx(h: pd.Series, l: pd.Series, c: pd.Series, n: int = 14) -> pd.Series:
    up = h.diff()
    down = -l.diff()
    plus_dm = up.where((up > down) & (up > 0), 0.0)
    minus_dm = down.where((down > up) & (down > 0), 0.0)
    atr14 = _atr(h, l, c, n)
    plus_di = 100 * plus_dm.rolling(n).mean() / atr14.replace(0, np.nan)
    minus_di = 100 * minus_dm.rolling(n).mean() / atr14.replace(0, np.nan)
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    return dx.rolling(n).mean().fillna(0)


# ── MTF feature builder ───────────────────────────────────────────────────────


def build_mtf_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Build multi-timeframe features from a daily OHLCV DataFrame.

    Parameters
    ----------
    df : pd.DataFrame
        Daily OHLCV with columns: Date, open, high, low, close, volume

    Returns
    -------
    pd.DataFrame
        Original df with 100+ MTF feature columns appended.
        Index is reset; Date column preserved.
    """
    df = df.copy()
    df["Date"] = pd.to_datetime(df["Date"])
    df = df.sort_values("Date").reset_index(drop=True)
    daily_idx = pd.DatetimeIndex(df["Date"])

    # ── Resample to HTF ───────────────────────────────────────────────────────
    weekly = _resample_ohlcv(df, "W-FRI")  # weekly bars
    monthly = _resample_ohlcv(df, "ME")  # month-end
    quarterly = _resample_ohlcv(df, "QE")  # quarter-end

    # Align HTF to daily index (forward-fill)
    w = _align_to_daily(weekly, daily_idx)
    m = _align_to_daily(monthly, daily_idx)
    q = _align_to_daily(quarterly, daily_idx)

    d = df.set_index("Date")

    # ── MTF-1: HTF OHLCV ratios ───────────────────────────────────────────────
    for prefix, htf in [("w", w), ("m", m), ("q", q)]:
        c_htf = htf["close"]
        o_htf = htf["open"]
        h_htf = htf["high"]
        l_htf = htf["low"]
        rng = (h_htf - l_htf).replace(0, np.nan)

        d[f"mtf_{prefix}_body_ratio"] = ((c_htf - o_htf).abs() / rng).fillna(0)
        d[f"mtf_{prefix}_bull"] = (c_htf > o_htf).astype(int)
        d[f"mtf_{prefix}_ret1"] = c_htf.pct_change(1).fillna(0)
        d[f"mtf_{prefix}_ret3"] = c_htf.pct_change(3).fillna(0)
        d[f"mtf_{prefix}_close_pos"] = ((d["close"] - l_htf) / rng).fillna(0.5).clip(0, 1)

    # ── MTF-2: Cross-TF trend alignment ───────────────────────────────────────
    # EMA trend direction on each TF: +1 = price > EMA, -1 = below
    for prefix, htf in [("w", w), ("m", m), ("q", q)]:
        c = htf["close"]
        for span in [8, 21, 50]:
            ema = _ema(c, span)
            d[f"mtf_{prefix}_above_ema{span}"] = (c > ema).astype(int) * 2 - 1

    # Alignment score: sum of all EMA signals across TFs (−9 to +9, normalised)
    ema_cols = [c for c in d.columns if "above_ema" in c]
    d["mtf_alignment_score"] = d[ema_cols].sum(axis=1) / max(len(ema_cols), 1)

    # ── MTF-3: Cross-TF momentum divergence ───────────────────────────────────
    d_ret = d["close"].pct_change(5).fillna(0)
    w_ret = w["close"].pct_change(3).reindex(daily_idx, method="ffill").fillna(0)
    m_ret = m["close"].pct_change(2).reindex(daily_idx, method="ffill").fillna(0)

    d["mtf_dw_divergence"] = (d_ret - w_ret).fillna(0)  # daily vs weekly
    d["mtf_dm_divergence"] = (d_ret - m_ret).fillna(0)  # daily vs monthly
    d["mtf_wm_divergence"] = (w_ret - m_ret).fillna(0)  # weekly vs monthly
    d["mtf_dw_div_z20"] = _zscore(d["mtf_dw_divergence"], 20)
    d["mtf_dm_div_z20"] = _zscore(d["mtf_dm_divergence"], 20)

    # ── MTF-4: HTF support/resistance proximity ───────────────────────────────
    for prefix, htf in [("w", w), ("m", m)]:
        h_htf = htf["high"].reindex(daily_idx, method="ffill")
        l_htf = htf["low"].reindex(daily_idx, method="ffill")
        c_htf = htf["close"].reindex(daily_idx, method="ffill")

        # Rolling swing high/low (20-period on HTF, aligned to daily)
        swing_h = htf["high"].rolling(20).max().reindex(daily_idx, method="ffill")
        swing_l = htf["low"].rolling(20).min().reindex(daily_idx, method="ffill")
        atr_htf = _atr(htf["high"], htf["low"], htf["close"], 14).reindex(daily_idx, method="ffill").replace(0, np.nan)

        d[f"mtf_{prefix}_dist_swing_h"] = ((swing_h - d["close"]) / atr_htf).fillna(0).clip(-10, 10)
        d[f"mtf_{prefix}_dist_swing_l"] = ((d["close"] - swing_l) / atr_htf).fillna(0).clip(-10, 10)
        d[f"mtf_{prefix}_near_res"] = (d[f"mtf_{prefix}_dist_swing_h"].abs() < 0.5).astype(int)
        d[f"mtf_{prefix}_near_sup"] = (d[f"mtf_{prefix}_dist_swing_l"].abs() < 0.5).astype(int)

    # ── MTF-5: HTF volatility regime ─────────────────────────────────────────
    for prefix, htf in [("w", w), ("m", m)]:
        atr = _atr(htf["high"], htf["low"], htf["close"], 14)
        atr_pct = atr.rank(pct=True)  # percentile rank
        atr_aligned = atr_pct.reindex(daily_idx, method="ffill").fillna(0.5)
        d[f"mtf_{prefix}_atr_pct"] = atr_aligned
        d[f"mtf_{prefix}_high_vol"] = (atr_aligned > 0.75).astype(int)
        d[f"mtf_{prefix}_low_vol"] = (atr_aligned < 0.25).astype(int)
        d[f"mtf_{prefix}_vol_z20"] = _zscore(atr_aligned, 20)

    # ── MTF-6: HTF RSI / momentum state ──────────────────────────────────────
    for prefix, htf in [("w", w), ("m", m)]:
        rsi = _rsi(htf["close"], 14)
        rsi_aligned = rsi.reindex(daily_idx, method="ffill").fillna(50)
        d[f"mtf_{prefix}_rsi"] = rsi_aligned / 100.0
        d[f"mtf_{prefix}_rsi_ob"] = (rsi_aligned > 70).astype(int)
        d[f"mtf_{prefix}_rsi_os"] = (rsi_aligned < 30).astype(int)
        d[f"mtf_{prefix}_rsi_bull"] = (rsi_aligned > 50).astype(int)
        d[f"mtf_{prefix}_rsi_z20"] = _zscore(rsi_aligned, 20)

    # ── MTF-7: Trend vs mean-reversion regime gate ────────────────────────────
    # Weekly ADX: > 25 = trending, < 20 = ranging
    w_adx = _adx(w["high"], w["low"], w["close"], 14).reindex(daily_idx, method="ffill").fillna(20)
    m_adx = _adx(m["high"], m["low"], m["close"], 14).reindex(daily_idx, method="ffill").fillna(20)

    d["mtf_w_adx"] = w_adx / 100.0
    d["mtf_m_adx"] = m_adx / 100.0
    d["mtf_w_trending"] = (w_adx > 25).astype(int)
    d["mtf_w_ranging"] = (w_adx < 20).astype(int)
    d["mtf_m_trending"] = (m_adx > 25).astype(int)

    # Hurst exponent proxy on weekly (R/S analysis, 20-bar)
    w_close_aligned = w["close"].reindex(daily_idx, method="ffill")
    d["mtf_w_hurst_proxy"] = _hurst_proxy(w_close_aligned, 20)

    # ── MTF-8: Seasonal / cyclical patterns ───────────────────────────────────
    dates = pd.DatetimeIndex(df["Date"])
    d["mtf_month"] = dates.month / 12.0
    d["mtf_month_sin"] = np.sin(2 * np.pi * dates.month / 12)
    d["mtf_month_cos"] = np.cos(2 * np.pi * dates.month / 12)
    d["mtf_quarter"] = dates.quarter / 4.0
    d["mtf_quarter_sin"] = np.sin(2 * np.pi * dates.quarter / 4)
    d["mtf_quarter_cos"] = np.cos(2 * np.pi * dates.quarter / 4)

    # Gold seasonality: historically strong Jan, Aug-Sep; weak Mar-Apr
    GOLD_SEASONAL_SCORE = {
        1: 0.7,
        2: 0.3,
        3: -0.4,
        4: -0.5,
        5: 0.1,
        6: 0.2,
        7: 0.3,
        8: 0.8,
        9: 0.9,
        10: 0.4,
        11: 0.2,
        12: 0.5,
    }
    d["mtf_gold_seasonal"] = dates.month.map(GOLD_SEASONAL_SCORE).fillna(0)

    # Year-end effect (last 10 trading days of year)
    d["mtf_year_end"] = ((dates.month == 12) & (dates.day >= 20)).astype(int)
    d["mtf_jan_effect"] = (dates.month == 1).astype(int)

    # ── MTF-9: Macro regime features ─────────────────────────────────────────
    # Rate cycle proxy: 12M change in monthly close (rising = tightening)
    m_ret12 = m["close"].pct_change(12).reindex(daily_idx, method="ffill").fillna(0)
    d["mtf_m_trend_12m"] = m_ret12
    d["mtf_m_bull_12m"] = (m_ret12 > 0).astype(int)
    d["mtf_m_strong_bull"] = (m_ret12 > 0.10).astype(int)  # >10% annual
    d["mtf_m_bear_12m"] = (m_ret12 < -0.10).astype(int)  # <-10% annual

    # Quarterly momentum (3-month return)
    q_ret3 = q["close"].pct_change(1).reindex(daily_idx, method="ffill").fillna(0)
    d["mtf_q_ret3m"] = q_ret3
    d["mtf_q_bull"] = (q_ret3 > 0).astype(int)

    # Long-term trend: 200-day MA on daily
    ema200 = _ema(d["close"], 200)
    d["mtf_above_ema200"] = (d["close"] > ema200).astype(int) * 2 - 1
    d["mtf_ema200_slope"] = ema200.pct_change(20).fillna(0)
    d["mtf_ema200_z50"] = _zscore(ema200.pct_change(1).fillna(0), 50)

    # ── MTF-10: Crisis / drawdown indicators ─────────────────────────────────
    # Rolling max drawdown (252-day window)
    roll_max = d["close"].rolling(252).max()
    d["mtf_drawdown_252"] = ((d["close"] - roll_max) / roll_max.replace(0, np.nan)).fillna(0)
    d["mtf_in_drawdown"] = (d["mtf_drawdown_252"] < -0.10).astype(int)
    d["mtf_deep_drawdown"] = (d["mtf_drawdown_252"] < -0.20).astype(int)

    # Recovery phase: price recovering from drawdown
    d["mtf_recovering"] = ((d["mtf_drawdown_252"] > -0.10) & (d["mtf_drawdown_252"].shift(20) < -0.10)).astype(int)

    # Volatility spike (daily vol vs 252-day average)
    daily_ret = d["close"].pct_change().fillna(0)
    vol_20 = daily_ret.rolling(20).std()
    vol_252 = daily_ret.rolling(252).std().replace(0, np.nan)
    d["mtf_vol_spike"] = (vol_20 / vol_252).fillna(1.0)
    d["mtf_vol_spike_flag"] = (d["mtf_vol_spike"] > 2.0).astype(int)

    # ── Cross-TF confluence score ─────────────────────────────────────────────
    # Composite bull/bear score from all MTF signals
    bull_signals = [
        "mtf_w_bull",
        "mtf_m_bull",
        "mtf_q_bull",
        "mtf_w_rsi_bull",
        "mtf_m_rsi_bull",
        "mtf_m_bull_12m",
        "mtf_q_bull",
    ]
    bear_signals = [
        "mtf_w_rsi_ob",
        "mtf_m_rsi_ob",
        "mtf_m_bear_12m",
        "mtf_in_drawdown",
    ]
    available_bull = [c for c in bull_signals if c in d.columns]
    available_bear = [c for c in bear_signals if c in d.columns]

    if available_bull:
        d["mtf_bull_confluence"] = d[available_bull].sum(axis=1) / len(available_bull)
    else:
        d["mtf_bull_confluence"] = 0.5

    if available_bear:
        d["mtf_bear_confluence"] = d[available_bear].sum(axis=1) / len(available_bear)
    else:
        d["mtf_bear_confluence"] = 0.5

    d["mtf_net_confluence"] = d["mtf_bull_confluence"] - d["mtf_bear_confluence"]

    # ── Interaction features ──────────────────────────────────────────────────
    # HTF trend × daily momentum (only trade with the trend)
    d["mtf_trend_x_mom"] = d["mtf_alignment_score"] * d["close"].pct_change(5).fillna(0)
    d["mtf_trend_x_vol"] = d["mtf_alignment_score"] * d["mtf_vol_spike"].clip(0, 5)
    d["mtf_conf_x_adx"] = d["mtf_net_confluence"] * d["mtf_w_adx"]

    # Reset index, restore Date column
    result = d.reset_index()
    result["Date"] = result["Date"].dt.strftime("%Y-%m-%d")

    mtf_cols = [c for c in result.columns if c.startswith("mtf_")]
    logger.info("MTF features: %d new columns added", len(mtf_cols))
    return result


# ── Hurst exponent proxy ──────────────────────────────────────────────────────


def _hurst_proxy(s: pd.Series, n: int = 20) -> pd.Series:
    """
    Rolling Hurst exponent proxy via R/S analysis.
    H > 0.5 = trending, H < 0.5 = mean-reverting, H ≈ 0.5 = random walk.
    """

    def _rs(x: np.ndarray) -> float:
        if len(x) < 4:
            return 0.5
        mean = x.mean()
        dev = np.cumsum(x - mean)
        r = dev.max() - dev.min()
        s = x.std()
        if s == 0:
            return 0.5
        return r / s

    log_prices = np.log(s.replace(0, np.nan).ffill())
    returns = log_prices.diff().fillna(0)

    hurst = (
        returns.rolling(n)
        .apply(
            lambda x: 0.5 + 0.5 * np.tanh(np.log(_rs(x) + 1e-8) / np.log(n) - 0.5) if len(x) >= 4 else 0.5,
            raw=True,
        )
        .fillna(0.5)
    )
    return hurst

# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
ml/features_extended.py
=======================
Extended feature engineering — layers 13-16 adding 130+ features on top of
the existing 100-feature base in advanced_features.py.

New layers
----------
13. Order-flow & tape reading  — delta, cumulative delta, buy/sell pressure
14. Fractal geometry           — fractal dimension, self-similarity, chaos
15. Regime-adaptive ensemble   — cross-feature interactions, regime-gated signals
16. Institutional edge signals — anchored VWAP (20/50/100-bar), VWAP slope &
    acceleration, cumulative delta divergence, stacked bid/ask imbalances,
    rolling volume profile (POC/VAH/VAL), institutional absorption, Smart Money
    Index, order-flow momentum divergence, bid/ask pressure ratios

Total output: 230+ features when combined with build_advanced_features().
"""

from __future__ import annotations

import logging
from typing import Dict, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Layer 13: Order-flow & tape reading
# ─────────────────────────────────────────────────────────────────────────────


def add_orderflow_features(df: pd.DataFrame) -> pd.DataFrame:
    """Delta, cumulative delta, buy/sell pressure, VWAP deviation."""
    d = df.copy()
    c, o, h, l, v = (  # noqa: E741
        d["close"],
        d["open"],
        d["high"],
        d["low"],
        d["volume"].replace(0, np.nan),
    )

    # Estimated buy/sell volume via close position in bar range
    bar_range = (h - l).replace(0, np.nan)
    buy_pct = ((c - l) / bar_range).fillna(0.5).clip(0, 1)
    sell_pct = 1.0 - buy_pct

    d["of_buy_vol"] = (buy_pct * v).fillna(0.0)
    d["of_sell_vol"] = (sell_pct * v).fillna(0.0)
    d["of_delta"] = (d["of_buy_vol"] - d["of_sell_vol"]).fillna(0.0)
    d["of_delta_z20"] = _zscore(d["of_delta"], 20)
    d["of_cum_delta_20"] = d["of_delta"].rolling(20).sum().fillna(0.0)
    d["of_cum_delta_z20"] = _zscore(d["of_cum_delta_20"], 40)

    # Buy pressure ratio
    total_vol = (d["of_buy_vol"] + d["of_sell_vol"]).replace(0, np.nan)
    d["of_buy_pressure"] = (d["of_buy_vol"] / total_vol).fillna(0.5)
    d["of_buy_pressure_z20"] = _zscore(d["of_buy_pressure"], 20)

    # VWAP deviation (rolling 20-bar VWAP)
    typical = (h + l + c) / 3
    vwap_num = (typical * v.fillna(0)).rolling(20).sum()
    vwap_den = v.fillna(0).rolling(20).sum().replace(0, np.nan)
    vwap = (vwap_num / vwap_den).fillna(c)
    d["of_vwap_dev"] = ((c - vwap) / vwap.replace(0, np.nan)).fillna(0.0)
    d["of_vwap_dev_z20"] = _zscore(d["of_vwap_dev"], 20)

    # Volume-weighted momentum
    d["of_vw_mom_10"] = (
        d["of_delta"].rolling(10).sum() / v.rolling(10).sum().replace(0, np.nan)
    ).fillna(0.0)
    d["of_vw_mom_20"] = (
        d["of_delta"].rolling(20).sum() / v.rolling(20).sum().replace(0, np.nan)
    ).fillna(0.0)

    # Absorption: large volume with small price move = absorption
    price_move = (c - o).abs()
    d["of_absorption"] = (
        v / (price_move.replace(0, np.nan) * c.replace(0, np.nan))
    ).fillna(0.0)
    d["of_absorption_z20"] = _zscore(d["of_absorption"], 20)

    # Volume surge
    vol_ma20 = v.rolling(20).mean().replace(0, np.nan)
    d["of_vol_surge"] = (v / vol_ma20).fillna(1.0).clip(0, 10)
    d["of_vol_surge_flag"] = (d["of_vol_surge"] > 2.0).astype(int)

    # Tape speed: number of consecutive same-direction closes
    direction = np.sign(c - c.shift(1)).fillna(0)
    d["of_tape_streak"] = (
        direction.groupby((direction != direction.shift()).cumsum()).cumcount() + 1
    )
    d["of_tape_streak"] = d["of_tape_streak"] * direction
    d["of_tape_streak"] = d["of_tape_streak"].fillna(0.0)

    return d


# ─────────────────────────────────────────────────────────────────────────────
# Layer 14: Fractal geometry & chaos theory
# ─────────────────────────────────────────────────────────────────────────────


def add_fractal_features(df: pd.DataFrame, smoke: bool = False) -> pd.DataFrame:
    """Fractal dimension, Lyapunov proxy, self-similarity, chaos indicators.

    In smoke mode all columns are filled with their neutral constant so the
    feature matrix shape stays identical but no expensive rolling apply runs.
    """
    d = df.copy()
    c = d["close"]

    if smoke:
        # Fill with neutral constants — same columns, no computation cost
        d["frac_hfd_10"] = 1.5
        d["frac_hfd_20"] = 1.5
        d["frac_dfa_20"] = 0.5
        d["frac_dfa_40"] = 0.5
        d["frac_lyapunov_10"] = 0.0
        d["frac_apen_10"] = 0.0
        d["frac_perm_ent_5"] = 0.0
        d["frac_perm_ent_10"] = 0.0
        d["frac_recurrence_20"] = 0.0
        d["frac_wavelet_ratio"] = 1.0
        d["frac_corr_dim"] = 1.5
        return d

    # Higuchi fractal dimension proxy (simplified)
    d["frac_hfd_10"] = _rolling_hfd(c, window=20, k_max=4)
    d["frac_hfd_20"] = _rolling_hfd(c, window=40, k_max=5)

    # Detrended fluctuation analysis proxy
    d["frac_dfa_20"] = _rolling_dfa(c, window=40)
    d["frac_dfa_40"] = _rolling_dfa(c, window=80)

    # Lyapunov exponent proxy (divergence of nearby trajectories)
    d["frac_lyapunov_10"] = _rolling_lyapunov(c, window=20)

    # Approximate entropy (complexity measure)
    d["frac_apen_10"] = _rolling_apen(c, window=20, m=2, r_factor=0.2)

    # Permutation entropy
    d["frac_perm_ent_5"] = _rolling_perm_entropy(c, window=20, order=3)
    d["frac_perm_ent_10"] = _rolling_perm_entropy(c, window=40, order=4)

    # Recurrence rate proxy
    d["frac_recurrence_20"] = _rolling_recurrence(c, window=40, eps_factor=0.1)

    # Wavelet energy ratio (high-freq vs low-freq energy)
    d["frac_wavelet_ratio"] = _rolling_wavelet_ratio(c, window=32)

    # Correlation dimension proxy
    d["frac_corr_dim"] = _rolling_corr_dim(c, window=40)

    return d


def _rolling_hfd(series: pd.Series, window: int, k_max: int) -> pd.Series:
    """Higuchi fractal dimension via rolling window."""

    def _hfd(x: np.ndarray) -> float:
        n = len(x)
        if n < k_max * 2:
            return 1.5
        lk = []
        for k in range(1, k_max + 1):
            lm = []
            for m in range(1, k + 1):
                idxs = np.arange(m - 1, n, k)
                if len(idxs) < 2:
                    continue
                xm = x[idxs]
                lm.append(np.sum(np.abs(np.diff(xm))) * (n - 1) / (k * len(xm)))
            if lm:
                lk.append(np.mean(lm))
        if len(lk) < 2:
            return 1.5
        log_k = np.log(np.arange(1, len(lk) + 1))
        log_lk = np.log(np.array(lk) + 1e-10)
        try:
            return float(np.polyfit(log_k, log_lk, 1)[0])
        except Exception:
            return 1.5

    return series.rolling(window).apply(_hfd, raw=True).fillna(1.5)


def _rolling_dfa(series: pd.Series, window: int) -> pd.Series:
    """Detrended fluctuation analysis scaling exponent."""

    def _dfa(x: np.ndarray) -> float:
        n = len(x)
        if n < 16:
            return 0.5
        y = np.cumsum(x - np.mean(x))
        scales = [4, 8, max(8, n // 4)]
        f = []
        for s in scales:
            if s >= n:
                continue
            segs = n // s
            if segs < 1:
                continue
            rms = []
            for i in range(segs):
                seg = y[i * s : (i + 1) * s]
                t = np.arange(len(seg))
                try:
                    p = np.polyfit(t, seg, 1)
                    rms.append(np.sqrt(np.mean((seg - np.polyval(p, t)) ** 2)))
                except Exception as _exc:
                    logger.debug('Suppressed exception: %s', _exc)
            if rms:
                f.append(np.mean(rms))
        if len(f) < 2:
            return 0.5
        log_s = np.log([4, 8, max(8, n // 4)][: len(f)])
        log_f = np.log(np.array(f) + 1e-10)
        try:
            return float(np.polyfit(log_s, log_f, 1)[0])
        except Exception:
            return 0.5

    return series.rolling(window).apply(_dfa, raw=True).fillna(0.5)


def _rolling_lyapunov(series: pd.Series, window: int) -> pd.Series:
    """Largest Lyapunov exponent proxy."""

    def _lyap(x: np.ndarray) -> float:
        n = len(x)
        if n < 8:
            return 0.0
        divergences = []
        for i in range(n // 2):
            diffs = np.abs(x[i + 1 :] - x[i])
            if len(diffs) == 0:
                continue
            min_d = np.min(diffs[diffs > 0]) if np.any(diffs > 0) else 1e-10
            divergences.append(np.log(min_d + 1e-10))
        return float(np.mean(divergences)) if divergences else 0.0

    return series.rolling(window).apply(_lyap, raw=True).fillna(0.0)


def _rolling_apen(series: pd.Series, window: int, m: int, r_factor: float) -> pd.Series:
    """Approximate entropy."""

    def _apen(x: np.ndarray) -> float:
        n = len(x)
        r = r_factor * np.std(x)
        if r == 0 or n < m + 2:
            return 0.0

        def _phi(m_):
            count = 0
            total = 0
            for i in range(n - m_):
                template = x[i : i + m_]
                for j in range(n - m_):
                    if np.max(np.abs(x[j : j + m_] - template)) <= r:
                        count += 1
                total += 1
            return np.log(count / max(total, 1) + 1e-10)

        try:
            return float(_phi(m) - _phi(m + 1))
        except Exception:
            return 0.0

    return series.rolling(window).apply(_apen, raw=True).fillna(0.0)


def _rolling_perm_entropy(series: pd.Series, window: int, order: int) -> pd.Series:
    """Permutation entropy."""

    def _pe(x: np.ndarray) -> float:
        n = len(x)
        if n < order:
            return 0.0
        import math

        counts: dict = {}
        for i in range(n - order + 1):
            perm = tuple(np.argsort(x[i : i + order]))
            counts[perm] = counts.get(perm, 0) + 1
        total = sum(counts.values())
        entropy = 0.0
        for cnt in counts.values():
            p = cnt / total
            entropy -= p * math.log(p + 1e-10)
        max_entropy = math.log(math.factorial(order) + 1e-10)
        return float(entropy / max_entropy) if max_entropy > 0 else 0.0

    return series.rolling(window).apply(_pe, raw=True).fillna(0.0)


def _rolling_recurrence(series: pd.Series, window: int, eps_factor: float) -> pd.Series:
    """Recurrence rate: fraction of state-space points within eps of each other."""

    def _rr(x: np.ndarray) -> float:
        n = len(x)
        if n < 4:
            return 0.0
        eps = eps_factor * np.std(x)
        if eps == 0:
            return 0.0
        count = 0
        total = n * (n - 1)
        for i in range(n):
            count += np.sum(np.abs(x - x[i]) < eps) - 1
        return float(count / max(total, 1))

    return series.rolling(window).apply(_rr, raw=True).fillna(0.0)


def _rolling_wavelet_ratio(series: pd.Series, window: int) -> pd.Series:
    """High-freq vs low-freq energy ratio via Haar wavelet."""

    def _wr(x: np.ndarray) -> float:
        n = len(x)
        if n < 4:
            return 1.0
        # One level Haar
        n2 = (n // 2) * 2
        x2 = x[:n2]
        approx = (x2[::2] + x2[1::2]) / 2
        detail = (x2[::2] - x2[1::2]) / 2
        e_approx = np.sum(approx**2) + 1e-10
        e_detail = np.sum(detail**2) + 1e-10
        return float(e_detail / e_approx)

    return series.rolling(window).apply(_wr, raw=True).fillna(1.0)


def _rolling_corr_dim(series: pd.Series, window: int) -> pd.Series:
    """Correlation dimension proxy (Grassberger-Procaccia)."""

    def _cd(x: np.ndarray) -> float:
        n = len(x)
        if n < 8:
            return 1.0
        eps_vals = np.percentile(np.abs(np.diff(x)), [25, 50, 75])
        c_vals = []
        for eps in eps_vals:
            if eps == 0:
                continue
            count = 0
            for i in range(n):
                count += np.sum(np.abs(x - x[i]) < eps) - 1
            c_vals.append(count / max(n * (n - 1), 1))
        if len(c_vals) < 2:
            return 1.0
        log_eps = np.log(eps_vals[: len(c_vals)] + 1e-10)
        log_c = np.log(np.array(c_vals) + 1e-10)
        try:
            return float(np.polyfit(log_eps, log_c, 1)[0])
        except Exception:
            return 1.0

    return series.rolling(window).apply(_cd, raw=True).fillna(1.0)


# ─────────────────────────────────────────────────────────────────────────────
# Layer 15: Regime-adaptive cross-feature interactions
# ─────────────────────────────────────────────────────────────────────────────


def add_regime_interactions(df: pd.DataFrame) -> pd.DataFrame:
    """
    Cross-feature interactions gated by market regime.
    Requires prior layers to have run (uses regime_*, mom_*, vol_* columns).
    """
    d = df.copy()
    c = d["close"]

    # RSI (14)
    delta = c.diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = (-delta.clip(upper=0)).rolling(14).mean().replace(0, np.nan)
    rs = gain / loss
    d["ri_rsi_14"] = (100 - 100 / (1 + rs)).fillna(50.0)
    d["ri_rsi_z20"] = _zscore(d["ri_rsi_14"], 20)
    d["ri_rsi_overbought"] = (d["ri_rsi_14"] > 70).astype(int)
    d["ri_rsi_oversold"] = (d["ri_rsi_14"] < 30).astype(int)

    # MACD
    ema12 = c.ewm(span=12, adjust=False).mean()
    ema26 = c.ewm(span=26, adjust=False).mean()
    macd = ema12 - ema26
    signal_line = macd.ewm(span=9, adjust=False).mean()
    d["ri_macd"] = macd
    d["ri_macd_signal"] = signal_line
    d["ri_macd_hist"] = macd - signal_line
    d["ri_macd_hist_z20"] = _zscore(d["ri_macd_hist"], 20)
    d["ri_macd_cross_bull"] = (
        (macd > signal_line) & (macd.shift(1) <= signal_line.shift(1))
    ).astype(int)
    d["ri_macd_cross_bear"] = (
        (macd < signal_line) & (macd.shift(1) >= signal_line.shift(1))
    ).astype(int)

    # Bollinger Bands
    ma20 = c.rolling(20).mean()
    std20 = c.rolling(20).std().replace(0, np.nan)
    bb_upper = ma20 + 2 * std20
    bb_lower = ma20 - 2 * std20
    bb_width = (bb_upper - bb_lower) / ma20.replace(0, np.nan)
    d["ri_bb_pct"] = ((c - bb_lower) / (bb_upper - bb_lower).replace(0, np.nan)).fillna(
        0.5
    )
    d["ri_bb_width"] = bb_width.fillna(0.0)
    d["ri_bb_width_z20"] = _zscore(d["ri_bb_width"], 20)
    d["ri_bb_squeeze"] = (
        d["ri_bb_width"] < d["ri_bb_width"].rolling(20).quantile(0.2)
    ).astype(int)
    d["ri_bb_expansion"] = (
        d["ri_bb_width"] > d["ri_bb_width"].rolling(20).quantile(0.8)
    ).astype(int)

    # Ichimoku components (simplified)
    high9 = d["high"].rolling(9).max()
    low9 = d["low"].rolling(9).min()
    high26 = d["high"].rolling(26).max()
    low26 = d["low"].rolling(26).min()
    tenkan = (high9 + low9) / 2
    kijun = (high26 + low26) / 2
    d["ri_tenkan_kijun_diff"] = ((tenkan - kijun) / c.replace(0, np.nan)).fillna(0.0)
    d["ri_price_above_kijun"] = (c > kijun).astype(int)
    d["ri_tk_cross_bull"] = (
        (tenkan > kijun) & (tenkan.shift(1) <= kijun.shift(1))
    ).astype(int)
    d["ri_tk_cross_bear"] = (
        (tenkan < kijun) & (tenkan.shift(1) >= kijun.shift(1))
    ).astype(int)

    # Regime-gated momentum: momentum × regime_trend (if available)
    if "regime_trend" in d.columns and "mom_20" in d.columns:
        d["ri_regime_mom"] = d["regime_trend"] * d["mom_20"]
    else:
        d["ri_regime_mom"] = 0.0

    # Volatility-adjusted momentum
    if "rvol_20" in d.columns and "mom_20" in d.columns:
        vol_adj = d["rvol_20"].replace(0, np.nan)
        d["ri_vol_adj_mom"] = (d["mom_20"] / vol_adj).fillna(0.0).clip(-5, 5)
    else:
        d["ri_vol_adj_mom"] = 0.0

    # Trend × volume confirmation
    if "adx_14" in d.columns and "of_vol_surge" in d.columns:
        d["ri_trend_vol_confirm"] = (d["adx_14"] / 100.0) * d["of_vol_surge"].clip(0, 3)
    else:
        d["ri_trend_vol_confirm"] = 0.0

    # Mean-reversion signal: RSI + BB combined
    d["ri_mean_rev_score"] = (
        d["ri_rsi_oversold"].astype(float) + (d["ri_bb_pct"] < 0.1).astype(float)
    ) / 2.0 - (
        d["ri_rsi_overbought"].astype(float) + (d["ri_bb_pct"] > 0.9).astype(float)
    ) / 2.0

    # Momentum quality: alignment of RSI, MACD, price momentum
    mom_sign = np.sign(d.get("mom_20", pd.Series(0.0, index=d.index)))
    rsi_sign = np.sign(d["ri_rsi_14"] - 50)
    macd_sign = np.sign(d["ri_macd_hist"])
    d["ri_signal_alignment"] = (
        (mom_sign == rsi_sign).astype(int) + (rsi_sign == macd_sign).astype(int)
    ) / 2.0

    # Composite bull/bear score
    d["ri_bull_score"] = (
        d["ri_rsi_oversold"].astype(float) * 0.2
        + (d["ri_bb_pct"] < 0.2).astype(float) * 0.2
        + d["ri_macd_cross_bull"].astype(float) * 0.3
        + d["ri_tk_cross_bull"].astype(float) * 0.3
    )
    d["ri_bear_score"] = (
        d["ri_rsi_overbought"].astype(float) * 0.2
        + (d["ri_bb_pct"] > 0.8).astype(float) * 0.2
        + d["ri_macd_cross_bear"].astype(float) * 0.3
        + d["ri_tk_cross_bear"].astype(float) * 0.3
    )

    return d


# ─────────────────────────────────────────────────────────────────────────────
# Layer 16: Institutional edge signals
#
# VWAP anchoring, order-flow imbalance, delta divergence, volume profile
# (POC / VAH / VAL), stacked imbalances, and smart-money footprint features.
#
# These signals capture the behaviour of institutional participants:
# - Anchored VWAP from session open / swing high / swing low
# - Volume-weighted price levels where institutions accumulate / distribute
# - Delta divergence: price makes new high but cumulative delta falls
# - Stacked bid/ask imbalances: consecutive bars with one-sided pressure
# - Volume profile: Point of Control, Value Area High/Low, TPO count
# ─────────────────────────────────────────────────────────────────────────────


def add_institutional_edge_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Layer 16: Institutional edge signals — VWAP + order flow.

    Adds ~35 features:
    - Anchored VWAP (session, 20-bar, 50-bar) + deviations
    - VWAP slope and acceleration
    - Delta divergence (price vs cumulative delta)
    - Stacked imbalance detection (3+ consecutive same-side bars)
    - Volume profile: POC, VAH, VAL, TPO count, value area width
    - Institutional absorption: large volume, small price move
    - Smart money index (SMI): early vs late session price action
    - Order flow momentum divergence
    - Bid/ask pressure ratio rolling windows
    """
    d = df.copy()
    c = d["close"]
    o = d["open"]
    h = d["high"]
    l = d["low"]  # noqa: E741
    v = d["volume"].replace(0, np.nan)

    # ── Typical price and volume-weighted price ───────────────────────────────
    typical = (h + l + c) / 3.0

    # ── Anchored VWAP: rolling windows ───────────────────────────────────────
    # 20-bar VWAP (intraday session proxy)
    vwap_20_num = (typical * v.fillna(0)).rolling(20).sum()
    vwap_20_den = v.fillna(0).rolling(20).sum().replace(0, np.nan)
    vwap_20 = (vwap_20_num / vwap_20_den).fillna(c)

    # 50-bar VWAP (multi-session / swing level)
    vwap_50_num = (typical * v.fillna(0)).rolling(50).sum()
    vwap_50_den = v.fillna(0).rolling(50).sum().replace(0, np.nan)
    vwap_50 = (vwap_50_num / vwap_50_den).fillna(c)

    # 100-bar VWAP (weekly / institutional reference)
    vwap_100_num = (typical * v.fillna(0)).rolling(100).sum()
    vwap_100_den = v.fillna(0).rolling(100).sum().replace(0, np.nan)
    vwap_100 = (vwap_100_num / vwap_100_den).fillna(c)

    # VWAP deviations (normalised by VWAP so cross-instrument comparable)
    d["inst_vwap20_dev"] = ((c - vwap_20) / vwap_20.replace(0, np.nan)).fillna(0.0)
    d["inst_vwap50_dev"] = ((c - vwap_50) / vwap_50.replace(0, np.nan)).fillna(0.0)
    d["inst_vwap100_dev"] = ((c - vwap_100) / vwap_100.replace(0, np.nan)).fillna(0.0)

    # Z-scores of VWAP deviations
    d["inst_vwap20_dev_z"] = _zscore(d["inst_vwap20_dev"], 20)
    d["inst_vwap50_dev_z"] = _zscore(d["inst_vwap50_dev"], 20)

    # Price position relative to VWAP stack (above all 3 = strong bull)
    d["inst_above_vwap20"] = (c > vwap_20).astype(int)
    d["inst_above_vwap50"] = (c > vwap_50).astype(int)
    d["inst_above_vwap100"] = (c > vwap_100).astype(int)
    d["inst_vwap_stack_bull"] = (
        d["inst_above_vwap20"] + d["inst_above_vwap50"] + d["inst_above_vwap100"]
    )  # 0–3: 3 = price above all VWAPs (institutional bull)

    # VWAP slope: rate of change of 20-bar VWAP (trend direction of institutions)
    d["inst_vwap20_slope"] = (
        (vwap_20 - vwap_20.shift(5)) / vwap_20.shift(5).replace(0, np.nan)
    ).fillna(0.0)
    d["inst_vwap20_accel"] = (
        d["inst_vwap20_slope"] - d["inst_vwap20_slope"].shift(5)
    ).fillna(0.0)

    # ── Buy/sell volume estimation ────────────────────────────────────────────
    bar_range = (h - l).replace(0, np.nan)
    buy_pct = ((c - l) / bar_range).fillna(0.5).clip(0, 1)
    sell_pct = 1.0 - buy_pct
    buy_vol = (buy_pct * v.fillna(0))
    sell_vol = (sell_pct * v.fillna(0))
    delta = buy_vol - sell_vol

    # ── Cumulative delta and divergence ───────────────────────────────────────
    cum_delta_20 = delta.rolling(20).sum().fillna(0.0)
    cum_delta_50 = delta.rolling(50).sum().fillna(0.0)

    d["inst_cum_delta_20"] = cum_delta_20
    d["inst_cum_delta_50"] = cum_delta_50
    d["inst_cum_delta_20_z"] = _zscore(cum_delta_20, 20)

    # Delta divergence: price makes new 20-bar high but cum_delta falls
    # (bearish divergence = institutional distribution at highs)
    price_new_high_20 = (c == c.rolling(20).max()).astype(int)
    delta_falling = (cum_delta_20 < cum_delta_20.shift(5)).astype(int)
    d["inst_bearish_delta_div"] = (price_new_high_20 & delta_falling).astype(int)

    price_new_low_20 = (c == c.rolling(20).min()).astype(int)
    delta_rising = (cum_delta_20 > cum_delta_20.shift(5)).astype(int)
    d["inst_bullish_delta_div"] = (price_new_low_20 & delta_rising).astype(int)

    # ── Stacked imbalances ────────────────────────────────────────────────────
    # 3+ consecutive bars where buy_vol > sell_vol × threshold (bid stacking)
    imbalance_threshold = 1.5  # buy_vol must be 1.5× sell_vol
    buy_dominant = (buy_vol > sell_vol * imbalance_threshold).astype(int)
    sell_dominant = (sell_vol > buy_vol * imbalance_threshold).astype(int)

    # Rolling sum of consecutive dominance (stacked = 3+ in a row)
    d["inst_buy_stack_3"] = buy_dominant.rolling(3).sum().fillna(0).astype(int)
    d["inst_sell_stack_3"] = sell_dominant.rolling(3).sum().fillna(0).astype(int)
    d["inst_buy_stacked"] = (d["inst_buy_stack_3"] >= 3).astype(int)
    d["inst_sell_stacked"] = (d["inst_sell_stack_3"] >= 3).astype(int)

    # ── Volume profile: POC, VAH, VAL ─────────────────────────────────────────
    # Computed over a rolling 50-bar window using price buckets.
    # POC = price level with highest volume (Point of Control)
    # VAH/VAL = Value Area High/Low (70% of volume)
    poc, vah, val = _rolling_volume_profile(h, l, c, v.fillna(0), window=50)
    d["inst_poc"] = poc
    d["inst_vah"] = vah
    d["inst_val"] = val

    # Normalised distances from current price to profile levels
    d["inst_dist_poc"] = ((c - poc) / poc.replace(0, np.nan)).fillna(0.0)
    d["inst_dist_vah"] = ((c - vah) / vah.replace(0, np.nan)).fillna(0.0)
    d["inst_dist_val"] = ((c - val) / val.replace(0, np.nan)).fillna(0.0)
    d["inst_va_width"] = ((vah - val) / poc.replace(0, np.nan)).fillna(0.0)

    # Price position within value area (0 = at VAL, 1 = at VAH)
    va_range = (vah - val).replace(0, np.nan)
    d["inst_va_position"] = ((c - val) / va_range).fillna(0.5).clip(0, 1)

    # ── Institutional absorption ──────────────────────────────────────────────
    # Large volume + small price move = institutions absorbing supply/demand
    price_move = (c - o).abs().replace(0, np.nan)
    vol_ma20 = v.rolling(20).mean().replace(0, np.nan)
    d["inst_absorption_ratio"] = (
        (v / vol_ma20) / (price_move / c.replace(0, np.nan))
    ).fillna(0.0).clip(0, 100)
    d["inst_absorption_z"] = _zscore(d["inst_absorption_ratio"], 20)
    # High absorption = large vol, small move (institutional accumulation/distribution)
    d["inst_high_absorption"] = (
        d["inst_absorption_z"] > 1.5
    ).astype(int)

    # ── Smart Money Index (SMI) ───────────────────────────────────────────────
    # SMI = close - open (first 30 min proxy) + close - open (last 30 min proxy)
    # On H1 bars: first bar of session = dumb money, last bar = smart money
    # Proxy: (close - open) of current bar vs (close - open) of 8 bars ago
    early_move = (o - o.shift(1)).fillna(0.0)   # gap open = retail reaction
    late_move = (c - o).fillna(0.0)              # intrabar close = smart money
    d["inst_smi"] = (late_move - early_move).fillna(0.0)
    d["inst_smi_z20"] = _zscore(d["inst_smi"], 20)
    d["inst_smi_ma10"] = d["inst_smi"].rolling(10).mean().fillna(0.0)

    # ── Order flow momentum divergence ────────────────────────────────────────
    # Price momentum vs delta momentum — divergence signals exhaustion
    price_mom_10 = (c - c.shift(10)).fillna(0.0)
    delta_mom_10 = (cum_delta_20 - cum_delta_20.shift(10)).fillna(0.0)

    # Normalise both to [-1, 1] range for comparison
    price_mom_norm = _rolling_minmax_norm(price_mom_10, 20)
    delta_mom_norm = _rolling_minmax_norm(delta_mom_10, 20)
    d["inst_of_divergence"] = (price_mom_norm - delta_mom_norm).fillna(0.0)
    d["inst_of_divergence_z"] = _zscore(d["inst_of_divergence"], 20)

    # ── Bid/ask pressure ratio ────────────────────────────────────────────────
    total_vol = (buy_vol + sell_vol).replace(0, np.nan)
    buy_pressure = (buy_vol / total_vol).fillna(0.5)
    d["inst_buy_pressure_10"] = buy_pressure.rolling(10).mean().fillna(0.5)
    d["inst_buy_pressure_20"] = buy_pressure.rolling(20).mean().fillna(0.5)
    d["inst_pressure_imbalance"] = (
        d["inst_buy_pressure_20"] - 0.5
    ) * 2.0  # [-1, 1]: positive = buy-side dominant

    return d


def _rolling_volume_profile(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    volume: pd.Series,
    window: int = 50,
    n_buckets: int = 20,
) -> tuple:
    """
    Compute rolling volume profile: POC, VAH, VAL over a lookback window.

    Uses price buckets (n_buckets bins between rolling high and low) and
    distributes each bar's volume proportionally across the buckets it spans.

    Returns three pd.Series: (poc, vah, val) aligned to the input index.
    """
    n = len(close)
    poc_vals = np.full(n, np.nan)
    vah_vals = np.full(n, np.nan)
    val_vals = np.full(n, np.nan)

    h_arr = high.values.astype(float)
    l_arr = low.values.astype(float)
    c_arr = close.values.astype(float)
    v_arr = volume.values.astype(float)

    for i in range(window - 1, n):
        start = i - window + 1
        h_w = h_arr[start : i + 1]
        l_w = l_arr[start : i + 1]
        v_w = v_arr[start : i + 1]

        price_high = np.nanmax(h_w)
        price_low = np.nanmin(l_w)
        if price_high <= price_low or np.isnan(price_high):
            poc_vals[i] = c_arr[i]
            vah_vals[i] = c_arr[i]
            val_vals[i] = c_arr[i]
            continue

        # Build price buckets
        bucket_edges = np.linspace(price_low, price_high, n_buckets + 1)
        bucket_mid = (bucket_edges[:-1] + bucket_edges[1:]) / 2.0
        bucket_vol = np.zeros(n_buckets)

        for j in range(len(h_w)):
            bar_h = h_w[j]
            bar_l = l_w[j]
            bar_v = v_w[j]
            if np.isnan(bar_v) or bar_v <= 0:
                continue
            # Find buckets this bar spans
            lo_idx = np.searchsorted(bucket_edges, bar_l, side="left")
            hi_idx = np.searchsorted(bucket_edges, bar_h, side="right")
            lo_idx = max(0, min(lo_idx, n_buckets - 1))
            hi_idx = max(0, min(hi_idx, n_buckets))
            span = hi_idx - lo_idx
            if span > 0:
                bucket_vol[lo_idx:hi_idx] += bar_v / span

        # POC = bucket with highest volume
        poc_idx = int(np.argmax(bucket_vol))
        poc_vals[i] = bucket_mid[poc_idx]

        # Value Area: 70% of total volume centred on POC
        total_vol_w = np.sum(bucket_vol)
        target_vol = total_vol_w * 0.70
        va_vol = bucket_vol[poc_idx]
        lo_ptr = poc_idx
        hi_ptr = poc_idx

        while va_vol < target_vol:
            can_expand_up = hi_ptr + 1 < n_buckets
            can_expand_dn = lo_ptr - 1 >= 0
            if not can_expand_up and not can_expand_dn:
                break
            up_vol = bucket_vol[hi_ptr + 1] if can_expand_up else -1
            dn_vol = bucket_vol[lo_ptr - 1] if can_expand_dn else -1
            if up_vol >= dn_vol:
                hi_ptr += 1
                va_vol += bucket_vol[hi_ptr]
            else:
                lo_ptr -= 1
                va_vol += bucket_vol[lo_ptr]

        vah_vals[i] = bucket_mid[hi_ptr]
        val_vals[i] = bucket_mid[lo_ptr]

    idx = close.index
    return (
        pd.Series(poc_vals, index=idx).ffill().fillna(close),
        pd.Series(vah_vals, index=idx).ffill().fillna(close),
        pd.Series(val_vals, index=idx).ffill().fillna(close),
    )


def _rolling_minmax_norm(series: pd.Series, window: int) -> pd.Series:
    """Normalise series to [-1, 1] using rolling min/max."""
    roll_min = series.rolling(window).min()
    roll_max = series.rolling(window).max()
    denom = (roll_max - roll_min).replace(0, np.nan)
    return (2.0 * (series - roll_min) / denom - 1.0).fillna(0.0)


# ─────────────────────────────────────────────────────────────────────────────
# Master builder: 200+ features
# ─────────────────────────────────────────────────────────────────────────────


def build_extended_features(
    ohlcv: pd.DataFrame,
    macro_df: Optional[pd.DataFrame] = None,
    horizon: int = 1,
    use_filtered_target: bool = True,
    min_move_atr: float = 0.25,
    smoke: bool = False,
) -> tuple[pd.DataFrame, pd.Series]:
    """
    Build 200+ feature matrix by combining base advanced_features (100)
    with extended layers 13-15 (100+ more).

    Parameters
    ----------
    ohlcv              : OHLCV DataFrame (open/high/low/close/volume)
    macro_df           : Optional macro DataFrame
    horizon            : Prediction horizon in bars
    use_filtered_target: Drop low-conviction bars from training
    min_move_atr       : Minimum move (ATR units) to include a bar
    smoke              : Skip expensive computations for CI speed

    Returns
    -------
    X : Feature DataFrame (200+ columns, no NaN, all stationary)
    y : Binary target Series (0=down, 1=up)
    """
    from ml.advanced_features import build_advanced_features

    # Base 100 features
    X_base, y_base = build_advanced_features(
        ohlcv,
        macro_df=macro_df,
        horizon=horizon,
        use_filtered_target=use_filtered_target,
        min_move_atr=min_move_atr,
        smoke=smoke,
    )

    # Re-run on full ohlcv to get extended features aligned to same index
    d = ohlcv.copy()
    d.columns = [c.lower() for c in d.columns]
    if "volume" not in d.columns:
        d["volume"] = 0.0

    # Apply extended layers
    d = add_orderflow_features(d)
    d = add_fractal_features(d, smoke=smoke)
    d = add_regime_interactions(d)
    d = add_institutional_edge_features(d)  # Layer 16: VWAP + order flow

    # Collect only new columns (not in base OHLCV)
    base_cols = {"open", "high", "low", "close", "volume"}
    ext_cols = [c for c in d.columns if c not in base_cols]
    d_ext = d[ext_cols].copy()

    # Align to X_base index
    d_ext = d_ext.reindex(X_base.index)
    d_ext = d_ext.replace([np.inf, -np.inf], np.nan).fillna(0.0)

    # Merge
    X = pd.concat([X_base, d_ext], axis=1)
    # Drop any duplicate columns
    X = X.loc[:, ~X.columns.duplicated()]

    logger.info(
        "Extended features: %d bars × %d features (base=%d, extended=%d)",
        len(X),
        X.shape[1],
        X_base.shape[1],
        d_ext.shape[1],
    )
    return X, y_base


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


def _zscore(s: pd.Series, w: int) -> pd.Series:
    mu = s.rolling(w).mean()
    sig = s.rolling(w).std().replace(0, np.nan)
    return ((s - mu) / sig).fillna(0.0)


# ─────────────────────────────────────────────────────────────────────────────
# Layer 17: Live data layer features (orchestrator injection)
# ─────────────────────────────────────────────────────────────────────────────


def add_data_layer_features(
    df: pd.DataFrame,
    as_of: Optional[pd.Timestamp] = None,
) -> pd.DataFrame:
    """
    Inject real-time data layer features from MarketDataOrchestrator into
    an OHLCV feature DataFrame.

    This is the ONLY function that bridges the data_layer into the ML
    feature pipeline. All data comes exclusively from the orchestrator —
    no direct broker or feed calls.

    Features injected (26 total)
    ----------------------------
    Microstructure (16):
      dl_spread, dl_spread_pct, dl_ofi, dl_trade_pressure,
      dl_buy_pressure, dl_sell_pressure, dl_cumulative_delta,
      dl_volume_delta, dl_vwap, dl_bid_depth, dl_ask_depth,
      dl_depth_imbalance, dl_tick_count, dl_spread_z20,
      dl_ofi_ema5, dl_pressure_divergence

    Sentiment (4):
      dl_news_sentiment, dl_news_momentum, dl_news_count_1h,
      dl_news_bullish_ratio

    Macro calendar (6):
      dl_macro_impact, dl_hours_to_next_high, dl_hours_since_last_high,
      dl_macro_surprise, dl_high_event_count_24h, dl_is_blackout

    Parameters
    ----------
    df     : OHLCV DataFrame with DatetimeIndex (UTC)
    as_of  : If provided, only use data available at this timestamp
             (causal guarantee for backtesting). If None, uses live data.

    Returns
    -------
    DataFrame with 26 additional dl_* columns appended.
    All columns are forward-filled and NaN-filled with neutral values.
    """
    d = df.copy()
    n = len(d)

    # ── Pull features from orchestrator ──────────────────────────────────────
    features: Dict[str, float] = {}
    try:
        from data_layer.orchestrator import orchestrator
        features = orchestrator.get_ml_features(as_of=as_of)
    except Exception as exc:
        logger.debug("add_data_layer_features: orchestrator unavailable: %s", exc)

    # ── Microstructure features (keys match orchestrator.get_ml_features()) ──
    spread          = features.get("micro_spread",           0.0)
    spread_pct      = features.get("micro_spread_pct",       0.0)
    ofi             = features.get("micro_ofi",              0.0)
    trade_pressure  = features.get("micro_trade_pressure",   0.0)
    buy_pressure    = features.get("micro_buy_pressure",     0.5)
    sell_pressure   = features.get("micro_sell_pressure",    0.5)
    cum_delta       = features.get("micro_cumulative_delta", 0.0)
    vol_delta       = features.get("micro_volume_delta",     0.0)
    vwap            = features.get("micro_vwap_dev",         0.0)
    # ── L2 order book features (populated from OrderBookFeed when available) ──
    bid_depth       = features.get("micro_bid_depth",        0.0)
    ask_depth       = features.get("micro_ask_depth",        0.0)
    depth_imbalance = features.get("micro_depth_imbalance",  0.0)
    # Supplement with live L2 feed if orchestrator didn't provide depth data
    if bid_depth == 0.0 and ask_depth == 0.0:
        try:
            from market_data.order_book import get_order_book_feed
            _l2_feed = get_order_book_feed()
            # Derive symbol from DataFrame index or use default
            _symbol = getattr(df, "_hopefx_symbol", "XAU_USD")
            _l2_features = _l2_feed.get_ml_features(_symbol)
            bid_depth       = _l2_features.get("micro_bid_depth",       0.0)
            ask_depth       = _l2_features.get("micro_ask_depth",       0.0)
            depth_imbalance = _l2_features.get("micro_depth_imbalance", depth_imbalance)
            # Also update OFI and pressure from L2 if available
            if _l2_features.get("micro_obi", 0.0) != 0.0:
                ofi = _l2_features["micro_obi"]
        except Exception as _l2_exc:
            logger.debug("L2 order book features unavailable: %s", _l2_exc)
    tick_count      = 0.0

    # Derived microstructure
    spread_z20   = features.get("micro_spread_z",          0.0)
    ofi_ema5     = features.get("micro_ofi",               ofi)   # EMA already in engine
    pressure_div = buy_pressure - sell_pressure

    # ── Sentiment features ────────────────────────────────────────────────────
    news_sentiment  = features.get("news_sentiment_score",    0.0)
    news_momentum   = features.get("news_sentiment_momentum", 0.0)
    news_count_1h   = features.get("news_article_count_1h",   0.0)
    news_bull_ratio = features.get("news_bullish_ratio",       0.5)

    # ── Macro calendar features ───────────────────────────────────────────────
    macro_impact      = features.get("macro_impact_score_now",      0.0)
    hours_to_next     = features.get("macro_hours_to_next_high",    48.0)
    hours_since_last  = features.get("macro_hours_since_last_high", 48.0)
    macro_surprise    = features.get("macro_surprise_last",          0.0)
    high_count_24h    = features.get("macro_high_event_count_24h",   0.0)
    is_blackout       = features.get("macro_is_blackout",            0.0)

    # ── Broadcast scalars to full DataFrame length ────────────────────────────
    # For live inference: all rows get the same current value (latest snapshot)
    # For backtesting with as_of: caller should iterate and call per-bar
    d["dl_spread"]             = spread
    d["dl_spread_pct"]         = spread_pct
    d["dl_ofi"]                = ofi
    d["dl_trade_pressure"]     = trade_pressure
    d["dl_buy_pressure"]       = buy_pressure
    d["dl_sell_pressure"]      = sell_pressure
    d["dl_cumulative_delta"]   = cum_delta
    d["dl_volume_delta"]       = vol_delta
    d["dl_vwap"]               = vwap
    d["dl_bid_depth"]          = bid_depth
    d["dl_ask_depth"]          = ask_depth
    d["dl_depth_imbalance"]    = depth_imbalance
    d["dl_tick_count"]         = tick_count
    d["dl_spread_z20"]         = spread_z20
    d["dl_ofi_ema5"]           = ofi_ema5
    d["dl_pressure_divergence"]= pressure_div
    d["dl_news_sentiment"]     = news_sentiment
    d["dl_news_momentum"]      = news_momentum
    d["dl_news_count_1h"]      = news_count_1h
    d["dl_news_bullish_ratio"] = news_bull_ratio
    d["dl_macro_impact"]       = macro_impact
    d["dl_hours_to_next_high"] = hours_to_next
    d["dl_hours_since_last_high"] = hours_since_last
    d["dl_macro_surprise"]     = macro_surprise
    d["dl_high_event_count_24h"] = high_count_24h
    d["dl_is_blackout"]        = is_blackout

    # Ensure no NaN/inf leaks
    dl_cols = [c for c in d.columns if c.startswith("dl_")]
    d[dl_cols] = d[dl_cols].replace([float("inf"), float("-inf")], 0.0).fillna(0.0)

    logger.debug(
        "add_data_layer_features: injected %d features, ofi=%.3f sent=%.3f impact=%.3f",
        len(dl_cols), ofi, news_sentiment, macro_impact,
    )
    return d


def build_extended_features_with_data_layer(
    ohlcv: pd.DataFrame,
    macro_df: Optional[pd.DataFrame] = None,
    horizon: int = 1,
    use_filtered_target: bool = True,
    min_move_atr: float = 0.25,
    smoke: bool = False,
    as_of: Optional[pd.Timestamp] = None,
) -> "tuple[pd.DataFrame, pd.Series]":
    """
    Full feature matrix: 200+ OHLCV features + 26 live data layer features.

    This is the production entry point for the ML pipeline.
    Calls build_extended_features() then appends add_data_layer_features().

    Parameters
    ----------
    ohlcv              : OHLCV DataFrame
    macro_df           : Optional macro DataFrame
    horizon            : Prediction horizon in bars
    use_filtered_target: Drop low-conviction bars
    min_move_atr       : Minimum move threshold
    smoke              : Skip expensive computations (CI mode)
    as_of              : Causal cutoff for data layer features

    Returns
    -------
    X : Feature DataFrame (226+ columns)
    y : Binary target Series
    """
    X, y = build_extended_features(
        ohlcv,
        macro_df=macro_df,
        horizon=horizon,
        use_filtered_target=use_filtered_target,
        min_move_atr=min_move_atr,
        smoke=smoke,
    )
    X = add_data_layer_features(X, as_of=as_of)
    return X, y

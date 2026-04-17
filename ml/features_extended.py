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

import contextlib
import logging

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Layer 13: Order-flow & tape reading
# ─────────────────────────────────────────────────────────────────────────────


def add_orderflow_features(df: pd.DataFrame) -> pd.DataFrame:
    """Delta, cumulative delta, buy/sell pressure, VWAP deviation."""
    d = df.copy()
    c, o, h, l, v = (
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
    d["of_vw_mom_10"] = (d["of_delta"].rolling(10).sum() / v.rolling(10).sum().replace(0, np.nan)).fillna(0.0)
    d["of_vw_mom_20"] = (d["of_delta"].rolling(20).sum() / v.rolling(20).sum().replace(0, np.nan)).fillna(0.0)

    # Absorption: large volume with small price move = absorption
    price_move = (c - o).abs()
    d["of_absorption"] = (v / (price_move.replace(0, np.nan) * c.replace(0, np.nan))).fillna(0.0)
    d["of_absorption_z20"] = _zscore(d["of_absorption"], 20)

    # Volume surge
    vol_ma20 = v.rolling(20).mean().replace(0, np.nan)
    d["of_vol_surge"] = (v / vol_ma20).fillna(1.0).clip(0, 10)
    d["of_vol_surge_flag"] = (d["of_vol_surge"] > 2.0).astype(int)

    # Tape speed: number of consecutive same-direction closes
    direction = np.sign(c - c.shift(1)).fillna(0)
    d["of_tape_streak"] = direction.groupby((direction != direction.shift()).cumsum()).cumcount() + 1
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
    """Higuchi fractal dimension — vectorized via strided windows."""
    arr = series.values.astype(float)
    n = len(arr)
    out = np.full(n, 1.5)
    if n < window:
        return pd.Series(out, index=series.index)
    # Build strided matrix (n_windows, window)
    stride = arr.strides[0]
    n_win = n - window + 1
    mat = np.lib.stride_tricks.as_strided(arr, shape=(n_win, window), strides=(stride, stride)).copy()
    for wi in range(n_win):
        x = mat[wi]
        lk = []
        for k in range(1, k_max + 1):
            lm_sum = 0.0
            lm_cnt = 0
            for m in range(1, k + 1):
                idxs = np.arange(m - 1, window, k)
                if len(idxs) < 2:
                    continue
                xm = x[idxs]
                lm_sum += np.sum(np.abs(np.diff(xm))) * (window - 1) / (k * len(xm))
                lm_cnt += 1
            if lm_cnt:
                lk.append(lm_sum / lm_cnt)
        if len(lk) >= 2:
            log_k = np.log(np.arange(1, len(lk) + 1))
            log_lk = np.log(np.array(lk) + 1e-10)
            with contextlib.suppress(Exception):
                out[wi + window - 1] = float(np.polyfit(log_k, log_lk, 1)[0])
    return pd.Series(out, index=series.index)


def _rolling_dfa(series: pd.Series, window: int) -> pd.Series:
    """Detrended fluctuation analysis — fully vectorized across all windows.

    Detrends each segment using a precomputed linear projection matrix so
    no per-segment polyfit is needed.  All windows are processed in a single
    batch operation.
    """
    arr = series.values.astype(float)
    n = len(arr)
    out = np.full(n, 0.5)
    if n < window:
        return pd.Series(out, index=series.index)

    n_win = n - window + 1
    stride = arr.strides[0]
    # Shape: (n_win, window)
    mat = np.lib.stride_tricks.as_strided(arr, shape=(n_win, window), strides=(stride, stride)).copy()

    # Cumulative sum of mean-centred series: (n_win, window)
    mat_c = mat - mat.mean(axis=1, keepdims=True)
    y_mat = np.cumsum(mat_c, axis=1)

    scales = [4, 8, max(8, window // 4)]
    f_vals = []

    for s in scales:
        if s >= window:
            f_vals.append(None)
            continue
        segs = window // s
        if segs < 1:
            f_vals.append(None)
            continue
        t = np.arange(s, dtype=float)
        # Precompute linear detrending projection for segments of length s
        # Residual = y - t*(t·y)/(t·t) - mean(y - t*(t·y)/(t·t))
        # Simplified: project out the linear component
        t_norm = t - t.mean()
        t_sq = (t_norm**2).sum()

        # Collect all segments across all windows: shape (n_win * segs, s)
        seg_list = []
        for i in range(segs):
            seg_list.append(y_mat[:, i * s : (i + 1) * s])
        segs_mat = np.concatenate(seg_list, axis=0)  # (n_win*segs, s)

        # Vectorized linear detrend
        seg_c = segs_mat - segs_mat.mean(axis=1, keepdims=True)
        if t_sq > 0:
            slope = (seg_c * t_norm[np.newaxis, :]).sum(axis=1, keepdims=True) / t_sq
            residual = seg_c - slope * t_norm[np.newaxis, :]
        else:
            residual = seg_c
        rms_all = np.sqrt((residual**2).mean(axis=1))  # (n_win*segs,)

        # Average RMS per window
        rms_per_win = rms_all.reshape(segs, n_win).mean(axis=0)  # (n_win,)
        f_vals.append(rms_per_win)

    # Compute DFA exponent from log-log slope
    valid_scales = [(s, fv) for s, fv in zip(scales, f_vals, strict=False) if fv is not None]
    if len(valid_scales) < 2:
        return pd.Series(out, index=series.index)

    log_s = np.log(np.array([s for s, _ in valid_scales], dtype=float))
    f_mat = np.stack([fv for _, fv in valid_scales], axis=0)  # (n_valid, n_win)
    log_f = np.log(f_mat + 1e-10)

    # Vectorized polyfit: slope = (n * Σxy - Σx*Σy) / (n * Σx² - (Σx)²)
    ns = len(log_s)
    sx = log_s.sum()
    sx2 = (log_s**2).sum()
    sy = log_f.sum(axis=0)
    sxy = (log_s[:, np.newaxis] * log_f).sum(axis=0)
    denom = ns * sx2 - sx**2
    if abs(denom) > 1e-12:
        slopes = (ns * sxy - sx * sy) / denom
        out[window - 1 :] = np.clip(slopes, -2.0, 2.0)

    return pd.Series(out, index=series.index)


def _rolling_lyapunov(series: pd.Series, window: int) -> pd.Series:
    """Lyapunov proxy — vectorized: mean log of nearest-neighbour distances."""
    arr = series.values.astype(float)
    n = len(arr)
    out = np.full(n, 0.0)
    if n < window:
        return pd.Series(out, index=series.index)
    stride = arr.strides[0]
    n_win = n - window + 1
    mat = np.lib.stride_tricks.as_strided(arr, shape=(n_win, window), strides=(stride, stride)).copy()
    half = window // 2
    for wi in range(n_win):
        x = mat[wi]
        divs = []
        for i in range(half):
            diffs = np.abs(x[i + 1 :] - x[i])
            pos = diffs[diffs > 0]
            if len(pos):
                divs.append(np.log(pos.min() + 1e-10))
        out[wi + window - 1] = float(np.mean(divs)) if divs else 0.0
    return pd.Series(out, index=series.index)


def _rolling_apen(series: pd.Series, window: int, m: int, r_factor: float) -> pd.Series:
    """Approximate entropy — vectorized using matrix distance computation."""
    arr = series.values.astype(float)
    n = len(arr)
    out = np.full(n, 0.0)
    if n < window:
        return pd.Series(out, index=series.index)
    stride = arr.strides[0]
    n_win = n - window + 1
    mat = np.lib.stride_tricks.as_strided(arr, shape=(n_win, window), strides=(stride, stride)).copy()

    def _phi_vec(x: np.ndarray, m_: int, r: float) -> float:
        """Vectorized phi computation using broadcasting."""
        nm = len(x) - m_
        if nm < 1:
            return 0.0
        # Build template matrix: (nm, m_)
        tmpl = np.lib.stride_tricks.as_strided(x, shape=(nm, m_), strides=(x.strides[0], x.strides[0]))
        # Chebyshev distance: max over m_ dimensions
        diff = np.abs(tmpl[:, np.newaxis, :] - tmpl[np.newaxis, :, :])  # (nm, nm, m_)
        cheb = diff.max(axis=2)  # (nm, nm)
        count = (cheb <= r).sum()
        return float(np.log(count / max(nm * nm, 1) + 1e-10))

    for wi in range(n_win):
        x = mat[wi]
        r = r_factor * x.std()
        if r == 0 or len(x) < m + 2:
            continue
        with contextlib.suppress(Exception):
            out[wi + window - 1] = _phi_vec(x, m, r) - _phi_vec(x, m + 1, r)
    return pd.Series(out, index=series.index)


def _rolling_perm_entropy(series: pd.Series, window: int, order: int) -> pd.Series:
    """Permutation entropy — vectorized using argsort on strided windows."""
    import math

    arr = series.values.astype(float)
    n = len(arr)
    out = np.full(n, 0.0)
    if n < window:
        return pd.Series(out, index=series.index)
    max_ent = math.log(math.factorial(order) + 1e-10)
    stride = arr.strides[0]
    n_win = n - window + 1
    mat = np.lib.stride_tricks.as_strided(arr, shape=(n_win, window), strides=(stride, stride)).copy()
    for wi in range(n_win):
        x = mat[wi]
        nm = window - order + 1
        if nm < 1:
            continue
        # Build all order-length sub-windows and argsort each
        sub = np.lib.stride_tricks.as_strided(x, shape=(nm, order), strides=(x.strides[0], x.strides[0]))
        perms = np.argsort(sub, axis=1)  # (nm, order)
        # Hash each permutation to an integer
        keys = np.ravel_multi_index(perms.T, dims=[order] * order, mode="clip")
        counts = np.bincount(keys)
        counts = counts[counts > 0]
        p = counts / counts.sum()
        ent = -float(np.sum(p * np.log(p + 1e-10)))
        out[wi + window - 1] = ent / max_ent if max_ent > 0 else 0.0
    return pd.Series(out, index=series.index)


def _rolling_recurrence(series: pd.Series, window: int, eps_factor: float) -> pd.Series:
    """Recurrence rate — vectorized using pairwise distance matrix."""
    arr = series.values.astype(float)
    n = len(arr)
    out = np.full(n, 0.0)
    if n < window:
        return pd.Series(out, index=series.index)
    stride = arr.strides[0]
    n_win = n - window + 1
    mat = np.lib.stride_tricks.as_strided(arr, shape=(n_win, window), strides=(stride, stride)).copy()
    for wi in range(n_win):
        x = mat[wi]
        eps = eps_factor * x.std()
        if eps == 0:
            continue
        # Vectorized pairwise distance
        dist = np.abs(x[:, np.newaxis] - x[np.newaxis, :])
        count = (dist < eps).sum() - window  # subtract diagonal
        out[wi + window - 1] = float(count / max(window * (window - 1), 1))
    return pd.Series(out, index=series.index)


def _rolling_wavelet_ratio(series: pd.Series, window: int) -> pd.Series:
    """Haar wavelet energy ratio — fully vectorized via strided matrix."""
    arr = series.values.astype(float)
    n = len(arr)
    out = np.full(n, 1.0)
    if n < window:
        return pd.Series(out, index=series.index)
    stride = arr.strides[0]
    n_win = n - window + 1
    mat = np.lib.stride_tricks.as_strided(arr, shape=(n_win, window), strides=(stride, stride)).copy()
    # Haar: use even-length portion
    w2 = (window // 2) * 2
    x_even = mat[:, :w2:2]  # (n_win, w2//2)
    x_odd = mat[:, 1:w2:2]  # (n_win, w2//2)
    approx = (x_even + x_odd) * 0.5
    detail = (x_even - x_odd) * 0.5
    e_approx = (approx**2).sum(axis=1) + 1e-10
    e_detail = (detail**2).sum(axis=1) + 1e-10
    out[window - 1 :] = e_detail / e_approx
    return pd.Series(out, index=series.index)


def _rolling_corr_dim(series: pd.Series, window: int) -> pd.Series:
    """Correlation dimension proxy — vectorized pairwise distance."""
    arr = series.values.astype(float)
    n = len(arr)
    out = np.full(n, 1.0)
    if n < window:
        return pd.Series(out, index=series.index)
    stride = arr.strides[0]
    n_win = n - window + 1
    mat = np.lib.stride_tricks.as_strided(arr, shape=(n_win, window), strides=(stride, stride)).copy()
    for wi in range(n_win):
        x = mat[wi]
        diffs = np.abs(np.diff(x))
        if len(diffs) == 0:
            continue
        eps_vals = np.percentile(diffs, [25, 50, 75])
        # Vectorized pairwise distance
        dist = np.abs(x[:, np.newaxis] - x[np.newaxis, :])
        c_vals = []
        for eps in eps_vals:
            if eps == 0:
                continue
            c_vals.append((dist < eps).sum() / max(window * (window - 1), 1))
        if len(c_vals) >= 2:
            log_eps = np.log(eps_vals[: len(c_vals)] + 1e-10)
            log_c = np.log(np.array(c_vals) + 1e-10)
            with contextlib.suppress(Exception):
                out[wi + window - 1] = float(np.polyfit(log_eps, log_c, 1)[0])
    return pd.Series(out, index=series.index)


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
    ema12 = c.ewm(span=12, adjust=False, min_periods=1).mean()
    ema26 = c.ewm(span=26, adjust=False, min_periods=1).mean()
    macd = ema12 - ema26
    signal_line = macd.ewm(span=9, adjust=False, min_periods=1).mean()
    d["ri_macd"] = macd
    d["ri_macd_signal"] = signal_line
    d["ri_macd_hist"] = macd - signal_line
    d["ri_macd_hist_z20"] = _zscore(d["ri_macd_hist"], 20)
    d["ri_macd_cross_bull"] = ((macd > signal_line) & (macd.shift(1) <= signal_line.shift(1))).astype(int)
    d["ri_macd_cross_bear"] = ((macd < signal_line) & (macd.shift(1) >= signal_line.shift(1))).astype(int)

    # Bollinger Bands
    ma20 = c.rolling(20).mean()
    std20 = c.rolling(20).std().replace(0, np.nan)
    bb_upper = ma20 + 2 * std20
    bb_lower = ma20 - 2 * std20
    bb_width = (bb_upper - bb_lower) / ma20.replace(0, np.nan)
    d["ri_bb_pct"] = ((c - bb_lower) / (bb_upper - bb_lower).replace(0, np.nan)).fillna(0.5)
    d["ri_bb_width"] = bb_width.fillna(0.0)
    d["ri_bb_width_z20"] = _zscore(d["ri_bb_width"], 20)
    d["ri_bb_squeeze"] = (d["ri_bb_width"] < d["ri_bb_width"].rolling(20).quantile(0.2)).astype(int)
    d["ri_bb_expansion"] = (d["ri_bb_width"] > d["ri_bb_width"].rolling(20).quantile(0.8)).astype(int)

    # Ichimoku components (simplified)
    high9 = d["high"].rolling(9).max()
    low9 = d["low"].rolling(9).min()
    high26 = d["high"].rolling(26).max()
    low26 = d["low"].rolling(26).min()
    tenkan = (high9 + low9) / 2
    kijun = (high26 + low26) / 2
    d["ri_tenkan_kijun_diff"] = ((tenkan - kijun) / c.replace(0, np.nan)).fillna(0.0)
    d["ri_price_above_kijun"] = (c > kijun).astype(int)
    d["ri_tk_cross_bull"] = ((tenkan > kijun) & (tenkan.shift(1) <= kijun.shift(1))).astype(int)
    d["ri_tk_cross_bear"] = ((tenkan < kijun) & (tenkan.shift(1) >= kijun.shift(1))).astype(int)

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
    d["ri_mean_rev_score"] = (d["ri_rsi_oversold"].astype(float) + (d["ri_bb_pct"] < 0.1).astype(float)) / 2.0 - (
        d["ri_rsi_overbought"].astype(float) + (d["ri_bb_pct"] > 0.9).astype(float)
    ) / 2.0

    # Momentum quality: alignment of RSI, MACD, price momentum
    mom_sign = np.sign(d.get("mom_20", pd.Series(0.0, index=d.index)))
    rsi_sign = np.sign(d["ri_rsi_14"] - 50)
    macd_sign = np.sign(d["ri_macd_hist"])
    d["ri_signal_alignment"] = ((mom_sign == rsi_sign).astype(int) + (rsi_sign == macd_sign).astype(int)) / 2.0

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
    l = d["low"]
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
    d["inst_vwap20_slope"] = ((vwap_20 - vwap_20.shift(5)) / vwap_20.shift(5).replace(0, np.nan)).fillna(0.0)
    d["inst_vwap20_accel"] = (d["inst_vwap20_slope"] - d["inst_vwap20_slope"].shift(5)).fillna(0.0)

    # ── Buy/sell volume estimation ────────────────────────────────────────────
    bar_range = (h - l).replace(0, np.nan)
    buy_pct = ((c - l) / bar_range).fillna(0.5).clip(0, 1)
    sell_pct = 1.0 - buy_pct
    buy_vol = buy_pct * v.fillna(0)
    sell_vol = sell_pct * v.fillna(0)
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
    d["inst_absorption_ratio"] = ((v / vol_ma20) / (price_move / c.replace(0, np.nan))).fillna(0.0).clip(0, 100)
    d["inst_absorption_z"] = _zscore(d["inst_absorption_ratio"], 20)
    # High absorption = large vol, small move (institutional accumulation/distribution)
    d["inst_high_absorption"] = (d["inst_absorption_z"] > 1.5).astype(int)

    # ── Smart Money Index (SMI) ───────────────────────────────────────────────
    # SMI = close - open (first 30 min proxy) + close - open (last 30 min proxy)
    # On H1 bars: first bar of session = dumb money, last bar = smart money
    # Proxy: (close - open) of current bar vs (close - open) of 8 bars ago
    early_move = (o - o.shift(1)).fillna(0.0)  # gap open = retail reaction
    late_move = (c - o).fillna(0.0)  # intrabar close = smart money
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
    d["inst_pressure_imbalance"] = (d["inst_buy_pressure_20"] - 0.5) * 2.0  # [-1, 1]: positive = buy-side dominant

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

    Fully-vectorized implementation using a strided bucket matrix.
    Each bar's volume is assigned to a bucket based on its normalised position
    within the rolling [low, high] range.  The bucket matrix has shape
    (n_windows, n_buckets) and is built with a single numpy operation,
    eliminating all Python-level loops over bars.

    Complexity: O(n * n_buckets) — ~100× faster than the naive nested loop.

    Returns three pd.Series: (poc, vah, val) aligned to the input index.
    """
    n = len(close)
    idx = close.index

    h_arr = high.values.astype(float)
    l_arr = low.values.astype(float)
    c_arr = close.values.astype(float)
    v_arr = np.where(np.isnan(volume.values) | (volume.values <= 0), 0.0, volume.values.astype(float))

    # Rolling high/low for each window endpoint
    roll_high = high.rolling(window, min_periods=window).max().values
    roll_low = low.rolling(window, min_periods=window).min().values

    poc_vals = c_arr.copy()
    vah_vals = c_arr.copy()
    val_vals = c_arr.copy()

    # Bar midpoints for bucket assignment
    bar_mid = (h_arr + l_arr) * 0.5

    # Build strided view: shape (n_windows, window) for bar_mid and v_arr
    # n_windows = n - window + 1
    n_windows = n - window + 1
    stride = bar_mid.strides[0]
    mid_strided = np.lib.stride_tricks.as_strided(bar_mid, shape=(n_windows, window), strides=(stride, stride))
    vol_strided = np.lib.stride_tricks.as_strided(v_arr, shape=(n_windows, window), strides=(stride, stride))

    # Rolling range for each window (shape: n_windows)
    rh = roll_high[window - 1 :]
    rl = roll_low[window - 1 :]
    price_range = rh - rl

    # Mask degenerate windows
    valid_windows = price_range > 0

    # Normalised position of each bar within its window's price range
    # Shape: (n_windows, window)
    _rh_col = rh[:, np.newaxis]
    rl_col = rl[:, np.newaxis]
    pr_col = np.where(price_range[:, np.newaxis] > 0, price_range[:, np.newaxis], 1.0)

    norm_pos = (mid_strided - rl_col) / pr_col  # 0..1
    bucket_idx = np.clip((norm_pos * n_buckets).astype(int), 0, n_buckets - 1)

    # Build bucket volume matrix: shape (n_windows, n_buckets)
    # Use one-hot encoding then dot with volume
    # one_hot shape: (n_windows, window, n_buckets)
    one_hot = bucket_idx[:, :, np.newaxis] == np.arange(n_buckets)[np.newaxis, np.newaxis, :]
    bucket_vol_mat = (one_hot * vol_strided[:, :, np.newaxis]).sum(axis=1)  # (n_windows, n_buckets)

    # POC: argmax per window
    poc_idx_arr = np.argmax(bucket_vol_mat, axis=1)  # (n_windows,)

    # Bucket midpoints per window: shape (n_windows, n_buckets)
    bucket_step = price_range / n_buckets
    bucket_mid_mat = rl_col + (np.arange(n_buckets)[np.newaxis, :] + 0.5) * bucket_step[:, np.newaxis]

    poc_prices = bucket_mid_mat[np.arange(n_windows), poc_idx_arr]

    # Value Area: cumulative sum from POC outward — vectorised per window
    # Sort buckets by volume descending, accumulate until 70% reached
    total_vol = bucket_vol_mat.sum(axis=1)  # (n_windows,)
    target_vol = total_vol * 0.70

    # For each window find the contiguous range [lo_ptr, hi_ptr] around POC
    # that captures 70% of volume.  Use a compact Python loop over windows
    # (only n_windows iterations, no inner bar loop).
    vah_prices = poc_prices.copy()
    val_prices = poc_prices.copy()

    for w in range(n_windows):
        if not valid_windows[w]:
            continue
        bv = bucket_vol_mat[w]
        bm = bucket_mid_mat[w]
        poc_i = poc_idx_arr[w]
        tv = target_vol[w]
        va = bv[poc_i]
        lo = poc_i
        hi = poc_i
        while va < tv:
            can_up = hi + 1 < n_buckets
            can_dn = lo - 1 >= 0
            if not can_up and not can_dn:
                break
            up = bv[hi + 1] if can_up else -1.0
            dn = bv[lo - 1] if can_dn else -1.0
            if up >= dn:
                hi += 1
                va += bv[hi]
            else:
                lo -= 1
                va += bv[lo]
        vah_prices[w] = bm[hi]
        val_prices[w] = bm[lo]

    # Write results back (offset by window-1)
    poc_vals[window - 1 :] = poc_prices
    vah_vals[window - 1 :] = vah_prices
    val_vals[window - 1 :] = val_prices

    # Mark pre-window bars as NaN so ffill works correctly
    poc_vals[: window - 1] = np.nan
    vah_vals[: window - 1] = np.nan
    val_vals[: window - 1] = np.nan

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
    macro_df: pd.DataFrame | None = None,
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
    as_of: pd.Timestamp | None = None,
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
    _n = len(d)

    # ── Pull features from orchestrator ──────────────────────────────────────
    features: dict[str, float] = {}
    try:
        from data_layer.orchestrator import orchestrator

        features = orchestrator.get_ml_features(as_of=as_of)
    except Exception as exc:
        logger.debug("add_data_layer_features: orchestrator unavailable: %s", exc)

    # ── Microstructure features (keys match orchestrator.get_ml_features()) ──
    spread = features.get("micro_spread", 0.0)
    spread_pct = features.get("micro_spread_pct", 0.0)
    ofi = features.get("micro_ofi", 0.0)
    trade_pressure = features.get("micro_trade_pressure", 0.0)
    buy_pressure = features.get("micro_buy_pressure", 0.5)
    sell_pressure = features.get("micro_sell_pressure", 0.5)
    cum_delta = features.get("micro_cumulative_delta", 0.0)
    vol_delta = features.get("micro_volume_delta", 0.0)
    vwap = features.get("micro_vwap_dev", 0.0)
    # ── L2 order book features (populated from OrderBookFeed when available) ──
    bid_depth = features.get("micro_bid_depth", 0.0)
    ask_depth = features.get("micro_ask_depth", 0.0)
    depth_imbalance = features.get("micro_depth_imbalance", 0.0)
    # Supplement with live L2 feed if orchestrator didn't provide depth data
    if bid_depth == 0.0 and ask_depth == 0.0:
        try:
            from market_data.order_book import get_order_book_feed

            _l2_feed = get_order_book_feed()
            # Derive symbol from DataFrame index or use default
            _symbol = getattr(df, "_hopefx_symbol", "XAU_USD")
            _l2_features = _l2_feed.get_ml_features(_symbol)
            bid_depth = _l2_features.get("micro_bid_depth", 0.0)
            ask_depth = _l2_features.get("micro_ask_depth", 0.0)
            depth_imbalance = _l2_features.get("micro_depth_imbalance", depth_imbalance)
            # Also update OFI and pressure from L2 if available
            if _l2_features.get("micro_obi", 0.0) != 0.0:
                ofi = _l2_features["micro_obi"]
        except Exception as _l2_exc:
            logger.debug("L2 order book features unavailable: %s", _l2_exc)
    # tick_count from microstructure snapshot (normalised to [0, 1] range)
    tick_count = min(features.get("micro_tick_count", 0.0) / 500.0, 1.0)

    # Derived microstructure
    spread_z20 = features.get("micro_spread_z", 0.0)
    ofi_ema5 = features.get("micro_ofi", ofi)  # EMA already in engine
    pressure_div = buy_pressure - sell_pressure

    # ── Sentiment features ────────────────────────────────────────────────────
    news_sentiment = features.get("news_sentiment_score", 0.0)
    news_momentum = features.get("news_sentiment_momentum", 0.0)
    news_count_1h = features.get("news_article_count_1h", 0.0)
    news_bull_ratio = features.get("news_bullish_ratio", 0.5)

    # ── Macro calendar features ───────────────────────────────────────────────
    macro_impact = features.get("macro_impact_score_now", 0.0)
    hours_to_next = features.get("macro_hours_to_next_high", 48.0)
    hours_since_last = features.get("macro_hours_since_last_high", 48.0)
    macro_surprise = features.get("macro_surprise_last", 0.0)
    high_count_24h = features.get("macro_high_event_count_24h", 0.0)
    is_blackout = features.get("macro_is_blackout", 0.0)

    # ── Tick quality / confidence ─────────────────────────────────────────────
    tick_confidence = features.get("tick_confidence", 1.0)
    tick_spread_pct = features.get("tick_spread_pct", 0.0)
    tick_src_count = features.get("tick_source_count", 1.0)

    # ── FRED macro features (injected by MacroStoreBridge) ────────────────────
    macro_dxy = features.get("macro_dxy", 0.0)
    macro_us10y = features.get("macro_us10y", 0.0)
    macro_us2y = features.get("macro_us2y", 0.0)
    macro_vix = features.get("macro_vix", 0.0)
    macro_cpi = features.get("macro_cpi", 0.0)
    macro_pce = features.get("macro_pce", 0.0)
    macro_yield_curve = macro_us10y - macro_us2y  # 10y-2y spread

    # ── Broadcast scalars to full DataFrame length ────────────────────────────
    # For live inference: all rows get the same current value (latest snapshot)
    # For backtesting with as_of: caller should iterate and call per-bar
    d["dl_spread"] = spread
    d["dl_spread_pct"] = spread_pct
    d["dl_ofi"] = ofi
    d["dl_trade_pressure"] = trade_pressure
    d["dl_buy_pressure"] = buy_pressure
    d["dl_sell_pressure"] = sell_pressure
    d["dl_cumulative_delta"] = cum_delta
    d["dl_volume_delta"] = vol_delta
    d["dl_vwap"] = vwap
    d["dl_bid_depth"] = bid_depth
    d["dl_ask_depth"] = ask_depth
    d["dl_depth_imbalance"] = depth_imbalance
    d["dl_tick_count"] = tick_count
    d["dl_spread_z20"] = spread_z20
    d["dl_ofi_ema5"] = ofi_ema5
    d["dl_pressure_divergence"] = pressure_div
    d["dl_news_sentiment"] = news_sentiment
    d["dl_news_momentum"] = news_momentum
    d["dl_news_count_1h"] = news_count_1h
    d["dl_news_bullish_ratio"] = news_bull_ratio
    d["dl_macro_impact"] = macro_impact
    d["dl_hours_to_next_high"] = hours_to_next
    d["dl_hours_since_last_high"] = hours_since_last
    d["dl_macro_surprise"] = macro_surprise
    d["dl_high_event_count_24h"] = high_count_24h
    d["dl_is_blackout"] = is_blackout
    # Tick quality
    d["dl_tick_confidence"] = tick_confidence
    d["dl_tick_spread_pct"] = tick_spread_pct
    d["dl_tick_source_count"] = tick_src_count
    # FRED macro
    d["dl_macro_dxy"] = macro_dxy
    d["dl_macro_us10y"] = macro_us10y
    d["dl_macro_us2y"] = macro_us2y
    d["dl_macro_vix"] = macro_vix
    d["dl_macro_cpi"] = macro_cpi
    d["dl_macro_pce"] = macro_pce
    d["dl_macro_yield_curve"] = macro_yield_curve

    # Ensure no NaN/inf leaks
    dl_cols = [c for c in d.columns if c.startswith("dl_")]
    d[dl_cols] = d[dl_cols].replace([float("inf"), float("-inf")], 0.0).fillna(0.0)

    logger.debug(
        "add_data_layer_features: injected %d features, ofi=%.3f sent=%.3f impact=%.3f tick_conf=%.2f",
        len(dl_cols),
        ofi,
        news_sentiment,
        macro_impact,
        tick_confidence,
    )
    return d


def build_extended_features_with_data_layer(
    ohlcv: pd.DataFrame,
    macro_df: pd.DataFrame | None = None,
    horizon: int = 1,
    use_filtered_target: bool = True,
    min_move_atr: float = 0.25,
    smoke: bool = False,
    as_of: pd.Timestamp | None = None,
) -> tuple[pd.DataFrame, pd.Series]:
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


# ── Alias expected by brain/hopefx_brain.py ───────────────────────────────────


def build_features_extended(
    ohlcv: pd.DataFrame,
    macro_df: pd.DataFrame | None = None,
    horizon: int = 1,
    use_filtered_target: bool = True,
    smoke: bool = False,
) -> pd.DataFrame:
    """Return only the feature matrix (X) from :func:`build_extended_features`.

    This alias is used by :mod:`brain.hopefx_brain` when it needs a feature
    DataFrame without the target series.

    Args:
        ohlcv:               OHLCV DataFrame (open, high, low, close, volume).
        macro_df:            Optional macro indicators DataFrame.
        horizon:             Prediction horizon in bars.
        use_filtered_target: When ``True``, use ATR-filtered target labels.
        smoke:               When ``True``, skip expensive computations.

    Returns:
        Feature DataFrame (X) from the extended feature pipeline.
    """
    X, _ = build_extended_features(
        ohlcv=ohlcv,
        macro_df=macro_df,
        horizon=horizon,
        use_filtered_target=use_filtered_target,
        smoke=smoke,
    )
    return X

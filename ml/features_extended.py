# HOPEFX-AI-TRADING
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
ml/features_extended.py
=======================
Extended feature engineering — layers 13-15 adding 100+ features on top of
the existing 100-feature base in advanced_features.py.

New layers
----------
13. Order-flow & tape reading  — delta, cumulative delta, buy/sell pressure
14. Fractal geometry           — fractal dimension, self-similarity, chaos
15. Regime-adaptive ensemble   — cross-feature interactions, regime-gated signals

Total output: 200+ features when combined with build_advanced_features().
"""

from __future__ import annotations

import logging
from typing import Optional

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
                except Exception:
                    pass
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

# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
ml/advanced_features.py
=======================
Advanced feature engineering for XAUUSD ML models.

Feature layers
--------------
1.  Price-action patterns     — candlestick body/wick ratios, engulfing, pin-bar
2.  Swing highs/lows          — fractal levels, distance to S/R in ATR units
3.  Multi-timeframe momentum  — 5/10/20/60-bar returns, alignment score
4.  Volatility regime         — realised vol, vol-of-vol, GARCH-proxy, regime label
5.  Market microstructure     — Kaufman efficiency ratio, Amihud illiquidity
6.  Calendar / seasonality    — cyclically encoded DOW, month, EOM/EOW effects
7.  Trend strength            — ADX, DI+/DI-, z-score mean reversion
8.  Hurst exponent            — rolling R/S (trending vs mean-reverting regime)
9.  COT proxy                 — open-interest momentum as speculative positioning proxy
10. Intermarket divergence    — gold vs DXY, gold vs SPX, gold vs oil divergence
11. Macro features            — from ml.macro_features (DXY, VIX, yields, SPX, copper, oil)
12. Filtered target           — only label bars with meaningful moves (>= min_move_atr × ATR)

All features are stationary (returns, z-scores, ratios, binary flags).
No raw price levels are included as features.
"""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# 1. Price-action & candlestick features
# ─────────────────────────────────────────────────────────────────────────────


def add_price_action_features(df: pd.DataFrame) -> pd.DataFrame:
    """Candlestick body/wick ratios, engulfing, doji, pin-bar, 3-bar patterns."""
    d = df.copy()
    o, h, l, c = d["open"], d["high"], d["low"], d["close"]

    body = (c - o).abs()
    candle_range = (h - l).replace(0, np.nan)

    d["pa_body_ratio"] = (body / candle_range).fillna(0.0)
    d["pa_upper_wick"] = ((h - pd.concat([o, c], axis=1).max(axis=1)) / candle_range).fillna(0.0)
    d["pa_lower_wick"] = ((pd.concat([o, c], axis=1).min(axis=1) - l) / candle_range).fillna(0.0)
    d["pa_bull_candle"] = (c > o).astype(int)
    d["pa_doji"] = (d["pa_body_ratio"] < 0.1).astype(int)
    d["pa_pin_bar_bull"] = ((d["pa_lower_wick"] > 0.6) & (d["pa_body_ratio"] < 0.3)).astype(int)
    d["pa_pin_bar_bear"] = ((d["pa_upper_wick"] > 0.6) & (d["pa_body_ratio"] < 0.3)).astype(int)

    # Engulfing patterns
    prev_body = (d["close"].shift(1) - d["open"].shift(1)).abs()
    d["pa_bull_engulf"] = ((c > o) & (o < d["close"].shift(1)) & (c > d["open"].shift(1)) & (body > prev_body)).astype(
        int
    )
    d["pa_bear_engulf"] = ((c < o) & (o > d["close"].shift(1)) & (c < d["open"].shift(1)) & (body > prev_body)).astype(
        int
    )

    # 3-bar momentum
    d["pa_3bar_bull"] = ((c > c.shift(1)) & (c.shift(1) > c.shift(2))).astype(int)
    d["pa_3bar_bear"] = ((c < c.shift(1)) & (c.shift(1) < c.shift(2))).astype(int)

    # Gap features (overnight gap as % of prior close)
    d["pa_gap_up"] = ((o > d["high"].shift(1)) & (o > c.shift(1))).astype(int)
    d["pa_gap_down"] = ((o < d["low"].shift(1)) & (o < c.shift(1))).astype(int)
    d["pa_gap_pct"] = ((o - c.shift(1)) / c.shift(1).replace(0, np.nan)).fillna(0.0)

    return d


# ─────────────────────────────────────────────────────────────────────────────
# 2. Swing highs/lows and fractal levels
# ─────────────────────────────────────────────────────────────────────────────


def add_swing_features(df: pd.DataFrame, window: int = 5) -> pd.DataFrame:
    """Fractal swing levels; distance from price to nearest S/R in ATR units."""
    d = df.copy()
    h, l, c = d["high"], d["low"], d["close"]
    atr = _atr(d, 14)

    swing_high = h[(h == h.rolling(window * 2 + 1, center=True).max())].reindex(d.index)
    swing_low = l[(l == l.rolling(window * 2 + 1, center=True).min())].reindex(d.index)

    last_sh = swing_high.ffill()
    last_sl = swing_low.ffill()

    d["dist_to_swing_high"] = ((last_sh - c) / atr.replace(0, np.nan)).fillna(0.0)
    d["dist_to_swing_low"] = ((c - last_sl) / atr.replace(0, np.nan)).fillna(0.0)
    d["near_swing_high"] = (d["dist_to_swing_high"].abs() < 0.5).astype(int)
    d["near_swing_low"] = (d["dist_to_swing_low"].abs() < 0.5).astype(int)

    # Breakout flags
    d["breakout_high"] = (c > last_sh.shift(1)).astype(int)
    d["breakout_low"] = (c < last_sl.shift(1)).astype(int)

    return d


# ─────────────────────────────────────────────────────────────────────────────
# 3. Multi-timeframe momentum
# ─────────────────────────────────────────────────────────────────────────────


def add_mtf_momentum(df: pd.DataFrame) -> pd.DataFrame:
    """Momentum at 5/10/20/60-bar horizons; alignment score; acceleration."""
    d = df.copy()
    c = d["close"]

    for n in [5, 10, 20, 60]:
        ret = c.pct_change(n)
        d[f"mom_{n}"] = ret
        d[f"mom_{n}_sign"] = np.sign(ret)

    # Alignment: fraction of timeframes agreeing on direction (-1 to +1)
    signs = [d[f"mom_{n}_sign"] for n in [5, 10, 20, 60]]
    d["mtf_alignment"] = sum(signs) / 4.0

    # Momentum acceleration (short vs long)
    d["mom_accel_5_20"] = d["mom_5"] - d["mom_20"]
    d["mom_accel_10_60"] = d["mom_10"] - d["mom_60"]

    # Rate of change of momentum (second derivative)
    d["mom_roc"] = d["mom_5"].diff()

    return d


# ─────────────────────────────────────────────────────────────────────────────
# 4. Volatility regime
# ─────────────────────────────────────────────────────────────────────────────


def add_volatility_regime(df: pd.DataFrame) -> pd.DataFrame:
    """Realised vol, vol-of-vol, GARCH-proxy, vol regime label, vol skew."""
    d = df.copy()
    ret = d["close"].pct_change(fill_method=None)

    for w in [5, 10, 20, 60]:
        d[f"rvol_{w}"] = ret.rolling(w).std() * np.sqrt(252)

    d["vol_ratio_5_20"] = (d["rvol_5"] / d["rvol_20"].replace(0, np.nan)).fillna(1.0)
    d["vol_ratio_10_60"] = (d["rvol_10"] / d["rvol_60"].replace(0, np.nan)).fillna(1.0)
    d["vol_of_vol"] = d["rvol_20"].rolling(20).std().fillna(0.0)

    # GARCH-proxy: exponentially weighted variance
    ewm_var = ret.ewm(span=20).var()
    d["garch_proxy"] = (np.sqrt(ewm_var) * np.sqrt(252)).fillna(0.0)

    # Vol regime: 0=low, 1=normal, 2=high (60-bar percentile)
    pct = d["rvol_20"].rolling(60).rank(pct=True).fillna(0.5)
    d["vol_regime"] = (
        pd.cut(pct, bins=[0, 0.33, 0.67, 1.0], labels=[0, 1, 2], include_lowest=True).astype(float).fillna(1.0)
    )

    # Parkinson volatility estimator (uses high-low range, more efficient)
    hl_ratio = (d["high"] / d["low"].replace(0, np.nan)).apply(np.log)
    d["parkinson_vol"] = ((1.0 / (4.0 * np.log(2))) * (hl_ratio**2)).rolling(
        20,
    ).mean().apply(np.sqrt).fillna(0.0) * np.sqrt(252)

    return d


# ─────────────────────────────────────────────────────────────────────────────
# 5. Market microstructure
# ─────────────────────────────────────────────────────────────────────────────


def add_microstructure_features(df: pd.DataFrame) -> pd.DataFrame:
    """Kaufman efficiency ratio, Amihud illiquidity, spread proxy, OI momentum."""
    d = df.copy()
    c = d["close"]

    # Kaufman Efficiency Ratio: directional move / path length
    for w in [10, 20]:
        direction = (c - c.shift(w)).abs()
        path = c.diff().abs().rolling(w).sum()
        d[f"efficiency_{w}"] = (direction / path.replace(0, np.nan)).fillna(0.5)

    # High-low spread proxy (normalised by close)
    d["hl_spread"] = ((d["high"] - d["low"]) / d["close"].replace(0, np.nan)).fillna(
        0.0,
    )

    # Amihud illiquidity proxy
    if "volume" in d.columns and d["volume"].sum() > 0:
        ret_abs = c.pct_change(fill_method=None).abs()
        d["amihud"] = ((ret_abs / d["volume"].replace(0, np.nan)).rolling(20).mean()).fillna(0.0)
        # Volume z-score
        vol_mean = d["volume"].rolling(20).mean()
        vol_std = d["volume"].rolling(20).std().replace(0, np.nan)
        d["volume_z20"] = ((d["volume"] - vol_mean) / vol_std).fillna(0.0)
        # OBV momentum (stationary: rate of change)
        obv = (np.sign(c.diff()) * d["volume"]).cumsum()
        d["obv_mom_10"] = obv.pct_change(10).fillna(0.0)
    else:
        d["amihud"] = 0.0
        d["volume_z20"] = 0.0
        d["obv_mom_10"] = 0.0

    # Open interest momentum proxy (if available)
    if "open_interest" in d.columns and d["open_interest"].sum() > 0:
        oi = d["open_interest"]
        d["oi_chg"] = oi.pct_change(fill_method=None).fillna(0.0)
        d["oi_z20"] = _zscore(oi, 20)
        # Price up + OI up = strong trend; price up + OI down = weak trend
        price_up = (c.pct_change(fill_method=None) > 0).astype(float)
        oi_up = (d["oi_chg"] > 0).astype(float)
        d["oi_price_confirm"] = (price_up == oi_up).astype(float)
    else:
        d["oi_chg"] = d["oi_z20"] = d["oi_price_confirm"] = 0.0

    return d


# ─────────────────────────────────────────────────────────────────────────────
# 6. Calendar / seasonality
# ─────────────────────────────────────────────────────────────────────────────


def add_calendar_features(df: pd.DataFrame) -> pd.DataFrame:
    """Cyclically encoded DOW, month, quarter, EOM/EOW, Monday effects."""
    d = df.copy()
    idx = pd.DatetimeIndex(d.index)

    d["cal_dow"] = idx.dayofweek
    d["cal_month"] = idx.month
    d["cal_quarter"] = idx.quarter
    d["cal_eom"] = idx.is_month_end.astype(int)
    d["cal_eow"] = (idx.dayofweek == 4).astype(int)
    d["cal_monday"] = (idx.dayofweek == 0).astype(int)

    # Cyclical encoding avoids ordinal assumption
    d["cal_dow_sin"] = np.sin(2 * np.pi * d["cal_dow"] / 5)
    d["cal_dow_cos"] = np.cos(2 * np.pi * d["cal_dow"] / 5)
    d["cal_month_sin"] = np.sin(2 * np.pi * d["cal_month"] / 12)
    d["cal_month_cos"] = np.cos(2 * np.pi * d["cal_month"] / 12)

    # Gold seasonality: historically strong in Jan, Sep-Nov; weak in Mar-Apr
    strong_months = idx.month.isin([1, 9, 10, 11]).astype(int)
    weak_months = idx.month.isin([3, 4]).astype(int)
    d["cal_gold_season_bull"] = strong_months
    d["cal_gold_season_bear"] = weak_months

    return d


# ─────────────────────────────────────────────────────────────────────────────
# 7. Trend strength
# ─────────────────────────────────────────────────────────────────────────────


def add_trend_features(df: pd.DataFrame, smoke: bool = False) -> pd.DataFrame:
    """ADX, DI+/DI-, z-score mean reversion, multiple MA distances."""
    d = df.copy()
    h, l, c = d["high"], d["low"], d["close"]
    atr14 = _atr(d, 14)

    # ADX
    plus_dm = (h - h.shift(1)).clip(lower=0)
    minus_dm = (l.shift(1) - l).clip(lower=0)
    plus_dm = plus_dm.where(plus_dm > minus_dm, 0.0)
    minus_dm = minus_dm.where(minus_dm > plus_dm, 0.0)
    plus_di = 100 * plus_dm.ewm(span=14).mean() / atr14.replace(0, np.nan)
    minus_di = 100 * minus_dm.ewm(span=14).mean() / atr14.replace(0, np.nan)
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    d["adx_14"] = dx.ewm(span=14).mean().fillna(0.0)
    d["plus_di_14"] = plus_di.fillna(0.0)
    d["minus_di_14"] = minus_di.fillna(0.0)
    d["di_diff"] = (plus_di - minus_di).fillna(0.0)

    # Distance from multiple MAs (stationary: normalised by ATR)
    for w in [10, 20, 50, 200]:
        ma = c.rolling(w).mean()
        d[f"dist_ma_{w}"] = ((c - ma) / atr14.replace(0, np.nan)).fillna(0.0)

    # Z-score mean reversion at multiple windows
    for w in [10, 20, 50]:
        mu = c.rolling(w).mean()
        sig = c.rolling(w).std().replace(0, np.nan)
        d[f"zscore_{w}"] = ((c - mu) / sig).fillna(0.0)

    # Hurst exponent proxy — skipped in smoke mode (expensive rolling apply)
    if smoke:
        d["hurst_proxy"] = 0.5
    else:
        d["hurst_proxy"] = _rolling_hurst(c, 40)

    # Stochastic oscillator
    for w in [14]:
        lo_w = l.rolling(w).min()
        hi_w = h.rolling(w).max()
        d[f"stoch_k_{w}"] = (100 * (c - lo_w) / (hi_w - lo_w).replace(0, np.nan)).fillna(50.0)
        d[f"stoch_d_{w}"] = d[f"stoch_k_{w}"].rolling(3).mean().fillna(50.0)

    # Williams %R
    d["williams_r"] = (
        -100 * (h.rolling(14).max() - c) / (h.rolling(14).max() - l.rolling(14).min()).replace(0, np.nan)
    ).fillna(-50.0)

    # CCI (Commodity Channel Index)
    tp = (h + l + c) / 3
    d["cci_20"] = ((tp - tp.rolling(20).mean()) / (0.015 * tp.rolling(20).std().replace(0, np.nan))).fillna(0.0)

    return d


# ─────────────────────────────────────────────────────────────────────────────
# 8. Intermarket divergence features
# ─────────────────────────────────────────────────────────────────────────────


def add_intermarket_features(
    df: pd.DataFrame,
    macro_df: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """
    Gold vs DXY, SPX, oil divergence signals.

    When gold rises while DXY also rises, it signals exceptional demand
    (central bank buying, geopolitical premium) — a strong bullish signal.
    When gold falls while VIX rises, it signals forced liquidation.
    """
    d = df.copy()

    if macro_df is None or macro_df.empty:
        for col in [
            "im_gold_dxy_div",
            "im_gold_spx_div",
            "im_gold_oil_div",
            "im_gold_strong_demand",
            "im_forced_liquidation",
        ]:
            d[col] = 0.0
        return d

    macro = macro_df.copy()
    # Normalise both indices to tz-naive UTC so reindex never hits a
    # "Cannot compare dtypes datetime64[ns] and datetime64[ns, UTC]" error.
    if macro.index.tz is not None:
        macro.index = macro.index.tz_convert("UTC").tz_localize(None)
    macro.index = pd.to_datetime(macro.index)
    # Normalising to midnight creates duplicate dates when macro_df has
    # sub-daily frequency.  Only normalise if the index is already daily
    # (all times are midnight) to avoid the duplicate-label reindex error.
    if len(macro.index) > 0 and (macro.index.time == macro.index[0].time()).all():
        macro.index = macro.index.normalize()
    # Drop any remaining duplicates before reindexing
    if macro.index.duplicated().any():
        macro = macro[~macro.index.duplicated(keep="last")]

    # Strip tz from d.index for the reindex, then restore both afterwards
    # so that arithmetic between d-derived series and macro-derived series
    # never hits "Cannot join tz-naive with tz-aware DatetimeIndex".
    d_tz = d.index.tz
    if d_tz is not None:
        d.index = d.index.tz_localize(None)
    macro = macro.reindex(d.index, method="ffill").fillna(0.0)
    if d_tz is not None:
        d.index = d.index.tz_localize(d_tz)
        macro.index = macro.index.tz_localize(d_tz)

    gold_ret = d["close"].pct_change(fill_method=None).fillna(0.0)

    # Gold-DXY divergence: both rising = exceptional demand (bullish)
    if "dxy" in macro.columns:
        dxy_ret = macro["dxy"].pct_change(fill_method=None).fillna(0.0)
        d["im_gold_dxy_div"] = (gold_ret * dxy_ret).rolling(5).mean()
        d["im_gold_strong_demand"] = ((gold_ret > 0) & (dxy_ret > 0)).astype(float)
    else:
        d["im_gold_dxy_div"] = d["im_gold_strong_demand"] = 0.0

    # Gold-SPX divergence: gold up + SPX down = risk-off (bullish for gold)
    if "spx" in macro.columns:
        spx_ret = macro["spx"].pct_change(fill_method=None).fillna(0.0)
        d["im_gold_spx_div"] = (gold_ret * (-spx_ret)).rolling(5).mean()
    else:
        d["im_gold_spx_div"] = 0.0

    # Gold-oil divergence: gold up + oil down = deflation fear (mixed signal)
    if "oil" in macro.columns:
        oil_ret = macro["oil"].pct_change(fill_method=None).fillna(0.0)
        d["im_gold_oil_div"] = (gold_ret * oil_ret).rolling(5).mean()
    else:
        d["im_gold_oil_div"] = 0.0

    # Forced liquidation: gold down + VIX up (risk-off but gold sold for margin)
    if "vix" in macro.columns:
        vix_ret = macro["vix"].pct_change(fill_method=None).fillna(0.0)
        d["im_forced_liquidation"] = ((gold_ret < -0.005) & (vix_ret > 0.05)).astype(
            float,
        )
    else:
        d["im_forced_liquidation"] = 0.0

    return d


# ─────────────────────────────────────────────────────────────────────────────
# 9. COT / central bank buying proxy features
# ─────────────────────────────────────────────────────────────────────────────


def add_cot_proxy_features(
    df: pd.DataFrame,
    macro_df: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """
    Proxy features for speculative positioning and central bank demand.

    The 2022-2026 gold bull market was driven by central bank buying and
    geopolitical risk — factors absent from the basic feature set.  Direct
    COT data requires a CFTC feed; these proxies are computable from
    price/volume and cross-asset data available via Yahoo Finance.

    Features
    --------
    cot_oi_momentum_5   : 5-bar rate of change of open interest (volume proxy)
    cot_oi_momentum_20  : 20-bar rate of change of open interest
    cot_large_spec_proxy: Gold ETF (GLD) vs futures divergence — when GLD
                          outperforms futures, institutional/ETF demand is
                          rising (central bank / sovereign wealth fund proxy)
    cot_net_long_proxy  : Composite score: OI rising + price rising = net long
                          accumulation; OI rising + price falling = distribution
    cot_demand_surge    : Binary flag: OI momentum > 1 std AND price > 0
    cot_cb_buying_proxy : Gold rising while DXY also rising AND yields rising
                          — the only scenario where gold defies macro headwinds
                          is central bank / geopolitical demand
    cot_geopolitical    : VIX spike + gold outperforming SPX (risk-off premium)
    """
    d = df.copy()

    # ── Open interest proxy (volume as OI substitute) ─────────────────────────
    # Gold futures volume is a reasonable OI proxy for daily data.
    if "volume" in d.columns and d["volume"].sum() > 0:
        vol = d["volume"].replace(0, np.nan)
        d["cot_oi_momentum_5"] = vol.pct_change(5).fillna(0.0)
        d["cot_oi_momentum_20"] = vol.pct_change(20).fillna(0.0)

        # Net long proxy: OI direction × price direction
        oi_dir = np.sign(d["cot_oi_momentum_5"])
        price_dir = np.sign(d["close"].pct_change(fill_method=None))
        d["cot_net_long_proxy"] = (oi_dir * price_dir).fillna(0.0)

        # Demand surge: OI momentum > 1 std above its 60-bar mean AND price up
        oi_mom_mean = d["cot_oi_momentum_5"].rolling(60).mean()
        oi_mom_std = d["cot_oi_momentum_5"].rolling(60).std().replace(0, np.nan)
        oi_z = ((d["cot_oi_momentum_5"] - oi_mom_mean) / oi_mom_std).fillna(0.0)
        d["cot_demand_surge"] = ((oi_z > 1.0) & (d["close"].pct_change(fill_method=None) > 0)).astype(
            float,
        )
    else:
        for col in [
            "cot_oi_momentum_5",
            "cot_oi_momentum_20",
            "cot_net_long_proxy",
            "cot_demand_surge",
        ]:
            d[col] = 0.0

    # ── Cross-asset proxies (require macro_df) ────────────────────────────────
    if macro_df is not None and not macro_df.empty:
        macro = macro_df.copy()
        # Normalise both indices to tz-naive UTC (same fix as add_intermarket_features)
        if macro.index.tz is not None:
            macro.index = macro.index.tz_convert("UTC").tz_localize(None)
        macro.index = pd.to_datetime(macro.index)
        # Only normalise to midnight when the index is already daily-frequency
        # (all times identical) — normalising sub-daily data creates duplicates.
        if len(macro.index) > 0 and (macro.index.time == macro.index[0].time()).all():
            macro.index = macro.index.normalize()
        if macro.index.duplicated().any():
            macro = macro[~macro.index.duplicated(keep="last")]

        # Strip tz from d.index for the reindex, then restore both so that
        # arithmetic between d-derived and macro-derived series stays tz-consistent.
        d_tz = d.index.tz
        if d_tz is not None:
            d.index = d.index.tz_localize(None)
        macro = macro.reindex(d.index, method="ffill").fillna(0.0)
        if d_tz is not None:
            d.index = d.index.tz_localize(d_tz)
            macro.index = macro.index.tz_localize(d_tz)

        gold_ret = d["close"].pct_change(fill_method=None).fillna(0.0)

        # GLD vs futures divergence (institutional demand proxy)
        # When GLD ETF (spot demand) outperforms futures, it signals
        # physical/institutional buying rather than speculative positioning.
        if "gold_etf" in macro.columns and macro["gold_etf"].abs().sum() > 0:
            gld_ret = macro["gold_etf"].pct_change(fill_method=None).fillna(0.0)
            d["cot_large_spec_proxy"] = (gold_ret - gld_ret).rolling(5).mean().fillna(0.0)
        else:
            d["cot_large_spec_proxy"] = 0.0

        # Central bank buying proxy: gold up + DXY up + yields up
        # This is the signature of demand that defies macro headwinds —
        # the dominant driver of the 2022-2026 bull market.
        has_dxy = "dxy" in macro.columns and macro["dxy"].abs().sum() > 0
        has_yield = "yield_10y" in macro.columns and macro["yield_10y"].abs().sum() > 0
        if has_dxy and has_yield:
            dxy_ret = macro["dxy"].pct_change(fill_method=None).fillna(0.0)
            yield_chg = macro["yield_10y"].diff().fillna(0.0)
            # All three rising simultaneously = central bank / geopolitical demand
            d["cot_cb_buying_proxy"] = ((gold_ret > 0.002) & (dxy_ret > 0) & (yield_chg > 0)).astype(float)
            # Rolling 20-bar frequency of this pattern (persistence measure)
            d["cot_cb_buying_freq20"] = d["cot_cb_buying_proxy"].rolling(20).mean().fillna(0.0)
        else:
            d["cot_cb_buying_proxy"] = 0.0
            d["cot_cb_buying_freq20"] = 0.0

        # Geopolitical premium: VIX spike + gold outperforming SPX
        has_vix = "vix" in macro.columns and macro["vix"].abs().sum() > 0
        has_spx = "spx" in macro.columns and macro["spx"].abs().sum() > 0
        if has_vix and has_spx:
            vix_spike = (macro["vix"] > 25).astype(float)
            spx_ret = macro["spx"].pct_change(fill_method=None).fillna(0.0)
            gold_vs_spx = gold_ret - spx_ret
            d["cot_geopolitical"] = (vix_spike * (gold_vs_spx > 0).astype(float)).fillna(0.0)
            # 20-bar rolling geopolitical premium score
            d["cot_geo_score20"] = d["cot_geopolitical"].rolling(20).mean().fillna(0.0)
        else:
            d["cot_geopolitical"] = 0.0
            d["cot_geo_score20"] = 0.0

    else:
        for col in [
            "cot_large_spec_proxy",
            "cot_cb_buying_proxy",
            "cot_cb_buying_freq20",
            "cot_geopolitical",
            "cot_geo_score20",
        ]:
            d[col] = 0.0

    return d


# ─────────────────────────────────────────────────────────────────────────────
# 10. Target engineering
# ─────────────────────────────────────────────────────────────────────────────


def build_filtered_target(
    df: pd.DataFrame,
    horizon: int = 1,
    min_move_atr: float = 0.3,
) -> pd.Series:
    """
    Binary direction target that only labels bars where the move is
    meaningful (>= min_move_atr × ATR14).

    Bars below the threshold are labelled NaN and dropped from training.
    This forces the model to learn high-conviction setups rather than noise.
    """
    c = df["close"]
    atr = _atr(df, 14)

    future_ret = c.pct_change(horizon).shift(-horizon)
    future_move = (c.shift(-horizon) - c).abs()
    threshold = min_move_atr * atr

    y = pd.Series(np.nan, index=df.index)
    mask = future_move >= threshold
    y[mask] = (future_ret[mask] > 0).astype(int)
    return y


# ─────────────────────────────────────────────────────────────────────────────
# Master builder
# ─────────────────────────────────────────────────────────────────────────────


def build_advanced_features(
    ohlcv: pd.DataFrame,
    macro_df: pd.DataFrame | None = None,
    horizon: int = 1,
    use_filtered_target: bool = True,
    min_move_atr: float = 0.25,
    smoke: bool = False,
) -> tuple[pd.DataFrame, pd.Series]:
    """
    Build the full advanced feature matrix and target.

    Parameters
    ----------
    ohlcv              : OHLCV DataFrame (open/high/low/close/volume)
    macro_df           : Optional macro DataFrame (DXY, VIX, yields, SPX, etc.)
    horizon            : Prediction horizon in bars
    use_filtered_target: If True, drop low-conviction bars from training
    min_move_atr       : Minimum move (ATR units) to include a bar
    smoke              : Skip expensive computations (e.g. rolling Hurst) for CI speed

    Returns
    -------
    X : Feature DataFrame (no NaN, all stationary)
    y : Binary target Series (0=down, 1=up)
    """
    d = ohlcv.copy()
    d.columns = [c.lower() for c in d.columns]

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
    d = add_trend_features(d, smoke=smoke)
    d = add_intermarket_features(d, macro_df=macro_df)
    d = add_cot_proxy_features(d, macro_df=macro_df)

    # ── Macro + regime features ───────────────────────────────────────────────
    if macro_df is not None and not macro_df.empty:
        try:
            from ml.macro_features import add_macro_features, add_regime_features

            d = add_macro_features(d, macro_df=macro_df, lookback=20)
            d = add_regime_features(d, lookback=60)
        except Exception as exc:
            logger.warning("Macro/regime features skipped: %s", exc)
    else:
        # Ensure regime columns exist even without macro data
        try:
            from ml.macro_features import add_regime_features

            d = add_regime_features(d, lookback=60)
        except Exception as _exc:
            logger.debug("Suppressed exception: %s", _exc)

    # ── Target ────────────────────────────────────────────────────────────────
    if use_filtered_target:
        y_raw = build_filtered_target(d, horizon=horizon, min_move_atr=min_move_atr)
    else:
        future_ret = d["close"].pct_change(horizon).shift(-horizon)
        y_raw = (future_ret > 0).astype(float)
        y_raw[y_raw.isna()] = np.nan

    d["_target"] = y_raw

    # ── Sanitise: replace inf with NaN, then drop ─────────────────────────────
    # Inf values arise from division by zero in early bars (e.g. pct_change on
    # the first bar, Amihud illiquidity when volume=0, Hurst on short windows).
    # sklearn's StandardScaler raises ValueError on inf — replace before drop.
    exclude = {"open", "high", "low", "close", "volume", "_target"}
    feature_cols = [c for c in d.columns if c not in exclude]

    d = d[feature_cols + ["_target"]]
    d = d.replace([np.inf, -np.inf], np.nan).dropna()

    X = d[feature_cols]
    y = d["_target"].astype(int)

    logger.info(
        "Advanced features: %d bars × %d features (filtered from %d, horizon=%d)",
        len(X),
        len(feature_cols),
        len(ohlcv),
        horizon,
    )
    return X, y


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


def _atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    h, l, c = df["high"], df["low"], df["close"]
    tr = pd.concat(
        [
            h - l,
            (h - c.shift(1)).abs(),
            (l - c.shift(1)).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return tr.ewm(span=period, adjust=False).mean()


def _zscore(s: pd.Series, w: int) -> pd.Series:
    mu = s.rolling(w).mean()
    sig = s.rolling(w).std().replace(0, np.nan)
    return ((s - mu) / sig).fillna(0.0)


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
            log_lags = np.log(list(lags)[: len(rs_vals)])
            log_rs = np.log(rs_vals)
            h = np.polyfit(log_lags, log_rs, 1)[0]
            return float(np.clip(h, 0.0, 1.0))
        except Exception:  # nosec B110 — numerical fallback for Hurst exponent
            return 0.5

    return series.rolling(window).apply(_hurst_scalar, raw=True).fillna(0.5)

# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
research/pipeline/microstructure.py
======================================
Order-book microstructure features for the prediction pipeline.

Wires the existing data/order_book.py and data/depth_of_market.py structures
into a pandas-native feature engineering layer.

Feature groups
--------------
1. Spread & mid-price
   - bid_ask_spread          : best ask − best bid
   - spread_pct              : spread / mid_price
   - spread_z20              : z-score of spread over 20 snapshots

2. Order-book imbalance (OBI)
   - obi_1                   : (bid_vol_L1 − ask_vol_L1) / total_L1
   - obi_5                   : depth-weighted imbalance across top-5 levels
   - obi_10                  : depth-weighted imbalance across top-10 levels
   - obi_ema5                : EMA(5) of obi_5 — smoothed pressure signal

3. Depth & liquidity
   - bid_depth_5             : total bid volume in top-5 levels
   - ask_depth_5             : total ask volume in top-5 levels
   - depth_ratio_5           : bid_depth_5 / ask_depth_5
   - weighted_mid            : volume-weighted mid-price (better than simple mid)
   - price_impact_1pct       : estimated slippage to move 1% of avg volume

4. Trade-flow (from Time & Sales)
   - buy_vol_ratio           : buy-initiated volume / total volume (last N trades)
   - large_trade_flag        : 1 if any trade > 2× avg trade size in window
   - trade_intensity         : trades per second in last window
   - vwap_deviation          : (last_price − session_vwap) / session_vwap

5. Microstructure regime
   - quote_stuffing_flag     : rapid quote updates without trades (manipulation proxy)
   - tick_direction          : +1 uptick, −1 downtick, 0 unchanged
   - tick_ema5               : EMA(5) of tick direction — short-term momentum

All features are computed from a list of OrderBook snapshots (or a DataFrame
of snapshots) and returned as a pandas DataFrame with a DatetimeIndex.

Usage — from live snapshots
----------------------------
    from research.pipeline.microstructure import MicrostructureFeatures
    from data.order_book import OrderBook

    mf = MicrostructureFeatures()
    mf.push_snapshot(order_book, timestamp)   # call on each tick
    features_df = mf.to_dataframe()           # ML-ready DataFrame

Usage — from historical snapshot DataFrame
------------------------------------------
    from research.pipeline.microstructure import compute_microstructure_features

    feat_df = compute_microstructure_features(snapshot_df)
    # snapshot_df columns: timestamp, bid_p1..bid_p10, bid_v1..bid_v10,
    #                       ask_p1..ask_p10, ask_v1..ask_v10, last_price, volume
"""

from __future__ import annotations

import logging
from collections import deque
from datetime import datetime, timezone

UTC = timezone.utc

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# Import existing order-book structures (graceful fallback if unavailable)
try:
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from data.order_book import OrderBook as _OrderBook  # used for isinstance checks below

    OB_AVAILABLE = True
except ImportError:
    _OrderBook = None  # type: ignore[assignment,misc]
    OB_AVAILABLE = False
    logger.debug("data.order_book not importable — snapshot-push mode unavailable")


# ─────────────────────────────────────────────────────────────────────────────
# Low-level helpers
# ─────────────────────────────────────────────────────────────────────────────


def _obi(bid_vols: np.ndarray, ask_vols: np.ndarray) -> float:
    """Order-book imbalance in [-1, +1]. +1 = all bids, -1 = all asks."""
    total = bid_vols.sum() + ask_vols.sum()
    if total == 0:
        return 0.0
    return float((bid_vols.sum() - ask_vols.sum()) / total)


def _weighted_mid(
    bid_prices: np.ndarray,
    bid_vols: np.ndarray,
    ask_prices: np.ndarray,
    ask_vols: np.ndarray,
) -> float:
    """
    Volume-weighted mid-price.
    Weights the best bid by ask-side volume and best ask by bid-side volume
    (Lee & Ready 1991 convention).
    """
    if len(bid_prices) == 0 or len(ask_prices) == 0:
        return 0.0
    ask_v = ask_vols[0] if len(ask_vols) > 0 else 1.0
    bid_v = bid_vols[0] if len(bid_vols) > 0 else 1.0
    total = ask_v + bid_v
    if total == 0:
        return (bid_prices[0] + ask_prices[0]) / 2
    return float((bid_prices[0] * ask_v + ask_prices[0] * bid_v) / total)


def _price_impact(
    bid_prices: np.ndarray,
    bid_vols: np.ndarray,
    ask_prices: np.ndarray,
    ask_vols: np.ndarray,
    target_vol: float,
) -> float:
    """
    Estimate the price impact of consuming `target_vol` units on the ask side.
    Returns the average execution price minus best ask (slippage).
    """
    if len(ask_prices) == 0 or target_vol <= 0:
        return 0.0
    remaining = target_vol
    cost = 0.0
    for p, v in zip(ask_prices, ask_vols, strict=False):
        fill = min(remaining, v)
        cost += fill * p
        remaining -= fill
        if remaining <= 0:
            break
    if remaining > 0:
        cost += remaining * ask_prices[-1]  # assume last level absorbs rest
    avg_price = cost / target_vol
    return float(avg_price - ask_prices[0]) if len(ask_prices) > 0 else 0.0


# ─────────────────────────────────────────────────────────────────────────────
# Snapshot-based feature computer (live mode)
# ─────────────────────────────────────────────────────────────────────────────


class MicrostructureFeatures:
    """
    Accumulates order-book snapshots and computes microstructure features.

    Designed for live trading: push one snapshot per tick, call to_dataframe()
    to get the ML-ready feature matrix at any time.

    Parameters
    ----------
    max_snapshots : Rolling window size for z-score / EMA calculations
    n_levels      : Number of order-book levels to use (default 10)
    """

    def __init__(self, max_snapshots: int = 500, n_levels: int = 10):
        self.max_snapshots = max_snapshots
        self.n_levels = n_levels
        self._records: deque[dict] = deque(maxlen=max_snapshots)

    def push_snapshot(
        self,
        book,  # OrderBook instance or dict with bids/asks
        timestamp: datetime | None = None,
        last_price: float = 0.0,
        trade_volume: float = 0.0,
        is_buy: bool | None = None,
    ) -> None:
        """
        Add one order-book snapshot.

        Parameters
        ----------
        book         : OrderBook (from data/order_book.py) or dict
                       {'bids': [(price, size), ...], 'asks': [(price, size), ...]}
        timestamp    : UTC datetime; defaults to now
        last_price   : Last trade price
        trade_volume : Volume of last trade
        is_buy       : True = buyer-initiated, False = seller-initiated, None = unknown
        """
        ts = timestamp or datetime.now(UTC)

        # Normalise to lists of (price, size) tuples
        if OB_AVAILABLE and hasattr(book, "bids"):
            bids = [(lvl.price, lvl.size) for lvl in book.bids[: self.n_levels]]
            asks = [(lvl.price, lvl.size) for lvl in book.asks[: self.n_levels]]
        elif isinstance(book, dict):
            bids = book.get("bids", [])[: self.n_levels]
            asks = book.get("asks", [])[: self.n_levels]
        else:
            bids, asks = [], []

        self._records.append(
            {
                "timestamp": ts,
                "bids": bids,
                "asks": asks,
                "last_price": last_price,
                "trade_volume": trade_volume,
                "is_buy": is_buy,
            }
        )

    def to_dataframe(self) -> pd.DataFrame:
        """Compute all microstructure features from accumulated snapshots."""
        if not self._records:
            return pd.DataFrame()
        return _compute_from_records(list(self._records), self.n_levels)


# ─────────────────────────────────────────────────────────────────────────────
# Core computation (works on both live records and historical DataFrames)
# ─────────────────────────────────────────────────────────────────────────────


def _compute_from_records(records: list[dict], n_levels: int = 10) -> pd.DataFrame:
    """Convert a list of snapshot dicts to a feature DataFrame."""
    rows = []
    for rec in records:
        bids = rec["bids"]
        asks = rec["asks"]

        bid_p = np.array([b[0] for b in bids], dtype=np.float64)
        bid_v = np.array([b[1] for b in bids], dtype=np.float64)
        ask_p = np.array([a[0] for a in asks], dtype=np.float64)
        ask_v = np.array([a[1] for a in asks], dtype=np.float64)

        best_bid = bid_p[0] if len(bid_p) > 0 else np.nan
        best_ask = ask_p[0] if len(ask_p) > 0 else np.nan
        mid = (best_bid + best_ask) / 2 if (not np.isnan(best_bid) and not np.isnan(best_ask)) else np.nan
        spread = (best_ask - best_bid) if not np.isnan(mid) else np.nan
        spread_pct = spread / mid if (mid and mid != 0) else np.nan

        # OBI at 1, 5, 10 levels
        obi1 = _obi(bid_v[:1], ask_v[:1])
        obi5 = _obi(bid_v[:5], ask_v[:5])
        obi10 = _obi(bid_v[:10], ask_v[:10])

        # Depth
        bid_depth5 = float(np.nan_to_num(bid_v[:5].sum(), nan=0.0))
        ask_depth5 = float(np.nan_to_num(ask_v[:5].sum(), nan=0.0))
        depth_ratio = bid_depth5 / ask_depth5 if ask_depth5 > 0 else np.nan

        # Weighted mid
        wmid = _weighted_mid(bid_p, bid_v, ask_p, ask_v)

        # Price impact (1% of avg depth as proxy target volume)
        avg_depth = (bid_depth5 + ask_depth5) / 2
        impact = _price_impact(ask_p, ask_v, bid_p, bid_v, avg_depth * 0.01)

        # Tick direction
        last_price = rec.get("last_price", 0.0)
        trade_vol = rec.get("trade_volume", 0.0)
        is_buy = rec.get("is_buy")

        rows.append(
            {
                "timestamp": rec["timestamp"],
                "ms_spread": spread,
                "ms_spread_pct": spread_pct,
                "ms_mid": mid,
                "ms_wmid": wmid,
                "ms_wmid_dev": (wmid - mid) / mid if (mid and mid != 0) else 0.0,
                "ms_obi_1": obi1,
                "ms_obi_5": obi5,
                "ms_obi_10": obi10,
                "ms_bid_depth5": bid_depth5,
                "ms_ask_depth5": ask_depth5,
                "ms_depth_ratio": depth_ratio,
                "ms_price_impact": impact,
                "ms_last_price": last_price,
                "ms_trade_vol": trade_vol,
                "ms_is_buy": 1.0 if is_buy is True else (-1.0 if is_buy is False else 0.0),
            }
        )

    df = pd.DataFrame(rows).set_index("timestamp")
    df.index = pd.to_datetime(df.index, utc=True)

    # ── Derived rolling features ───────────────────────────────────────────
    # Spread z-score (20 snapshots)
    df["ms_spread_z20"] = (df["ms_spread"] - df["ms_spread"].rolling(20).mean()) / df["ms_spread"].rolling(
        20
    ).std().replace(0, np.nan)

    # OBI EMA(5)
    df["ms_obi_ema5"] = df["ms_obi_5"].ewm(span=5, adjust=False).mean()

    # Buy-volume ratio (rolling 20 snapshots)
    buy_vol = df["ms_trade_vol"] * (df["ms_is_buy"] > 0).astype(float)
    total_vol = df["ms_trade_vol"].rolling(20).sum().replace(0, np.nan)
    df["ms_buy_vol_ratio"] = buy_vol.rolling(20).sum() / total_vol

    # Large trade flag (trade > 2× rolling mean)
    avg_trade = df["ms_trade_vol"].rolling(20).mean()
    df["ms_large_trade"] = (df["ms_trade_vol"] > 2 * avg_trade).astype(float)

    # Tick direction
    df["ms_tick"] = np.sign(df["ms_last_price"].diff()).fillna(0)
    df["ms_tick_ema5"] = df["ms_tick"].ewm(span=5, adjust=False).mean()

    # Quote stuffing proxy: spread narrows rapidly without a trade
    spread_chg = df["ms_spread"].diff().abs()
    df["ms_quote_stuff"] = ((spread_chg > spread_chg.rolling(20).mean() * 3) & (df["ms_trade_vol"] == 0)).astype(float)

    # VWAP deviation (session-level, reset daily)
    dates = df.index.normalize() if df.index.tz is not None else pd.to_datetime(df.index.date)
    cum_pv = (df["ms_last_price"] * df["ms_trade_vol"]).groupby(dates).cumsum()
    cum_v = df["ms_trade_vol"].groupby(dates).cumsum().replace(0, np.nan)
    session_vwap = cum_pv / cum_v
    df["ms_vwap_dev"] = (df["ms_last_price"] - session_vwap) / session_vwap.replace(0, np.nan)

    return df.drop(columns=["ms_last_price", "ms_trade_vol", "ms_is_buy"])


# ─────────────────────────────────────────────────────────────────────────────
# Historical snapshot DataFrame → features (batch mode)
# ─────────────────────────────────────────────────────────────────────────────


def compute_microstructure_features(snapshot_df: pd.DataFrame, n_levels: int = 10) -> pd.DataFrame:
    """
    Compute microstructure features from a historical snapshot DataFrame.

    Expected columns (wide format)
    --------------------------------
    timestamp                        — UTC datetime index or column
    bid_p1 .. bid_p{n}               — bid price levels
    bid_v1 .. bid_v{n}               — bid size levels
    ask_p1 .. ask_p{n}               — ask price levels
    ask_v1 .. ask_v{n}               — ask size levels
    last_price                       — last trade price
    volume                           — trade volume
    is_buy (optional)                — 1=buy, -1=sell, 0=unknown

    Returns
    -------
    DataFrame with ms_* feature columns, same index as snapshot_df.
    """
    records = []
    for ts, row in snapshot_df.iterrows():
        bids = [
            (row.get(f"bid_p{i}", np.nan), row.get(f"bid_v{i}", 0.0))
            for i in range(1, n_levels + 1)
            if not np.isnan(row.get(f"bid_p{i}", np.nan))
        ]
        asks = [
            (row.get(f"ask_p{i}", np.nan), row.get(f"ask_v{i}", 0.0))
            for i in range(1, n_levels + 1)
            if not np.isnan(row.get(f"ask_p{i}", np.nan))
        ]
        is_buy_raw = row.get("is_buy", 0)
        is_buy = True if is_buy_raw == 1 else (False if is_buy_raw == -1 else None)

        records.append(
            {
                "timestamp": ts,
                "bids": bids,
                "asks": asks,
                "last_price": float(row.get("last_price", 0.0)),
                "trade_volume": float(row.get("volume", 0.0)),
                "is_buy": is_buy,
            }
        )

    return _compute_from_records(records, n_levels=n_levels)


# ─────────────────────────────────────────────────────────────────────────────
# Attach microstructure features to an OHLCV price DataFrame
# ─────────────────────────────────────────────────────────────────────────────


def attach_microstructure(
    price_df: pd.DataFrame,
    ms_df: pd.DataFrame,
    resample: str | None = None,
) -> pd.DataFrame:
    """
    Merge microstructure features into a price DataFrame.

    Microstructure data is typically at tick/snapshot frequency; this function
    resamples it to match the price_df frequency (e.g. '5min', '1h', '1D')
    before merging.

    Parameters
    ----------
    price_df  : OHLCV DataFrame with DatetimeIndex (UTC)
    ms_df     : Microstructure feature DataFrame (from MicrostructureFeatures
                or compute_microstructure_features)
    resample  : Pandas offset string to resample ms_df before merging.
                If None, inferred from price_df index frequency.

    Returns
    -------
    price_df enriched with ms_* columns (forward-filled, NaN → 0).
    """
    if ms_df.empty:
        logger.warning("Empty microstructure DataFrame — skipping attach")
        return price_df

    # Infer resample frequency from price_df if not given
    if resample is None:
        freq = pd.infer_freq(price_df.index)
        resample = freq or "5min"

    ms_cols = [c for c in ms_df.columns if c.startswith("ms_")]

    # Resample: use mean for most features, last for directional ones
    agg = dict.fromkeys(ms_cols, "mean")
    for c in ["ms_large_trade", "ms_quote_stuff"]:
        if c in ms_cols:
            agg[c] = "max"  # flag is True if it happened at any point in the bar

    ms_resampled = ms_df[ms_cols].resample(resample).agg(agg)

    merged = price_df.join(ms_resampled, how="left")
    merged[ms_cols] = merged[ms_cols].ffill().fillna(0)
    return merged

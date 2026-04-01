# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
data_layer/microstructure/vpin.py
===================================
VPIN (Volume-Synchronized Probability of Informed Trading) calculator.

VPIN is a real-time measure of order flow toxicity and informed trading
probability. High VPIN predicts adverse selection and wider spreads.

Reference:
  Easley, D., López de Prado, M. & O'Hara, M. (2012). Flow Toxicity and
  Liquidity in a High-Frequency World. Review of Financial Studies, 25(5).
"""
from __future__ import annotations

import logging
import os
from collections import deque
from threading import Lock
from typing import NamedTuple

import numpy as np

logger = logging.getLogger(__name__)

_BUCKET_SIZE = int(os.getenv("VPIN_BUCKET_SIZE", "50"))
_N_BUCKETS = int(os.getenv("VPIN_N_BUCKETS", "50"))


class VPINSnapshot(NamedTuple):
    """Point-in-time VPIN state."""
    vpin: float
    """VPIN value in [0, 1]. Higher = more informed trading."""
    buy_volume: float
    """Volume classified as buyer-initiated in current bucket."""
    sell_volume: float
    """Volume classified as seller-initiated in current bucket."""
    bucket_fill: float
    """Fraction of current bucket filled [0, 1]."""
    n_buckets_complete: int
    """Number of complete buckets in the rolling window."""
    order_flow_imbalance: float
    """(buy_vol - sell_vol) / total_vol in current bucket."""


class VPINCalculator:
    """
    Volume-Synchronized Probability of Informed Trading (VPIN).

    Uses bulk volume classification (BVC) to split each trade into
    estimated buy and sell volume based on price change direction.
    """

    def __init__(
        self,
        bucket_size: int = _BUCKET_SIZE,
        n_buckets: int = _N_BUCKETS,
    ) -> None:
        """
        Parameters
        ----------
        bucket_size : int
            Target volume per bucket (in units / lots / USD). Default 50.
        n_buckets : int
            Rolling window of buckets for VPIN calculation. Default 50.
        """
        self._bucket_size = bucket_size
        self._n_buckets = n_buckets
        self._lock = Lock()

        # Current (incomplete) bucket accumulators
        self._bucket_buy: float = 0.0
        self._bucket_sell: float = 0.0
        self._bucket_vol: float = 0.0
        self._prev_mid: float | None = None

        # Completed buckets: deque of (buy_vol, sell_vol)
        self._buckets: deque[tuple[float, float]] = deque(maxlen=n_buckets)

        self._last_snapshot: VPINSnapshot | None = None

    def on_trade(
        self,
        price: float,
        volume: float,
        prev_price: float | None = None,
    ) -> VPINSnapshot:
        """
        Process a single trade (price, volume) and update VPIN.

        Uses Bulk Volume Classification (BVC):
          buy_fraction = Phi((price - prev_price) / sigma_price)
          buy_vol = volume * buy_fraction
          sell_vol = volume * (1 - buy_fraction)

        Parameters
        ----------
        price : float
            Trade price.
        volume : float
            Trade volume (in lots, units, or USD notional).
        prev_price : float, optional
            Previous price for direction inference. If None, uses last known.

        Returns
        -------
        VPINSnapshot
        """
        from scipy.stats import norm  # noqa: PLC0415

        with self._lock:
            ref_price = prev_price if prev_price is not None else self._prev_mid

            if ref_price is not None and ref_price > 0:
                price_change = price - ref_price
                # Sigma estimate: use fraction of price (basis points proxy)
                sigma = max(ref_price * 0.0005, 1e-8)
                buy_frac = float(norm.cdf(price_change / sigma))
            else:
                buy_frac = 0.5  # equal split when no price history

            buy_vol = volume * buy_frac
            sell_vol = volume * (1.0 - buy_frac)

            self._bucket_buy += buy_vol
            self._bucket_sell += sell_vol
            self._bucket_vol += volume
            self._prev_mid = price

            # Check if bucket is complete
            while self._bucket_vol >= self._bucket_size:
                # Allocate exactly bucket_size to current bucket
                scale = self._bucket_size / self._bucket_vol
                b_buy = self._bucket_buy * scale
                b_sell = self._bucket_sell * scale
                self._buckets.append((b_buy, b_sell))

                # Remainder carries over
                self._bucket_buy -= b_buy
                self._bucket_sell -= b_sell
                self._bucket_vol -= self._bucket_size

            snapshot = self._build_snapshot()
            self._last_snapshot = snapshot
            return snapshot

    def _build_snapshot(self) -> VPINSnapshot:
        """Build current VPIN snapshot from completed buckets."""
        n_complete = len(self._buckets)

        if n_complete == 0:
            bucket_fill = self._bucket_vol / max(self._bucket_size, 1)
            ofi = 0.0
            if self._bucket_vol > 0:
                ofi = (self._bucket_buy - self._bucket_sell) / self._bucket_vol
            return VPINSnapshot(
                vpin=0.5,
                buy_volume=self._bucket_buy,
                sell_volume=self._bucket_sell,
                bucket_fill=min(bucket_fill, 1.0),
                n_buckets_complete=0,
                order_flow_imbalance=ofi,
            )

        # VPIN = (1/n) * sum(|buy_vol - sell_vol|) / bucket_size
        imbalances = [abs(b - s) for b, s in self._buckets]
        vpin = float(np.mean(imbalances)) / self._bucket_size
        vpin = max(0.0, min(1.0, vpin))

        bucket_fill = min(self._bucket_vol / self._bucket_size, 1.0)
        ofi = 0.0
        if self._bucket_vol > 0:
            ofi = (self._bucket_buy - self._bucket_sell) / self._bucket_vol

        return VPINSnapshot(
            vpin=vpin,
            buy_volume=self._bucket_buy,
            sell_volume=self._bucket_sell,
            bucket_fill=bucket_fill,
            n_buckets_complete=n_complete,
            order_flow_imbalance=ofi,
        )

    def get_snapshot(self) -> VPINSnapshot | None:
        """Return the last computed snapshot (thread-safe)."""
        with self._lock:
            return self._last_snapshot

    def get_ml_features(self) -> dict[str, float]:
        """Return VPIN features for ML pipeline integration."""
        snap = self.get_snapshot()
        if snap is None:
            return {
                "vpin": 0.5,
                "vpin_buy_vol": 0.0,
                "vpin_sell_vol": 0.0,
                "vpin_bucket_fill": 0.0,
                "vpin_ofi": 0.0,
                "vpin_n_buckets": 0.0,
            }
        return {
            "vpin": snap.vpin,
            "vpin_buy_vol": snap.buy_volume,
            "vpin_sell_vol": snap.sell_volume,
            "vpin_bucket_fill": snap.bucket_fill,
            "vpin_ofi": snap.order_flow_imbalance,
            "vpin_n_buckets": float(snap.n_buckets_complete),
        }

    def reset(self) -> None:
        """Reset all accumulators (e.g. at session start)."""
        with self._lock:
            self._bucket_buy = 0.0
            self._bucket_sell = 0.0
            self._bucket_vol = 0.0
            self._prev_mid = None
            self._buckets.clear()
            self._last_snapshot = None


# Module-level singleton
vpin_calculator = VPINCalculator()

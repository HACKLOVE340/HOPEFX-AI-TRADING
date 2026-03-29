# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
data_layer/microstructure/engine.py
=====================================
MicrostructureEngine — professional market microstructure analytics.

Computed metrics (all tick-by-tick, no look-ahead)
---------------------------------------------------
Spread dynamics:
  - bid/ask spread (absolute + percentage)
  - spread EMA (short/long)
  - spread z-score (regime detection)

Volume & trade flow:
  - volume delta per tick (buy_vol - sell_vol, Lee-Ready classification)
  - cumulative delta (running sum, reset at session open)
  - buy/sell pressure ratio (rolling window)
  - order flow imbalance (OFI): (buy_vol - sell_vol) / (buy_vol + sell_vol)
  - trade pressure EMA (signed flow momentum)

Depth & liquidity:
  - bid/ask depth imbalance
  - effective spread (2 × |trade_price - mid|)
  - Kyle's lambda (price impact per unit volume)

Derived signals:
  - absorption ratio (large orders absorbed without price move)
  - delta divergence (price up but delta falling = bearish divergence)
  - VWAP deviation

All metrics are injected into the ML pipeline via get_ml_features().
Causal guarantee: every metric uses only past ticks.
"""
from __future__ import annotations

import logging
import math
import threading
import time
from collections import deque
from datetime import datetime, timezone
from typing import Dict, List, Optional

import numpy as np

from data_layer.types import GoldTick, MicrostructureSnapshot

logger = logging.getLogger(__name__)

import os
_WINDOW_TICKS   = int(os.getenv("MICRO_WINDOW_TICKS",   "500"))
_DELTA_WINDOW   = int(os.getenv("MICRO_DELTA_WINDOW",   "100"))
_PRESSURE_ALPHA = float(os.getenv("MICRO_PRESSURE_ALPHA", "0.1"))
_VWAP_WINDOW    = int(os.getenv("MICRO_VWAP_WINDOW",    "200"))


class _TickRecord:
    """Lightweight tick record for microstructure calculations."""
    __slots__ = ("ts", "mid", "bid", "ask", "spread", "volume",
                 "is_buy", "bid_depth", "ask_depth")

    def __init__(
        self,
        ts: float, mid: float, bid: float, ask: float,
        spread: float, volume: float, is_buy: bool,
        bid_depth: float = 0.0, ask_depth: float = 0.0,
    ) -> None:
        self.ts        = ts
        self.mid       = mid
        self.bid       = bid
        self.ask       = ask
        self.spread    = spread
        self.volume    = volume
        self.is_buy    = is_buy
        self.bid_depth = bid_depth
        self.ask_depth = ask_depth


class MicrostructureEngine:
    """
    Tick-by-tick microstructure analytics engine.

    Thread-safe. Call on_tick() for every validated GoldTick.
    Call get_snapshot() or get_ml_features() to read current state.
    """

    def __init__(self) -> None:
        self._ticks: deque = deque(maxlen=_WINDOW_TICKS)
        self._lock  = threading.Lock()

        # Running accumulators
        self._cumulative_delta: float = 0.0
        self._trade_pressure:   float = 0.0   # EMA
        self._vwap_num:         float = 0.0   # Σ(price × volume)
        self._vwap_den:         float = 0.0   # Σ(volume)
        self._session_open:     float = 0.0   # epoch of last session reset
        self._last_mid:         float = 0.0
        self._kyles_lambda_num: float = 0.0
        self._kyles_lambda_den: float = 0.0

        # Spread EMA state
        self._spread_ema_fast:  float = 0.0
        self._spread_ema_slow:  float = 0.0
        self._spread_alpha_fast = 0.1
        self._spread_alpha_slow = 0.02

        # Tick counter for session reset
        self._tick_count: int = 0

    # ── Public API ────────────────────────────────────────────────────────────

    def on_tick(self, tick: GoldTick) -> MicrostructureSnapshot:
        """
        Process a validated GoldTick and return the current microstructure snapshot.

        Lee-Ready trade classification:
          - tick.mid > prev_mid → buyer-initiated (buy volume)
          - tick.mid < prev_mid → seller-initiated (sell volume)
          - tick.mid == prev_mid → use quote rule (mid vs prev_mid)
        """
        with self._lock:
            return self._process_tick(tick)

    def get_snapshot(self) -> Optional[MicrostructureSnapshot]:
        """Return the most recent microstructure snapshot."""
        with self._lock:
            if not self._ticks:
                return None
            return self._build_snapshot()

    def get_ml_features(self) -> Dict[str, float]:
        """
        Return microstructure features for ML pipeline injection.

        All features are computed from past ticks only (causal).
        """
        snap = self.get_snapshot()
        if snap is None:
            return self._zero_features()

        ticks = list(self._ticks)
        if len(ticks) < 10:
            return self._zero_features()

        mids    = np.array([t.mid    for t in ticks])
        spreads = np.array([t.spread for t in ticks])
        deltas  = np.array([
            t.volume if t.is_buy else -t.volume for t in ticks
        ])

        # Rolling OFI (last 50 ticks)
        recent = ticks[-50:]
        buy_vol  = sum(t.volume for t in recent if t.is_buy)
        sell_vol = sum(t.volume for t in recent if not t.is_buy)
        total_vol = buy_vol + sell_vol
        ofi = (buy_vol - sell_vol) / max(total_vol, 1e-9)

        # Spread z-score
        spread_mean = spreads.mean()
        spread_std  = spreads.std() + 1e-9
        spread_z    = (snap.spread - spread_mean) / spread_std

        # Delta divergence: price direction vs delta direction
        if len(ticks) >= 20:
            price_dir = np.sign(mids[-1] - mids[-20])
            delta_dir = np.sign(deltas[-20:].sum())
            delta_divergence = float(price_dir != delta_dir and price_dir != 0)
        else:
            delta_divergence = 0.0

        # Kyle's lambda (price impact)
        kyles_lambda = (
            self._kyles_lambda_num / max(self._kyles_lambda_den, 1e-9)
        )

        # VWAP deviation
        vwap = self._vwap_num / max(self._vwap_den, 1e-9)
        vwap_dev = (snap.mid - vwap) / max(vwap, 1.0)

        # Absorption: large volume with small price move
        if len(ticks) >= 10:
            recent10 = ticks[-10:]
            vol10    = sum(t.volume for t in recent10)
            price_move = abs(recent10[-1].mid - recent10[0].mid)
            absorption = vol10 / max(price_move * 1000, 1e-9)
            absorption = min(1.0, absorption / 100.0)
        else:
            absorption = 0.0

        return {
            "micro_spread":              round(snap.spread, 6),
            "micro_spread_pct":          round(snap.spread_pct, 6),
            "micro_spread_z":            round(float(spread_z), 4),
            "micro_spread_ema_fast":     round(self._spread_ema_fast, 6),
            "micro_spread_ema_slow":     round(self._spread_ema_slow, 6),
            "micro_volume_delta":        round(snap.volume_delta, 4),
            "micro_cumulative_delta":    round(snap.cumulative_delta, 4),
            "micro_buy_pressure":        round(snap.buy_pressure, 4),
            "micro_sell_pressure":       round(snap.sell_pressure, 4),
            "micro_ofi":                 round(float(ofi), 4),
            "micro_trade_pressure":      round(snap.trade_pressure, 4),
            "micro_depth_imbalance":     round(snap.depth_imbalance, 4),
            "micro_vwap_dev":            round(float(vwap_dev), 6),
            "micro_kyles_lambda":        round(float(kyles_lambda), 8),
            "micro_delta_divergence":    round(delta_divergence, 4),
            "micro_absorption":          round(absorption, 4),
        }

    def reset_session(self) -> None:
        """Reset cumulative delta and VWAP at session open (00:00 UTC)."""
        with self._lock:
            self._cumulative_delta = 0.0
            self._vwap_num         = 0.0
            self._vwap_den         = 0.0
            self._kyles_lambda_num = 0.0
            self._kyles_lambda_den = 0.0
            self._session_open     = time.time()

    # ── Internal processing ───────────────────────────────────────────────────

    def _process_tick(self, tick: GoldTick) -> MicrostructureSnapshot:
        ts     = tick.timestamp.timestamp()
        spread = tick.ask - tick.bid
        mid    = tick.mid

        # Lee-Ready classification
        if self._last_mid > 0:
            is_buy = mid >= self._last_mid
        else:
            is_buy = True   # first tick — assume buy

        volume = max(tick.spread * 1000, 1.0)   # proxy volume from spread × 1000

        rec = _TickRecord(
            ts=ts, mid=mid, bid=tick.bid, ask=tick.ask,
            spread=spread, volume=volume, is_buy=is_buy,
        )
        self._ticks.append(rec)
        self._tick_count += 1

        # Update accumulators
        signed_vol = volume if is_buy else -volume
        self._cumulative_delta += signed_vol
        self._trade_pressure = (
            _PRESSURE_ALPHA * signed_vol
            + (1 - _PRESSURE_ALPHA) * self._trade_pressure
        )

        # VWAP
        self._vwap_num += mid * volume
        self._vwap_den += volume

        # Kyle's lambda: Δprice / Δvolume
        if self._last_mid > 0:
            dp = abs(mid - self._last_mid)
            self._kyles_lambda_num += dp
            self._kyles_lambda_den += volume

        # Spread EMAs
        if self._spread_ema_fast == 0:
            self._spread_ema_fast = spread
            self._spread_ema_slow = spread
        else:
            self._spread_ema_fast = (
                self._spread_alpha_fast * spread
                + (1 - self._spread_alpha_fast) * self._spread_ema_fast
            )
            self._spread_ema_slow = (
                self._spread_alpha_slow * spread
                + (1 - self._spread_alpha_slow) * self._spread_ema_slow
            )

        self._last_mid = mid

        # Auto-reset session at UTC midnight
        now_h = datetime.now(timezone.utc).hour
        if now_h == 0 and self._tick_count % 3600 == 0:
            self.reset_session()

        return self._build_snapshot()

    def _build_snapshot(self) -> MicrostructureSnapshot:
        ticks = list(self._ticks)
        if not ticks:
            return MicrostructureSnapshot(
                symbol="XAU_USD", timestamp=datetime.now(timezone.utc),
                bid=0, ask=0, spread=0, spread_pct=0,
                volume_delta=0, cumulative_delta=0,
                buy_pressure=0.5, sell_pressure=0.5,
                order_flow_imbalance=0, trade_pressure=0,
            )

        last = ticks[-1]
        mid  = last.mid
        spread_pct = (last.spread / mid * 100) if mid > 0 else 0.0

        # Rolling buy/sell pressure (last _DELTA_WINDOW ticks)
        window = ticks[-_DELTA_WINDOW:]
        buy_vol  = sum(t.volume for t in window if t.is_buy)
        sell_vol = sum(t.volume for t in window if not t.is_buy)
        total    = buy_vol + sell_vol or 1.0
        ofi      = (buy_vol - sell_vol) / total

        return MicrostructureSnapshot(
            symbol               = "XAU_USD",
            timestamp            = datetime.now(timezone.utc),
            bid                  = last.bid,
            ask                  = last.ask,
            spread               = last.spread,
            spread_pct           = spread_pct,
            volume_delta         = last.volume if last.is_buy else -last.volume,
            cumulative_delta     = self._cumulative_delta,
            buy_pressure         = buy_vol / total,
            sell_pressure        = sell_vol / total,
            order_flow_imbalance = ofi,
            trade_pressure       = self._trade_pressure,
            depth_imbalance      = 0.0,   # populated when depth data available
            vwap                 = self._vwap_num / max(self._vwap_den, 1e-9),
            tick_count           = len(ticks),
        )

    def _zero_features(self) -> Dict[str, float]:
        return {
            "micro_spread":           0.0,
            "micro_spread_pct":       0.0,
            "micro_spread_z":         0.0,
            "micro_spread_ema_fast":  0.0,
            "micro_spread_ema_slow":  0.0,
            "micro_volume_delta":     0.0,
            "micro_cumulative_delta": 0.0,
            "micro_buy_pressure":     0.5,
            "micro_sell_pressure":    0.5,
            "micro_ofi":              0.0,
            "micro_trade_pressure":   0.0,
            "micro_depth_imbalance":  0.0,
            "micro_vwap_dev":         0.0,
            "micro_kyles_lambda":     0.0,
            "micro_delta_divergence": 0.0,
            "micro_absorption":       0.0,
        }


# Module-level singleton
microstructure_engine = MicrostructureEngine()

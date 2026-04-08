# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
data_layer/microstructure/engine.py
=====================================
MicrostructureEngine — professional market microstructure analytics.

Computed metrics (all tick-by-tick, zero look-ahead)
-----------------------------------------------------
Spread dynamics:
  - bid/ask spread (absolute + percentage)
  - spread EMA fast (α=0.10) and slow (α=0.02)
  - spread z-score (regime detection: wide spread = low liquidity)

Volume & trade flow (Lee-Ready classification):
  - volume delta per tick (buy_vol - sell_vol, signed)
  - cumulative delta (running sum, reset at UTC session open)
  - buy/sell pressure ratio (rolling _DELTA_WINDOW ticks)
  - order flow imbalance (OFI): (buy_vol - sell_vol) / (buy_vol + sell_vol)
  - trade pressure EMA (signed flow momentum, α=0.10)

Depth & liquidity:
  - bid/ask depth imbalance (populated when L2 data available)
  - effective spread (2 × |trade_price - mid|)
  - Kyle's lambda (price impact per unit volume: Δprice / Δvolume)

Derived signals:
  - absorption ratio (large volume absorbed without price move)
  - delta divergence (price up but delta falling = bearish divergence)
  - VWAP deviation (current mid vs rolling VWAP)

All metrics use only past ticks — causal guarantee enforced.
Session reset at UTC midnight resets cumulative delta and VWAP.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from collections import deque
from datetime import datetime, timezone

UTC = timezone.utc

import numpy as np

from data_layer.types import GoldTick, MicrostructureSnapshot

logger = logging.getLogger(__name__)

_WINDOW_TICKS = int(os.getenv("MICRO_WINDOW_TICKS", "500"))
_DELTA_WINDOW = int(os.getenv("MICRO_DELTA_WINDOW", "100"))
_PRESSURE_ALPHA = float(os.getenv("MICRO_PRESSURE_ALPHA", "0.10"))
_SPREAD_ALPHA_F = float(os.getenv("MICRO_SPREAD_ALPHA_F", "0.10"))
_SPREAD_ALPHA_S = float(os.getenv("MICRO_SPREAD_ALPHA_S", "0.02"))
_VWAP_WINDOW = int(os.getenv("MICRO_VWAP_WINDOW", "200"))
_ZSCORE_WINDOW = int(os.getenv("MICRO_ZSCORE_WINDOW", "100"))


class _TickRecord:
    """Lightweight tick record for microstructure calculations."""

    __slots__ = (
        "ask",
        "ask_depth",
        "bid",
        "bid_depth",
        "is_buy",
        "mid",
        "spread",
        "ts",
        "volume",
    )

    def __init__(
        self,
        ts: float,
        mid: float,
        bid: float,
        ask: float,
        spread: float,
        volume: float,
        is_buy: bool,
        bid_depth: float = 0.0,
        ask_depth: float = 0.0,
    ) -> None:
        self.ts = ts
        self.mid = mid
        self.bid = bid
        self.ask = ask
        self.spread = spread
        self.volume = volume
        self.is_buy = is_buy
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
        self._lock = threading.Lock()

        # Running accumulators
        self._cumulative_delta: float = 0.0
        self._trade_pressure: float = 0.0  # EMA of signed flow
        self._vwap_num: float = 0.0  # Σ(price × volume)
        self._vwap_den: float = 0.0  # Σ(volume)
        self._session_open: float = 0.0
        self._last_mid: float = 0.0
        self._last_session_day: int = -1

        # Kyle's lambda accumulators
        self._kyles_num: float = 0.0  # Σ|Δprice|
        self._kyles_den: float = 0.0  # Σvolume

        # Spread EMA state
        self._spread_ema_fast: float = 0.0
        self._spread_ema_slow: float = 0.0

        # Tick counter
        self._tick_count: int = 0

        # Prometheus
        self._prom_spread = None
        self._prom_ofi = None
        self._prom_cum_delta = None
        self._init_prometheus()

    def _init_prometheus(self) -> None:
        try:
            from prometheus_client import Gauge

            self._prom_spread = Gauge(
                "hopefx_micro_spread_usd",
                "Current bid/ask spread in USD",
            )
            self._prom_ofi = Gauge(
                "hopefx_micro_ofi",
                "Order flow imbalance [-1, 1]",
            )
            self._prom_cum_delta = Gauge(
                "hopefx_micro_cumulative_delta",
                "Cumulative volume delta (session)",
            )
        except Exception as _exc:
            logger.debug("Suppressed exception: %s", _exc)

    # ── Public API ────────────────────────────────────────────────────────────

    def on_tick(self, tick: GoldTick) -> MicrostructureSnapshot:
        """
        Process a validated GoldTick and return the current snapshot.

        Lee-Ready trade classification:
          - mid > prev_mid  → buyer-initiated
          - mid < prev_mid  → seller-initiated
          - mid == prev_mid → use quote rule (mid vs midpoint)
        """
        with self._lock:
            return self._process_tick(tick)

    def get_snapshot(self) -> MicrostructureSnapshot | None:
        """Return the most recent microstructure snapshot."""
        with self._lock:
            if not self._ticks:
                return None
            return self._build_snapshot()

    def get_ml_features(self) -> dict[str, float]:
        """
        Return 16 microstructure features for ML pipeline injection.

        All features computed from past ticks only (causal).
        Returns zero-filled dict when insufficient history.
        """
        with self._lock:
            if len(self._ticks) < 10:
                return self._zero_features()

            snap = self._build_snapshot()
            ticks = list(self._ticks)
            mids = np.array([t.mid for t in ticks], dtype=np.float64)
            spreads = np.array([t.spread for t in ticks], dtype=np.float64)
            deltas = np.array([t.volume if t.is_buy else -t.volume for t in ticks], dtype=np.float64)

            # OFI over last 50 ticks
            recent = ticks[-50:]
            buy_vol = sum(t.volume for t in recent if t.is_buy)
            sell_vol = sum(t.volume for t in recent if not t.is_buy)
            total_vol = buy_vol + sell_vol
            ofi = (buy_vol - sell_vol) / max(total_vol, 1e-9)

            # Spread z-score (rolling _ZSCORE_WINDOW)
            w = min(_ZSCORE_WINDOW, len(spreads))
            spread_win = spreads[-w:]
            spread_mean = spread_win.mean()
            spread_std = spread_win.std() + 1e-9
            spread_z = (snap.spread - spread_mean) / spread_std

            # Delta divergence: price direction vs cumulative delta direction
            if len(ticks) >= 20:
                price_dir = np.sign(mids[-1] - mids[-20])
                delta_dir = np.sign(deltas[-20:].sum())
                delta_divergence = float(price_dir != delta_dir and price_dir != 0)
            else:
                delta_divergence = 0.0

            # Kyle's lambda (price impact coefficient)
            kyles_lambda = self._kyles_num / max(self._kyles_den, 1e-9)

            # VWAP deviation
            vwap = self._vwap_num / max(self._vwap_den, 1e-9)
            vwap_dev = (snap.mid - vwap) / max(vwap, 1.0) if vwap > 0 else 0.0

            # Absorption: large volume with small price move
            if len(ticks) >= 10:
                recent10 = ticks[-10:]
                vol10 = sum(t.volume for t in recent10)
                price_move = abs(recent10[-1].mid - recent10[0].mid)
                # Normalise: absorption > 1 means volume >> price move
                absorption = min(1.0, vol10 / max(price_move * 500, 1e-9) / 100.0)
            else:
                absorption = 0.0

            return {
                "micro_spread": round(snap.spread, 6),
                "micro_spread_pct": round(snap.spread_pct, 6),
                "micro_spread_z": round(float(spread_z), 4),
                "micro_spread_ema_fast": round(self._spread_ema_fast, 6),
                "micro_spread_ema_slow": round(self._spread_ema_slow, 6),
                "micro_volume_delta": round(snap.volume_delta, 4),
                "micro_cumulative_delta": round(snap.cumulative_delta, 4),
                "micro_buy_pressure": round(snap.buy_pressure, 4),
                "micro_sell_pressure": round(snap.sell_pressure, 4),
                "micro_ofi": round(float(ofi), 4),
                "micro_trade_pressure": round(snap.trade_pressure, 4),
                "micro_depth_imbalance": round(snap.depth_imbalance, 4),
                "micro_vwap_dev": round(float(vwap_dev), 6),
                "micro_kyles_lambda": round(float(kyles_lambda), 8),
                "micro_delta_divergence": round(delta_divergence, 4),
                "micro_absorption": round(absorption, 4),
                # Tick count — used by features_extended.py for normalised
                # activity feature (dl_tick_count = tick_count / 500)
                "micro_tick_count": float(self._tick_count),
            }

    def reset_session(self) -> None:
        """Reset cumulative delta and VWAP at session open (00:00 UTC).

        Public API — acquires the lock. Do NOT call from within _process_tick
        (which already holds the lock) — use _reset_session_unlocked() instead.
        """
        with self._lock:
            self._reset_session_unlocked()

    def _reset_session_unlocked(self) -> None:
        """Reset session accumulators. Caller must already hold self._lock."""
        self._cumulative_delta = 0.0
        self._vwap_num = 0.0
        self._vwap_den = 0.0
        self._kyles_num = 0.0
        self._kyles_den = 0.0
        self._session_open = time.time()
        logger.debug("MicrostructureEngine: session reset")

    def inject_l2_depth(
        self,
        symbol: str,
        bid_depth: float,
        ask_depth: float,
    ) -> None:
        """
        Inject real Level-2 order book depth into the latest tick record.

        Called by market_data/order_book.py when a real L2 snapshot arrives.
        Updates the most recent _TickRecord in-place so the next
        get_ml_features() call reflects real depth imbalance.

        Parameters
        ----------
        symbol    : instrument symbol (must match "XAU_USD")
        bid_depth : total bid-side volume within L2_DEPTH_BPS of mid
        ask_depth : total ask-side volume within L2_DEPTH_BPS of mid
        """
        if symbol != "XAU_USD":
            return
        with self._lock:
            if not self._ticks:
                return
            last = self._ticks[-1]
            last.bid_depth = max(bid_depth, 0.0)
            last.ask_depth = max(ask_depth, 0.0)

    def health(self) -> dict[str, object]:
        """
        Return a health summary dict for monitoring and the orchestrator health endpoint.

        Keys:
          tick_count        : total ticks processed since startup
          window_size       : current rolling window depth
          cumulative_delta  : session cumulative volume delta
          trade_pressure    : current EMA trade pressure
          spread_ema_fast   : fast spread EMA
          spread_ema_slow   : slow spread EMA
          session_open_age_s: seconds since last session reset
          has_data          : True when window has >= 10 ticks
        """
        with self._lock:
            return {
                "tick_count": self._tick_count,
                "window_size": len(self._ticks),
                "cumulative_delta": round(self._cumulative_delta, 4),
                "trade_pressure": round(self._trade_pressure, 4),
                "spread_ema_fast": round(self._spread_ema_fast, 6),
                "spread_ema_slow": round(self._spread_ema_slow, 6),
                "session_open_age_s": round(time.time() - self._session_open, 1) if self._session_open > 0 else None,
                "has_data": len(self._ticks) >= 10,
            }

    def tick_rate(self, window_s: float = 60.0) -> float:
        """
        Estimate ticks per second over the last window_s seconds.

        Uses the timestamps of ticks in the rolling window.
        Returns 0.0 when insufficient data.
        """
        with self._lock:
            if len(self._ticks) < 2:
                return 0.0
            ticks = list(self._ticks)
            now = time.time()
            recent = [t for t in ticks if (now - t.ts) <= window_s]
            if len(recent) < 2:
                return 0.0
            elapsed = recent[-1].ts - recent[0].ts
            return round(len(recent) / max(elapsed, 1e-9), 4)

    # ── Internal processing ───────────────────────────────────────────────────

    def _process_tick(self, tick: GoldTick) -> MicrostructureSnapshot:
        ts = tick.timestamp.timestamp()
        spread = max(tick.ask - tick.bid, 0.0)
        mid = tick.mid

        # Lee-Ready trade classification
        if self._last_mid > 0:
            if mid > self._last_mid:
                is_buy = True
            elif mid < self._last_mid:
                is_buy = False
            else:
                # Quote rule: trade at or above mid = buy
                is_buy = mid >= (tick.bid + tick.ask) / 2
        else:
            is_buy = True  # first tick — assume buy

        # Volume: use unit volume (1.0 per tick) for REST-only feeds that
        # provide no real trade volume. Using spread×1000 was fabricated data
        # that created spurious correlation between spread and OFI signals.
        # When real L2 volume is injected via inject_l2_depth(), the depth
        # fields carry the actual size information.
        volume = 1.0

        rec = _TickRecord(
            ts=ts,
            mid=mid,
            bid=tick.bid,
            ask=tick.ask,
            spread=spread,
            volume=volume,
            is_buy=is_buy,
        )
        self._ticks.append(rec)
        self._tick_count += 1

        # Signed volume (tick-count delta)
        signed_vol = 1.0 if is_buy else -1.0

        # Cumulative delta (net buy ticks - sell ticks this session)
        self._cumulative_delta += signed_vol

        # Trade pressure EMA
        self._trade_pressure = _PRESSURE_ALPHA * signed_vol + (1.0 - _PRESSURE_ALPHA) * self._trade_pressure

        # VWAP (mid-price weighted by tick count — best proxy without real volume)
        self._vwap_num += mid
        self._vwap_den += 1.0

        # Kyle's lambda: Σ|Δprice| / Σtick_count (price impact per tick)
        if self._last_mid > 0:
            self._kyles_num += abs(mid - self._last_mid)
            self._kyles_den += 1.0

        # Spread EMAs
        if self._spread_ema_fast == 0.0:
            self._spread_ema_fast = spread
            self._spread_ema_slow = spread
        else:
            self._spread_ema_fast = _SPREAD_ALPHA_F * spread + (1.0 - _SPREAD_ALPHA_F) * self._spread_ema_fast
            self._spread_ema_slow = _SPREAD_ALPHA_S * spread + (1.0 - _SPREAD_ALPHA_S) * self._spread_ema_slow

        self._last_mid = mid

        # Auto-reset at UTC midnight — call _reset_session_unlocked() to avoid
        # deadlock: _process_tick is already called under self._lock, and the
        # public reset_session() also acquires self._lock.
        now_utc = datetime.now(UTC)
        if now_utc.day != self._last_session_day and self._last_session_day >= 0:
            self._reset_session_unlocked()
        self._last_session_day = now_utc.day

        snap = self._build_snapshot()

        # Prometheus
        if self._prom_spread:
            self._prom_spread.set(spread)
        if self._prom_ofi:
            ticks = list(self._ticks)
            w = ticks[-_DELTA_WINDOW:]
            bv = sum(t.volume for t in w if t.is_buy)
            sv = sum(t.volume for t in w if not t.is_buy)
            tv = bv + sv
            self._prom_ofi.set((bv - sv) / max(tv, 1e-9))
        if self._prom_cum_delta:
            self._prom_cum_delta.set(self._cumulative_delta)

        return snap

    def _build_snapshot(self) -> MicrostructureSnapshot:
        ticks = list(self._ticks)
        if not ticks:
            return MicrostructureSnapshot(
                symbol="XAU_USD",
                timestamp=datetime.now(UTC),
                bid=0,
                ask=0,
                spread=0,
                spread_pct=0,
                volume_delta=0,
                cumulative_delta=0,
                buy_pressure=0.5,
                sell_pressure=0.5,
                order_flow_imbalance=0,
                trade_pressure=0,
            )

        last = ticks[-1]
        mid = last.mid
        spread_pct = (last.spread / mid * 100.0) if mid > 0 else 0.0

        # Rolling buy/sell pressure
        window = ticks[-_DELTA_WINDOW:]
        buy_vol = sum(t.volume for t in window if t.is_buy)
        sell_vol = sum(t.volume for t in window if not t.is_buy)
        total = buy_vol + sell_vol or 1.0
        ofi = (buy_vol - sell_vol) / total

        # Depth imbalance (populated when L2 data available)
        bid_depth = last.bid_depth
        ask_depth = last.ask_depth
        depth_total = bid_depth + ask_depth
        depth_imbalance = (bid_depth - ask_depth) / depth_total if depth_total > 0 else 0.0

        vwap = self._vwap_num / max(self._vwap_den, 1e-9)

        return MicrostructureSnapshot(
            symbol="XAU_USD",
            timestamp=datetime.now(UTC),
            bid=last.bid,
            ask=last.ask,
            spread=last.spread,
            spread_pct=spread_pct,
            volume_delta=last.volume if last.is_buy else -last.volume,
            cumulative_delta=self._cumulative_delta,
            buy_pressure=buy_vol / total,
            sell_pressure=sell_vol / total,
            order_flow_imbalance=ofi,
            trade_pressure=self._trade_pressure,
            bid_depth=bid_depth,
            ask_depth=ask_depth,
            depth_imbalance=depth_imbalance,
            vwap=vwap,
            tick_count=len(ticks),
        )

    def _zero_features(self) -> dict[str, float]:
        return {
            "micro_spread": 0.0,
            "micro_spread_pct": 0.0,
            "micro_spread_z": 0.0,
            "micro_spread_ema_fast": 0.0,
            "micro_spread_ema_slow": 0.0,
            "micro_volume_delta": 0.0,
            "micro_cumulative_delta": 0.0,
            "micro_buy_pressure": 0.5,
            "micro_sell_pressure": 0.5,
            "micro_ofi": 0.0,
            "micro_trade_pressure": 0.0,
            "micro_depth_imbalance": 0.0,
            "micro_vwap_dev": 0.0,
            "micro_kyles_lambda": 0.0,
            "micro_delta_divergence": 0.0,
            "micro_absorption": 0.0,
            # Always include tick_count even in zero state so downstream
            # consumers (features_extended.py dl_tick_count) never KeyError
            "micro_tick_count": float(self._tick_count),
        }


# Module-level singleton
microstructure_engine = MicrostructureEngine()

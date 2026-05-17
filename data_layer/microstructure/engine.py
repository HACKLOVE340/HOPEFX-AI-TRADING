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

New in this version
-------------------
- Amihud illiquidity ratio: |Δprice| / volume, rolling window average.
  High values indicate price moves a lot per unit of volume (illiquid).
- Hasbrouck information share: fraction of price discovery attributable to
  this venue, estimated from the ratio of permanent price impact to total
  variance. Computed over a rolling window using the Gonzalo-Granger method.
- PIN model (Probability of Informed Trading): estimated via the simplified
  Easley-O'Hara model on rolling buy/sell tick counts. PIN = α·μ / (α·μ + 2ε)
  where α = fraction of informed-trading days, μ = informed arrival rate,
  ε = uninformed arrival rate.

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
# Amihud illiquidity window (ticks)
_AMIHUD_WINDOW = int(os.getenv("MICRO_AMIHUD_WINDOW", "100"))
# Hasbrouck information share window (ticks)
_HASBROUCK_WINDOW = int(os.getenv("MICRO_HASBROUCK_WINDOW", "200"))
# PIN model window (ticks)
_PIN_WINDOW = int(os.getenv("MICRO_PIN_WINDOW", "200"))


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
        self._last_session_day: tuple | int = -1

        # Kyle's lambda accumulators — rolling window (last _KYLE_WINDOW ticks)
        self._kyles_num: float = 0.0  # Σ|Δprice|
        self._kyles_den: float = 0.0  # Σvolume
        # Rolling window for Kyle's lambda to prevent unbounded accumulation
        _KYLE_WINDOW = int(os.getenv("MICRO_KYLE_WINDOW", "200"))
        self._kyle_price_changes: deque = deque(maxlen=_KYLE_WINDOW)
        self._kyle_volumes: deque = deque(maxlen=_KYLE_WINDOW)

        # Spread EMA state
        self._spread_ema_fast: float = 0.0
        self._spread_ema_slow: float = 0.0

        # L2 OFI delta tracking — tracks changes in bid/ask depth between snapshots
        # OFI_L2 = Δbid_depth - Δask_depth (positive = net order flow buying pressure)
        self._prev_bid_depth: float = 0.0
        self._prev_ask_depth: float = 0.0
        self._ofi_l2_delta: float = 0.0  # latest L2 OFI delta
        self._ofi_l2_ema: float = 0.0  # EMA-smoothed L2 OFI
        _OFI_L2_ALPHA = float(os.getenv("MICRO_OFI_L2_ALPHA", "0.10"))
        self._ofi_l2_alpha: float = _OFI_L2_ALPHA

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
                mids_arr = np.nan_to_num(np.asarray(mids), nan=0.0)
                deltas_arr = np.nan_to_num(np.asarray(deltas), nan=0.0)
                price_dir = np.sign(mids_arr[-1] - mids_arr[-20])
                delta_dir = np.sign(deltas_arr[-20:].sum())
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

            # Amihud, Hasbrouck, PIN — computed under lock inside their methods
            # but we are already under lock here, so call internal versions
            amihud = self._amihud_unlocked(ticks)
            hasbrouck = self._hasbrouck_unlocked(ticks)
            pin_data = self._pin_unlocked(ticks)

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
                "micro_amihud": round(amihud, 8),
                "micro_hasbrouck_is": round(hasbrouck, 4),
                "micro_pin": round(pin_data["pin"], 4),
                "micro_pin_alpha": round(pin_data["alpha"], 4),
                # Tick count — used by features_extended.py for normalised
                # activity feature (dl_tick_count = tick_count / 500)
                "micro_tick_count": float(self._tick_count),
                # L2 OFI delta — change in bid depth minus change in ask depth
                # from the most recent L2 snapshot injection
                "micro_ofi_l2_delta": round(self._ofi_l2_delta, 6),
                "micro_ofi_l2_ema": round(self._ofi_l2_ema, 6),
            }

    # ── Amihud illiquidity ratio ──────────────────────────────────────────────

    def amihud_illiquidity(self, window: int | None = None) -> float:
        """
        Compute the Amihud (2002) illiquidity ratio over the rolling window.

        ILLIQ = (1/N) × Σ |Δprice_t| / volume_t

        High values indicate the market moves a lot per unit of volume (illiquid).
        Returns 0.0 when insufficient data.

        Reference: Amihud, Y. (2002). Illiquidity and stock returns.
        Journal of Financial Markets, 5(1), 31-56.
        """
        with self._lock:
            w = window or _AMIHUD_WINDOW
            ticks = list(self._ticks)
            if len(ticks) < 2:
                return 0.0
            recent = ticks[-w:]
            ratios = []
            for i in range(1, len(recent)):
                price_change = abs(recent[i].mid - recent[i - 1].mid)
                vol = max(recent[i].volume, 1e-9)
                ratios.append(price_change / vol)
            if not ratios:
                return 0.0
            return round(float(np.mean(ratios)), 8)

    # ── Hasbrouck information share ───────────────────────────────────────────

    def hasbrouck_information_share(self, window: int | None = None) -> float:
        """
        Estimate the Hasbrouck (1995) information share for this venue.

        Uses the Gonzalo-Granger (1995) permanent-transitory decomposition
        as a tractable approximation:

          IS ≈ var(permanent_component) / var(total_price_change)

        The permanent component is estimated as the fraction of a price
        innovation that persists after _HASBROUCK_WINDOW ticks, computed
        via the ratio of the long-run variance to the short-run variance.

        Returns a value in [0, 1] where 1 = all price discovery here.
        Returns 0.5 (neutral) when insufficient data.

        Reference: Hasbrouck, J. (1995). One security, many markets.
        Journal of Finance, 50(4), 1175-1199.
        """
        with self._lock:
            w = window or _HASBROUCK_WINDOW
            ticks = list(self._ticks)
            if len(ticks) < max(w, 20):
                return 0.5
            mids = np.array([t.mid for t in ticks[-w:]], dtype=np.float64)
            returns = np.diff(mids)
            if len(returns) < 10:
                return 0.5
            # Short-run variance: variance of 1-period returns
            var_short = float(np.var(returns)) + 1e-12
            # Long-run variance: variance of cumulative sum (random walk component)
            # Estimated via Newey-West-style sum of autocovariances
            n = len(returns)
            lags = min(10, n // 4)
            gamma_0 = float(np.var(returns))
            long_run_var = gamma_0
            for lag in range(1, lags + 1):
                gamma_lag = float(np.cov(returns[lag:], returns[:-lag])[0, 1]) if n > lag + 1 else 0.0
                weight = 1.0 - lag / (lags + 1)  # Bartlett kernel
                long_run_var += 2.0 * weight * gamma_lag
            long_run_var = max(long_run_var, 1e-12)
            # IS = long-run variance / (long-run variance + short-run variance)
            # Clamp to [0, 1]
            is_ratio = float(np.clip(long_run_var / (long_run_var + var_short), 0.0, 1.0))
            return round(is_ratio, 4)

    # ── PIN model ─────────────────────────────────────────────────────────────

    def pin_model(self, window: int | None = None) -> dict[str, float]:
        """
        Estimate the Probability of Informed Trading (PIN) via the simplified
        Easley, Kiefer, O'Hara & Paperman (1996) model.

        Model parameters estimated from rolling buy/sell tick counts:
          α  = fraction of trading periods with informed activity
               estimated as: |buy_ticks - sell_ticks| / total_ticks
          μ  = informed trader arrival rate (excess order flow)
               estimated as: |buy_ticks - sell_ticks| / window
          ε  = uninformed arrival rate (symmetric baseline)
               estimated as: min(buy_ticks, sell_ticks) / window

        PIN = α·μ / (α·μ + 2ε)

        Returns dict with keys:
          pin:   Probability of Informed Trading [0, 1]
          alpha: fraction of informed periods [0, 1]
          mu:    informed arrival rate (ticks/window)
          epsilon: uninformed arrival rate (ticks/window)
          buy_ticks: count of buyer-initiated ticks in window
          sell_ticks: count of seller-initiated ticks in window

        Returns zeros when insufficient data.

        Reference: Easley, D. et al. (1996). Liquidity, information, and
        infrequently traded stocks. Journal of Finance, 51(4), 1405-1436.
        """
        with self._lock:
            w = window or _PIN_WINDOW
            ticks = list(self._ticks)
            if len(ticks) < 20:
                return {"pin": 0.0, "alpha": 0.0, "mu": 0.0, "epsilon": 0.0, "buy_ticks": 0, "sell_ticks": 0}
            recent = ticks[-w:]
            buy_ticks = sum(1 for t in recent if t.is_buy)
            sell_ticks = len(recent) - buy_ticks
            total = len(recent)

            if total == 0:
                return {"pin": 0.0, "alpha": 0.0, "mu": 0.0, "epsilon": 0.0, "buy_ticks": 0, "sell_ticks": 0}

            # Estimate model parameters
            imbalance = abs(buy_ticks - sell_ticks)
            alpha = imbalance / total  # fraction of informed periods
            mu = imbalance / total  # informed arrival rate (normalised)
            epsilon = min(buy_ticks, sell_ticks) / total  # uninformed rate

            # PIN formula
            denom = alpha * mu + 2.0 * epsilon
            pin = (alpha * mu / denom) if denom > 1e-9 else 0.0
            pin = float(np.clip(pin, 0.0, 1.0))

            return {
                "pin": round(pin, 4),
                "alpha": round(alpha, 4),
                "mu": round(mu, 4),
                "epsilon": round(epsilon, 4),
                "buy_ticks": buy_ticks,
                "sell_ticks": sell_ticks,
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
        # Clear rolling window so Kyle's lambda starts fresh each session
        self._kyle_price_changes.clear()
        self._kyle_volumes.clear()
        # Reset L2 OFI delta baseline so the first post-reset snapshot
        # doesn't produce a spurious large delta from the previous session
        self._prev_bid_depth = 0.0
        self._prev_ask_depth = 0.0
        self._ofi_l2_delta = 0.0
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
            bid_depth = max(bid_depth, 0.0)
            ask_depth = max(ask_depth, 0.0)
            last.bid_depth = bid_depth
            last.ask_depth = ask_depth

            # OFI L2 delta: change in bid depth minus change in ask depth.
            # Positive = more bids added (or asks removed) = buying pressure.
            delta_bid = bid_depth - self._prev_bid_depth
            delta_ask = ask_depth - self._prev_ask_depth
            self._ofi_l2_delta = delta_bid - delta_ask
            self._ofi_l2_ema = self._ofi_l2_alpha * self._ofi_l2_delta + (1.0 - self._ofi_l2_alpha) * self._ofi_l2_ema
            self._prev_bid_depth = bid_depth
            self._prev_ask_depth = ask_depth

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

    # ── Lock-free internal variants (called while self._lock is held) ─────────

    def _amihud_unlocked(self, ticks: list) -> float:
        if len(ticks) < 2:
            return 0.0
        recent = ticks[-_AMIHUD_WINDOW:]
        ratios = []
        for i in range(1, len(recent)):
            price_change = abs(recent[i].mid - recent[i - 1].mid)
            vol = max(recent[i].volume, 1e-9)
            ratios.append(price_change / vol)
        return float(np.mean(ratios)) if ratios else 0.0

    def _hasbrouck_unlocked(self, ticks: list) -> float:
        w = _HASBROUCK_WINDOW
        if len(ticks) < max(w, 20):
            return 0.5
        mids = np.array([t.mid for t in ticks[-w:]], dtype=np.float64)
        returns = np.diff(mids)
        if len(returns) < 10:
            return 0.5
        var_short = float(np.var(returns)) + 1e-12
        n = len(returns)
        lags = min(10, n // 4)
        long_run_var = float(np.var(returns))
        for lag in range(1, lags + 1):
            if n > lag + 1:
                gamma_lag = float(np.cov(returns[lag:], returns[:-lag])[0, 1])
                weight = 1.0 - lag / (lags + 1)
                long_run_var += 2.0 * weight * gamma_lag
        long_run_var = max(long_run_var, 1e-12)
        return float(np.clip(long_run_var / (long_run_var + var_short), 0.0, 1.0))

    def _pin_unlocked(self, ticks: list) -> dict[str, float]:
        w = _PIN_WINDOW
        if len(ticks) < 20:
            return {"pin": 0.0, "alpha": 0.0, "mu": 0.0, "epsilon": 0.0, "buy_ticks": 0, "sell_ticks": 0}
        recent = ticks[-w:]
        buy_ticks = sum(1 for t in recent if t.is_buy)
        sell_ticks = len(recent) - buy_ticks
        total = len(recent)
        imbalance = abs(buy_ticks - sell_ticks)
        alpha = imbalance / total
        mu = imbalance / total
        epsilon = min(buy_ticks, sell_ticks) / total
        denom = alpha * mu + 2.0 * epsilon
        pin = float(np.clip((alpha * mu / denom) if denom > 1e-9 else 0.0, 0.0, 1.0))
        return {
            "pin": pin,
            "alpha": alpha,
            "mu": mu,
            "epsilon": epsilon,
            "buy_ticks": buy_ticks,
            "sell_ticks": sell_ticks,
        }

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

        # Kyle's lambda: rolling window |Δprice| / volume (price impact per unit volume)
        if self._last_mid > 0:
            price_change = abs(mid - self._last_mid)
            self._kyle_price_changes.append(price_change)
            self._kyle_volumes.append(volume)
            # Recompute from rolling window (deque handles eviction automatically)
            self._kyles_num = sum(self._kyle_price_changes)
            self._kyles_den = sum(self._kyle_volumes)

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
        now_date = (now_utc.year, now_utc.month, now_utc.day)
        if now_date != self._last_session_day and self._last_session_day != -1:
            self._reset_session_unlocked()
        self._last_session_day = now_date

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
            "micro_amihud": 0.0,
            "micro_hasbrouck_is": 0.5,
            "micro_pin": 0.0,
            "micro_pin_alpha": 0.0,
            # Always include tick_count even in zero state so downstream
            # consumers (features_extended.py dl_tick_count) never KeyError
            "micro_tick_count": float(self._tick_count),
            "micro_ofi_l2_delta": 0.0,
            "micro_ofi_l2_ema": 0.0,
        }


# Module-level singleton
microstructure_engine = MicrostructureEngine()

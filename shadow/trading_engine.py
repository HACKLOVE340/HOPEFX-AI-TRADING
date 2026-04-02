# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
shadow/trading_engine.py
=========================
ShadowTradingEngine — live signals executed in paper mode in parallel.

Runs the full signal → risk → sizing → paper-fill pipeline alongside live
trading without touching any real broker. Enables:

  - Paper-vs-live performance comparison at tick frequency
  - Slippage model validation (shadow fill vs live fill)
  - Strategy degradation detection before it costs real money
  - Regime-shift impact measurement

Architecture
------------
  Live signal (from HopeFXEngine)
        │
        ├──► Real broker (live execution)
        │
        └──► ShadowTradingEngine.on_signal()
                    │
                    ├── RiskManager (same instance, read-only sizing)
                    ├── PaperFillSimulator (realistic slippage model)
                    ├── PerformanceTracker (shadow equity curve)
                    └── Divergence reporter (shadow vs live PnL gap)

Zero side-effects: never calls any broker API, never modifies shared state.

Slippage model
--------------
  fill_price = mid ± (half_spread + market_impact + random_noise)

  market_impact = IMPACT_BPS * sqrt(lots / ADV_LOTS) * mid / 10_000
  random_noise  = N(0, NOISE_BPS) * mid / 10_000

  All parameters env-overridable (SHADOW_HALF_SPREAD_BPS etc.)
"""

from __future__ import annotations

import logging
import math
import os
import random
import time
from dataclasses import dataclass
from datetime import datetime, timezone

UTC = timezone.utc
from typing import Any

logger = logging.getLogger(__name__)

# ── slippage model params ─────────────────────────────────────────────────────
_HALF_SPREAD_BPS = float(os.getenv("SHADOW_HALF_SPREAD_BPS", "3.0"))
_IMPACT_BPS = float(os.getenv("SHADOW_IMPACT_BPS", "2.0"))
_NOISE_BPS = float(os.getenv("SHADOW_NOISE_BPS", "1.0"))
_ADV_LOTS = float(os.getenv("SHADOW_ADV_LOTS", "100.0"))

# ── Prometheus ────────────────────────────────────────────────────────────────
try:
    from prometheus_client import Counter, Gauge

    _prom_shadow_trades = Counter("hopefx_shadow_trades_total", "Shadow trades executed")
    _prom_shadow_pnl = Gauge("hopefx_shadow_pnl_usd", "Shadow cumulative PnL USD")
    _prom_shadow_equity = Gauge("hopefx_shadow_equity_usd", "Shadow equity USD")
    _prom_live_gap = Gauge("hopefx_shadow_live_pnl_gap_usd", "Shadow vs live PnL gap USD")
    _PROM_OK = True
except Exception:
    _PROM_OK = False


@dataclass
class ShadowFill:
    """A simulated paper fill."""

    signal_id: str
    symbol: str
    side: str
    lots: float
    requested: float
    fill_price: float
    slippage_bps: float
    timestamp: datetime
    pnl: float = 0.0
    closed: bool = False
    close_price: float = 0.0
    live_slippage_bps: float | None = None  # set when live fill is reported


@dataclass
class ShadowPosition:
    """Open shadow position."""

    symbol: str
    side: str
    lots: float
    entry_price: float
    stop_loss: float
    take_profit: float
    opened_at: datetime
    signal_id: str


class PaperFillSimulator:
    """
    Realistic paper fill simulator using Almgren-Chriss inspired impact model.

    fill = mid ± half_spread ± market_impact ± noise
    """

    def simulate(
        self,
        side: str,
        mid: float,
        lots: float,
    ) -> tuple[float, float]:
        """
        Return (fill_price, slippage_bps).

        side: "long" | "short"
        """
        half_spread = mid * _HALF_SPREAD_BPS / 10_000
        market_impact = mid * _IMPACT_BPS / 10_000 * math.sqrt(lots / max(_ADV_LOTS, 0.01))
        noise = mid * _NOISE_BPS / 10_000 * random.gauss(0, 1)

        total_cost = half_spread + market_impact + abs(noise)
        fill = mid + total_cost if side == "long" else mid - total_cost

        slippage_bps = abs(fill - mid) / mid * 10_000
        return round(fill, 4), round(slippage_bps, 3)


class ShadowTradingEngine:
    """
    Shadow trading engine — paper execution of live signals.

    Usage
    -----
        engine = ShadowTradingEngine(initial_balance=10_000.0)
        await engine.start()

        # Called by HopeFXEngine on every signal (before live execution):
        engine.on_signal(signal_id="abc", symbol="XAU_USD", side="long",
                         lots=0.01, mid=2350.0, stop_loss=2345.0,
                         take_profit=2360.0)

        # Called on each tick to update open positions:
        engine.on_tick(mid=2352.0)

        # Called when live trade closes (for comparison):
        engine.on_live_close(signal_id="abc", live_pnl=12.50)
    """

    def __init__(self, initial_balance: float = 10_000.0) -> None:
        self._balance: float = initial_balance
        self._equity: float = initial_balance
        self._peak: float = initial_balance
        self._pnl: float = 0.0
        self._fills: list[ShadowFill] = []
        self._positions: list[ShadowPosition] = []
        self._simulator = PaperFillSimulator()
        self._started: bool = False
        self._start_ts: float = time.time()

        # Live comparison
        self._live_pnl: float = 0.0
        self._live_fills: int = 0

    async def start(self) -> None:
        self._started = True
        logger.info("ShadowTradingEngine: started (balance=%.2f)", self._balance)

    async def stop(self) -> None:
        self._started = False
        logger.info(
            "ShadowTradingEngine: stopped — trades=%d pnl=%.2f",
            len(self._fills),
            self._pnl,
        )

    def on_signal(
        self,
        signal_id: str,
        symbol: str,
        side: str,
        lots: float,
        mid: float,
        stop_loss: float,
        take_profit: float,
    ) -> ShadowFill | None:
        """Execute a signal in paper mode. Returns the simulated fill."""
        if not self._started:
            return None
        if lots <= 0 or mid <= 0:
            return None

        fill_price, slippage_bps = self._simulator.simulate(side, mid, lots)
        fill = ShadowFill(
            signal_id=signal_id,
            symbol=symbol,
            side=side,
            lots=lots,
            requested=mid,
            fill_price=fill_price,
            slippage_bps=slippage_bps,
            timestamp=datetime.now(UTC),
        )
        self._fills.append(fill)
        self._positions.append(
            ShadowPosition(
                symbol=symbol,
                side=side,
                lots=lots,
                entry_price=fill_price,
                stop_loss=stop_loss,
                take_profit=take_profit,
                opened_at=datetime.now(UTC),
                signal_id=signal_id,
            )
        )

        if _PROM_OK:
            _prom_shadow_trades.inc()

        logger.debug(
            "Shadow OPEN %s %s lots=%.3f fill=%.4f slip=%.2fbps",
            side,
            symbol,
            lots,
            fill_price,
            slippage_bps,
        )
        return fill

    def on_tick(self, mid: float) -> None:
        """Update open positions on each tick — check SL/TP."""
        if mid <= 0:
            return
        closed = []
        for pos in self._positions:
            hit_sl = (pos.side == "long" and mid <= pos.stop_loss) or (pos.side == "short" and mid >= pos.stop_loss)
            hit_tp = (pos.side == "long" and mid >= pos.take_profit) or (pos.side == "short" and mid <= pos.take_profit)
            if hit_sl or hit_tp:
                if pos.side == "long":
                    pnl = (mid - pos.entry_price) * pos.lots * 100.0
                else:
                    pnl = (pos.entry_price - mid) * pos.lots * 100.0

                self._pnl += pnl
                self._balance += pnl
                self._equity = self._balance
                self._peak = max(self._peak, self._equity)

                # Mark fill as closed
                for f in self._fills:
                    if f.signal_id == pos.signal_id and not f.closed:
                        f.pnl = pnl
                        f.closed = True
                        f.close_price = mid
                        break

                closed.append(pos)
                logger.debug(
                    "Shadow CLOSE %s %s pnl=%.2f reason=%s",
                    pos.side,
                    pos.symbol,
                    pnl,
                    "TP" if hit_tp else "SL",
                )

        for pos in closed:
            self._positions.remove(pos)

        if _PROM_OK:
            _prom_shadow_pnl.set(self._pnl)
            _prom_shadow_equity.set(self._equity)

    def on_live_close(
        self,
        signal_id: str,
        live_pnl: float,
        live_fill_price: float | None = None,
        live_slippage_bps: float | None = None,
    ) -> None:
        """
        Record a live trade close for paper-vs-live comparison.

        Parameters
        ----------
        signal_id         : Matches the signal_id used in on_signal()
        live_pnl          : Realised PnL of the live trade (USD)
        live_fill_price   : Actual broker fill price (optional)
        live_slippage_bps : Measured live slippage in bps (optional).
                            When provided, enables _slippage_accuracy() R²
                            computation comparing shadow model vs reality.
        """
        self._live_pnl += live_pnl
        self._live_fills += 1

        # Attach live slippage to the matching shadow fill for R² computation
        if live_slippage_bps is not None:
            for f in self._fills:
                if f.signal_id == signal_id:
                    f.live_slippage_bps = live_slippage_bps
                    break

        gap = self._pnl - self._live_pnl
        if _PROM_OK:
            _prom_live_gap.set(gap)
        logger.info(
            "Shadow vs Live: shadow_pnl=%.2f live_pnl=%.2f gap=%.2f slip_r2=%.3f",
            self._pnl,
            self._live_pnl,
            gap,
            self._slippage_accuracy(),
        )

    # ── Diagnostics ───────────────────────────────────────────────────────────

    def health(self) -> dict[str, Any]:
        closed_fills = [f for f in self._fills if f.closed]
        wins = [f for f in closed_fills if f.pnl > 0]
        now = time.time()
        dd = (self._peak - self._equity) / max(self._peak, 1) * 100
        return {
            "started": self._started,
            "uptime_s": round(now - self._start_ts, 1),
            "balance": round(self._balance, 2),
            "equity": round(self._equity, 2),
            "pnl": round(self._pnl, 2),
            "drawdown_pct": round(dd, 3),
            "total_trades": len(self._fills),
            "open_positions": len(self._positions),
            "win_rate": round(len(wins) / max(len(closed_fills), 1), 4),
            "live_pnl": round(self._live_pnl, 2),
            "live_gap_usd": round(self._pnl - self._live_pnl, 2),
            "avg_slippage_bps": round(sum(f.slippage_bps for f in self._fills) / max(len(self._fills), 1), 3),
        }

    def get_comparison_report(self) -> dict[str, Any]:
        """Paper-vs-live comparison report."""
        closed = [f for f in self._fills if f.closed]
        return {
            "shadow_trades": len(closed),
            "shadow_pnl": round(self._pnl, 2),
            "live_trades": self._live_fills,
            "live_pnl": round(self._live_pnl, 2),
            "pnl_gap": round(self._pnl - self._live_pnl, 2),
            "avg_slippage_bps": round(sum(f.slippage_bps for f in self._fills) / max(len(self._fills), 1), 3),
            "slippage_model_accuracy": self._slippage_accuracy(),
        }

    def _slippage_accuracy(self) -> float:
        """
        Measure how well the slippage model predicts real slippage.

        Returns R² of shadow_slippage_bps vs live_slippage_bps over all
        closed fills that have a recorded live_slippage_bps.

        R² = 1 - SS_res / SS_tot
          SS_res = Σ(shadow_i - live_i)²
          SS_tot = Σ(live_i - mean(live))²

        Returns 0.0 if fewer than 2 paired observations are available.
        """
        # Include any fill where live_slippage_bps has been recorded,
        # regardless of whether the shadow position is still open.
        paired = [(f.slippage_bps, f.live_slippage_bps) for f in self._fills if f.live_slippage_bps is not None]
        if len(paired) < 2:
            return 0.0

        _shadow_vals = [p[0] for p in paired]
        live_vals = [p[1] for p in paired]
        mean_live = sum(live_vals) / len(live_vals)

        ss_res = sum((s - lv) ** 2 for s, lv in paired)
        ss_tot = sum((lv - mean_live) ** 2 for lv in live_vals)

        if ss_tot < 1e-12:
            return 1.0  # perfect prediction (zero variance in live)
        return max(0.0, round(1.0 - ss_res / ss_tot, 4))


# ── Module-level singleton ────────────────────────────────────────────────────
shadow_trading_engine = ShadowTradingEngine()

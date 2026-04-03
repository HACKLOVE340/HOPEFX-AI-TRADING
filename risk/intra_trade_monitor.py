# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
risk/intra_trade_monitor.py
============================
IntraTradeMonitor — tick-frequency risk recalculation on open positions.

Runs on every tick while positions are open. Recalculates:
  - Mark-to-market PnL per position
  - Portfolio-level CVaR/ES (Conditional Value-at-Risk / Expected Shortfall)
  - Drawdown from position peak
  - Adverse excursion (MAE) vs maximum favourable excursion (MFE)
  - Regime-shift detection (volatility spike → tighten stops)

Auto-unwind triggers (any one fires immediate close signal):
  1. Position CVaR exceeds INTRA_CVAR_LIMIT_PCT of equity
  2. Single-position drawdown exceeds INTRA_MAX_POSITION_DD_PCT
  3. Portfolio drawdown exceeds INTRA_MAX_PORTFOLIO_DD_PCT
  4. Volatility regime shift: realised vol > INTRA_VOL_SPIKE_MULT × baseline
  5. Data quality drops below INTRA_MIN_DATA_QUALITY (stale/bad ticks)

Architecture
------------
  HopeFXEngine.on_tick()
        │
        └──► IntraTradeMonitor.on_tick(tick, open_positions)
                    │
                    ├── _update_mtm()        — mark positions to market
                    ├── _compute_cvar_es()   — rolling CVaR/ES on returns
                    ├── _check_unwind()      — evaluate all triggers
                    └── emit UnwindSignal    — consumed by SmartRouter
"""

from __future__ import annotations

import logging
import os
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
UTC = timezone.utc
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)

# ── thresholds (env-overridable) ──────────────────────────────────────────────
_CVAR_LIMIT_PCT = float(os.getenv("INTRA_CVAR_LIMIT_PCT", "0.03"))  # 3% equity
_MAX_POS_DD_PCT = float(os.getenv("INTRA_MAX_POSITION_DD_PCT", "0.015"))  # 1.5%
_MAX_PORT_DD_PCT = float(os.getenv("INTRA_MAX_PORTFOLIO_DD_PCT", "0.04"))  # 4%
_VOL_SPIKE_MULT = float(os.getenv("INTRA_VOL_SPIKE_MULT", "3.0"))  # 3× baseline
_MIN_DATA_QUALITY = float(os.getenv("INTRA_MIN_DATA_QUALITY", "0.40"))
_CVAR_CONFIDENCE = float(os.getenv("INTRA_CVAR_CONFIDENCE", "0.95"))
_RETURNS_WINDOW = int(os.getenv("INTRA_RETURNS_WINDOW", "200"))
_VOL_BASELINE_WINDOW = int(os.getenv("INTRA_VOL_BASELINE_WINDOW", "100"))

# ── Prometheus ────────────────────────────────────────────────────────────────
try:
    from prometheus_client import Counter, Gauge

    _prom_unwinds = Counter("hopefx_intra_unwinds_total", "Auto-unwind signals emitted", ["reason"])
    _prom_cvar = Gauge("hopefx_intra_cvar_pct", "Current portfolio CVaR as % equity")
    _prom_port_dd = Gauge("hopefx_intra_portfolio_dd_pct", "Current portfolio drawdown %")
    _prom_vol_ratio = Gauge("hopefx_intra_vol_ratio", "Current vol / baseline vol ratio")
    _PROM_OK = True
except Exception:  # nosec B110 — Prometheus metrics optional
    _PROM_OK = False


@dataclass
class OpenPosition:
    """Snapshot of an open position for intra-trade monitoring."""

    position_id: str
    symbol: str
    side: str  # "long" | "short"
    lots: float
    entry_price: float
    stop_loss: float
    take_profit: float
    opened_at: datetime
    peak_price: float = 0.0  # highest favourable price seen
    mtm_pnl: float = 0.0  # current mark-to-market PnL (USD)

    def __post_init__(self) -> None:
        self.peak_price = self.entry_price


@dataclass
class UnwindSignal:
    """Emitted when a position must be closed immediately."""

    position_id: str
    symbol: str
    reason: str
    urgency: str  # "immediate" | "next_tick"
    mtm_pnl: float
    triggered_at: datetime = field(default_factory=lambda: datetime.now(UTC))


class IntraTradeMonitor:
    """
    Tick-frequency intra-trade risk monitor with auto-unwind.

    Usage
    -----
        monitor = IntraTradeMonitor(equity=10_000.0)
        monitor.on_open(position)

        # On every tick:
        unwinds = monitor.on_tick(mid=2351.0, data_quality=0.95)
        for signal in unwinds:
            await router.close_position(signal.position_id, reason=signal.reason)

        monitor.on_close(position_id="abc", close_price=2355.0)
    """

    def __init__(self, equity: float = 10_000.0) -> None:
        self._equity: float = equity
        self._peak_equity: float = equity
        self._positions: dict[str, OpenPosition] = {}
        self._returns: deque[float] = deque(maxlen=_RETURNS_WINDOW)
        self._vol_baseline: deque[float] = deque(maxlen=_VOL_BASELINE_WINDOW)
        self._last_mid: float = 0.0
        self._tick_count: int = 0
        self._unwind_log: list[UnwindSignal] = []

    # ── Position lifecycle ────────────────────────────────────────────────────

    def on_open(self, position: OpenPosition) -> None:
        self._positions[position.position_id] = position
        logger.debug(
            "IntraMonitor: tracking position %s %s %s lots=%.3f entry=%.4f",
            position.position_id,
            position.side,
            position.symbol,
            position.lots,
            position.entry_price,
        )

    def on_close(self, position_id: str, close_price: float) -> float | None:
        """Remove position and return realised PnL."""
        pos = self._positions.pop(position_id, None)
        if pos is None:
            return None
        if pos.side == "long":
            pnl = (close_price - pos.entry_price) * pos.lots * 100.0
        else:
            pnl = (pos.entry_price - close_price) * pos.lots * 100.0
        self._equity += pnl
        self._peak_equity = max(self._peak_equity, self._equity)
        return pnl

    def update_equity(self, equity: float) -> None:
        self._equity = equity
        self._peak_equity = max(self._peak_equity, equity)

    # ── Tick processing ───────────────────────────────────────────────────────

    def on_tick(
        self,
        mid: float,
        data_quality: float = 1.0,
    ) -> list[UnwindSignal]:
        """
        Process a tick. Returns list of UnwindSignals (empty if all clear).

        Called on every validated tick from the orchestrator.
        """
        if mid <= 0:
            return []

        self._tick_count += 1

        # Track returns for CVaR
        if self._last_mid > 0:
            ret = (mid - self._last_mid) / self._last_mid
            self._returns.append(ret)
            self._vol_baseline.append(abs(ret))
        self._last_mid = mid

        if not self._positions:
            return []

        # Update MTM on all positions
        self._update_mtm(mid)

        # Compute portfolio-level metrics
        cvar_pct = self._compute_cvar_pct()
        port_dd = self._portfolio_drawdown()
        vol_ratio = self._vol_spike_ratio()

        if _PROM_OK:
            _prom_cvar.set(cvar_pct * 100)
            _prom_port_dd.set(port_dd * 100)
            _prom_vol_ratio.set(vol_ratio)

        # Evaluate unwind triggers
        unwinds: list[UnwindSignal] = []

        # 1. Data quality gate
        if data_quality < _MIN_DATA_QUALITY:
            for pos in list(self._positions.values()):
                sig = UnwindSignal(
                    position_id=pos.position_id,
                    symbol=pos.symbol,
                    reason=f"data_quality_too_low:{data_quality:.2f}",
                    urgency="immediate",
                    mtm_pnl=pos.mtm_pnl,
                )
                unwinds.append(sig)
                self._record_unwind(sig)
            return unwinds

        # 2. Portfolio CVaR limit
        if cvar_pct > _CVAR_LIMIT_PCT and len(self._returns) >= 20:
            for pos in list(self._positions.values()):
                sig = UnwindSignal(
                    position_id=pos.position_id,
                    symbol=pos.symbol,
                    reason=f"cvar_limit:{cvar_pct * 100:.2f}%>={_CVAR_LIMIT_PCT * 100:.1f}%",
                    urgency="immediate",
                    mtm_pnl=pos.mtm_pnl,
                )
                unwinds.append(sig)
                self._record_unwind(sig)
            return unwinds

        # 3. Portfolio drawdown limit
        if port_dd > _MAX_PORT_DD_PCT:
            for pos in list(self._positions.values()):
                sig = UnwindSignal(
                    position_id=pos.position_id,
                    symbol=pos.symbol,
                    reason=f"portfolio_dd:{port_dd * 100:.2f}%>={_MAX_PORT_DD_PCT * 100:.1f}%",
                    urgency="immediate",
                    mtm_pnl=pos.mtm_pnl,
                )
                unwinds.append(sig)
                self._record_unwind(sig)
            return unwinds

        # 4. Volatility regime shift
        if vol_ratio > _VOL_SPIKE_MULT and len(self._vol_baseline) >= 20:
            for pos in list(self._positions.values()):
                sig = UnwindSignal(
                    position_id=pos.position_id,
                    symbol=pos.symbol,
                    reason=f"vol_spike:{vol_ratio:.1f}x_baseline",
                    urgency="next_tick",
                    mtm_pnl=pos.mtm_pnl,
                )
                unwinds.append(sig)
                self._record_unwind(sig)
            return unwinds

        # 5. Per-position drawdown
        for pos in list(self._positions.values()):
            pos_dd = self._position_drawdown(pos)
            if pos_dd > _MAX_POS_DD_PCT:
                sig = UnwindSignal(
                    position_id=pos.position_id,
                    symbol=pos.symbol,
                    reason=f"position_dd:{pos_dd * 100:.2f}%>={_MAX_POS_DD_PCT * 100:.1f}%",
                    urgency="immediate",
                    mtm_pnl=pos.mtm_pnl,
                )
                unwinds.append(sig)
                self._record_unwind(sig)

        return unwinds

    # ── Calculations ──────────────────────────────────────────────────────────

    def _update_mtm(self, mid: float) -> None:
        for pos in self._positions.values():
            if pos.side == "long":
                pos.mtm_pnl = (mid - pos.entry_price) * pos.lots * 100.0
                pos.peak_price = max(pos.peak_price, mid)
            else:
                pos.mtm_pnl = (pos.entry_price - mid) * pos.lots * 100.0
                pos.peak_price = min(pos.peak_price, mid)

    def _compute_cvar_pct(self) -> float:
        """
        Compute CVaR (Expected Shortfall) at _CVAR_CONFIDENCE level.

        Uses the historical simulation method on the rolling returns window.
        Returns CVaR as a fraction of equity (positive = loss).
        """
        if len(self._returns) < 10:
            return 0.0
        arr = np.array(self._returns)
        # Total position exposure in USD
        total_exposure = sum(abs(pos.entry_price * pos.lots * 100.0) for pos in self._positions.values())
        if total_exposure <= 0:
            return 0.0
        # Dollar returns on the exposure
        dollar_returns = arr * total_exposure
        # CVaR = mean of worst (1-confidence) fraction
        cutoff = np.percentile(dollar_returns, (1 - _CVAR_CONFIDENCE) * 100)
        tail = dollar_returns[dollar_returns <= cutoff]
        cvar_usd = -float(np.mean(tail)) if len(tail) > 0 else 0.0
        return cvar_usd / max(self._equity, 1.0)

    def _portfolio_drawdown(self) -> float:
        """Current portfolio drawdown from peak equity as a fraction."""
        total_mtm = sum(pos.mtm_pnl for pos in self._positions.values())
        current = self._equity + total_mtm
        return max(0.0, (self._peak_equity - current) / max(self._peak_equity, 1.0))

    def _position_drawdown(self, pos: OpenPosition) -> float:
        """
        Drawdown of a single position as a fraction of equity.

        Measures how far the current MTM PnL has fallen from the peak MTM PnL,
        expressed as a fraction of current equity. Capped at 1.0.
        """
        if pos.side == "long":
            peak_pnl = (pos.peak_price - pos.entry_price) * pos.lots * 100.0
        else:
            peak_pnl = (pos.entry_price - pos.peak_price) * pos.lots * 100.0
        # Only measure drawdown when we had a profit to give back
        if peak_pnl <= 0:
            return 0.0
        drawdown_usd = peak_pnl - pos.mtm_pnl
        if drawdown_usd <= 0:
            return 0.0
        return min(1.0, drawdown_usd / max(self._equity, 1.0))

    def _vol_spike_ratio(self) -> float:
        """Current realised vol / baseline vol ratio."""
        if len(self._vol_baseline) < 20:
            return 1.0
        arr = np.array(self._vol_baseline)
        baseline = float(np.mean(arr[:-5])) if len(arr) > 5 else float(np.mean(arr))
        current = float(np.mean(arr[-5:])) if len(arr) >= 5 else baseline
        return current / max(baseline, 1e-10)

    def _record_unwind(self, sig: UnwindSignal) -> None:
        self._unwind_log.append(sig)
        if len(self._unwind_log) > 500:
            self._unwind_log = self._unwind_log[-250:]
        if _PROM_OK:
            _prom_unwinds.labels(reason=sig.reason.split(":")[0]).inc()
        logger.warning(
            "INTRA-TRADE UNWIND [%s] pos=%s reason=%s mtm=%.2f",
            sig.urgency,
            sig.position_id,
            sig.reason,
            sig.mtm_pnl,
        )

    # ── Diagnostics ───────────────────────────────────────────────────────────

    def snapshot(self) -> dict[str, Any]:
        return {
            "equity": round(self._equity, 2),
            "peak_equity": round(self._peak_equity, 2),
            "open_positions": len(self._positions),
            "portfolio_dd_pct": round(self._portfolio_drawdown() * 100, 3),
            "cvar_pct": round(self._compute_cvar_pct() * 100, 3),
            "vol_ratio": round(self._vol_spike_ratio(), 3),
            "tick_count": self._tick_count,
            "total_unwinds": len(self._unwind_log),
            "positions": {
                pid: {
                    "side": p.side,
                    "lots": p.lots,
                    "entry": p.entry_price,
                    "mtm_pnl": round(p.mtm_pnl, 2),
                    "peak_price": p.peak_price,
                }
                for pid, p in self._positions.items()
            },
        }

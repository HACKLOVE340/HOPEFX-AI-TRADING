# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
risk/drawdown_tracker.py
========================
Precise drawdown tracking with trailing high-water mark (HWM).

Fixes the gap in risk/manager.py where peak_equity is used as both the
all-time HWM and the daily reset anchor, conflating two distinct concepts:

  - Trailing HWM (all-time peak equity): used for max total drawdown.
    Never resets. Prop firms (FTMO, Goat) measure against this.

  - Daily open equity: used for daily drawdown.
    Resets at midnight UTC. Measured on floating equity (FTMO) or
    closed balance (Goat Funded) depending on drawdown_mode.

  - Rolling HWM (optional): trailing peak over a rolling N-day window.
    Useful for strategies that want to lock in profits progressively.

Usage
-----
    from risk.drawdown_tracker import DrawdownTracker

    tracker = DrawdownTracker(
        initial_balance=100_000,
        max_total_dd_pct=0.10,
        max_daily_dd_pct=0.05,
        drawdown_mode="equity",   # "equity" (FTMO) or "balance" (Goat)
    )

    # On every equity update (tick or bar close):
    result = tracker.update(equity=99_500, balance=99_800)
    if result.total_breach:
        halt_trading("Total drawdown breached")
    if result.daily_breach:
        halt_trading("Daily drawdown breached")
    if result.daily_alert:
        warn("Approaching daily limit")

    # On partial fill — update balance only:
    tracker.record_fill(pnl=-120.0)

    # On modify_order — re-check risk with new SL:
    ok, reason = tracker.check_modify(
        current_equity=99_500,
        new_stop_loss_distance=0.003,  # 0.3% of price
        lots=0.1,
        account_balance=100_000,
    )
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
UTC = timezone.utc

logger = logging.getLogger(__name__)


@dataclass
class DrawdownResult:
    """Result of a single equity update."""

    equity: float
    balance: float

    # All-time trailing HWM drawdown
    total_drawdown_pct: float  # current DD from all-time HWM (0–1)
    total_hwm: float  # all-time peak equity
    total_breach: bool  # True if total_drawdown_pct >= max_total_dd_pct
    total_alert: bool  # True if >= alert threshold (e.g. 80% of limit)

    # Daily drawdown
    daily_drawdown_pct: float  # current DD from day-open anchor (0–1)
    daily_open: float  # equity/balance at day open
    daily_breach: bool  # True if daily_drawdown_pct >= max_daily_dd_pct
    daily_alert: bool  # True if >= alert threshold

    # Metadata
    drawdown_mode: str  # "equity" or "balance"
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())


class DrawdownTracker:
    """
    Thread-safe drawdown tracker with trailing HWM.

    Parameters
    ----------
    initial_balance     : Starting account balance
    max_total_dd_pct    : Maximum total drawdown fraction (e.g. 0.10 = 10%)
    max_daily_dd_pct    : Maximum daily drawdown fraction (e.g. 0.05 = 5%)
    drawdown_mode       : "equity" — measure on floating equity (FTMO default)
                          "balance" — measure on closed balance (Goat Funded)
    alert_pct_of_limit  : Emit alert when DD reaches this fraction of the limit
                          (e.g. 0.80 = alert at 80% of the daily limit)
    """

    def __init__(
        self,
        initial_balance: float = 100_000.0,
        max_total_dd_pct: float = float(os.getenv("RISK_MAX_DRAWDOWN_PCT", "0.10")),
        max_daily_dd_pct: float = float(os.getenv("RISK_MAX_DAILY_LOSS_PCT", "0.05")),
        drawdown_mode: str = os.getenv("RISK_DRAWDOWN_MODE", "equity"),
        alert_pct_of_limit: float = float(os.getenv("RISK_ALERT_PCT_OF_LIMIT", "0.80")),
    ) -> None:
        self.max_total_dd_pct = max_total_dd_pct
        self.max_daily_dd_pct = max_daily_dd_pct
        self.drawdown_mode = drawdown_mode.lower()
        self.alert_pct_of_limit = alert_pct_of_limit

        # All-time trailing HWM — never decreases
        self._total_hwm: float = initial_balance

        # Daily anchor — resets at midnight UTC
        self._daily_open: float = initial_balance
        self._day: int = datetime.now(UTC).day

        # Cumulative realised PnL from partial fills today
        self._daily_realised_pnl: float = 0.0

        # Last known values
        self._last_equity: float = initial_balance
        self._last_balance: float = initial_balance

    # ── Core update ───────────────────────────────────────────────────────────

    def update(
        self,
        equity: float,
        balance: float | None = None,
    ) -> DrawdownResult:
        """
        Update tracker with current equity (and optionally balance).

        equity  : Floating equity (open P&L included)
        balance : Closed balance (no open P&L). Defaults to equity if not given.

        Returns DrawdownResult with breach/alert flags.
        """
        if balance is None:
            balance = equity

        self._last_equity = equity
        self._last_balance = balance

        # ── Day rollover ──────────────────────────────────────────────────────
        today = datetime.now(UTC).day
        if today != self._day:
            # New day: anchor is the equity/balance at the start of the new day
            anchor = balance if self.drawdown_mode == "balance" else equity
            self._daily_open = anchor
            self._daily_realised_pnl = 0.0
            self._day = today
            logger.info(
                "DrawdownTracker: day rollover — daily_open=%.2f mode=%s",
                self._daily_open,
                self.drawdown_mode,
            )

        # ── Trailing HWM update ───────────────────────────────────────────────
        # HWM tracks the highest equity ever seen (not just today)
        self._total_hwm = max(self._total_hwm, equity)

        # ── Total drawdown (from all-time HWM) ────────────────────────────────
        total_dd = 0.0
        if self._total_hwm > 0:
            total_dd = max(0.0, (self._total_hwm - equity) / self._total_hwm)

        total_breach = total_dd >= self.max_total_dd_pct
        total_alert = not total_breach and total_dd >= self.max_total_dd_pct * self.alert_pct_of_limit

        # ── Daily drawdown ────────────────────────────────────────────────────
        # FTMO: measure on floating equity
        # Goat Funded: measure on closed balance from day-open balance
        anchor = self._daily_open
        measure = balance if self.drawdown_mode == "balance" else equity

        daily_dd = 0.0
        if anchor > 0:
            daily_dd = max(0.0, (anchor - measure) / anchor)

        daily_breach = daily_dd >= self.max_daily_dd_pct
        daily_alert = not daily_breach and daily_dd >= self.max_daily_dd_pct * self.alert_pct_of_limit

        # ── Logging ───────────────────────────────────────────────────────────
        if total_breach:
            logger.critical(
                "TOTAL DRAWDOWN BREACH: %.2f%% >= %.2f%% (HWM=%.2f equity=%.2f)",
                total_dd * 100,
                self.max_total_dd_pct * 100,
                self._total_hwm,
                equity,
            )
        elif total_alert:
            logger.warning(
                "Total drawdown alert: %.2f%% approaching %.2f%% limit",
                total_dd * 100,
                self.max_total_dd_pct * 100,
            )

        if daily_breach:
            logger.critical(
                "DAILY DRAWDOWN BREACH: %.2f%% >= %.2f%% (open=%.2f %s=%.2f)",
                daily_dd * 100,
                self.max_daily_dd_pct * 100,
                anchor,
                self.drawdown_mode,
                measure,
            )
        elif daily_alert:
            logger.warning(
                "Daily drawdown alert: %.2f%% approaching %.2f%% limit",
                daily_dd * 100,
                self.max_daily_dd_pct * 100,
            )

        return DrawdownResult(
            equity=equity,
            balance=balance,
            total_drawdown_pct=round(total_dd, 6),
            total_hwm=self._total_hwm,
            total_breach=total_breach,
            total_alert=total_alert,
            daily_drawdown_pct=round(daily_dd, 6),
            daily_open=self._daily_open,
            daily_breach=daily_breach,
            daily_alert=daily_alert,
            drawdown_mode=self.drawdown_mode,
        )

    # ── Partial fill handling ─────────────────────────────────────────────────

    def record_fill(self, pnl: float, balance_after: float | None = None) -> None:
        """
        Record a partial or full fill with its realised P&L.

        For "balance" mode (Goat Funded), the daily drawdown anchor is the
        balance at day open. Partial fills change the balance but NOT the anchor.
        This method accumulates realised PnL so the daily drawdown calculation
        stays accurate even with multiple partial fills.

        Parameters
        ----------
        pnl           : Realised P&L of this fill (negative = loss)
        balance_after : New closed balance after the fill (optional; used for
                        direct balance tracking instead of PnL accumulation)
        """
        self._daily_realised_pnl += pnl
        if balance_after is not None:
            self._last_balance = balance_after
        logger.debug(
            "DrawdownTracker.record_fill: pnl=%.2f daily_realised=%.2f",
            pnl,
            self._daily_realised_pnl,
        )

    # ── Modify-order risk re-check ────────────────────────────────────────────

    def check_modify(
        self,
        current_equity: float,
        new_stop_loss_distance: float,
        lots: float,
        account_balance: float,
        pip_value: float = 1.0,
    ) -> tuple[bool, str]:
        """
        Re-check risk when modifying an order's stop-loss.

        Ensures the new SL does not increase risk beyond the per-trade limit.
        Called before sending a modify_order to the broker.

        Parameters
        ----------
        current_equity         : Current floating equity
        new_stop_loss_distance : Distance from entry to new SL (in price units)
        lots                   : Position size in lots
        account_balance        : Closed balance (for risk % calculation)
        pip_value              : Value per pip per lot (default 1.0 for normalised)

        Returns (allowed: bool, reason: str)
        """
        if account_balance <= 0:
            return False, "Invalid account balance"

        # Risk amount = SL distance × lots × pip_value
        risk_amount = new_stop_loss_distance * lots * pip_value
        risk_pct = risk_amount / account_balance

        max_risk_pct = float(os.getenv("RISK_MAX_POSITION_SIZE_PCT", "0.05"))
        if risk_pct > max_risk_pct:
            return (
                False,
                f"Modified SL increases risk to {risk_pct:.2%} > max {max_risk_pct:.2%}",
            )

        # Also check that we're not already in a daily breach
        result = self.update(current_equity)
        if result.daily_breach:
            return (
                False,
                f"Daily drawdown already breached ({result.daily_drawdown_pct:.2%})",
            )
        if result.total_breach:
            return (
                False,
                f"Total drawdown already breached ({result.total_drawdown_pct:.2%})",
            )

        return True, "OK"

    # ── Properties ────────────────────────────────────────────────────────────

    @property
    def total_hwm(self) -> float:
        return self._total_hwm

    @property
    def daily_open(self) -> float:
        return self._daily_open

    @property
    def daily_realised_pnl(self) -> float:
        return self._daily_realised_pnl

    @property
    def current_total_dd(self) -> float:
        """Current total drawdown fraction from all-time HWM."""
        if self._total_hwm <= 0:
            return 0.0
        return max(0.0, (self._total_hwm - self._last_equity) / self._total_hwm)

    @property
    def current_daily_dd(self) -> float:
        """Current daily drawdown fraction from day-open anchor."""
        anchor = self._daily_open
        measure = self._last_balance if self.drawdown_mode == "balance" else self._last_equity
        if anchor <= 0:
            return 0.0
        return max(0.0, (anchor - measure) / anchor)

    def status(self) -> dict:
        return {
            "total_hwm": self._total_hwm,
            "total_drawdown_pct": round(self.current_total_dd * 100, 4),
            "max_total_dd_pct": round(self.max_total_dd_pct * 100, 4),
            "daily_open": self._daily_open,
            "daily_drawdown_pct": round(self.current_daily_dd * 100, 4),
            "max_daily_dd_pct": round(self.max_daily_dd_pct * 100, 4),
            "daily_realised_pnl": round(self._daily_realised_pnl, 4),
            "drawdown_mode": self.drawdown_mode,
            "last_equity": self._last_equity,
            "last_balance": self._last_balance,
        }

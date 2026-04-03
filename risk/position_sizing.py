# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
Position Sizing

Provides ATR-based, fixed-risk, and Kelly-criterion position sizing.
"""

from __future__ import annotations

from decimal import Decimal


class PositionSizer:
    """
    Calculate position sizes using configurable methods.

    Methods
    -------
    atr       : risk a fixed % of equity per ATR unit
    fixed     : fixed lot size
    kelly     : fractional Kelly based on win-rate / payoff
    percent   : fixed % of equity divided by stop distance
    """

    # Default parameters
    RISK_PCT = Decimal("0.01")  # 1 % of equity per trade
    MAX_LOTS = Decimal(100)  # hard cap

    def __init__(
        self,
        method: str = "atr",
        risk_pct: float = 0.01,
        max_lots: float = 100.0,
    ):
        self.method = method.lower()
        self.risk_pct = Decimal(str(risk_pct))
        self.max_lots = Decimal(str(max_lots))

    # ── Public API ────────────────────────────────────────────────────────────

    def calculate_size(
        self,
        account,
        entry_price: Decimal,
        atr: Decimal | None = None,
        stop_distance: Decimal | None = None,
        win_rate: float | None = None,
        payoff_ratio: float | None = None,
    ) -> Decimal:
        """
        Return position size in lots, capped at self.max_lots.

        Parameters
        ----------
        account       : Account domain model (must have .equity or .balance)
        entry_price   : Trade entry price
        atr           : Average True Range (required for 'atr' method)
        stop_distance : Distance to stop in price units (optional override)
        win_rate      : Historical win rate 0-1 (required for 'kelly')
        payoff_ratio  : avg_win / avg_loss (required for 'kelly')
        """
        equity = getattr(account, "equity", None) or getattr(
            account,
            "balance",
            Decimal(0),
        )

        if self.method == "atr":
            size = self._atr_size(equity, entry_price, atr or Decimal(1))
        elif self.method == "kelly":
            size = self._kelly_size(
                equity,
                entry_price,
                win_rate or 0.5,
                payoff_ratio or 1.0,
            )
        elif self.method == "percent":
            dist = stop_distance or (entry_price * Decimal("0.01"))
            size = self._percent_size(equity, dist)
        else:  # fixed
            size = Decimal(1)

        return min(size, self.max_lots)

    # ── Private helpers ───────────────────────────────────────────────────────

    def _atr_size(self, equity: Decimal, entry_price: Decimal, atr: Decimal) -> Decimal:
        """Risk risk_pct of equity per 1-ATR adverse move."""
        if atr <= 0 or entry_price <= 0:
            return Decimal(0)
        risk_amount = equity * self.risk_pct
        # 1 lot = 1 unit; stop = 1 ATR
        size = risk_amount / atr
        return max(Decimal(0), size)

    def _kelly_size(
        self,
        equity: Decimal,
        entry_price: Decimal,
        win_rate: float,
        payoff_ratio: float,
    ) -> Decimal:
        """Half-Kelly criterion."""
        if payoff_ratio <= 0:
            return Decimal(0)
        kelly = win_rate - (1 - win_rate) / payoff_ratio
        half_kelly = max(0.0, kelly * 0.5)
        risk_amount = equity * Decimal(str(half_kelly))
        if entry_price <= 0:
            return Decimal(0)
        return risk_amount / entry_price

    def _percent_size(self, equity: Decimal, stop_distance: Decimal) -> Decimal:
        """Risk risk_pct of equity over stop_distance."""
        if stop_distance <= 0:
            return Decimal(0)
        return (equity * self.risk_pct) / stop_distance

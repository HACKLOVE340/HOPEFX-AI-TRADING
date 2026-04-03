# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# AGPL-3.0 — Share all modifications
"""
execution/market_impact.py
==========================
Almgren-Chriss (2001) market impact model for realistic fill simulation.

The model decomposes total market impact into:
  - Temporary impact: price concession paid at execution time, decays after fill.
  - Permanent impact: lasting price shift from information leakage.

Reference: Almgren & Chriss, "Optimal Execution of Portfolio Transactions",
           Journal of Risk, 2001.

Usage
-----
    from execution.market_impact import AlmgrenChrissModel, FillSimulator

    model = AlmgrenChrissModel()

    # Estimate impact for a 100-lot order in a 10,000 ADV market
    impact = model.estimate(
        order_size=100,
        adv=10_000,
        volatility_daily=0.012,   # 1.2% daily vol (gold ~1%)
        spread_bps=3.0,
        price=2000.0,
    )
    # impact.total_cost_usd, impact.slippage_bps, impact.fill_price

    # Backtest fill simulation (replaces optimistic signal-price fills)
    sim = FillSimulator()
    fill = sim.simulate_fill(
        signal_price=2000.0,
        side="BUY",
        quantity=1.0,
        bar_high=2002.0,
        bar_low=1998.0,
        bar_volume=5000.0,
        adv=10_000.0,
        volatility_daily=0.012,
    )
"""

from __future__ import annotations

import logging
import math
import os
from dataclasses import dataclass
from typing import Literal

logger = logging.getLogger(__name__)

# ── Model parameters (env-overridable) ────────────────────────────────────────
# Almgren-Chriss: temporary impact coefficient η (eta)
# Empirical range: 0.1–0.5 for liquid instruments; 0.3 is a conservative default.
_ETA = float(os.getenv("AC_ETA", "0.3"))

# Permanent impact coefficient γ (gamma)
# Typically 0.5–1.0 × η; 0.1 is conservative for FX/gold.
_GAMMA = float(os.getenv("AC_GAMMA", "0.1"))

# Participation rate cap: max fraction of ADV per order (prevents unrealistic fills)
_MAX_PARTICIPATION = float(os.getenv("AC_MAX_PARTICIPATION", "0.10"))

# Minimum spread contribution to slippage (bps)
_MIN_SPREAD_BPS = float(os.getenv("AC_MIN_SPREAD_BPS", "1.0"))

# Queue position factor: fraction of spread added for queue position uncertainty
_QUEUE_FACTOR = float(os.getenv("AC_QUEUE_FACTOR", "0.5"))


@dataclass
class ImpactEstimate:
    """Result of an Almgren-Chriss impact calculation."""

    order_size: float
    adv: float
    participation_rate: float  # order_size / adv
    volatility_daily: float
    spread_bps: float
    price: float

    # Impact components (all in bps of price)
    temporary_impact_bps: float
    permanent_impact_bps: float
    spread_cost_bps: float
    queue_cost_bps: float

    @property
    def total_impact_bps(self) -> float:
        return self.temporary_impact_bps + self.permanent_impact_bps + self.spread_cost_bps + self.queue_cost_bps

    @property
    def total_cost_usd(self) -> float:
        """Total impact cost in USD for this order."""
        return self.order_size * self.price * self.total_impact_bps / 10_000

    @property
    def slippage_bps(self) -> float:
        """Alias for total_impact_bps — used by callers expecting 'slippage'."""
        return self.total_impact_bps

    def fill_price(self, side: Literal["BUY", "SELL"]) -> float:
        """
        Adjusted fill price after applying total impact.

        BUY orders pay more (positive slippage).
        SELL orders receive less (negative slippage).
        """
        impact_fraction = self.total_impact_bps / 10_000
        if side == "BUY":
            return self.price * (1 + impact_fraction)
        return self.price * (1 - impact_fraction)


class AlmgrenChrissModel:
    """
    Almgren-Chriss (2001) market impact model.

    Temporary impact (η model):
        I_temp = η × σ × sqrt(X / ADV)

    where:
        η     = temporary impact coefficient (default 0.3)
        σ     = daily volatility (fraction)
        X     = order size (units)
        ADV   = average daily volume (units)

    Permanent impact (γ model):
        I_perm = γ × σ × (X / ADV)

    Spread cost:
        I_spread = spread_bps / 2   (half-spread per side)

    Queue position uncertainty:
        I_queue = queue_factor × spread_bps / 2

    All components are in basis points (bps) of price.
    """

    def __init__(
        self,
        eta: float = _ETA,
        gamma: float = _GAMMA,
        max_participation: float = _MAX_PARTICIPATION,
        queue_factor: float = _QUEUE_FACTOR,
    ) -> None:
        self.eta = eta
        self.gamma = gamma
        self.max_participation = max_participation
        self.queue_factor = queue_factor

    def estimate(
        self,
        order_size: float,
        adv: float,
        volatility_daily: float,
        spread_bps: float,
        price: float,
    ) -> ImpactEstimate:
        """
        Estimate total market impact for an order.

        Parameters
        ----------
        order_size      : Order size in units (lots, shares, oz, etc.)
        adv             : Average daily volume in same units as order_size.
                          Use 0 to skip volume-based impact (spread-only mode).
        volatility_daily: Daily return volatility as a fraction (e.g. 0.012 = 1.2%).
        spread_bps      : Bid-ask spread in basis points.
        price           : Current mid price.

        Returns
        -------
        ImpactEstimate with all impact components in bps.
        """
        if adv <= 0:
            # No volume data — fall back to spread-only model
            participation_rate = 0.0
            temp_bps = 0.0
            perm_bps = 0.0
        else:
            participation_rate = min(order_size / adv, self.max_participation)

            # Temporary impact: η × σ × sqrt(participation)
            # Converted to bps: × 10,000
            temp_bps = self.eta * volatility_daily * math.sqrt(participation_rate) * 10_000

            # Permanent impact: γ × σ × participation
            perm_bps = self.gamma * volatility_daily * participation_rate * 10_000

        # Spread cost: half-spread per side (we pay the spread on entry)
        spread_cost_bps = max(spread_bps / 2.0, _MIN_SPREAD_BPS)

        # Queue position uncertainty: fraction of half-spread
        queue_cost_bps = self.queue_factor * spread_cost_bps

        return ImpactEstimate(
            order_size=order_size,
            adv=adv,
            participation_rate=participation_rate,
            volatility_daily=volatility_daily,
            spread_bps=spread_bps,
            price=price,
            temporary_impact_bps=temp_bps,
            permanent_impact_bps=perm_bps,
            spread_cost_bps=spread_cost_bps,
            queue_cost_bps=queue_cost_bps,
        )


@dataclass
class SimulatedFill:
    """Result of a simulated fill."""

    signal_price: float  # Price at signal generation time
    fill_price: float  # Actual simulated fill price
    slippage_bps: float  # Total slippage in bps
    slippage_usd: float  # Total slippage in USD
    partial_fill: bool  # True if order was partially filled
    fill_quantity: float  # Actual filled quantity
    requested_quantity: float
    impact_estimate: ImpactEstimate | None = None
    notes: str = ""


class FillSimulator:
    """
    Realistic fill simulator for backtesting.

    Replaces the optimistic "fill at signal price" assumption with:
    1. Almgren-Chriss market impact (temporary + permanent + spread + queue)
    2. Partial fill logic: if order size > bar volume × participation cap,
       only a fraction is filled.
    3. Price feasibility check: fill price must be within the bar's high-low range.

    This produces backtest P&L that is closer to live performance.
    """

    def __init__(self, model: AlmgrenChrissModel | None = None) -> None:
        self.model = model or AlmgrenChrissModel()

    def simulate_fill(
        self,
        signal_price: float,
        side: Literal["BUY", "SELL"],
        quantity: float,
        bar_high: float,
        bar_low: float,
        bar_volume: float,
        adv: float,
        volatility_daily: float,
        spread_bps: float = 3.0,
    ) -> SimulatedFill:
        """
        Simulate a realistic fill for a backtest order.

        Parameters
        ----------
        signal_price    : Mid price at signal generation time.
        side            : "BUY" or "SELL".
        quantity        : Requested order size.
        bar_high        : Bar high (used for price feasibility check).
        bar_low         : Bar low (used for price feasibility check).
        bar_volume      : Bar volume (used for partial fill logic).
        adv             : Average daily volume.
        volatility_daily: Daily return volatility (fraction).
        spread_bps      : Bid-ask spread in bps.

        Returns
        -------
        SimulatedFill with fill_price, slippage, and partial fill flag.
        """
        # ── Partial fill logic ────────────────────────────────────────────────
        # If the order exceeds the bar's available liquidity, only fill the
        # portion that can be absorbed without moving the market excessively.
        max_fillable = bar_volume * self.model.max_participation
        partial_fill = quantity > max_fillable
        fill_quantity = min(quantity, max_fillable) if partial_fill else quantity

        # ── Market impact estimate ────────────────────────────────────────────
        impact = self.model.estimate(
            order_size=fill_quantity,
            adv=adv,
            volatility_daily=volatility_daily,
            spread_bps=spread_bps,
            price=signal_price,
        )

        raw_fill = impact.fill_price(side)

        # ── Price feasibility: clamp to bar range ─────────────────────────────
        # A fill cannot occur outside the bar's high-low range.
        # This prevents fills at prices the market never traded.
        # BUY fills at or below bar high; SELL fills at or above bar low
        fill_price = min(raw_fill, bar_high) if side == "BUY" else max(raw_fill, bar_low)

        slippage_usd = abs(fill_price - signal_price) * fill_quantity
        slippage_bps = abs(fill_price - signal_price) / signal_price * 10_000

        notes = ""
        if partial_fill:
            notes = (
                f"Partial fill: {fill_quantity:.2f}/{quantity:.2f} units "
                f"(bar volume {bar_volume:.0f}, participation cap "
                f"{self.model.max_participation:.0%})"
            )

        return SimulatedFill(
            signal_price=signal_price,
            fill_price=fill_price,
            slippage_bps=slippage_bps,
            slippage_usd=slippage_usd,
            partial_fill=partial_fill,
            fill_quantity=fill_quantity,
            requested_quantity=quantity,
            impact_estimate=impact,
            notes=notes,
        )

    def simulate_fills_batch(
        self,
        signals: list[dict],
        adv: float,
        volatility_daily: float,
        spread_bps: float = 3.0,
    ) -> list[SimulatedFill]:
        """
        Simulate fills for a batch of signals.

        Each signal dict must have keys:
            signal_price, side, quantity, bar_high, bar_low, bar_volume
        """
        return [
            self.simulate_fill(
                signal_price=s["signal_price"],
                side=s["side"],
                quantity=s["quantity"],
                bar_high=s["bar_high"],
                bar_low=s["bar_low"],
                bar_volume=s["bar_volume"],
                adv=adv,
                volatility_daily=volatility_daily,
                spread_bps=spread_bps,
            )
            for s in signals
        ]


# ── Module-level singleton ────────────────────────────────────────────────────

_fill_simulator: FillSimulator | None = None


def get_fill_simulator() -> FillSimulator:
    """Return the module-level FillSimulator singleton."""
    global _fill_simulator
    if _fill_simulator is None:
        _fill_simulator = FillSimulator()
    return _fill_simulator

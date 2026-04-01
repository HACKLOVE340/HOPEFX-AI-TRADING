# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
risk/liquidity_var.py
======================
Liquidity-Adjusted Value-at-Risk (LaVaR).

Extends standard VaR to account for position illiquidity:
  - Endogenous liquidity: bid-ask spread, market impact
  - Exogenous liquidity: time to liquidation (liquidation horizon)

Based on Bangia et al. (1999) and Jarrow & Protter (2005).

LaVaR = VaR + Liquidity Cost Component
      = VaR + (spread / 2) * position_size * confidence_adjustment
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field

import numpy as np
from scipy.stats import norm

logger = logging.getLogger(__name__)


@dataclass
class LaVaRResult:
    """Result of Liquidity-Adjusted VaR calculation."""
    lavar: float
    """LaVaR in base currency (USD)."""
    var_market: float
    """Standard market VaR component."""
    liquidity_cost: float
    """Liquidity add-on in USD."""
    liquidation_horizon: int
    """Estimated days to liquidate position."""
    avg_daily_spread_pct: float
    """Average bid-ask spread as % of price."""
    confidence: float
    """Confidence level used."""
    position_value: float
    """Mark-to-market value of position."""


class LiquidityAdjustedVaR:
    """
    Liquidity-Adjusted Value-at-Risk calculator.

    Incorporates both exogenous liquidity (spread cost) and
    endogenous liquidity (market impact of unwinding).
    """

    def __init__(
        self,
        confidence: float = 0.99,
        frequency: int = 252,
    ) -> None:
        if not 0 < confidence < 1:
            raise ValueError("confidence must be in (0, 1)")
        self.confidence = confidence
        self.frequency = frequency

    def calculate(
        self,
        returns: np.ndarray,
        position_value: float,
        avg_spread_pct: float = 0.0002,
        avg_daily_volume_usd: float | None = None,
        liquidation_horizon: int | None = None,
    ) -> LaVaRResult:
        """
        Compute Liquidity-Adjusted VaR.

        Parameters
        ----------
        returns : np.ndarray
            Historical daily P&L returns (fractional, e.g. 0.01 for 1%).
        position_value : float
            Current mark-to-market position value in USD.
        avg_spread_pct : float
            Average bid-ask spread as fraction of price. Default 0.02%.
        avg_daily_volume_usd : float, optional
            Average daily trading volume in USD. Used to estimate liquidation
            horizon. If None, liquidation_horizon must be provided.
        liquidation_horizon : int, optional
            Days needed to liquidate position. If None, estimated from volume.

        Returns
        -------
        LaVaRResult
        """
        r = np.asarray(returns, dtype=float)
        r = r[~np.isnan(r)]

        # Estimate liquidation horizon
        if liquidation_horizon is None:
            if avg_daily_volume_usd and avg_daily_volume_usd > 0:
                # Assume we can trade max 20% of ADV per day without impact
                liq_horizon = max(1, math.ceil(position_value / (0.20 * avg_daily_volume_usd)))
            else:
                liq_horizon = 1
        else:
            liq_horizon = max(1, int(liquidation_horizon))

        # Standard VaR (historical simulation)
        if len(r) < 10:
            z = norm.ppf(self.confidence)
            market_var = abs(position_value) * z * 0.01
        else:
            daily_pnl = r * position_value
            market_var = float(-np.percentile(daily_pnl, (1 - self.confidence) * 100))

        # Scale VaR to liquidation horizon (sqrt-of-time rule as conservative approx)
        if liq_horizon > 1:
            market_var_scaled = market_var * math.sqrt(liq_horizon)
        else:
            market_var_scaled = market_var

        # Liquidity cost = half-spread * position * (1 + confidence adjustment)
        # Additional cost for unwinding: market impact ~ spread * sqrt(liq_horizon)
        spread_cost = (avg_spread_pct / 2.0) * abs(position_value)
        impact_cost = spread_cost * math.sqrt(liq_horizon)
        liquidity_cost = spread_cost + impact_cost

        lavar = market_var_scaled + liquidity_cost

        logger.debug(
            "LaVaR: var=%.2f, liq_cost=%.2f, horizon=%d days, LaVaR=%.2f",
            market_var_scaled, liquidity_cost, liq_horizon, lavar,
        )

        return LaVaRResult(
            lavar=lavar,
            var_market=market_var_scaled,
            liquidity_cost=liquidity_cost,
            liquidation_horizon=liq_horizon,
            avg_daily_spread_pct=avg_spread_pct,
            confidence=self.confidence,
            position_value=position_value,
        )

    def time_scaled_lavar(
        self,
        daily_lavar: LaVaRResult,
        holding_period: int,
    ) -> float:
        """
        Scale a 1-day LaVaR to a multi-day holding period.
        Uses sqrt-of-time for market component, linear for liquidity cost.
        """
        market_scaled = daily_lavar.var_market * math.sqrt(holding_period)
        liq_scaled = daily_lavar.liquidity_cost * holding_period
        return market_scaled + liq_scaled

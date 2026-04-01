# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
ml/capacity.py
===============
Strategy capacity analysis.

Estimates the maximum AUM a strategy can deploy before market impact
erodes its edge. Uses the square-root market impact model.

Produces:
  - Capacity curve: alpha vs AUM
  - Breakeven AUM: where net alpha = 0
  - Optimal AUM: maximises total dollar profit

Reference:
  Grinold, R. & Kahn, R. (2000). Active Portfolio Management.
  Almgren, R. & Chriss, N. (2001). Optimal Execution of Portfolio Transactions.
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import Sequence

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


@dataclass
class CapacityResult:
    """Strategy capacity analysis output."""
    gross_alpha_bps: float
    """Gross alpha in basis points (pre-cost)."""
    breakeven_aum_usd: float
    """AUM at which net alpha reaches zero."""
    optimal_aum_usd: float
    """AUM that maximises total dollar profit."""
    optimal_dollar_profit: float
    """Maximum achievable dollar profit per year."""
    capacity_curve: list[tuple[float, float]]
    """List of (aum_usd, net_alpha_bps) tuples for plotting."""
    avg_daily_volume_usd: float
    """Estimated average daily volume of traded instrument."""
    turnover_per_year: float
    """Estimated annual strategy turnover (fraction of AUM)."""


class CapacityAnalyzer:
    """
    Strategy capacity estimator using square-root market impact model.

    Impact model: market_impact_bps = eta * sqrt(participation_rate)
    where participation_rate = AUM * turnover / (ADV * 252)
    and eta is the market impact coefficient (default 10 bps for gold).
    """

    def __init__(
        self,
        eta: float = 10.0,
        spread_bps: float = 5.0,
    ) -> None:
        """
        Parameters
        ----------
        eta : float
            Market impact coefficient in bps per sqrt(participation). Default 10.
        spread_bps : float
            Round-trip bid-ask spread cost in bps. Default 5.
        """
        self.eta = eta
        self.spread_bps = spread_bps

    def estimate(
        self,
        returns: pd.Series,
        avg_daily_volume_usd: float,
        turnover_per_year: float = 50.0,
        aum_range: tuple[float, float] = (1e4, 1e10),
        n_points: int = 100,
    ) -> CapacityResult:
        """
        Estimate strategy capacity.

        Parameters
        ----------
        returns : pd.Series
            Strategy daily returns (e.g. from backtest).
        avg_daily_volume_usd : float
            Average daily volume of the traded instrument in USD.
        turnover_per_year : float
            Strategy turnover: how many times AUM is turned over annually.
            Default 50 (e.g. 4-day average hold, 250 trading days).
        aum_range : tuple
            (min_aum, max_aum) for capacity curve.
        n_points : int
            Number of points on capacity curve.

        Returns
        -------
        CapacityResult
        """
        r = np.asarray(returns.dropna(), dtype=float)
        if len(r) < 20:
            logger.warning("Capacity: insufficient returns data")
            gross_bps = 0.0
        else:
            # Annualised gross alpha
            ann_return = r.mean() * 252
            gross_bps = ann_return * 10_000  # convert to bps

        adv = max(avg_daily_volume_usd, 1.0)

        aum_min, aum_max = aum_range
        aum_points = np.geomspace(aum_min, aum_max, n_points)
        capacity_curve: list[tuple[float, float]] = []

        for aum in aum_points:
            net_bps = self._net_alpha(gross_bps, aum, adv, turnover_per_year)
            capacity_curve.append((float(aum), float(net_bps)))

        # Find breakeven AUM (net_alpha = 0)
        breakeven = self._find_zero(gross_bps, adv, turnover_per_year, aum_min, aum_max)

        # Optimal AUM = argmax(AUM * net_alpha)
        # d/d(AUM) [AUM * net_alpha] = 0 => analytical solution
        optimal_aum = self._optimal_aum(gross_bps, adv, turnover_per_year)
        optimal_profit = optimal_aum * self._net_alpha(
            gross_bps, optimal_aum, adv, turnover_per_year
        ) / 10_000  # convert bps to fraction, then multiply by AUM

        return CapacityResult(
            gross_alpha_bps=gross_bps,
            breakeven_aum_usd=breakeven,
            optimal_aum_usd=optimal_aum,
            optimal_dollar_profit=optimal_profit,
            capacity_curve=capacity_curve,
            avg_daily_volume_usd=adv,
            turnover_per_year=turnover_per_year,
        )

    def _participation_rate(
        self, aum: float, adv: float, turnover: float
    ) -> float:
        """AUM * annual_turnover / (ADV * 252) = daily traded / ADV."""
        return aum * turnover / (adv * 252)

    def _impact_bps(self, aum: float, adv: float, turnover: float) -> float:
        """Square-root market impact in bps."""
        p = self._participation_rate(aum, adv, turnover)
        return self.eta * math.sqrt(max(p, 0.0)) + self.spread_bps

    def _net_alpha(
        self, gross_bps: float, aum: float, adv: float, turnover: float
    ) -> float:
        """Net alpha in bps after impact and spread costs."""
        return gross_bps - self._impact_bps(aum, adv, turnover)

    def _find_zero(
        self, gross_bps: float, adv: float, turnover: float,
        lo: float, hi: float,
    ) -> float:
        """Binary search for AUM where net_alpha = 0."""
        for _ in range(60):
            mid = (lo + hi) / 2
            if self._net_alpha(gross_bps, mid, adv, turnover) > 0:
                lo = mid
            else:
                hi = mid
        return (lo + hi) / 2

    def _optimal_aum(self, gross_bps: float, adv: float, turnover: float) -> float:
        """
        Analytical optimal AUM: d/d(AUM)[AUM * net_alpha] = 0
        net_alpha = A - eta * sqrt(c * AUM) - spread
        => d/d(AUM)[AUM*net_alpha] = A - spread - 3/2 * eta * sqrt(c*AUM) = 0
        => AUM* = ((A - spread) / (1.5 * eta))^2 / c
        """
        c = turnover / (adv * 252)
        effective = gross_bps - self.spread_bps
        if effective <= 0 or c <= 0:
            return 0.0
        return ((effective / (1.5 * self.eta)) ** 2) / c

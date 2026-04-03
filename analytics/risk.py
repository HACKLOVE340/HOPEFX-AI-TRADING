# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
Risk Analytics
"""

import numpy as np


class RiskAnalyzer:
    """Advanced risk analytics"""

    def calculate_var(
        self,
        portfolio_returns: list[float],
        confidence_level: float = 0.95,
        method: str = "historical",
    ) -> float:
        """Calculate 1-day Value at Risk.

        Returns the loss threshold not exceeded with probability `confidence_level`
        over a **1-day horizon**.

        Multi-day scaling note
        ----------------------
        Extending to a t-day horizon via ``VaR_t = VaR_1 * sqrt(t)`` (the Basel II
        square-root-of-time rule) is only valid when returns are i.i.d. and normally
        distributed.  Real gold/FX returns exhibit fat tails, autocorrelation, and
        volatility clustering — all of which violate this assumption.  For horizons
        beyond 1 day, prefer computing VaR directly from overlapping or
        non-overlapping t-day return windows.  See risk/advanced_analytics.py for
        the full implementation with this caveat documented inline.
        """
        if method == "historical":
            sorted_returns = sorted(portfolio_returns)
            index = int((1 - confidence_level) * len(sorted_returns))
            return sorted_returns[index] if index < len(sorted_returns) else sorted_returns[0]

        # Parametric VaR — assumes normally distributed returns (fat tails not captured)
        mean = np.mean(portfolio_returns)
        std = np.std(portfolio_returns)
        z_score = 1.645 if confidence_level == 0.95 else 2.326
        return mean - z_score * std

    def calculate_cvar(self, portfolio_returns: list[float], confidence_level: float = 0.95) -> float:
        """Calculate Conditional VaR (Expected Shortfall)"""
        var = self.calculate_var(portfolio_returns, confidence_level)
        tail_returns = [r for r in portfolio_returns if r <= var]
        return np.mean(tail_returns) if tail_returns else var

    def risk_attribution(self, portfolio_weights: np.ndarray, covariance_matrix: np.ndarray) -> dict:
        """Calculate risk attribution"""
        portfolio_variance = portfolio_weights.T @ covariance_matrix @ portfolio_weights
        marginal_risk = covariance_matrix @ portfolio_weights

        return {
            "total_risk": float(np.sqrt(portfolio_variance)),
            "marginal_risk": marginal_risk.tolist(),
            "component_risk": (portfolio_weights * marginal_risk).tolist(),
        }

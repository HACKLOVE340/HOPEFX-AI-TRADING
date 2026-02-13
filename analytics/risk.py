"""
Risk Analytics
"""

from typing import List, Dict
from decimal import Decimal
import numpy as np


class RiskAnalyzer:
    """Advanced risk analytics"""

    def calculate_var(
        self,
        portfolio_returns: List[float],
        confidence_level: float = 0.95,
        method: str = 'historical'
    ) -> float:
        """Calculate Value at Risk"""
        if method == 'historical':
            sorted_returns = sorted(portfolio_returns)
            index = int((1 - confidence_level) * len(sorted_returns))
            return sorted_returns[index] if index < len(sorted_returns) else sorted_returns[0]

        # Parametric VaR
        mean = np.mean(portfolio_returns)
        std = np.std(portfolio_returns)
        z_score = 1.645 if confidence_level == 0.95 else 2.326
        return mean - z_score * std

    def calculate_cvar(
        self,
        portfolio_returns: List[float],
        confidence_level: float = 0.95
    ) -> float:
        """Calculate Conditional VaR (Expected Shortfall)"""
        var = self.calculate_var(portfolio_returns, confidence_level)
        tail_returns = [r for r in portfolio_returns if r <= var]
        return np.mean(tail_returns) if tail_returns else var

    def risk_attribution(
        self,
        portfolio_weights: np.ndarray,
        covariance_matrix: np.ndarray
    ) -> Dict:
        """Calculate risk attribution"""
        portfolio_variance = portfolio_weights.T @ covariance_matrix @ portfolio_weights
        marginal_risk = covariance_matrix @ portfolio_weights

        return {
            'total_risk': float(np.sqrt(portfolio_variance)),
            'marginal_risk': marginal_risk.tolist(),
            'component_risk': (portfolio_weights * marginal_risk).tolist()
        }

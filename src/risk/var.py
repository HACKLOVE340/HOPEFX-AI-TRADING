"""Monte Carlo VaR/CVaR calculation."""
from __future__ import annotations

import numpy as np
from decimal import Decimal
from typing import Any

import structlog

logger = structlog.get_logger()


class VaRCalculator:
    """Monte Carlo VaR/CVaR."""
    
    def __init__(self, n_sims: int = 10000, confidence: float = 0.95) -> None:
        self.n_sims = n_sims
        self.confidence = confidence
    
    def calculate(
        self,
        positions: list[dict[str, Any]],
        returns_history: np.ndarray,
        correlation_matrix: np.ndarray | None = None
    ) -> dict[str, Decimal]:
        """Calculate portfolio VaR/CVaR."""
        if len(returns_history) < 30:
            logger.warning("Insufficient history for VaR")
            return {"var": Decimal("0"), "cvar": Decimal("0")}
        
        # Monte Carlo simulation
        simulated_returns = self._monte_carlo_sim(
            returns_history, 
            correlation_matrix
        )
        
        # Calculate P&L distribution
        portfolio_values = self._calculate_portfolio_pnl(
            positions, 
            simulated_returns
        )
        
        # VaR at confidence level
        var_percentile = (1 - self.confidence) * 100
        var = np.percentile(portfolio_values, var_percentile)
        
        # CVaR (Expected Shortfall)
        cvar = np.mean(portfolio_values[portfolio_values <= var])
        
        return {
            "var": Decimal(str(abs(var))),
            "cvar": Decimal(str(abs(cvar))),
            "confidence": self.confidence,
            "sims": self.n_sims,
        }
    
    def _monte_carlo_sim(
        self, 
        returns: np.ndarray, 
        corr: np.ndarray | None
    ) -> np.ndarray:
        """Generate Monte Carlo simulations."""
        mean = np.mean(returns, axis=0)
        std = np.std(returns, axis=0)
        
        if corr is not None:
            # Correlated random variables
            L = np.linalg.cholesky(corr)
            uncorrelated = np.random.standard_normal((self.n_sims, len(mean)))
            correlated = uncorrelated @ L.T
            simulated = mean + std * correlated
        else:
            simulated = np.random.normal(
                mean, std, (self.n_sims, len(mean))
            )
        
        return simulated
    
    def _calculate_portfolio_pnl(
        self, 
        positions: list[dict], 
        sim_returns: np.ndarray
    ) -> np.ndarray:
        """Calculate portfolio P&L from simulated returns."""
        notionals = np.array([p["notional"] for p in positions])
        directions = np.array([1 if p["side"] == "LONG" else -1 for p in positions])
        
        # Portfolio returns
        weighted_returns = sim_returns * notionals * directions
        portfolio_pnl = np.sum(weighted_returns, axis=1)
        
        return portfolio_pnl

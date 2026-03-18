"""
Monte Carlo VaR/CVaR with historical and parametric methods.
"""

import numpy as np
from scipy import stats

from src.core.config import settings


class RiskMetrics:
    """
    Institutional risk metrics calculation.
    """
    
    def __init__(
        self,
        confidence: float = 0.95,
        horizon_days: int = 1,
        simulations: int = 10000
    ):
        self.confidence = confidence
        self.horizon = horizon_days
        self.simulations = simulations
    
    def calculate_var(
        self,
        returns: np.ndarray,
        method: str = "historical",
        portfolio_value: float = 1.0
    ) -> dict[str, float]:
        """
        Calculate Value at Risk.
        """
        if method == "historical":
            var = self._historical_var(returns)
        elif method == "parametric":
            var = self._parametric_var(returns)
        elif method == "monte_carlo":
            var = self._monte_carlo_var(returns)
        else:
            raise ValueError(f"Unknown VaR method: {method}")
        
        # Scale to horizon
        var = var * np.sqrt(self.horizon)
        
        return {
            "var_absolute": var * portfolio_value,
            "var_percentage": var * 100,
            "confidence": self.confidence,
            "horizon_days": self.horizon,
            "method": method
        }
    
    def _historical_var(self, returns: np.ndarray) -> float:
        """Historical simulation VaR."""
        return np.percentile(returns, (1 - self.confidence) * 100)
    
    def _parametric_var(self, returns: np.ndarray) -> float:
        """Parametric (variance-covariance) VaR."""
        mean = np.mean(returns)
        std = np.std(returns)
        z_score = stats.norm.ppf(1 - self.confidence)
        return mean - z_score * std
    
    def _monte_carlo_var(self, returns: np.ndarray) -> float:
        """Monte Carlo simulation VaR."""
        mean = np.mean(returns)
        std = np.std(returns)
        
        # Generate simulated returns
        simulated = np.random.normal(mean, std, self.simulations)
        return np.percentile(simulated, (1 - self.confidence) * 100)
    
    def calculate_cvar(
        self,
        returns: np.ndarray,
        portfolio_value: float = 1.0
    ) -> dict[str, float]:
        """
        Calculate Conditional VaR (Expected Shortfall).
        """
        var_threshold = np.percentile(returns, (1 - self.confidence) * 100)
        cvar = np.mean(returns[returns <= var_threshold])
        
        return {
            "cvar_absolute": cvar * portfolio_value,
            "cvar_percentage": cvar * 100,
            "confidence": self.confidence,
            "var_threshold": var_threshold
        }
    
    def calculate_drawdown(
        self,
        equity_curve: np.ndarray
    ) -> dict[str, float]:
        """
        Calculate drawdown statistics.
        """
        # Running maximum
        running_max = np.maximum.accumulate(equity_curve)
        drawdown = (equity_curve - running_max) / running_max
        
        max_dd = np.min(drawdown)
        max_dd_duration = 0
        current_duration = 0
        
        for dd in drawdown:
            if dd < 0:
                current_duration += 1
                max_dd_duration = max(max_dd_duration, current_duration)
            else:
                current_duration = 0
        
        return {
            "max_drawdown": max_dd * 100,
            "max_drawdown_duration": max_dd_duration,
            "current_drawdown": drawdown[-1] * 100
        }
    
    def stress_test(
        self,
        returns: np.ndarray,
        shocks: dict[str, float] | None = None
    ) -> dict[str, float]:
        """
        Parametric stress testing.
        """
        if shocks is None:
            shocks = {
                "market_crash": -0.20,
                "flash_crash": -0.10,
                "volatility_spike": 2.0,
                "correlation_breakdown": 1.5
            }
        
        results = {}
        baseline_var = self._parametric_var(returns)
        
        for scenario, shock in shocks.items():
            if scenario == "volatility_spike":
                # Increase volatility
                stressed_var = baseline_var * shock
            elif scenario == "correlation_breakdown":
                # Increase correlation (diversification breakdown)
                stressed_var = baseline_var * shock
            else:
                # Direct return shock
                stressed_var = baseline_var + shock
            
            results[scenario] = {
                "shock": shock,
                "stressed_var": stressed_var,
                "impact": abs(stressed_var - baseline_var)
            }
        
        return results

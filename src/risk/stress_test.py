"""
Historical and parametric stress testing.
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

import numpy as np
import pandas as pd
from scipy import stats


@dataclass
class StressScenario:
    """Stress test scenario definition."""
    name: str
    description: str
    shock_type: Literal["absolute", "relative", "correlation"]
    shock_magnitude: float
    affected_assets: list[str]
    duration_days: int


class StressTester:
    """
    Institutional stress testing framework.
    """
    
    def __init__(self, confidence: float = 0.99):
        self.confidence = confidence
        self.scenarios = self._load_standard_scenarios()
    
    def _load_standard_scenarios(self) -> list[StressScenario]:
        """Load standard stress scenarios."""
        return [
            StressScenario(
                name="2008_financial_crisis",
                description="2008-style market crash",
                shock_type="relative",
                shock_magnitude=-0.30,
                affected_assets=["XAUUSD", "SPX", "EURUSD"],
                duration_days=30
            ),
            StressScenario(
                name="covid_crash",
                description="COVID-19 style sudden crash",
                shock_type="relative",
                shock_magnitude=-0.35,
                affected_assets=["XAUUSD", "SPX"],
                duration_days=20
            ),
            StressScenario(
                name="gold_spike",
                description="Safe haven flight to gold",
                shock_type="relative",
                shock_magnitude=0.25,
                affected_assets=["XAUUSD"],
                duration_days=10
            ),
            StressScenario(
                name="liquidity_crisis",
                description="Market liquidity freeze",
                shock_type="absolute",
                shock_magnitude=0.05,  # 500 bps spread
                affected_assets=["XAUUSD"],
                duration_days=5
            ),
            StressScenario(
                name="dollar_strength",
                description="USD strength impacts gold",
                shock_type="relative",
                shock_magnitude=-0.15,
                affected_assets=["XAUUSD"],
                duration_days=15
            ),
        ]
    
    def run_stress_test(
        self,
        portfolio_value: Decimal,
        positions: dict[str, Decimal],
        scenario: StressScenario | None = None,
        custom_shocks: dict[str, float] | None = None
    ) -> dict:
        """
        Run stress test on portfolio.
        
        Args:
            portfolio_value: Current portfolio value
            positions: Position sizes by symbol
            scenario: Predefined scenario or None for custom
            custom_shocks: Custom shock values by symbol
        
        Returns:
            Stress test results
        """
        if scenario:
            shocks = {asset: scenario.shock_magnitude for asset in scenario.affected_assets}
        else:
            shocks = custom_shocks or {}
        
        results = {
            "scenario": scenario.name if scenario else "custom",
            "initial_value": float(portfolio_value),
            "shocks": shocks,
            "position_impacts": {},
            "total_impact": 0.0,
            "stressed_value": 0.0,
            "breaches": []
        }
        
        total_impact = 0.0
        
        for symbol, size in positions.items():
            shock = shocks.get(symbol, 0.0)
            
            # Calculate position value impact
            position_value = float(size) * 1800  # Simplified price
            impact = position_value * shock
            
            results["position_impacts"][symbol] = {
                "size": float(size),
                "shock": shock,
                "impact": impact,
                "impact_pct": (impact / float(portfolio_value)) * 100
            }
            
            total_impact += impact
        
        results["total_impact"] = total_impact
        results["stressed_value"] = float(portfolio_value) + total_impact
        results["portfolio_impact_pct"] = (total_impact / float(portfolio_value)) * 100
        
        # Check for limit breaches
        if results["portfolio_impact_pct"] < -10:
            results["breaches"].append("Max drawdown limit (10%)")
        if results["portfolio_impact_pct"] < -5:
            results["breaches"].append("Daily loss limit (5%)")
        
        return results
    
    def run_monte_carlo_stress(
        self,
        portfolio_value: Decimal,
        positions: dict[str, Decimal],
        correlations: pd.DataFrame | None = None,
        n_sims: int = 10000
    ) -> dict:
        """
        Monte Carlo stress simulation with correlated shocks.
        """
        # Generate correlated random shocks
        n_assets = len(positions)
        
        if correlations is not None:
            # Use provided correlation matrix
            corr_matrix = correlations.values
        else:
            # Assume high correlation during stress (0.8)
            corr_matrix = np.ones((n_assets, n_assets)) * 0.8
            np.fill_diagonal(corr_matrix, 1.0)
        
        # Cholesky decomposition
        L = np.linalg.cholesky(corr_matrix)
        
        # Generate random shocks (fat-tailed distribution)
        random_normals = np.random.standard_t(df=3, size=(n_sims, n_assets))
        correlated_shocks = random_normals @ L.T
        
        # Scale to realistic market moves (annualized volatility)
        volatilities = np.array([0.15] * n_assets)  # 15% annual vol
        daily_vol = volatilities / np.sqrt(252)
        
        shocks = correlated_shocks * daily_vol * np.sqrt(10)  # 10-day horizon
        
        # Calculate portfolio impacts
        position_values = np.array([float(p) * 1800 for p in positions.values()])
        portfolio_impacts = shocks @ position_values
        
        results = {
            "mean_impact": float(np.mean(portfolio_impacts)),
            "worst_1pct": float(np.percentile(portfolio_impacts, 1)),
            "worst_5pct": float(np.percentile(portfolio_impacts, 5)),
            "var_99": float(np.percentile(portfolio_impacts, 1)),
            "cvar_99": float(np.mean(portfolio_impacts[portfolio_impacts <= np.percentile(portfolio_impacts, 1)])),
            "probability_of_ruin": float(np.mean(portfolio_impacts < -float(portfolio_value) * 0.5)),
            "n_simulations": n_sims
        }
        
        return results
    
    def historical_simulation(
        self,
        portfolio_value: Decimal,
        positions: dict[str, Decimal],
        historical_returns: pd.DataFrame,
        lookback_days: int = 252
    ) -> dict:
        """
        Historical simulation using actual past returns.
        """
        # Use recent historical returns
        recent_returns = historical_returns.tail(lookback_days)
        
        # Calculate portfolio returns for each historical day
        portfolio_returns = []
        
        for _, day_returns in recent_returns.iterrows():
            daily_pnl = 0
            for symbol, size in positions.items():
                ret = day_returns.get(symbol, 0)
                position_value = float(size) * 1800
                daily_pnl += position_value * ret
            
            portfolio_returns.append(daily_pnl)
        
        portfolio_returns = np.array(portfolio_returns)
        
        results = {
            "historical_var_95": float(np.percentile(portfolio_returns, 5)),
            "historical_var_99": float(np.percentile(portfolio_returns, 1)),
            "max_historical_loss": float(np.min(portfolio_returns)),
            "avg_loss_tail": float(np.mean(portfolio_returns[portfolio_returns <= np.percentile(portfolio_returns, 5)])),
            "n_observations": len(portfolio_returns),
            "lookback_days": lookback_days
        }
        
        return results

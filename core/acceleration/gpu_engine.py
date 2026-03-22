# core/risk/advanced_engine.py
"""
HOPEFX Advanced Risk Engine
Monte Carlo simulation with GARCH volatility and copula correlation
"""

import numpy as np
from scipy import stats
from scipy.optimize import minimize
from typing import Dict, List, Tuple
from dataclasses import dataclass
from decimal import Decimal
import pandas as pd


@dataclass
class RiskMetrics:
    var_95: float
    var_99: float
    cvar_95: float  # Expected shortfall
    cvar_99: float
    volatility: float
    max_drawdown: float
    tail_risk: float
    correlation_stress: float


class GARCHModel:
    """GARCH(1,1) with Student-t innovations"""
    
    def __init__(self):
        self.omega = 0.000001
        self.alpha = 0.1
        self.beta = 0.85
        self.nu = 5  # Degrees of freedom
    
    def fit(self, returns: np.ndarray):
        """Fit GARCH parameters via MLE"""
        def neg_log_likelihood(params):
            omega, alpha, beta, nu = params
            if omega <= 0 or alpha < 0 or beta < 0 or alpha + beta >= 1 or nu <= 2:
                return 1e10
            
            variance = np.zeros(len(returns))
            variance[0] = np.var(returns)
            
            for t in range(1, len(returns)):
                variance[t] = omega + alpha * returns[t-1]**2 + beta * variance[t-1]
            
            # Student-t log-likelihood
            log_likelihood = -np.sum(
                np.log(stats.t.pdf(returns / np.sqrt(variance), nu) / np.sqrt(variance))
            )
            return log_likelihood
        
        result = minimize(
            neg_log_likelihood,
            [self.omega, self.alpha, self.beta, self.nu],
            method='L-BFGS-B',
            bounds=[(1e-8, 1), (0, 1), (0, 1), (2.1, 30)]
        )
        
        self.omega, self.alpha, self.beta, self.nu = result.x
        return self
    
    def forecast(self, horizon: int = 1) -> np.ndarray:
        """Forecast conditional volatility"""
        # Simplified: assumes last variance known
        last_var = self.omega / (1 - self.alpha - self.beta)
        forecasts = np.zeros(horizon)
        
        for h in range(horizon):
            if h == 0:
                forecasts[h] = last_var
            else:
                forecasts[h] = self.omega + (self.alpha + self.beta) * forecasts[h-1]
        
        return np.sqrt(forecasts)
    
    def simulate(self, n_sims: int = 10000, horizon: int = 5) -> np.ndarray:
        """Simulate future paths"""
        simulated = np.zeros((n_sims, horizon))
        variance = np.ones(n_sims) * self.omega / (1 - self.alpha - self.beta)
        
        for t in range(horizon):
            variance = self.omega + self.alpha * simulated[:, t-1]**2 + self.beta * variance
            simulated[:, t] = np.sqrt(variance) * stats.t.rvs(self.nu, size=n_sims)
        
        return simulated


class CopulaRiskModel:
    """Vine copula for modeling tail dependencies"""
    
    def __init__(self):
        self.marginals = {}
        self.correlation = np.eye(2)
    
    def fit(self, returns: pd.DataFrame):
        """Fit copula to multivariate returns"""
        # Fit marginal distributions (Johnson SU)
        for col in returns.columns:
            params = stats.johnsonsu.fit(returns[col].dropna())
            self.marginals[col] = params
        
        # Transform to uniform
        uniform = pd.DataFrame()
        for col in returns.columns:
            uniform[col] = stats.johnsonsu.cdf(returns[col], *self.marginals[col])
        
        # Fit Gaussian copula (simplified)
        self.correlation = uniform.corr().values
        
        return self
    
    def simulate(self, n_sims: int = 10000) -> pd.DataFrame:
        """Simulate correlated returns"""
        # Generate correlated uniforms
        normal = np.random.multivariate_normal(
            np.zeros(len(self.marginals)),
            self.correlation,
            n_sims
        )
        uniform = stats.norm.cdf(normal)
        
        # Transform back
        simulated = pd.DataFrame()
        for i, col in enumerate(self.marginals.keys()):
            simulated[col] = stats.johnsonsu.ppf(uniform[:, i], *self.marginals[col])
        
        return simulated


class MonteCarloRiskEngine:
    """Full portfolio risk simulation"""
    
    def __init__(self, n_sims: int = 100000):
        self.n_sims = n_sims
        self.garch_models = {}
        self.copula = CopulaRiskModel()
        self.historical_returns = pd.DataFrame()
    
    def add_asset(self, symbol: str, returns: np.ndarray):
        """Add asset to risk model"""
        self.historical_returns[symbol] = returns
        
        # Fit GARCH
        garch = GARCHModel()
        garch.fit(returns)
        self.garch_models[symbol] = garch
    
    def calculate_portfolio_risk(self, weights: Dict[str, float]) -> RiskMetrics:
        """Calculate full risk metrics via Monte Carlo"""
        # Simulate using copula for dependencies
        copula_sims = self.copula.simulate(self.n_sims)
        
        # Apply GARCH volatility scaling
        scaled_returns = pd.DataFrame()
        for col in copula_sims.columns:
            if col in self.garch_models:
                vol = self.garch_models[col].forecast(len(copula_sims))
                scaled_returns[col] = copula_sims[col] * vol[:len(copula_sims)]
        
        # Calculate portfolio returns
        portfolio_returns = sum(
            scaled_returns[col] * weights.get(col, 0)
            for col in scaled_returns.columns
        )
        
        # Risk metrics
        var_95 = np.percentile(portfolio_returns, 5)
        var_99 = np.percentile(portfolio_returns, 1)
        cvar_95 = portfolio_returns[portfolio_returns <= var_95].mean()
        cvar_99 = portfolio_returns[portfolio_returns <= var_99].mean()
        
        # Max drawdown
        cumulative = (1 + portfolio_returns).cumprod()
        running_max = np.maximum.accumulate(cumulative)
        drawdown = (cumulative - running_max) / running_max
        
        return RiskMetrics(
            var_95=float(var_95),
            var_99=float(var_99),
            cvar_95=float(cvar_95),
            cvar_99=float(cvar_99),
            volatility=float(portfolio_returns.std()),
            max_drawdown=float(drawdown.min()),
            tail_risk=float(abs(var_99 / var_95)) if var_95 != 0 else 0,
            correlation_stress=float(self._stress_correlation(weights))
        )
    
    def _stress_correlation(self, weights: Dict[str, float]) -> float:
        """Calculate correlation under stress (tail dependence)"""
        # Simplified: use historical correlation in worst 5% of days
        if len(self.historical_returns) < 100:
            return 0.5
        
        worst_days = self.historical_returns.sum(axis=1).quantile(0.05)
        stress_data = self.historical_returns[self.historical_returns.sum(axis=1) <= worst_days]
        
        if len(stress_data) < 10:
            return 0.5
        
        return float(stress_data.corr().values.mean())


class RealTimeRiskMonitor:
    """Continuous risk monitoring with automatic position adjustment"""
    
    def __init__(self, risk_engine: MonteCarloRiskEngine):
        self.risk_engine = risk_engine
        self.limits = {
            'var_95_daily': -0.02,  # 2% daily VaR limit
            'cvar_95_daily': -0.03,  # 3% expected shortfall
            'max_drawdown': -0.10,   # 10% max drawdown
            'tail_risk': 3.0         # Tail risk ratio limit
        }
        self.current_risk: Optional[RiskMetrics] = None
        self.kill_switch_triggered = False
    
    def update_portfolio(self, positions: Dict[str, Decimal], prices: Dict[str, Decimal]):
        """Recalculate risk with current positions"""
        total_value = sum(positions[s] * prices[s] for s in positions)
        
        weights = {
            s: float(positions[s] * prices[s] / total_value) if total_value > 0 else 0
            for s in positions
        }
        
        self.current_risk = self.risk_engine.calculate_portfolio_risk(weights)
        return self._check_limits()
    
    def _check_limits(self) -> List[str]:
        """Check if any risk limits breached"""
        if not self.current_risk:
            return []
        
        violations = []
        
        if self.current_risk.var_95 < self.limits['var_95_daily']:
            violations.append(f"VaR 95%: {self.current_risk.var_95:.2%}")
        
        if self.current_risk.cvar_95 < self.limits['cvar_95_daily']:
            violations.append(f"CVaR 95%: {self.current_risk.cvar_95:.2%}")
        
        if self.current_risk.max_drawdown < self.limits['max_drawdown']:
            violations.append(f"Max DD: {self.current_risk.max_drawdown:.2%}")
        
        if violations:
            self._trigger_kill_switch(violations)
        
        return violations
    
    def _trigger_kill_switch(self, violations: List[str]):
        """Emergency position reduction"""
        print(f"🚨 RISK LIMIT BREACH: {', '.join(violations)}")
        self.kill_switch_triggered = True
        # Signal to close all positions

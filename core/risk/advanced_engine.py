# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
core/risk/advanced_engine.py
============================
Advanced risk engine — Monte Carlo simulation with GARCH volatility and
copula correlation.

Previously the GARCH/risk implementation lived in core/acceleration/gpu_engine.py
(misnamed historical placement — L-6 fix).  It now lives here.
GPU inference classes (GPUInferenceEngine, GPUFeatureEngine, GPUConfig)
remain in core/acceleration/gpu_engine.py.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
import logging

import numpy as np
import pandas as pd
from scipy import stats
from scipy.optimize import minimize

logger = logging.getLogger(__name__)


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
    """GARCH(1,1) with Student-t innovations."""

    def __init__(self):
        self.omega = 0.000001
        self.alpha = 0.1
        self.beta = 0.85
        self.nu = 5  # Degrees of freedom

    def fit(self, returns: np.ndarray):
        """Fit GARCH parameters via MLE."""

        def _garch_params_invalid(omega, alpha, beta, nu) -> bool:
            """Return True when GARCH(1,1)-t parameters are outside the stationarity region."""
            non_positive_omega = omega <= 0
            negative_alpha = alpha < 0
            negative_beta = beta < 0
            non_stationary = alpha + beta >= 1
            invalid_df = nu <= 2  # Student-t requires df > 2 for finite variance
            return non_positive_omega or negative_alpha or negative_beta or non_stationary or invalid_df

        def neg_log_likelihood(params):
            omega, alpha, beta, nu = params
            if _garch_params_invalid(omega, alpha, beta, nu):
                return 1e10

            variance = np.zeros(len(returns))
            variance[0] = np.var(returns)

            for t in range(1, len(returns)):
                variance[t] = omega + alpha * returns[t - 1] ** 2 + beta * variance[t - 1]

            # Student-t log-likelihood
            variance_safe = np.where(variance > 0, variance, 1e-12)
            pdf_vals = np.nan_to_num(
                stats.t.pdf(returns / np.sqrt(variance_safe), nu) / np.sqrt(variance_safe),
                nan=1e-300,
                posinf=1e-300,
                neginf=1e-300,
            )
            log_likelihood = -np.sum(
                np.log(  # healer: ignore — pdf_vals guarded by np.nan_to_num + np.where above
                    np.where(pdf_vals > 0, pdf_vals, 1e-300)
                )
            )
            return log_likelihood

        result = minimize(
            neg_log_likelihood,
            [self.omega, self.alpha, self.beta, self.nu],
            method="L-BFGS-B",
            bounds=[(1e-8, 1), (0, 1), (0, 1), (2.1, 30)],
        )

        self.omega, self.alpha, self.beta, self.nu = result.x
        return self

    def forecast(self, horizon: int = 1) -> np.ndarray:
        """Forecast conditional volatility."""
        last_var = self.omega / (1 - self.alpha - self.beta)
        forecasts = np.zeros(horizon)

        for h in range(horizon):
            if h == 0:
                forecasts[h] = last_var
            else:
                forecasts[h] = self.omega + (self.alpha + self.beta) * forecasts[h - 1]

        return np.sqrt(np.nan_to_num(forecasts, nan=0.0, posinf=0.0))

    def simulate(self, n_sims: int = 10000, horizon: int = 5) -> np.ndarray:
        """Simulate future paths using GARCH(1,1)-t dynamics.

        Bug fixed: at t=0 the previous code used simulated[:, t-1] which
        resolves to simulated[:, -1] (the last column, all zeros at init).
        This made the t=0 variance update use zero lagged returns regardless
        of the unconditional variance, producing a degenerate first step.
        Fix: seed a separate prev_return array from the unconditional variance
        so the t=0 update is consistent with the GARCH recursion.
        """
        simulated = np.zeros((n_sims, horizon))
        unconditional_var = self.omega / max(1 - self.alpha - self.beta, 1e-8)
        variance = np.ones(n_sims) * unconditional_var
        # Seed lagged return from unconditional std so t=0 is not degenerate.
        prev_return = np.sqrt(unconditional_var) * stats.t.rvs(self.nu, size=n_sims)

        for t in range(horizon):
            variance = self.omega + self.alpha * prev_return**2 + self.beta * variance
            variance = np.nan_to_num(variance, nan=0.0, posinf=0.0)
            simulated[:, t] = np.sqrt(np.maximum(variance, 0.0)) * stats.t.rvs(self.nu, size=n_sims)
            prev_return = simulated[:, t]

        return simulated


class CopulaRiskModel:
    """Vine copula for modeling tail dependencies."""

    def __init__(self):
        self.marginals = {}
        self.correlation = np.eye(2)

    def fit(self, returns: pd.DataFrame):
        """Fit copula to multivariate returns."""
        for col in returns.columns:
            params = stats.johnsonsu.fit(returns[col].dropna())
            self.marginals[col] = params

        uniform = pd.DataFrame()
        for col in returns.columns:
            uniform[col] = stats.johnsonsu.cdf(returns[col], *self.marginals[col])

        self.correlation = uniform.corr().values
        return self

    def simulate(self, n_sims: int = 10000) -> pd.DataFrame:
        """Simulate correlated returns."""
        normal = np.random.multivariate_normal(
            np.zeros(len(self.marginals)),
            self.correlation,
            n_sims,
        )
        uniform = stats.norm.cdf(normal)

        simulated = pd.DataFrame()
        for i, col in enumerate(self.marginals.keys()):
            simulated[col] = stats.johnsonsu.ppf(uniform[:, i], *self.marginals[col])

        return simulated


class MonteCarloRiskEngine:
    """Full portfolio risk simulation."""

    def __init__(self, n_sims: int = 100000):
        self.n_sims = n_sims
        self.garch_models = {}
        self.copula = CopulaRiskModel()
        self.historical_returns = pd.DataFrame()

    def add_asset(self, symbol: str, returns: np.ndarray):
        """Add asset to risk model."""
        self.historical_returns[symbol] = returns
        garch = GARCHModel()
        garch.fit(returns)
        self.garch_models[symbol] = garch

    def calculate_portfolio_risk(self, weights: dict[str, float]) -> RiskMetrics:
        """Calculate full risk metrics via Monte Carlo."""
        # Guard: copula needs at least one fitted marginal; return zero-risk
        # metrics when no assets have been added rather than crashing inside
        # np.random.multivariate_normal with an empty covariance matrix.
        if not self.garch_models or not self.copula.marginals:
            return RiskMetrics(
                var_95=0.0,
                var_99=0.0,
                cvar_95=0.0,
                cvar_99=0.0,
                volatility=0.0,
                max_drawdown=0.0,
                tail_risk=0.0,
                correlation_stress=0.0,
            )

        copula_sims = self.copula.simulate(self.n_sims)

        scaled_returns = pd.DataFrame()
        for col in copula_sims.columns:
            if col in self.garch_models:
                vol = self.garch_models[col].forecast(len(copula_sims))
                scaled_returns[col] = copula_sims[col] * vol[: len(copula_sims)]

        # Guard: if no columns matched GARCH models, return zero-risk metrics
        # rather than letting sum() return int 0 and crashing on .fillna().
        if scaled_returns.empty:
            return RiskMetrics(
                var_95=0.0,
                var_99=0.0,
                cvar_95=0.0,
                cvar_99=0.0,
                volatility=0.0,
                max_drawdown=0.0,
                tail_risk=0.0,
                correlation_stress=0.0,
            )

        portfolio_returns = sum(scaled_returns[col] * weights.get(col, 0) for col in scaled_returns.columns)
        portfolio_returns = portfolio_returns.fillna(0.0)

        var_95 = np.percentile(portfolio_returns, 5)
        var_99 = np.percentile(portfolio_returns, 1)
        cvar_95 = float(np.nan_to_num(portfolio_returns[portfolio_returns <= var_95].mean(), nan=0.0))
        cvar_99 = float(np.nan_to_num(portfolio_returns[portfolio_returns <= var_99].mean(), nan=0.0))

        cumulative = (1 + portfolio_returns).cumprod().fillna(1.0)
        running_max = np.maximum.accumulate(cumulative)
        drawdown = (cumulative - running_max) / np.where(running_max != 0, running_max, 1.0)

        return RiskMetrics(
            var_95=float(var_95),
            var_99=float(var_99),
            cvar_95=float(cvar_95),
            cvar_99=float(cvar_99),
            volatility=float(portfolio_returns.std()),
            max_drawdown=float(drawdown.min()),
            tail_risk=float(abs(var_99 / var_95)) if var_95 != 0 else 0,
            correlation_stress=float(self._stress_correlation(weights)),
        )

    def _stress_correlation(self, weights: dict[str, float]) -> float:
        """Calculate mean pairwise correlation under stress (tail dependence).

        Bug fixed: the previous implementation returned the mean of the full
        correlation matrix including the diagonal (all 1.0). For a 2-asset
        portfolio this gave (1 + rho + rho + 1) / 4 instead of rho, inflating
        the stress correlation metric and causing false risk-limit breaches.
        Fix: mask the diagonal before computing the mean so only off-diagonal
        (pairwise) correlations are averaged.
        """
        if len(self.historical_returns) < 100:
            return 0.5

        worst_days = self.historical_returns.sum(axis=1).quantile(0.05)
        stress_data = self.historical_returns[self.historical_returns.sum(axis=1) <= worst_days]

        if len(stress_data) < 10:
            return 0.5

        corr_matrix = stress_data.corr().fillna(0.0).values  # fillna guards NaN from constant columns
        n = corr_matrix.shape[0]
        if n < 2:
            return 0.5
        # Average off-diagonal elements only (exclude self-correlation = 1.0)
        mask = ~np.eye(n, dtype=bool)
        return float(corr_matrix[mask].mean())  # healer: ignore — fillna applied above


class RealTimeRiskMonitor:
    """Continuous risk monitoring with automatic position adjustment."""

    def __init__(self, risk_engine: MonteCarloRiskEngine):
        self.risk_engine = risk_engine
        self.limits = {
            "var_95_daily": -0.02,
            "cvar_95_daily": -0.03,
            "max_drawdown": -0.10,
            "tail_risk": 3.0,
        }
        self.current_risk: RiskMetrics | None = None
        self.kill_switch_triggered = False

    def update_portfolio(
        self,
        positions: dict[str, Decimal],
        prices: dict[str, Decimal],
    ):
        """Recalculate risk with current positions.

        Handles three edge cases that previously caused crashes or silent errors:
        1. Empty positions dict — returns [] without calling the risk engine
           (which would fail with an empty copula model).
        2. Symbol in positions but missing from prices — skipped rather than
           raising KeyError.
        3. total_value == 0 (all positions have zero price) — returns [] to
           avoid ZeroDivisionError in the weight calculation.
        """
        if not positions:
            return []

        # Only include symbols present in both dicts to avoid KeyError
        common = {s for s in positions if s in prices}
        if not common:
            return []

        total_value = sum(positions[s] * prices[s] for s in common)

        if total_value <= 0:
            return []

        weights = {s: float(positions[s] * prices[s] / total_value) for s in common}

        self.current_risk = self.risk_engine.calculate_portfolio_risk(weights)
        return self._check_limits()

    def _check_limits(self) -> list[str]:
        """Check if any risk limits are breached."""
        if not self.current_risk:
            return []

        violations = []

        if self.current_risk.var_95 < self.limits["var_95_daily"]:
            violations.append(f"VaR 95%: {self.current_risk.var_95:.2%}")

        if self.current_risk.cvar_95 < self.limits["cvar_95_daily"]:
            violations.append(f"CVaR 95%: {self.current_risk.cvar_95:.2%}")

        if self.current_risk.max_drawdown < self.limits["max_drawdown"]:
            violations.append(f"Max DD: {self.current_risk.max_drawdown:.2%}")

        if violations:
            self._trigger_kill_switch(violations)

        return violations

    def _trigger_kill_switch(self, violations: list[str]):
        """Emergency position reduction."""
        logger.critical("RISK LIMIT BREACH: %s", ", ".join(violations))
        self.kill_switch_triggered = True


__all__ = [
    "CopulaRiskModel",
    "GARCHModel",
    "MonteCarloRiskEngine",
    "RealTimeRiskMonitor",
    "RiskMetrics",
]

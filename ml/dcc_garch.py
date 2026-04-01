# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
ml/dcc_garch.py
================
DCC-GARCH (Dynamic Conditional Correlation) model.

Implements Engle's (2002) DCC-GARCH for time-varying correlation estimation:
  1. Fit univariate GARCH(1,1) to each series for conditional variances
  2. Standardise residuals
  3. Model dynamic conditional correlations via DCC(1,1)

Provides time-varying covariance matrices for portfolio construction,
risk management, and cross-asset hedge ratio estimation.

Reference:
  Engle, R. (2002). Dynamic Conditional Correlation. Journal of Business &
  Economic Statistics, 20(3), 339-350.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy.optimize import minimize

logger = logging.getLogger(__name__)


@dataclass
class DCCResult:
    """DCC-GARCH estimation result."""
    correlation_series: pd.DataFrame
    """Time-varying correlations (pairwise). Index = dates, cols = 'asset1_asset2'."""
    conditional_variances: pd.DataFrame
    """Conditional variance per series (h_it). Same index as input."""
    latest_correlation_matrix: np.ndarray
    """Most recent estimated correlation matrix."""
    dcc_alpha: float
    """DCC alpha parameter (shock persistence)."""
    dcc_beta: float
    """DCC beta parameter (correlation persistence)."""
    garch_params: dict[str, dict[str, float]]
    """Per-series GARCH(1,1) params: omega, alpha, beta."""
    n_observations: int


class GARCH11:
    """Simple GARCH(1,1) estimator for conditional variance."""

    def fit(self, returns: np.ndarray) -> dict[str, float]:
        """
        Fit GARCH(1,1) to return series via MLE.

        Model: h_t = omega + alpha * eps_{t-1}^2 + beta * h_{t-1}

        Returns dict with omega, alpha, beta, log_likelihood.
        """
        r = np.asarray(returns, dtype=float)
        r = r[~np.isnan(r)]
        var0 = float(np.var(r))

        def neg_loglik(params: np.ndarray) -> float:
            omega, a, b = params
            if omega <= 0 or a < 0 or b < 0 or a + b >= 1:
                return 1e10
            h = np.empty(len(r))
            h[0] = var0
            for t in range(1, len(r)):
                h[t] = omega + a * r[t - 1] ** 2 + b * h[t - 1]
            h = np.maximum(h, 1e-10)
            ll = -0.5 * np.sum(np.log(h) + r ** 2 / h)
            return float(-ll)

        # Initial guess: persistence = 0.9
        x0 = np.array([var0 * 0.05, 0.05, 0.90])
        bounds = [(1e-10, None), (1e-6, 0.5), (1e-6, 0.999)]
        constraints = [{"type": "ineq", "fun": lambda p: 0.999 - p[1] - p[2]}]

        try:
            result = minimize(
                neg_loglik, x0, method="L-BFGS-B",
        result = minimize(
            neg_loglik, x0, method="SLSQP",
            bounds=bounds,
            constraints=constraints,
            options={"maxiter": 200, "ftol": 1e-8},
        )

        return {
            "omega": float(omega),
            "alpha": float(alpha),
            "beta": float(beta),
        }

    def conditional_variance(
        self,
        returns: np.ndarray,
        params: dict[str, float],
    ) -> np.ndarray:
        """Compute conditional variance series h_t given GARCH(1,1) params."""
        r = np.asarray(returns, dtype=float)
        omega, alpha, beta = params["omega"], params["alpha"], params["beta"]
        h = np.empty(len(r))
        h[0] = float(np.var(r[:max(5, len(r) // 10)]))
        for t in range(1, len(r)):
            h[t] = omega + alpha * r[t - 1] ** 2 + beta * h[t - 1]
        return np.maximum(h, 1e-10)


class DCCGARCH:
    """
    DCC-GARCH(1,1) dynamic conditional correlation estimator.

    Provides time-varying correlation matrices between multiple assets.
    """

    def __init__(self) -> None:
        self._garch = GARCH11()

    def fit(self, returns: pd.DataFrame) -> DCCResult:
        """
        Fit DCC-GARCH to multivariate return series.

        Parameters
        ----------
        returns : pd.DataFrame
            Asset returns, shape (T, N). Columns are asset names.

        Returns
        -------
        DCCResult
        """
        returns_clean = returns.dropna()
        n_obs, n_assets = returns_clean.shape
        assets = list(returns_clean.columns)

        if n_obs < 50:
            raise ValueError("DCC-GARCH requires at least 50 observations")

        # Step 1: Fit univariate GARCH(1,1) to each series
        garch_params: dict[str, dict[str, float]] = {}
        h_matrix = np.empty((n_obs, n_assets))
        eps_std = np.empty((n_obs, n_assets))

        for i, asset in enumerate(assets):
            r_i = returns_clean[asset].values
            params = self._garch.fit(r_i)
            garch_params[asset] = params
            h_i = self._garch.conditional_variance(r_i, params)
            h_matrix[:, i] = h_i
            eps_std[:, i] = r_i / np.sqrt(h_i)

        # Unconditional correlation matrix
        Q_bar = np.corrcoef(eps_std.T)

        # Step 2: Fit DCC parameters
        dcc_alpha, dcc_beta = self._fit_dcc(eps_std, Q_bar)

        # Step 3: Compute time-varying correlations
        corr_series, Q_last = self._compute_correlations(
            eps_std, Q_bar, dcc_alpha, dcc_beta
        )

        # Build output correlation series (pairwise)
        corr_records: dict[str, list[float]] = {}
        for i in range(n_assets):
            for j in range(i + 1, n_assets):
                key = f"{assets[i]}_{assets[j]}"
                corr_records[key] = [float(c[i, j]) for c in corr_series]

        corr_df = pd.DataFrame(corr_records, index=returns_clean.index)
        h_df = pd.DataFrame(h_matrix, index=returns_clean.index, columns=assets)

        return DCCResult(
            correlation_series=corr_df,
            conditional_variances=h_df,
            latest_correlation_matrix=Q_last,
            dcc_alpha=dcc_alpha,
            dcc_beta=dcc_beta,
            garch_params=garch_params,
            n_observations=n_obs,
        )

    def _fit_dcc(
        self, eps_std: np.ndarray, Q_bar: np.ndarray
    ) -> tuple[float, float]:
        """Fit DCC(1,1) parameters via two-step MLE."""

        def neg_loglik(params: np.ndarray) -> float:
            a, b = params
            if a <= 0 or b <= 0 or a + b >= 1:
                return 1e10
            n, k = eps_std.shape
            Q = Q_bar.copy()
            ll = 0.0
            for t in range(1, n):
                e = eps_std[t - 1]
                Q = (1 - a - b) * Q_bar + a * np.outer(e, e) + b * Q
                Q_diag = np.sqrt(np.maximum(np.diag(Q), 1e-10))
                R = Q / np.outer(Q_diag, Q_diag)
                np.fill_diagonal(R, 1.0)
                try:
                    sign, logdet = np.linalg.slogdet(R)
                    if sign <= 0:
                        return 1e10
                    inv_R = np.linalg.inv(R)
                    e_t = eps_std[t]
                    ll += logdet + float(e_t @ inv_R @ e_t) - float(e_t @ e_t)
                except np.linalg.LinAlgError:
                    return 1e10
            return float(ll / 2)

        x0 = np.array([0.05, 0.90])
        bounds = [(1e-6, 0.3), (1e-6, 0.999)]
        constr = [{"type": "ineq", "fun": lambda p: 0.999 - p[0] - p[1]}]
        try:
            res = minimize(
                neg_loglik, x0, method="L-BFGS-B",
                bounds=bounds, options={"maxiter": 100},
            )
            return float(res.x[0]), float(res.x[1])
        except Exception:
            return 0.05, 0.90

    def _compute_correlations(
        self,
        eps_std: np.ndarray,
        Q_bar: np.ndarray,
        alpha: float,
        beta: float,
    ) -> tuple[list[np.ndarray], np.ndarray]:
        """Compute time-varying correlation matrices."""
        n, k = eps_std.shape
        Q = Q_bar.copy()
        corr_series = []

        for t in range(n):
            if t > 0:
                e = eps_std[t - 1]
                Q = (1 - alpha - beta) * Q_bar + alpha * np.outer(e, e) + beta * Q
            Q_diag = np.sqrt(np.maximum(np.diag(Q), 1e-10))
            R = Q / np.outer(Q_diag, Q_diag)
            np.fill_diagonal(R, 1.0)
            corr_series.append(R.copy())

        return corr_series, corr_series[-1]

# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
portfolio/black_litterman.py
==============================
Black-Litterman portfolio construction.

Implements the original He & Litterman (1999) Black-Litterman model:
  1. Compute implied equilibrium returns from market-cap weights
  2. Blend with investor views using uncertainty-weighted mixing
  3. Solve for BL posterior mean and covariance
  4. Optional mean-variance optimisation on posterior

Reference:
  He, G. & Litterman, R. (1999). The Intuition Behind Black-Litterman
  Model Portfolios. Goldman Sachs Asset Management.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


@dataclass
class BLResult:
    """Black-Litterman optimisation result."""
    weights: dict[str, float]
    """Optimal portfolio weights."""
    bl_returns: dict[str, float]
    """BL posterior expected returns."""
    bl_covariance: np.ndarray
    """BL posterior covariance matrix."""
    assets: list[str]
    """Asset names (ordered)."""


class BlackLitterman:
    """
    Black-Litterman portfolio optimiser.

    Parameters
    ----------
    risk_aversion : float
        Market risk aversion (lambda). Default 2.5 (typical equity).
    tau : float
        Uncertainty scalar on prior. Default 0.05.
    """

    def __init__(
        self,
        risk_aversion: float = 2.5,
        tau: float = 0.05,
    ) -> None:
        self.risk_aversion = risk_aversion
        self.tau = tau

    def fit(
        self,
        returns: pd.DataFrame,
        market_caps: pd.Series | None = None,
        views: list[dict] | None = None,
    ) -> BLResult:
        """
        Compute BL posterior and optimal weights.

        Parameters
        ----------
        returns : pd.DataFrame
            Historical returns, shape (T, N).
        market_caps : pd.Series, optional
            Market capitalisation per asset (for equilibrium prior).
            If None, equal-weight market portfolio is used.
        views : list[dict], optional
            List of view dicts, each with:
            - 'assets': list of asset names
            - 'weights': list of portfolio weights for the view (sums to 0
              for relative views, >0 for absolute)
            - 'return': expected return of the view
            - 'confidence': confidence level 0-1 (default 0.5)

        Returns
        -------
        BLResult
        """
        assets = list(returns.columns)
        n = len(assets)

        # Sample covariance
        cov = returns.cov().values

        # Market-cap weights (equilibrium portfolio)
        if market_caps is not None:
            mc = market_caps.reindex(assets).fillna(0).values
            w_mkt = mc / mc.sum() if mc.sum() > 0 else np.ones(n) / n
        else:
            w_mkt = np.ones(n) / n

        # Implied equilibrium excess returns: pi = lambda * Sigma * w_mkt
        pi = self.risk_aversion * cov @ w_mkt

        # Prior covariance scaled by tau
        tau_sigma = self.tau * cov

        if not views:
            # No views — return market equilibrium
            bl_mu = pi
            bl_sigma = cov + tau_sigma
        else:
            # Build views matrices P and q
            k = len(views)
            P = np.zeros((k, n))
            q = np.zeros(k)
            omega_diag = np.zeros(k)

            asset_idx = {a: i for i, a in enumerate(assets)}
            for vi, view in enumerate(views):
                vweights = view.get("weights", [])
                vassets = view.get("assets", [])
                for a, w in zip(vassets, vweights):
                    if a in asset_idx:
                        P[vi, asset_idx[a]] = w
                q[vi] = view.get("return", 0.0)
                conf = float(view.get("confidence", 0.5))
                conf = max(1e-6, min(conf, 1.0 - 1e-6))
                # Omega = diag(P * tau_sigma * P') / confidence
                p_row = P[vi : vi + 1, :]
                view_var = float(p_row @ tau_sigma @ p_row.T)
                omega_diag[vi] = view_var / conf

            omega = np.diag(omega_diag)

            # BL posterior
            # M1 = inv(tau_sigma) + P' * inv(omega) * P
            # BL_mu = M1^-1 * (inv(tau_sigma) * pi + P' * inv(omega) * q)
            try:
                inv_tau_sigma = np.linalg.inv(tau_sigma)
                inv_omega = np.linalg.inv(omega)
                M1 = inv_tau_sigma + P.T @ inv_omega @ P
                M2 = inv_tau_sigma @ pi + P.T @ inv_omega @ q
                bl_mu = np.linalg.solve(M1, M2)
                bl_sigma = np.linalg.inv(M1) + cov
            except np.linalg.LinAlgError as exc:
                logger.warning("BL: linear algebra error: %s — using prior", exc)
                bl_mu = pi
                bl_sigma = cov + tau_sigma

        # Mean-variance optimisation on BL posterior
        weights = _mv_optimise(bl_mu, bl_sigma, self.risk_aversion)
        weight_map = {a: float(weights[i]) for i, a in enumerate(assets)}

        logger.info(
            "BL: n_assets=%d, n_views=%d",
            n, len(views) if views else 0,
        )

        return BLResult(
            weights=weight_map,
            bl_returns={a: float(bl_mu[i]) for i, a in enumerate(assets)},
            bl_covariance=bl_sigma,
            assets=assets,
        )


def _mv_optimise(
    mu: np.ndarray,
    sigma: np.ndarray,
    risk_aversion: float,
) -> np.ndarray:
    """
    Analytical mean-variance solution: w* = (1/lambda) * Sigma^-1 * mu
    Projected onto the simplex (long-only, sum=1).
    """
    try:
        raw = np.linalg.solve(sigma, mu) / risk_aversion
    except np.linalg.LinAlgError:
        raw = mu.copy()

    # Long-only projection onto simplex
    raw = np.maximum(raw, 0.0)
    total = raw.sum()
    if total <= 0:
        return np.ones(len(mu)) / len(mu)
    return raw / total

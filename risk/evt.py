# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
risk/evt.py
============
Extreme Value Theory (EVT) tail risk — Generalised Pareto Distribution (GPD).

Implements Peaks-Over-Threshold (POT) method:
  1. Select threshold u (e.g. 95th percentile of losses)
  2. Fit Generalised Pareto Distribution to exceedances
  3. Compute VaR and Expected Shortfall at extreme quantiles (99%, 99.9%)

Reference:
  McNeil, A., Frey, R. & Embrechts, P. (2015). Quantitative Risk Management.
  Princeton University Press.
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass

import numpy as np
from scipy.optimize import minimize
from scipy.stats import genpareto

logger = logging.getLogger(__name__)


@dataclass
class EVTResult:
    """Extreme Value Theory tail risk result."""
    threshold: float
    """POT threshold (loss units)."""
    n_exceedances: int
    """Number of observations above threshold."""
    gpd_xi: float
    """GPD shape parameter (xi > 0: heavy tail)."""
    gpd_sigma: float
    """GPD scale parameter."""
    var_99: float
    """VaR at 99% confidence (loss amount)."""
    var_999: float
    """VaR at 99.9% confidence."""
    es_99: float
    """Expected Shortfall (CVaR) at 99%."""
    es_999: float
    """Expected Shortfall at 99.9%."""
    n_total: int
    """Total observations in sample."""


class EVTRiskModel:
    """
    Peaks-Over-Threshold EVT risk model using GPD.

    Fits a Generalised Pareto Distribution to the tail of losses
    to compute statistically motivated extreme VaR and ES.
    """

    def __init__(
        self,
        threshold_quantile: float = 0.90,
        min_exceedances: int = 30,
    ) -> None:
        """
        Parameters
        ----------
        threshold_quantile : float
            Quantile used to select threshold u. Default 0.90.
        min_exceedances : int
            Minimum exceedances required for reliable GPD fit.
        """
        if not 0.5 < threshold_quantile < 1.0:
            raise ValueError("threshold_quantile must be in (0.5, 1.0)")
        self.threshold_quantile = threshold_quantile
        self.min_exceedances = min_exceedances

    def fit(self, returns: np.ndarray) -> EVTResult:
        """
        Fit GPD to tail exceedances and compute extreme VaR/ES.

        Parameters
        ----------
        returns : np.ndarray
            Return series (not losses — losses = -returns, handled internally).

        Returns
        -------
        EVTResult
        """
        r = np.asarray(returns, dtype=float)
        r = r[~np.isnan(r)]
        losses = -r  # convert returns to losses

        n_total = len(losses)
        if n_total < 50:
            raise ValueError(f"EVT requires at least 50 observations, got {n_total}")

        # Threshold selection via quantile
        threshold = float(np.quantile(losses, self.threshold_quantile))
        exceedances = losses[losses > threshold] - threshold

        n_exc = len(exceedances)
        if n_exc < self.min_exceedances:
            logger.warning(
                "EVT: only %d exceedances (need %d), lowering threshold",
                n_exc, self.min_exceedances,
            )
            # Try lower threshold
            threshold = float(np.quantile(losses, max(0.5, self.threshold_quantile - 0.10)))
            exceedances = losses[losses > threshold] - threshold
            n_exc = len(exceedances)

        # Fit GPD via MLE
        xi, loc, sigma = self._fit_gpd(exceedances)

        # Compute VaR via GPD tail formula
        # F(x) = 1 - (n_u/n) * (1 + xi*(x-u)/sigma)^(-1/xi)
        # At level p: VaR_p = u + (sigma/xi) * (((1-p)/(n_u/n))^(-xi) - 1)
        n_u = n_exc
        n = n_total

        var_99 = self._gpd_var(0.99, threshold, xi, sigma, n, n_u)
        var_999 = self._gpd_var(0.999, threshold, xi, sigma, n, n_u)

        # Expected Shortfall: ES = VaR + (sigma + xi*(VaR - u)) / (1 - xi)
        es_99 = self._gpd_es(var_99, threshold, xi, sigma)
        es_999 = self._gpd_es(var_999, threshold, xi, sigma)

        logger.info(
            "EVT: n=%d, u=%.4f, n_exc=%d, xi=%.4f, VaR99=%.4f, ES99=%.4f",
            n_total, threshold, n_exc, xi, var_99, es_99,
        )

        return EVTResult(
            threshold=threshold,
            n_exceedances=n_exc,
            gpd_xi=xi,
            gpd_sigma=sigma,
            var_99=var_99,
            var_999=var_999,
            es_99=es_99,
            es_999=es_999,
            n_total=n_total,
        )

    def _fit_gpd(self, exceedances: np.ndarray) -> tuple[float, float, float]:
        """Fit GPD to exceedances using scipy MLE."""
        try:
            xi, loc, sigma = genpareto.fit(exceedances, floc=0)
            return float(xi), float(loc), float(sigma)
        except Exception as exc:
            logger.warning("EVT: GPD fit failed (%s), using moments", exc)
            # Method of moments fallback
            mu = float(exceedances.mean())
            var = float(exceedances.var())
            if var > 0:
                xi = 0.5 * (mu ** 2 / var - 1)
                sigma = 0.5 * mu * (mu ** 2 / var + 1)
            else:
                xi, sigma = 0.0, float(mu)
            return xi, 0.0, max(sigma, 1e-8)

    def _gpd_var(
        self,
        p: float,
        u: float,
        xi: float,
        sigma: float,
        n: int,
        n_u: int,
    ) -> float:
        """VaR from GPD tail."""
        p_u = n_u / n
        if p < (1 - p_u):
            return float(np.quantile([], p) if False else u)  # below threshold
        try:
            if abs(xi) < 1e-8:
                # Exponential case
                var = u - sigma * math.log((1 - p) / p_u)
            else:
                var = u + (sigma / xi) * (((1 - p) / p_u) ** (-xi) - 1)
            return float(var)
        except (ValueError, ZeroDivisionError):
            return float(u)

    def _gpd_es(self, var: float, u: float, xi: float, sigma: float) -> float:
        """Expected Shortfall from GPD: ES = (VaR + sigma - xi*u) / (1 - xi)."""
        if xi >= 1.0:
            return float("inf")
        try:
            es = (var + sigma - xi * u) / (1.0 - xi)
            return float(es)
        except ZeroDivisionError:
            return float("inf")

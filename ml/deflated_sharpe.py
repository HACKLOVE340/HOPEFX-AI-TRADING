# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
ml/deflated_sharpe.py
======================
Deflated Sharpe Ratio (DSR) and Probabilistic Sharpe Ratio (PSR).

Implements Bailey & López de Prado (2012):
  - PSR: probability that the observed Sharpe ratio exceeds a benchmark
  - DSR: PSR adjusted for multiple testing (selection bias, non-normality)

Reference:
  Bailey, D. & López de Prado, M. (2012). The Sharpe Ratio Efficient Frontier.
  Journal of Risk, 15(2), 3-44.
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import Sequence

import numpy as np
from scipy.stats import norm

logger = logging.getLogger(__name__)


@dataclass
class SharpeStats:
    """Output of Sharpe ratio analysis."""
    sharpe_ratio: float
    """Observed (annualised) Sharpe ratio."""
    psr: float
    """Probabilistic Sharpe Ratio: P(SR > SR_benchmark)."""
    dsr: float
    """Deflated Sharpe Ratio: PSR adjusted for multiple testing."""
    skewness: float
    """Return distribution skewness."""
    kurtosis: float
    """Excess kurtosis."""
    n_observations: int
    """Number of return observations."""
    n_trials: int
    """Number of strategies tested (for DSR)."""
    sr_benchmark: float
    """Benchmark Sharpe ratio used."""


def probabilistic_sharpe_ratio(
    returns: np.ndarray | list[float],
    sr_benchmark: float = 0.0,
    frequency: int = 252,
) -> float:
    """
    Compute Probabilistic Sharpe Ratio (PSR).

    PSR = Phi(((SR_hat - SR_ref) * sqrt(T-1)) / sqrt(1 - gamma3*SR_hat + (gamma4-1)/4*SR_hat^2))

    Parameters
    ----------
    returns : array-like of periodic returns
    sr_benchmark : float
        Reference Sharpe ratio (default 0.0)
    frequency : int
        Periods per year for annualisation (default 252)

    Returns
    -------
    float in [0, 1] — probability SR > benchmark
    """
    r = np.asarray(returns, dtype=float)
    r = r[~np.isnan(r)]
    n = len(r)
    if n < 5:
        return 0.5

    sr_hat = (r.mean() / r.std(ddof=1)) * math.sqrt(frequency)
    skew = _skewness(r)
    kurt = _excess_kurtosis(r)

    denominator = math.sqrt(
        (1.0 - skew * sr_hat + ((kurt - 1.0) / 4.0) * sr_hat ** 2) / (n - 1)
    )
    if denominator <= 0:
        return 0.5

    z = (sr_hat - sr_benchmark) / denominator
    return float(norm.cdf(z))


def deflated_sharpe_ratio(
    returns_list: Sequence[np.ndarray | list[float]],
    frequency: int = 252,
    sr_benchmark: float = 0.0,
) -> SharpeStats:
    """
    Compute Deflated Sharpe Ratio for the best strategy out of N.

    DSR adjusts the benchmark Sharpe ratio upward for the expected maximum
    of N independent standard normal variables (Bonferroni correction via
    Euler-Mascheroni + extreme value distribution).

    Parameters
    ----------
    returns_list : sequence of return arrays (one per strategy tried)
    frequency : int
        Periods per year
    sr_benchmark : float
        Minimum benchmark before multiple-testing adjustment

    Returns
    -------
    SharpeStats for the best strategy in returns_list
    """
    if not returns_list:
        raise ValueError("returns_list is empty")

    n_trials = len(returns_list)

    # Annualised SRs for all strategies
    srs = []
    for r in returns_list:
        arr = np.asarray(r, dtype=float)
        arr = arr[~np.isnan(arr)]
        if len(arr) < 2:
            srs.append(0.0)
        else:
            srs.append(float(arr.mean() / arr.std(ddof=1)) * math.sqrt(frequency))

    # Select best strategy
    best_idx = int(np.argmax(srs))
    best_returns = np.asarray(returns_list[best_idx], dtype=float)
    best_returns = best_returns[~np.isnan(best_returns)]
    n_obs = len(best_returns)

    # Benchmark SR adjusted for multiple testing (expected max of N iid N(0,1))
    adjusted_benchmark = _expected_max_sr(n_trials, sr_benchmark)

    # PSR for best strategy vs adjusted benchmark
    psr = probabilistic_sharpe_ratio(best_returns, adjusted_benchmark, frequency)

    # DSR = PSR with adjusted benchmark (same computation)
    dsr = psr

    skew = _skewness(best_returns)
    kurt = _excess_kurtosis(best_returns)

    return SharpeStats(
        sharpe_ratio=srs[best_idx],
        psr=probabilistic_sharpe_ratio(best_returns, sr_benchmark, frequency),
        dsr=dsr,
        skewness=skew,
        kurtosis=kurt,
        n_observations=n_obs,
        n_trials=n_trials,
        sr_benchmark=adjusted_benchmark,
    )


def _expected_max_sr(n: int, sr_floor: float = 0.0) -> float:
    """
    Expected maximum SR from N iid tests using Euler-Mascheroni constant.

    E[max(Z1,...,ZN)] ≈ (1 - euler_gamma) * Phi^-1(1 - 1/n) + euler_gamma * Phi^-1(1 - 1/(n*e))
    """
    if n <= 1:
        return sr_floor

    euler_gamma = 0.5772156649
    # Approximate expected max of N standard normals
    if n > 1:
        e_max = (
            (1 - euler_gamma) * norm.ppf(1 - 1 / n)
            + euler_gamma * norm.ppf(1 - 1 / (n * math.e))
        )
    else:
        e_max = 0.0

    return max(sr_floor, float(e_max))


def _skewness(r: np.ndarray) -> float:
    """Sample skewness."""
    n = len(r)
    if n < 3:
        return 0.0
    mu = r.mean()
    sigma = r.std(ddof=1)
    if sigma == 0:
        return 0.0
    return float(np.mean(((r - mu) / sigma) ** 3))


def _excess_kurtosis(r: np.ndarray) -> float:
    """Excess kurtosis (normal = 0)."""
    n = len(r)
    if n < 4:
        return 0.0
    mu = r.mean()
    sigma = r.std(ddof=1)
    if sigma == 0:
        return 0.0
    return float(np.mean(((r - mu) / sigma) ** 4) - 3.0)

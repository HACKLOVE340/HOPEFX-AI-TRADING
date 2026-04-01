# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
portfolio/hrp.py
=================
Hierarchical Risk Parity (HRP) portfolio construction.

Implements López de Prado's HRP algorithm (2016):
  1. Tree clustering of assets via single-linkage on correlation distance
  2. Quasi-diagonalization of the covariance matrix
  3. Recursive bisection to allocate weights inversely proportional to variance

Reference:
  López de Prado, M. (2016). Building Diversified Portfolios that Outperform
  Out-of-Sample. Journal of Portfolio Management.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Sequence

import numpy as np
import pandas as pd
from scipy.cluster.hierarchy import linkage, leaves_list
from scipy.spatial.distance import squareform

logger = logging.getLogger(__name__)


@dataclass
class HRPResult:
    """Result of HRP optimisation."""
    weights: dict[str, float]
    """Asset name → weight (sums to 1.0)."""
    cluster_order: list[str]
    """Assets in quasi-diagonal order."""
    diversification_ratio: float
    """Portfolio diversification ratio (>1 is more diversified)."""
    portfolio_vol: float
    """Annualised portfolio volatility estimate."""


class HRP:
    """
    Hierarchical Risk Parity optimiser.

    Parameters
    ----------
    linkage_method : str
        Scipy linkage method. 'single' (default) matches original paper.
    frequency : int
        Return frequency for annualisation. 252 for daily (default).
    """

    def __init__(
        self,
        linkage_method: str = "single",
        frequency: int = 252,
    ) -> None:
        self.linkage_method = linkage_method
        self.frequency = frequency

    def fit(self, returns: pd.DataFrame) -> HRPResult:
        """
        Compute HRP weights from a DataFrame of returns.

        Parameters
        ----------
        returns : pd.DataFrame
            Asset returns, shape (T, N). Columns are asset names.

        Returns
        -------
        HRPResult with weights, cluster_order, diversification_ratio.
        """
        assets = list(returns.columns)
        n = len(assets)

        if n < 2:
            w = {assets[0]: 1.0} if assets else {}
            return HRPResult(
                weights=w,
                cluster_order=assets,
                diversification_ratio=1.0,
                portfolio_vol=float(returns.std().iloc[0]) * np.sqrt(self.frequency)
                if assets else 0.0,
            )

        # Covariance and correlation matrices
        cov = returns.cov().values
        corr = returns.corr().values

        # Step 1: Tree clustering on correlation distance
        dist = np.sqrt(0.5 * (1.0 - corr))
        condensed = squareform(dist, checks=False)
        link = linkage(condensed, method=self.linkage_method)
        ordered_idx = leaves_list(link)  # quasi-diagonal leaf ordering

        # Step 2: Quasi-diagonal covariance matrix
        ordered_assets = [assets[i] for i in ordered_idx]

        # Step 3: Recursive bisection
        weights_arr = np.ones(n)
        cluster_list = [list(range(n))]  # work in quasi-diagonal indices

        while any(len(c) > 1 for c in cluster_list):
            cluster_list = [
                sub
                for subcluster in cluster_list
                for sub in _bisect(subcluster)
                if len(sub) > 0
            ]
            for subcluster in cluster_list:
                _allocate_risk_parity(weights_arr, subcluster, cov, ordered_idx)
        # Reorder weights back to original asset order
        weight_map: dict[str, float] = {}
        total = weights_arr.sum()
        for qi, orig_i in enumerate(ordered_idx):
            weight_map[assets[orig_i]] = float(weights_arr[qi] / total)

        # Portfolio statistics
        w_arr = np.array([weight_map[a] for a in assets])
        port_var = float(w_arr @ cov @ w_arr)
        port_vol = float(np.sqrt(port_var * self.frequency))

        # Diversification ratio: weighted avg asset vol / portfolio vol
        asset_vols = np.sqrt(np.diag(cov) * self.frequency)
        weighted_avg_vol = float(w_arr @ asset_vols)
        div_ratio = (weighted_avg_vol / port_vol) if port_vol > 0 else 1.0

        logger.info(
            "HRP: n_assets=%d, port_vol=%.4f, div_ratio=%.3f",
            n, port_vol, div_ratio,
        )

        return HRPResult(
            weights=weight_map,
            cluster_order=ordered_assets,
            diversification_ratio=div_ratio,
            portfolio_vol=port_vol,
        )


def _bisect(cluster: list[int]) -> list[list[int]]:
    """Split a cluster into two halves."""
    mid = len(cluster) // 2
    return [cluster[:mid], cluster[mid:]]


def _allocate_risk_parity(
    weights: np.ndarray,
    subcluster: list[int],
    cov: np.ndarray,
    ordered_idx: np.ndarray,
) -> None:
    """
    Inverse-variance allocation within a bisected cluster.
    Mutates `weights` in place.
    """
    if len(subcluster) < 2:
        return

    mid = len(subcluster) // 2
    left = subcluster[:mid]
    right = subcluster[mid:]

    # Map quasi-diagonal positions to original covariance indices
    left_orig = [ordered_idx[i] for i in left]
    right_orig = [ordered_idx[i] for i in right]

    left_var = _cluster_var(weights, left_orig, cov)
    right_var = _cluster_var(weights, right_orig, cov)

    total_var = left_var + right_var
    if total_var == 0:
        return

    alpha = 1.0 - left_var / total_var  # right gets alpha, left gets (1-alpha)

    for i in left:
        weights[i] *= (1.0 - alpha)
    for i in right:
        weights[i] *= alpha


def _cluster_var(
    weights: np.ndarray,
    cluster_orig: list[int],
    cov: np.ndarray,
) -> float:
    """Compute sub-portfolio variance for a cluster."""
    sub_w = weights[cluster_orig]
    sub_cov = cov[np.ix_(cluster_orig, cluster_orig)]
    total = sub_w.sum()
    if total == 0:
        return 0.0
    sub_w_norm = sub_w / total
    return float(sub_w_norm @ sub_cov @ sub_w_norm)

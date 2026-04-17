# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
Portfolio Manager

Portfolio construction, correlation analysis, optimization, and risk contribution.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd


@dataclass
class Portfolio:
    """Represents a constructed portfolio."""

    name: str
    assets: dict[str, float]  # symbol -> weight
    rebalancing: str = "monthly"

    @property
    def total_exposure(self) -> float:
        return round(sum(self.assets.values()), 10)

    @property
    def asset_count(self) -> int:
        return len(self.assets)


class PortfolioManager:
    """Portfolio construction, optimization, and risk analytics."""

    def __init__(self, config: dict | None = None):
        self.config = config or {}
        self.portfolios: dict[str, Portfolio] = {}

    # ── Construction ─────────────────────────────────────────────────────────

    def create_portfolio(
        self,
        name: str,
        assets: dict[str, float],
        rebalancing: str = "monthly",
    ) -> Portfolio:
        """Create and register a portfolio."""
        portfolio = Portfolio(name=name, assets=assets, rebalancing=rebalancing)
        self.portfolios[name] = portfolio
        return portfolio

    # ── Correlation ──────────────────────────────────────────────────────────

    def calculate_correlation(self, returns: pd.DataFrame) -> pd.DataFrame:
        """Return the Pearson correlation matrix for the given returns DataFrame."""
        return returns.corr()

    # ── Optimization ─────────────────────────────────────────────────────────

    def optimize(
        self,
        returns: pd.DataFrame,
        method: str = "sharpe",
        constraints: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        Optimize portfolio weights.

        Supported methods:
          - 'sharpe'   : maximize Sharpe ratio via random search
          - 'equal'    : equal-weight baseline
        """
        constraints = constraints or {}
        max_weight: float = constraints.get("max_weight", 1.0)
        assets = list(returns.columns)
        n = len(assets)

        if method == "equal":
            w = dict.fromkeys(assets, 1.0 / n)
            mu = returns.mean()
            returns.std()
            port_ret = sum(w[a] * mu[a] for a in assets)
            _cov_eq = np.nan_to_num(returns.cov().values, nan=0.0)
            _wv_eq = np.array(list(w.values()))
            port_vol = float(np.sqrt(max(np.dot(_wv_eq, np.dot(_cov_eq, _wv_eq)), 0.0)))
            sharpe = port_ret / port_vol if port_vol > 0 else 0.0
            return {"weights": w, "expected_sharpe": sharpe}

        # Random search for max Sharpe with guaranteed max_weight constraint.
        best_sharpe = -np.inf
        best_weights: dict[str, float] = {}
        rng = np.random.default_rng(42)
        cov = np.nan_to_num(returns.cov().values, nan=0.0)
        mu = np.nan_to_num(returns.mean().values, nan=0.0)

        for _ in range(10_000):
            raw = rng.random(n)
            # Project onto the simplex with per-weight upper bound via
            # iterative clipping (guaranteed to converge in ≤ n iterations).
            w = self._project_simplex_bounded(raw, max_weight)

            port_ret = float(np.nan_to_num(np.dot(w, mu), nan=0.0))
            port_vol = float(np.sqrt(max(float(np.nan_to_num(w @ cov @ w, nan=0.0)), 0.0)))
            if port_vol == 0:
                continue
            sharpe = port_ret / port_vol

            if sharpe > best_sharpe:
                best_sharpe = sharpe
                best_weights = {a: float(w[i]) for i, a in enumerate(assets)}

        return {"weights": best_weights, "expected_sharpe": best_sharpe}

    @staticmethod
    def _project_simplex_bounded(v: np.ndarray, max_w: float) -> np.ndarray:
        """
        Project v onto the probability simplex with per-element upper bound max_w.

        Algorithm:
        1. Clip each element to [0, max_w].
        2. Normalise so weights sum to 1.
        3. Any weight that now exceeds max_w is clamped; the excess is
           redistributed to unclamped weights.  Repeat until stable.
        4. Final truncation to max_w guarantees the constraint holds exactly
           regardless of floating-point rounding.
        """
        n = len(v)
        w = np.clip(v.astype(float), 0.0, max_w)
        s = w.sum()
        if s == 0:
            return np.full(n, 1.0 / n)

        w /= s  # initial normalise

        for _ in range(200):
            over = w > max_w
            if not over.any():
                break
            excess = float(np.nan_to_num((w[over] - max_w).sum(), nan=0.0))
            w[over] = max_w
            free = ~over
            if free.any():
                w[free] += excess / free.sum()
            else:
                break

        # Truncate any sub-epsilon overshoot from floating-point arithmetic,
        # then renormalise so weights sum exactly to 1.
        w = np.minimum(w, max_w)
        s = w.sum()
        if s > 0:
            w /= s
        # One final truncation: renormalisation can push a weight to
        # max_w * (1 + ε).  Clamp and accept the tiny shortfall.
        w = np.minimum(w, max_w)
        return w

    # ── Risk contribution ────────────────────────────────────────────────────

    def calculate_risk_contribution(
        self,
        weights: dict[str, float],
        cov_matrix: pd.DataFrame,
    ) -> dict[str, float]:
        """
        Compute each asset's fractional contribution to total portfolio variance.

        RC_i = w_i * (Sigma * w)_i  /  w^T Sigma w
        """
        assets = list(weights.keys())
        w = np.array([weights[a] for a in assets])
        sigma = cov_matrix.loc[assets, assets].values

        marginal = sigma @ w  # (Sigma * w)
        contrib = w * marginal  # element-wise
        total = float(contrib.sum())

        if total == 0:
            return {a: 1.0 / len(assets) for a in assets}

        return {a: float(contrib[i] / total) for i, a in enumerate(assets)}

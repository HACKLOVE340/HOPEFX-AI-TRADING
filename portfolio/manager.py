"""
Portfolio Manager

Portfolio construction, correlation analysis, optimization, and risk contribution.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from dataclasses import dataclass, field
from typing import Any, Dict, Optional


@dataclass
class Portfolio:
    """Represents a constructed portfolio."""

    name: str
    assets: Dict[str, float]  # symbol -> weight
    rebalancing: str = "monthly"

    @property
    def total_exposure(self) -> float:
        return sum(self.assets.values())

    @property
    def asset_count(self) -> int:
        return len(self.assets)


class PortfolioManager:
    """Portfolio construction, optimization, and risk analytics."""

    def __init__(self, config: Optional[Dict] = None):
        self.config = config or {}
        self.portfolios: Dict[str, Portfolio] = {}

    # ── Construction ─────────────────────────────────────────────────────────

    def create_portfolio(
        self,
        name: str,
        assets: Dict[str, float],
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
        constraints: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
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
            w = {a: 1.0 / n for a in assets}
            mu = returns.mean()
            sigma = returns.std()
            port_ret = sum(w[a] * mu[a] for a in assets)
            port_vol = float(np.sqrt(np.dot(list(w.values()), np.dot(returns.cov().values, list(w.values())))))
            sharpe = port_ret / port_vol if port_vol > 0 else 0.0
            return {"weights": w, "expected_sharpe": sharpe}

        # Random search for max Sharpe (fast, no scipy dependency)
        best_sharpe = -np.inf
        best_weights: Dict[str, float] = {}
        rng = np.random.default_rng(42)

        for _ in range(5_000):
            raw = rng.random(n)
            raw = np.clip(raw, 0, max_weight * sum(raw))
            raw /= raw.sum()
            # Enforce max_weight constraint
            raw = np.minimum(raw, max_weight)
            raw /= raw.sum()

            port_ret = float(np.dot(raw, returns.mean()))
            port_vol = float(np.sqrt(raw @ returns.cov().values @ raw))
            if port_vol == 0:
                continue
            sharpe = port_ret / port_vol

            if sharpe > best_sharpe:
                best_sharpe = sharpe
                best_weights = {a: float(raw[i]) for i, a in enumerate(assets)}

        return {"weights": best_weights, "expected_sharpe": best_sharpe}

    # ── Risk contribution ────────────────────────────────────────────────────

    def calculate_risk_contribution(
        self,
        weights: Dict[str, float],
        cov_matrix: pd.DataFrame,
    ) -> Dict[str, float]:
        """
        Compute each asset's fractional contribution to total portfolio variance.

        RC_i = w_i * (Sigma * w)_i  /  w^T Sigma w
        """
        assets = list(weights.keys())
        w = np.array([weights[a] for a in assets])
        sigma = cov_matrix.loc[assets, assets].values

        marginal = sigma @ w          # (Sigma * w)
        contrib = w * marginal        # element-wise
        total = float(contrib.sum())

        if total == 0:
            return {a: 1.0 / len(assets) for a in assets}

        return {a: float(contrib[i] / total) for i, a in enumerate(assets)}

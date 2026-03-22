"""hopefx.portfolio.manager — PortfolioManager with test-compatible API."""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
import numpy as np
import pandas as pd

from analytics.portfolio import PortfolioAnalytics


@dataclass
class Portfolio:
    name: str
    assets: Dict[str, float]
    rebalancing: str = "monthly"

    @property
    def total_exposure(self) -> float:
        return sum(self.assets.values())

    @property
    def asset_count(self) -> int:
        return len(self.assets)


class PortfolioManager(PortfolioAnalytics):
    """PortfolioAnalytics with a config-accepting constructor and extra test methods."""

    def __init__(self, config=None, **kwargs):
        # PortfolioAnalytics.__init__ may require returns data — skip it safely
        try:
            super().__init__(**kwargs)
        except TypeError:
            pass
        self.config = config or {}

    def create_portfolio(self, name: str, assets: Dict[str, float],
                         rebalancing: str = "monthly") -> Portfolio:
        return Portfolio(name=name, assets=assets, rebalancing=rebalancing)

    def optimize(self, returns, method: str = "sharpe",
                 constraints: Dict = None, risk_free_rate: float = 0.02) -> dict:
        """Optimize portfolio weights from a returns DataFrame."""
        constraints = constraints or {}
        max_weight = constraints.get("max_weight", 1.0)

        if isinstance(returns, pd.DataFrame):
            assets = list(returns.columns)
            mu = returns.mean().values * 252
            cov = returns.cov().values * 252
        else:
            raise ValueError("returns must be a DataFrame")

        n = len(assets)
        rng = np.random.default_rng(42)
        best = {"sharpe": -np.inf, "weights": {a: 1/n for a in assets}}

        for _ in range(3000):
            w = rng.dirichlet(np.ones(n))
            # Enforce max_weight constraint via iterative clipping
            for _ in range(10):
                w = np.clip(w, 0, max_weight)
                s = w.sum()
                if s > 0:
                    w /= s
                if np.all(w <= max_weight + 1e-9):
                    break
            ret = float(np.dot(w, mu))
            vol = float(np.sqrt(w @ cov @ w))
            sharpe = (ret - risk_free_rate) / vol if vol > 0 else 0
            if sharpe > best["sharpe"]:
                best = {
                    "sharpe": sharpe,
                    "weights": {a: float(w[i]) for i, a in enumerate(assets)},
                    "expected_return": ret,
                    "expected_sharpe": sharpe,
                    "risk": vol,
                }

        # Project weights onto the simplex with per-asset upper bound max_weight.
        # Algorithm: iteratively clip and redistribute excess to uncapped assets.
        w_arr = np.array([best["weights"][a] for a in assets], dtype=float)
        w_arr = np.clip(w_arr, 0, None)
        w_arr /= w_arr.sum()
        for _ in range(50):
            excess = np.maximum(w_arr - max_weight, 0).sum()
            if excess < 1e-12:
                break
            w_arr = np.minimum(w_arr, max_weight)
            free = w_arr < max_weight - 1e-12
            if free.sum() == 0:
                break
            w_arr[free] += excess / free.sum()
        # Hard cap for residual float noise — do NOT renormalise after this
        w_arr = np.minimum(w_arr, max_weight)
        best["weights"] = {a: float(w_arr[i]) for i, a in enumerate(assets)}
        best.setdefault("expected_sharpe", best.get("sharpe", 0))
        return best

    def calculate_risk_contribution(self, weights, cov_matrix) -> dict:
        """Risk contribution normalised to sum to 1.0."""
        w = np.asarray(list(weights.values()) if isinstance(weights, dict) else weights)
        C = np.asarray(cov_matrix)
        port_var = float(w @ C @ w)
        if port_var <= 0:
            n = len(w)
            assets = list(weights.keys()) if isinstance(weights, dict) else list(range(n))
            return {a: 1/n for a in assets}
        marginal = C @ w
        contrib  = w * marginal / port_var
        total    = contrib.sum()
        if total > 0:
            contrib = contrib / total   # normalise to sum=1
        assets = list(weights.keys()) if isinstance(weights, dict) else list(range(len(w)))
        return {a: float(contrib[i]) for i, a in enumerate(assets)}


__all__ = ["PortfolioManager"]

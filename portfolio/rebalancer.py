# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
portfolio/rebalancer.py
=======================
Dynamic portfolio rebalancer with mean-variance and risk-parity optimisation.

Manages a *book* of strategies with live correlation constraints — the key
institutional capability that separates a pod from a single-strategy system.

Architecture
------------
BookOptimiser      — scipy SLSQP mean-variance + risk-parity solver
CorrelationTracker — rolling live correlation matrix across strategies
RebalanceScheduler — decides *when* to rebalance (threshold + calendar)
DynamicRebalancer  — top-level orchestrator; wires all components together

Optimisation methods
--------------------
mean_variance  : maximise Sharpe subject to weight, drawdown, and correlation
                 constraints.  Uses scipy.optimize.minimize (SLSQP).
risk_parity    : equalise risk contribution across strategies (ERC).
                 Solved via convex optimisation (scipy SLSQP).
equal_weight   : 1/N baseline (no optimisation).

Constraints enforced
--------------------
- Sum of weights = 1 (fully invested)
- 0 ≤ w_i ≤ max_weight (default 0.40)
- Pairwise correlation between any two active strategies ≤ max_corr (default 0.70)
  → strategies that breach this are down-weighted proportionally
- Max drawdown gate: strategy with drawdown > dd_limit gets weight = 0

Usage
-----
    from portfolio.rebalancer import DynamicRebalancer
    rebalancer = DynamicRebalancer(method="risk_parity")
    rebalancer.update_strategy_returns("smc_ict", returns_series)
    rebalancer.update_strategy_returns("mean_reversion", returns_series)

    result = rebalancer.rebalance()
    # result.weights  -> {"smc_ict": 0.55, "mean_reversion": 0.45}
    # result.trades   -> {"smc_ict": +0.05, "mean_reversion": -0.05}
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

UTC = timezone.utc
from typing import Any

import numpy as np
import pandas as pd
from scipy.optimize import minimize

try:
    from enum import StrEnum
except ImportError:
    from enum import Enum

    class StrEnum(str, Enum):  # Python 3.10 compat
        pass


logger = logging.getLogger(__name__)


# ── Enums & data structures ───────────────────────────────────────────────────


class OptimMethod(StrEnum):
    MEAN_VARIANCE = "mean_variance"
    RISK_PARITY = "risk_parity"
    EQUAL_WEIGHT = "equal_weight"


@dataclass
class RebalanceResult:
    """Output of a single rebalance run."""

    method: str
    weights: dict[str, float]  # strategy_id -> target weight
    trades: dict[str, float]  # strategy_id -> weight delta (+ = increase)
    expected_return: float  # annualised
    expected_vol: float  # annualised
    expected_sharpe: float
    correlation_matrix: dict[str, dict[str, float]]
    risk_contributions: dict[str, float]  # strategy_id -> % of portfolio risk
    constrained_strategies: list[str]  # strategies that hit a constraint
    computed_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict[str, Any]:
        return {
            "method": self.method,
            "weights": {k: round(v, 4) for k, v in self.weights.items()},
            "trades": {k: round(v, 4) for k, v in self.trades.items()},
            "expected_return": round(self.expected_return, 4),
            "expected_vol": round(self.expected_vol, 4),
            "expected_sharpe": round(self.expected_sharpe, 4),
            "correlation_matrix": {
                k: {kk: round(vv, 4) for kk, vv in v.items()} for k, v in self.correlation_matrix.items()
            },
            "risk_contributions": {k: round(v, 4) for k, v in self.risk_contributions.items()},
            "constrained_strategies": self.constrained_strategies,
            "computed_at": self.computed_at.isoformat(),
        }


# ── Correlation Tracker ───────────────────────────────────────────────────────


class CorrelationTracker:
    """
    Maintains a rolling correlation matrix across strategy return streams.

    Uses an exponentially weighted covariance (EWMA) with span=60 so that
    recent correlation regimes are weighted more heavily than distant history.
    """

    def __init__(self, ewm_span: int = 60, min_periods: int = 20):
        self.ewm_span = ewm_span
        self.min_periods = min_periods
        self._returns: dict[str, pd.Series] = {}

    def update(self, strategy_id: str, returns: pd.Series) -> None:
        """Add or replace the return series for a strategy."""
        self._returns[strategy_id] = returns.dropna()

    def get_correlation_matrix(self) -> pd.DataFrame:
        """
        Return the EWMA correlation matrix for all tracked strategies.

        Returns an identity matrix if fewer than 2 strategies are tracked
        or if there is insufficient history.
        """
        strategies = list(self._returns.keys())
        n = len(strategies)
        if n < 2:
            return pd.DataFrame(
                np.eye(max(n, 1)),
                index=strategies,
                columns=strategies,
            )

        # Align all series to a common index
        df = pd.DataFrame({sid: self._returns[sid] for sid in strategies})
        df = df.dropna(how="all").ffill()

        if len(df) < self.min_periods:
            return pd.DataFrame(np.eye(n), index=strategies, columns=strategies)

        # EWMA covariance → correlation
        ewm_cov = df.ewm(span=self.ewm_span, min_periods=self.min_periods).cov()
        # ewm_cov is a MultiIndex DataFrame; take the last timestamp slice
        last_ts = ewm_cov.index.get_level_values(0)[-1]
        cov_slice = ewm_cov.loc[last_ts]

        # Convert covariance to correlation
        std_diag = np.sqrt(np.diag(cov_slice.values))
        with np.errstate(divide="ignore", invalid="ignore"):
            corr = cov_slice.values / np.outer(std_diag, std_diag)
        corr = np.nan_to_num(corr, nan=0.0)
        np.fill_diagonal(corr, 1.0)

        return pd.DataFrame(corr, index=strategies, columns=strategies)

    def get_covariance_matrix(self) -> pd.DataFrame:
        """Return the EWMA covariance matrix."""
        strategies = list(self._returns.keys())
        n = len(strategies)
        if n < 2:
            return pd.DataFrame(np.eye(max(n, 1)), index=strategies, columns=strategies)

        df = pd.DataFrame({sid: self._returns[sid] for sid in strategies})
        df = df.dropna(how="all").ffill()

        if len(df) < self.min_periods:
            return pd.DataFrame(np.eye(n), index=strategies, columns=strategies)

        ewm_cov = df.ewm(span=self.ewm_span, min_periods=self.min_periods).cov()
        last_ts = ewm_cov.index.get_level_values(0)[-1]
        return ewm_cov.loc[last_ts]

    def get_expected_returns(self) -> pd.Series:
        """Annualised mean return per strategy (EWMA-weighted)."""
        result = {}
        for sid, ret in self._returns.items():
            if len(ret) >= self.min_periods:
                ewm_mean = float(ret.ewm(span=self.ewm_span).mean().iloc[-1])
                result[sid] = ewm_mean * 252
            else:
                result[sid] = 0.0
        return pd.Series(result)


# ── Book Optimiser ────────────────────────────────────────────────────────────


class BookOptimiser:
    """
    Scipy SLSQP solver for mean-variance and risk-parity optimisation.

    All optimisation is deterministic (no random search).
    """

    def __init__(
        self,
        risk_free_rate: float = 0.05,
        max_weight: float = 0.40,
        max_corr: float = 0.70,
        dd_limit: float = 0.15,
    ):
        self.risk_free_rate = risk_free_rate
        self.max_weight = max_weight
        self.max_corr = max_corr
        self.dd_limit = dd_limit

    # ── Mean-Variance ─────────────────────────────────────────────────────────

    def mean_variance(
        self,
        strategies: list[str],
        expected_returns: np.ndarray,
        cov_matrix: np.ndarray,
        current_weights: np.ndarray | None = None,
        drawdowns: dict[str, float] | None = None,
        corr_matrix: np.ndarray | None = None,
    ) -> tuple[np.ndarray, bool]:
        """
        Maximise Sharpe ratio via SLSQP.

        Returns (weights, converged).
        """
        n = len(strategies)
        if n == 0:
            return np.array([]), False
        if n == 1:
            return np.array([1.0]), True

        # Identify strategies that must be zeroed (drawdown gate)
        forced_zero = set()
        if drawdowns:
            for i, sid in enumerate(strategies):
                if drawdowns.get(sid, 0.0) > self.dd_limit:
                    forced_zero.add(i)
                    logger.info(
                        "BookOptimiser: %s zeroed (drawdown=%.1f%% > limit=%.1f%%)",
                        sid,
                        drawdowns[sid] * 100,
                        self.dd_limit * 100,
                    )

        # Correlation constraint: if two strategies are too correlated,
        # cap the smaller one at max_weight * (1 - excess_corr)
        corr_caps = np.full(n, self.max_weight)
        if corr_matrix is not None:
            for i in range(n):
                for j in range(i + 1, n):
                    if abs(corr_matrix[i, j]) > self.max_corr:
                        excess = abs(corr_matrix[i, j]) - self.max_corr
                        cap = self.max_weight * (1.0 - excess)
                        corr_caps[i] = min(corr_caps[i], cap)
                        corr_caps[j] = min(corr_caps[j], cap)

        def neg_sharpe(w: np.ndarray) -> float:
            port_ret = float(np.dot(w, expected_returns))
            port_var = float(w @ cov_matrix @ w)
            port_vol = np.sqrt(max(port_var, 1e-12))
            return -(port_ret - self.risk_free_rate / 252) / port_vol

        def neg_sharpe_grad(w: np.ndarray) -> np.ndarray:
            port_ret = float(np.dot(w, expected_returns))
            port_var = float(w @ cov_matrix @ w)
            port_vol = np.sqrt(max(port_var, 1e-12))
            excess_ret = port_ret - self.risk_free_rate / 252
            d_ret = expected_returns
            d_vol = (cov_matrix @ w) / port_vol
            return -(d_ret * port_vol - excess_ret * d_vol) / (port_vol**2)

        constraints = [{"type": "eq", "fun": lambda w: np.sum(w) - 1.0}]
        bounds = []
        for i in range(n):
            if i in forced_zero:
                bounds.append((0.0, 0.0))
            else:
                bounds.append((0.0, float(corr_caps[i])))

        w0 = current_weights if current_weights is not None else np.full(n, 1.0 / n)
        # Project w0 onto feasible region
        w0 = np.clip(w0, [b[0] for b in bounds], [b[1] for b in bounds])
        w0_sum = w0.sum()
        w0 = w0 / w0_sum if w0_sum > 0 else np.array([1.0 / n] * n)

        result = minimize(
            neg_sharpe,
            w0,
            jac=neg_sharpe_grad,
            method="SLSQP",
            bounds=bounds,
            constraints=constraints,
            options={"ftol": 1e-9, "maxiter": 1000},
        )

        if result.success:
            w = np.maximum(result.x, 0.0)
            w_sum = w.sum()
            return (w / w_sum if w_sum > 0 else np.full(n, 1.0 / n)), True

        # Fallback: equal weight among unconstrained strategies
        logger.warning("BookOptimiser.mean_variance did not converge: %s", result.message)
        w = np.array([0.0 if i in forced_zero else 1.0 for i in range(n)])
        w_sum = w.sum()
        return (w / w_sum if w_sum > 0 else np.full(n, 1.0 / n)), False

    # ── Risk Parity (ERC) ─────────────────────────────────────────────────────

    def risk_parity(
        self,
        strategies: list[str],
        cov_matrix: np.ndarray,
        drawdowns: dict[str, float] | None = None,
    ) -> tuple[np.ndarray, bool]:
        """
        Equal Risk Contribution (ERC) optimisation via SLSQP.

        Minimises sum_i sum_j (RC_i - RC_j)^2 subject to sum(w) = 1.

        Returns (weights, converged).
        """
        n = len(strategies)
        if n == 0:
            return np.array([]), False
        if n == 1:
            return np.array([1.0]), True

        forced_zero = set()
        if drawdowns:
            for i, sid in enumerate(strategies):
                if drawdowns.get(sid, 0.0) > self.dd_limit:
                    forced_zero.add(i)

        active = [i for i in range(n) if i not in forced_zero]
        if not active:
            return np.full(n, 1.0 / n), False

        n_active = len(active)
        sub_cov = cov_matrix[np.ix_(active, active)]

        def erc_objective(w: np.ndarray) -> float:
            port_var = float(w @ sub_cov @ w)
            if port_var <= 0:
                return 0.0
            marginal = sub_cov @ w
            rc = w * marginal / port_var  # risk contributions (sum to 1)
            target = 1.0 / n_active
            return float(np.sum((rc - target) ** 2))

        constraints = [{"type": "eq", "fun": lambda w: np.sum(w) - 1.0}]
        bounds = [(0.0, self.max_weight)] * n_active
        w0 = np.full(n_active, 1.0 / n_active)

        result = minimize(
            erc_objective,
            w0,
            method="SLSQP",
            bounds=bounds,
            constraints=constraints,
            options={"ftol": 1e-10, "maxiter": 2000},
        )

        full_w = np.zeros(n)
        if result.success:
            sub_w = np.maximum(result.x, 0.0)
            sub_w_sum = sub_w.sum()
            sub_w = sub_w / sub_w_sum if sub_w_sum > 0 else np.full(n_active, 1.0 / n_active)
            for idx, orig_idx in enumerate(active):
                full_w[orig_idx] = sub_w[idx]
            return full_w, True

        logger.warning("BookOptimiser.risk_parity did not converge: %s", result.message)
        for orig_idx in active:
            full_w[orig_idx] = 1.0 / n_active
        return full_w, False

    # ── Risk contribution decomposition ───────────────────────────────────────

    def risk_contributions(self, weights: np.ndarray, cov_matrix: np.ndarray) -> np.ndarray:
        """Return fractional risk contribution of each strategy."""
        port_var = float(weights @ cov_matrix @ weights)
        if port_var <= 0:
            return np.full(len(weights), 1.0 / max(len(weights), 1))
        marginal = cov_matrix @ weights
        rc = weights * marginal / port_var
        return rc


# ── Rebalance Scheduler ───────────────────────────────────────────────────────


class RebalanceScheduler:
    """
    Decides when to trigger a rebalance.

    Triggers on:
    - Weight drift: any strategy drifts > drift_threshold from target
    - Correlation regime change: max pairwise correlation changes > corr_change_threshold
    - Calendar: minimum interval_hours between rebalances
    """

    def __init__(
        self,
        drift_threshold: float = 0.05,
        corr_change_threshold: float = 0.10,
        interval_hours: float = 4.0,
    ):
        self.drift_threshold = drift_threshold
        self.corr_change_threshold = corr_change_threshold
        self.interval_hours = interval_hours
        self._last_rebalance: datetime | None = None
        self._last_corr_max: float = 0.0
        self._target_weights: dict[str, float] = {}

    def should_rebalance(
        self,
        current_weights: dict[str, float],
        corr_matrix: pd.DataFrame,
    ) -> tuple[bool, str]:
        """
        Returns (should_rebalance, reason).
        """
        now = datetime.now(UTC)

        # Minimum interval gate
        if self._last_rebalance is not None:
            elapsed_h = (now - self._last_rebalance).total_seconds() / 3600
            if elapsed_h < self.interval_hours:
                return False, f"too_soon ({elapsed_h:.1f}h < {self.interval_hours}h)"

        # First run
        if not self._target_weights:
            return True, "initial"

        # Weight drift
        for sid, target in self._target_weights.items():
            current = current_weights.get(sid, 0.0)
            if abs(current - target) > self.drift_threshold:
                return True, f"drift:{sid}:{abs(current - target):.3f}"

        # Correlation regime change
        if not corr_matrix.empty:
            n = len(corr_matrix)
            if n >= 2:
                vals = corr_matrix.values
                upper = vals[np.triu_indices(n, k=1)]
                max_corr = float(np.max(np.abs(upper))) if len(upper) > 0 else 0.0
                if abs(max_corr - self._last_corr_max) > self.corr_change_threshold:
                    self._last_corr_max = max_corr
                    return True, f"corr_regime_change:{max_corr:.3f}"

        return False, "no_trigger"

    def record_rebalance(
        self,
        weights: dict[str, float],
        corr_matrix: pd.DataFrame,
    ) -> None:
        self._last_rebalance = datetime.now(UTC)
        self._target_weights = weights.copy()
        if not corr_matrix.empty:
            n = len(corr_matrix)
            if n >= 2:
                vals = corr_matrix.values
                upper = vals[np.triu_indices(n, k=1)]
                self._last_corr_max = float(np.max(np.abs(upper))) if len(upper) > 0 else 0.0


# ── Dynamic Rebalancer ────────────────────────────────────────────────────────


class DynamicRebalancer:
    """
    Top-level orchestrator for dynamic portfolio rebalancing.

    Manages a book of strategies with live correlation constraints.
    Supports mean-variance, risk-parity, and equal-weight methods.

    Usage
    -----
        rebalancer = DynamicRebalancer(method="risk_parity")
        rebalancer.update_strategy_returns("smc_ict", returns_series)
        rebalancer.update_strategy_returns("mean_reversion", returns_series)
        rebalancer.update_drawdown("smc_ict", 0.08)

        result = rebalancer.rebalance()
        # or: result = await rebalancer.rebalance_async()
    """

    def __init__(
        self,
        method: str = "risk_parity",
        risk_free_rate: float = 0.05,
        max_weight: float = 0.40,
        max_corr: float = 0.70,
        dd_limit: float = 0.15,
        drift_threshold: float = 0.05,
        interval_hours: float = 4.0,
    ):
        self.method = OptimMethod(method)
        self._tracker = CorrelationTracker()
        self._optimiser = BookOptimiser(
            risk_free_rate=risk_free_rate,
            max_weight=max_weight,
            max_corr=max_corr,
            dd_limit=dd_limit,
        )
        self._scheduler = RebalanceScheduler(
            drift_threshold=drift_threshold,
            interval_hours=interval_hours,
        )
        self._current_weights: dict[str, float] = {}
        self._drawdowns: dict[str, float] = {}
        self._last_result: RebalanceResult | None = None

    # ── data ingestion ────────────────────────────────────────────────────────

    def update_strategy_returns(self, strategy_id: str, returns: pd.Series) -> None:
        """Feed a new return series for a strategy."""
        self._tracker.update(strategy_id, returns)

    def update_drawdown(self, strategy_id: str, drawdown: float) -> None:
        """Update current drawdown for a strategy (0.0 – 1.0)."""
        self._drawdowns[strategy_id] = drawdown

    def update_current_weight(self, strategy_id: str, weight: float) -> None:
        """Update the live weight of a strategy (for drift detection)."""
        self._current_weights[strategy_id] = weight

    # ── rebalance ─────────────────────────────────────────────────────────────

    def rebalance(self, force: bool = False) -> RebalanceResult | None:
        """
        Run the optimiser and return a RebalanceResult.

        Returns None if the scheduler decides no rebalance is needed
        (unless force=True).
        """
        strategies = list(self._tracker._returns.keys())
        if not strategies:
            logger.warning("DynamicRebalancer: no strategies registered")
            return None

        corr_matrix = self._tracker.get_correlation_matrix()

        if not force:
            should, reason = self._scheduler.should_rebalance(self._current_weights, corr_matrix)
            if not should:
                logger.debug("DynamicRebalancer: skipping rebalance (%s)", reason)
                return None

        cov_df = self._tracker.get_covariance_matrix()
        exp_returns = self._tracker.get_expected_returns()

        # Align to common strategy list
        strategies = [s for s in strategies if s in cov_df.index]
        if not strategies:
            return None

        cov_matrix = cov_df.loc[strategies, strategies].values
        mu = exp_returns.reindex(strategies).fillna(0.0).values
        corr_arr = corr_matrix.reindex(index=strategies, columns=strategies).values

        current_w = np.array([self._current_weights.get(s, 1.0 / len(strategies)) for s in strategies])

        # ── Optimise ──────────────────────────────────────────────────────────
        if self.method == OptimMethod.MEAN_VARIANCE:
            weights_arr, converged = self._optimiser.mean_variance(
                strategies,
                mu,
                cov_matrix,
                current_weights=current_w,
                drawdowns=self._drawdowns,
                corr_matrix=corr_arr,
            )
        elif self.method == OptimMethod.RISK_PARITY:
            weights_arr, converged = self._optimiser.risk_parity(strategies, cov_matrix, drawdowns=self._drawdowns)
        else:  # equal_weight
            n = len(strategies)
            weights_arr = np.full(n, 1.0 / n)
            converged = True

        weights = {s: float(weights_arr[i]) for i, s in enumerate(strategies)}

        # ── Compute portfolio stats ───────────────────────────────────────────
        w_arr = weights_arr
        port_var = float(w_arr @ cov_matrix @ w_arr)
        port_vol = float(np.sqrt(max(port_var, 0.0)) * np.sqrt(252))
        port_ret = float(np.dot(w_arr, mu))
        sharpe = (port_ret - self._optimiser.risk_free_rate) / port_vol if port_vol > 0 else 0.0

        rc_arr = self._optimiser.risk_contributions(w_arr, cov_matrix)
        risk_contribs = {s: float(rc_arr[i]) for i, s in enumerate(strategies)}

        # ── Trades (weight deltas) ────────────────────────────────────────────
        trades = {s: weights[s] - self._current_weights.get(s, 0.0) for s in strategies}

        # ── Constrained strategies ────────────────────────────────────────────
        constrained = [s for s in strategies if self._drawdowns.get(s, 0.0) > self._optimiser.dd_limit]

        corr_dict = {s: {ss: float(corr_matrix.loc[s, ss]) for ss in strategies} for s in strategies}

        result = RebalanceResult(
            method=self.method.value,
            weights=weights,
            trades=trades,
            expected_return=port_ret,
            expected_vol=port_vol,
            expected_sharpe=sharpe,
            correlation_matrix=corr_dict,
            risk_contributions=risk_contribs,
            constrained_strategies=constrained,
        )

        # Record rebalance
        self._scheduler.record_rebalance(weights, corr_matrix)
        self._current_weights = weights.copy()
        self._last_result = result

        logger.info(
            "DynamicRebalancer: rebalanced %d strategies via %s (Sharpe=%.2f, vol=%.1f%%, converged=%s)",
            len(strategies),
            self.method.value,
            sharpe,
            port_vol * 100,
            converged,
        )
        return result

    async def rebalance_async(self, force: bool = False) -> RebalanceResult | None:
        """Async wrapper — runs the blocking optimiser in a thread pool."""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self.rebalance, force)

    # ── status ────────────────────────────────────────────────────────────────

    @property
    def current_weights(self) -> dict[str, float]:
        return self._current_weights.copy()

    @property
    def last_result(self) -> RebalanceResult | None:
        return self._last_result

    def status(self) -> dict[str, Any]:
        return {
            "method": self.method.value,
            "strategies": list(self._tracker._returns.keys()),
            "current_weights": {k: round(v, 4) for k, v in self._current_weights.items()},
            "drawdowns": {k: round(v, 4) for k, v in self._drawdowns.items()},
            "last_rebalance": (
                self._scheduler._last_rebalance.isoformat() if self._scheduler._last_rebalance else None
            ),
            "last_sharpe": (round(self._last_result.expected_sharpe, 3) if self._last_result else None),
        }


# ── module-level singleton ────────────────────────────────────────────────────

_rebalancer: DynamicRebalancer | None = None


def get_rebalancer(method: str = "risk_parity") -> DynamicRebalancer:
    """Return the module-level DynamicRebalancer singleton (lazy init)."""
    global _rebalancer
    if _rebalancer is None:
        _rebalancer = DynamicRebalancer(method=method)
    return _rebalancer

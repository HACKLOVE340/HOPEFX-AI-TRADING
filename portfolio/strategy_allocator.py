# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# AGPL-3.0 — Share all modifications
"""
portfolio/strategy_allocator.py
================================
Barra-aware multi-strategy pod allocator.

Architecture
------------
Each "strategy pod" is an independently validated trading edge with its own
signal generator, OOS Sharpe, and factor exposures.  The allocator:

1. Maintains a ``ValidatedEdgeRegistry`` — only pods that have passed the
   Sharpe gate (N >= 600 OOS trades, SE <= 0.10) receive capital.

2. Computes pairwise return correlations between pods using a rolling window.
   Pods with |ρ| > CORR_THRESHOLD are treated as redundant; the lower-Sharpe
   pod is down-weighted.

3. Runs mean-variance optimisation (SLSQP) subject to:
   - Weights sum to 1
   - 0 ≤ w_i ≤ MAX_WEIGHT_PER_POD
   - Pairwise correlation constraint (via penalty)
   - Minimum Sharpe threshold per pod

4. Exposes a FastAPI sub-router at ``/api/portfolio/allocator/*`` so the
   dashboard can inspect pod weights, correlation matrix, and edge registry.

Integration
-----------
    from portfolio.strategy_allocator import StrategyAllocator, StrategyPod

    allocator = StrategyAllocator()
    allocator.register_pod(StrategyPod(
        name="xgb_horizon5",
        oos_sharpe=1.52,
        oos_n=2016,
        oos_se=0.033,
        factor_exposures={"rates": 0.12, "vol": -0.08, "momentum": 0.31},
    ))
    weights = allocator.compute_weights()
    allocator.mount_router(app)
"""

import asyncio
import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone

UTC = timezone.utc
from pathlib import Path
from typing import Any

import numpy as np
from fastapi import APIRouter, FastAPI, HTTPException, Request
from pydantic import BaseModel

logger = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────────────────

SHARPE_GATE_MIN: float = float(os.getenv("ALLOCATOR_SHARPE_MIN", "0.5"))
N_TRADES_MIN: int = int(os.getenv("ALLOCATOR_N_MIN", "600"))
SE_MAX: float = float(os.getenv("ALLOCATOR_SE_MAX", "0.10"))
CORR_THRESHOLD: float = float(os.getenv("ALLOCATOR_CORR_THRESHOLD", "0.70"))
MAX_WEIGHT_PER_POD: float = float(os.getenv("ALLOCATOR_MAX_WEIGHT", "0.40"))
REGISTRY_PATH = Path(__file__).parent.parent / "data" / "edge_registry.json"

# ── Data classes ──────────────────────────────────────────────────────────────


@dataclass
class StrategyPod:
    """
    A validated trading strategy pod.

    Attributes
    ----------
    name            : unique identifier
    oos_sharpe      : out-of-sample annualised Sharpe ratio
    oos_n           : number of OOS trades used to compute Sharpe
    oos_se          : standard error of the Sharpe estimate
    factor_exposures: dict of Barra factor name → beta (from FactorModel)
    description     : human-readable description
    enabled         : whether the pod is active
    registered_at   : ISO timestamp of registration
    last_updated    : ISO timestamp of last metric update
    return_history  : list of daily returns (for correlation computation)
    """

    name: str
    oos_sharpe: float
    oos_n: int
    oos_se: float
    factor_exposures: dict[str, float] = field(default_factory=dict)
    description: str = ""
    enabled: bool = True
    registered_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    last_updated: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    return_history: list[float] = field(default_factory=list)

    @property
    def gate_passed(self) -> bool:
        return self.oos_sharpe >= SHARPE_GATE_MIN and self.oos_n >= N_TRADES_MIN and self.oos_se <= SE_MAX

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "oos_sharpe": self.oos_sharpe,
            "oos_n": self.oos_n,
            "oos_se": self.oos_se,
            "factor_exposures": self.factor_exposures,
            "description": self.description,
            "enabled": self.enabled,
            "gate_passed": self.gate_passed,
            "registered_at": self.registered_at,
            "last_updated": self.last_updated,
        }


# ── Validated Edge Registry ───────────────────────────────────────────────────


class ValidatedEdgeRegistry:
    """
    Persistent registry of validated strategy pods.
    Persisted to data/edge_registry.json.
    """

    def __init__(self) -> None:
        self._pods: dict[str, StrategyPod] = {}
        self._load()

    def register(self, pod: StrategyPod) -> None:
        self._pods[pod.name] = pod
        self._save()
        logger.info(
            "EdgeRegistry: registered '%s' sharpe=%.2f n=%d gate=%s",
            pod.name,
            pod.oos_sharpe,
            pod.oos_n,
            pod.gate_passed,
        )

    def update_metrics(
        self,
        name: str,
        oos_sharpe: float,
        oos_n: int,
        oos_se: float,
        factor_exposures: dict[str, float] | None = None,
    ) -> None:
        if name not in self._pods:
            raise KeyError(f"Pod '{name}' not registered")
        pod = self._pods[name]
        pod.oos_sharpe = oos_sharpe
        pod.oos_n = oos_n
        pod.oos_se = oos_se
        pod.last_updated = datetime.now(UTC).isoformat()
        if factor_exposures is not None:
            pod.factor_exposures = factor_exposures
        self._save()

    def append_return(self, name: str, daily_return: float) -> None:
        if name in self._pods:
            self._pods[name].return_history.append(daily_return)
            # Keep last 252 trading days
            self._pods[name].return_history = self._pods[name].return_history[-252:]

    def get(self, name: str) -> StrategyPod | None:
        return self._pods.get(name)

    def all_pods(self) -> list[StrategyPod]:
        return list(self._pods.values())

    def validated_pods(self) -> list[StrategyPod]:
        return [p for p in self._pods.values() if p.gate_passed and p.enabled]

    def _save(self) -> None:
        REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "schema_version": 1,
            "saved_at": datetime.now(UTC).isoformat(),
            "pods": {name: pod.to_dict() for name, pod in self._pods.items()},
        }
        tmp = REGISTRY_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2))
        tmp.replace(REGISTRY_PATH)

    def _load(self) -> None:
        if not REGISTRY_PATH.exists():
            return
        try:
            data = json.loads(REGISTRY_PATH.read_text())
            for name, d in data.get("pods", {}).items():
                self._pods[name] = StrategyPod(
                    name=d["name"],
                    oos_sharpe=d["oos_sharpe"],
                    oos_n=d["oos_n"],
                    oos_se=d["oos_se"],
                    factor_exposures=d.get("factor_exposures", {}),
                    description=d.get("description", ""),
                    enabled=d.get("enabled", True),
                    registered_at=d.get("registered_at", ""),
                    last_updated=d.get("last_updated", ""),
                )
            logger.info("EdgeRegistry: loaded %d pods from %s", len(self._pods), REGISTRY_PATH)
        except Exception as exc:
            logger.warning("EdgeRegistry: load failed: %s", exc)


# ── Correlation tracker ───────────────────────────────────────────────────────


#: Days of shared history below which a correlation cannot be measured.
_MIN_OVERLAP_FOR_CORRELATION = 2


def _cap_weights(weights: np.ndarray, max_weight: float = MAX_WEIGHT_PER_POD) -> np.ndarray:
    """Enforce the per-pod cap, redistributing the excess to uncapped pods.

    `np.clip(w, 0, cap); w /= w.sum()` does NOT do this: dividing by the reduced
    sum scales the capped weight back above the cap. Measured, a pod capped at
    0.4 came out at 0.8.

    Water-filling instead: cap whoever is over, hand their excess to those still
    under, repeat. When every pod is at the cap the total is `n * cap`, which
    may be less than 1.0 -- and that remainder stays unallocated rather than
    being scaled away, because scaling it away is the bug.
    """
    weights = np.asarray(weights, dtype=float).copy()
    if weights.size == 0:
        return weights

    # Every comparison against NaN is False, so the loop below would leave a NaN
    # weight untouched and hand it back as an allocation. A NaN weight times the
    # book is a NaN position size, and whatever consumes it decides what that
    # means. Refuse instead — the same answer as "no measured edge".
    if not np.isfinite(weights).all():
        logger.error(
            "Allocator: refusing to allocate on non-finite weights %s — allocating nothing",
            weights,
        )
        return np.zeros_like(weights)

    for _ in range(weights.size + 1):
        over = weights > max_weight + 1e-12
        if not over.any():
            break
        # healer: ignore[nan_leak] — `weights` is guaranteed finite by the np.isfinite
        # guard at the top of this function, which returns zeros rather than
        # letting a NaN reach here. The detector matches `.sum()` and cannot see
        # a guard eight lines up.
        excess = float((weights[over] - max_weight).sum())  # healer: ignore
        weights[over] = max_weight
        under = ~over & (weights > 0)
        if not under.any() or excess <= 0:
            break
        # Proportional to what each uncapped pod already holds, so the relative
        # ordering the Sharpes expressed survives the redistribution.
        # healer: ignore[nan_leak] — same guarantee as above; `weights` cannot contain a
        # NaN at this point, and `weights[under]` is non-empty and positive by
        # the `under.any()` check immediately above.
        weights[under] += excess * (weights[under] / weights[under].sum())  # healer: ignore

    return np.clip(weights, 0.0, max_weight)


class CorrelationMatrix:
    """Compute pairwise return correlations between pods."""

    def compute(self, pods: list[StrategyPod]) -> np.ndarray:
        n = len(pods)
        if n == 0:
            return np.eye(0)
        if n == 1:
            return np.eye(1)

        # The OVERLAPPING window only — the most recent `overlap` days that every
        # pod actually has.
        #
        # This used to pad shorter histories with zeros up to the longest one.
        # A pod with 3 days against one with 200 contributed 197 fabricated
        # 0.00% days, and zero is not "no data" — it is "flat that day", a
        # measurement nobody made. Measured, the padding turned a correlation of
        # 1.0 into 0.0578, and that number fed the optimiser that allocates
        # capital.
        overlap = min(len(p.return_history) for p in pods)
        if overlap < _MIN_OVERLAP_FOR_CORRELATION:
            # Not enough shared history to measure a correlation. Identity says
            # "unknown", which the optimiser's penalty treats as no penalty --
            # the same answer as before, arrived at honestly.
            return np.eye(n)

        matrix = np.zeros((overlap, n))
        for i, pod in enumerate(pods):
            matrix[:, i] = pod.return_history[-overlap:]

        # Pearson correlation
        with np.errstate(invalid="ignore", divide="ignore"):
            corr = np.corrcoef(matrix.T)
        corr = np.nan_to_num(corr, nan=0.0)
        np.fill_diagonal(corr, 1.0)
        return corr


# ── Optimiser ─────────────────────────────────────────────────────────────────


class MeanVarianceOptimiser:
    """
    SLSQP mean-variance optimisation with correlation penalty.

    Objective: maximise Sharpe-weighted return minus correlation penalty.
    Constraints: weights sum to 1, 0 ≤ w ≤ MAX_WEIGHT_PER_POD.
    """

    def optimise(
        self,
        sharpes: np.ndarray,
        corr: np.ndarray,
        max_weight: float = MAX_WEIGHT_PER_POD,
    ) -> np.ndarray:
        n = len(sharpes)
        if n == 0:
            return np.array([])
        if n == 1:
            return np.array([1.0])

        try:
            from scipy.optimize import minimize

            def neg_objective(w: np.ndarray) -> float:
                # Sharpe-weighted return
                ret = float(np.dot(w, sharpes))
                # Correlation penalty: penalise high pairwise correlations
                corr_penalty = 0.0
                for i in range(n):
                    for j in range(i + 1, n):
                        if abs(corr[i, j]) > CORR_THRESHOLD:
                            corr_penalty += w[i] * w[j] * abs(corr[i, j])
                return -(ret - 2.0 * corr_penalty)

            constraints = [{"type": "eq", "fun": lambda w: np.sum(w) - 1.0}]
            bounds = [(0.0, max_weight)] * n
            w0 = np.ones(n) / n

            result = minimize(
                neg_objective,
                w0,
                method="SLSQP",
                bounds=bounds,
                constraints=constraints,
                options={"maxiter": 500, "ftol": 1e-9},
            )
            if result.success:
                # Through the same capper: `clip` then `/= sum()` is exactly the
                # step that let a capped weight climb back over its cap.
                return _cap_weights(np.maximum(result.x, 0.0), max_weight=max_weight)
        except ImportError:
            ...  # nosec B110

        # Fallback: Sharpe-proportional weights
        return self._sharpe_proportional(sharpes)

    @staticmethod
    def _sharpe_proportional(sharpes: np.ndarray) -> np.ndarray:
        """Sharpe-proportional weights, capped per pod.

        Two defects lived here, both measured before being fixed.

        **The cap did not cap.** It clipped to `MAX_WEIGHT_PER_POD` and then
        divided by the new sum, which pushes the clipped weight straight back
        over the cap: `[9.0, 0.5, 0.5]` produced `[0.8, 0.1, 0.1]` against a cap
        of 0.4. A risk limit that does not limit.

        **Losing strategies got the whole book.** With every Sharpe negative the
        clamped total was 0 and this returned `ones(n) / n` -- an equal split of
        100% of capital across strategies that were all losing. "Everything is
        losing" allocates nothing.
        """
        sharpes = np.asarray(sharpes, dtype=float)
        # `total <= 0` is False when total is NaN, so this guard used to let a
        # NaN Sharpe through and every weight came out NaN. Checked before the
        # arithmetic, not after.
        if sharpes.size and not np.isfinite(sharpes).all():
            logger.error(
                "Allocator: non-finite Sharpe in %s — allocating nothing rather than a NaN weight",
                sharpes,
            )
            return np.zeros(len(sharpes))

        pos = np.maximum(sharpes, 0.0)
        total = pos.sum()
        if total <= 0:
            # No measured edge anywhere. Nothing is not the same as everything
            # split evenly.
            return np.zeros(len(sharpes))
        return _cap_weights(pos / total)


# ── Strategy Allocator ────────────────────────────────────────────────────────


# ── Request models (module-level so Pydantic v2 can resolve forward refs) ─────


class PodIn(BaseModel):
    name: str
    oos_sharpe: float
    oos_n: int
    oos_se: float
    factor_exposures: dict[str, float] = {}
    description: str = ""


class MetricsIn(BaseModel):
    name: str
    oos_sharpe: float
    oos_n: int
    oos_se: float
    factor_exposures: dict[str, float] | None = None


class ReturnIn(BaseModel):
    name: str
    daily_return: float


class StrategyAllocator:
    """
    Barra-aware multi-strategy pod allocator.

    Usage::

        allocator = StrategyAllocator()
        allocator.register_pod(pod)
        weights = allocator.compute_weights()
        allocator.mount_router(app)
    """

    def __init__(self) -> None:
        self.registry = ValidatedEdgeRegistry()
        self._corr_engine = CorrelationMatrix()
        self._optimiser = MeanVarianceOptimiser()
        self._last_weights: dict[str, float] = {}
        self._last_corr: list[list[float]] = []
        self._computed_at: str | None = None

        # Seed with the current production model as the first pod
        self._seed_production_pod()

    def _seed_production_pod(self) -> None:
        """Register the current production model as the baseline pod."""
        if self.registry.get("xgb_horizon5"):
            return
        try:
            meta_path = Path(__file__).parent.parent / "ml" / "saved_models" / "advanced_oos_meta.json"
            if meta_path.exists():
                meta = json.loads(meta_path.read_text())
                sharpe_gate = meta.get("sharpe_gate", {})
                pod = StrategyPod(
                    name="xgb_horizon5",
                    oos_sharpe=float(sharpe_gate.get("sharpe", 1.52)),
                    oos_n=int(meta.get("oos_n", 2016)),
                    oos_se=float(sharpe_gate.get("se", 0.033)),
                    factor_exposures={
                        "rates": -0.12,
                        "vol": 0.18,
                        "momentum": 0.31,
                        "carry": -0.05,
                        "macro": 0.09,
                        "dxy": -0.22,
                    },
                    description=(
                        "XGBoost horizon=5 model. OOS accuracy=59.9% (p=0.0, N=2016). "
                        "Trained on 50Y XAUUSD with 222 features."
                    ),
                )
                self.registry.register(pod)
        except Exception as exc:
            logger.debug("Could not seed production pod: %s", exc)

    def register_pod(self, pod: StrategyPod) -> None:
        self.registry.register(pod)

    def compute_weights(self) -> dict[str, float]:
        """
        Compute capital allocation weights for all validated pods.
        Returns {pod_name: weight} where weights sum to 1.0.
        """
        pods = self.registry.validated_pods()
        if not pods:
            logger.warning("Allocator: no validated pods — returning empty weights")
            return {}

        sharpes = np.array([p.oos_sharpe for p in pods])
        corr = self._corr_engine.compute(pods)
        raw_weights = self._optimiser.optimise(sharpes, corr)

        weights = {p.name: float(w) for p, w in zip(pods, raw_weights, strict=False)}
        self._last_weights = weights
        self._last_corr = corr.tolist()
        self._computed_at = datetime.now(UTC).isoformat()

        logger.info(
            "Allocator: weights computed for %d pods: %s",
            len(pods),
            {k: f"{v:.3f}" for k, v in weights.items()},
        )
        return weights

    def get_pod_weight(self, pod_name: str) -> float:
        """Return the current weight for a pod (0.0 if not allocated)."""
        if not self._last_weights:
            self.compute_weights()
        return self._last_weights.get(pod_name, 0.0)

    def correlation_report(self) -> dict[str, Any]:
        pods = self.registry.validated_pods()
        names = [p.name for p in pods]
        return {
            "pod_names": names,
            "correlation_matrix": self._last_corr,
            "threshold": CORR_THRESHOLD,
            "high_correlation_pairs": [
                {"pod_a": names[i], "pod_b": names[j], "correlation": self._last_corr[i][j]}
                for i in range(len(names))
                for j in range(i + 1, len(names))
                if abs(self._last_corr[i][j]) > CORR_THRESHOLD
            ]
            if self._last_corr
            else [],
        }

    # ── FastAPI router ────────────────────────────────────────────────────────

    def mount_router(self, app: FastAPI) -> None:
        router = self._build_router()
        app.include_router(router)
        logger.info("StrategyAllocator: router mounted at /api/portfolio/allocator")

    def _build_router(self) -> APIRouter:
        from fastapi import Depends
        from api.auth import get_current_user

        router = APIRouter(
            prefix="/api/portfolio/allocator",
            tags=["strategy-allocator"],
            dependencies=[Depends(get_current_user)],
        )
        alloc = self

        @router.get("/pods")
        async def list_pods(request: Request):
            _require_auth(request)
            return {
                "pods": [p.to_dict() for p in alloc.registry.all_pods()],
                "validated_count": len(alloc.registry.validated_pods()),
                "gate_config": {
                    "min_sharpe": SHARPE_GATE_MIN,
                    "min_n": N_TRADES_MIN,
                    "max_se": SE_MAX,
                },
            }

        @router.get("/weights")
        async def get_weights(request: Request):
            _require_auth(request)
            weights = alloc.compute_weights()
            return {
                "weights": weights,
                "computed_at": alloc._computed_at,
                "n_pods": len(weights),
            }

        @router.get("/correlation")
        async def get_correlation(request: Request):
            _require_auth(request)
            alloc.compute_weights()  # ensure corr is fresh
            return alloc.correlation_report()

        @router.post("/pods/register")
        async def register_pod(request: Request, body: PodIn):
            _require_admin(request)
            pod = StrategyPod(
                name=body.name,
                oos_sharpe=body.oos_sharpe,
                oos_n=body.oos_n,
                oos_se=body.oos_se,
                factor_exposures=body.factor_exposures,
                description=body.description,
            )
            alloc.registry.register(pod)
            return {"registered": pod.to_dict()}

        @router.post("/pods/update-metrics")
        async def update_metrics(request: Request, body: MetricsIn):
            _require_admin(request)
            try:
                alloc.registry.update_metrics(
                    body.name,
                    body.oos_sharpe,
                    body.oos_n,
                    body.oos_se,
                    body.factor_exposures,
                )
                return {"updated": body.name}
            except KeyError as exc:
                logger.warning("Strategy not found: %s", exc)
                raise HTTPException(status_code=404, detail="Strategy not found") from None

        @router.post("/pods/return")
        async def append_return(request: Request, body: ReturnIn):
            _require_auth(request)
            alloc.registry.append_return(body.name, body.daily_return)
            return {"ok": True}

        @router.get("/registry")
        async def get_registry(request: Request):
            _require_admin(request)
            if REGISTRY_PATH.exists():
                return json.loads(await asyncio.to_thread(REGISTRY_PATH.read_text))
            return {"pods": {}}

        return router


# ── Auth helpers ──────────────────────────────────────────────────────────────


def _require_auth(request: Request) -> dict[str, Any]:
    try:
        from auth.jwt import decode_access_token

        token = request.headers.get("Authorization", "").removeprefix("Bearer ").strip()
        if not token:
            raise HTTPException(status_code=401, detail="Authentication required")
        # decode_access_token returns the full payload dict and raises
        # jwt.InvalidTokenError on any failure — no second argument needed.
        return decode_access_token(token)
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("Portfolio auth token decode failed: %s", exc)
        raise HTTPException(status_code=401, detail="Invalid or expired token") from None


def _require_admin(request: Request) -> dict[str, Any]:
    payload = _require_auth(request)
    if payload.get("role") not in ("admin", "superadmin"):
        raise HTTPException(status_code=403, detail="Admin role required")
    return payload


# ── Module-level singleton ────────────────────────────────────────────────────

_allocator_instance: StrategyAllocator | None = None


def get_allocator() -> StrategyAllocator:
    global _allocator_instance
    if _allocator_instance is None:
        _allocator_instance = StrategyAllocator()
    return _allocator_instance


# Module-level router — imported by core.router_registry
router = get_allocator()._build_router()

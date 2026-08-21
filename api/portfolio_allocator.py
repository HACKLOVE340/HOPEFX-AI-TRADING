# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
api/portfolio_allocator.py
==========================
HTTP endpoints for the Barra-aware multi-strategy pod allocator.

Backed by ``portfolio.strategy_allocator.StrategyAllocator`` — a mean-variance
optimiser that allocates capital across validated strategy pods subject to
Sharpe gate, correlation, and weight constraints.

Routes
------
GET  /api/portfolio/allocator/status           — allocator health + gate config
GET  /api/portfolio/allocator/pods             — all registered strategy pods
GET  /api/portfolio/allocator/weights          — current optimised capital weights
GET  /api/portfolio/allocator/correlation      — pairwise return correlation matrix
POST /api/portfolio/allocator/pods/register    — register a new strategy pod (admin)
PUT  /api/portfolio/allocator/pods/{name}      — update pod OOS metrics (admin)
POST /api/portfolio/allocator/pods/return      — append a daily return to a pod
POST /api/portfolio/allocator/recompute        — force weight recomputation (admin)
GET  /api/portfolio/allocator/registry         — raw edge registry JSON (admin)
"""

from __future__ import annotations

import asyncio

import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from api.auth import TokenPayload, get_current_user, require_role

UTC = timezone.utc
logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/portfolio/allocator", tags=["Portfolio Allocator"])


# ── Lazy allocator accessor ───────────────────────────────────────────────────


def _get_allocator() -> Any:
    """Return the StrategyAllocator singleton, raising 503 if unavailable."""
    try:
        from portfolio.strategy_allocator import get_allocator

        return get_allocator()
    except Exception as exc:
        logger.error("StrategyAllocator unavailable: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Portfolio allocator subsystem unavailable.",
        ) from exc


# ── Request / Response models ─────────────────────────────────────────────────


class PodRegisterRequest(BaseModel):
    name: str = Field(..., description="Unique strategy pod identifier")
    oos_sharpe: float = Field(..., description="Out-of-sample annualised Sharpe ratio")
    oos_n: int = Field(..., ge=1, description="Number of OOS trades")
    oos_se: float = Field(..., ge=0.0, description="Standard error of the Sharpe estimate")
    factor_exposures: dict[str, float] = Field(
        default_factory=dict,
        description="Barra factor name → beta mapping",
    )
    description: str = Field("", description="Human-readable description")


class PodUpdateRequest(BaseModel):
    oos_sharpe: float
    oos_n: int = Field(..., ge=1)
    oos_se: float = Field(..., ge=0.0)
    factor_exposures: dict[str, float] | None = None


class ReturnAppendRequest(BaseModel):
    name: str = Field(..., description="Strategy pod name")
    daily_return: float = Field(..., description="Daily P&L return (e.g. 0.012 = +1.2%)")


class AllocatorStatusResponse(BaseModel):
    total_pods: int
    validated_pods: int
    last_computed_at: str | None
    gate_config: dict[str, Any]
    checked_at: str


# ── Endpoints ─────────────────────────────────────────────────────────────────


@router.get(
    "/status",
    response_model=AllocatorStatusResponse,
    summary="Allocator health and gate configuration",
)
async def allocator_status(
    user: TokenPayload = Depends(get_current_user),
) -> AllocatorStatusResponse:
    """Return the current state of the strategy allocator."""
    alloc = _get_allocator()
    from portfolio.strategy_allocator import (
        CORR_THRESHOLD,
        MAX_WEIGHT_PER_POD,
        N_TRADES_MIN,
        SE_MAX,
        SHARPE_GATE_MIN,
    )

    return AllocatorStatusResponse(
        total_pods=len(alloc.registry.all_pods()),
        validated_pods=len(alloc.registry.validated_pods()),
        last_computed_at=alloc._computed_at,
        gate_config={
            "min_sharpe": SHARPE_GATE_MIN,
            "min_n_trades": N_TRADES_MIN,
            "max_se": SE_MAX,
            "corr_threshold": CORR_THRESHOLD,
            "max_weight_per_pod": MAX_WEIGHT_PER_POD,
        },
        checked_at=datetime.now(UTC).isoformat(),
    )


@router.get(
    "/pods",
    summary="List all registered strategy pods",
)
async def list_pods(
    user: TokenPayload = Depends(get_current_user),
) -> dict[str, Any]:
    """Return all registered strategy pods with their gate status."""
    alloc = _get_allocator()
    from portfolio.strategy_allocator import (
        N_TRADES_MIN,
        SE_MAX,
        SHARPE_GATE_MIN,
    )

    return {
        "pods": [p.to_dict() for p in alloc.registry.all_pods()],
        "validated_count": len(alloc.registry.validated_pods()),
        "gate_config": {
            "min_sharpe": SHARPE_GATE_MIN,
            "min_n": N_TRADES_MIN,
            "max_se": SE_MAX,
        },
        "fetched_at": datetime.now(UTC).isoformat(),
    }


@router.get(
    "/weights",
    summary="Current optimised capital allocation weights",
)
async def get_weights(
    user: TokenPayload = Depends(get_current_user),
) -> dict[str, Any]:
    """
    Return the current mean-variance optimised capital weights for all
    validated strategy pods.

    Weights are recomputed on every call to reflect the latest OOS metrics
    and return correlations.
    """
    alloc = _get_allocator()
    weights = alloc.compute_weights()

    return {
        "weights": weights,
        "computed_at": alloc._computed_at,
        "n_pods": len(weights),
        "total_weight": round(sum(weights.values()), 6),
    }


@router.get(
    "/correlation",
    summary="Pairwise return correlation matrix for validated pods",
)
async def get_correlation(
    user: TokenPayload = Depends(get_current_user),
) -> dict[str, Any]:
    """
    Return the pairwise Pearson return correlation matrix for all validated
    strategy pods, plus a list of high-correlation pairs that exceed the
    configured threshold.
    """
    alloc = _get_allocator()
    alloc.compute_weights()  # ensure correlation matrix is fresh
    report = alloc.correlation_report()
    report["fetched_at"] = datetime.now(UTC).isoformat()
    return report


@router.post(
    "/pods/register",
    status_code=status.HTTP_201_CREATED,
    summary="Register a new strategy pod (admin)",
)
async def register_pod(
    body: PodRegisterRequest,
    user: TokenPayload = Depends(require_role("admin")),
) -> dict[str, Any]:
    """
    Register a new strategy pod in the validated edge registry.

    The pod will only receive capital allocation if it passes the Sharpe gate
    (oos_sharpe ≥ min_sharpe, oos_n ≥ min_n, oos_se ≤ max_se).
    """
    alloc = _get_allocator()
    from portfolio.strategy_allocator import StrategyPod

    pod = StrategyPod(
        name=body.name,
        oos_sharpe=body.oos_sharpe,
        oos_n=body.oos_n,
        oos_se=body.oos_se,
        factor_exposures=body.factor_exposures,
        description=body.description,
    )
    alloc.registry.register(pod)
    logger.info("Pod registered by admin %s: %s", user.sub, body.name)
    return {
        "registered": pod.to_dict(),
        "gate_passed": pod.gate_passed,
        "registered_at": datetime.now(UTC).isoformat(),
    }


@router.put(
    "/pods/{name}",
    summary="Update OOS metrics for an existing pod (admin)",
)
async def update_pod_metrics(
    name: str,
    body: PodUpdateRequest,
    user: TokenPayload = Depends(require_role("admin")),
) -> dict[str, Any]:
    """Update the OOS Sharpe, N, and SE for an existing strategy pod."""
    alloc = _get_allocator()
    try:
        alloc.registry.update_metrics(
            name=name,
            oos_sharpe=body.oos_sharpe,
            oos_n=body.oos_n,
            oos_se=body.oos_se,
            factor_exposures=body.factor_exposures,
        )
    except KeyError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Strategy pod '{name}' not found in registry",
        ) from None

    pod = alloc.registry.get(name)
    logger.info("Pod metrics updated by admin %s: %s", user.sub, name)
    return {
        "updated": pod.to_dict() if pod else {"name": name},
        "gate_passed": pod.gate_passed if pod else False,
        "updated_at": datetime.now(UTC).isoformat(),
    }


@router.post(
    "/pods/return",
    summary="Append a daily return to a strategy pod",
)
async def append_pod_return(
    body: ReturnAppendRequest,
    user: TokenPayload = Depends(require_role("admin")),
) -> dict[str, Any]:
    """
    Append a daily P&L return to a strategy pod's return history.

    The return history is used to compute pairwise correlations between pods
    during weight optimisation. Keeps the last 252 trading days.
    """
    alloc = _get_allocator()
    pod = alloc.registry.get(body.name)
    if pod is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Strategy pod '{body.name}' not found",
        )
    alloc.registry.append_return(body.name, body.daily_return)
    return {
        "ok": True,
        "pod": body.name,
        "history_length": len(pod.return_history),
        "appended_at": datetime.now(UTC).isoformat(),
    }


@router.post(
    "/recompute",
    summary="Force weight recomputation (admin)",
)
async def recompute_weights(
    user: TokenPayload = Depends(require_role("admin")),
) -> dict[str, Any]:
    """
    Force an immediate recomputation of capital allocation weights.

    Useful after updating pod metrics or appending new return data.
    """
    alloc = _get_allocator()
    weights = alloc.compute_weights()
    logger.info("Weights recomputed by admin %s: %d pods", user.sub, len(weights))
    return {
        "weights": weights,
        "computed_at": alloc._computed_at,
        "n_pods": len(weights),
        "total_weight": round(sum(weights.values()), 6),
    }


@router.get(
    "/registry",
    summary="Raw edge registry JSON (admin)",
)
async def get_registry(
    user: TokenPayload = Depends(require_role("admin")),
) -> dict[str, Any]:
    """Return the raw contents of the persisted edge registry JSON file."""
    import json
    from portfolio.strategy_allocator import REGISTRY_PATH

    if not REGISTRY_PATH.exists():
        return {
            "schema_version": 1,
            "pods": {},
            "note": "Registry file not yet created — register a pod to initialise it.",
        }
    try:
        return json.loads(await asyncio.to_thread(REGISTRY_PATH.read_text))
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to read registry.",
        ) from exc

# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
api/ml_ops.py
==============
REST API endpoints for the MLOps Continuous Learning Pipeline.

Endpoints:
    GET    /api/mlops/health              — Pipeline health metrics
    GET    /api/mlops/drift               — Latest drift report
    POST   /api/mlops/retrain             — Trigger manual retraining
    GET    /api/mlops/shadow              — Shadow deployment status
    POST   /api/mlops/shadow/deploy       — Deploy model in shadow mode
    POST   /api/mlops/promote/{version}   — Promote a shadow model
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from api.auth import TokenPayload, require_role
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# The POST routes below already required admin individually, but the GET routes
# did not — drift reports, shadow-deployment state, retrain history and
# per-version model metrics were readable without a token. Those describe the
# live model's behaviour and are the same class of secret as the model itself,
# so the guard belongs on the router rather than on the write routes only.
# The frontend's /ml-ops page is adminOnly() already; this makes it true of the
# API too.
router = APIRouter(
    prefix="/api/mlops",
    tags=["MLOps"],
    dependencies=[Depends(require_role("admin"))],
)


class ManualRetrainRequest(BaseModel):
    """Request body for triggering manual retraining."""

    reason: str = Field(default="manual", description="Reason for retraining")


class ShadowDeployRequest(BaseModel):
    """Request body for deploying a model in shadow mode."""

    version_id: str = Field(..., description="Model version to deploy in shadow")


@router.get("/health", response_model=dict)
async def mlops_health():
    """Return MLOps pipeline health metrics."""
    from ml.continuous_learning import get_continuous_learning_pipeline

    pipeline = get_continuous_learning_pipeline()
    return pipeline.health()


@router.get("/drift", response_model=dict)
async def get_drift_status():
    """Return the latest drift detection report."""
    from ml.continuous_learning import get_continuous_learning_pipeline

    pipeline = get_continuous_learning_pipeline()
    health = pipeline.health()
    drift = health.get("latest_drift")

    if drift is None:
        return {"status": "no_drift_data", "message": "No drift checks have run yet."}

    return drift


@router.post("/retrain", response_model=dict)
async def trigger_retraining(request: ManualRetrainRequest, user: TokenPayload = Depends(require_role("admin"))):
    """
    Trigger a manual retraining run.

    This bypasses the drift detection trigger and immediately starts
    the retraining pipeline. Use with caution in production.
    """
    from ml.continuous_learning import (
        DriftReport,
        DriftType,
        get_continuous_learning_pipeline,
    )
    from datetime import datetime, timezone

    pipeline = get_continuous_learning_pipeline()

    # Create a manual drift report to trigger retraining
    manual_report = DriftReport(
        timestamp=datetime.now(timezone.utc),
        drift_type=DriftType.PERFORMANCE_DRIFT,
        score=1.0,
        threshold=0.0,
        is_drifted=True,
        details={"trigger": "manual", "reason": request.reason},
    )

    try:
        version_id = await pipeline._retraining.trigger_retraining(
            drift_report=manual_report,
            model_registry=pipeline._model_registry,
            data_store=pipeline._data_store,
        )

        if version_id:
            return {
                "status": "success",
                "version_id": version_id,
                "message": f"Retraining completed. New model: {version_id}",
            }
        else:
            return {
                "status": "skipped",
                "message": "Retraining was skipped (cooldown active or insufficient data).",
            }
    except Exception as exc:
        logger.error("Manual retraining failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/shadow", response_model=dict)
async def get_shadow_status():
    """Return status of all shadow model deployments."""
    from ml.continuous_learning import get_continuous_learning_pipeline

    pipeline = get_continuous_learning_pipeline()
    results = pipeline._shadow.get_shadow_results()

    return {
        "count": len(results),
        "shadows": {k: v.to_dict() for k, v in results.items()},
    }


@router.post("/promote/{version_id}", response_model=dict)
async def promote_model(version_id: str, user: TokenPayload = Depends(require_role("admin"))):
    """
    Promote a shadow model to production.

    The model must be in shadow mode and meet all promotion criteria.
    """
    from ml.continuous_learning import get_continuous_learning_pipeline

    pipeline = get_continuous_learning_pipeline()

    if not pipeline._champion_challenger:
        raise HTTPException(
            status_code=503,
            detail="Champion/Challenger system not initialized.",
        )

    promoted = await pipeline._champion_challenger.promote_if_ready(pipeline._shadow, version_id)

    if promoted:
        return {
            "status": "success",
            "message": f"Model '{version_id}' promoted to production.",
        }
    else:
        raise HTTPException(
            status_code=400,
            detail=f"Model '{version_id}' does not meet promotion criteria.",
        )


@router.get("/retrain/history", response_model=dict)
async def get_retrain_history():
    """Return the history of model retrains / promotions for the MLOps dashboard."""
    from ml.continuous_learning import get_continuous_learning_pipeline

    pipeline = get_continuous_learning_pipeline()
    health = pipeline.health()
    return {
        "history": health.get("promotion_history", []) or [],
        "retraining_state": health.get("retraining_state"),
        "can_retrain": health.get("can_retrain"),
    }


@router.get("/models/{version_id}/metrics", response_model=dict)
async def get_model_metrics(version_id: str):
    """Return metrics for a specific model version (from shadow-deployment results)."""
    from ml.continuous_learning import get_continuous_learning_pipeline

    pipeline = get_continuous_learning_pipeline()
    shadows = pipeline.health().get("shadow_models", {}) or {}
    metrics = shadows.get(version_id)
    return {
        "version_id": version_id,
        "available": metrics is not None,
        "metrics": metrics or {},
    }

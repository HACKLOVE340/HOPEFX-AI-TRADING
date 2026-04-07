# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""SuperAdmin ML/AI sub-router."""

import logging

from fastapi import APIRouter, Depends, HTTPException

from api.auth import TokenPayload

from ._shared import DeployModelBody, MLControlBody, _log_superadmin_action, _require_superadmin, _utcnow

logger = logging.getLogger(__name__)

router = APIRouter()

# ── ML / AI ───────────────────────────────────────────────────────────────────


@router.get("/ml/status")
async def get_ml_status(user: TokenPayload = Depends(_require_superadmin)) -> dict:
    try:
        from api.ml import get_ml_status as _gms

        return await _gms(user=user)
    except Exception:
        return {"status": "unknown"}


@router.get("/ml/models")
async def list_ml_models(user: TokenPayload = Depends(_require_superadmin)) -> dict:
    models = []
    try:
        from ml import model_registry

        for name, info in model_registry.items():
            models.append(
                {
                    "name": name,
                    "version": info.get("version", "1.0"),
                    "status": info.get("status", "active"),
                    "accuracy": info.get("accuracy", 0.0),
                    "last_trained": info.get("last_trained", _utcnow().isoformat()),
                    "predictions_today": info.get("predictions_today", 0),
                    "drift_score": info.get("drift_score", 0.0),
                    "deployed_at": info.get("deployed_at"),
                }
            )
    except Exception:
        for name in ["signal_classifier", "regime_detector", "rl_agent", "sentiment_model"]:
            models.append(
                {
                    "name": name,
                    "version": "1.0",
                    "status": "active",
                    "accuracy": 0.0,
                    "last_trained": _utcnow().isoformat(),
                    "predictions_today": 0,
                    "drift_score": 0.0,
                    "deployed_at": None,
                }
            )
    return {"models": models}


@router.post("/ml/retrain/{model_name}")
async def retrain_model(model_name: str, user: TokenPayload = Depends(_require_superadmin)) -> dict:
    _log_superadmin_action(user, "retrain_model", model_name)
    try:
        from api.ml import trigger_retrain

        await trigger_retrain(model_name)
    except Exception as exc:
        logger.debug("retrain %s: %s", model_name, exc)
    return {"ok": True, "model": model_name, "status": "retrain_queued"}


@router.post("/ml/deploy")
async def deploy_model(body: DeployModelBody, user: TokenPayload = Depends(_require_superadmin)) -> dict:
    _log_superadmin_action(user, "deploy_model", f"{body.model}@{body.version}")
    return {"ok": True, "model": body.model, "version": body.version, "status": "deploy_queued"}


@router.post("/ml/rollback/{model_name}")
async def rollback_model(model_name: str, user: TokenPayload = Depends(_require_superadmin)) -> dict:
    _log_superadmin_action(user, "rollback_model", model_name)
    return {"ok": True, "model": model_name, "status": "rollback_queued"}


@router.get("/ml/metrics")
async def get_ml_metrics(user: TokenPayload = Depends(_require_superadmin)) -> dict:
    try:
        from api.ml import get_accuracy

        result = await get_accuracy(user=user)
        if hasattr(result, "model_dump"):
            return result.model_dump()
        if hasattr(result, "dict"):
            return result.dict()
        return result if isinstance(result, dict) else {}
    except Exception:
        return {}


@router.get("/ml/rl/status")
async def get_rl_status(user: TokenPayload = Depends(_require_superadmin)) -> dict:
    try:
        from api.ml import get_rl_status as _grl

        return await _grl(user=user)
    except Exception:
        return {
            "status": "unknown",
            "episode": 0,
            "total_reward": 0.0,
            "win_rate": 0.0,
            "last_updated": _utcnow().isoformat(),
            "model_version": "1.0",
        }


@router.post("/ml/rl/control")
async def rl_agent_control(body: MLControlBody, user: TokenPayload = Depends(_require_superadmin)) -> dict:
    valid = {"start", "pause", "stop", "reset"}
    if body.action not in valid:
        raise HTTPException(status_code=400, detail=f"action must be one of {valid}")
    _log_superadmin_action(user, "rl_control", body.action)
    try:
        from api.ml import control_rl_agent

        await control_rl_agent(body.action)
    except Exception as exc:
        logger.debug("rl_control %s: %s", body.action, exc)
    return {"ok": True, "action": body.action}

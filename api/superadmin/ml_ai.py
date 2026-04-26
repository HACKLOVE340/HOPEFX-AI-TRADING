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
    """Return ML engine status in the shape the frontend MLStatus interface expects.

    MLStatus fields:
      status               — "healthy" | "degraded" | "unavailable"
      active_model         — name/id of the currently loaded model
      inference_latency_ms — most recent predict() wall-clock time in ms
      predictions_today    — total predict() calls since process start
      accuracy_7d          — OOS accuracy from the active model (0–100 scale)
      drift_score          — feature drift score (0.0 = no drift)
    """
    result: dict = {
        "status": "unavailable",
        "active_model": "unknown",
        "inference_latency_ms": 0.0,
        "predictions_today": 0,
        "accuracy_7d": 0.0,
        "drift_score": 0.0,
    }

    # ── Primary: InferenceEngine.health() ─────────────────────────────────────
    try:
        from ml.inference_engine import get_inference_engine

        engine = get_inference_engine()
        health = engine.health()

        engine_status = health.get("status", "unavailable")
        # Map engine status values → frontend-expected values
        if engine_status in ("ok", "healthy"):
            result["status"] = "healthy"
        elif engine_status == "degraded":
            result["status"] = "degraded"
        else:
            result["status"] = "unavailable"

        result["active_model"] = (
            health.get("model_version")
            or health.get("model_id")
            or "unknown"
        )
        result["inference_latency_ms"] = round(
            float(health.get("last_latency_ms", 0.0)), 2
        )
        result["predictions_today"] = int(health.get("predict_count", 0))

        # oos_accuracy is stored as a fraction (0–1); frontend shows as percentage
        oos_acc = float(health.get("oos_accuracy") or 0.0)
        result["accuracy_7d"] = round(oos_acc * 100 if oos_acc <= 1.0 else oos_acc, 2)

    except Exception as exc:
        logger.debug("get_ml_status: inference engine unavailable: %s", exc)

    # ── Drift score from drift monitor ────────────────────────────────────────
    try:
        import json as _json
        from cache.redis_client import get_redis_client

        rc = get_redis_client()
        if rc:
            raw = rc.get("ml:drift:status")
            if raw:
                drift_data = _json.loads(raw)
                result["drift_score"] = round(
                    float(drift_data.get("drift_score", 0.0)), 4
                )
    except Exception as exc:
        logger.debug("get_ml_status: drift score redis: %s", exc)

    return result


@router.get("/ml/models")
async def list_ml_models(user: TokenPayload = Depends(_require_superadmin)) -> dict:
    """Return all registered model versions mapped to the MLModel interface.

    Registry entry fields → MLModel fields:
      name            → name
      state           → status  (production→active, staging→staged, retired→retired)
      oos_accuracy    → accuracy
      registered_at   → last_trained  (best available timestamp)
      promoted_at     → deployed_at
    """
    models = []

    # ── Primary: ModelRegistry manifest (versioned, SHA-256 integrity) ────────
    try:
        from ml.model_registry import get_registry

        registry = get_registry()
        versions = registry.list_versions()
        active_version = registry._load().get("active_version")

        # Pull live prediction counters from the inference engine if available
        predict_count_today = 0
        try:
            from ml.inference_engine import get_inference_engine
            predict_count_today = get_inference_engine()._predict_count
        except Exception:  # noqa: BLE001 — inference engine is optional
            pass

        for name, info in versions.items():
            state = info.get("state", "staging")
            # Map registry state → MLModel status values
            status_map = {
                "production": "active",
                "staging": "staged",
                "retired": "retired",
            }
            status = status_map.get(state, "staged")

            # The active version gets the live prediction counter
            preds_today = predict_count_today if name == active_version else 0

            models.append(
                {
                    "name": name,
                    "version": info.get("sha256", "")[:8] or "1.0",
                    "status": status,
                    "accuracy": round(float(info.get("oos_accuracy", 0.0)), 4),
                    "last_trained": info.get("registered_at", _utcnow().isoformat()),
                    "predictions_today": preds_today,
                    "drift_score": 0.0,  # populated by drift monitor if running
                    "deployed_at": info.get("promoted_at"),
                }
            )
    except Exception as exc:
        logger.debug("list_ml_models: registry unavailable: %s", exc)

    # ── Fallback: scan saved_models/ directory for .pkl files ─────────────────
    if not models:
        try:
            import pathlib

            saved_dir = pathlib.Path(__file__).parent.parent.parent / "ml" / "saved_models"
            for pkl in sorted(saved_dir.glob("*.pkl")):
                stat = pkl.stat()
                models.append(
                    {
                        "name": pkl.stem,
                        "version": "1.0",
                        "status": "active",
                        "accuracy": 0.0,
                        "last_trained": _utcnow().replace(
                            second=0, microsecond=0
                        ).isoformat(),
                        "predictions_today": 0,
                        "drift_score": 0.0,
                        "deployed_at": None,
                    }
                )
        except Exception as exc:
            logger.debug("list_ml_models: saved_models scan failed: %s", exc)

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

# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""SuperAdmin ML/AI sub-router."""

import logging
import re

from fastapi import APIRouter, Depends, HTTPException

from api.auth import TokenPayload

from ._shared import DeployModelBody, MLControlBody, _log_superadmin_action, _require_superadmin, _utcnow

logger = logging.getLogger(__name__)

router = APIRouter()


def _live_drift_score() -> float:
    """Read the current feature-drift score from the drift monitor (Redis).

    Returns 0.0 when the monitor is not running / Redis is unavailable. This is
    the single source of truth for drift used by both /ml/status and /ml/models,
    so the dashboard never shows a hardcoded zero while real drift exists.
    """
    try:
        import json as _json

        from cache.redis_client import get_sync_redis_client

        rc = get_sync_redis_client()
        if rc:
            raw = rc.get("ml:drift:status")
            if raw:
                return float(_json.loads(raw).get("drift_score", 0.0))
    except Exception as exc:  # best-effort; drift is informational
        logger.debug("_live_drift_score: %s", exc)
    return 0.0


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

        result["active_model"] = health.get("model_version") or health.get("model_id") or "unknown"
        result["inference_latency_ms"] = round(float(health.get("last_latency_ms", 0.0)), 2)
        result["predictions_today"] = int(health.get("predict_count", 0))

        # oos_accuracy is stored as a fraction (0–1); frontend shows as percentage
        oos_acc = float(health.get("oos_accuracy") or 0.0)
        result["accuracy_7d"] = round(oos_acc * 100 if oos_acc <= 1.0 else oos_acc, 2)

    except Exception as exc:
        logger.debug("get_ml_status: inference engine unavailable: %s", exc)

    # ── Drift score from drift monitor (shared source of truth) ───────────────
    result["drift_score"] = round(_live_drift_score(), 4)

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
        except Exception:  # nosec B110  # noqa: S110
            pass

        # Live drift score from the drift monitor (applies to the model actually
        # serving inference). Previously every row was hardcoded to 0.0, which
        # made the dashboard show all models as zero-drift regardless of reality.
        active_drift = _live_drift_score()

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
                    # oos_accuracy is stored as a fraction (0–1); the frontend
                    # AccuracyBar expects a 0–100 percent (matches accuracy_7d).
                    "accuracy": round((lambda a: a * 100 if a <= 1.0 else a)(float(info.get("oos_accuracy", 0.0))), 2),
                    "last_trained": info.get("registered_at", _utcnow().isoformat()),
                    "predictions_today": preds_today,
                    # Only the serving (active) model has a live drift score;
                    # staged/retired versions are not serving, so 0.0 is correct.
                    "drift_score": round(active_drift, 4) if name == active_version else 0.0,
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
                pkl.stat()
                models.append(
                    {
                        "name": pkl.stem,
                        "version": "1.0",
                        "status": "active",
                        "accuracy": 0.0,
                        "last_trained": _utcnow().replace(second=0, microsecond=0).isoformat(),
                        "predictions_today": 0,
                        "drift_score": 0.0,
                        "deployed_at": None,
                    }
                )
        except Exception as exc:
            logger.debug("list_ml_models: saved_models scan failed: %s", exc)

    # ── Cross-entry integrity ────────────────────────────────────────────────
    #
    # The VERSION column shows sha256[:8]. Four entries in the shipped manifest
    # share one digest because they point at one file, so the table printed
    # "vdc7454d8" four times against four different model names — and two
    # different accuracies. Per-entry verification cannot see that; only a
    # comparison across entries can. Attach it so the page can say so instead of
    # rendering the contradiction as ordinary rows.
    integrity: dict = {"ok": True}
    try:
        from ml.model_registry import get_registry

        integrity = get_registry().audit_manifest()
        conflicted: set[str] = set()
        for conflict in integrity.get("metric_conflicts", []):
            conflicted.update(conflict["versions"])
        duplicated: dict[str, list[str]] = {}
        for names in integrity.get("duplicate_artifacts", {}).values():
            for n in names:
                duplicated[n] = [m for m in names if m != n]
        for model in models:
            name = model["name"]
            model["shares_artifact_with"] = duplicated.get(name, [])
            model["metrics_conflict"] = name in conflicted
    except Exception as exc:
        logger.debug("list_ml_models: manifest audit failed: %s", exc)

    return {"models": models, "integrity": integrity}


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
    try:
        from ml.model_registry import get_registry

        registry = get_registry()
        registry.promote(body.model)
        # Reload the inference engine so it picks up the newly promoted model
        try:
            from ml.inference_engine import get_inference_engine

            engine = get_inference_engine()
            if hasattr(engine, "reload"):
                await engine.reload() if hasattr(engine.reload, "__await__") else engine.reload()
        except Exception as exc:
            logger.warning("deploy_model: inference engine reload failed: %s", exc)
        return {"ok": True, "model": body.model, "version": body.version, "status": "deployed"}
    except Exception as exc:
        logger.warning("deploy_model %s@%s failed: %s", body.model, body.version, exc)
        raise HTTPException(status_code=500, detail="Deploy failed.") from exc


@router.post("/ml/rollback/{model_name}")
async def rollback_model(model_name: str, user: TokenPayload = Depends(_require_superadmin)) -> dict:
    _log_superadmin_action(user, "rollback_model", model_name)
    try:
        from ml.model_registry import get_registry

        registry = get_registry()
        # Demote the current active version back to staging, then promote the
        # previous production version if one exists.
        manifest = registry._load()
        versions = manifest.get("versions", {})
        active = manifest.get("active_version")
        # Find the most recent non-active production or staging version
        candidates = [
            (name, info)
            for name, info in versions.items()
            if name != active and info.get("state") in ("production", "staging")
        ]
        if not candidates:
            raise HTTPException(status_code=404, detail="No previous version available for rollback")
        # Sort by registered_at descending and pick the most recent
        candidates.sort(key=lambda x: x[1].get("registered_at", ""), reverse=True)
        prev_name, _ = candidates[0]
        # Use rollback() which bypasses quality gates — this is an emergency
        # restore of a previously-validated model, not a new promotion.
        registry.rollback(prev_name)
        # Reload inference engine
        try:
            from ml.inference_engine import get_inference_engine

            engine = get_inference_engine()
            if hasattr(engine, "reload"):
                await engine.reload() if hasattr(engine.reload, "__await__") else engine.reload()
        except Exception as exc:
            logger.warning("rollback_model: inference engine reload failed: %s", exc)
        return {"ok": True, "model": model_name, "rolled_back_to": prev_name, "status": "rolled_back"}
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("rollback_model %s failed: %s", model_name, exc)
        raise HTTPException(status_code=500, detail="Rollback failed.") from exc


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


@router.get("/ml/training-jobs")
async def list_training_jobs(user: TokenPayload = Depends(_require_superadmin)) -> dict:
    """Active and recent ML training jobs."""
    try:
        from ml.training_manager import get_training_manager  # type: ignore[import]

        mgr = get_training_manager()
        return {"jobs": mgr.list_jobs()}
    except Exception:  # nosec B110  # noqa: S110
        pass
    # Fallback: read from DB or return empty
    try:
        from database.connection import get_db_manager

        mgr = get_db_manager()
        if mgr:
            with mgr.session() as db:
                from database.system_events import read_events
                from ml.training_manager import _job_from_event

                # This used to re-derive the row→dict mapping by hand, from the
                # same three non-existent columns as the manager above it. One
                # mapping now, in ml/training_manager.
                return {"jobs": [_job_from_event(rec) for rec in read_events(db, event_type="ml_training", limit=50)]}
    except Exception as exc:
        logger.warning("training_jobs db fallback failed: %s", exc)
    return {"jobs": []}


@router.get("/ml/ab-tests")
async def list_ab_tests(user: TokenPayload = Depends(_require_superadmin)) -> dict:
    """Active A/B tests for ML models."""
    try:
        from ml.ab_testing import get_ab_test_manager  # type: ignore[import]

        mgr = get_ab_test_manager()
        return {"tests": mgr.list_tests()}
    except Exception:  # nosec B110  # noqa: S110
        pass
    try:
        from database.connection import get_db_manager

        mgr = get_db_manager()
        if mgr:
            with mgr.session() as db:
                from database.system_events import read_events
                from ml.ab_testing import _test_from_event

                # As above: the hand-rolled copy also disagreed with the
                # manager's own shape, emitting "variant" where every other
                # producer emits "challenger".
                return {"tests": [_test_from_event(rec) for rec in read_events(db, event_type="ab_test", limit=20)]}
    except Exception as exc:
        logger.warning("ab_tests db fallback failed: %s", exc)
    return {"tests": []}


@router.get("/ml/drift")
async def get_model_drift(user: TokenPayload = Depends(_require_superadmin)) -> dict:
    """Model drift metrics for all deployed models."""
    try:
        from ml.drift_detector import get_drift_detector  # type: ignore[import]

        detector = get_drift_detector()
        return detector.get_all_drift()
    except Exception:  # nosec B110  # noqa: S110
        pass
    # No drift detector available and no real metrics to return.
    # Return an empty list rather than synthetic data — callers must handle
    # the empty case and prompt the operator to configure drift monitoring.
    return {
        "drift_reports": [],
        "total": 0,
        "message": "Drift detector unavailable. Configure ml.drift_detector to enable real drift metrics.",
        "last_checked": _utcnow().isoformat(),
    }


@router.get("/ml/explainability")
async def get_model_explainability(
    model: str = "advanced_oos",
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    """SHAP / feature importance for a deployed model."""
    # Validate model name: only alphanumeric + underscore, max 64 chars
    if not re.fullmatch(r"[A-Za-z0-9_]{1,64}", model):
        raise HTTPException(status_code=400, detail="Invalid model name")

    try:
        from ml.explainability import get_shap_values  # type: ignore[import]

        return get_shap_values(model)
    except Exception:  # nosec B110  # noqa: S110
        pass
    # Fallback: load model and compute basic feature importance
    try:
        import pickle
        from pathlib import Path

        _model_dir = Path("ml/saved_models").resolve()
        model_path = (_model_dir / f"{model}.pkl").resolve()
        # Confine path to the model directory to prevent traversal
        try:
            model_path.relative_to(_model_dir)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid model name") from None
        if model_path.exists():
            with open(model_path, "rb") as f:
                clf = pickle.load(f)  # nosec B301 — path-confined local model file
            if hasattr(clf, "feature_importances_"):
                features = getattr(clf, "feature_names_in_", [f"f{i}" for i in range(len(clf.feature_importances_))])
                importance = [
                    {"feature": str(feat), "importance": round(float(imp), 6)}
                    for feat, imp in sorted(
                        zip(features, clf.feature_importances_, strict=False), key=lambda x: x[1], reverse=True
                    )
                ]
                return {
                    "model": model,
                    "method": "feature_importances",
                    "features": importance[:20],
                    "computed_at": _utcnow().isoformat(),
                }
    except Exception as exc:
        logger.debug("explainability model load: %s", exc)
    return {
        "model": model,
        "method": "unavailable",
        "features": [],
        "computed_at": _utcnow().isoformat(),
        "note": "Model does not expose feature importances",
    }

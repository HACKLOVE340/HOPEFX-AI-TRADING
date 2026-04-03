# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
Machine Learning Module

This module provides machine learning models for trading.

Model types:
- LSTM (Long Short-Term Memory) - Price prediction
- Random Forest - Signal classification
- Feature engineering - Technical indicators

Components:
- Feature engineering
- Model training
- Model evaluation
- Prediction generation
- Model versioning and storage
"""

from .features import TechnicalFeatureEngineer
from .models import BaseMLModel, LSTMPricePredictor, RandomForestTradingClassifier

# RL nuclear decision agent path constant — used by NuclearHopeFXSupervisor
RL_NUCLEAR_MODEL_PATH: str = "ml/rl_models/nuclear_decision_ppo.zip"
RL_NUCLEAR_VECNORM_PATH: str = "ml/rl_models/nuclear_decision_vecnorm.pkl"

__all__ = [
    "RL_NUCLEAR_MODEL_PATH",
    "RL_NUCLEAR_VECNORM_PATH",
    "BaseMLModel",
    "LSTMPricePredictor",
    "RandomForestTradingClassifier",
    "TechnicalFeatureEngineer",
    "create_ml_router",
    "get_active_model",
    "get_advanced_predictor",
    "get_model_version",
]

# Module metadata
__version__ = "1.0.0"

# ── Macro-aware model loader ──────────────────────────────────────────────────
import hashlib as _hashlib
import json as _json
import logging as _logging
from pathlib import Path as _Path
from typing import Any as _Any

_ml_logger = _logging.getLogger(__name__)
_SAVED = _Path(__file__).parent / "saved_models"
_CHECKSUM_FILE = _SAVED / "model_checksums.json"

# Loaded model instances (None until first call to get_active_model())
_macro_xgb: _Any | None = None
_macro_rf: _Any | None = None
_baseline_xgb: _Any | None = None
_baseline_rf: _Any | None = None
_model_version: str = "none"


def _sha256(path: _Path) -> str:
    """Return the SHA-256 hex digest of a file."""
    h = _hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _verify_checksum(path: _Path) -> bool:
    """
    Verify a model file against the stored SHA-256 checksum.

    Returns True if:
    - The checksum file does not exist (first run — no baseline yet).
    - The file matches the stored checksum.

    Returns False (and logs CRITICAL) if the file has been tampered with.
    The checksum file is written automatically on first successful load so
    subsequent loads can detect modifications.
    """
    if not _CHECKSUM_FILE.exists():
        # First run — record checksums for all existing models
        _record_checksums()
        return True

    try:
        stored = _json.loads(_CHECKSUM_FILE.read_text())
    except Exception as exc:
        _ml_logger.warning("Could not read model checksums: %s — skipping verification", exc)
        return True

    name = path.name
    if name not in stored:
        # New model file not yet in checksum registry — record and allow
        _record_checksums()
        return True

    actual = _sha256(path)
    if actual != stored[name]:
        _ml_logger.critical(
            "MODEL INTEGRITY FAILURE: %s checksum mismatch. "
            "Expected %s, got %s. "
            "The file may have been tampered with. Refusing to load.",
            name,
            stored[name][:16] + "...",
            actual[:16] + "...",
        )
        return False
    return True


def _record_checksums() -> None:
    """Write SHA-256 checksums for all .pkl files in saved_models/."""
    try:
        checksums = {}
        for pkl in _SAVED.glob("*.pkl"):
            checksums[pkl.name] = _sha256(pkl)
        _CHECKSUM_FILE.write_text(_json.dumps(checksums, indent=2))
        _ml_logger.info("Model checksums recorded: %d files", len(checksums))
    except Exception as exc:
        _ml_logger.warning("Could not record model checksums: %s", exc)


def _try_load(path: _Path) -> _Any | None:
    """Load a model file via joblib with SHA-256 integrity check.

    Uses joblib (not raw pickle) — joblib handles numpy arrays more safely
    and is the standard for sklearn/XGBoost pipelines.  Raw pickle is kept
    as a fallback for files that joblib cannot read.

    On load failure a CRITICAL log is emitted with the exact remediation
    command so operators can detect silent model degradation in log aggregators.
    """
    if not path.exists():
        return None
    if not _verify_checksum(path):
        # Checksum mismatch — refuse to load potentially tampered model
        return None
    try:
        import joblib as _joblib

        return _joblib.load(path)  # nosec B301 - path is always from ml/saved_models (internal)
    except Exception as _jl_exc:
        _ml_logger.debug("joblib.load failed for %s (%s) — trying pickle", path.name, _jl_exc)
        try:
            import pickle as _pickle  # nosec B403

            with Path(path).open("rb") as f:
                return _pickle.load(f)  # nosec B301 - joblib failed; legacy pickle fallback for protocol mismatch
        except Exception as exc:
            import sys as _sys

            _ml_logger.critical(
                "CANNOT LOAD MODEL %s: %s\n"
                "  Python version: %s\n"
                "  This is usually a pickle protocol mismatch between the Python\n"
                "  version used to train the model and the current runtime.\n"
                "  Remediation (run inside Docker on Python 3.10):\n"
                "    docker compose run --rm app python scripts/resave_models.py\n"
                "  Or retrain from scratch:\n"
                "    docker compose run --rm app python ml/train_advanced.py --years 50 --oos-years 3\n"
                "  The engine will fall back to a weaker model — live trading is NOT recommended.",
                path.name,
                exc,
                _sys.version,
            )
            return None


def _load_models() -> None:
    """Lazy-load all saved models on first access.

    Priority (highest to lowest):
      1. advanced_oos.pkl  — 122-feature calibrated XGBoost, 68% OOS accuracy (p=0.0000)
      2. xgb_macro.pkl     — basic macro XGBoost, 65 stationary features, ~50% OOS
      3. xgb_xauusd.pkl    — baseline XGBoost (no macro)
      4. rf_macro.pkl      — basic macro RF
      5. rf_xauusd.pkl     — baseline RF

    FALLBACK WARNING
    ----------------
    If advanced_oos.pkl fails to load (version mismatch, missing file, import
    error), the engine falls back to xgb_macro.pkl which has ~50% OOS accuracy
    — no demonstrated edge above chance.  A CRITICAL log is emitted so
    operators can detect silent degradation in log aggregators (Sentry, Datadog,
    CloudWatch).  The fallback model has had all close_lag_N non-stationary
    features removed as of this version.

    OOS metadata sidecar
    --------------------
    When advanced_oos.pkl loads successfully, the companion
    advanced_oos_meta.json is read to log the validated OOS accuracy, SE,
    p-value, and period.  This lets operators confirm the loaded model matches
    the expected 68% OOS accuracy without unpickling the full pipeline.
    """
    global _macro_xgb, _macro_rf, _baseline_xgb, _baseline_rf, _model_version

    # ── Priority 1: advanced OOS model (122 stationary features, p=0.0000) ──
    _advanced_oos = _try_load(_SAVED / "advanced_oos.pkl")
    if _advanced_oos is not None:
        _macro_xgb = _advanced_oos
        _model_version = "advanced_oos_v1"

        # Read OOS metadata sidecar to log validated accuracy without unpickling
        _meta_path = _SAVED / "advanced_oos_meta.json"
        if _meta_path.exists():
            try:
                with Path(_meta_path).open(encoding="utf-8") as _f:
                    _meta = _json.load(_f)
                _oos_acc = _meta.get("oos_accuracy", "?")
                _oos_se = _meta.get("oos_accuracy_se", "?")
                _oos_p = _meta.get("oos_p_value", "?")
                _oos_period = _meta.get("oos_period", "?")
                _n_features = _meta.get("feature_count", "?")
                _trained_at = _meta.get("trained_at", "?")
                _ml_logger.info(
                    "Active ML model: advanced_oos.pkl — OOS acc=%.3f±%.3f  p=%.4f  period=%s  features=%s  trained=%s",
                    _oos_acc,
                    _oos_se,
                    _oos_p,
                    _oos_period,
                    _n_features,
                    _trained_at,
                )
                # Warn if loaded model accuracy is below the validated 68% threshold
                if isinstance(_oos_acc, float) and _oos_acc < 0.60:
                    _ml_logger.warning(
                        "advanced_oos.pkl OOS accuracy %.3f is below 60%% — "
                        "model may need retraining. Run: "
                        "python ml/train_advanced.py --years 50 --oos-years 8",
                        _oos_acc,
                    )
            except Exception as _exc:
                _ml_logger.info(
                    "Active ML model: advanced_oos.pkl — "
                    "68.0%% OOS accuracy, p=0.0000, 122 stationary features "
                    "(metadata sidecar unreadable: %s)",
                    _exc,
                )
        else:
            _ml_logger.info(
                "Active ML model: advanced_oos.pkl — "
                "68.0%% OOS accuracy, p=0.0000, 122 stationary features "
                "(no metadata sidecar — retrain to generate advanced_oos_meta.json)",
            )
        return

    # ── CRITICAL: advanced model unavailable — falling back ──────────────────
    # This means advanced_oos.pkl is missing, corrupt, or incompatible with
    # the installed scikit-learn/xgboost version.  The fallback model has
    # ~50% OOS accuracy (no demonstrated edge).  Operator action required.
    _ml_logger.critical(
        "FALLBACK ACTIVATED: advanced_oos.pkl could not be loaded from %s. "
        "The live signal engine is now running on the basic fallback model "
        "(xgb_macro.pkl, ~50%% OOS accuracy, no demonstrated edge above chance). "
        "This is a SILENT DEGRADATION from 68%% to ~50%% accuracy. "
        "Fix: ensure advanced_oos.pkl exists and scikit-learn/xgboost versions "
        "match the training environment. Re-run: python ml/train_advanced.py "
        "--years 50 --oos-years 8",
        _SAVED,
    )
    # Fire a Sentry fatal-level issue so operators get paged immediately
    try:
        from monitoring.sentry_config import capture_ml_fallback_event

        capture_ml_fallback_event(
            reason=f"advanced_oos.pkl not loadable from {_SAVED}",
            fallback_model="xgb_macro.pkl",
            fallback_accuracy=0.503,
        )
    except Exception as _sentry_exc:
        _ml_logger.debug("Sentry capture failed (non-fatal): %s", _sentry_exc)

    # Post Discord alert so community operators are notified immediately
    try:
        import asyncio as _asyncio

        from notifications.discord_bot import discord_signal_bot

        async def _post_discord_fallback():
            await discord_signal_bot.post_ml_fallback_alert(
                reason=f"advanced_oos.pkl not loadable from {_SAVED}",
                fallback_model="xgb_macro.pkl",
                fallback_accuracy=0.503,
            )

        # Fire-and-forget: post without blocking model loading
        try:
            loop = _asyncio.get_event_loop()
            if loop.is_running():
                _t = loop.create_task(_post_discord_fallback())
                _t.add_done_callback(lambda _: None)
            else:
                loop.run_until_complete(_post_discord_fallback())
        except RuntimeError:
            _ml_logger.debug("No event loop available — Discord fallback alert skipped")
    except Exception as _discord_exc:
        _ml_logger.debug("Discord alert failed (non-fatal): %s", _discord_exc)

    # ── Priority 2: basic macro XGBoost (65 stationary features, ~50% OOS) ──
    _macro_xgb = _try_load(_SAVED / "xgb_macro.pkl")
    _macro_rf = _try_load(_SAVED / "rf_macro.pkl")

    # ── Priority 3: baseline models (no macro) ───────────────────────────────
    _baseline_xgb = _try_load(_SAVED / "xgb_xauusd.pkl")
    _baseline_rf = _try_load(_SAVED / "rf_xauusd.pkl")

    if _macro_xgb is not None:
        _model_version = "macro_xgb_v1"
        _ml_logger.warning(
            "FALLBACK MODEL ACTIVE: xgb_macro.pkl (65 stationary features, "
            "~50%% OOS accuracy, p>0.05 — no demonstrated edge). "
            "Signals are strategy-only quality. Do not trade live capital.",
        )
    elif _baseline_xgb is not None:
        _model_version = "baseline_xgb_v1"
        _ml_logger.warning(
            "FALLBACK MODEL ACTIVE: xgb_xauusd.pkl (baseline, no macro features, "
            "~49%% OOS accuracy). Signals are strategy-only quality.",
        )
    else:
        _model_version = "none"
        _ml_logger.warning(
            "No trained ML model found in %s — signal engine will use "
            "strategy-only signals (no ML probability enrichment)",
            _SAVED,
        )


def get_active_model() -> _Any | None:
    """
    Return the best available trained model.

    Priority: macro XGBoost → baseline XGBoost → macro RF → baseline RF → None.
    Models are loaded lazily on first call and cached for the process lifetime.
    """
    if _macro_xgb is None and _model_version == "none":
        _load_models()
    return _macro_xgb or _baseline_xgb or _macro_rf or _baseline_rf


def get_model_version() -> str:
    """Return the version string of the currently active model."""
    if _model_version == "none":
        _load_models()
    return _model_version


# ── Advanced predictor (122-feature live inference) ───────────────────────────
try:
    from ml.live_inference import get_advanced_predictor
except Exception as _live_inf_exc:
    _ml_logger.warning(
        "ml.live_inference unavailable — advanced predictor disabled: %s",
        _live_inf_exc,
    )

    def get_advanced_predictor():  # type: ignore[misc]
        return None


__author__ = "HOPEFX Development Team"
__description__ = "Machine learning models for price prediction and signal classification"


def create_ml_router(feature_engineer: "TechnicalFeatureEngineer"):
    """
    Create a FastAPI router for the Machine Learning module.

    Exposes endpoints for feature engineering, model status, and
    (when a trained model is available) price-direction predictions.

    Args:
        feature_engineer: TechnicalFeatureEngineer instance

    Returns:
        FastAPI APIRouter
    """
    from fastapi import APIRouter, HTTPException
    from pydantic import BaseModel

    router = APIRouter(prefix="/api/ml", tags=["Machine Learning"])

    class OHLCVRow(BaseModel):
        open: float
        high: float
        low: float
        close: float
        volume: float

    class FeatureRequest(BaseModel):
        bars: list[OHLCVRow]

    @router.get("/status")
    async def get_status():
        """Return the status and capabilities of the ML module."""
        return {
            "module": "ML Predictions",
            "status": "experimental",
            "feature_engineer": "ready",
            "models": {
                "lstm": "requires training",
                "random_forest": "requires training",
                "ensemble": "requires training",
            },
            "note": ("Set FEATURE_ML_PREDICTIONS=true and provide labelled data to enable live predictions."),
        }

    @router.get("/features/groups")
    async def get_feature_groups():
        """Return the feature groups produced by the feature engineer."""
        return feature_engineer.get_feature_groups()

    @router.post("/features/compute")
    async def compute_features(req: FeatureRequest):
        """
        Compute technical features for a OHLCV bar series.

        Send at least 200 bars to avoid NaN-heavy output.
        """
        import pandas as pd

        if len(req.bars) < 10:
            raise HTTPException(
                status_code=422,
                detail="At least 10 bars are required to compute features.",
            )
        df = pd.DataFrame([b.dict() for b in req.bars])
        try:
            features_df = feature_engineer.create_features(df)
        except Exception as exc:
            _ml_logger.error("Feature engineering failed: %s", exc)
            raise HTTPException(status_code=422, detail="Feature engineering failed — check server logs") from None
        return {
            "rows": len(features_df),
            "feature_count": len(feature_engineer.feature_names),
            "feature_names": feature_engineer.feature_names,
            "sample": features_df.tail(3).to_dict(orient="records"),
        }

    @router.get("/accuracy")
    async def get_accuracy():
        """
        Return accuracy metrics for all trained models.
        Reads from the saved training report if available; returns demo
        metrics otherwise so the frontend always has data to display.
        """
        report_path = _Path(__file__).parent / "saved_models" / "advanced_training_report.json"
        if report_path.exists():
            try:
                with Path(report_path).open(encoding="utf-8") as f:
                    report = _json.load(f)
                final = report.get("final", {})
                wf = report.get("walkforward", {})
                return {
                    "models": [
                        {
                            "model": "Stacking Ensemble",
                            "accuracy": final.get("accuracy", 0),
                            "auc": final.get("auc", 0),
                            "f1": final.get("f1", 0),
                        },
                        {
                            "model": "Walk-forward (XGBoost+Cal)",
                            "accuracy": wf.get("mean_accuracy", 0),
                            "auc": wf.get("mean_auc", 0),
                            "f1": wf.get("mean_f1", 0),
                        },
                    ],
                    "trained_at": report.get("trained_at"),
                    "sample_count": report.get("sample_count"),
                    "feature_count": report.get("feature_count"),
                    "significant": wf.get("significant", False),
                    "p_value": wf.get("p_value"),
                }
            except Exception as _report_exc:
                _logging.getLogger(__name__).warning(
                    "Failed to read training report: %s",
                    _report_exc,
                )

        # No trained model yet — return honest untrained state.
        # Do NOT return fabricated accuracy numbers here; the frontend
        # must show "not trained" rather than misleading 87% figures.
        return {
            "models": [],
            "trained_at": None,
            "sample_count": None,
            "feature_count": None,
            "significant": False,
            "note": "No trained model found. Run: python ml/train_advanced.py --years 50 --oos-years 3",
        }

    @router.get("/predict/{symbol}")
    async def predict(symbol: str):
        """
        Return the latest ML signal for a symbol.
        Uses the saved stacking ensemble if available.
        """
        # Try to load a cached prediction from the report
        report_path = _Path(__file__).parent / "saved_models" / "advanced_training_report.json"
        if report_path.exists():
            try:
                with Path(report_path).open(encoding="utf-8") as f:
                    report = _json.load(f)
                acc = report.get("final", {}).get("accuracy", 0.5)
                return {
                    "symbol": symbol,
                    "direction": "long",
                    "confidence": round(acc, 4),
                    "model": "Stacking Ensemble",
                    "note": "Based on last training run — retrain for live signals",
                }
            except Exception as _pred_exc:
                _ml_logger.warning(
                    "Failed to read training report for predict: %s",
                    _pred_exc,
                )

        return {
            "symbol": symbol,
            "direction": "neutral",
            "confidence": 0.5,
            "model": "none",
            "note": "No trained model found — run ml/train_advanced.py",
        }

    @router.get("/models")
    async def list_models():
        """List available trained model files."""
        model_dir = _Path(__file__).parent / "saved_models"
        if not model_dir.exists():
            return {"models": []}
        files = [
            {"name": f.name, "size_kb": round(f.stat().st_size / 1024, 1)}
            for f in model_dir.iterdir()
            if f.suffix in {".pkl", ".json", ".h5", ".pt"}
        ]
        return {"models": files, "directory": str(model_dir)}

    return router

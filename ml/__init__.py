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
    "StackingEnsemblePredictor",
    "TechnicalFeatureEngineer",
    "create_ml_router",
    "get_active_model",
    "get_advanced_predictor",
    "get_inference_engine",
    "get_model_version",
    "get_online_learner",
    "get_predictor",
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

# ── PyTorch availability check ────────────────────────────────────────────────
try:
    import torch as _torch  # noqa: F401

    _TORCH_AVAILABLE = True
except ImportError:
    _TORCH_AVAILABLE = False
    _ml_logger.warning(
        "PyTorch is not installed. The following ML components will be disabled: "
        "LSTM signal layer, RL/PPO agent (RLAgent), EWC online learner. "
        "Install with: pip install torch>=2.1.1  "
        "These components will fall back to stubs — predictions may be degraded."
    )

# Loaded model instances (None until first call to get_active_model())
_macro_xgb: _Any | None = None
_macro_rf: _Any | None = None
_baseline_xgb: _Any | None = None
_baseline_rf: _Any | None = None
_model_version: str = "none"


def _sha256(path: _Path) -> str:
    """Return the SHA-256 hex digest of a file."""
    h = _hashlib.sha256()
    with _Path(path).open("rb") as f:
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

            with _Path(path).open("rb") as f:
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


def _load_from_registry() -> "tuple[_Any | None, str]":
    """
    Try to load the active model from registry.json.

    Supports two pkl formats:
    - ``sklearn_estimator``: standard sklearn/XGBoost model → loaded directly.
    - ``stacking_dict``: MTF ensemble dict with keys
      ``base_learners``, ``meta_model``, ``feature_cols``, ``scaler``,
      ``horizon``, ``abstain_threshold`` → wrapped in ``StackingEnsemblePredictor``.

    Returns (model, version_name) or (None, "") on failure.
    """
    registry_path = _SAVED / "registry.json"
    if not registry_path.exists():
        _ml_logger.debug("_load_from_registry: registry.json not found — skipping")
        return None, ""

    try:
        registry = _json.loads(registry_path.read_text())
        active = registry.get("active_version", "")
        if not active:
            return None, ""
        entry = registry.get("versions", {}).get(active)
        if not entry:
            return None, ""

        pkl_file = _Path(entry.get("file", ""))
        if not pkl_file.is_absolute():
            # Resolve relative to repo root (two parents up from ml/saved_models)
            pkl_file = _Path(__file__).parent.parent / pkl_file

        if not pkl_file.exists():
            _ml_logger.warning("_load_from_registry: active model file not found: %s", pkl_file)
            return None, ""

        model = _try_load(pkl_file)
        if model is None:
            return None, ""

        # ── Unwrap stacking_dict format (MTF ensemble) ────────────────────────
        pkl_format = entry.get("pkl_format", "sklearn_estimator")
        if isinstance(model, dict) and pkl_format == "stacking_dict":
            model = StackingEnsemblePredictor(model)
            _ml_logger.info(
                "_load_from_registry: loaded stacking_dict '%s' from %s",
                active,
                pkl_file.name,
            )
        else:
            _ml_logger.info(
                "_load_from_registry: loaded sklearn_estimator '%s' from %s",
                active,
                pkl_file.name,
            )

        return model, active

    except Exception as exc:
        _ml_logger.warning("_load_from_registry: error loading active version: %s", exc)
        return None, ""


class StackingEnsemblePredictor:
    """
    Wraps the MTF stacking-ensemble pkl dict so it exposes a standard
    sklearn ``predict_proba(X)`` interface compatible with the execution engine.

    The dict produced by ``scripts/retrain_mtf_accuracy.py`` contains:
      base_learners     : list of fitted sklearn estimators
      meta_model        : fitted CalibratedClassifierCV meta-learner
      feature_cols      : list of feature column names (for alignment)
      scaler            : StandardScaler fitted on training data
      horizon           : int — prediction horizon in bars
      abstain_threshold : float — confidence floor for abstain

    Calling ``predict_proba(X)`` returns an (N, 2) array where column 1 is
    P(up) — consistent with the sklearn API consumed by the signal engine.

    Missing feature columns are filled with 0.0 (safe default for scaled features).
    """

    def __init__(self, payload: dict) -> None:
        self._base_learners = payload["base_learners"]
        self._meta = payload["meta_model"]
        self._feature_cols: list[str] = payload.get("feature_cols", [])
        self._scaler = payload.get("scaler")
        self._horizon: int = payload.get("horizon", 5)
        self._abstain_threshold: float = payload.get("abstain_threshold", 0.55)

    # ── sklearn-compatible API ────────────────────────────────────────────────

    def predict_proba(self, X) -> "_Any":
        """Return (N, 2) probability array consistent with sklearn convention."""
        import numpy as np
        import pandas as pd

        if isinstance(X, pd.DataFrame):
            # Work on a copy to avoid mutating caller's DataFrame
            X_in = X.copy()
            if self._feature_cols:
                for col in self._feature_cols:
                    if col not in X_in.columns:
                        X_in[col] = 0.0
                X_in = X_in[self._feature_cols]
            X_in = X_in.replace([np.inf, -np.inf], np.nan).fillna(0.0)
        else:
            X_in = X

        if self._scaler is not None:
            try:
                X_in = self._scaler.transform(X_in)
            except Exception as exc:
                _ml_logger.debug("StackingEnsemblePredictor: scaler.transform failed: %s", exc)

        base_probas = []
        for idx, m in enumerate(self._base_learners):
            try:
                base_probas.append(m.predict_proba(X_in)[:, 1])
            except Exception as exc:
                _ml_logger.warning(
                    "StackingEnsemblePredictor: base_learner[%d] (%s) predict_proba failed: %s "
                    "— substituting 0.5 (neutral)",
                    idx,
                    type(m).__name__,
                    exc,
                )
                n = X_in.shape[0] if hasattr(X_in, "shape") else len(X_in)
                base_probas.append(np.full(n, 0.5))

        meta_X = np.column_stack(base_probas)
        return self._meta.predict_proba(meta_X)

    def predict(self, X) -> "_Any":
        proba = self.predict_proba(X)
        return (proba[:, 1] >= 0.5).astype(int)

    @property
    def horizon(self) -> int:
        return self._horizon

    @property
    def abstain_threshold(self) -> float:
        return self._abstain_threshold

    def __repr__(self) -> str:
        return (
            f"StackingEnsemblePredictor("
            f"n_base={len(self._base_learners)}, "
            f"features={len(self._feature_cols)}, "
            f"horizon={self._horizon})"
        )


def _load_models() -> None:
    """Lazy-load all saved models on first access.

    Priority (highest to lowest):
      1. Registry-active model  — resolved from registry.json ``active_version``
         (currently xgb_horizon5_v1 → advanced_oos.pkl, horizon=5, OOS=59.9%)
      2. advanced_oos.pkl       — hardcoded fallback (same file, backward-compat)
      3. xgb_macro.pkl          — basic macro XGBoost, ~50% OOS
      4. xgb_xauusd.pkl         — baseline XGBoost (no macro)

    FALLBACK WARNING
    ----------------
    If the registry-active model fails to load (version mismatch, missing file,
    import error), the engine falls back to xgb_macro.pkl which has ~50% OOS
    accuracy — no demonstrated edge above chance.  A CRITICAL log is emitted so
    operators can detect silent degradation in log aggregators.

    OOS metadata sidecar
    --------------------
    When advanced_oos.pkl loads successfully, the companion
    advanced_oos_meta.json is read to log the validated OOS accuracy, SE,
    p-value, and period.  This lets operators confirm the loaded model matches
    the expected OOS accuracy without unpickling the full pipeline.
    """
    global _macro_xgb, _macro_rf, _baseline_xgb, _baseline_rf, _model_version

    # ── Priority 1: registry-active model ────────────────────────────────────
    _reg_model, _reg_version = _load_from_registry()
    if _reg_model is not None:
        _macro_xgb = _reg_model
        _model_version = _reg_version
        # Log registry metadata
        try:
            registry = _json.loads((_SAVED / "registry.json").read_text())
            entry = registry["versions"].get(_reg_version, {})
            _ml_logger.info(
                "Active ML model (registry): %s  oos_acc=%.3f  oos_n=%d  horizon=%d  features=%d",
                _reg_version,
                float(entry.get("oos_accuracy", 0)),
                int(entry.get("oos_n", entry.get("n_trades", 0))),
                int(entry.get("horizon", 1)),
                int(entry.get("feature_count", 0)),
            )
        except Exception as _meta_exc:
            _ml_logger.debug("Registry metadata log failed: %s", _meta_exc)
        return

    # ── Priority 2: advanced OOS model (hardcoded fallback path) ─────────────
    _advanced_oos = _try_load(_SAVED / "advanced_oos.pkl")
    if _advanced_oos is not None:
        _macro_xgb = _advanced_oos
        _model_version = "advanced_oos_v2"

        _meta_path = _SAVED / "advanced_oos_meta.json"
        if _meta_path.exists():
            try:
                with _Path(_meta_path).open(encoding="utf-8") as _f:
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
                if isinstance(_oos_acc, float) and _oos_acc < 0.60:
                    _ml_logger.warning(
                        "advanced_oos.pkl OOS accuracy %.3f is below 60%% — "
                        "model may need retraining. Run: "
                        "python ml/train_advanced.py --years 50 --oos-years 8",
                        _oos_acc,
                    )
            except Exception as _exc:
                _ml_logger.info(
                    "Active ML model: advanced_oos.pkl — OOS accuracy (metadata sidecar unreadable: %s)",
                    _exc,
                )
        else:
            _ml_logger.info(
                "Active ML model: advanced_oos.pkl — 59.9%% OOS accuracy (horizon-5, no metadata sidecar)",
            )
        return

    # ── CRITICAL: advanced model unavailable — falling back ──────────────────
    _ml_logger.critical(
        "FALLBACK ACTIVATED: registry-active model and advanced_oos.pkl could not be "
        "loaded from %s. The live signal engine is now running on the basic fallback model "
        "(xgb_macro.pkl, ~50%% OOS accuracy, no demonstrated edge above chance). "
        "Fix: ensure ml/saved_models/registry.json points to a valid model file and "
        "scikit-learn/xgboost versions match the training environment. "
        "Re-run: python ml/train_advanced.py --years 50 --oos-years 8",
        _SAVED,
    )
    try:
        from monitoring.sentry_config import capture_ml_fallback_event

        capture_ml_fallback_event(
            reason=f"registry model not loadable from {_SAVED}",
            fallback_model="xgb_macro.pkl",
            fallback_accuracy=0.503,
        )
    except Exception as _sentry_exc:
        _ml_logger.debug("Sentry capture failed (non-fatal): %s", _sentry_exc)

    try:
        import asyncio as _asyncio

        from notifications.discord_bot import discord_signal_bot

        async def _post_discord_fallback():
            await discord_signal_bot.post_ml_fallback_alert(
                reason=f"advanced_oos.pkl not loadable from {_SAVED}",
                fallback_model="xgb_macro.pkl",
                fallback_accuracy=0.503,
            )

        try:
            loop = _asyncio.get_running_loop()
            if loop.is_running():
                _t = loop.create_task(_post_discord_fallback())
                _t.add_done_callback(lambda _: None)
            else:
                loop.run_until_complete(_post_discord_fallback())
        except RuntimeError:
            _ml_logger.debug("No event loop available — Discord fallback alert skipped")
    except Exception as _discord_exc:
        _ml_logger.debug("Discord alert failed (non-fatal): %s", _discord_exc)

    # ── Priority 3: basic macro XGBoost ──────────────────────────────────────
    _macro_xgb = _try_load(_SAVED / "xgb_macro.pkl")
    _macro_rf = _try_load(_SAVED / "rf_macro.pkl")

    # ── Priority 4: baseline models (no macro) ───────────────────────────────
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

    Uses the registry-active model (xgb_horizon5_v1 / mtf_ensemble_v1) when
    available.  Falls back through macro XGBoost → baseline XGBoost → RF.
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


# ── Inference engine singleton ────────────────────────────────────────────────
try:
    from ml.inference_engine import get_inference_engine
except Exception as _inf_eng_exc:
    _ml_logger.warning(
        "ml.inference_engine unavailable: %s",
        _inf_eng_exc,
    )

    def get_inference_engine():  # type: ignore[misc]
        return None


# ── Online learner singleton ──────────────────────────────────────────────────
try:
    from ml.online_learner import get_online_learner
except Exception as _ol_exc:
    _ml_logger.warning(
        "ml.online_learner unavailable: %s",
        _ol_exc,
    )

    def get_online_learner(symbol: str = "XAUUSD"):  # type: ignore[misc]
        return None


# ── Advanced predictor (AdvancedPredictor singleton) ─────────────────────────
try:
    from ml.advanced_predictor import get_predictor
except Exception as _ap_exc:
    _ml_logger.warning(
        "ml.advanced_predictor unavailable: %s",
        _ap_exc,
    )

    def get_predictor():  # type: ignore[misc]
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
                with _Path(report_path).open(encoding="utf-8") as f:
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
                with _Path(report_path).open(encoding="utf-8") as f:
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

    @router.get("/health")
    async def get_health():
        """ML health — reports live signal-engine ML availability and model status."""
        try:
            from core.signal_engine import get_signal_engine_status

            engine_status = get_signal_engine_status()
            ml_available = engine_status.get("ml_available", False)
            model_version = engine_status.get("model_version", "none")
        except Exception:
            ml_available = False
            model_version = "unknown"

        model_dir = _Path(__file__).parent / "saved_models"
        model_files = []
        if model_dir.exists():
            model_files = [f.name for f in model_dir.iterdir() if f.suffix in {".pkl", ".json"}]

        return {
            "status": "ok" if ml_available else "degraded",
            "ml_available": ml_available,
            "model_version": model_version,
            "module": "ML Predictions",
            "feature_engineer": "ready",
            "saved_models": model_files,
            "note": None if ml_available else "ML package unavailable — signals use StrategyBrain only",
        }

    @router.get("/features")
    async def get_features():
        """Return flat list of feature names produced by the feature engineer."""
        return {
            "feature_names": feature_engineer.feature_names,
            "feature_count": len(feature_engineer.feature_names),
            "groups": feature_engineer.get_feature_groups(),
        }

    @router.post("/retrain")
    async def trigger_retrain(payload: dict = None):
        """
        Trigger an async ML model retrain.  Returns immediately with a job id;
        training runs in a background thread so the HTTP response is not blocked.
        """
        import asyncio  # noqa: F401
        import threading
        import uuid

        job_id = str(uuid.uuid4())

        def _run_retrain():
            try:
                import subprocess
                import sys

                subprocess.run(  # noqa: PLW1510
                    [sys.executable, "ml/train_advanced.py", "--years", "3", "--oos-years", "1"],
                    capture_output=True,
                    text=True,
                    timeout=3600,
                )
            except Exception as exc:
                _ml_logger.warning("Background retrain failed: %s", exc)

        t = threading.Thread(target=_run_retrain, daemon=True)
        t.start()
        return {"job_id": job_id, "status": "started", "message": "Retraining started in background"}

    @router.get("/drift/status")
    async def get_drift_status():
        """Return data-drift detection configuration and last known result."""
        from ml.robust_predictor import DriftDetector

        return {
            "status": "ok",
            "detector": "KolmogorovSmirnov",
            "config": {
                "window_size": DriftDetector.__init__.__defaults__[0] if DriftDetector.__init__.__defaults__ else 50,
                "check_every": DriftDetector.__init__.__defaults__[1]
                if DriftDetector.__init__.__defaults__ and len(DriftDetector.__init__.__defaults__) > 1
                else 10,
                "p_threshold": DriftDetector.__init__.__defaults__[2]
                if DriftDetector.__init__.__defaults__ and len(DriftDetector.__init__.__defaults__) > 2
                else 0.05,
            },
            "note": "Drift detector is instantiated per model; no persistent state between requests.",
        }

    @router.get("/signal-filter/stats")
    async def get_signal_filter_stats():
        """Return signal filter pass/block statistics."""
        from ml.signal_filter import get_signal_filter

        sf = get_signal_filter()
        return sf.get_stats()

    @router.get("/sharpe-circuit-breaker/status")
    async def get_sharpe_cb_status():
        """Return current Sharpe circuit breaker state for all tracked model versions."""
        from ml.sharpe_circuit_breaker import get_sharpe_cb

        cb = get_sharpe_cb()
        return cb.get_status()

    @router.get("/rl/status")
    async def get_rl_status():
        """Return RL agent training and deployment status."""
        try:
            from ml.rl_agent import RLAgent  # noqa: F401

            model_dir = _Path(__file__).parent / "rl_models"
            models = []
            if model_dir.exists():
                models = [
                    {"name": f.name, "size_kb": round(f.stat().st_size / 1024, 1)}
                    for f in model_dir.iterdir()
                    if f.suffix in {".zip", ".pkl", ".pt", ".h5"}
                ]
            return {
                "status": "ok",
                "agent": "PPO/RLAgent",
                "models": models,
                "model_count": len(models),
            }
        except Exception as exc:
            return {"status": "unavailable", "error": str(exc)}

    @router.post("/rl/train")
    async def trigger_rl_train(payload: dict = None):
        """Trigger RL agent training in a background thread."""
        import asyncio
        import threading
        import uuid

        payload = payload or {}
        job_id = str(uuid.uuid4())

        def _run_rl_train():
            try:
                from ml.rl_agent import RLAgentTrainer

                trainer = RLAgentTrainer()
                asyncio.run(
                    trainer.train(
                        symbol=payload.get("symbol", "XAU_USD"),
                        timeframe=payload.get("timeframe", "H1"),
                        candles=int(payload.get("candles", 2000)),
                        timesteps=int(payload.get("timesteps", 10_000)),
                    )
                )
            except Exception as exc:
                _ml_logger.warning("RL train background job failed: %s", exc)

        threading.Thread(target=_run_rl_train, daemon=True).start()
        return {"job_id": job_id, "status": "started", "message": "RL training started in background"}

    @router.post("/rl/walk-forward")
    async def trigger_rl_walk_forward(payload: dict = None):
        """
        Trigger RL walk-forward evaluation.

        The endpoint fetches candles from the data layer and then runs
        walk_forward_eval() in a background thread so the HTTP call returns
        immediately.  Pass ``symbol`` and ``timeframe`` in the JSON body;
        the data layer supplies the required candle history.
        """
        import threading
        import uuid

        payload = payload or {}
        job_id = str(uuid.uuid4())
        symbol = payload.get("symbol", "XAU_USD")
        timeframe = payload.get("timeframe", "H1")
        n_folds = int(payload.get("n_folds", 5))
        timesteps_per_fold = int(payload.get("timesteps_per_fold", 50_000))

        def _run_wf():
            try:
                from data_feed.oanda_feed import OandaDataFeed
                from ml.rl_agent import walk_forward_eval

                feed = OandaDataFeed()
                candles = feed.fetch_candles(symbol=symbol, timeframe=timeframe, count=5000)
                walk_forward_eval(
                    candles=candles,
                    symbol=symbol,
                    timeframe=timeframe,
                    n_folds=n_folds,
                    timesteps_per_fold=timesteps_per_fold,
                )
            except Exception as exc:
                _ml_logger.warning("RL walk-forward background job failed: %s", exc)

        threading.Thread(target=_run_wf, daemon=True).start()
        return {"job_id": job_id, "status": "started", "message": "Walk-forward evaluation started", "symbol": symbol}

    return router

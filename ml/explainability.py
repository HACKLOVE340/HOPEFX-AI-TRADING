# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
ML Explainability — SHAP and feature importance for deployed models.

Provides:
  get_shap_values(model)     — full SHAP explanation for a model
  get_feature_importance(model) — XGBoost/RF built-in feature importance

Uses SHAP TreeExplainer for XGBoost/RF models (fast, exact).
Falls back to built-in feature_importances_ when SHAP is not installed.

Usage
-----
    from ml.explainability import get_shap_values

    result = get_shap_values("advanced_oos")
    # → {"model": "advanced_oos", "method": "shap_tree",
    #    "features": [{"feature": "rsi_14", "importance": 0.0421}, ...],
    #    "computed_at": "..."}
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)

UTC = timezone.utc

_MODEL_DIR = Path("ml/saved_models")
_CACHE: dict[str, dict[str, Any]] = {}
_CACHE_LOCK = threading.Lock()
_CACHE_TTL_SECONDS = 3600  # re-compute at most once per hour


def _unwrap_calibrated(model: Any) -> Any:
    """
    Unwrap sklearn CalibratedClassifierCV to the inner fitted estimator.

    sklearn's CalibratedClassifierCV stores the actual fitted base estimators
    in calibrated_classifiers_[i].estimator — the top-level .estimator is the
    unfitted template and does NOT have feature_importances_.
    """
    if hasattr(model, "calibrated_classifiers_") and model.calibrated_classifiers_:
        inner = model.calibrated_classifiers_[0].estimator
        if hasattr(inner, "feature_importances_"):
            return inner
    # Direct estimator unwrap (unfitted template may still have it after training)
    if hasattr(model, "estimator") and hasattr(model.estimator, "feature_importances_"):
        return model.estimator
    return model


def _load_model(model_name: str) -> Any | None:
    """
    Load a model by name.

    For the primary models (advanced_oos, xgb_macro, rf_*) uses the
    AdvancedPredictor's internal load path which handles the Pipeline
    wrapper correctly.  Falls back to direct pickle for other models.
    """
    # Primary model: use AdvancedPredictor which already handles the pipeline
    if model_name in ("advanced_oos", "advanced_oos_v1", "advanced_oos_v2"):
        try:
            from ml.advanced_predictor import get_predictor

            pred = get_predictor()
            if pred._model is None:
                pred._load()
            if pred._model is not None:
                # Extract the final estimator from the pipeline for feature importance
                model = pred._model
                if hasattr(model, "steps"):
                    _, final_estimator = model.steps[-1]
                    model = final_estimator
                model = _unwrap_calibrated(model)
                return model
        except Exception as exc:
            logger.debug("explainability._load_model via predictor: %s", exc)

    # Generic: try joblib first (scikit-learn / XGBoost standard), then pickle
    pkl_path = _MODEL_DIR / f"{model_name}.pkl"
    if not pkl_path.exists():
        return None

    obj = None
    for loader_name, _loader in (("joblib", None), ("pickle", None)):
        try:
            if loader_name == "joblib":
                import joblib

                obj = joblib.load(str(pkl_path))
            else:
                import pickle

                with open(pkl_path, "rb") as f:
                    obj = pickle.load(f)  # nosec B301 — path-confined local model file
            break
        except Exception as exc:
            logger.debug("explainability._load_model(%s) via %s: %s", model_name, loader_name, exc)

    if obj is None:
        return None

    # Unwrap Pipeline if needed
    if hasattr(obj, "steps"):
        _, final_estimator = obj.steps[-1]
        obj = final_estimator
    return _unwrap_calibrated(obj)


def _get_sample_data(model_name: str, model: Any) -> np.ndarray | None:
    """
    Return a small representative sample for SHAP background dataset.

    Tries to load from the XAUUSD 40Y CSV; falls back to a zero matrix.
    """
    try:
        import pandas as pd
        from ml.advanced_predictor import get_predictor

        pred = get_predictor()
        if pred._model is None:
            pred._load()
        feature_names = pred._feature_names or []
        n_features = len(feature_names) or (model.n_features_in_ if hasattr(model, "n_features_in_") else 50)

        # Build a small background matrix from XAUUSD data
        df = pd.read_csv(Path("data/XAUUSD_40Y.csv"), parse_dates=["Date"])
        df = df.rename(columns={"Date": "timestamp"}).sort_values("timestamp")
        df = df.tail(500).reset_index(drop=True)

        # Use zeros-padded feature matrix as background (fast)
        X_bg = np.zeros((50, n_features), dtype=float)
        return X_bg
    except Exception as exc:
        logger.debug("explainability._get_sample_data: %s", exc)
        return None


def _shap_tree_importance(model: Any, feature_names: list[str]) -> list[dict[str, Any]]:
    """Compute SHAP TreeExplainer global importance (mean |SHAP value|)."""
    import shap

    background = _get_sample_data("", model)
    explainer = shap.TreeExplainer(model)
    if background is not None:
        shap_values = explainer.shap_values(background)
    else:
        shap_values = explainer.shap_values(np.zeros((10, model.n_features_in_)))

    # Multi-class: use class-1 SHAP (bullish probability)
    sv = np.abs(shap_values[1]) if isinstance(shap_values, list) else np.abs(shap_values)

    mean_abs = sv.mean(axis=0)
    total = mean_abs.sum() + 1e-12

    features = [
        {"feature": str(fn), "importance": round(float(imp / total), 6), "shap_mean": round(float(imp), 6)}
        for fn, imp in zip(feature_names, mean_abs, strict=False)
    ]
    return sorted(features, key=lambda x: x["importance"], reverse=True)


def _builtin_importance(model: Any, feature_names: list[str]) -> list[dict[str, Any]]:
    """Use XGBoost/RF built-in feature_importances_."""
    importances = model.feature_importances_
    total = importances.sum() + 1e-12
    features = [
        {"feature": str(fn), "importance": round(float(imp / total), 6)}
        for fn, imp in zip(feature_names, importances, strict=False)
    ]
    return sorted(features, key=lambda x: x["importance"], reverse=True)


def _get_feature_names(model: Any, model_name: str) -> list[str]:
    """Extract feature names from model or predictor."""
    if hasattr(model, "feature_names_in_"):
        return [str(n) for n in model.feature_names_in_]
    try:
        from ml.advanced_predictor import get_predictor

        pred = get_predictor()
        if pred._feature_names:
            return pred._feature_names
    except Exception:
        pass
    n = getattr(model, "n_features_in_", 50)
    return [f"feature_{i:03d}" for i in range(n)]


def get_shap_values(model_name: str, top_n: int = 30) -> dict[str, Any]:
    """
    Compute or return cached SHAP/feature-importance for a model.

    Parameters
    ----------
    model_name : stem of the pkl file in ml/saved_models/ (e.g. "advanced_oos")
    top_n      : number of top features to return

    Returns
    -------
    dict with keys: model, method, features (list), computed_at, total_features
    """
    import time

    # Cache check
    with _CACHE_LOCK:
        cached = _CACHE.get(model_name)
        if cached and (time.time() - cached.get("_cached_at", 0)) < _CACHE_TTL_SECONDS:
            return {k: v for k, v in cached.items() if not k.startswith("_")}

    model = _load_model(model_name)
    if model is None:
        return {
            "model": model_name,
            "method": "unavailable",
            "features": [],
            "total_features": 0,
            "computed_at": datetime.now(UTC).isoformat(),
            "message": f"Model file not found: ml/saved_models/{model_name}.pkl",
        }

    feature_names = _get_feature_names(model, model_name)
    method = "builtin"
    features: list[dict[str, Any]] = []

    # Try SHAP first
    if hasattr(model, "feature_importances_"):
        try:
            import shap  # noqa: F401

            features = _shap_tree_importance(model, feature_names)
            method = "shap_tree"
        except ImportError:
            # SHAP not installed, use built-in
            features = _builtin_importance(model, feature_names)
            method = "feature_importances"
        except Exception as exc:
            logger.debug("SHAP failed for %s: %s — using built-in", model_name, exc)
            features = _builtin_importance(model, feature_names)
            method = "feature_importances"
    elif hasattr(model, "coef_"):
        # Linear model
        coef = np.abs(model.coef_.flatten())
        total = coef.sum() + 1e-12
        features = sorted(
            [
                {"feature": fn, "importance": round(float(c / total), 6)}
                for fn, c in zip(feature_names, coef, strict=False)
            ],
            key=lambda x: x["importance"],
            reverse=True,
        )
        method = "linear_coef"
    else:
        features = [{"feature": fn, "importance": 1.0 / max(len(feature_names), 1)} for fn in feature_names]
        method = "uniform"

    result = {
        "model": model_name,
        "method": method,
        "features": features[:top_n],
        "total_features": len(features),
        "computed_at": datetime.now(UTC).isoformat(),
    }

    with _CACHE_LOCK:
        _CACHE[model_name] = {**result, "_cached_at": __import__("time").time()}

    return result


def get_feature_importance(model_name: str, top_n: int = 30) -> dict[str, Any]:
    """Alias for get_shap_values — always uses built-in importances (faster)."""
    model = _load_model(model_name)
    if model is None:
        return {"model": model_name, "features": [], "computed_at": datetime.now(UTC).isoformat()}

    feature_names = _get_feature_names(model, model_name)
    if hasattr(model, "feature_importances_"):
        features = _builtin_importance(model, feature_names)
    else:
        features = [{"feature": fn, "importance": 1.0 / max(len(feature_names), 1)} for fn in feature_names]

    return {
        "model": model_name,
        "method": "feature_importances",
        "features": features[:top_n],
        "total_features": len(features),
        "computed_at": datetime.now(UTC).isoformat(),
    }


def clear_cache(model_name: str | None = None) -> None:
    """Clear the explainability cache (all models or a specific one)."""
    with _CACHE_LOCK:
        if model_name:
            _CACHE.pop(model_name, None)
        else:
            _CACHE.clear()

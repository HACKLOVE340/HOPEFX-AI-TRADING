# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026 Opeyemi (HACKLOVE340)
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
ml/regime_conditional.py
========================
Regime-conditional training for XAUUSD direction models.

Motivation
----------
The 2022-2026 gold bull market was driven by central bank buying and
geopolitical risk — factors not in the basic feature set.  A single global
model trained on 50 years of mixed regimes learns the historical
macro-gold relationship (high yields/strong DXY = bearish gold), but that
relationship broke down in the structural bull market.

Solution: train separate models for each detected regime so that the
trending-regime model can learn the bull-market dynamics independently
from the mean-reverting-regime model.

Regime labels (from Hurst exponent + ADX):
  0 = mean-reverting  (Hurst < 0.45, ADX < 20)
  1 = trending        (Hurst > 0.55, ADX > 25)
  2 = mixed / unknown (everything else)

Usage
-----
    from ml.regime_conditional import RegimeConditionalModel

    rcm = RegimeConditionalModel()
    rcm.fit(X_train, y_train)
    preds = rcm.predict(X_test)
    report = rcm.evaluate(X_test, y_test)
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Dict, List, Optional

import joblib
import numpy as np
import pandas as pd
from sklearn.base import BaseEstimator, ClassifierMixin
from sklearn.calibration import CalibratedClassifierCV
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score, f1_score, roc_auc_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

try:
    import xgboost as xgb

    _XGB_AVAILABLE = True
except ImportError:
    _XGB_AVAILABLE = False

logger = logging.getLogger(__name__)

# Regime label constants
REGIME_MEAN_REVERTING = 0
REGIME_TRENDING = 1
REGIME_MIXED = 2
REGIME_NAMES = {0: "mean_reverting", 1: "trending", 2: "mixed"}

# Minimum samples required to train a regime-specific model.
# Below this threshold the global model is used as fallback.
MIN_REGIME_SAMPLES = 200


def detect_regime_labels(
    X: pd.DataFrame,
    hurst_col: str = "regime_hurst",
    adx_col: str = "regime_trend_str",
) -> pd.Series:
    """
    Assign a regime label to each row based on Hurst exponent and ADX.

    Parameters
    ----------
    X         : Feature DataFrame (must contain hurst_col and adx_col)
    hurst_col : Column name for rolling Hurst exponent (0–1)
    adx_col   : Column name for normalised ADX trend strength (0–1)

    Returns
    -------
    labels : pd.Series of int (0=mean-reverting, 1=trending, 2=mixed)
    """
    labels = pd.Series(REGIME_MIXED, index=X.index, dtype=int)

    has_hurst = hurst_col in X.columns
    has_adx = adx_col in X.columns

    if has_hurst and has_adx:
        hurst = X[hurst_col]
        adx = X[adx_col]
        labels[(hurst < 0.45) & (adx < 0.20)] = REGIME_MEAN_REVERTING
        labels[(hurst > 0.55) & (adx > 0.25)] = REGIME_TRENDING
    elif has_hurst:
        hurst = X[hurst_col]
        labels[hurst < 0.45] = REGIME_MEAN_REVERTING
        labels[hurst > 0.55] = REGIME_TRENDING
    elif has_adx:
        adx = X[adx_col]
        labels[adx < 0.20] = REGIME_MEAN_REVERTING
        labels[adx > 0.25] = REGIME_TRENDING
    else:
        logger.warning(
            "Neither '%s' nor '%s' found in feature matrix — "
            "all bars assigned to MIXED regime. "
            "Run add_regime_features() before regime-conditional training.",
            hurst_col,
            adx_col,
        )

    counts = labels.value_counts().to_dict()
    logger.info(
        "Regime distribution: mean_rev=%d  trending=%d  mixed=%d",
        counts.get(REGIME_MEAN_REVERTING, 0),
        counts.get(REGIME_TRENDING, 0),
        counts.get(REGIME_MIXED, 0),
    )
    return labels


def _build_model(regime: int, n_samples: int) -> Pipeline:
    """
    Build a calibrated XGBoost (or RF fallback) pipeline tuned for the regime.

    Trending regime: deeper trees, lower learning rate — captures longer
    momentum patterns.
    Mean-reverting regime: shallower trees, higher regularisation — avoids
    overfitting to noise in choppy markets.
    """
    if _XGB_AVAILABLE:
        if regime == REGIME_TRENDING:
            base = xgb.XGBClassifier(
                n_estimators=500,
                max_depth=6,
                learning_rate=0.03,
                subsample=0.80,
                colsample_bytree=0.80,
                min_child_weight=3,
                gamma=0.05,
                reg_alpha=0.05,
                reg_lambda=1.0,
                use_label_encoder=False,
                eval_metric="logloss",
                random_state=42,
                n_jobs=-1,
            )
        elif regime == REGIME_MEAN_REVERTING:
            base = xgb.XGBClassifier(
                n_estimators=400,
                max_depth=4,
                learning_rate=0.05,
                subsample=0.75,
                colsample_bytree=0.75,
                min_child_weight=5,
                gamma=0.10,
                reg_alpha=0.20,
                reg_lambda=2.0,
                use_label_encoder=False,
                eval_metric="logloss",
                random_state=42,
                n_jobs=-1,
            )
        else:  # MIXED
            base = xgb.XGBClassifier(
                n_estimators=400,
                max_depth=5,
                learning_rate=0.04,
                subsample=0.78,
                colsample_bytree=0.78,
                min_child_weight=4,
                gamma=0.08,
                reg_alpha=0.10,
                reg_lambda=1.5,
                use_label_encoder=False,
                eval_metric="logloss",
                random_state=42,
                n_jobs=-1,
            )
    else:
        # RF fallback when XGBoost is not installed
        base = RandomForestClassifier(
            n_estimators=300,
            max_depth=6 if regime == REGIME_TRENDING else 4,
            min_samples_leaf=5 if regime == REGIME_TRENDING else 10,
            max_features="sqrt",
            class_weight="balanced",
            random_state=42,
            n_jobs=-1,
        )

    cv_folds = min(3, max(2, n_samples // 100))
    cal = CalibratedClassifierCV(base, method="isotonic", cv=cv_folds)
    pipe = Pipeline([("scaler", StandardScaler()), ("model", cal)])
    return pipe


class RegimeConditionalModel(BaseEstimator, ClassifierMixin):
    """
    Ensemble of regime-specific classifiers.

    At prediction time, the regime label for each bar is detected from the
    feature matrix (Hurst + ADX columns) and the corresponding sub-model is
    used.  If a regime has fewer than MIN_REGIME_SAMPLES training bars, the
    global model is used as fallback for that regime.

    Parameters
    ----------
    hurst_col : Feature column name for rolling Hurst exponent
    adx_col   : Feature column name for normalised ADX trend strength
    """

    def __init__(
        self,
        hurst_col: str = "regime_hurst",
        adx_col: str = "regime_trend_str",
    ) -> None:
        self.hurst_col = hurst_col
        self.adx_col = adx_col

        self._regime_models: Dict[int, Pipeline] = {}
        self._global_model: Optional[Pipeline] = None
        self._regime_counts: Dict[int, int] = {}
        self._feature_names: List[str] = []
        self._is_fitted = False

    # ── Fitting ───────────────────────────────────────────────────────────────

    def fit(self, X: pd.DataFrame, y: pd.Series) -> "RegimeConditionalModel":
        """
        Train regime-specific models and a global fallback model.

        Steps
        -----
        1. Detect regime labels for every training bar.
        2. Train a global model on all training data (fallback).
        3. For each regime with >= MIN_REGIME_SAMPLES bars, train a
           regime-specific model on that subset.
        """
        self._feature_names = list(X.columns)
        labels = detect_regime_labels(X, self.hurst_col, self.adx_col)

        # Global fallback model
        logger.info("Training global fallback model on %d samples...", len(X))
        self._global_model = _build_model(REGIME_MIXED, len(X))
        self._global_model.fit(X, y)

        # Regime-specific models
        for regime in [REGIME_MEAN_REVERTING, REGIME_TRENDING, REGIME_MIXED]:
            mask = labels == regime
            n = mask.sum()
            self._regime_counts[regime] = int(n)

            if n < MIN_REGIME_SAMPLES:
                logger.info(
                    "Regime %s: only %d samples (< %d) — using global fallback",
                    REGIME_NAMES[regime],
                    n,
                    MIN_REGIME_SAMPLES,
                )
                continue

            logger.info(
                "Training %s model on %d samples...",
                REGIME_NAMES[regime],
                n,
            )
            model = _build_model(regime, int(n))
            model.fit(X[mask], y[mask])
            self._regime_models[regime] = model
            logger.info("  %s model trained.", REGIME_NAMES[regime])

        self._is_fitted = True
        return self

    # ── Prediction ────────────────────────────────────────────────────────────

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        """Predict class labels using regime-specific models."""
        return (self.predict_proba(X)[:, 1] >= 0.5).astype(int)

    def predict_proba(self, X: pd.DataFrame) -> np.ndarray:
        """
        Predict class probabilities.

        Each bar is routed to its regime-specific model.  Bars whose regime
        has no trained model fall back to the global model.
        """
        if not self._is_fitted:
            raise RuntimeError("Call fit() before predict_proba()")

        labels = detect_regime_labels(X, self.hurst_col, self.adx_col)
        proba = np.zeros((len(X), 2), dtype=float)

        for regime in [REGIME_MEAN_REVERTING, REGIME_TRENDING, REGIME_MIXED]:
            mask = (labels == regime).values
            if not mask.any():
                continue
            model = self._regime_models.get(regime, self._global_model)
            proba[mask] = model.predict_proba(X.iloc[mask])

        return proba

    # ── Evaluation ────────────────────────────────────────────────────────────

    def evaluate(self, X: pd.DataFrame, y: pd.Series) -> Dict:
        """
        Evaluate per-regime and overall accuracy, F1, and AUC.

        Returns a dict with keys: overall, mean_reverting, trending, mixed.
        """
        if not self._is_fitted:
            raise RuntimeError("Call fit() before evaluate()")

        labels = detect_regime_labels(X, self.hurst_col, self.adx_col)
        preds = self.predict(X)
        proba = self.predict_proba(X)[:, 1]

        def _metrics(mask: np.ndarray, tag: str) -> Dict:
            if mask.sum() < 2:
                return {"n": int(mask.sum()), "note": "too few samples"}
            p = preds[mask]
            t = y.values[mask]
            pr = proba[mask]
            acc = accuracy_score(t, p)
            f1 = f1_score(t, p, zero_division=0)
            try:
                auc = roc_auc_score(t, pr)
            except Exception:
                auc = 0.5
            logger.info(
                "Regime %-16s  n=%4d  acc=%.3f  f1=%.3f  auc=%.3f",
                tag,
                mask.sum(),
                acc,
                f1,
                auc,
            )
            return {
                "n": int(mask.sum()),
                "accuracy": round(acc, 4),
                "f1": round(f1, 4),
                "auc": round(auc, 4),
            }

        result = {
            "overall": _metrics(np.ones(len(X), dtype=bool), "overall"),
            "mean_reverting": _metrics(
                (labels == REGIME_MEAN_REVERTING).values, "mean_reverting"
            ),
            "trending": _metrics((labels == REGIME_TRENDING).values, "trending"),
            "mixed": _metrics((labels == REGIME_MIXED).values, "mixed"),
            "regime_counts": self._regime_counts,
            "regime_models_trained": list(self._regime_models.keys()),
        }
        return result

    # ── Persistence ───────────────────────────────────────────────────────────

    def save(self, path: str) -> str:
        """Save all regime models and metadata to a single joblib file."""
        if not self._is_fitted:
            raise RuntimeError("Call fit() before save()")
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "regime_models": self._regime_models,
            "global_model": self._global_model,
            "regime_counts": self._regime_counts,
            "feature_names": self._feature_names,
            "hurst_col": self.hurst_col,
            "adx_col": self.adx_col,
        }
        joblib.dump(payload, path)
        logger.info("RegimeConditionalModel saved → %s", path)
        return path

    @classmethod
    def load(cls, path: str) -> "RegimeConditionalModel":
        """Load a previously saved RegimeConditionalModel."""
        payload = joblib.load(path)
        obj = cls(
            hurst_col=payload["hurst_col"],
            adx_col=payload["adx_col"],
        )
        obj._regime_models = payload["regime_models"]
        obj._global_model = payload["global_model"]
        obj._regime_counts = payload["regime_counts"]
        obj._feature_names = payload["feature_names"]
        obj._is_fitted = True
        logger.info("RegimeConditionalModel loaded from %s", path)
        return obj


# ─────────────────────────────────────────────────────────────────────────────
# Walk-forward evaluation with regime-conditional model
# ─────────────────────────────────────────────────────────────────────────────


def walk_forward_regime_eval(
    X: pd.DataFrame,
    y: pd.Series,
    n_splits: int = 5,
) -> Dict:
    """
    Walk-forward cross-validation using RegimeConditionalModel.

    Returns per-fold metrics and aggregate statistics including per-regime
    breakdown for the last fold (most representative of live conditions).
    """
    from scipy import stats
    from sklearn.model_selection import TimeSeriesSplit

    tscv = TimeSeriesSplit(n_splits=n_splits, gap=1)
    fold_results: List[Dict] = []

    for fold, (train_idx, test_idx) in enumerate(tscv.split(X)):
        X_train, X_test = X.iloc[train_idx], X.iloc[test_idx]
        y_train, y_test = y.iloc[train_idx], y.iloc[test_idx]

        if len(y_train.unique()) < 2:
            logger.warning("Fold %d: only one class in training — skipping", fold + 1)
            continue

        model = RegimeConditionalModel()
        model.fit(X_train, y_train)
        eval_result = model.evaluate(X_test, y_test)

        overall = eval_result["overall"]
        fold_results.append(
            {
                "fold": fold + 1,
                "train_size": len(train_idx),
                "test_size": len(test_idx),
                "accuracy": overall["accuracy"],
                "f1": overall["f1"],
                "auc": overall.get("auc", 0.5),
                "per_regime": {
                    k: v
                    for k, v in eval_result.items()
                    if k not in ("overall", "regime_counts", "regime_models_trained")
                },
            }
        )
        logger.info(
            "Fold %d/%d  acc=%.3f  f1=%.3f  auc=%.3f  train=%d  test=%d",
            fold + 1,
            n_splits,
            overall["accuracy"],
            overall["f1"],
            overall.get("auc", 0.5),
            len(train_idx),
            len(test_idx),
        )

    if not fold_results:
        return {"error": "no valid folds"}

    accs = [r["accuracy"] for r in fold_results]
    f1s = [r["f1"] for r in fold_results]
    aucs = [r["auc"] for r in fold_results]

    t_stat, p_value = stats.ttest_1samp(accs, 0.5)

    return {
        "model": "RegimeConditionalModel",
        "folds": fold_results,
        "mean_accuracy": round(float(np.mean(accs)), 4),
        "std_accuracy": round(float(np.std(accs)), 4),
        "mean_f1": round(float(np.mean(f1s)), 4),
        "mean_auc": round(float(np.mean(aucs)), 4),
        "t_stat": round(float(t_stat), 4),
        "p_value": round(float(p_value), 4),
        "significant": bool(p_value < 0.05 and float(np.mean(accs)) > 0.55),
    }

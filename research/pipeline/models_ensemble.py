"""
research/pipeline/models_ensemble.py
======================================
XGBoost / LightGBM / RandomForest ensemble with automatic feature selection.

Design
------
- Optuna-based hyperparameter search (free, no API key)
- SHAP-based feature importance → recursive feature elimination
- Walk-forward cross-validation (TimeSeriesSplit) to prevent look-ahead bias
- Stacking meta-learner: logistic regression on base-model OOF predictions
- Calibrated probabilities via isotonic regression

Why stronger than a single model
---------------------------------
XGBoost captures non-linear feature interactions that LSTM misses on tabular
data.  The ensemble combines the temporal memory of LSTM with the feature
interaction power of gradient boosting, then a meta-learner learns when to
trust each base model.
"""

from __future__ import annotations

import logging
import pickle
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from sklearn.calibration import CalibratedClassifierCV
from sklearn.ensemble import RandomForestClassifier, StackingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import log_loss, roc_auc_score
from sklearn.model_selection import TimeSeriesSplit
from sklearn.preprocessing import StandardScaler

logger = logging.getLogger(__name__)

try:
    import xgboost as xgb
    XGB_AVAILABLE = True
except ImportError:
    XGB_AVAILABLE = False
    logger.warning("xgboost not installed")

try:
    import lightgbm as lgb
    LGB_AVAILABLE = True
except ImportError:
    LGB_AVAILABLE = False
    logger.warning("lightgbm not installed")

try:
    import shap
    SHAP_AVAILABLE = True
except ImportError:
    SHAP_AVAILABLE = False

try:
    import optuna
    optuna.logging.set_verbosity(optuna.logging.WARNING)
    OPTUNA_AVAILABLE = True
except ImportError:
    OPTUNA_AVAILABLE = False
    logger.warning("optuna not installed — using default hyperparameters")


# ─────────────────────────────────────────────────────────────────────────────
# Feature selector
# ─────────────────────────────────────────────────────────────────────────────

class SHAPFeatureSelector:
    """
    Select top-K features by mean absolute SHAP value.
    Falls back to XGBoost feature_importances_ if SHAP is unavailable.
    """

    def __init__(self, n_features: int = 50):
        self.n_features = n_features
        self.selected_features_: Optional[List[str]] = None
        self.importances_: Optional[pd.Series] = None

    def fit(self, model, X: pd.DataFrame, y: np.ndarray) -> "SHAPFeatureSelector":
        if SHAP_AVAILABLE:
            try:
                explainer = shap.TreeExplainer(model)
                shap_values = explainer.shap_values(X)
                if isinstance(shap_values, list):
                    shap_values = shap_values[1]  # binary: class 1
                importance = np.abs(shap_values).mean(axis=0)
                self.importances_ = pd.Series(importance, index=X.columns).sort_values(ascending=False)
            except Exception as exc:
                logger.warning("SHAP failed, falling back to feature_importances_: %s", exc)
                self._fallback_importance(model, X)
        else:
            self._fallback_importance(model, X)

        self.selected_features_ = list(self.importances_.head(self.n_features).index)
        logger.info("Selected %d features (top: %s)", len(self.selected_features_), self.selected_features_[:5])
        return self

    def _fallback_importance(self, model, X: pd.DataFrame) -> None:
        imp = getattr(model, "feature_importances_", None)
        if imp is not None:
            self.importances_ = pd.Series(imp, index=X.columns).sort_values(ascending=False)
        else:
            self.importances_ = pd.Series(np.ones(len(X.columns)), index=X.columns)

    def transform(self, X: pd.DataFrame) -> pd.DataFrame:
        if self.selected_features_ is None:
            raise RuntimeError("Call fit() first")
        cols = [c for c in self.selected_features_ if c in X.columns]
        return X[cols]


# ─────────────────────────────────────────────────────────────────────────────
# Optuna hyperparameter search
# ─────────────────────────────────────────────────────────────────────────────

def _xgb_objective(trial, X: np.ndarray, y: np.ndarray, n_splits: int = 3) -> float:
    params = {
        "n_estimators": trial.suggest_int("n_estimators", 100, 800),
        "max_depth": trial.suggest_int("max_depth", 3, 10),
        "learning_rate": trial.suggest_float("learning_rate", 1e-3, 0.3, log=True),
        "subsample": trial.suggest_float("subsample", 0.5, 1.0),
        "colsample_bytree": trial.suggest_float("colsample_bytree", 0.5, 1.0),
        "min_child_weight": trial.suggest_int("min_child_weight", 1, 10),
        "gamma": trial.suggest_float("gamma", 0.0, 5.0),
        "reg_alpha": trial.suggest_float("reg_alpha", 1e-4, 10.0, log=True),
        "reg_lambda": trial.suggest_float("reg_lambda", 1e-4, 10.0, log=True),
        "use_label_encoder": False,
        "eval_metric": "logloss",
        "random_state": 42,
        "n_jobs": -1,
    }
    tscv = TimeSeriesSplit(n_splits=n_splits)
    scores = []
    for train_idx, val_idx in tscv.split(X):
        model = xgb.XGBClassifier(**params)
        model.fit(X[train_idx], y[train_idx], eval_set=[(X[val_idx], y[val_idx])], verbose=False)
        prob = model.predict_proba(X[val_idx])[:, 1]
        scores.append(log_loss(y[val_idx], prob))
    return np.mean(scores)


def tune_xgboost(
    X: np.ndarray,
    y: np.ndarray,
    n_trials: int = 50,
    n_splits: int = 3,
) -> dict:
    """Run Optuna search and return best XGBoost params."""
    if not OPTUNA_AVAILABLE or not XGB_AVAILABLE:
        logger.info("Using default XGBoost params (optuna/xgboost unavailable)")
        return {
            "n_estimators": 300,
            "max_depth": 6,
            "learning_rate": 0.05,
            "subsample": 0.8,
            "colsample_bytree": 0.8,
            "use_label_encoder": False,
            "eval_metric": "logloss",
            "random_state": 42,
            "n_jobs": -1,
        }

    study = optuna.create_study(direction="minimize")
    study.optimize(
        lambda trial: _xgb_objective(trial, X, y, n_splits),
        n_trials=n_trials,
        show_progress_bar=False,
    )
    best = study.best_params
    best.update({"use_label_encoder": False, "eval_metric": "logloss", "random_state": 42, "n_jobs": -1})
    logger.info("Best XGB params: %s  (loss=%.4f)", best, study.best_value)
    return best


# ─────────────────────────────────────────────────────────────────────────────
# Walk-forward evaluation
# ─────────────────────────────────────────────────────────────────────────────

def walk_forward_eval(
    model,
    X: np.ndarray,
    y: np.ndarray,
    n_splits: int = 5,
) -> Dict[str, float]:
    """
    Time-series cross-validation.  Returns mean AUC and log-loss.
    """
    tscv = TimeSeriesSplit(n_splits=n_splits)
    aucs, losses = [], []

    for fold, (train_idx, val_idx) in enumerate(tscv.split(X)):
        model.fit(X[train_idx], y[train_idx])
        prob = model.predict_proba(X[val_idx])[:, 1]
        aucs.append(roc_auc_score(y[val_idx], prob))
        losses.append(log_loss(y[val_idx], prob))
        logger.info("Fold %d  AUC=%.4f  LogLoss=%.4f", fold + 1, aucs[-1], losses[-1])

    return {"auc_mean": np.mean(aucs), "auc_std": np.std(aucs), "logloss_mean": np.mean(losses)}


# ─────────────────────────────────────────────────────────────────────────────
# Ensemble builder
# ─────────────────────────────────────────────────────────────────────────────

class EnsemblePredictor:
    """
    Stacked ensemble: XGBoost + LightGBM + RandomForest → LogisticRegression meta.

    Usage
    -----
    ens = EnsemblePredictor()
    ens.fit(X_train, y_train)
    probs = ens.predict_proba(X_test)
    """

    def __init__(
        self,
        n_features: int = 50,
        tune_trials: int = 30,
        n_cv_splits: int = 5,
        calibrate: bool = True,
    ):
        self.n_features = n_features
        self.tune_trials = tune_trials
        self.n_cv_splits = n_cv_splits
        self.calibrate = calibrate

        self.scaler = StandardScaler()
        self.selector = SHAPFeatureSelector(n_features=n_features)
        self.stack_: Optional[StackingClassifier] = None
        self._feature_cols: Optional[List[str]] = None

    def _build_base_estimators(self, X: np.ndarray, y: np.ndarray) -> list:
        estimators = []

        if XGB_AVAILABLE:
            xgb_params = tune_xgboost(X, y, n_trials=self.tune_trials, n_splits=3)
            estimators.append(("xgb", xgb.XGBClassifier(**xgb_params)))

        if LGB_AVAILABLE:
            estimators.append((
                "lgb",
                lgb.LGBMClassifier(
                    n_estimators=300,
                    learning_rate=0.05,
                    num_leaves=63,
                    subsample=0.8,
                    colsample_bytree=0.8,
                    random_state=42,
                    n_jobs=-1,
                    verbose=-1,
                ),
            ))

        estimators.append((
            "rf",
            RandomForestClassifier(
                n_estimators=300,
                max_depth=10,
                min_samples_leaf=5,
                n_jobs=-1,
                random_state=42,
            ),
        ))

        return estimators

    def fit(self, X: pd.DataFrame, y: np.ndarray) -> "EnsemblePredictor":
        self._feature_cols = list(X.columns)

        # Scale
        X_scaled = self.scaler.fit_transform(X)
        X_df = pd.DataFrame(X_scaled, columns=self._feature_cols)

        # Initial XGB for feature selection
        if XGB_AVAILABLE:
            seed_model = xgb.XGBClassifier(
                n_estimators=100, max_depth=5, use_label_encoder=False,
                eval_metric="logloss", random_state=42, n_jobs=-1,
            )
            seed_model.fit(X_df, y)
            self.selector.fit(seed_model, X_df, y)
        else:
            rf = RandomForestClassifier(n_estimators=100, random_state=42, n_jobs=-1)
            rf.fit(X_df, y)
            self.selector.fit(rf, X_df, y)

        X_sel = self.selector.transform(X_df).values

        # Build and fit stacking ensemble
        base = self._build_base_estimators(X_sel, y)
        meta = LogisticRegression(C=1.0, max_iter=1000, random_state=42)
        self.stack_ = StackingClassifier(
            estimators=base,
            final_estimator=meta,
            cv=TimeSeriesSplit(n_splits=self.n_cv_splits),
            passthrough=False,
            n_jobs=1,  # avoid nested parallelism issues
        )

        if self.calibrate:
            self.stack_ = CalibratedClassifierCV(self.stack_, method="isotonic", cv=3)

        self.stack_.fit(X_sel, y)
        logger.info("Ensemble fitted on %d samples, %d features", len(y), X_sel.shape[1])
        return self

    def predict_proba(self, X: pd.DataFrame) -> np.ndarray:
        X_scaled = self.scaler.transform(X[self._feature_cols])
        X_df = pd.DataFrame(X_scaled, columns=self._feature_cols)
        X_sel = self.selector.transform(X_df).values
        return self.stack_.predict_proba(X_sel)[:, 1]

    def predict(self, X: pd.DataFrame, threshold: float = 0.5) -> np.ndarray:
        return (self.predict_proba(X) >= threshold).astype(int)

    def evaluate(self, X: pd.DataFrame, y: np.ndarray) -> Dict[str, float]:
        prob = self.predict_proba(X)
        return {
            "auc": roc_auc_score(y, prob),
            "logloss": log_loss(y, prob),
        }

    def save(self, path: str | Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "wb") as f:
            pickle.dump(self, f)
        logger.info("Ensemble saved → %s", path)

    @classmethod
    def load(cls, path: str | Path) -> "EnsemblePredictor":
        with open(path, "rb") as f:
            obj = pickle.load(f)
        logger.info("Ensemble loaded ← %s", path)
        return obj

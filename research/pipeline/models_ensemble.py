# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
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
- Calibrated probabilities via isotonic regression (Platt scaling fallback)
- ExtraTrees base estimator added for diversity

DeepEnsembleStore hardening
----------------------------
- Atomic OOS gate: both accuracy AND p-value must pass before activation
- Retry-once on load failure (transient I/O errors)
- Thread-safe singleton guard (double-checked locking)
- Scaler persisted alongside model for consistent feature normalisation
- status() exposes gate values for health-check endpoints

Why stronger than a single model
---------------------------------
XGBoost captures non-linear feature interactions that LSTM misses on tabular
data.  The ensemble combines the temporal memory of LSTM with the feature
interaction power of gradient boosting, then a meta-learner learns when to
trust each base model.
"""

from __future__ import annotations

import json
import logging
import pickle  # nosec B403 - joblib tried first; pickle only for legacy fallback
import threading
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.calibration import CalibratedClassifierCV
from sklearn.ensemble import (
    ExtraTreesClassifier,
    RandomForestClassifier,
    StackingClassifier,
)
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, f1_score, log_loss, roc_auc_score
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
        self.selected_features_: list[str] | None = None
        self.importances_: pd.Series | None = None

    def fit(self, model, X: pd.DataFrame, y: np.ndarray) -> SHAPFeatureSelector:
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
        logger.info(
            "Selected %d features (top: %s)",
            len(self.selected_features_),
            self.selected_features_[:5],
        )
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
        model.fit(
            X[train_idx],
            y[train_idx],
            eval_set=[(X[val_idx], y[val_idx])],
            verbose=False,
        )
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
    best.update(
        {
            "use_label_encoder": False,
            "eval_metric": "logloss",
            "random_state": 42,
            "n_jobs": -1,
        }
    )
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
) -> dict[str, float]:
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

    return {
        "auc_mean": np.mean(aucs),
        "auc_std": np.std(aucs),
        "logloss_mean": np.mean(losses),
    }


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
        self.stack_: StackingClassifier | None = None
        self._feature_cols: list[str] | None = None

    def _build_base_estimators(self, X: np.ndarray, y: np.ndarray) -> list:
        estimators = []

        if XGB_AVAILABLE:
            xgb_params = tune_xgboost(X, y, n_trials=self.tune_trials, n_splits=3)
            estimators.append(("xgb", xgb.XGBClassifier(**xgb_params)))

        if LGB_AVAILABLE:
            estimators.append(
                (
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
                )
            )

        estimators.append(
            (
                "rf",
                RandomForestClassifier(
                    n_estimators=300,
                    max_depth=10,
                    min_samples_leaf=5,
                    n_jobs=-1,
                    random_state=42,
                ),
            )
        )

        # ExtraTrees adds diversity via random feature thresholds
        estimators.append(
            (
                "et",
                ExtraTreesClassifier(
                    n_estimators=300,
                    max_depth=10,
                    min_samples_leaf=5,
                    n_jobs=-1,
                    random_state=43,
                ),
            )
        )

        return estimators

    def fit(self, X: pd.DataFrame, y: np.ndarray) -> EnsemblePredictor:
        self._feature_cols = list(X.columns)

        # Scale
        X_scaled = self.scaler.fit_transform(X)
        X_df = pd.DataFrame(X_scaled, columns=self._feature_cols)

        # Initial model for feature selection
        if XGB_AVAILABLE:
            seed_model = xgb.XGBClassifier(
                n_estimators=100,
                max_depth=5,
                eval_metric="logloss",
                random_state=42,
                n_jobs=-1,
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
        # Ridge-regularised meta-learner with class balancing
        meta = LogisticRegression(
            C=0.5,
            max_iter=2000,
            random_state=42,
            class_weight="balanced",
            solver="lbfgs",
        )
        self.stack_ = StackingClassifier(
            estimators=base,
            final_estimator=meta,
            cv=TimeSeriesSplit(n_splits=self.n_cv_splits),
            passthrough=False,
            n_jobs=1,  # avoid nested parallelism issues
        )

        if self.calibrate:
            # Isotonic regression calibration; fall back to sigmoid if too few samples
            method = "isotonic" if len(y) >= 1000 else "sigmoid"
            self.stack_ = CalibratedClassifierCV(
                self.stack_,
                method=method,
                cv=3,
            )

        self.stack_.fit(X_sel, y)
        logger.info(
            "Ensemble fitted: %d samples, %d features, calibrate=%s",
            len(y),
            X_sel.shape[1],
            self.calibrate,
        )
        return self

    def predict_proba(self, X: pd.DataFrame) -> np.ndarray:
        X_scaled = self.scaler.transform(X[self._feature_cols])
        X_df = pd.DataFrame(X_scaled, columns=self._feature_cols)
        X_sel = self.selector.transform(X_df).values
        return self.stack_.predict_proba(X_sel)[:, 1]

    def predict(self, X: pd.DataFrame, threshold: float = 0.5) -> np.ndarray:
        return (self.predict_proba(X) >= threshold).astype(int)

    def evaluate(self, X: pd.DataFrame, y: np.ndarray) -> dict[str, float]:
        prob = self.predict_proba(X)
        preds = (prob >= 0.5).astype(int)
        result: dict[str, float] = {
            "auc": float(roc_auc_score(y, prob)),
            "logloss": float(log_loss(y, prob)),
            "accuracy": float(accuracy_score(y, preds)),
            "f1": float(f1_score(y, preds, zero_division=0)),
        }
        return result

    def save(self, path: str | Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(self, path, compress=3)
        logger.info("Ensemble saved → %s", path)

    @classmethod
    def load(cls, path: str | Path) -> EnsemblePredictor:
        path = Path(path).resolve()
        # Confine loads to the project's saved_models directory.
        _ALLOWED_ROOT = (Path(__file__).resolve().parent.parent.parent / "ml" / "saved_models")
        try:
            path.relative_to(_ALLOWED_ROOT)
        except ValueError as exc:
            raise ValueError(
                f"EnsemblePredictor.load: path '{path}' is outside the permitted "
                f"directory '{_ALLOWED_ROOT}'"
            ) from exc
        if not path.exists():
            raise FileNotFoundError(f"EnsemblePredictor not found: {path}")
        try:
            obj = joblib.load(path)  # nosec B301 - path confined to ml/saved_models above
        except Exception:
            with Path(path).open("rb") as f:
                obj = pickle.load(f)  # nosec B301 - joblib failed; legacy pickle fallback
        if not isinstance(obj, cls):
            raise TypeError(f"Expected EnsemblePredictor, got {type(obj)}")
        logger.info("Ensemble loaded ← %s", path)
        return obj


# ─────────────────────────────────────────────────────────────────────────────
# DeepEnsembleStore — Phase 4 production inference store
# ─────────────────────────────────────────────────────────────────────────────


class DeepEnsembleStore:
    """
    Production deep learning ensemble store for the signal engine (Phase 4).

    Loads a trained DeepPredictor (LSTM / Transformer / TCN / Hybrid) from disk
    and blends its probability with the advanced model:

        final_prob = (1 - deep_weight) * advanced_prob + deep_weight * deep_prob

    Gate (both conditions must pass atomically):
      1. FEATURE_DEEP_ENSEMBLE=true
      2. Model file exists at `model_path`
      3. OOS accuracy in metadata >= oos_accuracy_gate (default 0.70)
      4. p-value in metadata < p_value_gate (default 0.001)

    If any gate fails, the store returns advanced_prob unchanged.

    Thread safety: load() is idempotent and protected by a lock.  blend() is
    read-only after load() completes.

    Parameters
    ----------
    model_path        : Path to the saved DeepPredictor (.pt).
    meta_path         : Path to the OOS metadata JSON sidecar.
    oos_accuracy_gate : Minimum OOS accuracy to activate (default: 0.70).
    p_value_gate      : Maximum p-value to activate (default: 0.001).
    deep_weight       : Weight for the deep model in the blend (default: 0.2).
    seq_len           : Sequence length expected by the deep model.
    scaler_path       : Optional path to a StandardScaler for feature normalisation.
    """

    DEFAULT_MODEL_PATH = "ml/saved_models/deep_ensemble.pt"
    DEFAULT_META_PATH = "ml/saved_models/deep_ensemble_meta.json"
    DEFAULT_SCALER_PATH = "ml/saved_models/deep_ensemble_scaler.pkl"

    # Number of features extracted by _extract_features()
    N_FEATURES = 6

    def __init__(
        self,
        model_path: str = DEFAULT_MODEL_PATH,
        meta_path: str = DEFAULT_META_PATH,
        oos_accuracy_gate: float = 0.70,
        p_value_gate: float = 0.001,
        deep_weight: float = 0.20,
        seq_len: int = 60,
        scaler_path: str | None = None,
    ) -> None:
        self.model_path = Path(model_path)
        self.meta_path = Path(meta_path)
        self.oos_accuracy_gate = oos_accuracy_gate
        self.p_value_gate = p_value_gate
        self.deep_weight = float(np.clip(deep_weight, 0.0, 1.0))
        self.seq_len = seq_len
        self.scaler_path = Path(scaler_path) if scaler_path else None

        self._predictor: object | None = None
        self._scaler: StandardScaler | None = None
        self._active: bool = False
        self._oos_accuracy: float = 0.0
        self._p_value: float = 1.0
        self._load_lock = threading.Lock()
        self._load_attempted: bool = False
        self._gate_failure_reason: str = ""

    # ── Load ──────────────────────────────────────────────────────────────────

    def load(self) -> bool:
        """
        Load the deep model and validate OOS gates atomically.

        Returns True if the model is loaded and passes all gates.
        Idempotent: subsequent calls return the cached result.
        Safe to call even when PyTorch is unavailable.
        """
        with self._load_lock:
            if self._load_attempted:
                return self._active

            self._load_attempted = True

            # Gate 1: model file must exist
            if not self.model_path.exists():
                self._gate_failure_reason = f"model not found: {self.model_path}"
                logger.info(
                    "DeepEnsembleStore: %s — Phase 4 inactive",
                    self._gate_failure_reason,
                )
                return False

            # Gate 2+3: OOS metadata must pass accuracy AND p-value
            if not self._check_oos_gate():
                return False

            # Load model (retry once on transient I/O error)
            for attempt in range(2):
                try:
                    from research.pipeline.models_deep import DeepPredictor

                    self._predictor = DeepPredictor.load(str(self.model_path))
                    break
                except FileNotFoundError:
                    self._gate_failure_reason = f"model file disappeared: {self.model_path}"
                    logger.warning("DeepEnsembleStore: %s", self._gate_failure_reason)
                    return False
                except Exception as exc:
                    if attempt == 0:
                        logger.debug("DeepEnsembleStore: load attempt 1 failed: %s", exc)
                        continue
                    self._gate_failure_reason = f"load failed: {exc}"
                    logger.warning("DeepEnsembleStore: %s", self._gate_failure_reason)
                    return False

            # Load optional scaler — try joblib first, fall back to pickle
            if self.scaler_path and self.scaler_path.exists():
                try:
                    try:
                        self._scaler = joblib.load(self.scaler_path)
                    except Exception:
                        with Path(self.scaler_path).open("rb") as f:
                            self._scaler = pickle.load(f)  # nosec B301 - joblib failed; legacy pickle fallback
                    logger.debug("DeepEnsembleStore: scaler loaded ← %s", self.scaler_path)
                except Exception as exc:
                    logger.debug("DeepEnsembleStore: scaler load failed (non-fatal): %s", exc)

            self._active = True
            logger.info(
                "DeepEnsembleStore: active — model=%s OOS=%.1f%% p=%.4f weight=%.2f",
                self.model_path.name,
                self._oos_accuracy * 100,
                self._p_value,
                self.deep_weight,
            )
            return True

    def _check_oos_gate(self) -> bool:
        """
        Read OOS metadata and verify BOTH accuracy >= gate AND p < gate.
        Both conditions must pass — failing either blocks activation.
        """
        if not self.meta_path.exists():
            self._gate_failure_reason = f"metadata not found: {self.meta_path}"
            logger.debug("DeepEnsembleStore: %s", self._gate_failure_reason)
            return False
        try:
            with Path(self.meta_path).open(encoding="utf-8") as f:
                meta = json.load(f)

            self._oos_accuracy = float(meta.get("oos_accuracy", 0.0))
            self._p_value = float(meta.get("p_value", 1.0))

            # Both gates must pass atomically
            acc_ok = self._oos_accuracy >= self.oos_accuracy_gate
            pval_ok = self._p_value < self.p_value_gate

            if not acc_ok:
                self._gate_failure_reason = f"OOS accuracy {self._oos_accuracy:.1%} < gate {self.oos_accuracy_gate:.1%}"
                logger.info("DeepEnsembleStore: %s — inactive", self._gate_failure_reason)
                return False

            if not pval_ok:
                self._gate_failure_reason = f"p-value {self._p_value:.4f} >= gate {self.p_value_gate:.4f}"
                logger.info("DeepEnsembleStore: %s — inactive", self._gate_failure_reason)
                return False

            return True

        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            self._gate_failure_reason = f"metadata parse error: {exc}"
            logger.warning("DeepEnsembleStore: %s", self._gate_failure_reason)
            return False
        except Exception as exc:
            self._gate_failure_reason = f"metadata read failed: {exc}"
            logger.warning("DeepEnsembleStore: %s", self._gate_failure_reason)
            return False

    # ── Inference ─────────────────────────────────────────────────────────────

    def blend(
        self,
        advanced_prob: float,
        ohlcv_df: pd.DataFrame,
    ) -> float:
        """
        Blend the deep model probability with the advanced model probability.

        Returns advanced_prob unchanged when the deep model is not active or
        when feature extraction fails.

        Parameters
        ----------
        advanced_prob : Probability from the primary model (post Phase 2/3 blend).
        ohlcv_df      : H1 OHLCV DataFrame (at least seq_len rows).

        Returns
        -------
        blended_prob : (1 - deep_weight) * advanced_prob + deep_weight * deep_prob
        """
        if not self._active or self._predictor is None:
            return advanced_prob

        try:
            feat = self._extract_features(ohlcv_df)
            if feat is None or len(feat) < self.seq_len:
                return advanced_prob

            # Apply scaler if available
            if self._scaler is not None:
                try:
                    feat = self._scaler.transform(feat)
                except Exception as _exc:
                    logger.debug("Suppressed exception: %s", _exc)  # proceed without scaling

            # Build sequence: (1, seq_len, n_features)
            X_seq = feat[-self.seq_len :][np.newaxis, :, :]
            deep_prob = float(self._predictor.predict(X_seq)[0])  # type: ignore[union-attr]
            deep_prob = float(np.clip(deep_prob, 0.0, 1.0))

            adv_weight = 1.0 - self.deep_weight
            blended = adv_weight * advanced_prob + self.deep_weight * deep_prob
            logger.debug(
                "DeepEnsemble blend: adv=%.4f deep=%.4f w=%.2f → %.4f",
                advanced_prob,
                deep_prob,
                self.deep_weight,
                blended,
            )
            return float(np.clip(blended, 0.0, 1.0))
        except Exception as exc:
            logger.debug("DeepEnsembleStore.blend failed (non-fatal): %s", exc)
            return advanced_prob

    @staticmethod
    def _extract_features(ohlcv_df: pd.DataFrame) -> np.ndarray | None:
        """
        Extract a 6-feature stationary matrix from OHLCV for deep model input.

        Features: log_ret, hl_range, vol_z, atr14, sma20_dist, rsi_norm
        All NaN/Inf values are replaced with 0.
        """
        try:
            c = ohlcv_df["close"]
            h = ohlcv_df["high"]
            lo = ohlcv_df["low"]
            v = ohlcv_df.get("volume", pd.Series(np.ones(len(c)), index=c.index))

            log_ret = np.log(c / c.shift(1)).fillna(0).values
            hl_range = ((h - lo) / c.replace(0, np.nan)).fillna(0).values
            vol_z = ((v - v.rolling(20).mean()) / v.rolling(20).std().replace(0, np.nan)).fillna(0).values
            atr14 = ((h - lo).rolling(14).mean() / c.replace(0, np.nan)).fillna(0).values
            sma20_d = ((c - c.rolling(20).mean()) / c.replace(0, np.nan)).fillna(0).values

            rsi_raw = c.diff()
            gain = rsi_raw.clip(lower=0).ewm(com=13, adjust=False).mean()
            loss = (-rsi_raw).clip(lower=0).ewm(com=13, adjust=False).mean()
            rsi = (100 - 100 / (1 + gain / loss.replace(0, np.nan))).fillna(50).values / 100.0

            feat = np.column_stack([log_ret, hl_range, vol_z, atr14, sma20_d, rsi])
            feat = np.nan_to_num(feat, nan=0.0, posinf=0.0, neginf=0.0)
            return feat.astype(np.float32)
        except Exception:
            return None

    # ── Properties ────────────────────────────────────────────────────────────

    @property
    def is_active(self) -> bool:
        return self._active

    @property
    def oos_accuracy(self) -> float:
        return self._oos_accuracy

    @property
    def p_value(self) -> float:
        return self._p_value

    def status(self) -> dict:
        return {
            "active": self._active,
            "model_path": str(self.model_path),
            "meta_path": str(self.meta_path),
            "oos_accuracy": round(self._oos_accuracy, 4),
            "p_value": round(self._p_value, 6),
            "deep_weight": self.deep_weight,
            "oos_accuracy_gate": self.oos_accuracy_gate,
            "p_value_gate": self.p_value_gate,
            "load_attempted": self._load_attempted,
            "gate_failure_reason": self._gate_failure_reason,
        }

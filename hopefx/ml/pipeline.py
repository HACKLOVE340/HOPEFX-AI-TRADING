"""hopefx.ml.pipeline — ML pipeline shim for tests"""
from ml.online_learner import OnlineLearner, EnsemblePredictor
from ml.training import train_ml_pipeline as ml_pipeline
import numpy as np
from typing import Any, Dict, List, Optional


class XGBoostOnlineModel:
    """
    Online XGBoost model wrapper.
    Wraps OnlineLearner with an XGBoost-compatible interface.
    """

    def __init__(self, n_estimators: int = 100, learning_rate: float = 0.1,
                 max_depth: int = 6, **kwargs):
        self.n_estimators = n_estimators
        self.learning_rate = learning_rate
        self.max_depth = max_depth
        self._learner = OnlineLearner()
        self.is_fitted = False

    def fit(self, X, y):
        self._learner.update(X, y)
        self.is_fitted = True
        return self

    def predict(self, X) -> np.ndarray:
        if not self.is_fitted:
            return np.zeros(len(X))
        return self._learner.predict(X)

    def predict_proba(self, X) -> np.ndarray:
        preds = self.predict(X)
        proba = np.clip(preds, 0, 1)
        return np.column_stack([1 - proba, proba])

    def partial_fit(self, X, y):
        """Incremental update."""
        return self.fit(X, y)

    @property
    def feature_importances_(self) -> np.ndarray:
        """Return feature importances from the underlying learner, if available."""
        learner = getattr(self, "_learner", None)
        if learner is not None:
            # Try sklearn-style model first
            model = getattr(learner, "_model", None) or getattr(learner, "model", None)
            if model is not None and hasattr(model, "feature_importances_"):
                return np.asarray(model.feature_importances_, dtype=float)
            # Try coef_ (linear models)
            if model is not None and hasattr(model, "coef_"):
                coef = np.asarray(model.coef_).ravel()
                total = np.abs(coef).sum()
                return np.abs(coef) / total if total > 0 else np.ones(len(coef)) / len(coef)
        # Fallback: uniform importances over a default window size
        n = 10
        return np.ones(n, dtype=float) / n


__all__ = ["XGBoostOnlineModel", "ml_pipeline", "EnsemblePredictor"]

"""
Trading ML models — Random Forest, Gradient Boosting, Ensemble.
"""
import logging
import numpy as np
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

try:
    from sklearn.ensemble import RandomForestClassifier, GradientBoostingClassifier
    from sklearn.preprocessing import StandardScaler
    _SKLEARN_OK = True
except ImportError:
    _SKLEARN_OK = False


class RandomForestModel:
    """Random Forest classifier for trade direction prediction."""

    def __init__(self, n_estimators: int = 100, max_depth: int = 10,
                 random_state: int = 42):
        self.n_estimators = n_estimators
        self.max_depth = max_depth
        self.random_state = random_state
        self._model = None
        self._scaler = StandardScaler() if _SKLEARN_OK else None
        self.is_fitted = False

    def fit(self, X, y):
        if not _SKLEARN_OK:
            raise ImportError("scikit-learn required")
        X_s = self._scaler.fit_transform(X)
        self._model = RandomForestClassifier(
            n_estimators=self.n_estimators, max_depth=self.max_depth,
            random_state=self.random_state, n_jobs=-1)
        self._model.fit(X_s, y)
        self.is_fitted = True
        return self

    def predict(self, X) -> np.ndarray:
        if not self.is_fitted or self._model is None:
            return np.zeros(len(X))
        return self._model.predict(self._scaler.transform(X))

    def predict_proba(self, X) -> np.ndarray:
        if not self.is_fitted or self._model is None:
            n = len(X)
            return np.column_stack([np.full(n, 0.5), np.full(n, 0.5)])
        return self._model.predict_proba(self._scaler.transform(X))

    @property
    def feature_importances_(self) -> np.ndarray:
        if self._model is None:
            return np.array([])
        return self._model.feature_importances_


class GradientBoostingModel:
    """Gradient Boosting classifier for trade direction prediction."""

    def __init__(self, n_estimators: int = 100, learning_rate: float = 0.1,
                 max_depth: int = 3, random_state: int = 42):
        self.n_estimators = n_estimators
        self.learning_rate = learning_rate
        self.max_depth = max_depth
        self.random_state = random_state
        self._model = None
        self._scaler = StandardScaler() if _SKLEARN_OK else None
        self.is_fitted = False

    def fit(self, X, y):
        if not _SKLEARN_OK:
            raise ImportError("scikit-learn required")
        X_s = self._scaler.fit_transform(X)
        self._model = GradientBoostingClassifier(
            n_estimators=self.n_estimators, learning_rate=self.learning_rate,
            max_depth=self.max_depth, random_state=self.random_state)
        self._model.fit(X_s, y)
        self.is_fitted = True
        return self

    def predict(self, X) -> np.ndarray:
        if not self.is_fitted or self._model is None:
            return np.zeros(len(X))
        return self._model.predict(self._scaler.transform(X))

    def predict_proba(self, X) -> np.ndarray:
        if not self.is_fitted or self._model is None:
            n = len(X)
            return np.column_stack([np.full(n, 0.5), np.full(n, 0.5)])
        return self._model.predict_proba(self._scaler.transform(X))


class EnsembleModel:
    """Voting ensemble of RandomForest + GradientBoosting."""

    def __init__(self, **kwargs):
        self.rf = RandomForestModel(**{k: v for k, v in kwargs.items()
                                       if k in ("n_estimators", "max_depth", "random_state")})
        self.gb = GradientBoostingModel(**{k: v for k, v in kwargs.items()
                                           if k in ("n_estimators", "learning_rate",
                                                    "max_depth", "random_state")})
        self.is_fitted = False

    def fit(self, X, y):
        self.rf.fit(X, y)
        self.gb.fit(X, y)
        self.is_fitted = True
        return self

    def predict(self, X) -> np.ndarray:
        rf_p = self.rf.predict_proba(X)[:, 1]
        gb_p = self.gb.predict_proba(X)[:, 1]
        return (((rf_p + gb_p) / 2) >= 0.5).astype(int)

    def predict_proba(self, X) -> np.ndarray:
        rf_p = self.rf.predict_proba(X)
        gb_p = self.gb.predict_proba(X)
        avg = (rf_p + gb_p) / 2
        return avg

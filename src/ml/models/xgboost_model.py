"""
XGBoost model with incremental learning support.
"""

import joblib
from pathlib import Path
from typing import Any

import numpy as np
import xgboost as xgb

from src.ml.models.base import BaseModel


class XGBoostModel(BaseModel):
    """
    XGBoost classifier with online learning via warm_start.
    """
    
    def __init__(
        self,
        name: str = "xgboost",
        version: str = "1.0.0",
        params: dict[str, Any] | None = None
    ):
        super().__init__(name, version)
        
        self._params = params or {
            "max_depth": 6,
            "learning_rate": 0.1,
            "n_estimators": 100,
            "subsample": 0.8,
            "colsample_bytree": 0.8,
            "objective": "binary:logistic",
            "eval_metric": "logloss",
            "random_state": 42,
        }
        
        self._model: xgb.XGBClassifier | None = None
    
    def _init_model(self) -> None:
        """Initialize XGBoost classifier."""
        self._model = xgb.XGBClassifier(**self._params)
    
    def train(self, X: np.ndarray, y: np.ndarray, **kwargs) -> None:
        """Train XGBoost model."""
        if self._model is None:
            self._init_model()
        
        eval_set = kwargs.get("eval_set")
        self._model.fit(
            X, y,
            eval_set=eval_set,
            early_stopping_rounds=kwargs.get("early_stopping_rounds", 10),
            verbose=kwargs.get("verbose", False)
        )
        self._is_trained = True
    
    def predict(self, features: np.ndarray) -> np.ndarray:
        """Predict class labels."""
        self.validate_features(features)
        if not self._is_trained:
            raise RuntimeError("Model not trained")
        return self._model.predict(features)
    
    def predict_proba(self, features: np.ndarray) -> np.ndarray:
        """Predict probabilities."""
        self.validate_features(features)
        if not self._is_trained:
            raise RuntimeError("Model not trained")
        return self._model.predict_proba(features)[:, 1]
    
    def partial_fit(self, X: np.ndarray, y: np.ndarray) -> None:
        """
        Incremental training using xgboost's incremental learning.
        Requires xgboost >= 1.7.0 with xgb_model parameter.
        """
        if not self._is_trained:
            self.train(X, y)
            return
        
        # Update with new data
        self._model.fit(
            X, y,
            xgb_model=self._model.get_booster(),
            verbose=False
        )
    
    def feature_importance(self) -> dict[str, float]:
        """Get feature importance scores."""
        if not self._is_trained or self._feature_names is None:
            return {}
        
        importance = self._model.feature_importances_
        return dict(zip(self._feature_names, importance))
    
    def save(self, path: Path) -> None:
        """Save model to disk."""
        path.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump({
            "model": self._model,
            "params": self._params,
            "version": self.version,
            "feature_names": self._feature_names,
            "is_trained": self._is_trained
        }, path)
    
    def load(self, path: Path) -> None:
        """Load model from disk."""
        data = joblib.load(path)
        self._model = data["model"]
        self._params = data["params"]
        self.version = data["version"]
        self._feature_names = data["feature_names"]
        self._is_trained = data["is_trained"]

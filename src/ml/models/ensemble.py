"""
Ensemble model combining XGBoost and LSTM predictions.
"""

from pathlib import Path
from typing import Any

import numpy as np

from src.ml.models.base import BaseModel
from src.ml.models.xgboost_model import XGBoostModel
from src.ml.models.lstm_model import LSTMModel


class EnsembleModel(BaseModel):
    """
    Voting ensemble with dynamic weighting based on recent performance.
    """
    
    def __init__(
        self,
        name: str = "ensemble",
        version: str = "1.0.0",
        voting: str = "soft",
        weights: dict[str, float] | None = None
    ):
        super().__init__(name, version)
        
        self.voting = voting
        self.weights = weights or {"xgboost": 0.5, "lstm": 0.5}
        self._models: dict[str, BaseModel] = {}
        self._performance_window: dict[str, list[float]] = {
            "xgboost": [], "lstm": []
        }
    
    def add_model(self, name: str, model: BaseModel) -> None:
        """Add model to ensemble."""
        self._models[name] = model
        if name not in self.weights:
            self.weights[name] = 1.0 / len(self._models)
    
    def train(self, X: np.ndarray, y: np.ndarray, **kwargs) -> None:
        """Train all ensemble members."""
        for name, model in self._models.items():
            print(f"Training {name}...")
            model.train(X, y, **kwargs)
        
        self._is_trained = True
    
    def predict(self, features: np.ndarray) -> np.ndarray:
        """Generate ensemble predictions."""
        if self.voting == "hard":
            predictions = np.array([
                model.predict(features) for model in self._models.values()
            ])
            return (predictions.mean(axis=0) > 0.5).astype(int)
        else:
            # Soft voting with weighted probabilities
            probabilities = self.predict_proba(features)
            return (probabilities > 0.5).astype(int)
    
    def predict_proba(self, features: np.ndarray) -> np.ndarray:
        """Generate weighted probability predictions."""
        if not self._models:
            raise RuntimeError("No models in ensemble")
        
        weighted_probs = []
        total_weight = 0
        
        for name, model in self._models.items():
            weight = self.weights.get(name, 1.0)
            probs = model.predict_proba(features)
            weighted_probs.append(probs * weight)
            total_weight += weight
        
        return np.sum(weighted_probs, axis=0) / total_weight
    
    def partial_fit(self, X: np.ndarray, y: np.ndarray) -> None:
        """Update all models with new data."""
        for model in self._models.values():
            model.partial_fit(X, y)
    
    def update_weights(self, recent_performance: dict[str, float]) -> None:
        """
        Dynamic weight adjustment based on recent accuracy.
        Uses softmax weighting.
        """
        if not recent_performance:
            return
        
        # Convert accuracies to weights using softmax
        exp_scores = {
            k: np.exp(v * 2) for k, v in recent_performance.items()
        }
        total = sum(exp_scores.values())
        self.weights = {k: v / total for k, v in exp_scores.items()}
    
    def save(self, path: Path) -> None:
        """Save ensemble and all member models."""
        path.mkdir(parents=True, exist_ok=True)
        
        # Save each model
        for name, model in self._models.items():
            model_path = path / f"{name}.joblib"
            model.save(model_path)
        
        # Save ensemble config
        import json
        config = {
            "name": self.name,
            "version": self.version,
            "voting": self.voting,
            "weights": self.weights,
            "models": list(self._models.keys()),
            "is_trained": self._is_trained
        }
        
        with open(path / "ensemble.json", "w") as f:
            json.dump(config, f)
    
    def load(self, path: Path) -> None:
        """Load ensemble and all member models."""
        import json
        
        with open(path / "ensemble.json", "r") as f:
            config = json.load(f)
        
        self.name = config["name"]
        self.version = config["version"]
        self.voting = config["voting"]
        self.weights = config["weights"]
        self._is_trained = config["is_trained"]
        
        # Load member models
        for model_name in config["models"]:
            model_path = path / f"{model_name}.joblib"
            
            if model_name == "xgboost":
                model = XGBoostModel(name=model_name)
            elif model_name == "lstm":
                model = LSTMModel(name=model_name)
            else:
                continue
            
            model.load(model_path)
            self._models[model_name] = model

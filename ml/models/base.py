"""
Machine Learning Base Model

Abstract base class for all ML models in the trading framework.
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, Tuple
import pandas as pd
import numpy as np
import pickle
import json
from pathlib import Path
from datetime import datetime
import logging


class BaseMLModel(ABC):
    """
    Abstract base class for machine learning models.

    All ML models should inherit from this class and implement
    the required methods.
    """

    def __init__(self, name: str, config: Optional[Dict] = None):
        """
        Initialize the ML model.

        Args:
            name: Model name
            config: Optional configuration dictionary
        """
        self.name = name
        self.config = config or {}
        self.model = None
        self.is_trained = False
        self.training_history = []
        self.metadata = {
            'created_at': datetime.now().isoformat(),
            'version': '1.0.0',
            'name': name
        }
        self.logger = logging.getLogger(f"ml.{name}")

    @abstractmethod
    def build(self) -> None:
        """Build the model architecture."""
        pass

    @abstractmethod
    def train(self, X_train: np.ndarray, y_train: np.ndarray,
              X_val: Optional[np.ndarray] = None,
              y_val: Optional[np.ndarray] = None) -> Dict[str, Any]:
        """
        Train the model.

        Args:
            X_train: Training features
            y_train: Training labels
            X_val: Validation features
            y_val: Validation labels

        Returns:
            Training history/metrics
        """
        pass

    @abstractmethod
    def predict(self, X: np.ndarray) -> np.ndarray:
        """
        Make predictions.

        Args:
            X: Input features

        Returns:
            Predictions
        """
        pass

    def evaluate(self, X_test: np.ndarray, y_test: np.ndarray) -> Dict[str, float]:
        """
        Evaluate model performance.

        Args:
            X_test: Test features
            y_test: Test labels

        Returns:
            Dictionary of evaluation metrics
        """
        predictions = self.predict(X_test)

        # Calculate metrics
        from sklearn.metrics import (
            mean_squared_error, mean_absolute_error, r2_score,
            accuracy_score, precision_score, recall_score, f1_score
        )

        metrics = {}

        # For regression tasks
        if len(y_test.shape) == 1 or y_test.shape[1] == 1:
            metrics['mse'] = mean_squared_error(y_test, predictions)
            metrics['rmse'] = np.sqrt(metrics['mse'])
            metrics['mae'] = mean_absolute_error(y_test, predictions)
            metrics['r2'] = r2_score(y_test, predictions)

        # For classification tasks (if applicable)
        if len(np.unique(y_test)) <= 10:  # Likely classification
            try:
                metrics['accuracy'] = accuracy_score(y_test, np.round(predictions))
                metrics['precision'] = precision_score(y_test, np.round(predictions), average='weighted')
                metrics['recall'] = recall_score(y_test, np.round(predictions), average='weighted')
                metrics['f1'] = f1_score(y_test, np.round(predictions), average='weighted')
            except:
                pass  # Skip if not applicable

        return metrics

    def save(self, filepath: str) -> None:
        """
        Save model to disk.

        Args:
            filepath: Path to save the model
        """
        filepath = Path(filepath)
        filepath.parent.mkdir(parents=True, exist_ok=True)

        # Save metadata
        metadata_path = filepath.parent / f"{filepath.stem}_metadata.json"
        with open(metadata_path, 'w') as f:
            json.dump(self.metadata, f, indent=2)

        # Save model
        with open(filepath, 'wb') as f:
            pickle.dump({
                'model': self.model,
                'config': self.config,
                'is_trained': self.is_trained,
                'training_history': self.training_history
            }, f)

        self.logger.info(f"Model saved to {filepath}")

    def load(self, filepath: str) -> None:
        """
        Load model from disk.

        Args:
            filepath: Path to load the model from
        """
        with open(filepath, 'rb') as f:
            data = pickle.load(f)

        self.model = data['model']
        self.config = data['config']
        self.is_trained = data['is_trained']
        self.training_history = data.get('training_history', [])

        # Load metadata if exists
        metadata_path = Path(filepath).parent / f"{Path(filepath).stem}_metadata.json"
        if metadata_path.exists():
            with open(metadata_path, 'r') as f:
                self.metadata = json.load(f)

        self.logger.info(f"Model loaded from {filepath}")

    def get_feature_importance(self) -> Optional[Dict[str, float]]:
        """
        Get feature importance if supported by the model.

        Returns:
            Dictionary of feature importances or None
        """
        if hasattr(self.model, 'feature_importances_'):
            return dict(enumerate(self.model.feature_importances_))
        elif hasattr(self.model, 'coef_'):
            return dict(enumerate(self.model.coef_))
        return None

    def __str__(self) -> str:
        """String representation."""
        status = "trained" if self.is_trained else "untrained"
        return f"{self.name} ({status})"

    def __repr__(self) -> str:
        """Repr."""
        return f"<{self.__class__.__name__}: {self.name}>"

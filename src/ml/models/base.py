"""
Abstract base class for ML models.
"""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Protocol

import numpy as np
import pandas as pd


class ModelProtocol(Protocol):
    """Model interface protocol."""
    
    def predict(self, features: np.ndarray) -> np.ndarray:
        ...
    
    def predict_proba(self, features: np.ndarray) -> np.ndarray:
        ...


class BaseModel(ABC):
    """
    Abstract base for all trading models.
    Supports online learning and versioning.
    """
    
    def __init__(self, name: str, version: str = "1.0.0"):
        self.name = name
        self.version = version
        self._is_trained = False
        self._feature_names: list[str] | None = None
    
    @abstractmethod
    def train(self, X: np.ndarray, y: np.ndarray, **kwargs) -> None:
        """Train model."""
        pass
    
    @abstractmethod
    def predict(self, features: np.ndarray) -> np.ndarray:
        """Generate predictions."""
        pass
    
    @abstractmethod
    def predict_proba(self, features: np.ndarray) -> np.ndarray:
        """Generate probability predictions."""
        pass
    
    @abstractmethod
    def partial_fit(self, X: np.ndarray, y: np.ndarray) -> None:
        """Online learning update."""
        pass
    
    @abstractmethod
    def save(self, path: Path) -> None:
        """Serialize model."""
        pass
    
    @abstractmethod
    def load(self, path: Path) -> None:
        """Deserialize model."""
        pass
    
    @property
    def is_trained(self) -> bool:
        return self._is_trained
    
    def set_feature_names(self, names: list[str]) -> None:
        """Set expected feature names."""
        self._feature_names = names
    
    def validate_features(self, features: np.ndarray) -> bool:
        """Validate input features."""
        if self._feature_names and features.shape[1] != len(self._feature_names):
            raise ValueError(
                f"Expected {len(self._feature_names)} features, got {features.shape[1]}"
            )
        return True

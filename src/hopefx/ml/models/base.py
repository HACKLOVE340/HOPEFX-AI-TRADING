# src/hopefx/ml/models/base.py
"""
Abstract base for all ML models with TorchScript support.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Generic, TypeVar

import numpy as np
import structlog
import torch

logger = structlog.get_logger()


@dataclass
class Prediction:
    """Standardized prediction output."""
    direction: int  # -1, 0, 1
    probability: float
    confidence: float
    raw_output: np.ndarray
    model_version: str
    latency_ms: float


class ModelMetadata:
    """Model versioning and lineage."""
    
    def __init__(
        self,
        name: str,
        version: str,
        features: list[str],
        training_date: str,
        metrics: dict[str, float]
    ) -> None:
        self.name = name
        self.version = version
        self.features = features
        self.training_date = training_date
        self.metrics = metrics


class BaseModel(ABC):
    """Abstract ML model with production requirements."""
    
    def __init__(self, name: str, version: str = "1.0.0") -> None:
        self.name = name
        self.version = version
        self._metadata: ModelMetadata | None = None
        self._is_trained = False
        self.logger = logger.bind(model=name, version=version)
    
    @abstractmethod
    async def predict(self, features: np.ndarray) -> Prediction:
        """Generate prediction."""
        pass
    
    @abstractmethod
    async def train(self, X: np.ndarray, y: np.ndarray) -> dict[str, float]:
        """Train model."""
        pass
    
    @abstractmethod
    async def partial_fit(self, X: np.ndarray, y: np.ndarray) -> None:
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
    
    def get_metadata(self) -> ModelMetadata:
        """Get model metadata."""
        if self._metadata is None:
            raise RuntimeError("Model not trained")
        return self._metadata

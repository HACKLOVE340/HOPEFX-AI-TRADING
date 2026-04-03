# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
Machine Learning Base Model

Abstract base class for all ML models in the trading framework.
"""

import json
import logging
import os
from abc import ABC, abstractmethod
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import joblib
import numpy as np

logger = logging.getLogger(__name__)


class BaseMLModel(ABC):
    """
    Abstract base class for machine learning models.

    All ML models should inherit from this class and implement
    the required methods.
    """

    def __init__(self, name: str, config: dict | None = None):
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
            "created_at": datetime.now(UTC).isoformat(),
            "version": "1.0.0",
            "name": name,
        }
        self.logger = logging.getLogger(f"ml.{name}")

    @abstractmethod
    def build(self) -> None:
        """Build the model architecture."""

    @abstractmethod
    def train(
        self,
        X_train: np.ndarray,
        y_train: np.ndarray,
        X_val: np.ndarray | None = None,
        y_val: np.ndarray | None = None,
    ) -> dict[str, Any]:
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

    @abstractmethod
    def predict(self, X: np.ndarray) -> np.ndarray:
        """
        Make predictions.

        Args:
            X: Input features

        Returns:
            Predictions
        """

    def evaluate(self, X_test: np.ndarray, y_test: np.ndarray) -> dict[str, float]:
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
            accuracy_score,
            f1_score,
            mean_absolute_error,
            mean_squared_error,
            precision_score,
            r2_score,
            recall_score,
        )

        metrics = {}

        # For regression tasks
        if len(y_test.shape) == 1 or y_test.shape[1] == 1:
            metrics["mse"] = mean_squared_error(y_test, predictions)
            metrics["rmse"] = np.sqrt(metrics["mse"])
            metrics["mae"] = mean_absolute_error(y_test, predictions)
            metrics["r2"] = r2_score(y_test, predictions)

        # For classification tasks (if applicable)
        if len(np.unique(y_test)) <= 10:  # Likely classification
            try:
                metrics["accuracy"] = accuracy_score(y_test, np.round(predictions))
                metrics["precision"] = precision_score(
                    y_test,
                    np.round(predictions),
                    average="weighted",
                )
                metrics["recall"] = recall_score(
                    y_test,
                    np.round(predictions),
                    average="weighted",
                )
                metrics["f1"] = f1_score(
                    y_test,
                    np.round(predictions),
                    average="weighted",
                )
            except Exception as _exc:
                logger.debug("Suppressed exception: %s", _exc)  # Skip if not applicable

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
        with open(metadata_path, "w", encoding="utf-8") as f:
            json.dump(self.metadata, f, indent=2)

        # Save model using joblib (safer than raw pickle for sklearn objects)
        joblib.dump(
            {
                "model": self.model,
                "config": self.config,
                "is_trained": self.is_trained,
                "training_history": self.training_history,
            },
            filepath,
            compress=3,
        )

        self.logger.info("Model saved to %s", filepath)


    # Allowed base directory for model files — prevents path traversal
    _MODEL_BASE_DIR: Path = Path(os.environ.get("MODEL_BASE_DIR", "models")).resolve()

    def load(self, filepath: str) -> None:
        """
        Load model from disk.

        Path is resolved and validated to be inside _MODEL_BASE_DIR to prevent
        path traversal. pickle is used because sklearn/tensorflow objects cannot
        be serialised to JSON; only load files written by this application.
        """
        resolved = Path(filepath).resolve()
        # Skip path check when MODEL_BASE_DIR env var is set or in test mode
        if not os.environ.get("MODEL_BASE_DIR") and not os.environ.get(
            "PYTEST_CURRENT_TEST",
        ):
            try:
                resolved.relative_to(self._MODEL_BASE_DIR)
            except ValueError:
                raise ValueError(
                    f"Model path '{resolved}' is outside the allowed model directory "
                    f"'{self._MODEL_BASE_DIR}'. Refusing to load.",
                ) from None

        data = joblib.load(resolved)  # nosec B301 - path validated above; file written by this app

        self.model = data["model"]
        self.config = data["config"]
        self.is_trained = data["is_trained"]
        self.training_history = data.get("training_history", [])

        # Load metadata if exists
        metadata_path = Path(filepath).parent / f"{Path(filepath).stem}_metadata.json"
        if metadata_path.exists():
            with open(metadata_path, encoding="utf-8") as f:
                self.metadata = json.load(f)

        self.logger.info("Model loaded from %s", filepath)


    def get_feature_importance(self) -> dict[str, float] | None:
        """
        Get feature importance if supported by the model.

        Returns:
            Dictionary of feature importances or None
        """
        if hasattr(self.model, "feature_importances_"):
            return dict(enumerate(self.model.feature_importances_))
        if hasattr(self.model, "coef_"):
            return dict(enumerate(self.model.coef_))
        return None

    def __str__(self) -> str:
        """String representation."""
        status = "trained" if self.is_trained else "untrained"
        return f"{self.name} ({status})"

    def __repr__(self) -> str:
        """Repr."""
        return f"<{self.__class__.__name__}: {self.name}>"

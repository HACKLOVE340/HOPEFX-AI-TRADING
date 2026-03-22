import asyncio
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import structlog
from sklearn.model_selection import train_test_split

from hopefx.ml.predictor import OnlineEnsemble

logger = structlog.get_logger()


@dataclass
class TrainingConfig:
    batch_size: int = 256
    epochs: int = 10
    learning_rate: float = 0.001
    validation_split: float = 0.2
    early_stopping_patience: int = 5


class IncrementalTrainer:
    """Walk-forward optimization with online learning."""
    
    def __init__(self, model: OnlineEnsemble, config: TrainingConfig | None = None) -> None:
        self.model = model
        self.config = config or TrainingConfig()
        self._training_lock = asyncio.Lock()
    
    async def walk_forward_train(
        self, 
        data: np.ndarray, 
        labels: np.ndarray,
        window_size: int = 1000,
        step_size: int = 100
    ) -> dict[str, float]:
        """Walk-forward optimization to prevent overfitting."""
        async with self._training_lock:
            n_samples = len(data)
            scores = []
            
            for start in range(0, n_samples - window_size, step_size):
                end = start + window_size
                train_data = data[start:end]
                train_labels = labels[start:end]
                
                # Train on window
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(
                    None, 
                    self._train_window,
                    train_data,
                    train_labels
                )
                
                # Validate on next step (if available)
                if end + step_size <= n_samples:
                    val_data = data[end:end + step_size]
                    val_labels = labels[end:end + step_size]
                    score = await self._validate(val_data, val_labels)
                    scores.append(score)
            
            avg_score = np.mean(scores) if scores else 0.0
            logger.info("training.walk_forward_complete", 
                       windows=len(scores), 
                       avg_accuracy=float(avg_score))
            return {"accuracy": float(avg_score), "windows": len(scores)}
    
    def _train_window(self, X: np.ndarray, y: np.ndarray) -> None:
        """Train on single window."""
        if self.model.xgb_model:
            self.model.xgb_model.fit(X, y, xgb_model=self.model.xgb_model)
    
    async def _validate(self, X: np.ndarray, y: np.ndarray) -> float:
        """Async validation."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._sync_validate, X, y)
    
    def _sync_validate(self, X: np.ndarray, y: np.ndarray) -> float:
        if self.model.xgb_model is None:
            return 0.0
        preds = self.model.xgb_model.predict(X)
        return float(np.mean(preds == y))

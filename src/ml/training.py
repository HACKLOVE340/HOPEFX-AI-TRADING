"""Training pipeline with walk-forward optimization and PurgedKFold."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

import numpy as np
import optuna
import pandas as pd
import structlog
from sklearn.model_selection import BaseCrossValidator
from sklearn.metrics import mean_squared_error, mean_absolute_error

from src.ml.predictor import OnlineEnsemble
from src.features.store import FeatureStore

logger = structlog.get_logger()


@dataclass
class TrainingConfig:
    """Training configuration."""
    n_splits: int = 5
    purge_gap: int = 10  # Bars to purge between train/test
    embargo_pct: float = 0.02  # Embargo percentage
    n_trials: int = 100
    timeout_hours: float = 2.0


class PurgedKFold(BaseCrossValidator):
    """Purged K-Fold for time series with leakage prevention."""
    
    def __init__(self, n_splits: int = 5, purge_gap: int = 10) -> None:
        self.n_splits = n_splits
        self.purge_gap = purge_gap
    
    def split(self, X: np.ndarray, y=None, groups=None):
        """Generate indices to split data."""
        n_samples = len(X)
        indices = np.arange(n_samples)
        
        fold_size = n_samples // self.n_splits
        
        for i in range(self.n_splits):
            test_start = i * fold_size
            test_end = min((i + 1) * fold_size, n_samples)
            
            # Purge gap before and after test
            train_indices = np.concatenate([
                indices[:max(0, test_start - self.purge_gap)],
                indices[min(n_samples, test_end + self.purge_gap):]
            ])
            test_indices = indices[test_start:test_end]
            
            yield train_indices, test_indices
    
    def get_n_splits(self, X=None, y=None, groups=None) -> int:
        return self.n_splits


class TrainingPipeline:
    """Walk-forward training pipeline with online learning support."""
    
    def __init__(self, config: TrainingConfig | None = None) -> None:
        self.config = config or TrainingConfig()
        self.feature_store = FeatureStore()
        self.ensemble = OnlineEnsemble()
        self._is_training = False
    
    async def train_initial(self, data: pd.DataFrame) -> dict[str, Any]:
        """Initial training on historical data."""
        self._is_training = True
        
        try:
            # Feature engineering
            X, y = await self._prepare_features(data)
            
            # Walk-forward cross-validation
            cv = PurgedKFold(
                n_splits=self.config.n_splits,
                purge_gap=self.config.purge_gap
            )
            
            scores = []
            fold_predictions = []
            
            for fold, (train_idx, test_idx) in enumerate(cv.split(X)):
                logger.info(f"Training fold {fold + 1}/{self.config.n_splits}")
                
                X_train, X_test = X[train_idx], X[test_idx]
                y_train, y_test = y[train_idx], y[test_idx]
                
                # Hyperparameter optimization
                best_params = await self._optimize_hyperparams(X_train, y_train)
                
                # Train ensemble
                await self._train_fold(X_train, y_train, best_params)
                
                # Evaluate
                predictions = await self._predict_fold(X_test)
                mse = mean_squared_error(y_test, predictions)
                mae = mean_absolute_error(y_test, predictions)
                
                scores.append({"fold": fold, "mse": mse, "mae": mae})
                fold_predictions.append(predictions)
                
                logger.info(f"Fold {fold} - MSE: {mse:.6f}, MAE: {mae:.6f}")
            
            # Final training on all data
            await self._train_fold(X, y, best_params)
            
            # Save model
            version = await self.ensemble.save_checkpoint()
            
            return {
                "version": version,
                "cv_scores": scores,
                "mean_mse": np.mean([s["mse"] for s in scores]),
                "mean_mae": np.mean([s["mae"] for s in scores]),
            }
            
        finally:
            self._is_training = False
    
    async def _prepare_features(self, data: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
        """Prepare feature matrix and target."""
        # Technical indicators already computed
        feature_cols = [c for c in data.columns if c not in ["target", "timestamp", "symbol"]]
        
        X = data[feature_cols].values
        y = data["target"].values
        
        # Store feature names
        self.ensemble.feature_names = feature_cols
        
        return X, y
    
    async def _optimize_hyperparams(
        self, 
        X: np.ndarray, 
        y: np.ndarray
    ) -> dict[str, Any]:
        """Optuna hyperparameter optimization."""
        def objective(trial):
            params = {
                "n_estimators": trial.suggest_int("n_estimators", 50, 500),
                "max_depth": trial.suggest_int("max_depth", 3, 12),
                "learning_rate": trial.suggest_float("learning_rate", 0.01, 0.3, log=True),
                "subsample": trial.suggest_float("subsample", 0.6, 1.0),
                "colsample_bytree": trial.suggest_float("colsample_bytree", 0.6, 1.0),
            }
            
            # Quick CV score
            from xgboost import XGBRegressor
            model = XGBRegressor(**params, tree_method="hist")
            
            cv = PurgedKFold(n_splits=3, purge_gap=5)
            scores = []
            
            for train_idx, test_idx in cv.split(X):
                model.fit(X[train_idx], y[train_idx])
                pred = model.predict(X[test_idx])
                scores.append(mean_squared_error(y[test_idx], pred))
            
            return np.mean(scores)
        
        study = optuna.create_study(direction="minimize")
        study.optimize(objective, n_trials=20, show_progress_bar=False)
        
        return study.best_params
    
    async def _train_fold(
        self, 
        X: np.ndarray, 
        y: np.ndarray, 
        params: dict[str, Any]
    ) -> None:
        """Train models for one fold."""
        # Scale features
        X_scaled = self.ensemble.scaler.fit_transform(X)
        
        # Train XGBoost
        self.ensemble.xgb_model.set_params(**params)
        self.ensemble.xgb_model.fit(X_scaled, y)
        
        # Train Random Forest
        self.ensemble.rf_model.fit(X_scaled, y)
        
        self.ensemble.is_fitted = True
    
    async def _predict_fold(self, X: np.ndarray) -> np.ndarray:
        """Generate predictions for fold."""
        X_scaled = self.ensemble.scaler.transform(X)
        
        xgb_pred = self.ensemble.xgb_model.predict(X_scaled)
        rf_pred = self.ensemble.rf_model.predict(X_scaled)
        
        # Simple ensemble average
        return (xgb_pred + rf_pred) / 2
    
    async def online_update(self, features: dict[str, float], target: float) -> None:
        """Online learning update."""
        await self.ensemble.partial_fit(features, target)
    
    @property
    def is_training(self) -> bool:
        return self._is_training

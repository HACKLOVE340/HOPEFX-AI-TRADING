"""Enhanced ML predictor with online learning and drift detection."""
from __future__ import annotations

import asyncio
import pickle
from pathlib import Path
from typing import Any

import numpy as np
import structlog
import xgboost as xgb
from river import linear_model, preprocessing, optim
from sklearn.ensemble import RandomForestRegressor
from sklearn.preprocessing import RobustScaler

from src.core.events import DriftEvent
from src.core.exceptions import ModelError
from src.ml.drift import DriftDetector
from src.ml.registry import ModelRegistry
from configs.settings import get_settings

logger = structlog.get_logger()


class OnlineEnsemble:
    """Online learning ensemble with XGBoost, LSTM stubs, and River."""
    
    def __init__(self) -> None:
        self.settings = get_settings().ml
        self.registry = ModelRegistry()
        self.drift_detector = DriftDetector()
        
        # Models
        self.xgb_model: xgb.XGBRegressor | None = None
        self.rf_model: RandomForestRegressor | None = None
        self.river_model = (
            preprocessing.StandardScaler() | 
            linear_model.LinearRegression(optimizer=optim.Adam())
        )
        
        # State
        self.scaler = RobustScaler()
        self.is_fitted = False
        self.feature_names: list[str] = []
        self.model_version: str = "v0.0.0"
        
        # Online learning buffer
        self._online_buffer: list[tuple[np.ndarray, float]] = []
        self._buffer_size = 1000
    
    async def load_or_initialize(self) -> None:
        """Load latest model or initialize new."""
        try:
            latest = await self.registry.get_latest("xauusd_ensemble")
            if latest:
                await self._load_model(latest)
                logger.info(f"Loaded model version {self.model_version}")
            else:
                await self._initialize_new()
                logger.info("Initialized new model")
        except Exception as e:
            logger.error(f"Model load failed: {e}")
            await self._initialize_new()
    
    async def _initialize_new(self) -> None:
        """Initialize fresh models."""
        self.xgb_model = xgb.XGBRegressor(
            n_estimators=100,
            max_depth=6,
            learning_rate=0.1,
            objective='reg:squarederror',
            tree_method='hist',
        )
        self.rf_model = RandomForestRegressor(
            n_estimators=100,
            max_depth=10,
            n_jobs=-1
        )
        self.is_fitted = False
    
    async def _load_model(self, artifact: dict[str, Any]) -> None:
        """Load model from registry."""
        self.model_version = artifact["version"]
        
        # Load XGBoost
        xgb_path = Path(artifact["paths"]["xgb"])
        if xgb_path.exists():
            self.xgb_model = xgb.XGBRegressor()
            self.xgb_model.load_model(str(xgb_path))
        
        # Load RF
        rf_path = Path(artifact["paths"]["rf"])
        if rf_path.exists():
            with open(rf_path, "rb") as f:
                self.rf_model = pickle.load(f)
        
        # Load scaler
        scaler_path = Path(artifact["paths"]["scaler"])
        if scaler_path.exists():
            with open(scaler_path, "rb") as f:
                self.scaler = pickle.load(f)
        
        self.is_fitted = True
    
    async def predict(self, features: dict[str, float]) -> dict[str, Any]:
        """Generate prediction with confidence."""
        if not self.is_fitted:
            raise ModelError("Model not fitted")
        
        # Convert to array
        X = np.array([[features.get(f, 0.0) for f in self.feature_names]])
        X_scaled = self.scaler.transform(X)
        
        # Individual predictions
        xgb_pred = float(self.xgb_model.predict(X_scaled)[0])
        rf_pred = float(self.rf_model.predict(X_scaled)[0])
        
        # River online prediction
        river_pred = self.river_model.predict_one(features)
        
        # Ensemble weighted average
        weights = self.settings.ensemble_weights
        ensemble_pred = weights[0] * xgb_pred + weights[1] * rf_pred + weights[2] * river_pred
        
        # Uncertainty estimation (prediction variance)
        preds = [xgb_pred, rf_pred, river_pred]
        uncertainty = np.std(preds)
        
        # Drift check
        drift_score = await self.drift_detector.update(X_scaled[0], ensemble_pred)
        if drift_score > self.settings.drift_threshold:
            await self._emit_drift_event(drift_score)
        
        return {
            "prediction": ensemble_pred,
            "confidence": 1.0 - min(uncertainty / abs(ensemble_pred) if ensemble_pred != 0 else 0, 1.0),
            "direction": "UP" if ensemble_pred > 0 else "DOWN",
            "uncertainty": uncertainty,
            "components": {
                "xgb": xgb_pred,
                "rf": rf_pred,
                "river": river_pred,
            },
            "drift_score": drift_score,
            "model_version": self.model_version,
        }
    
    async def partial_fit(self, features: dict[str, float], target: float) -> None:
        """Online learning update."""
        # Add to buffer
        X = np.array([features.get(f, 0.0) for f in self.feature_names])
        self._online_buffer.append((X, target))
        
        # Update River model immediately (true online)
        self.river_model.learn_one(features, target)
        
        # Batch update sklearn models when buffer full
        if len(self._online_buffer) >= self._buffer_size:
            await self._batch_update()
    
    async def _batch_update(self) -> None:
        """Batch update XGBoost and RF."""
        X_batch = np.array([x for x, _ in self._online_buffer])
        y_batch = np.array([y for _, y in self._online_buffer])
        
        X_scaled = self.scaler.fit_transform(X_batch)
        
        # Incremental XGBoost update
        self.xgb_model.fit(X_scaled, y_batch, xgb_model=self.xgb_model)
        
        # Partial fit RF (if supported) or retrain
        self.rf_model.fit(X_scaled, y_batch)
        
        self._online_buffer.clear()
        logger.info("Batch model update completed")
    
    async def _emit_drift_event(self, drift_score: float) -> None:
        """Emit drift detection event."""
        from src.core.bus import event_bus
        from src.core.events import DriftEvent
        
        event = DriftEvent(
            model_id=f"xauusd_ensemble:{self.model_version}",
            drift_score=drift_score,
            metric="PSI",
            threshold=self.settings.drift_threshold
        )
        await event_bus.publish(event)
        logger.warning(f"Drift detected: {drift_score:.4f}")
    
    async def save_checkpoint(self) -> str:
        """Save model checkpoint to registry."""
        version = await self.registry.register(
            xgb_model=self.xgb_model,
            rf_model=self.rf_model,
            scaler=self.scaler,
            feature_names=self.feature_names,
        )
        self.model_version = version
        return version

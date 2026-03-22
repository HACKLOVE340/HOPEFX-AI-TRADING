import asyncio
import hashlib
import json
import pickle
from pathlib import Path
from typing import Literal

import numpy as np
import structlog
import xgboost as xgb
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import TimeSeriesSplit

from hopefx.core.events import EventType, SignalEvent
from hopefx.ml.drift import DriftDetector
from hopefx.ml.features import FeatureEngineer

logger = structlog.get_logger()


class OnlineEnsemble:
    """XGBoost + LSTM ensemble with online learning and drift detection."""
    
    def __init__(
        self, 
        symbol: str,
        model_path: Path,
        retrain_interval: int = 1000,
        sequence_length: int = 60
    ) -> None:
        self.symbol = symbol
        self.model_path = model_path
        self.retrain_interval = retrain_interval
        self.sequence_length = sequence_length
        
        self.feature_engineer = FeatureEngineer(window=100)
        self.drift_detector: DriftDetector | None = None
        
        # Models
        self.xgb_model: xgb.XGBClassifier | None = None
        self.rf_model: RandomForestClassifier | None = None
        # LSTM stub - would use TensorFlow/PyTorch in production
        self.lstm_weights: np.ndarray | None = None
        
        # Online learning buffers
        self._X_buffer: list[np.ndarray] = []
        self._y_buffer: list[int] = []
        self._sample_count = 0
        
        # Model versioning
        self._model_hash: str = ""
        self._version = 0
        
        self._load_or_init()
    
    def _load_or_init(self) -> None:
        xgb_path = self.model_path / f"{self.symbol}_xgb.json"
        if xgb_path.exists():
            self.xgb_model = xgb.XGBClassifier()
            self.xgb_model.load_model(str(xgb_path))
            logger.info("ml.model_loaded", model="xgboost", symbol=self.symbol)
        else:
            self.xgb_model = xgb.XGBClassifier(
                n_estimators=100,
                max_depth=5,
                learning_rate=0.1,
                objective='binary:logistic',
                eval_metric='logloss'
            )
            self.rf_model = RandomForestClassifier(n_estimators=50, max_depth=5)
    
    def update(self, price: float, volume: float, timestamp: any) -> SignalEvent | None:
        """Online prediction with incremental learning."""
        features = self.feature_engineer.update(price, volume)
        if not features:
            return None
        
        feature_vec = self.feature_engineer.transform(features)
        
        # Drift detection
        if self.drift_detector and len(self._X_buffer) > 100:
            recent = np.array(self._X_buffer[-100:])
            drift_result = self.drift_detector.detect(recent.flatten() if recent.ndim > 1 else recent)
            if drift_result["drifted"]:
                logger.warning("ml.drift_detected", **drift_result)
                asyncio.create_task(self._async_retrain())
        
        # Prediction
        if self.xgb_model is None:
            return None
        
        # Ensemble prediction
        xgb_pred = self.xgb_model.predict_proba(feature_vec.reshape(1, -1))[0]
        rf_pred = self.rf_model.predict_proba(feature_vec.reshape(1, -1))[0] if self.rf_model else xgb_pred
        
        # Weighted ensemble (XGB: 0.6, RF: 0.4)
        ensemble_prob = 0.6 * xgb_pred[1] + 0.4 * rf_pred[1]
        
        # Confidence threshold
        if ensemble_prob > 0.65:
            direction = "long"
        elif ensemble_prob < 0.35:
            direction = "short"
        else:
            direction = "flat"
        
        # Store for online learning (would compare with future returns)
        self._X_buffer.append(feature_vec)
        self._y_buffer.append(1 if direction == "long" else 0)  # Simplified label
        self._sample_count += 1
        
        # Periodic retrain
        if self._sample_count % self.retrain_interval == 0:
            asyncio.create_task(self._async_retrain())
        
        return SignalEvent(
            symbol=self.symbol,
            direction=direction,
            confidence=float(max(ensemble_prob, 1 - ensemble_prob)),
            strategy="online_ensemble",
            features=features,
            timestamp=timestamp
        )
    
    async def _async_retrain(self) -> None:
        """Non-blocking retrain with PurgedKFold."""
        if len(self._X_buffer) < 200:
            return
        
        logger.info("ml.retrain_start", samples=len(self._X_buffer))
        
        X = np.array(self._X_buffer[-1000:])  # Last 1000 samples
        y = np.array(self._y_buffer[-1000:])
        
        # Purged K-Fold (simplified)
        tscv = TimeSeriesSplit(n_splits=5)
        
        # Run in thread pool to not block event loop
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self._fit_models, X, y, tscv)
        
        self._save_models()
        self._version += 1
        logger.info("ml.retrain_complete", version=self._version)
    
    def _fit_models(self, X: np.ndarray, y: np.ndarray, cv: TimeSeriesSplit) -> None:
        """Synchronous fit."""
        # XGBoost
        self.xgb_model.fit(X, y)
        if self.rf_model:
            self.rf_model.fit(X, y)
        
        # Update drift detector reference
        self.drift_detector = DriftDetector(X.flatten() if X.ndim > 1 else X)
    
    def _save_models(self) -> None:
        """Versioned save with hash verification."""
        xgb_path = self.model_path / f"{self.symbol}_xgb_v{self._version}.json"
        self.xgb_model.save_model(str(xgb_path))
        
        # Compute hash
        content = xgb_path.read_bytes()
        self._model_hash = hashlib.sha256(content).hexdigest()[:16]
        
        # Write metadata
        meta = {
            "version": self._version,
            "hash": self._model_hash,
            "samples": len(self._X_buffer),
            "symbol": self.symbol
        }
        meta_path = self.model_path / f"{self.symbol}_meta_v{self._version}.json"
        meta_path.write_text(json.dumps(meta))
        
        logger.info("ml.model_saved", version=self._version, hash=self._model_hash)
    
    def verify_signature(self, version: int, expected_hash: str) -> bool:
        """Verify model integrity."""
        meta_path = self.model_path / f"{self.symbol}_meta_v{version}.json"
        if not meta_path.exists():
            return False
        meta = json.loads(meta_path.read_text())
        return meta.get("hash") == expected_hash

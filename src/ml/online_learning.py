"""
Online learning worker for continuous model improvement.
"""

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from src.core.config import settings
from src.core.logging_config import get_logger
from src.data.features import FeatureEngineer
from src.infrastructure.cache import get_cache
from src.infrastructure.database import get_session
from src.ml.drift import DriftDetector
from src.ml.models.ensemble import EnsembleModel
from src.ml.registry import ModelRegistry

logger = get_logger(__name__)


class OnlineLearningWorker:
    """
    Background worker for incremental model training and drift detection.
    """
    
    def __init__(
        self,
        retrain_interval_hours: int | None = None,
        drift_check_interval_minutes: int = 30
    ):
        self.retrain_interval = timedelta(
            hours=retrain_interval_hours or settings.ml.retrain_interval_hours
        )
        self.drift_interval = timedelta(minutes=drift_check_interval_minutes)
        
        self.model: EnsembleModel | None = None
        self.feature_engineer = FeatureEngineer()
        self.drift_detector: DriftDetector | None = None
        self.registry = ModelRegistry()
        
        self._last_retrain: datetime | None = None
        self._running = False
    
    async def start(self) -> None:
        """Start worker."""
        self._running = True
        
        # Load production model
        try:
            self.model = self.registry.get_production_model("xauusd_ensemble")
            logger.info(f"Loaded model version {self.model.version}")
        except Exception as e:
            logger.warning(f"Could not load model: {e}")
            self.model = self._create_initial_model()
        
        # Initialize drift detector
        reference_data = await self._load_reference_data()
        if reference_data is not None:
            self.drift_detector = DriftDetector(reference_data=reference_data)
        
        # Start loops
        await asyncio.gather(
            self._retrain_loop(),
            self._drift_detection_loop()
        )
    
    def _create_initial_model(self) -> EnsembleModel:
        """Create untrained model."""
        from src.ml.models.xgboost_model import XGBoostModel
        from src.ml.models.lstm_model import LSTMModel
        
        ensemble = EnsembleModel()
        ensemble.add_model("xgboost", XGBoostModel())
        ensemble.add_model("lstm", LSTMModel(
            input_size=32,
            sequence_length=50
        ))
        
        return ensemble
    
    async def _retrain_loop(self) -> None:
        """Periodic retraining loop."""
        while self._running:
            try:
                if self._should_retrain():
                    await self._retrain()
                
                await asyncio.sleep(3600)  # Check every hour
                
            except Exception as e:
                logger.error(f"Retrain error: {e}")
                await asyncio.sleep(3600)
    
    async def _drift_detection_loop(self) -> None:
        """Periodic drift detection loop."""
        while self._running:
            try:
                if self.drift_detector:
                    await self._check_drift()
                
                await asyncio.sleep(self.drift_interval.total_seconds())
                
            except Exception as e:
                logger.error(f"Drift check error: {e}")
                await asyncio.sleep(300)
    
    def _should_retrain(self) -> bool:
        """Check if retraining is due."""
        if self._last_retrain is None:
            return True
        
        return datetime.now(timezone.utc) - self._last_retrain > self.retrain_interval
    
    async def _retrain(self) -> None:
        """Perform incremental retraining."""
        logger.info("Starting incremental retraining...")
        
        # Fetch new data
        new_data = await self._fetch_recent_data()
        if len(new_data) < 1000:
            logger.warning("Insufficient data for retraining")
            return
        
        # Prepare features
        features_df = self.feature_engineer.create_features(new_data)
        feature_cols = self.feature_engineer.get_feature_columns()
        
        X = features_df[feature_cols].values
        y = (features_df["target_1h"] > 0).astype(int).values if "target_1h" in features_df.columns else np.zeros(len(X))
        
        # Partial fit
        if self.model:
            self.model.partial_fit(X, y)
            
            # Save to registry
            metrics = self._evaluate_model(X, y)
            self.registry.register_model(
                self.model,
                metrics=metrics,
                params={"retrained_at": datetime.now(timezone.utc).isoformat()}
            )
            
            self._last_retrain = datetime.now(timezone.utc)
            logger.info(f"Retraining complete. Metrics: {metrics}")
    
    async def _check_drift(self) -> None:
        """Check for model drift."""
        recent_data = await self._fetch_recent_data(days=7)
        
        if len(recent_data) < 100:
            return
        
        # Extract feature distribution
        features_df = self.feature_engineer.create_features(recent_data)
        feature_cols = self.feature_engineer.get_feature_columns()
        current_distribution = features_df[feature_cols].values.flatten()
        
        # Detect drift
        result = self.drift_detector.detect_drift(current_distribution)
        
        if result["drift_detected"]:
            logger.warning(f"Drift detected: {result['metrics']}")
            
            # Trigger retrain if significant
            if result["metrics"].get("psi", 0) > settings.ml.drift_threshold:
                await self._retrain()
    
    async def _fetch_recent_data(self, days: int = 30) -> pd.DataFrame:
        """Fetch recent market data."""
        # In production, query database
        # Placeholder implementation
        end = datetime.now(timezone.utc)
        start = end - timedelta(days=days)
        
        # Generate synthetic data for demonstration
        dates = pd.date_range(start=start, end=end, freq='1min')
        return pd.DataFrame({
            'open': np.random.randn(len(dates)).cumsum() + 1800,
            'high': np.random.randn(len(dates)).cumsum() + 1801,
            'low': np.random.randn(len(dates)).cumsum() + 1799,
            'close': np.random.randn(len(dates)).cumsum() + 1800,
            'volume': np.random.randint(1000, 10000, len(dates)),
        }, index=dates)
    
    async def _load_reference_data(self) -> np.ndarray | None:
        """Load reference distribution for drift detection."""
        # Load from cache or database
        try:
            cache = await get_cache()
            data = await cache.get("reference_distribution")
            if data:
                return np.array(json.loads(data))
        except Exception:
            pass
        return None
    
    def _evaluate_model(self, X: np.ndarray, y: np.ndarray) -> dict[str, float]:
        """Evaluate model performance."""
        from sklearn.metrics import accuracy_score, precision_score, recall_score, f1_score
        
        predictions = self.model.predict(X)
        
        return {
            "accuracy": float(accuracy_score(y, predictions)),
            "precision": float(precision_score(y, predictions, zero_division=0)),
            "recall": float(recall_score(y, predictions, zero_division=0)),
            "f1": float(f1_score(y, predictions, zero_division=0)),
        }

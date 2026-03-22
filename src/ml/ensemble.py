"""Adaptive ensemble with online learning and dynamic weighting."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import structlog
import xgboost as xgb
from river import linear_model, optim, preprocessing
from sklearn.ensemble import RandomForestRegressor

from src.ml.drift import DriftDetector
from src.ml.regime import MarketRegime
from src.ml.registry import ModelRegistry

logger = structlog.get_logger()


@dataclass
class ModelPrediction:
    model: str
    prediction: float
    uncertainty: float
    latency_ms: float


class AdaptiveEnsemble:
    """Multi-model ensemble with online adaptation."""
    
    def __init__(self) -> None:
        self.models: dict[str, Any] = {}
        self.weights: dict[str, float] = {
            "xgb": 0.4,
            "rf": 0.35,
            "river": 0.25
        }
        self.performance: dict[str, list[float]] = {
            "xgb": [], "rf": [], "river": []
        }
        self.window_size = 100
        
        # Online learning
        self.river = (
            preprocessing.StandardScaler() | 
            linear_model.LinearRegression(optimizer=optim.Adam(lr=0.01))
        )
        
        # Drift detection per model
        self.drift_detectors: dict[str, DriftDetector] = {
            name: DriftDetector() for name in self.weights.keys()
        }
        
        # State
        self.scaler = None
        self.feature_names: list[str] = []
        self.is_fitted = False
        self.registry = ModelRegistry()
        
        # GPU
        self.device = "cuda" if xgb.rabit.get_rank() >= 0 else "cpu"  # Simplified check
    
    async def load(self) -> None:
        """Load or initialize models."""
        latest = await self.registry.get_latest("adaptive_ensemble")
        
        if latest:
            await self._load_checkpoint(latest)
        else:
            await self._initialize_fresh()
        
        self.is_fitted = True
        logger.info(f"Ensemble loaded: weights={self.weights}")
    
    async def predict(
        self,
        features: Any,
        regime: MarketRegime = MarketRegime.UNKNOWN,
        regime_confidence: float = 0.0
    ) -> dict[str, Any]:
        """Generate prediction with dynamic weighting."""
        start = asyncio.get_event_loop().time()
        
        feature_dict = features.to_dict() if hasattr(features, "to_dict") else features
        X = np.array([[feature_dict.get(f, 0.0) for f in self.feature_names]])
        
        # Individual predictions
        predictions: list[ModelPrediction] = []
        
        # XGBoost
        if "xgb" in self.models:
            xgb_pred, xgb_unc = await self._predict_xgb(X)
            predictions.append(ModelPrediction("xgb", xgb_pred, xgb_unc, 0))
        
        # Random Forest
        if "rf" in self.models:
            rf_pred, rf_unc = await self._predict_rf(X)
            predictions.append(ModelPrediction("rf", rf_pred, rf_unc, 0))
        
        # River (online)
        river_pred = self.river.predict_one(feature_dict)
        river_unc = 0.1  # Fixed for online model
        predictions.append(ModelPrediction("river", river_pred, river_unc, 0))
        
        # Dynamic weight adjustment based on regime
        weights = self._adjust_weights_for_regime(regime, regime_confidence)
        
        # Weighted ensemble
        total_weight = sum(weights.get(p.model, 0) for p in predictions)
        ensemble_pred = sum(
            p.prediction * weights.get(p.model, 0) / total_weight 
            for p in predictions
        )
        
        # Uncertainty propagation
        variances = [p.uncertainty ** 2 for p in predictions]
        ensemble_var = np.average(variances, weights=[weights.get(p.model, 0) for p in predictions])
        ensemble_unc = np.sqrt(ensemble_var)
        
        # Drift check
        drift_scores = {}
        for p in predictions:
            drift_scores[p.model] = await self.drift_detectors[p.model].update(
                X[0], p.prediction
            )
        
        latency_ms = (asyncio.get_event_loop().time() - start) * 1000
        
        return {
            "prediction": ensemble_pred,
            "confidence": 1.0 - min(ensemble_unc / abs(ensemble_pred) if ensemble_pred != 0 else 0, 1.0),
            "direction": "UP" if ensemble_pred > 0 else "DOWN",
            "uncertainty": ensemble_unc,
            "contributions": {p.model: p.prediction for p in predictions},
            "weights_used": weights,
            "drift_scores": drift_scores,
            "latency_ms": latency_ms,
            "regime": regime.name
        }
    
    async def _predict_xgb(self, X: np.ndarray) -> tuple[float, float]:
        """XGBoost prediction with uncertainty (leaf variance)."""
        dmatrix = xgb.DMatrix(X)
        pred = self.models["xgb"].predict(dmatrix)
        
        # Uncertainty from prediction variance across trees
        # Enable pred_interactions for uncertainty estimation
        uncertainty = 0.05  # Placeholder - implement tree variance
        
        return float(pred[0]), uncertainty
    
    async def _predict_rf(self, X: np.ndarray) -> tuple[float, float]:
        """RF prediction with uncertainty (tree disagreement)."""
        model = self.models["rf"]
        preds = np.array([tree.predict(X)[0] for tree in model.estimators_])
        
        mean_pred = np.mean(preds)
        uncertainty = np.std(preds)
        
        return float(mean_pred), float(uncertainty)
    
    def _adjust_weights_for_regime(
        self, 
        regime: MarketRegime, 
        confidence: float
    ) -> dict[str, float]:
        """Adjust ensemble weights based on market regime."""
        base_weights = self.weights.copy()
        
        # Regime-specific adjustments
        if regime == MarketRegime.TRENDING_UP or regime == MarketRegime.TRENDING_DOWN:
            # XGBoost better in trends (captures non-linear momentum)
            base_weights["xgb"] *= 1.2
            base_weights["river"] *= 0.8  # Linear model weaker in trends
        
        elif regime == MarketRegime.MEAN_REVERTING:
            # RF better for pattern recognition in ranges
            base_weights["rf"] *= 1.2
            base_weights["xgb"] *= 0.9
        
        elif regime == MarketRegime.HIGH_VOL:
            # Conservative: weight uncertainty more
            base_weights["river"] *= 1.1  # More stable
            base_weights["xgb"] *= 0.9
        
        # Normalize
        total = sum(base_weights.values())
        return {k: v/total for k, v in base_weights.items()}
    
    async def online_update(
        self,
        features: dict[str, float],
        target: float,
        outcome: float | None = None
    ) -> None:
        """Online learning update with performance tracking."""
        # Update River immediately
        self.river.learn_one(features, target)
        
        # Track performance for weight adaptation
        if outcome is not None:
            for model_name in self.performance:
                # Calculate error and update rolling performance
                pass  # Implement
        
        # Periodic batch update for XGB/RF
        # Buffer and retrain every N samples
        
    async def fallback_to_simpler_model(self) -> None:
        """Degrade gracefully to simpler model."""
        logger.warning("Falling back to River-only mode")
        self.weights = {"river": 1.0}
        self.models = {"river": self.river}
    
    async def _load_checkpoint(self, artifact: dict) -> None:
        """Load from registry."""
        # Implementation...
        pass
    
    async def _initialize_fresh(self) -> None:
        """Initialize fresh models."""
        self.models["xgb"] = xgb.XGBRegressor(
            n_estimators=100,
            max_depth=6,
            learning_rate=0.1,
            tree_method="hist",
            # device="cuda" if available
        )
        self.models["rf"] = RandomForestRegressor(
            n_estimators=100,
            max_depth=10
        )

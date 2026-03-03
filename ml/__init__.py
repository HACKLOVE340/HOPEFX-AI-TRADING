"""
Machine Learning Module

This module provides machine learning models for trading.

Model types:
- LSTM (Long Short-Term Memory) - Price prediction
- Random Forest - Signal classification
- Feature engineering - Technical indicators

Components:
- Feature engineering
- Model training
- Model evaluation
- Prediction generation
- Model versioning and storage
"""

from .models import BaseMLModel, LSTMPricePredictor, RandomForestTradingClassifier
from .features import TechnicalFeatureEngineer

__all__ = [
    'BaseMLModel',
    'LSTMPricePredictor',
    'RandomForestTradingClassifier',
    'TechnicalFeatureEngineer',
    'create_ml_router',
]

# Module metadata
__version__ = '1.0.0'
__author__ = 'HOPEFX Development Team'
__description__ = 'Machine learning models for price prediction and signal classification'


def create_ml_router(feature_engineer: 'TechnicalFeatureEngineer'):
    """
    Create a FastAPI router for the Machine Learning module.

    Exposes endpoints for feature engineering, model status, and
    (when a trained model is available) price-direction predictions.

    Args:
        feature_engineer: TechnicalFeatureEngineer instance

    Returns:
        FastAPI APIRouter
    """
    from fastapi import APIRouter, HTTPException
    from pydantic import BaseModel
    from typing import List, Dict, Any, Optional

    router = APIRouter(prefix="/api/ml", tags=["Machine Learning"])

    class OHLCVRow(BaseModel):
        open: float
        high: float
        low: float
        close: float
        volume: float

    class FeatureRequest(BaseModel):
        bars: List[OHLCVRow]

    @router.get("/status")
    async def get_status():
        """Return the status and capabilities of the ML module."""
        return {
            "module": "ML Predictions",
            "status": "experimental",
            "feature_engineer": "ready",
            "models": {
                "lstm": "requires training",
                "random_forest": "requires training",
                "ensemble": "requires training",
            },
            "note": (
                "Set FEATURE_ML_PREDICTIONS=true and provide labelled data "
                "to enable live predictions."
            ),
        }

    @router.get("/features/groups")
    async def get_feature_groups():
        """Return the feature groups produced by the feature engineer."""
        return feature_engineer.get_feature_groups()

    @router.post("/features/compute")
    async def compute_features(req: FeatureRequest):
        """
        Compute technical features for a OHLCV bar series.

        Send at least 200 bars to avoid NaN-heavy output.
        """
        import pandas as pd
        if len(req.bars) < 10:
            raise HTTPException(
                status_code=422,
                detail="At least 10 bars are required to compute features.",
            )
        df = pd.DataFrame([b.dict() for b in req.bars])
        try:
            features_df = feature_engineer.create_features(df)
        except Exception as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        return {
            "rows": len(features_df),
            "feature_count": len(feature_engineer.feature_names),
            "feature_names": feature_engineer.feature_names,
            "sample": features_df.tail(3).to_dict(orient="records"),
        }

    return router


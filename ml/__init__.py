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
]

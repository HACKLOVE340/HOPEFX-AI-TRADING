# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
Machine Learning Models

Implemented models:
- BaseMLModel: Abstract base class for all ML models
- LSTMPricePredictor: LSTM neural network for price prediction
- LSTMPredictor: Advanced multi-feature LSTM predictor
- EnsembleLSTMPredictor: Ensemble of LSTM models
- RandomForestTradingClassifier: Random Forest for signal classification
- EnsemblePredictor: Advanced ensemble combining LSTM, RF, GB, XGBoost
- RandomForestModel: Lightweight RF wrapper (trading_models)
- GradientBoostingModel: Gradient Boosting wrapper (trading_models)
- EnsembleModel: Lightweight ensemble wrapper (trading_models)
"""

from .base import BaseMLModel
from .ensemble import EnsemblePrediction, EnsemblePredictor, ModelPrediction
from .lstm import LSTMPricePredictor
from .lstm_predictor import EnsembleLSTMPredictor, LSTMPredictor, PredictionResult
from .random_forest import RandomForestTradingClassifier
from .trading_models import EnsembleModel, GradientBoostingModel
from .trading_models import RandomForestModel as TradingRandomForestModel

__all__ = [
    "BaseMLModel",
    "EnsembleLSTMPredictor",
    "EnsembleModel",
    "EnsemblePrediction",
    "EnsemblePredictor",
    "GradientBoostingModel",
    "LSTMPredictor",
    "LSTMPricePredictor",
    "ModelPrediction",
    "PredictionResult",
    "RandomForestTradingClassifier",
    "TradingRandomForestModel",
]

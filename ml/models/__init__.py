# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026 Opeyemi (HACKLOVE340)
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
Machine Learning Models

Implemented models:
- BaseMLModel: Abstract base class for all ML models
- LSTMPricePredictor: LSTM neural network for price prediction
- RandomForestTradingClassifier: Random Forest for signal classification
- EnsemblePredictor: Advanced ensemble combining LSTM, RF, GB, XGBoost
"""

from .base import BaseMLModel
from .ensemble import EnsemblePrediction, EnsemblePredictor, ModelPrediction
from .lstm import LSTMPricePredictor
from .random_forest import RandomForestTradingClassifier

__all__ = [
    "BaseMLModel",
    "LSTMPricePredictor",
    "RandomForestTradingClassifier",
    "EnsemblePredictor",
    "EnsemblePrediction",
    "ModelPrediction",
]

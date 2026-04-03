# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""explainability/models.py — Data models for AI explainability."""

import logging
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

logger = logging.getLogger(__name__)


class ExplanationType(Enum):
    """Types of AI explanations"""

    FEATURE_IMPORTANCE = "feature_importance"
    DECISION_PATH = "decision_path"
    CONFIDENCE_INTERVAL = "confidence_interval"
    COUNTERFACTUAL = "counterfactual"
    SHAP_VALUES = "shap_values"
    LIME_EXPLANATION = "lime_explanation"


@dataclass
class FeatureContribution:
    """Single feature's contribution to prediction"""

    feature_name: str
    feature_value: float
    contribution: float  # Positive = supports prediction, negative = against
    importance_rank: int
    description: str = ""


@dataclass
class DecisionNode:
    """Node in decision path"""

    node_id: int
    feature: str
    threshold: float
    operator: str  # '<' or '>='
    value_at_node: float
    decision: str  # 'left' or 'right'
    samples: int


@dataclass
class Explanation:
    """Complete AI explanation for a prediction"""

    explanation_id: str
    prediction: float
    prediction_class: str  # 'BUY', 'SELL', 'HOLD'
    confidence: float
    timestamp: datetime
    feature_contributions: list[FeatureContribution]
    decision_path: list[DecisionNode]
    confidence_interval: tuple[float, float]
    key_factors: list[str]
    natural_language: str


@dataclass
class ModelPerformanceExplanation:
    """Explanation of model's historical performance"""

    model_name: str
    accuracy: float
    precision: float
    recall: float
    f1_score: float
    total_predictions: int
    correct_predictions: int
    confusion_matrix: dict[str, dict[str, int]]
    best_performing_conditions: list[str]
    worst_performing_conditions: list[str]
    feature_importance_history: list[dict[str, float]]

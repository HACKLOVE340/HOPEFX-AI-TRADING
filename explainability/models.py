"""explainability/models.py — Data models for AI explainability."""

from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
import logging

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
    feature_contributions: List[FeatureContribution]
    decision_path: List[DecisionNode]
    confidence_interval: Tuple[float, float]
    key_factors: List[str]
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
    confusion_matrix: Dict[str, Dict[str, int]]
    best_performing_conditions: List[str]
    worst_performing_conditions: List[str]
    feature_importance_history: List[Dict[str, float]]



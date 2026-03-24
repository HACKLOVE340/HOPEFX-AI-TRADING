"""
explainability — AI Signal Explainability

Provides SHAP-based feature importance, decision tree visualization,
and plain-English explanations for every AI trading signal.

Submodules:
    models    — Data classes (FeatureContribution, Explanation, …)
    explainer — AIExplainer: compute and cache signal explanations
    router    — FastAPI router exposing explanations via REST API
"""

from explainability.models import (
    ExplanationType,
    FeatureContribution,
    DecisionNode,
    Explanation,
    ModelPerformanceExplanation,
)
from explainability.explainer import AIExplainer
from explainability.router import create_explainability_router

__all__ = [
    "AIExplainer",
    "Explanation",
    "FeatureContribution",
    "DecisionNode",
    "ModelPerformanceExplanation",
    "ExplanationType",
    "create_explainability_router",
]

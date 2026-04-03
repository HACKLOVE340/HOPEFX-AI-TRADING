# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
explainability — AI Signal Explainability

Provides SHAP-based feature importance, decision tree visualization,
and plain-English explanations for every AI trading signal.

Submodules:
    models    — Data classes (FeatureContribution, Explanation, …)
    explainer — AIExplainer: compute and cache signal explanations
    router    — FastAPI router exposing explanations via REST API
"""

from explainability.explainer import AIExplainer
from explainability.models import (
    DecisionNode,
    Explanation,
    ExplanationType,
    FeatureContribution,
    ModelPerformanceExplanation,
)
from explainability.router import create_explainability_router

__all__ = [
    "AIExplainer",
    "DecisionNode",
    "Explanation",
    "ExplanationType",
    "FeatureContribution",
    "ModelPerformanceExplanation",
    "create_explainability_router",
]

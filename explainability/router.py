# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""explainability/router.py — FastAPI router for AI explainability endpoints."""

from explainability.explainer import AIExplainer


def create_explainability_router(explainer: "AIExplainer"):
    """
    Create a FastAPI router for the AI Explainability module.

    Args:
        explainer: AIExplainer instance

    Returns:
        FastAPI APIRouter
    """
    from fastapi import APIRouter, HTTPException
    from pydantic import BaseModel

    router = APIRouter(prefix="/api/explainability", tags=["Explainability"])

    class ExplainRequest(BaseModel):
        prediction: float
        prediction_class: str
        features: dict[str, float]
        model_name: str = "default"

    class CounterfactualRequest(BaseModel):
        explanation_id: str
        target_prediction: str

    @router.post("/explain")
    async def explain_prediction(req: ExplainRequest):
        """Generate a full explanation for a model prediction."""
        explanation = explainer.explain_prediction(
            model=None,  # AIExplainer handles None model gracefully
            features=req.features,
            prediction=req.prediction,
            prediction_class=req.prediction_class,
        )
        return {
            "explanation_id": explanation.explanation_id,
            "prediction": explanation.prediction,
            "prediction_class": explanation.prediction_class,
            "confidence": explanation.confidence,
            "key_factors": explanation.key_factors,
            "natural_language": explanation.natural_language,
            "timestamp": explanation.timestamp.isoformat(),
        }

    @router.get("/history")
    async def get_history(limit: int = 50):
        """Get recent explanation history."""
        return explainer.get_explanation_history(limit=limit)

    @router.get("/model/{model_name}/performance")
    async def get_model_performance(model_name: str):
        """Get performance explanation for a named model."""
        perf = explainer.get_model_performance_explanation(model_name)
        if perf is None:
            raise HTTPException(status_code=404, detail=f"No data for model '{model_name}'")
        return {
            "model_name": perf.model_name,
            "accuracy": perf.accuracy,
            "win_rate": perf.win_rate,
            "avg_confidence": perf.avg_confidence,
            "total_predictions": perf.total_predictions,
            "summary": perf.summary,
        }

    @router.post("/counterfactual")
    async def generate_counterfactual(req: CounterfactualRequest):
        """Generate a counterfactual explanation (what would need to change)."""
        result = explainer.generate_counterfactual(req.explanation_id, req.target_prediction)
        if result is None:
            raise HTTPException(status_code=404, detail=f"Explanation {req.explanation_id} not found")
        return result

    @router.get("/explanation/{explanation_id}/chart")
    async def get_chart_data(explanation_id: str):
        """Get feature-importance chart data for visualisation."""
        history = explainer.get_explanation_history(limit=1000)
        match = next((e for e in history if e["id"] == explanation_id), None)
        if match is None:
            raise HTTPException(status_code=404, detail=f"Explanation {explanation_id} not found")
        # Return the stored explanation object's chart data via the explainer
        stored = next(
            (e for e in explainer.explanation_history if e.explanation_id == explanation_id),
            None,
        )
        if stored is None:
            raise HTTPException(status_code=404, detail=f"Explanation {explanation_id} not found")
        return explainer.get_feature_importance_chart_data(stored)

    return router


# Module exports

# Module-level router — imported by core.router_registry
_explainer_instance = None


def _get_explainer():
    global _explainer_instance
    if _explainer_instance is None:
        _explainer_instance = AIExplainer()
    return _explainer_instance


router = create_explainability_router(_get_explainer())

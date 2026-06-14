# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
api/nocode.py
==============
No-Code Strategy Builder API — serves the frontend Strategy Builder page.
Provides: /api/nocode/templates, /api/nocode/deploy, /api/nocode/validate
Connected to: nocode/builder.py, nocode/state_machine.py, nocode/ml_nodes.py
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/nocode", tags=["No-Code Builder"])


# ── Request Models ───────────────────────────────────────────────────────────


class DeployRequest(BaseModel):
    """Request body for deploying a no-code strategy template."""
    template_id: str = Field(..., description="Template ID to deploy")
    parameters: dict = Field(default_factory=dict, description="Override parameters")
    symbol: str = Field(default="XAU_USD", description="Trading symbol")
    timeframe: str = Field(default="M15", description="Timeframe")


class ValidateRequest(BaseModel):
    """Request body for validating a no-code strategy definition."""
    nodes: list[dict] = Field(..., description="List of strategy nodes")
    edges: list[dict] = Field(default_factory=list, description="Node connections")


# ── Endpoints ────────────────────────────────────────────────────────────────


@router.get("/templates")
async def list_templates(
    category: Optional[str] = Query(None, description="Filter by category"),
):
    """
    List available no-code strategy templates.
    Templates include pre-built strategies that users can deploy with parameter overrides.
    """
    try:
        from nocode.builder import NoCodeStrategyBuilder
        builder = NoCodeStrategyBuilder()
        templates = builder.get_templates(category=category)
        return {"templates": templates, "total": len(templates)}
    except Exception as e:
        logger.error(f"Failed to list templates: {e}")
        # Return built-in templates as fallback
        built_in = [
            {
                "id": "smc_breakout",
                "name": "SMC Breakout",
                "category": "trend",
                "description": "Smart Money Concepts breakout strategy with order block detection",
                "parameters": {"lookback": 20, "risk_reward": 2.0, "atr_multiplier": 1.5},
                "complexity": "intermediate",
            },
            {
                "id": "mean_reversion_rsi",
                "name": "Mean Reversion RSI",
                "category": "mean_reversion",
                "description": "RSI-based mean reversion with dynamic overbought/oversold levels",
                "parameters": {"rsi_period": 14, "ob_level": 70, "os_level": 30},
                "complexity": "beginner",
            },
            {
                "id": "news_sentiment_filter",
                "name": "News Sentiment Filter",
                "category": "fundamental",
                "description": "Filters trades based on nuclear wordmap sentiment scores",
                "parameters": {"min_score": 0.6, "max_nuclear_level": 3},
                "complexity": "advanced",
            },
            {
                "id": "multi_timeframe_confluence",
                "name": "Multi-Timeframe Confluence",
                "category": "trend",
                "description": "Requires alignment across H4, H1, and M15 for entry",
                "parameters": {"timeframes": ["H4", "H1", "M15"], "min_alignment": 3},
                "complexity": "advanced",
            },
            {
                "id": "ml_ensemble_signal",
                "name": "ML Ensemble Signal",
                "category": "ml",
                "description": "Combines LSTM, XGBoost, and attention model predictions",
                "parameters": {"confidence_threshold": 0.7, "ensemble_method": "weighted"},
                "complexity": "expert",
            },
        ]
        if category:
            built_in = [t for t in built_in if t["category"] == category]
        return {"templates": built_in, "total": len(built_in)}


@router.post("/deploy")
async def deploy_template(request: DeployRequest):
    """
    Deploy a no-code strategy template as a live strategy.
    Compiles the template with provided parameters and registers it
    in the Dynamic Strategy Registry for activation.
    """
    try:
        from nocode.builder import NoCodeStrategyBuilder
        builder = NoCodeStrategyBuilder()

        # Compile template to executable strategy
        compiled = await builder.compile_template(
            template_id=request.template_id,
            parameters=request.parameters,
            symbol=request.symbol,
            timeframe=request.timeframe,
        )

        # Register in dynamic strategy registry
        from strategies.dynamic_registry import get_dynamic_registry
        registry = get_dynamic_registry()
        version_id = await registry.register_strategy(
            name=compiled["name"],
            source_code=compiled["source_code"],
            symbol=request.symbol,
            timeframe=request.timeframe,
            author_id="nocode_builder",
        )

        # Auto-activate the deployed strategy
        await registry.activate_strategy(version_id)

        return {
            "status": "deployed",
            "version_id": version_id,
            "strategy_name": compiled["name"],
            "message": f"Template '{request.template_id}' deployed and activated.",
        }
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.error(f"Template deployment failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Deployment failed: {e}")


@router.post("/validate")
async def validate_strategy(request: ValidateRequest):
    """
    Validate a no-code strategy definition (nodes + edges).
    Checks for: valid node types, proper connections, no cycles in execution flow,
    and required parameters.
    """
    try:
        from nocode.state_machine import StateMachineEngine
        engine = StateMachineEngine()
        result = engine.validate_graph(nodes=request.nodes, edges=request.edges)
        return result
    except Exception as e:
        logger.error(f"Validation failed: {e}")
        return {
            "valid": False,
            "errors": [str(e)],
            "warnings": [],
        }


@router.get("/node-types")
async def get_node_types():
    """
    Get all available node types for the visual strategy builder.
    Includes: indicators, conditions, actions, ML nodes, risk nodes.
    """
    node_types = {
        "indicators": [
            {"id": "rsi", "name": "RSI", "params": ["period"], "outputs": ["value"]},
            {"id": "macd", "name": "MACD", "params": ["fast", "slow", "signal"], "outputs": ["macd", "signal", "histogram"]},
            {"id": "atr", "name": "ATR", "params": ["period"], "outputs": ["value"]},
            {"id": "bollinger", "name": "Bollinger Bands", "params": ["period", "std_dev"], "outputs": ["upper", "middle", "lower"]},
            {"id": "ema", "name": "EMA", "params": ["period"], "outputs": ["value"]},
            {"id": "sma", "name": "SMA", "params": ["period"], "outputs": ["value"]},
            {"id": "stochastic", "name": "Stochastic", "params": ["k_period", "d_period"], "outputs": ["k", "d"]},
            {"id": "adx", "name": "ADX", "params": ["period"], "outputs": ["value", "plus_di", "minus_di"]},
        ],
        "conditions": [
            {"id": "crossover", "name": "Crossover", "inputs": ["line_a", "line_b"], "outputs": ["signal"]},
            {"id": "threshold", "name": "Threshold", "inputs": ["value"], "params": ["level", "direction"], "outputs": ["signal"]},
            {"id": "time_filter", "name": "Time Filter", "params": ["start_hour", "end_hour", "days"], "outputs": ["allowed"]},
            {"id": "spread_filter", "name": "Spread Filter", "params": ["max_spread_pips"], "outputs": ["allowed"]},
        ],
        "actions": [
            {"id": "buy", "name": "Buy", "inputs": ["signal"], "params": ["lot_size"]},
            {"id": "sell", "name": "Sell", "inputs": ["signal"], "params": ["lot_size"]},
            {"id": "close_all", "name": "Close All", "inputs": ["signal"]},
            {"id": "trailing_stop", "name": "Trailing Stop", "inputs": ["position"], "params": ["distance_pips"]},
        ],
        "ml_nodes": [
            {"id": "ml_predict", "name": "ML Prediction", "params": ["model_name", "confidence_threshold"], "outputs": ["prediction", "confidence"]},
            {"id": "sentiment_score", "name": "Sentiment Score", "params": ["source"], "outputs": ["score", "direction"]},
            {"id": "anomaly_detect", "name": "Anomaly Detection", "params": ["sensitivity"], "outputs": ["is_anomaly", "score"]},
        ],
        "risk": [
            {"id": "position_size", "name": "Position Sizer", "params": ["risk_percent", "method"], "outputs": ["lot_size"]},
            {"id": "max_drawdown", "name": "Max Drawdown Guard", "params": ["max_dd_percent"], "outputs": ["allowed"]},
            {"id": "correlation_filter", "name": "Correlation Filter", "params": ["max_correlation"], "outputs": ["allowed"]},
        ],
    }
    return {"node_types": node_types}

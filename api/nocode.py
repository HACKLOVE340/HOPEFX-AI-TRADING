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

import os
import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from api.auth import TokenPayload, get_current_user
from monetization.subscription import require_plan
from pydantic import BaseModel, Field
from api.error_details import safe_error

from strategies.strategy_execution_boundary import ExecutionScope

logger = logging.getLogger(__name__)


def _activation_scope() -> ExecutionScope:
    """The scope this deployment actually activates at.

    Derived from BROKER_TYPE rather than defaulted. The gate this feeds
    (`StrategyExecutionBoundary`) previously took `ExecutionScope.RESEARCH` as
    its default and short-circuited every check on it, so activation happened
    under a scope no caller had chosen. Choosing here means the claim matches
    what the registry then does -- it sets StrategyState.ACTIVE either way.
    """
    return ExecutionScope.PAPER if os.getenv("BROKER_TYPE", "paper").strip().lower() == "paper" else ExecutionScope.LIVE


router = APIRouter(prefix="/api/nocode", tags=["No-Code Builder"])

# The Strategy Builder is advertised as a professional-tier feature in the
# frontend nav (navConfig: plan: 'professional'), but these routes only ever
# checked *authentication*, so any logged-in free-tier user could deploy a live
# strategy. The gate has to live here — the client-side one is a courtesy.
#
# Written out at each route rather than bound to a module-level alias:
# scripts/ci/gate_a_auth_coverage.py reads the dependency statically and
# recognises `require_plan`, but cannot follow an alias, so an alias reads to
# the gate as an unauthenticated mutating endpoint.


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
    category: str | None = Query(None, description="Filter by category"),
    user: TokenPayload = Depends(require_plan("professional")),
):
    """
    List available no-code strategy templates.
    Templates include pre-built strategies that users can deploy with parameter overrides.

    Requires a professional plan — templates are proprietary strategy IP and the
    Strategy Builder is a professional-tier feature. Authentication alone is not
    enough: it left every free-tier account able to read and deploy them.
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
async def deploy_template(
    request: DeployRequest,
    user: TokenPayload = Depends(require_plan("professional")),
):
    """
    Deploy a no-code strategy template as a live strategy.
    Compiles the template with provided parameters and registers it
    in the Dynamic Strategy Registry for activation.

    Requires a professional plan — this activates a strategy against live
    trading, so it is both a paid feature and a privileged action.
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
            # Attribute the strategy to the account that deployed it. This was
            # the constant "nocode_builder", so a live strategy could not be
            # traced back to whoever activated it.
            author_id=user.sub,
        )

        # Auto-activate the deployed strategy
        await registry.activate_strategy(scope=_activation_scope(), version_id=version_id)

        return {
            "status": "deployed",
            "version_id": version_id,
            "strategy_name": compiled["name"],
            "message": f"Template '{request.template_id}' deployed and activated.",
        }
    except ValueError as e:
        # Deliberate: the compiler raises ValueError to say *why* a template is
        # invalid, and that message is the response's whole purpose. It is our
        # own copy, not an arbitrary library's, so it passes through unchanged.
        raise HTTPException(status_code=422, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Deployment failed: {safe_error(e, 'nocode deploy')}") from e


@router.post("/validate")
async def validate_strategy(
    request: ValidateRequest,
    user: TokenPayload = Depends(require_plan("professional")),
):
    """
    Validate a no-code strategy definition (nodes + edges).
    Checks for: valid node types, proper connections, no cycles in execution flow,
    and required parameters.
    """
    try:
        from nocode.graph_validation import validate_graph

        return validate_graph(request.nodes, request.edges)
    except Exception as e:
        # Genuine validation findings come back inside `result` above. Reaching
        # here means the engine itself failed, so this is an internal error
        # wearing a validation response's shape — not something to quote back.
        return {
            "valid": False,
            "errors": [safe_error(e, "nocode graph validation")],
            "warnings": [],
        }


@router.get("/node-types")
async def get_node_types(user: TokenPayload = Depends(get_current_user)):
    """
    Get all available node types for the visual strategy builder.
    Includes: indicators, conditions, actions, ML nodes, risk nodes.

    Requires authentication. The node taxonomy describes the same proprietary
    strategy surface that /templates was deliberately locked down to protect;
    this endpoint previously had no auth dependency at all. It stays at
    authentication rather than the professional gate so the builder UI can
    render its palette for an upgrade preview.
    """
    # The taxonomy lives in nocode/graph_validation.py so the palette this
    # endpoint renders and the rules /validate enforces cannot drift apart.
    from nocode.graph_validation import NODE_TYPES

    return {"node_types": NODE_TYPES}

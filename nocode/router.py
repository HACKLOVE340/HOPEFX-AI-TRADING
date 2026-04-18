# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""nocode/router.py — FastAPI router for the no-code strategy builder."""

from nocode.builder import NoCodeStrategyBuilder


def create_nocode_router(builder: "NoCodeStrategyBuilder"):
    """
    Create a FastAPI router for the No-Code Strategy Builder module.

    Args:
        builder: NoCodeStrategyBuilder instance

    Returns:
        FastAPI APIRouter
    """
    from fastapi import APIRouter, HTTPException
    from pydantic import BaseModel

    router = APIRouter(prefix="/api/nocode", tags=["No-Code Builder"])

    class CreateStrategyRequest(BaseModel):
        name: str
        description: str = ""
        symbol: str = "XAUUSD"
        timeframe: str = "1h"

    class PlainEnglishRequest(BaseModel):
        description: str
        symbol: str = "XAUUSD"
        timeframe: str = "1h"

    class FromTemplateRequest(BaseModel):
        name: str
        symbol: str = "XAUUSD"
        timeframe: str = "1h"

    @router.get("/strategies")
    async def list_strategies():
        """List all no-code strategies."""
        return [
            {
                "strategy_id": sid,
                "name": s.name,
                "description": s.description,
                "symbol": s.symbol,
                "timeframe": s.timeframe,
                "is_active": s.is_active,
                "rules_count": len(s.rules),
                "created_at": s.created_at.isoformat(),
            }
            for sid, s in builder.strategies.items()
        ]

    @router.post("/strategies")
    async def create_strategy(req: CreateStrategyRequest):
        """Create a new empty no-code strategy."""
        strategy = builder.create_strategy(
            name=req.name,
            description=req.description,
            symbol=req.symbol,
            timeframe=req.timeframe,
        )
        return {
            "strategy_id": strategy.strategy_id,
            "name": strategy.name,
            "symbol": strategy.symbol,
            "timeframe": strategy.timeframe,
        }

    @router.get("/strategies/{strategy_id}/export")
    async def export_strategy(strategy_id: str):
        """Export a no-code strategy as Python code."""
        code = builder.export_to_python(strategy_id)
        if code is None:
            raise HTTPException(status_code=404, detail=f"Strategy {strategy_id} not found")
        return {"strategy_id": strategy_id, "python_code": code}

    @router.post("/strategies/parse")
    async def parse_plain_english(req: PlainEnglishRequest):
        """Parse a plain-English strategy description into a structured strategy."""
        strategy = builder.parse_plain_english(req.description, req.symbol, req.timeframe)
        if strategy is None:
            raise HTTPException(
                status_code=422,
                detail="Could not parse strategy description. Try including trigger conditions and actions.",
            )
        return {
            "strategy_id": strategy.strategy_id,
            "name": strategy.name,
            "rules_count": len(strategy.rules),
            "symbol": strategy.symbol,
            "timeframe": strategy.timeframe,
        }

    @router.get("/indicators")
    async def get_indicators():
        """Get list of available indicators for building conditions."""
        return builder.get_available_indicators()

    @router.get("/templates")
    async def get_templates():
        """Get list of built-in strategy templates."""
        return builder.get_templates()

    @router.post("/strategies/from-template/{template_id}")
    async def create_from_template(template_id: str, req: FromTemplateRequest):
        """Create a strategy from a built-in template."""
        strategy = builder.create_from_template(template_id, req.name, req.symbol, req.timeframe)
        if strategy is None:
            raise HTTPException(status_code=404, detail=f"Template {template_id} not found")
        return {
            "strategy_id": strategy.strategy_id,
            "name": strategy.name,
            "rules_count": len(strategy.rules),
        }

    return router


# Module-level router — imported by core.router_registry
_nocode_builder_instance = None


def _get_nocode_builder():
    global _nocode_builder_instance
    if _nocode_builder_instance is None:
        _nocode_builder_instance = NoCodeStrategyBuilder()
    return _nocode_builder_instance


router = create_nocode_router(_get_nocode_builder())


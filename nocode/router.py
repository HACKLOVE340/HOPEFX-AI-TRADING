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
    from fastapi import APIRouter, Depends, HTTPException
    from pydantic import BaseModel
    from api.auth import TokenPayload, get_current_user, require_role

    router = APIRouter(prefix="/api/nocode", tags=["No-Code Builder"], dependencies=[Depends(get_current_user)])

    def _visible_to(strategy, user_id: str) -> bool:
        """Whether *user_id* may see or act on *strategy*.

        A strategy with no owner is a built-in template — `_create_templates()`
        puts those in the same dict at builder init — and stays visible to
        everyone. Everything else belongs to whoever created it.
        """
        owner = getattr(strategy, "user_id", None)
        return owner is None or owner == user_id

    def _viewable_strategy(strategy_id: str, user_id: str):
        """Return a strategy the caller may read (their own, or a template)."""
        strategy = builder.strategies.get(strategy_id)
        if strategy is None or not _visible_to(strategy, user_id):
            raise HTTPException(status_code=404, detail=f"Strategy {strategy_id} not found")
        return strategy

    def _owned_strategy(strategy_id: str, user_id: str):
        """Return a strategy the caller owns, or raise 404.

        Ownership, not visibility. This gates PATCH, DELETE, compile and
        backtest, and it used to reuse the *read* predicate, which treats an
        ownerless strategy as everyone's. The built-in templates
        `_create_templates()`
        installs carry `user_id=None` in the **shared** `builder.strategies`
        dict, so any trader could edit or delete the very objects
        `create_from_template` hands to the next caller.

        Working from a template means copying it — that is what
        `create_from_template` is for — so a built-in, having no owner, is
        owned by nobody.

        404 rather than 403 for someone else's strategy, so the response does
        not disclose which strategy ids exist — the same choice
        `api/alerts._get_owned_alert` makes.
        """
        strategy = builder.strategies.get(strategy_id)
        if strategy is None or getattr(strategy, "user_id", None) != user_id:
            raise HTTPException(status_code=404, detail=f"Strategy {strategy_id} not found")
        return strategy

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
    async def list_strategies(user: TokenPayload = Depends(require_role("trader"))):
        """List the caller's no-code strategies, plus the built-in templates.

        This took no user parameter at all and returned every strategy in the
        shared `builder.strategies` dict — every other trader's included.
        """
        return [
            {
                "strategy_id": sid,
                "name": s.name,
                "description": s.description,
                "symbol": s.symbol,
                "timeframe": s.timeframe,
                "is_active": getattr(s, "is_active", getattr(s, "enabled", True)),
                "rules_count": len(s.rules),
                "created_at": s.created_at.isoformat(),
            }
            for sid, s in builder.strategies.items()
            if _visible_to(s, user.sub)
        ]

    @router.post("/strategies")
    async def create_strategy(
        req: CreateStrategyRequest,
        user: TokenPayload = Depends(require_role("trader")),
    ):
        """Create a new empty no-code strategy."""
        strategy = builder.create_strategy(
            name=req.name,
            description=req.description,
            symbol=req.symbol,
            timeframe=req.timeframe,
            user_id=user.sub,
        )
        return {
            "strategy_id": strategy.strategy_id,
            "name": strategy.name,
            "symbol": strategy.symbol,
            "timeframe": strategy.timeframe,
        }

    @router.get("/strategies/{strategy_id}")
    async def get_strategy(strategy_id: str):
        """Return a single strategy by ID with all rules."""
        strategy = builder.strategies.get(strategy_id)
        if strategy is None:
            raise HTTPException(status_code=404, detail=f"Strategy {strategy_id} not found")
        return strategy.to_dict()

    @router.patch("/strategies/{strategy_id}")
    async def update_strategy(
        strategy_id: str,
        req: CreateStrategyRequest,
        user: TokenPayload = Depends(require_role("trader")),
    ):
        """Update strategy metadata (name, description, symbol, timeframe)."""
        strategy = _owned_strategy(strategy_id, user.sub)
        if req.name:
            strategy.name = req.name
        if req.description is not None:
            strategy.description = req.description
        if req.symbol:
            strategy.symbol = req.symbol
        if req.timeframe:
            strategy.timeframe = req.timeframe
        return strategy.to_dict()

    @router.delete("/strategies/{strategy_id}", status_code=204)
    async def delete_strategy(
        strategy_id: str,
        user: TokenPayload = Depends(require_role("trader")),
    ):
        """Delete a strategy."""
        _owned_strategy(strategy_id, user.sub)
        del builder.strategies[strategy_id]

    @router.post("/strategies/{strategy_id}/compile")
    async def compile_strategy(
        strategy_id: str,
        user: TokenPayload = Depends(require_role("trader")),
    ):
        """Compile a strategy to Python and validate it."""
        strategy = _owned_strategy(strategy_id, user.sub)
        code = builder.export_to_python(strategy_id)
        if not code:
            raise HTTPException(status_code=404, detail=f"Strategy {strategy_id} not found")
        return {
            "strategy_id": strategy_id,
            "status": "compiled",
            "code": code,
            "rules_count": len(strategy.rules) if strategy else 0,
        }

    @router.post("/strategies/{strategy_id}/backtest")
    async def backtest_strategy(
        strategy_id: str,
        user: TokenPayload = Depends(require_role("trader")),
    ):
        """Queue a backtest for a no-code strategy."""
        strategy = _owned_strategy(strategy_id, user.sub)
        try:
            from backtesting.engine import BacktestEngine

            engine = BacktestEngine()
            result = engine.run_strategy_backtest(
                strategy_id=strategy_id,
                symbol=strategy.symbol,
                timeframe=strategy.timeframe,
            )
            return result
        except Exception as exc:
            return {
                "strategy_id": strategy_id,
                "status": "pending",
                "message": f"Backtest queued — engine unavailable: {exc}",
                "symbol": strategy.symbol,
                "timeframe": strategy.timeframe,
            }

    @router.get("/blocks")
    async def list_blocks():
        """Return available building blocks (indicators, conditions, actions)."""
        return {
            "indicators": builder.get_available_indicators(),
            "conditions": [
                {"id": "crosses_above", "label": "Crosses above"},
                {"id": "crosses_below", "label": "Crosses below"},
                {"id": "greater_than", "label": "Greater than"},
                {"id": "less_than", "label": "Less than"},
                {"id": "equals", "label": "Equals"},
            ],
            "actions": [
                {"id": "buy", "label": "Buy"},
                {"id": "sell", "label": "Sell"},
                {"id": "close_all", "label": "Close all"},
                {"id": "close_long", "label": "Close long"},
                {"id": "close_short", "label": "Close short"},
            ],
        }

    @router.get("/strategies/{strategy_id}/export")
    async def export_strategy(
        strategy_id: str,
        user: TokenPayload = Depends(require_role("trader")),
    ):
        """Export one of the caller's no-code strategies as Python code.

        This had no user parameter and no role gate — only the router-level
        `Depends(get_current_user)` — so any authenticated account, of any
        role, could dump the generated source of any strategy. A strategy is
        the user's trading logic, and the platform sells strategies through
        /api/monetization/marketplace.
        """
        _viewable_strategy(strategy_id, user.sub)
        code = builder.export_to_python(strategy_id)
        if code is None:
            raise HTTPException(status_code=404, detail=f"Strategy {strategy_id} not found")
        return {"strategy_id": strategy_id, "python_code": code}

    @router.post("/strategies/parse")
    async def parse_plain_english(
        req: PlainEnglishRequest,
        user: TokenPayload = Depends(require_role("trader")),
    ):
        """Parse a plain-English strategy description into a structured strategy."""
        strategy = builder.parse_plain_english(req.description, req.symbol, req.timeframe, user_id=user.sub)
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
    async def create_from_template(
        template_id: str,
        req: FromTemplateRequest,
        user: TokenPayload = Depends(require_role("trader")),
    ):
        """Create a strategy from a built-in template."""
        strategy = builder.create_from_template(template_id, req.name, req.symbol, req.timeframe, user_id=user.sub)
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

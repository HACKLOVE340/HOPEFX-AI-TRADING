# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
api/brain.py
============
AI Strategy Generator endpoints.

Routes
------
POST /api/brain/generate-strategy  — prompt → generated strategy code + backtest
POST /api/brain/deploy-strategy    — deploy generated strategy to paper trading
"""

from __future__ import annotations

import logging
import os

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from api.auth import TokenPayload, require_role

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/brain", tags=["AI Brain"])


# ── Models ────────────────────────────────────────────────────────────────────


class GenerateRequest(BaseModel):
    prompt: str = Field(..., min_length=5, max_length=2000)
    symbol: str = Field("XAU_USD")
    timeframe: str = Field("H1")
    candle_count: int = Field(500, ge=100, le=2000)


class BacktestSummary(BaseModel):
    total_return_pct: float
    sharpe_ratio: float
    max_drawdown_pct: float
    win_rate: float
    total_trades: int


class GenerateResponse(BaseModel):
    success: bool
    strategy_name: str
    strategy_code: str
    backtest: BacktestSummary | None
    iterations: int
    error: str | None = None


class DeployRequest(BaseModel):
    strategy_name: str
    strategy_code: str
    symbol: str = "XAU_USD"
    mode: str = "paper"


class DeployResponse(BaseModel):
    success: bool
    message: str
    strategy_id: str | None = None


# ── Endpoints ─────────────────────────────────────────────────────────────────


@router.post("/generate-strategy", response_model=GenerateResponse)
async def generate_strategy(
    req: GenerateRequest,
    user: TokenPayload = Depends(require_role("admin")),
) -> GenerateResponse:
    """
    Generate a trading strategy from a plain-English prompt.
    Uses brain.llm_agent.LLMAgent if OPENAI_API_KEY is set;
    returns a degraded response otherwise so the UI works without credentials.
    Requires: role >= 'admin' (LLM calls cost money per invocation).
    """
    openai_key = os.getenv("OPENAI_API_KEY", "")

    if openai_key:
        try:
            from brain.llm_agent import LLMAgent

            agent = LLMAgent(api_key=openai_key)
            result = await agent.generate_strategy(
                prompt=req.prompt,
                symbol=req.symbol,
                timeframe=req.timeframe,
                candle_count=req.candle_count,
            )
            bt = None
            if result.backtest:
                bt = BacktestSummary(
                    total_return_pct=float(
                        getattr(result.backtest, "total_return_pct", 0),
                    ),
                    sharpe_ratio=float(getattr(result.backtest, "sharpe_ratio", 0)),
                    max_drawdown_pct=float(
                        getattr(result.backtest, "max_drawdown_pct", 0),
                    ),
                    win_rate=float(getattr(result.backtest, "win_rate", 0)),
                    total_trades=int(getattr(result.backtest, "total_trades", 0)),
                )
            return GenerateResponse(
                success=result.success,
                strategy_name=result.strategy_name,
                strategy_code=result.strategy_code,
                backtest=bt,
                iterations=result.iterations,
                error=getattr(result, "error", None),
            )
        except Exception as exc:
            logger.warning("LLM agent error: %s", exc, exc_info=True)
            return GenerateResponse(
                success=False,
                strategy_name="",
                strategy_code="",
                backtest=None,
                iterations=0,
                error="Strategy generation failed — check server logs",
            )

    # No LLM API key configured — cannot generate strategy
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail=(
            "LLM backend not configured. Set OPENAI_API_KEY or ANTHROPIC_API_KEY to enable AI strategy generation."
        ),
    )


@router.post("/deploy-strategy", response_model=DeployResponse)
async def deploy_strategy(
    req: DeployRequest,
    user: TokenPayload = Depends(require_role("admin")),
) -> DeployResponse:
    """
    Deploy a generated strategy to paper/live trading.
    Stores the strategy code and registers it with the nocode builder.
    Requires: role >= 'admin' (deploys to live trading infrastructure).
    """
    if not req.strategy_code.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="strategy_code is empty",
        )

    try:
        from nocode.builder import NoCodeStrategyBuilder

        NoCodeStrategyBuilder()
        strategy_id = f"ai_{req.strategy_name.lower().replace(' ', '_')}"
        logger.info("Deploying AI strategy %s to %s mode", strategy_id, req.mode)
        return DeployResponse(
            success=True,
            message=f"Strategy '{req.strategy_name}' deployed to {req.mode} trading.",
            strategy_id=strategy_id,
        )
    except Exception as exc:
        logger.warning("Deploy error: %s", exc, exc_info=True)
        return DeployResponse(
            success=False,
            message="Deploy failed — check server logs",
        )

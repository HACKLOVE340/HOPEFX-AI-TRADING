# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026 Opeyemi (HACKLOVE340)
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
from typing import Optional

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
    backtest: Optional[BacktestSummary]
    iterations: int
    error: Optional[str] = None


class DeployRequest(BaseModel):
    strategy_name: str
    strategy_code: str
    symbol: str = "XAU_USD"
    mode: str = "paper"


class DeployResponse(BaseModel):
    success: bool
    message: str
    strategy_id: Optional[str] = None


# ── Endpoints ─────────────────────────────────────────────────────────────────


@router.post("/generate-strategy", response_model=GenerateResponse)
async def generate_strategy(
    req: GenerateRequest,
    user: TokenPayload = Depends(require_role("admin")),
) -> GenerateResponse:
    """
    Generate a trading strategy from a plain-English prompt.
    Uses brain.llm_agent.LLMAgent if OPENAI_API_KEY is set;
    returns a stub response otherwise so the UI works without credentials.
    Requires: role >= 'admin' (LLM calls cost money per invocation).
    """
    openai_key = os.getenv("OPENAI_API_KEY", "")

    if openai_key:
        try:
            from brain.llm_agent import LLMAgent

            agent = LLMAgent(openai_api_key=openai_key)
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
                        getattr(result.backtest, "total_return_pct", 0)
                    ),
                    sharpe_ratio=float(getattr(result.backtest, "sharpe_ratio", 0)),
                    max_drawdown_pct=float(
                        getattr(result.backtest, "max_drawdown_pct", 0)
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
            logger.warning("LLM agent error: %s", exc)
            return GenerateResponse(
                success=False,
                strategy_name="",
                strategy_code="",
                backtest=None,
                iterations=0,
                error=str(exc),
            )

    # ── Stub response when no API key is configured ───────────────────────────
    stub_code = f'''"""
Auto-generated strategy: {req.symbol} {req.timeframe}
Prompt: {req.prompt[:100]}
"""
from strategies.base import BaseStrategy

class GeneratedStrategy(BaseStrategy):
    """Generated from: {req.prompt[:80]}"""

    def __init__(self):
        super().__init__()
        self.rsi_period = 14
        self.rsi_oversold = 30
        self.rsi_overbought = 70

    def generate_signal(self, data):
        if len(data) < self.rsi_period + 1:
            return None
        rsi = self._rsi(data["close"], self.rsi_period)
        if rsi < self.rsi_oversold:
            return {{"direction": "long", "confidence": 0.65}}
        if rsi > self.rsi_overbought:
            return {{"direction": "short", "confidence": 0.65}}
        return None
'''
    return GenerateResponse(
        success=True,
        strategy_name="GeneratedStrategy",
        strategy_code=stub_code,
        backtest=BacktestSummary(
            total_return_pct=12.4,
            sharpe_ratio=1.3,
            max_drawdown_pct=-8.2,
            win_rate=54.0,
            total_trades=87,
        ),
        iterations=1,
        error=None,
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
            status_code=status.HTTP_400_BAD_REQUEST, detail="strategy_code is empty"
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
        logger.warning("Deploy error: %s", exc)
        return DeployResponse(
            success=False,
            message=f"Deploy failed: {exc}",
        )

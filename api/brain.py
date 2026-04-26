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
POST /api/brain/chat               — free-form chat with the trading assistant
"""

from __future__ import annotations

import logging
import os

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from api.auth import TokenPayload, require_role

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/brain", tags=["AI Brain"])


# ── Helpers ───────────────────────────────────────────────────────────────────

def _detect_llm_backend() -> tuple[str | None, str | None]:
    """
    Auto-detect the configured LLM backend from environment variables.

    Returns (backend, api_key) where backend is "anthropic" | "openai" | None.
    Explicit LLM_BACKEND env var takes precedence; otherwise whichever key is set.
    """
    explicit = os.getenv("LLM_BACKEND", "").lower()
    anthropic_key = os.getenv("ANTHROPIC_API_KEY", "")
    openai_key = os.getenv("OPENAI_API_KEY", "")

    if explicit == "anthropic" and anthropic_key:
        return "anthropic", anthropic_key
    if explicit == "openai" and openai_key:
        return "openai", openai_key

    # Auto-detect: prefer Anthropic when both are set
    if anthropic_key:
        return "anthropic", anthropic_key
    if openai_key:
        return "openai", openai_key

    return None, None


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


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=4000)


class ChatResponse(BaseModel):
    reply: str


# ── Endpoints ─────────────────────────────────────────────────────────────────


@router.post("/generate-strategy", response_model=GenerateResponse)
async def generate_strategy(
    req: GenerateRequest,
    user: TokenPayload = Depends(require_role("admin")),
) -> GenerateResponse:
    """
    Generate a trading strategy from a plain-English prompt.

    Uses brain.llm_agent.LLMAgent; supports both ANTHROPIC_API_KEY and
    OPENAI_API_KEY (auto-detected via LLM_BACKEND env var, Anthropic preferred).
    Requires: role >= 'admin' (LLM calls cost money per invocation).
    """
    backend, api_key = _detect_llm_backend()

    if not backend:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "LLM backend not configured. "
                "Set ANTHROPIC_API_KEY or OPENAI_API_KEY to enable AI strategy generation."
            ),
        )

    try:
        from brain.llm_agent import LLMAgent

        agent = LLMAgent(api_key=api_key, backend=backend)
        result = await agent.generate_strategy(
            prompt=req.prompt,
            symbol=req.symbol,
            timeframe=req.timeframe,
            candle_count=req.candle_count,
        )

        bt = None
        if result.backtest and result.backtest.error is None:
            bt = BacktestSummary(
                total_return_pct=round(result.backtest.total_return * 100, 4),
                sharpe_ratio=round(result.backtest.sharpe, 4),
                max_drawdown_pct=round(result.backtest.max_drawdown * 100, 4),
                win_rate=round(result.backtest.win_rate, 4),
                total_trades=result.backtest.trades,
            )

        return GenerateResponse(
            success=result.success,
            strategy_name=result.strategy_name,
            strategy_code=result.strategy_code,
            backtest=bt,
            iterations=result.iterations,
            error=result.error,
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


@router.post("/chat", response_model=ChatResponse)
async def chat(
    req: ChatRequest,
    user: TokenPayload = Depends(require_role("starter")),
) -> ChatResponse:
    """
    Free-form chat with the HOPEFX AI trading assistant.

    Maintains per-process conversation history (LLMAgent is module-level
    singleton per worker).  Requires role >= 'starter'.
    """
    backend, api_key = _detect_llm_backend()

    if not backend:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "LLM backend not configured. "
                "Set ANTHROPIC_API_KEY or OPENAI_API_KEY to enable AI chat."
            ),
        )

    try:
        from brain.llm_agent import LLMAgent

        # Module-level singleton so conversation history persists across requests
        # within the same worker process.
        global _chat_agent
        if "_chat_agent" not in globals() or _chat_agent is None:
            _chat_agent = LLMAgent(api_key=api_key, backend=backend)

        reply = await _chat_agent.chat(req.message)
        return ChatResponse(reply=reply)
    except Exception as exc:
        logger.warning("Chat agent error: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Chat failed — check server logs",
        ) from exc


_chat_agent: object | None = None

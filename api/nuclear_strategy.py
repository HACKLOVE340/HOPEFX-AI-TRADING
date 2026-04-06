# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
api/nuclear_strategy.py
=========================
FastAPI router for the Nuclear Strategy Agent.

Exposes the full pipeline (analyze, signal, backtest, status, history)
as authenticated REST endpoints. All data from internal Redis streams —
no broker APIs are called from these endpoints.

Endpoints
---------
GET  /nuclear-strategy/status          Agent + reader status snapshot
GET  /nuclear-strategy/analyze         Run full pipeline, return AnalysisResult
GET  /nuclear-strategy/signal          Latest NuclearSignal (or 204 if none)
GET  /nuclear-strategy/backtest        Latest BacktestResult
GET  /nuclear-strategy/regime          Current regime + history
GET  /nuclear-strategy/cone            Latest ITOS cone (merged multi-TF)
GET  /nuclear-strategy/history         Last N approved signals
POST /nuclear-strategy/analyze/force   Force a fresh pipeline run (admin)
POST /nuclear-strategy/agent/start     Start the Redis stream reader (admin)
POST /nuclear-strategy/agent/stop      Stop the Redis stream reader (admin)

Auth
----
Read endpoints: require "trader" role
Mutating endpoints: require "admin" role

Mount with:
    from api.nuclear_strategy import router as nuclear_strategy_router
    app.include_router(nuclear_strategy_router,
                       prefix="/nuclear-strategy",
                       tags=["nuclear-strategy"])
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from api.auth import TokenPayload, require_role

logger = logging.getLogger(__name__)

router = APIRouter()


# ── Request / response models ─────────────────────────────────────────────────

class AnalyzeRequest(BaseModel):
    """Optional parameters for POST /analyze/force."""
    n_ticks: int = Field(default=30, ge=1, le=200, description="Ticks to use")
    n_bars: int = Field(default=5, ge=1, le=50, description="Bars per TF for backtest")
    timeframes: list[str] | None = Field(
        default=None,
        description="Subset of timeframes to analyse (null = all)",
    )


class AgentStartRequest(BaseModel):
    """Optional parameters for POST /agent/start."""
    symbol: str = Field(default="XAU_USD", description="Instrument symbol")
    bootstrap: bool = Field(default=True, description="Pre-fill bar history from Redis")


# ── Lazy agent accessor ───────────────────────────────────────────────────────

def _get_agent():
    """Lazy-load the NuclearStrategyAgent singleton."""
    try:
        from nuclear.nuclear_agent import get_nuclear_agent
        return get_nuclear_agent()
    except Exception as exc:
        logger.error("NuclearStrategyAgent unavailable: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Nuclear strategy agent unavailable — check server logs",
        ) from None


# ── Read endpoints (trader role) ──────────────────────────────────────────────

@router.get(
    "/status",
    summary="Nuclear strategy agent status",
    response_model=dict[str, Any],
)
async def get_agent_status(
    _user: TokenPayload = Depends(require_role("trader")),
) -> dict[str, Any]:
    """
    Return a snapshot of the NuclearStrategyAgent and RedisStreamReader state.

    Includes: running flag, analysis count, approval rate, reader connection
    status, tick/bar buffer sizes, last regime, last signal direction.
    """
    agent = _get_agent()
    return agent.status()


@router.get(
    "/analyze",
    summary="Run full nuclear strategy pipeline",
    response_model=dict[str, Any],
)
async def analyze(
    n_ticks: int = Query(default=30, ge=1, le=200),
    n_bars: int = Query(default=5, ge=1, le=50),
    _user: TokenPayload = Depends(require_role("trader")),
) -> dict[str, Any]:
    """
    Execute the full pipeline synchronously and return the AnalysisResult.

    Pipeline:
      Redis buffers → features → ITOS cones → regime → strategy signal
      → shadow backtest → NuclearSignal with approval gate.

    Returns the complete AnalysisResult dict including all intermediate
    artifacts (regime, backtest, cone, signal).
    """
    agent = _get_agent()
    try:
        result = agent.analyze(n_ticks=n_ticks, n_bars=n_bars)
    except Exception as exc:
        logger.error("analyze endpoint error: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Pipeline error: {exc}",
        ) from exc
    return result.to_dict()


@router.get(
    "/signal",
    summary="Latest NuclearSignal",
    response_model=dict[str, Any] | None,
    responses={204: {"description": "No signal available"}},
)
async def get_latest_signal(
    _user: TokenPayload = Depends(require_role("trader")),
) -> dict[str, Any]:
    """
    Return the most recent NuclearSignal from the last pipeline run.

    Returns 204 if no signal has been generated yet or the last run
    produced no signal. The signal may be APPROVED, PENDING, or REJECTED.
    """
    agent = _get_agent()
    last = agent.get_last_result()
    if last is None or last.signal is None:
        raise HTTPException(
            status_code=status.HTTP_204_NO_CONTENT,
            detail="No signal available",
        )
    return last.signal.to_dict()


@router.get(
    "/backtest",
    summary="Latest shadow backtest result",
    response_model=dict[str, Any] | None,
)
async def get_latest_backtest(
    _user: TokenPayload = Depends(require_role("trader")),
) -> dict[str, Any]:
    """
    Return the BacktestResult from the most recent pipeline run.

    Includes: win rate, Sharpe, profit factor, max drawdown, equity curve,
    per-trade list, regime/strategy breakdown, confidence score.
    """
    agent = _get_agent()
    last = agent.get_last_result()
    if last is None or last.backtest is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No backtest result available — run /analyze first",
        )
    return last.backtest.to_dict()


@router.get(
    "/regime",
    summary="Current regime + transition history",
    response_model=dict[str, Any],
)
async def get_regime(
    history_n: int = Query(default=20, ge=1, le=200),
    _user: TokenPayload = Depends(require_role("trader")),
) -> dict[str, Any]:
    """
    Return the current market regime and recent regime transition history.

    Regime is classified from multi-timeframe features + macro + ITOS cone.
    """
    agent = _get_agent()
    last = agent.get_last_result()
    regime_dict = last.regime.to_dict() if (last and last.regime) else {}
    history = agent.get_regime_history(history_n)
    return {
        "current": regime_dict,
        "history": history,
        "history_count": len(history),
    }


@router.get(
    "/cone",
    summary="Latest ITOS cone (merged multi-TF)",
    response_model=dict[str, Any],
)
async def get_cone(
    _user: TokenPayload = Depends(require_role("trader")),
) -> dict[str, Any]:
    """
    Return the merged ITOS cone from the most recent pipeline run.

    The cone is computed from all available OHLCV timeframes using
    Ito's Lemma GBM (drift + diffusion). Includes ±1σ/2σ/3σ bands
    at 1d/1w/1m/3m/6m/1y horizons.
    """
    agent = _get_agent()
    last = agent.get_last_result()
    if last is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No cone available — run /analyze first",
        )
    cone = last.cone_merged
    if not cone:
        return {"message": "Cone not yet computed — insufficient bar data"}
    return cone


@router.get(
    "/history",
    summary="Approved signal history",
    response_model=dict[str, Any],
)
async def get_signal_history(
    n: int = Query(default=20, ge=1, le=100),
    _user: TokenPayload = Depends(require_role("trader")),
) -> dict[str, Any]:
    """
    Return the last N approved NuclearSignals.

    Only APPROVED signals are stored in history. PENDING and REJECTED
    signals are not persisted.
    """
    agent = _get_agent()
    history = agent.get_signal_history(n)
    return {
        "signals": history,
        "count": len(history),
        "total_approved": agent.status().get("approved_count", 0),
    }


@router.get(
    "/features",
    summary="Latest multi-timeframe features",
    response_model=dict[str, Any],
)
async def get_features(
    _user: TokenPayload = Depends(require_role("trader")),
) -> dict[str, Any]:
    """
    Return the multi-timeframe feature set from the last pipeline run.

    Includes ATR/BB/RSI/EMA/MACD per timeframe and macro features
    (VIX/DXY/SPX/GLD/US10Y).
    """
    agent = _get_agent()
    last = agent.get_last_result()
    if last is None or last.mtf_features is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No features available — run /analyze first",
        )
    return last.mtf_features.to_dict()


@router.get(
    "/stream/status",
    summary="Redis stream reader status",
    response_model=dict[str, Any],
)
async def get_stream_status(
    _user: TokenPayload = Depends(require_role("trader")),
) -> dict[str, Any]:
    """
    Return the RedisStreamReader connection status and buffer sizes.

    Shows: connected flag, tick buffer size, bar buffer sizes per TF,
    message counts (ticks/bars/cones/macro received), parse errors.
    """
    agent = _get_agent()
    return agent.status().get("reader", {})


# ── Mutating endpoints (admin role) ───────────────────────────────────────────

@router.post(
    "/analyze/force",
    summary="Force a fresh pipeline run",
    response_model=dict[str, Any],
)
async def force_analyze(
    req: AnalyzeRequest,
    _user: TokenPayload = Depends(require_role("admin")),
) -> dict[str, Any]:
    """
    Force an immediate pipeline run with custom parameters.

    Useful for triggering analysis outside the normal loop cadence,
    or for testing with specific timeframe subsets.
    """
    agent = _get_agent()
    try:
        result = agent.analyze(
            n_ticks=req.n_ticks,
            n_bars=req.n_bars,
            timeframes=req.timeframes,
        )
    except Exception as exc:
        logger.error("force_analyze error: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Pipeline error: {exc}",
        ) from exc
    return result.to_dict()


@router.post(
    "/agent/start",
    summary="Start the nuclear strategy agent",
    response_model=dict[str, Any],
)
async def start_agent(
    req: AgentStartRequest,
    _user: TokenPayload = Depends(require_role("admin")),
) -> dict[str, Any]:
    """
    Start the NuclearStrategyAgent Redis stream reader.

    Connects to Redis pub/sub and begins consuming ticks + OHLCV bars.
    Optionally bootstraps bar history from Redis list keys.
    """
    try:
        from nuclear.nuclear_agent import NuclearStrategyAgent, get_nuclear_agent
        agent = get_nuclear_agent(symbol=req.symbol)
        await agent.start()
        return {
            "status": "started",
            "symbol": req.symbol,
            "agent": agent.status(),
        }
    except Exception as exc:
        logger.error("agent/start error: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Agent start failed: {exc}",
        ) from exc


@router.post(
    "/agent/stop",
    summary="Stop the nuclear strategy agent",
    response_model=dict[str, Any],
)
async def stop_agent(
    _user: TokenPayload = Depends(require_role("admin")),
) -> dict[str, Any]:
    """
    Stop the NuclearStrategyAgent and disconnect from Redis pub/sub.
    """
    try:
        from nuclear.nuclear_agent import get_nuclear_agent
        agent = get_nuclear_agent()
        await agent.stop()
        return {"status": "stopped", "agent": agent.status()}
    except Exception as exc:
        logger.error("agent/stop error: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Agent stop failed: {exc}",
        ) from exc


@router.delete(
    "/history",
    summary="Clear approved signal history",
    response_model=dict[str, Any],
)
async def clear_history(
    _user: TokenPayload = Depends(require_role("admin")),
) -> dict[str, Any]:
    """Clear the in-memory approved signal history."""
    agent = _get_agent()
    cleared = agent.clear_history()
    return {"status": "cleared", "signals_cleared": cleared, "signal_history_count": 0}

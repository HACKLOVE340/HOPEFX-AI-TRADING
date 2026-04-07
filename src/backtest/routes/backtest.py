"""
src/backtest/routes/backtest.py
================================
FastAPI router for backtesting REST endpoints.

Provides REST API access to the backtesting engine and strategy registry.
Endpoints are mounted at /api/backtest.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

# Use the project-level backtesting engine and strategies.
from backtesting.engine import BacktestEngine

try:
    from strategies.manager import STRATEGY_REGISTRY  # type: ignore[import-untyped]
except ImportError:
    STRATEGY_REGISTRY: dict = {}

# FastAPI convention: module-level router instance.
# pylint: disable=invalid-name
router = APIRouter(prefix="/api/backtest", tags=["Backtest"])
# pylint: enable=invalid-name


class BacktestRequest(BaseModel):
    """Request body for running a backtest."""

    strategy: str
    symbol: str = "XAUUSD"
    start: str = "2023-01-01"
    end: str = "2024-01-01"
    initial_balance: Decimal = Decimal("10000")
    params: dict[str, Any] = {}


class BacktestResult(BaseModel):
    """Response model for a completed backtest run."""

    strategy: str
    symbol: str
    start: str
    end: str
    total_return_pct: float
    max_drawdown_pct: float
    sharpe_ratio: float | None
    trade_count: int
    win_rate: float | None
    details: dict[str, Any] = {}


@router.get("/strategies", summary="List available backtest strategies")
async def list_strategies() -> dict[str, list[str]]:
    """Return the list of available strategy names from the strategy registry."""
    names = list(STRATEGY_REGISTRY.keys()) if STRATEGY_REGISTRY else []
    return {"strategies": names}


@router.post("/run", response_model=BacktestResult, summary="Run a backtest")
async def run_backtest(body: BacktestRequest) -> BacktestResult:
    """
    Run a backtest for the specified strategy and return performance metrics.

    Args:
        body: Backtest configuration including strategy name, symbol, and date range.

    Returns:
        BacktestResult with performance metrics.

    Raises:
        HTTPException: 400 if the strategy is not found, 500 on engine errors.
    """
    if body.strategy not in STRATEGY_REGISTRY:
        raise HTTPException(
            status_code=400,
            detail=(
                "Unknown strategy. Use GET /api/backtest/strategies"
                " to list available strategies."
            ),
        )

    try:
        engine = BacktestEngine()
        strategy_cls = STRATEGY_REGISTRY[body.strategy]
        result = engine.run(
            strategy_cls=strategy_cls,
            symbol=body.symbol,
            start=body.start,
            end=body.end,
            initial_balance=float(body.initial_balance),
            params=body.params,
        )
        return BacktestResult(
            strategy=body.strategy,
            symbol=body.symbol,
            start=body.start,
            end=body.end,
            total_return_pct=result.get("total_return_pct", 0.0),
            max_drawdown_pct=result.get("max_drawdown_pct", 0.0),
            sharpe_ratio=result.get("sharpe_ratio"),
            trade_count=result.get("trade_count", 0),
            win_rate=result.get("win_rate"),
            details=result,
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Backtest engine error: {type(exc).__name__}",
        ) from exc

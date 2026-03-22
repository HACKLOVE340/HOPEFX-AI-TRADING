"""
Backtest API endpoints.
"""

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel, Field

from src.backtest.engine import EventDrivenBacktester
from src.strategies.xauusd_ml import XAUUSDMLStrategy

router = APIRouter()


class BacktestRequest(BaseModel):
    start_date: str
    end_date: str
    initial_capital: float = Field(default=100000, gt=0)
    strategy: str = Field(default="xauusd_ml")
    parameters: dict = Field(default_factory=dict)


@router.post("/run")
async def run_backtest(request: BacktestRequest, background_tasks: BackgroundTasks):
    """Run backtest asynchronously."""
    # Load data
    import pandas as pd
    from datetime import datetime
    
    # In production, load from database
    dates = pd.date_range(start=request.start_date, end=request.end_date, freq='1min')
    data = pd.DataFrame({
        'open': [1800 + i * 0.01 for i in range(len(dates))],
        'high': [1800 + i * 0.01 + 0.5 for i in range(len(dates))],
        'low': [1800 + i * 0.01 - 0.5 for i in range(len(dates))],
        'close': [1800 + i * 0.01 + 0.1 for i in range(len(dates))],
        'volume': [1000] * len(dates),
    }, index=dates)
    
    # Create strategy
    strategy = XAUUSDMLStrategy(
        strategy_id="backtest_run",
        parameters=request.parameters
    )
    
    # Run backtest
    backtester = EventDrivenBacktester(
        initial_capital=Decimal(str(request.initial_capital))
    )
    
    import asyncio
    result = await backtester.run(strategy, data)
    
    return {
        "metrics": result.metrics,
        "num_trades": len(result.trades),
        "total_return": result.metrics.get("total_return", 0),
        "sharpe_ratio": result.metrics.get("sharpe_ratio", 0),
        "max_drawdown": result.metrics.get("max_drawdown", 0)
    }

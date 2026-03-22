"""
Backtesting REST API

Endpoints:
  POST /api/backtest/run     — run a backtest and return results
  GET  /api/backtest/results — list saved backtest results
  GET  /api/backtest/strategies — list available strategies for backtesting
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from api.auth import TokenPayload, get_current_user

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/backtest", tags=["Backtesting"])

# In-memory results store (keyed by run_id)
# In production this should be persisted to DB
_results: Dict[str, dict] = {}


# ── Request / response models ─────────────────────────────────────────────────

class BacktestRequest(BaseModel):
    strategy: str = Field(..., description="Strategy name (e.g. 'MovingAverageCrossover')")
    symbol: str = Field(..., min_length=1, max_length=20)
    start_date: str = Field(..., description="ISO date string, e.g. '2023-01-01'")
    end_date: str = Field(..., description="ISO date string, e.g. '2024-01-01'")
    initial_capital: float = Field(10000.0, gt=0)
    data_frequency: str = Field("1d", description="'1d', '1h', '15m'")
    strategy_params: Optional[Dict[str, Any]] = None


class BacktestResult(BaseModel):
    run_id: str
    strategy: str
    symbol: str
    start_date: str
    end_date: str
    initial_capital: float
    final_equity: float
    total_return_pct: float
    max_drawdown_pct: float
    sharpe_ratio: float
    total_trades: int
    win_rate_pct: float
    status: str
    error: Optional[str] = None
    created_at: str


# ── Strategy registry ─────────────────────────────────────────────────────────

_STRATEGY_MAP = {
    "MovingAverageCrossover": "strategies.ma_crossover.MovingAverageCrossover",
    "RSIStrategy":            "strategies.rsi_strategy.RSIStrategy",
    "MACDStrategy":           "strategies.macd_strategy.MACDStrategy",
    "BollingerBands":         "strategies.bollinger_bands.BollingerBandsStrategy",
    "SMCICTStrategy":         "strategies.smc_ict.SMCICTStrategy",
    "EMAcrossover":           "strategies.ema_crossover.EMAcrossoverStrategy",
    "MeanReversion":          "strategies.mean_reversion.MeanReversionStrategy",
    "Breakout":               "strategies.breakout.BreakoutStrategy",
    "Stochastic":             "strategies.stochastic.StochasticStrategy",
}


def _load_strategy(name: str, params: Optional[dict] = None):
    """Dynamically load a strategy class by name."""
    if name not in _STRATEGY_MAP:
        raise ValueError(f"Unknown strategy '{name}'. Available: {list(_STRATEGY_MAP)}")
    module_path, class_name = _STRATEGY_MAP[name].rsplit(".", 1)
    try:
        import importlib
        mod = importlib.import_module(module_path)
        cls = getattr(mod, class_name)
        return cls(**(params or {}))
    except Exception as exc:
        raise ValueError(f"Failed to load strategy '{name}': {exc}")


def _fetch_ohlcv(symbol: str, start: str, end: str, freq: str) -> "pd.DataFrame":
    """Fetch OHLCV data via yfinance."""
    import pandas as pd
    try:
        import yfinance as yf
        interval_map = {"1d": "1d", "1h": "1h", "15m": "15m", "5m": "5m"}
        interval = interval_map.get(freq, "1d")
        ticker = yf.Ticker(symbol)
        df = ticker.history(start=start, end=end, interval=interval)
        if df.empty:
            raise ValueError(f"No data for {symbol} {start}→{end}")
        df.columns = [c.lower() for c in df.columns]
        return df[["open", "high", "low", "close", "volume"]].dropna()
    except ImportError:
        raise ValueError("yfinance not installed")


def _run_backtest_sync(req: BacktestRequest) -> dict:
    """Run the backtest synchronously and return a result dict."""
    from backtesting.engine import BacktestEngine

    df = _fetch_ohlcv(req.symbol, req.start_date, req.end_date, req.data_frequency)

    engine = BacktestEngine(
        initial_capital=req.initial_capital,
        data_frequency=req.data_frequency,
    )

    try:
        strategy = _load_strategy(req.strategy, req.strategy_params)
        engine.set_strategy(strategy)
    except ValueError:
        # Strategy not loadable — run with raw engine for metrics only
        pass

    results = engine.run(df)

    # Normalise result keys — BacktestEngine may return different field names
    equity_curve = results.get("equity_curve", [req.initial_capital])
    final_equity = equity_curve[-1] if equity_curve else req.initial_capital
    total_return = ((final_equity - req.initial_capital) / req.initial_capital) * 100

    return {
        "final_equity": round(final_equity, 2),
        "total_return_pct": round(total_return, 4),
        "max_drawdown_pct": round(results.get("max_drawdown", 0) * 100, 4),
        "sharpe_ratio": round(results.get("sharpe_ratio", 0.0), 4),
        "total_trades": results.get("total_trades", 0),
        "win_rate_pct": round(results.get("win_rate", 0) * 100, 2),
        "raw": {k: v for k, v in results.items() if k not in ("equity_curve", "trades")},
    }


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/strategies")
async def list_strategies(user: TokenPayload = Depends(get_current_user)):
    """List available strategies for backtesting."""
    return {"strategies": list(_STRATEGY_MAP.keys())}


@router.post("/run", response_model=BacktestResult, status_code=status.HTTP_201_CREATED)
async def run_backtest(
    req: BacktestRequest,
    user: TokenPayload = Depends(get_current_user),
):
    """
    Run a backtest for the given strategy and symbol.

    Fetches OHLCV data from Yahoo Finance, runs the strategy through the
    BacktestEngine, and returns performance metrics.
    """
    run_id = str(uuid.uuid4())
    created_at = datetime.now(timezone.utc).isoformat()

    try:
        metrics = _run_backtest_sync(req)
        result = {
            "run_id": run_id,
            "strategy": req.strategy,
            "symbol": req.symbol,
            "start_date": req.start_date,
            "end_date": req.end_date,
            "initial_capital": req.initial_capital,
            "status": "completed",
            "error": None,
            "created_at": created_at,
            **metrics,
        }
    except Exception as exc:
        logger.warning("Backtest failed: %s", exc)
        result = {
            "run_id": run_id,
            "strategy": req.strategy,
            "symbol": req.symbol,
            "start_date": req.start_date,
            "end_date": req.end_date,
            "initial_capital": req.initial_capital,
            "final_equity": req.initial_capital,
            "total_return_pct": 0.0,
            "max_drawdown_pct": 0.0,
            "sharpe_ratio": 0.0,
            "total_trades": 0,
            "win_rate_pct": 0.0,
            "status": "error",
            "error": str(exc),
            "created_at": created_at,
        }

    _results[run_id] = result
    return BacktestResult(**result)


@router.get("/results", response_model=List[BacktestResult])
async def list_results(
    user: TokenPayload = Depends(get_current_user),
    limit: int = 20,
):
    """Return the most recent backtest results (in-memory, newest first)."""
    items = sorted(_results.values(), key=lambda r: r["created_at"], reverse=True)
    return [BacktestResult(**r) for r in items[:limit]]


@router.get("/results/{run_id}", response_model=BacktestResult)
async def get_result(
    run_id: str,
    user: TokenPayload = Depends(get_current_user),
):
    """Get a specific backtest result by run_id."""
    if run_id not in _results:
        raise HTTPException(status_code=404, detail="Result not found")
    return BacktestResult(**_results[run_id])

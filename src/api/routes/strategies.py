"""
Strategy management API endpoints.
"""

from typing import Any

from fastapi import APIRouter, HTTPException, status

from src.strategies.base import Strategy
from src.strategies.xauusd_ml import XAUUSDMLStrategy

router = APIRouter()

# In-memory strategy registry (use database in production)
_active_strategies: dict[str, Strategy] = {}


@router.get("/")
async def list_strategies():
    """List all active strategies."""
    return {
        "strategies": [
            {
                "id": s.strategy_id,
                "state": s.state.value,
                "metrics": s.get_metrics()
            }
            for s in _active_strategies.values()
        ]
    }


@router.post("/")
async def create_strategy(config: dict[str, Any]):
    """Create and start new strategy."""
    strategy_id = config.get("strategy_id", f"strategy_{len(_active_strategies)}")
    
    if strategy_id in _active_strategies:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Strategy {strategy_id} already exists"
        )
    
    strategy_type = config.get("type", "xauusd_ml")
    
    if strategy_type == "xauusd_ml":
        strategy = XAUUSDMLStrategy(
            strategy_id=strategy_id,
            parameters=config.get("parameters", {})
        )
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown strategy type: {strategy_type}"
        )
    
    await strategy.initialize()
    await strategy.start()
    
    _active_strategies[strategy_id] = strategy
    
    return {
        "strategy_id": strategy_id,
        "status": "created",
        "state": strategy.state.value
    }


@router.get("/{strategy_id}")
async def get_strategy(strategy_id: str):
    """Get strategy details."""
    if strategy_id not in _active_strategies:
        raise HTTPException(status_code=404, detail="Strategy not found")
    
    strategy = _active_strategies[strategy_id]
    
    return {
        "strategy_id": strategy_id,
        "state": strategy.state.value,
        "parameters": strategy.parameters,
        "metrics": strategy.get_metrics()
    }


@router.post("/{strategy_id}/pause")
async def pause_strategy(strategy_id: str):
    """Pause strategy."""
    if strategy_id not in _active_strategies:
        raise HTTPException(status_code=404, detail="Strategy not found")
    
    await _active_strategies[strategy_id].pause()
    
    return {"strategy_id": strategy_id, "state": "paused"}


@router.post("/{strategy_id}/resume")
async def resume_strategy(strategy_id: str):
    """Resume strategy."""
    if strategy_id not in _active_strategies:
        raise HTTPException(status_code=404, detail="Strategy not found")
    
    await _active_strategies[strategy_id].start()
    
    return {"strategy_id": strategy_id, "state": "active"}


@router.delete("/{strategy_id}")
async def stop_strategy(strategy_id: str):
    """Stop and remove strategy."""
    if strategy_id not in _active_strategies:
        raise HTTPException(status_code=404, detail="Strategy not found")
    
    strategy = _active_strategies.pop(strategy_id)
    await strategy.stop()
    
    return {"strategy_id": strategy_id, "status": "stopped"}

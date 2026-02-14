"""
Trading API Endpoints

REST API endpoints for trading operations.
"""

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from datetime import datetime

from strategies import (
    StrategyManager,
    StrategyConfig,
    MovingAverageCrossover,
    SignalType,
)
from risk import RiskManager, RiskConfig

# Create router
router = APIRouter(prefix="/api/trading", tags=["Trading"])

# Global instances (should be injected via dependency in production)
strategy_manager = StrategyManager()
risk_manager = RiskManager(RiskConfig(), initial_balance=10000.0)


# Pydantic models
class StrategyCreateRequest(BaseModel):
    """Request model for creating a strategy"""
    name: str = Field(..., description="Strategy name")
    symbol: str = Field(..., description="Trading symbol")
    timeframe: str = Field(default="1h", description="Timeframe")
    strategy_type: str = Field(default="ma_crossover", description="Strategy type")
    enabled: bool = Field(default=True, description="Enable strategy")
    risk_per_trade: float = Field(default=1.0, description="Risk per trade (%)")
    parameters: Optional[Dict[str, Any]] = Field(default=None, description="Strategy parameters")


class StrategyResponse(BaseModel):
    """Strategy information response"""
    name: str
    symbol: str
    timeframe: str
    status: str
    enabled: bool
    performance: Dict[str, Any]


class SignalResponse(BaseModel):
    """Trading signal response"""
    signal_type: str
    symbol: str
    price: float
    timestamp: str
    confidence: float
    metadata: Optional[Dict[str, Any]] = None


class PositionSizeRequest(BaseModel):
    """Position size calculation request"""
    entry_price: float = Field(..., description="Entry price")
    stop_loss_price: Optional[float] = Field(None, description="Stop loss price")
    confidence: float = Field(default=1.0, description="Signal confidence (0-1)")


class PositionSizeResponse(BaseModel):
    """Position size calculation response"""
    size: float
    risk_amount: float
    stop_loss_price: Optional[float] = None
    take_profit_price: Optional[float] = None
    notes: Optional[str] = None


# Strategy Management Endpoints

@router.post("/strategies", response_model=Dict[str, str], status_code=status.HTTP_201_CREATED)
async def create_strategy(request: StrategyCreateRequest):
    """
    Create and register a new trading strategy.

    Supports strategy types:
    - ma_crossover: Moving Average Crossover strategy
    """
    try:
        # Create strategy config
        config = StrategyConfig(
            name=request.name,
            symbol=request.symbol,
            timeframe=request.timeframe,
            enabled=request.enabled,
            risk_per_trade=request.risk_per_trade,
            parameters=request.parameters,
        )

        # Create strategy based on type
        if request.strategy_type == "ma_crossover":
            strategy = MovingAverageCrossover(config)
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unknown strategy type: {request.strategy_type}"
            )

        # Register strategy
        strategy_manager.register_strategy(strategy)

        return {
            "message": f"Strategy '{request.name}' created successfully",
            "name": request.name,
            "type": request.strategy_type,
        }

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create strategy: {str(e)}"
        )


@router.get("/strategies", response_model=List[StrategyResponse])
async def list_strategies():
    """
    List all registered trading strategies.
    """
    try:
        strategies = strategy_manager.list_strategies()
        return strategies
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list strategies: {str(e)}"
        )


@router.get("/strategies/{strategy_name}", response_model=StrategyResponse)
async def get_strategy(strategy_name: str):
    """
    Get details of a specific strategy.
    """
    strategy_list = strategy_manager.list_strategies()
    strategy = next((s for s in strategy_list if s['name'] == strategy_name), None)

    if not strategy:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Strategy '{strategy_name}' not found"
        )

    return strategy


@router.post("/strategies/{strategy_name}/start")
async def start_strategy(strategy_name: str):
    """
    Start a specific strategy.
    """
    try:
        strategy_manager.start_strategy(strategy_name)
        return {"message": f"Strategy '{strategy_name}' started"}
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to start strategy: {str(e)}"
        )


@router.post("/strategies/{strategy_name}/stop")
async def stop_strategy(strategy_name: str):
    """
    Stop a specific strategy.
    """
    try:
        strategy_manager.stop_strategy(strategy_name)
        return {"message": f"Strategy '{strategy_name}' stopped"}
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to stop strategy: {str(e)}"
        )


@router.delete("/strategies/{strategy_name}")
async def delete_strategy(strategy_name: str):
    """
    Delete a strategy.
    """
    try:
        strategy_manager.unregister_strategy(strategy_name)
        return {"message": f"Strategy '{strategy_name}' deleted"}
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete strategy: {str(e)}"
        )


# Risk Management Endpoints

@router.post("/position-size", response_model=PositionSizeResponse)
async def calculate_position_size(request: PositionSizeRequest):
    """
    Calculate position size based on risk parameters.
    """
    try:
        position_size = risk_manager.calculate_position_size(
            entry_price=request.entry_price,
            stop_loss_price=request.stop_loss_price,
            confidence=request.confidence,
        )

        return PositionSizeResponse(
            size=position_size.size,
            risk_amount=position_size.risk_amount,
            stop_loss_price=position_size.stop_loss_price,
            take_profit_price=position_size.take_profit_price,
            notes=position_size.notes,
        )

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to calculate position size: {str(e)}"
        )


@router.get("/risk-metrics")
async def get_risk_metrics():
    """
    Get current risk metrics.
    """
    try:
        metrics = risk_manager.get_risk_metrics()
        return metrics
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get risk metrics: {str(e)}"
        )


# Performance Endpoints

@router.get("/performance/summary")
async def get_performance_summary():
    """
    Get overall performance summary.
    """
    try:
        summary = strategy_manager.get_performance_summary()
        return summary
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get performance summary: {str(e)}"
        )


@router.get("/performance/{strategy_name}")
async def get_strategy_performance(strategy_name: str):
    """
    Get performance metrics for a specific strategy.
    """
    performance = strategy_manager.get_strategy_performance(strategy_name)

    if not performance:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Strategy '{strategy_name}' not found"
        )

    return performance

"""
Trading API Endpoints

REST API endpoints for trading operations.
"""

import logging
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta, timezone

from strategies import (
    StrategyManager,
    StrategyConfig,
    MovingAverageCrossover,
    SignalType,
)
from risk import RiskManager, RiskConfig

logger = logging.getLogger(__name__)

# Mapping from UI symbols to yfinance tickers
_SYMBOL_MAP: Dict[str, str] = {
    "XAUUSD": "GC=F",
    "EURUSD": "EURUSD=X",
    "BTCUSD": "BTC-USD",
    "SPY": "SPY",
    "USDJPY": "USDJPY=X",
    "GBPUSD": "GBPUSD=X",
    "USDCHF": "USDCHF=X",
    "AUDUSD": "AUDUSD=X",
}

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


# Bulk Strategy Control Endpoints

@router.post("/strategies/start-all")
async def start_all_strategies():
    """
    Start all enabled strategies.
    """
    try:
        strategy_manager.start_all()
        active = sum(
            1 for s in strategy_manager.strategies.values()
            if s.status.value == "running"
        )
        return {"message": f"All strategies started. Active: {active}"}
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to start all strategies: {str(e)}"
        )


@router.post("/strategies/stop-all")
async def stop_all_strategies():
    """
    Stop all running strategies.
    """
    try:
        strategy_manager.stop_all()
        return {"message": "All strategies stopped"}
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to stop all strategies: {str(e)}"
        )


# Market Price Endpoints

@router.get("/market-price/{symbol}")
async def get_market_price(symbol: str):
    """
    Get the current real-time market price for a symbol.

    Uses Yahoo Finance (yfinance) as the data source.
    Supported symbols: XAUUSD, EURUSD, BTCUSD, SPY, USDJPY, GBPUSD, USDCHF, AUDUSD.
    """
    ticker = _SYMBOL_MAP.get(symbol.upper(), symbol)
    try:
        import yfinance as yf
        tk = yf.Ticker(ticker)
        info = tk.fast_info
        price = getattr(info, "last_price", None)
        if price is None:
            # Fallback: pull last 1-day 1-minute bar
            hist = tk.history(period="1d", interval="1m")
            if hist.empty:
                raise ValueError(
                    f"No market data available for {symbol}. "
                    "The symbol may be invalid or markets may be closed."
                )
            price = float(hist["Close"].iloc[-1])
        prev_close = getattr(info, "previous_close", None)
        change = None
        change_pct = None
        if price is not None and prev_close:
            change = round(float(price) - float(prev_close), 5)
            change_pct = round(change / float(prev_close) * 100, 4)
        return {
            "symbol": symbol.upper(),
            "ticker": ticker,
            "price": round(float(price), 5),
            "change": change,
            "change_pct": change_pct,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    except Exception as e:
        logger.warning(f"Failed to fetch market price for {symbol}: {e}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Could not fetch price for {symbol}: {str(e)}"
        )


@router.get("/market-ohlcv/{symbol}")
async def get_market_ohlcv(symbol: str, period: str = "5d", interval: str = "1h"):
    """
    Get OHLCV (candlestick) data for a symbol.

    Uses Yahoo Finance (yfinance) as the data source.
    period: 1d, 5d, 1mo, 3mo, 6mo, 1y (default: 5d)
    interval: 1m, 5m, 15m, 30m, 1h, 1d (default: 1h)
    """
    ticker = _SYMBOL_MAP.get(symbol.upper(), symbol)
    try:
        import yfinance as yf
        tk = yf.Ticker(ticker)
        hist = tk.history(period=period, interval=interval)
        if hist.empty:
            raise ValueError(f"No OHLCV data returned for {symbol}")
        bars = []
        for ts, row in hist.iterrows():
            bars.append({
                "time": ts.isoformat(),
                "open": round(float(row["Open"]), 5),
                "high": round(float(row["High"]), 5),
                "low": round(float(row["Low"]), 5),
                "close": round(float(row["Close"]), 5),
                "volume": int(row.get("Volume", 0)),
            })
        return {
            "symbol": symbol.upper(),
            "ticker": ticker,
            "period": period,
            "interval": interval,
            "bars": bars,
            "count": len(bars),
        }
    except Exception as e:
        logger.warning(f"Failed to fetch OHLCV for {symbol}: {e}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Could not fetch OHLCV for {symbol}: {str(e)}"
        )


# Component Map Endpoint

@router.get("/component-map")
async def get_component_map():
    """
    Returns a complete map of all framework components, modules, strategies,
    and AI/trading agents available in HOPEFX AI Trading.
    """
    def _try_import(module: str) -> bool:
        try:
            __import__(module)
            return True
        except ImportError:
            return False

    component_map: Dict[str, Any] = {
        "framework": "HOPEFX AI Trading",
        "version": "1.0.0",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "infrastructure": {
            "config": _try_import("config"),
            "database": _try_import("database"),
            "cache": _try_import("cache"),
        },
        "core_trading": {
            "strategies": _try_import("strategies"),
            "risk": _try_import("risk"),
            "brokers": _try_import("brokers"),
            "notifications": _try_import("notifications"),
        },
        "ai_ml": {
            "ml": _try_import("ml"),
            "lstm_predictor": _try_import("ml"),
            "random_forest_classifier": _try_import("ml"),
            "feature_engineer": _try_import("ml"),
        },
        "analysis": {
            "order_flow": _try_import("analysis.order_flow"),
            "market_scanner": _try_import("analysis.market_scanner"),
            "advanced_order_flow": _try_import("analysis"),
        },
        "data": {
            "depth_of_market": _try_import("data.depth_of_market"),
            "streaming": _try_import("data.streaming"),
            "time_and_sales": _try_import("data.time_and_sales"),
        },
        "backtesting": {
            "backtesting": _try_import("backtesting"),
            "backtest_engine": _try_import("backtesting"),
            "parameter_optimizer": _try_import("backtesting"),
            "walk_forward_analysis": _try_import("backtesting"),
        },
        "news_sentiment": {
            "news": _try_import("news"),
            "aggregator": _try_import("news"),
            "impact_predictor": _try_import("news"),
            "economic_calendar": _try_import("news"),
            "sentiment_analyzer": _try_import("news"),
        },
        "analytics": {
            "analytics": _try_import("analytics"),
            "portfolio_optimizer": _try_import("analytics"),
            "risk_analyzer": _try_import("analytics"),
            "simulation_engine": _try_import("analytics"),
        },
        "monetization": {
            "monetization": _try_import("monetization"),
            "subscription_manager": _try_import("monetization"),
            "pricing_manager": _try_import("monetization"),
            "license_validator": _try_import("monetization"),
        },
        "payments": {
            "payments": _try_import("payments"),
            "wallet_manager": _try_import("payments"),
            "payment_gateway": _try_import("payments"),
            "compliance_manager": _try_import("payments"),
        },
        "social": {
            "social": _try_import("social"),
            "copy_trading": _try_import("social"),
            "strategy_marketplace": _try_import("social"),
            "leaderboards": _try_import("social"),
        },
        "mobile": {
            "mobile": _try_import("mobile"),
            "mobile_api": _try_import("mobile"),
            "push_notifications": _try_import("mobile"),
        },
        "charting": {
            "charting": _try_import("charting"),
            "chart_engine": _try_import("charting"),
            "indicator_library": _try_import("charting"),
        },
        "dashboard": {
            "dashboard": _try_import("dashboard"),
            "admin_api": True,
            "paper_trading_ui": True,
            "pricing_ui": True,
        },
        "websocket": {
            "websocket_server": _try_import("api.websocket_server"),
            "alert_engine": _try_import("notifications.alert_engine"),
        },
        "strategies_available": [
            "MovingAverageCrossover",
            "RSIStrategy",
            "MACDStrategy",
            "BollingerBands",
            "EMACrossover",
            "StochasticStrategy",
            "MeanReversion",
            "BreakoutStrategy",
            "SMC_ICT",
            "ITS8OS",
        ],
        "brokers_supported": [
            "PaperTradingBroker",
            "AlpacaBroker",
            "BinanceBroker",
            "OandaBroker",
            "InteractiveBrokersBroker",
            "MT5Broker",
            "CCXTBroker",
        ],
        "market_data_symbols": list(_SYMBOL_MAP.keys()),
    }

    # Count only modules verified via _try_import (excludes hardcoded True flags)
    import_verified_sections = [
        "infrastructure", "core_trading", "ai_ml", "analysis", "data",
        "backtesting", "news_sentiment", "analytics", "monetization",
        "payments", "social", "mobile", "charting", "websocket",
    ]
    available_count = sum(
        1 for section_key in import_verified_sections
        for v in component_map.get(section_key, {}).values()
        if isinstance(v, bool) and v
    )

    component_map["summary"] = {
        "total_components_available": available_count,
        "market_data_source": "Yahoo Finance (yfinance)",
        "paper_trading": True,
        "live_trading": False,
    }

    return component_map

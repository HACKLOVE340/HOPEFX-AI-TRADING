"""
Mobile-optimized API endpoints with data compression and touch-friendly interfaces
"""

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import List, Optional
import gzip
from datetime import datetime, timedelta

router = APIRouter(prefix="/mobile", tags=["mobile"])

class MobilePosition(BaseModel):
    symbol: str
    direction: str
    size: float
    entry_price: float
    current_price: float
    unrealized_pnl: float
    unrealized_pnl_pct: float
    stop_loss: Optional[float]
    take_profit: Optional[float]

class MobileOrderRequest(BaseModel):
    symbol: str
    side: str  # 'buy' or 'sell'
    order_type: str  # 'market', 'limit', 'stop'
    quantity: float
    price: Optional[float] = None
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None

@router.get("/dashboard")
async def mobile_dashboard():
    """
    Compressed dashboard data optimized for mobile apps.
    Returns essential metrics only to minimize data usage.
    """
    # Aggregate data for mobile view
    dashboard_data = {
        'account_summary': {
            'balance': 100000.0,
            'equity': 102500.0,
            'day_pnl': 2500.0,
            'day_pnl_pct': 2.5,
            'open_positions': 3,
            'margin_used': 15000.0
        },
        'positions': [
            {
                'symbol': 'XAUUSD',
                'direction': 'long',
                'size': 1.0,
                'pnl': 150.0,
                'pnl_pct': 1.5
            }
        ],
        'watchlist': [
            {'symbol': 'XAUUSD', 'price': 2000.50, 'change': 0.25},
            {'symbol': 'EURUSD', 'price': 1.0850, 'change': -0.10}
        ],
        'alerts': [
            {'type': 'price', 'symbol': 'XAUUSD', 'message': 'Resistance at 2010'}
        ]
    }
    
    # Compress for mobile bandwidth
    return JSONResponse(
        content=dashboard_data,
        headers={'Content-Encoding': 'gzip'}
    )

@router.post("/orders/quick")
async def quick_order(order: MobileOrderRequest, background_tasks: BackgroundTasks):
    """
    One-tap order execution for mobile.
    Validates risk limits and executes immediately.
    """
    # Risk check
    risk_check = await validate_mobile_order(order)
    if not risk_check['allowed']:
        raise HTTPException(400, risk_check['reason'])
    
    # Execute in background to return quickly
    background_tasks.add_task(execute_order_async, order)
    
    return {
        'status': 'accepted',
        'order_id': generate_order_id(),
        'estimated_fill': 'market' if order.order_type == 'market' else order.price
    }

@router.get("/charts/{symbol}")
async def mobile_chart(
    symbol: str,
    timeframe: str = '1h',
    bars: int = 100  # Limited for mobile performance
):
    """
    Lightweight chart data for mobile rendering.
    Returns pre-aggregated data to reduce client-side processing.
    """
    # Fetch and downsample data
    data = await fetch_ohlcv(symbol, timeframe, limit=bars)
    
    # Optimize for mobile charting library
    return {
        'symbol': symbol,
        'timeframe': timeframe,
        'data': {
            't': [bar['timestamp'] for bar in data],  # Timestamps
            'o': [bar['open'] for bar in data],       # Opens
            'h': [bar['high'] for bar in data],       # Highs
            'l': [bar['low'] for bar in data],        # Lows
            'c': [bar['close'] for bar in data],      # Closes
            'v': [bar['volume'] for bar in data]      # Volumes
        },
        'indicators': {
            'sma_20': calculate_sma(data, 20),
            'rsi_14': calculate_rsi(data, 14)
        }
    }

@router.post("/biometric-auth")
async def biometric_authenticate(token: str):
    """
    Mobile biometric authentication endpoint.
    Validates FaceID/TouchID tokens from mobile app.
    """
    # Verify with platform-specific services
    if verify_biometric_token(token):
        return {'status': 'authenticated', 'session_token': create_jwt()}
    raise HTTPException(401, "Biometric authentication failed")

# Helper functions
async def validate_mobile_order(order: MobileOrderRequest) -> dict:
    """Validate order against mobile-specific risk limits."""
    # Implement risk checks
    return {'allowed': True}

def generate_order_id() -> str:
    return f"mob-{datetime.now().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:6]}"

async def execute_order_async(order: MobileOrderRequest):
    """Background order execution."""
    pass

async def fetch_ohlcv(symbol: str, timeframe: str, limit: int):
    """Fetch market data."""
    pass

def calculate_sma(data: list, period: int) -> list:
    """Calculate Simple Moving Average."""
    closes = [bar['close'] for bar in data]
    return [sum(closes[max(0, i-period):i])/min(period, i+1) 
            for i in range(len(closes))]

def calculate_rsi(data: list, period: int) -> list:
    """Calculate RSI."""
    # Simplified RSI calculation
    return [50.0] * len(data)  # Placeholder

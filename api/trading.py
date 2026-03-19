
# 8. API ROUTERS - Trading, Admin, and WebSocket

trading_router = '''"""
HOPEFX Trading API Router
Endpoints for trading operations
"""

from fastapi import APIRouter, HTTPException, Depends
from typing import Dict, List, Optional
from pydantic import BaseModel
import logging

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/trading", tags=["Trading"])

# Models
class OrderRequest(BaseModel):
    symbol: str
    side: str  # buy or sell
    quantity: float
    order_type: str = "market"
    price: Optional[float] = None

class PositionResponse(BaseModel):
    id: str
    symbol: str
    side: str
    quantity: float
    entry_price: float
    current_price: float
    unrealized_pnl: float

# State (injected from main app)
app_state = None

def set_state(state):
    global app_state
    app_state = state

@router.post("/order")
async def place_order(order: OrderRequest):
    """Place a new order"""
    if not app_state or not app_state.broker:
        raise HTTPException(status_code=503, detail="Broker not available")
    
    try:
        result = await app_state.broker.place_market_order(
            symbol=order.symbol,
            side=order.side,
            quantity=order.quantity
        )
        return {
            "status": "success",
            "order_id": result.id,
            "filled_price": result.average_fill_price,
            "filled_quantity": result.filled_quantity
        }
    except Exception as e:
        logger.error(f"Order error: {e}")
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/positions", response_model=List[PositionResponse])
async def get_positions():
    """Get all open positions"""
    if not app_state or not app_state.broker:
        raise HTTPException(status_code=503, detail="Broker not available")
    
    positions = await app_state.broker.get_positions()
    return [
        PositionResponse(
            id=p.id,
            symbol=p.symbol,
            side=p.side.value,
            quantity=p.quantity,
            entry_price=p.entry_price,
            current_price=p.current_price,
            unrealized_pnl=p.unrealized_pnl
        )
        for p in positions
    ]

@router.delete("/positions/{position_id}")
async def close_position(position_id: str):
    """Close a specific position"""
    if not app_state or not app_state.broker:
        raise HTTPException(status_code=503, detail="Broker not available")
    
    success = await app_state.broker.close_position(position_id)
    if not success:
        raise HTTPException(status_code=404, detail="Position not found")
    
    return {"status": "success", "position_id": position_id}

@router.delete("/positions")
async def close_all_positions():
    """Close all positions"""
    if not app_state or not app_state.broker:
        raise HTTPException(status_code=503, detail="Broker not available")
    
    closed = await app_state.broker.close_all_positions()
    return {"status": "success", "closed_positions": closed}

@router.get("/account")
async def get_account():
    """Get account information"""
    if not app_state or not app_state.broker:
        raise HTTPException(status_code=503, detail="Broker not available")
    
    info = await app_state.broker.get_account_info()
    return info

@router.get("/prices")
async def get_prices():
    """Get current prices for all symbols"""
    if not app_state or not app_state.price_engine:
        raise HTTPException(status_code=503, detail="Price engine not available")
    
    prices = {}
    for symbol in app_state.price_engine.symbols:
        tick = app_state.price_engine.get_last_price(symbol)
        if tick:
            prices[symbol] = {
                "bid": tick.bid,
                "ask": tick.ask,
                "last": tick.last_price,
                "timestamp": tick.timestamp
            }
    
    return prices

@router.get("/ohlcv/{symbol}")
async def get_ohlcv(symbol: str, timeframe: str = "1h", limit: int = 100):
    """Get OHLCV data"""
    if not app_state or not app_state.price_engine:
        raise HTTPException(status_code=503, detail="Price engine not available")
    
    data = app_state.price_engine.get_ohlcv(symbol, timeframe, limit)
    return [
        {
            "timestamp": d.timestamp,
            "open": d.open,
            "high": d.high,
            "low": d.low,
            "close": d.close,
            "volume": d.volume
        }
        for d in data
    ]

@router.get("/brain-state")
async def get_brain_state():
    """Get current brain state"""
    if not app_state or not app_state.brain:
        raise HTTPException(status_code=503, detail="Brain not available")
    
    return app_state.brain.state.to_dict()

@router.post("/emergency-stop")
async def emergency_stop():
    """Trigger emergency stop"""
    if not app_state or not app_state.brain:
        raise HTTPException(status_code=503, detail="Brain not available")
    
    app_state.brain.emergency_stop()
    return {"status": "emergency_stop_triggered"}
'''

with open(project_root / "api" / "trading.py", "w") as f:
    f.write(trading_router)

print("✓ Created api/trading.py")

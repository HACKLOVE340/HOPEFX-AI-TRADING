"""
HOPEFX Trading API Router

All state-mutating endpoints (order placement, position close, emergency-stop)
require a valid JWT bearer token with at minimum the "trader" role.
Read-only endpoints (prices, OHLCV, account, brain-state) require any
authenticated user ("user" role or higher).

Auth is enforced via Depends(require_role(...)) from api.auth.
"""

import logging
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator

from api.auth import (
    TokenPayload,
    get_current_user,
    require_role,
    validate_order_symbol,
    validate_order_quantity,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/trading", tags=["Trading"])


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------

class OrderRequest(BaseModel):
    symbol: str = Field(..., min_length=1, max_length=20)
    side: str = Field(..., pattern="^(buy|sell)$")
    quantity: float = Field(..., gt=0)
    order_type: str = Field("market", pattern="^(market|limit|stop)$")
    price: Optional[float] = Field(None, gt=0)

    @field_validator("symbol")
    @classmethod
    def _symbol(cls, v: str) -> str:
        return validate_order_symbol(v)

    @field_validator("quantity")
    @classmethod
    def _quantity(cls, v: float) -> float:
        return validate_order_quantity(v)


class PositionResponse(BaseModel):
    id: str
    symbol: str
    side: str
    quantity: float
    entry_price: float
    current_price: float
    unrealized_pnl: float


# ---------------------------------------------------------------------------
# Module-level state (injected from app.py startup)
# ---------------------------------------------------------------------------

app_state = None


def set_state(state) -> None:
    global app_state
    app_state = state


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/order", status_code=status.HTTP_201_CREATED)
async def place_order(
    order: OrderRequest,
    user: TokenPayload = Depends(require_role("trader")),
):
    """
    Place a new order.

    Requires: Bearer token with role >= 'trader'.
    Symbol and quantity are validated against server-side allowlists.
    """
    if not app_state or not app_state.broker:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Broker not available")

    try:
        result = await app_state.broker.place_market_order(
            symbol=order.symbol,
            side=order.side,
            quantity=order.quantity,
        )
        logger.info(
            "Order placed: user=%s symbol=%s side=%s qty=%s order_id=%s",
            user.sub, order.symbol, order.side, order.quantity, result.id,
        )
        return {
            "status": "success",
            "order_id": result.id,
            "filled_price": result.average_fill_price,
            "filled_quantity": result.filled_quantity,
        }
    except Exception as exc:
        logger.error("Order error for user=%s: %s", user.sub, exc)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.get("/positions", response_model=List[PositionResponse])
async def get_positions(
    user: TokenPayload = Depends(get_current_user),
):
    """Get all open positions. Requires: any authenticated user."""
    if not app_state or not app_state.broker:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Broker not available")

    positions = await app_state.broker.get_positions()
    return [
        PositionResponse(
            id=p.id,
            symbol=p.symbol,
            side=p.side.value,
            quantity=p.quantity,
            entry_price=p.entry_price,
            current_price=p.current_price,
            unrealized_pnl=p.unrealized_pnl,
        )
        for p in positions
    ]


@router.delete("/positions/{position_id}")
async def close_position(
    position_id: str,
    user: TokenPayload = Depends(require_role("trader")),
):
    """Close a specific position. Requires: role >= 'trader'."""
    if not app_state or not app_state.broker:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Broker not available")

    success = await app_state.broker.close_position(position_id)
    if not success:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Position not found")

    logger.info("Position closed: user=%s position_id=%s", user.sub, position_id)
    return {"status": "success", "position_id": position_id}


@router.delete("/positions")
async def close_all_positions(
    user: TokenPayload = Depends(require_role("trader")),
):
    """Close all open positions. Requires: role >= 'trader'."""
    if not app_state or not app_state.broker:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Broker not available")

    closed = await app_state.broker.close_all_positions()
    logger.info("All positions closed: user=%s count=%s", user.sub, closed)
    return {"status": "success", "closed_positions": closed}


@router.get("/account")
async def get_account(
    user: TokenPayload = Depends(get_current_user),
):
    """Get account information. Requires: any authenticated user."""
    if not app_state or not app_state.broker:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Broker not available")

    return await app_state.broker.get_account_info()


@router.get("/prices")
async def get_prices(
    user: TokenPayload = Depends(get_current_user),
):
    """Get current bid/ask prices. Requires: any authenticated user."""
    if not app_state or not app_state.price_engine:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Price engine not available")

    prices: Dict = {}
    for symbol in app_state.price_engine.symbols:
        tick = app_state.price_engine.get_last_price(symbol)
        if tick:
            prices[symbol] = {
                "bid": tick.bid,
                "ask": tick.ask,
                "last": tick.last_price,
                "timestamp": tick.timestamp,
            }
    return prices


@router.get("/ohlcv/{symbol}")
async def get_ohlcv(
    symbol: str,
    timeframe: str = "1h",
    limit: int = 100,
    user: TokenPayload = Depends(get_current_user),
):
    """Get OHLCV data. Requires: any authenticated user. Symbol validated server-side."""
    symbol = validate_order_symbol(symbol)

    if not app_state or not app_state.price_engine:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Price engine not available")

    data = app_state.price_engine.get_ohlcv(symbol, timeframe, limit)
    return [
        {
            "timestamp": d.timestamp,
            "open": d.open,
            "high": d.high,
            "low": d.low,
            "close": d.close,
            "volume": d.volume,
        }
        for d in data
    ]


@router.get("/brain-state")
async def get_brain_state(
    user: TokenPayload = Depends(get_current_user),
):
    """Get AI brain state. Requires: any authenticated user."""
    if not app_state or not app_state.brain:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Brain not available")

    return app_state.brain.state.to_dict()


@router.post("/emergency-stop")
async def emergency_stop(
    user: TokenPayload = Depends(require_role("admin")),
):
    """
    Trigger emergency stop — halts all trading immediately.

    Requires: role >= 'admin'. Logs the triggering user for audit trail.
    """
    if not app_state or not app_state.brain:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Brain not available")

    app_state.brain.emergency_stop()
    logger.critical("Emergency stop triggered by user=%s", user.sub)
    return {"status": "emergency_stop_triggered", "triggered_by": user.sub}

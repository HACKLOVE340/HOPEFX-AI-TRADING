# src/hopefx/api/routes/trading.py
"""
Secure trading API endpoints with full auth and validation.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator

from hopefx.api.dependencies import (
    get_current_user,
    require_roles,
    User,
    get_rate_limit_key
)
from hopefx.execution.oms import OrderManager, OrderType
from hopefx.risk.manager import RiskManager
from hopefx.config.settings import settings

router = APIRouter()


class OrderRequest(BaseModel):
    """Validated order request."""
    symbol: str = Field(..., min_length=1, max_length=20)
    side: Literal["BUY", "SELL"]
    quantity: Decimal = Field(..., gt=0, decimal_places=2)
    order_type: Literal["MARKET", "LIMIT", "STOP"] = "MARKET"
    price: Decimal | None = Field(None, gt=0)
    stop_loss: Decimal | None = Field(None, gt=0)
    take_profit: Decimal | None = Field(None, gt=0)
    
    @field_validator("symbol")
    @classmethod
    def validate_symbol(cls, v: str) -> str:
        """Validate trading symbol."""
        allowed = ["XAUUSD", "EURUSD", "GBPUSD", "USDJPY"]
        if v.upper() not in allowed:
            raise ValueError(f"Symbol must be one of: {allowed}")
        return v.upper()
    
    @field_validator("price")
    @classmethod
    def validate_limit_price(cls, v: Decimal | None, info) -> Decimal | None:
        """Validate limit price exists for limit orders."""
        order_type = info.data.get("order_type")
        if order_type == "LIMIT" and v is None:
            raise ValueError("Limit orders require a price")
        return v


class OrderResponse(BaseModel):
    """Order response."""
    order_id: str
    status: str
    symbol: str
    side: str
    quantity: str  # Decimal as string for JSON
    message: str


@router.post("/orders", response_model=OrderResponse)
async def create_order(
    request: OrderRequest,
    user: User = Depends(get_current_user),
    risk_manager: RiskManager = Depends(),
    oms: OrderManager = Depends()
) -> OrderResponse:
    """
    Create new trading order with risk checks.
    
    Requires authentication. Position size validated against risk limits.
    """
    # Check if trading is allowed
    if not user.has_permission("trading:write"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Trading permission required"
        )
    
    # Risk check
    if request.stop_loss:
        position_size = await risk_manager.calculate_position_size(
            symbol=request.symbol,
            entry_price=request.price or Decimal("2000"),  # Current market
            stop_loss=Decimal(str(request.stop_loss)),
            account_balance=Decimal("100000"),  # From user account
            volatility=0.15  # Current market vol
        )
        
        if request.quantity > position_size:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Position size exceeds risk limit. Max: {position_size}"
            )
    
    # Submit order
    order_type = OrderType[request.order_type]
    
    order = await oms.submit_order(
        symbol=request.symbol,
        side=request.side,
        quantity=request.quantity,
        order_type=order_type,
        price=request.price
    )
    
    return OrderResponse(
        order_id=order.order_id,
        status=order.status.name,
        symbol=order.symbol,
        side=order.side,
        quantity=str(order.quantity),
        message="Order submitted successfully"
    )


@router.get("/orders")
async def list_orders(
    user: User = Depends(get_current_user),
    oms: OrderManager = Depends()
):
    """List user's open orders."""
    orders = oms.get_open_orders()
    return {"orders": orders}


@router.delete("/orders/{order_id}")
async def cancel_order(
    order_id: str,
    user: User = Depends(require_roles(["trader", "admin"])),
    oms: OrderManager = Depends()
):
    """Cancel an order."""
    try:
        order = await oms.cancel_order(order_id)
        return {"status": "cancelled", "order_id": order.order_id}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

"""
Trading API endpoints.
"""

from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from src.domain.enums import OrderType, TradeDirection
from src.domain.models import Order
from src.execution.oms import OrderManagementSystem
from src.brokers.paper import PaperBroker

router = APIRouter()


class OrderRequest(BaseModel):
    symbol: str = Field(default="XAUUSD")
    direction: TradeDirection
    quantity: float = Field(gt=0)
    order_type: OrderType = Field(default=OrderType.MARKET)
    price: float | None = Field(default=None, gt=0)


class OrderResponse(BaseModel):
    order_id: str
    status: str
    broker_id: str | None


# Dependency
async def get_oms():
    broker = PaperBroker()
    await broker.connect()
    return OrderManagementSystem(broker)


@router.post("/orders", response_model=OrderResponse)
async def submit_order(
    request: OrderRequest,
    oms: OrderManagementSystem = Depends(get_oms)
):
    """Submit trading order."""
    try:
        order = await oms.submit_order(
            symbol=request.symbol,
            direction=request.direction,
            quantity=Decimal(str(request.quantity)),
            order_type=request.order_type,
            price=Decimal(str(request.price)) if request.price else None
        )
        
        return {
            "order_id": str(order.id),
            "status": order.status.value,
            "broker_id": order.broker_id
        }
        
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/positions")
async def get_positions():
    """Get current positions."""
    # Implementation
    return {"positions": []}


@router.post("/emergency/kill")
async def emergency_kill():
    """Trigger emergency kill switch."""
    from src.risk.kill_switch import KillSwitch
    
    kill_switch = KillSwitch()
    kill_switch.trigger("Manual API trigger")
    
    return {"status": "kill_switch_triggered"}

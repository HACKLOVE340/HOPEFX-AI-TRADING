from __future__ import annotations

from decimal import Decimal
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks
from pydantic import BaseModel, Field

from hopefx.brain.engine import brain
from hopefx.config.settings import settings
from hopefx.database.models import Trade, Strategy
from hopefx.execution.oms import oms, OrderState
from hopefx.risk.prop_rules import prop_rules

router = APIRouter()


class TradeRequest(BaseModel):
    symbol: str = Field(default="XAUUSD")
    side: str = Field(..., regex="^(buy|sell|close)$")
    quantity: Decimal = Field(..., gt=0)
    order_type: str = Field(default="market", regex="^(market|limit|stop)$")
    price: Optional[Decimal] = None
    stop_loss: Optional[Decimal] = None
    take_profit: Optional[Decimal] = None
    strategy_id: Optional[str] = None


class TradeResponse(BaseModel):
    order_id: str
    status: str
    filled_qty: float
    filled_price: Optional[float]
    commission: float
    message: str


@router.post("/trades", response_model=TradeResponse)
async def create_trade(request: TradeRequest, background_tasks: BackgroundTasks):
    """Execute new trade with full risk validation."""
    
    # Prop firm validation
    if settings.trading_mode == "prop_challenge":
        approved, reason = prop_rules.check_account(
            brain.state.equity,
            brain.state.daily_pnl,
            Decimal("0")  # total_pnl from DB
        )
        if not approved:
            raise HTTPException(403, f"Prop challenge violation: {reason}")

    # Build signal
    from hopefx.events.schemas import Signal
    signal = Signal(
        symbol=request.symbol,
        timestamp=datetime.utcnow(),
        direction=request.side,
        confidence=Decimal("0.8"),  # From ML or manual
        size=request.quantity,
        order_type=request.order_type,
        limit_price=request.price,
        stop_price=request.stop_loss,
        metadata={
            "take_profit": request.take_profit,
            "strategy_id": request.strategy_id,
        }
    )

    # Submit to OMS
    # This happens async via event bus
    await event_bus.publish(
        Event(
            type=EventType.SIGNAL,
            payload=signal,
            source="api",
        )
    )

    return TradeResponse(
        order_id="pending",  # Will be updated
        status="pending",
        filled_qty=0,
        filled_price=None,
        commission=0,
        message="Order submitted for processing"
    )


@router.get("/trades")
async def get_trades(status: Optional[str] = None, limit: int = 100):
    """Get trade history."""
    trades = []
    for order_id, state in oms._orders.items():
        if status and state.status.name.lower() != status:
            continue
        trades.append({
            "order_id": order_id,
            "status": state.status.name,
            "symbol": state.signal.symbol if state.signal else None,
            "side": state.signal.direction if state.signal else None,
            "size": float(state.signal.size) if state.signal else 0,
            "created_at": state.created_at,
            "risk_approved": state.risk_approved,
            "filled_qty": float(state.execution_result.filled_qty) if state.execution_result else 0,
            "filled_price": float(state.execution_result.filled_price) if state.execution_result else None,
        })
    return {"trades": trades[-limit:]}


@router.get("/trades/{order_id}")
async def get_trade(order_id: str):
    """Get specific trade details."""
    state = oms.get_order(order_id)
    if not state:
        raise HTTPException(404, "Trade not found")
    
    return {
        "order_id": order_id,
        "status": state.status.name,
        "signal": state.signal.model_dump() if state.signal else None,
        "execution": state.execution_result.__dict__ if state.execution_result else None,
        "amendments": state.amendments,
    }


@router.delete("/trades/{order_id}")
async def cancel_trade(order_id: str):
    """Cancel pending trade."""
    success = await oms.cancel_order(order_id)
    if not success:
        raise HTTPException(400, "Cannot cancel order - may already be filled or rejected")
    return {"message": "Order cancelled"}


@router.get("/positions")
async def get_positions():
    """Get all open positions."""
    positions = oms.get_all_positions()
    return {
        "positions": [
            {
                "symbol": sym,
                "side": pos["side"],
                "qty": float(pos["qty"]),
                "entry_price": float(pos["entry_price"]),
                "unrealized_pnl": float(pos.get("unrealized_pnl", 0)),
            }
            for sym, pos in positions.items()
        ],
        "count": len(positions),
    }


@router.post("/positions/{symbol}/close")
async def close_position(symbol: str):
    """Close specific position."""
    position = oms.get_position(symbol)
    if not position:
        raise HTTPException(404, "No open position for symbol")

    # Create close signal
    close_signal = Signal(
        symbol=symbol,
        timestamp=datetime.utcnow(),
        direction="close",
        confidence=Decimal("1.0"),
        size=position["qty"],
        order_type="market",
    )

    await event_bus.publish(
        Event(
            type=EventType.SIGNAL,
            payload=close_signal,
            source="api",
        )
    )

    return {"message": f"Close order submitted for {symbol}"}


@router.get("/equity")
async def get_equity():
    """Get current account equity."""
    return {
        "equity": float(brain.state.equity),
        "cash": float(brain.state.cash),
        "daily_pnl": float(brain.state.daily_pnl),
        "open_positions_value": sum(
            float(pos.get("unrealized_pnl", 0)) 
            for pos in oms.get_all_positions().values()
        ),
        "buying_power": float(brain.state.cash * Decimal("30")),  # Leverage
    }


@router.post("/emergency-stop")
async def emergency_stop():
    """EMERGENCY: Stop all trading and close positions."""
    # Close all positions first
    for symbol in list(oms.get_all_positions().keys()):
        await close_position(symbol)

    # Stop OMS
    await oms.stop()

    return {
        "message": "EMERGENCY STOP ACTIVATED",
        "timestamp": datetime.utcnow().isoformat(),
        "closed_positions": list(oms.get_all_positions().keys()),
    }


@router.get("/performance")
async def get_performance(period: str = "1m"):
    """Get trading performance metrics."""
    # Calculate from trade history
    return {
        "period": period,
        "total_return_pct": 0.0,  # Calculate from DB
        "sharpe_ratio": 0.0,
        "max_drawdown_pct": 0.0,
        "win_rate": 0.0,
        "profit_factor": 0.0,
        "total_trades": len(oms._orders),
    }

from __future__ import annotations

from decimal import Decimal
from typing import List

from fastapi import APIRouter, HTTPException, Depends

from hopefx.execution.oms import oms
from hopefx.brain.engine import brain

router = APIRouter()


@router.get("/trades")
async def get_trades():
    """Get all orders from OMS."""
    return {
        "orders": [
            {
                "id": oid,
                "status": state.status.name,
                "signal": state.signal.model_dump() if state.signal else None,
            }
            for oid, state in oms._orders.items()
        ]
    }


@router.get("/positions")
async def get_positions():
    """Get current positions."""
    return oms.get_all_positions()


@router.get("/equity")
async def get_equity():
    """Get current equity."""
    return {
        "equity": float(brain.state.equity),
        "cash": float(brain.state.cash),
        "daily_pnl": float(brain.state.daily_pnl),
    }


@router.post("/emergency-stop")
async def emergency_stop():
    """Emergency stop all trading."""
    await oms.stop()
    return {"status": "emergency_stop_activated"}

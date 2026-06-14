# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
api/advanced_orders.py
=======================
REST API endpoints for Advanced Order Types (OCO, Trailing Stop, Stop-Limit).

Endpoints:
    POST   /api/orders/advanced/oco           — Submit OCO order
    POST   /api/orders/advanced/trailing-stop — Submit trailing stop
    POST   /api/orders/advanced/stop-limit    — Submit stop-limit order
    DELETE /api/orders/advanced/{order_id}     — Cancel an advanced order
    GET    /api/orders/advanced/active         — List active advanced orders
    GET    /api/orders/advanced/{order_id}     — Get order details
    GET    /api/orders/advanced/health         — Manager health metrics
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

UTC = timezone.utc
logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/orders/advanced",
    tags=["Advanced Orders"],
)


# ── Request Models ────────────────────────────────────────────────────────────


class OCORequest(BaseModel):
    """Request body for submitting an OCO order."""
    position_id: str = Field(..., description="Position ID to protect")
    symbol: str = Field(default="XAU_USD", description="Trading symbol")
    side: str = Field(..., description="Closing side (BUY or SELL)")
    quantity: float = Field(..., gt=0, description="Order quantity in lots")
    stop_loss_price: float = Field(..., gt=0, description="Stop-loss trigger price")
    take_profit_price: float = Field(..., gt=0, description="Take-profit trigger price")


class TrailingStopRequest(BaseModel):
    """Request body for submitting a trailing stop order."""
    position_id: str = Field(..., description="Position ID to protect")
    symbol: str = Field(default="XAU_USD", description="Trading symbol")
    side: str = Field(..., description="Closing side (BUY or SELL)")
    quantity: float = Field(..., gt=0, description="Order quantity in lots")
    trail_distance_pips: float = Field(..., gt=0, description="Trail distance in pips")
    activation_price: float | None = Field(
        default=None, description="Price at which trailing begins (optional)"
    )


class StopLimitRequest(BaseModel):
    """Request body for submitting a stop-limit order."""
    position_id: str = Field(..., description="Position ID")
    symbol: str = Field(default="XAU_USD", description="Trading symbol")
    side: str = Field(..., description="Order side (BUY or SELL)")
    quantity: float = Field(..., gt=0, description="Order quantity in lots")
    stop_price: float = Field(..., gt=0, description="Stop trigger price")
    limit_price: float = Field(..., gt=0, description="Limit price once triggered")
    expires_at: str | None = Field(
        default=None, description="Expiration time (ISO 8601)"
    )


# ── Endpoints ─────────────────────────────────────────────────────────────────


@router.post("/oco", response_model=dict)
async def submit_oco(request: OCORequest):
    """
    Submit an OCO (One-Cancels-the-Other) order.

    Pairs a stop-loss and take-profit. When one fills, the other is cancelled.
    Uses native broker support when available; falls back to in-memory monitoring.
    """
    from execution.advanced_orders import get_advanced_order_manager

    manager = get_advanced_order_manager()

    try:
        order_id = await manager.submit_oco(
            position_id=request.position_id,
            symbol=request.symbol,
            side=request.side,
            quantity=request.quantity,
            stop_loss_price=request.stop_loss_price,
            take_profit_price=request.take_profit_price,
        )
        return {
            "status": "success",
            "order_id": order_id,
            "message": "OCO order submitted successfully.",
        }
    except Exception as exc:
        logger.error("OCO submission failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/trailing-stop", response_model=dict)
async def submit_trailing_stop(request: TrailingStopRequest):
    """
    Submit a trailing stop order.

    The stop price follows the market by trail_distance_pips.
    Optionally, trailing only activates after activation_price is reached.
    """
    from execution.advanced_orders import get_advanced_order_manager

    manager = get_advanced_order_manager()

    try:
        order_id = await manager.submit_trailing_stop(
            position_id=request.position_id,
            symbol=request.symbol,
            side=request.side,
            quantity=request.quantity,
            trail_distance_pips=request.trail_distance_pips,
            activation_price=request.activation_price,
        )
        return {
            "status": "success",
            "order_id": order_id,
            "message": "Trailing stop order submitted successfully.",
        }
    except Exception as exc:
        logger.error("Trailing stop submission failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/stop-limit", response_model=dict)
async def submit_stop_limit(request: StopLimitRequest):
    """
    Submit a stop-limit order.

    When price reaches stop_price, a limit order at limit_price is placed.
    Provides price certainty at the cost of fill certainty.
    """
    from execution.advanced_orders import get_advanced_order_manager

    manager = get_advanced_order_manager()

    expires = None
    if request.expires_at:
        try:
            expires = datetime.fromisoformat(request.expires_at)
        except ValueError as exc:
            raise HTTPException(
                status_code=422, detail=f"Invalid expires_at format: {exc}"
            ) from exc

    try:
        order_id = await manager.submit_stop_limit(
            position_id=request.position_id,
            symbol=request.symbol,
            side=request.side,
            quantity=request.quantity,
            stop_price=request.stop_price,
            limit_price=request.limit_price,
            expires_at=expires,
        )
        return {
            "status": "success",
            "order_id": order_id,
            "message": "Stop-limit order submitted successfully.",
        }
    except Exception as exc:
        logger.error("Stop-limit submission failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.delete("/{order_id}", response_model=dict)
async def cancel_advanced_order(order_id: str):
    """Cancel an active advanced order."""
    from execution.advanced_orders import get_advanced_order_manager

    manager = get_advanced_order_manager()

    success = await manager.cancel_order(order_id)
    if not success:
        raise HTTPException(
            status_code=404,
            detail=f"Order '{order_id}' not found or not in cancellable state.",
        )

    return {
        "status": "success",
        "message": f"Order '{order_id}' cancelled.",
    }


@router.get("/active", response_model=dict)
async def list_active_orders(position_id: str | None = Query(default=None)):
    """List all active advanced orders, optionally filtered by position."""
    from execution.advanced_orders import get_advanced_order_manager

    manager = get_advanced_order_manager()
    orders = manager.get_active_orders(position_id=position_id)

    return {
        "count": len(orders),
        "orders": orders,
    }


@router.get("/health", response_model=dict)
async def advanced_orders_health():
    """Return Advanced Order Manager health metrics."""
    from execution.advanced_orders import get_advanced_order_manager

    manager = get_advanced_order_manager()
    return manager.health()


@router.get("/{order_id}", response_model=dict)
async def get_order_details(order_id: str):
    """Get details of a specific advanced order."""
    from execution.advanced_orders import get_advanced_order_manager

    manager = get_advanced_order_manager()
    order = manager.get_order(order_id)

    if order is None:
        raise HTTPException(status_code=404, detail=f"Order '{order_id}' not found.")

    return order

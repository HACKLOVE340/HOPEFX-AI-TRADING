# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
api/copy_trading.py
====================
Copy Trading Management API — serves the frontend CopyTrading page.
Provides: /api/copy-trading/my-copies, /api/copy-trading/copies/{id}/pause|resume|stop
Connected to: social/advanced_copy_trading.py
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from api.auth import TokenPayload, get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/copy-trading", tags=["Copy Trading"])


def _get_copy_engine():
    """Retrieve the copy trading engine from app state."""
    try:
        from core.app_state import app_state

        engine = getattr(app_state, "copy_trading_engine", None)
        if engine is None:
            from social.copy_trading_engine import AdvancedCopyTradingEngine

            engine = AdvancedCopyTradingEngine()
            app_state.copy_trading_engine = engine
        return engine
    except Exception as e:
        logger.warning(f"Copy trading engine init failed: {e}")
        return None


@router.get("/my-copies")
async def get_my_copies(user: TokenPayload = Depends(get_current_user)):
    """
    Retrieve all active copy trading subscriptions for the current user.
    Returns: list of copies with master trader info, performance, and settings.
    """
    engine = _get_copy_engine()
    if not engine:
        return {"copies": [], "total": 0}

    try:
        copies = await engine.get_user_copies(user_id=user.sub)
        return {"copies": copies, "total": len(copies)}
    except Exception as e:
        logger.error(f"Failed to get copies: {e}")
        return {"copies": [], "total": 0}


@router.post("/copies/{copy_id}/pause")
async def pause_copy(copy_id: str, user: TokenPayload = Depends(get_current_user)):
    """Pause an active copy trading subscription."""
    engine = _get_copy_engine()
    if not engine:
        raise HTTPException(status_code=503, detail="Copy trading engine unavailable")

    try:
        result = await engine.pause_copy(copy_id)
        return {"status": "paused", "copy_id": copy_id, **result}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to pause: {e}") from e


@router.post("/copies/{copy_id}/resume")
async def resume_copy(copy_id: str, user: TokenPayload = Depends(get_current_user)):
    """Resume a paused copy trading subscription."""
    engine = _get_copy_engine()
    if not engine:
        raise HTTPException(status_code=503, detail="Copy trading engine unavailable")

    try:
        result = await engine.resume_copy(copy_id)
        return {"status": "active", "copy_id": copy_id, **result}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to resume: {e}") from e


@router.post("/copies/{copy_id}/stop")
async def stop_copy(copy_id: str, user: TokenPayload = Depends(get_current_user)):
    """Stop and remove a copy trading subscription permanently."""
    engine = _get_copy_engine()
    if not engine:
        raise HTTPException(status_code=503, detail="Copy trading engine unavailable")

    try:
        result = await engine.stop_copy(copy_id)
        return {"status": "stopped", "copy_id": copy_id, **result}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to stop: {e}") from e


@router.patch("/copies/{copy_id}/risk")
async def adjust_copy_risk(copy_id: str, payload: dict, user: TokenPayload = Depends(get_current_user)):
    """
    Adjust risk settings for a copy trading subscription.
    Payload: { max_drawdown_pct, lot_multiplier, max_open_trades }
    """
    engine = _get_copy_engine()
    if not engine:
        raise HTTPException(status_code=503, detail="Copy trading engine unavailable")

    try:
        result = await engine.adjust_risk(copy_id, payload)
        return {"status": "updated", "copy_id": copy_id, "settings": result}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to adjust risk: {e}") from e


@router.get("/copies/{copy_id}/performance")
async def get_copy_performance(copy_id: str, user: TokenPayload = Depends(get_current_user)):
    """Get performance metrics for a specific copy subscription (must belong to the requesting user)."""
    engine = _get_copy_engine()
    if not engine:
        raise HTTPException(status_code=503, detail="Copy trading engine unavailable")

    try:
        perf = await engine.get_copy_performance(copy_id, user_id=user.sub)
        # Engine returns None when copy_id doesn't exist or belongs to another user
        if perf is None:
            raise HTTPException(
                status_code=404,
                detail=f"Copy subscription '{copy_id}' not found or does not belong to the requesting user",
            )
        return perf
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get performance: {e}") from e


@router.get("/masters")
async def get_master_traders(
    sort_by: str = Query("profit", pattern="^(profit|win_rate|followers|drawdown)$"),
    limit: int = Query(20, ge=1, le=100),
):
    """
    Get list of available master traders to copy.
    Sorted by the specified metric.
    """
    engine = _get_copy_engine()
    if not engine:
        return {"masters": [], "total": 0}

    try:
        masters = await engine.get_master_traders(sort_by=sort_by, limit=limit)
        return {"masters": masters, "total": len(masters)}
    except Exception as e:
        logger.error(f"Failed to get master traders: {e}")
        return {"masters": [], "total": 0}

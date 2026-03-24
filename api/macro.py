"""
api/macro.py
============
Macro data endpoints — DXY, US yields, CPI, and regime score for gold.

Routes
------
GET /api/macro/snapshot   — current macro snapshot (cached, refreshes hourly)
GET /api/macro/refresh    — force-refresh from FRED (admin use)
GET /api/macro/features   — flat ML feature dict for model inference
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, status

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/macro", tags=["Macro Data"])


@router.get("/snapshot", summary="Current macro snapshot for gold")
async def macro_snapshot():
    """
    Return the latest macro data snapshot: DXY, 10Y yield, 2Y yield,
    yield spread, CPI, and a 0–100 regime score for gold.

    Data is cached for 1 hour to avoid hammering FRED.
    """
    try:
        from data.feeds.macro import get_macro_feed
        feed = get_macro_feed()
        return await feed.refresh_async()
    except Exception as exc:
        logger.warning("macro snapshot failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Macro data unavailable: {exc}",
        )


@router.get("/refresh", summary="Force-refresh macro data from FRED")
async def macro_refresh():
    """Force a fresh pull from FRED, bypassing the cache."""
    try:
        from data.feeds.macro import get_macro_feed
        feed = get_macro_feed()
        snapshot = await feed.refresh_async()
        return {"status": "refreshed", **snapshot}
    except Exception as exc:
        logger.warning("macro refresh failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Macro refresh failed: {exc}",
        )


@router.get("/features", summary="Macro features for ML inference")
async def macro_features():
    """
    Return macro values as a flat dict of floats ready to merge into
    the ML feature matrix.  All keys are prefixed with 'macro_'.
    """
    try:
        from data.feeds.macro import get_macro_feed
        feed = get_macro_feed()
        return feed.as_ml_features()
    except Exception as exc:
        logger.warning("macro features failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Macro features unavailable: {exc}",
        )

# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026 Opeyemi (HACKLOVE340)
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
api/macro.py
============
Macro data endpoints — DXY, US yields, CPI, and regime score for gold.

Routes
------
GET  /api/macro/snapshot      — current macro snapshot (cached, refreshes hourly)
GET  /api/macro/refresh       — force-refresh from FRED and push into MacroStore
GET  /api/macro/features      — flat ML feature dict for model inference
GET  /api/macro/store         — MacroStore snapshot (series loaded, latest values)
POST /api/macro/store/update  — upsert a single macro observation into MacroStore

Wiring
------
MacroFeed (FRED) → MacroStore (in-memory, forward-fill) → live_inference
  - /refresh pulls fresh FRED values and calls macro_store.update() for each
    series so the signal engine immediately sees the new values.
  - /store/update lets external jobs (COT, ETF flow) push values directly.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict

from fastapi import APIRouter, Body, HTTPException, status
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/macro", tags=["Macro Data"])


# ── helpers ───────────────────────────────────────────────────────────────────

def _get_macro_store():
    """Return the module-level MacroStore singleton (never raises)."""
    try:
        from ml.macro_store import macro_store
        return macro_store
    except Exception as exc:
        logger.debug("MacroStore unavailable: %s", exc)
        return None


def _push_snapshot_to_store(snapshot: Dict[str, Any]) -> int:
    """
    Push FRED snapshot values into MacroStore so live inference sees them.

    Maps MacroFeed keys → MacroStore series names and calls store.update()
    for each non-None value.  Returns the number of series updated.
    """
    store = _get_macro_store()
    if store is None:
        return 0

    today = datetime.now(timezone.utc).date().isoformat()
    mapping = {
        "dxy":          "dxy",
        "yield_10y":    "us10y",
        "yield_2y":     "us2y",
        "yield_spread": "yield_spread",
        "cpi_latest":   "cpi_surprise",
    }
    updated = 0
    for feed_key, store_key in mapping.items():
        val = snapshot.get(feed_key)
        if val is not None:
            try:
                store.update(store_key, today, float(val))
                updated += 1
            except Exception as exc:
                logger.debug("MacroStore.update(%s) failed: %s", store_key, exc)
    return updated


# ── endpoints ─────────────────────────────────────────────────────────────────

@router.get("/snapshot", summary="Current macro snapshot for gold")
async def macro_snapshot():
    """
    Return the latest macro data snapshot: DXY, 10Y yield, 2Y yield,
    yield spread, CPI, and a 0-100 regime score for gold.

    Data is cached for 1 hour to avoid hammering FRED.
    """
    try:
        from data.feeds.macro import get_macro_feed

        feed = get_macro_feed()
        snap = await feed.refresh_async()
        n = _push_snapshot_to_store(snap)
        snap["macro_store_series_updated"] = n
        return snap
    except Exception as exc:
        logger.warning("macro snapshot failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Macro data unavailable: {exc}",
        )


@router.get("/refresh", summary="Force-refresh macro data from FRED and update MacroStore")
async def macro_refresh():
    """
    Force a fresh pull from FRED, bypassing the 1-hour cache, and push
    the new values into MacroStore for immediate use by live inference.
    """
    try:
        from data.feeds.macro import get_macro_feed

        feed = get_macro_feed()
        feed._cache_ts = None  # invalidate cache
        snapshot = await feed.refresh_async()
        n = _push_snapshot_to_store(snapshot)
        return {"status": "refreshed", "macro_store_series_updated": n, **snapshot}
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

    Prefers MacroStore (which may have more series than FRED alone) and
    falls back to MacroFeed if the store is empty.
    """
    store = _get_macro_store()
    if store is not None and len(store) > 0:
        snap = store.snapshot()
        features: Dict[str, float] = {}
        for name, info in snap.items():
            if info is not None:
                features[f"macro_{name}"] = float(info["value"])
        if features:
            return features

    # Fallback: MacroFeed
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


@router.get("/store", summary="MacroStore snapshot — all loaded series with latest values")
async def macro_store_snapshot():
    """
    Return the current state of the in-memory MacroStore: which series are
    loaded, their latest values, and observation counts.

    Used by the admin dashboard to verify macro data is flowing into the
    signal engine.
    """
    store = _get_macro_store()
    if store is None:
        return {"status": "unavailable", "series": {}, "total_series": 0}

    snap = store.snapshot()
    return {
        "status": "ok",
        "total_series": len(store),
        "series": snap,
    }


class MacroUpdateRequest(BaseModel):
    series_name: str = Field(..., description="MacroStore series name, e.g. 'dxy', 'us10y'")
    date: str = Field(..., description="ISO date string, e.g. '2026-03-26'")
    value: float = Field(..., description="Observed value")


@router.post("/store/update", summary="Upsert a macro observation into MacroStore")
async def macro_store_update(req: MacroUpdateRequest = Body(...)):
    """
    Upsert a single macro observation into the in-memory MacroStore.

    Called by external data ingestion jobs (COT weekly, ETF flow daily,
    custom macro feeds) to push values that FRED does not provide.

    The new value is immediately available to live inference on the next
    signal generation call.
    """
    store = _get_macro_store()
    if store is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="MacroStore not initialised",
        )
    try:
        store.update(req.series_name, req.date, req.value)
        snap = store.snapshot().get(req.series_name)
        return {
            "status": "updated",
            "series": req.series_name,
            "date": req.date,
            "value": req.value,
            "total_observations": snap["n_observations"] if snap else 1,
        }
    except Exception as exc:
        logger.warning("MacroStore.update failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Update failed: {exc}",
        )

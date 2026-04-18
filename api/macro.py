# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
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

UTC = timezone.utc
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, status
from pydantic import BaseModel, Field

from api.auth import TokenPayload, get_current_user, require_role

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


def _push_snapshot_to_store(snapshot: dict[str, Any]) -> int:
    """
    Push FRED snapshot values into MacroStore so live inference sees them.

    Maps MacroFeed keys → MacroStore series names and calls store.update()
    for each non-None value.  Returns the number of series updated.
    """
    store = _get_macro_store()
    if store is None:
        return 0

    today = datetime.now(UTC).date().isoformat()
    mapping = {
        "dxy": "dxy",
        "yield_10y": "us10y",
        "yield_2y": "us2y",
        "yield_spread": "yield_spread",
        "cpi_latest": "cpi_surprise",
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

    Fallback chain (never returns 503):
    1. FRED live fetch (requires FRED_API_KEY for best rate limits)
    2. MacroStore cached values from a previous successful fetch
    3. Hardcoded neutral baseline with source='static_fallback'
    """
    # 1. Try FRED live fetch
    try:
        from data.feeds.macro import get_macro_feed

        feed = get_macro_feed()
        snap = await feed.refresh_async()
        n = _push_snapshot_to_store(snap)
        snap["macro_store_series_updated"] = n
        snap["source"] = "fred_live"
        return snap
    except Exception as fred_exc:
        logger.warning("FRED fetch failed, trying MacroStore cache: %s", fred_exc)

    # 2. MacroStore cached values
    store = _get_macro_store()
    if store is not None and len(store) > 0:
        try:
            snap_store = store.snapshot()
            snap: dict[str, Any] = {
                "dxy": None,
                "yield_10y": None,
                "yield_2y": None,
                "yield_spread": None,
                "cpi_latest": None,
                "cpi_yoy_pct": None,
                "macro_regime_score": 50,
                "macro_stance": "neutral",
                "refreshed_at": datetime.now(UTC).isoformat(),
                "source": "macro_store_cache",
            }
            key_map = {
                "dxy": "dxy",
                "us10y": "yield_10y",
                "us2y": "yield_2y",
                "yield_spread": "yield_spread",
                "cpi_surprise": "cpi_latest",
            }
            for store_key, snap_key in key_map.items():
                entry = snap_store.get(store_key)
                if entry and entry.get("value") is not None:
                    snap[snap_key] = entry["value"]
            y10 = snap.get("yield_10y")
            y2 = snap.get("yield_2y")
            if y10 is not None and y2 is not None:
                snap["yield_spread"] = round(y10 - y2, 4)
            return snap
        except Exception as store_exc:
            logger.warning("MacroStore fallback failed: %s", store_exc)

    # 3. No-data response — all values null so callers know data is absent.
    # Do NOT substitute hardcoded numbers here; stale guesses would silently
    # corrupt ML features and regime scoring.  Consumers must handle null.
    logger.info("Returning null macro fallback. Set FRED_API_KEY in .env for live data.")
    return {
        "dxy": None,
        "yield_10y": None,
        "yield_2y": None,
        "yield_spread": None,
        "cpi_latest": None,
        "cpi_yoy_pct": None,
        "macro_regime_score": None,
        "macro_stance": "unavailable",
        "refreshed_at": datetime.now(UTC).isoformat(),
        "source": "no_data",
        "note": (
            "FRED data unavailable and no cached values exist. "
            "Set FRED_API_KEY in .env to enable live macro data. "
            "All fields are null — do not use for trading decisions."
        ),
    }


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
        logger.warning("macro refresh failed (FRED unavailable): %s", exc)
        return {
            "status": "unavailable",
            "error": "FRED fetch failed — check server logs for details",
            "note": "FRED fetch failed. Set FRED_API_KEY in .env for live data.",
        }


@router.get("/features", summary="Macro features for ML inference")
async def macro_features(user: TokenPayload = Depends(get_current_user)):
    """
    Return macro values as a flat dict of floats ready to merge into
    the ML feature matrix.  All keys are prefixed with 'macro_'.

    Prefers MacroStore (which may have more series than FRED alone) and
    falls back to MacroFeed if the store is empty.
    """
    store = _get_macro_store()
    if store is not None and len(store) > 0:
        snap = store.snapshot()
        features: dict[str, float] = {}
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
        # Log the full exception server-side. Suppress the chain (from None) so
        # the original exception object is not attached to the HTTPException and
        # cannot be serialised into the response by any middleware.
        logger.warning("macro features failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Macro features unavailable — check server logs",
        ) from None


@router.get("/store", summary="MacroStore snapshot — all loaded series with latest values")
async def macro_store_snapshot(user: TokenPayload = Depends(get_current_user)):
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
async def macro_store_update(
    req: MacroUpdateRequest = Body(...),
    user: TokenPayload = Depends(require_role("admin")),
):
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
        # Log the full exception server-side; return a generic detail to avoid
        # leaking internal error messages to API callers.
        logger.warning("MacroStore.update failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="MacroStore update failed — check server logs",
        ) from None


# ── WGC endpoints ─────────────────────────────────────────────────────────────


def _get_wgc_feed():
    """Return the WGCFeed singleton (never raises)."""
    try:
        from data_layer.feeds.macro.wgc import wgc_feed

        return wgc_feed
    except Exception as exc:
        logger.debug("WGCFeed unavailable: %s", exc)
        return None


@router.get(
    "/wgc",
    summary="WGC gold demand snapshot — latest values from MacroStore",
)
async def wgc_snapshot():
    """
    Return the latest World Gold Council gold demand values from MacroStore.

    Series returned:
      wgc_total_demand   — total gold demand (tonnes, quarterly)
      wgc_investment     — bar/coin + ETF investment demand (tonnes, quarterly)
      wgc_central_bank   — central bank net purchases (tonnes, quarterly)
      wgc_jewellery      — jewellery demand (tonnes, quarterly)
      wgc_etf_flow       — ETF net flow (tonnes, monthly)

    Data is sourced from the WGC public download portal (no API key required)
    and cached locally. Values are forward-filled from the last quarterly/
    monthly observation.

    Returns null values when WGC data has not yet been loaded. Call
    /api/macro/wgc/refresh to trigger an immediate fetch.
    """
    store = _get_macro_store()
    wgc_series = [
        "wgc_total_demand",
        "wgc_investment",
        "wgc_central_bank",
        "wgc_jewellery",
        "wgc_etf_flow",
    ]

    result: dict[str, Any] = {
        "refreshed_at": datetime.now(UTC).isoformat(),
        "source": "macro_store",
    }

    if store is not None:
        snap = store.snapshot()
        for key in wgc_series:
            info = snap.get(key)
            result[key] = {
                "value": info["value"] if info else None,
                "date": info["date"] if info else None,
                "observations": info["n_observations"] if info else 0,
            }
    else:
        for key in wgc_series:
            result[key] = {"value": None, "date": None, "observations": 0}

    # Include feed health
    feed = _get_wgc_feed()
    result["feed_health"] = feed.health() if feed else {"loaded": False}

    return result


@router.post(
    "/wgc/refresh",
    summary="Force-refresh WGC gold demand data and inject into MacroStore",
)
async def wgc_refresh():
    """
    Trigger an immediate WGC data fetch, bypassing the local cache TTL.

    Fetches quarterly demand and monthly ETF flow data from WGC's public
    download endpoints and injects all series into MacroStore.

    Use this after manually placing downloaded WGC CSV files in WGC_CACHE_DIR,
    or to force a refresh outside the daily 18:00 UTC schedule.
    """
    feed = _get_wgc_feed()
    if feed is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="WGCFeed not available",
        )
    try:
        status_dict = await feed.fetch_and_inject()
        return {"status": "refreshed", **status_dict}
    except Exception as exc:
        logger.warning("WGC refresh failed: %s", exc)
        return {
            "status": "error",
            "error": "WGC fetch failed — check server logs for details",
            "note": (
                "WGC fetch failed. Check WGC_CACHE_DIR or place CSV files manually. "
                "See data_layer/feeds/macro/wgc.py for download instructions."
            ),
        }


@router.get(
    "/wgc/health",
    summary="WGC feed health — cache status and loaded series",
)
async def wgc_health():
    """
    Return WGC feed health: cache directory, last fetch time, and per-series
    observation counts and latest values.

    Used by the admin dashboard to verify WGC data is flowing into the
    signal engine.
    """
    feed = _get_wgc_feed()
    if feed is None:
        return {"status": "unavailable", "loaded": False}
    return {"status": "ok", **feed.health()}

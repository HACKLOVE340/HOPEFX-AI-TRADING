# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# AGPL-3.0 — Share all modifications
"""
api/superadmin/health_engine_api.py
=====================================
SuperAdmin REST endpoints for the auto-discovering Health Engine.

Routes
------
GET  /superadmin/health-engine/status          — full health report (all probes)
GET  /superadmin/health-engine/probes          — list registered probe names
POST /superadmin/health-engine/probe/{name}    — run a single named probe
POST /superadmin/health-engine/run             — run a subset of probes
GET  /superadmin/health-engine/history         — last N reports from Redis
POST /superadmin/health-engine/register        — register a custom probe URL
"""

from __future__ import annotations

import json
import logging
import time
from datetime import timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request

from api.superadmin._shared import TokenPayload, _require_superadmin

logger = logging.getLogger(__name__)
router = APIRouter()
UTC = timezone.utc

_HISTORY_KEY = "superadmin:health_engine:history"
_HISTORY_MAX = 50


def _get_engine():
    from infrastructure.health_engine import get_health_engine
    return get_health_engine()


def _redis():
    try:
        from cache.redis_client import get_redis_client
        return get_redis_client()
    except Exception:
        return None


def _push_history(report_dict: dict[str, Any]) -> None:
    rc = _redis()
    if not rc:
        return
    try:
        rc.lpush(_HISTORY_KEY, json.dumps(report_dict))
        rc.ltrim(_HISTORY_KEY, 0, _HISTORY_MAX - 1)
    except Exception:
        logger.debug("Suppressed non-fatal exception", exc_info=True)  # nosec B110


@router.get("/health-engine/status")
async def health_engine_status(
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    """Run all registered probes and return a full health report."""
    engine = _get_engine()
    report = await engine.run_all()
    result = report.to_dict()
    _push_history(result)
    return result


@router.get("/health-engine/probes")
async def list_probes(
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    """List all registered probe names."""
    engine = _get_engine()
    return {"probes": engine.probe_names, "count": len(engine.probe_names)}


@router.post("/health-engine/probe/{name}")
async def run_single_probe(
    name: str,
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    """Run a single named probe immediately."""
    engine = _get_engine()
    if name not in engine.probe_names:
        raise HTTPException(status_code=404, detail=f"Probe '{name}' not registered")
    result = await engine.probe_one(name)
    return result.to_dict()


@router.post("/health-engine/run")
async def run_subset(
    request: Request,
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    """Run a subset of probes.  Body: {"probes": ["database", "redis", ...]}"""
    body = await request.json()
    names: list[str] = body.get("probes", [])
    engine = _get_engine()
    if not names:
        names = engine.probe_names
    report = await engine.run_all(names=names)
    return report.to_dict()


@router.get("/health-engine/history")
async def get_history(
    limit: int = 10,
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    """Return the last N health reports stored in Redis."""
    rc = _redis()
    if not rc:
        return {"entries": [], "count": 0, "note": "Redis unavailable"}
    try:
        raw_list = rc.lrange(_HISTORY_KEY, 0, min(limit, _HISTORY_MAX) - 1)
        entries = []
        for raw in raw_list:
            try:
                entries.append(json.loads(raw))
            except Exception:
                logger.debug("Suppressed non-fatal exception", exc_info=True)  # nosec B110
        return {"entries": entries, "count": len(entries)}
    except Exception as exc:
        return {"entries": [], "count": 0, "error": str(exc)}


@router.post("/health-engine/register")
async def register_url_probe(
    request: Request,
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    """
    Register a custom HTTP probe.
    Body: {"name": "my_service", "label": "My Service", "url": "http://...", "method": "GET"}
    """
    body = await request.json()
    name: str = body.get("name", "")
    label: str = body.get("label", name)
    url: str = body.get("url", "")
    method: str = body.get("method", "GET").upper()

    if not name or not url:
        raise HTTPException(status_code=422, detail="name and url are required")

    import httpx

    async def _url_probe() -> dict[str, Any]:
        t0 = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.request(method, url)
            latency_ms = round((time.perf_counter() - t0) * 1000, 2)
            ok = resp.status_code < 400
            return {
                "status": "ok" if ok else "error",
                "detail": f"HTTP {resp.status_code}",
                "http_status": resp.status_code,
                "latency_ms": latency_ms,
            }
        except Exception as exc:
            return {"status": "error", "detail": str(exc)}

    engine = _get_engine()
    engine.register(name, label, _url_probe)
    return {"registered": True, "name": name, "label": label, "url": url}

# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
Nuclear Supervisor API Router

Exposes status, manual resume, and escalation controls for the
NuclearHopeFXSupervisor and RiskOrchestrator.

All state-mutating endpoints require the "admin" role.
Read-only status endpoints require the "trader" role.

This router carries no prefix — the prefix "/nuclear" is supplied by
core/router_registry.py at mount time:

    _include_router_deduped(app, nuclear_router,
                            prefix="/nuclear", tags=["nuclear"])

Resulting paths: /nuclear/status, /nuclear/resume, /nuclear/set_risk,
/nuclear/hedge/activate, /nuclear/hedge/deactivate, /nuclear/history,
/nuclear/kill_switch/activate, /nuclear/kill_switch/deactivate
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from api.auth import TokenPayload, require_role

logger = logging.getLogger(__name__)

router = APIRouter()


# ── Request / response models ─────────────────────────────────────────────────


class NuclearResumeRequest(BaseModel):
    """Body for POST /nuclear/resume."""

    deactivation_token: str | None = Field(
        default=None,
        description=(
            "Kill switch deactivation token (value of HOPEFX_KILL_SWITCH_TOKEN). "
            "Required when a token is configured on the kill switch."
        ),
    )


class NuclearSetRiskRequest(BaseModel):
    """Body for POST /nuclear/set_risk."""

    fraction: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Max-risk fraction [0, 1]. 0 = no new positions.",
    )


class NuclearHedgeRequest(BaseModel):
    """Body for POST /nuclear/hedge/activate."""

    symbol: str = Field(default="XAU_USD", description="Symbol to hedge.")


# ── Lazy dependency helpers ───────────────────────────────────────────────────


def _get_supervisor():
    try:
        from brain.nuclear_supervisor import get_nuclear_supervisor

        return get_nuclear_supervisor()
    except Exception as exc:
        logger.error("Nuclear supervisor unavailable: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Nuclear supervisor unavailable — check server logs",
        ) from None


def _get_orchestrator():
    try:
        from risk.orchestrator import risk_orchestrator

        return risk_orchestrator
    except Exception as exc:
        logger.error("Risk orchestrator unavailable: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Risk orchestrator unavailable — check server logs",
        ) from None


def _get_kill_switch():
    try:
        from kill_switch import kill_switch

        return kill_switch
    except Exception as exc:
        logger.error("Kill switch unavailable: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Kill switch unavailable — check server logs",
        ) from None


# ── Endpoints ─────────────────────────────────────────────────────────────────


@router.get(
    "/snapshot",
    summary="Real-time NuclearChartState snapshot (HTTP polling fallback)",
    response_model=dict[str, Any],
)
async def get_nuclear_chart_snapshot():
    """
    Return the current NuclearChartState from the charting engine.
    Use this as an HTTP fallback when the /ws/nuclear WebSocket is unavailable.
    """
    try:
        from charting.nuclear_ai_chart_engine import get_chart_engine

        engine = get_chart_engine()
        return engine.get_snapshot()
    except Exception:
        return {"status": "unavailable", "nuclear_level": 0}


@router.post(
    "/event",
    summary="Inject a news event for immediate nuclear scoring",
    response_model=dict[str, Any],
)
async def inject_nuclear_event(
    body: dict[str, Any],
    _user: TokenPayload = Depends(require_role("admin")),
):
    """
    Inject a news event into the nuclear chart engine for immediate scoring.
    Body: { "text": "...", "volatility": 1.0, "sentiment": 0.0 }
    """
    text = body.get("text", "")
    if not text:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="text is required")
    try:
        from charting.nuclear_ai_chart_engine import get_chart_engine

        engine = get_chart_engine()
        result = engine.inject_news_event(
            text,
            float(body.get("volatility", 1.0)),
            float(body.get("sentiment", 0.0)),
        )
        return result
    except Exception as exc:
        raise HTTPException(status_code=500, detail="Event injection failed — check server logs") from exc


@router.get(
    "/status",
    summary="Nuclear supervisor + risk orchestrator status",
    response_model=dict[str, Any],
)
async def get_nuclear_status(
    _user: TokenPayload = Depends(require_role("trader")),
):
    """
    Return a combined snapshot of:
    - NuclearHopeFXSupervisor state (nuclear_level, trading_paused, monitoring_only, …)
    - RiskOrchestrator state (max_risk_fraction, hedge_active, hedge_positions, …)
    - KillSwitch state (active, reason, activated_at)
    """
    supervisor = _get_supervisor()
    orchestrator = _get_orchestrator()
    ks = _get_kill_switch()

    return {
        "supervisor": supervisor.get_status(),
        "orchestrator": orchestrator.get_status(),
        "kill_switch": ks.status(),
    }


@router.post(
    "/resume",
    summary="Manually resume trading after nuclear halt",
    response_model=dict[str, Any],
)
async def manual_resume(
    req: NuclearResumeRequest,
    _user: TokenPayload = Depends(require_role("admin")),
):
    """
    Deactivate the kill switch, restore the risk budget to 100 %, close
    hedges, and exit monitoring-only mode.

    Requires the ``deactivation_token`` when ``HOPEFX_KILL_SWITCH_TOKEN``
    is configured.  Returns 403 if the token is wrong or missing.
    """
    supervisor = _get_supervisor()
    try:
        await supervisor.manual_resume(deactivation_token=req.deactivation_token)
    except PermissionError as exc:
        logger.warning("manual_resume permission denied: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permission denied",
        ) from None
    except Exception as exc:
        logger.error("manual_resume failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Resume failed — check server logs",
        ) from None

    return {
        "status": "resumed",
        "supervisor": supervisor.get_status(),
    }


@router.post(
    "/set_risk",
    summary="Override the global max-risk fraction",
    response_model=dict[str, Any],
)
async def set_max_risk(
    req: NuclearSetRiskRequest,
    _user: TokenPayload = Depends(require_role("admin")),
):
    """
    Directly set the RiskOrchestrator max-risk fraction.
    0.0 = no new positions (nuclear mode).
    1.0 = full budget restored.
    """
    orchestrator = _get_orchestrator()
    await orchestrator.set_max_risk(req.fraction)
    return {
        "status": "ok",
        "max_risk": orchestrator.get_max_risk(),
        "trading_allowed": orchestrator.is_trading_allowed(),
    }


@router.post(
    "/hedge/activate",
    summary="Activate hedge mode on a symbol",
    response_model=dict[str, Any],
)
async def activate_hedge(
    req: NuclearHedgeRequest,
    _user: TokenPayload = Depends(require_role("admin")),
):
    """Open an inverse hedge position on the given symbol."""
    orchestrator = _get_orchestrator()
    await orchestrator.activate_hedge_mode(req.symbol)
    return {
        "status": "ok",
        "hedge_active": orchestrator._hedge_active,
        "hedge_positions": len(orchestrator._hedge_positions),
    }


@router.post(
    "/hedge/deactivate",
    summary="Deactivate hedge mode and close all hedge positions",
    response_model=dict[str, Any],
)
async def deactivate_hedge(
    _user: TokenPayload = Depends(require_role("admin")),
):
    """Close all open hedge positions and restore normal mode."""
    orchestrator = _get_orchestrator()
    await orchestrator.deactivate_hedge_mode()
    return {
        "status": "ok",
        "hedge_active": orchestrator._hedge_active,
    }


@router.get(
    "/history",
    summary="Last N nuclear supervisor events",
    response_model=dict[str, Any],
)
async def get_event_history(
    n: int = 20,
    _user: TokenPayload = Depends(require_role("trader")),
):
    """Return the last ``n`` events processed by the nuclear supervisor."""
    supervisor = _get_supervisor()
    return {
        "events": supervisor.get_event_history(n=n),
        "total": len(supervisor._event_history),
    }


@router.post(
    "/kill_switch/activate",
    summary="Manually activate the kill switch",
    response_model=dict[str, Any],
)
async def activate_kill_switch(
    reason: str = "manual activation via API",
    _user: TokenPayload = Depends(require_role("admin")),
):
    """Immediately halt all trading by activating the kill switch."""
    ks = _get_kill_switch()
    ks.activate(reason)
    return {"status": "activated", "kill_switch": ks.status()}


@router.post(
    "/kill_switch/deactivate",
    summary="Deactivate the kill switch",
    response_model=dict[str, Any],
)
async def deactivate_kill_switch(
    token: str | None = None,
    _user: TokenPayload = Depends(require_role("admin")),
):
    """
    Deactivate the kill switch directly (without going through the supervisor).
    Use ``/nuclear/resume`` for the full resume flow including risk restoration.
    """
    ks = _get_kill_switch()
    try:
        ks.deactivate(token=token)
    except PermissionError as exc:
        logger.warning("kill switch deactivation permission denied: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permission denied",
        ) from None
    return {"status": "deactivated", "kill_switch": ks.status()}

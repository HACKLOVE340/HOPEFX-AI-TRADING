# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
api/alerts.py
=============
Price alert REST endpoints.

Adapts the frontend's { conditions: [...], notification_channels: [...] } shape
to the AlertEngine's flat condition_type / notify_channels interface.

Registered in app.py as a static router (prefix /api/alerts) so it is always
available even when the lifespan-registered alert_engine router is not.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from api.auth import TokenPayload, get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/alerts", tags=["Alerts"])


# ── Request / response models ─────────────────────────────────────────────────


class AlertConditionIn(BaseModel):
    type: str
    threshold: float
    threshold_2: float | None = None


class CreateAlertIn(BaseModel):
    name: str
    symbol: str
    conditions: list[AlertConditionIn]
    notification_channels: list[str] = ["discord"]
    priority: str = "high"
    expires_in_hours: int | None = None
    cooldown_minutes: int = 5
    max_triggers: int = 0


# ── Helpers ───────────────────────────────────────────────────────────────────


_fallback_engine = None  # lazy-init when startup factory hasn't run


def _get_engine(request: Request):
    """
    Retrieve the AlertEngine.

    Check order:
    1. app_state.alert_engine  — set by the startup factory (primary)
    2. request.app.state.alert_engine — legacy location
    3. Lazy-init a minimal AlertEngine so the endpoint never 503s
    """
    global _fallback_engine

    # 1. app_state (primary — set by startup_factories.init_alert_engine)
    try:
        from app import app_state

        engine = getattr(app_state, "alert_engine", None)
        if engine is not None:
            return engine
    except Exception as _exc:
        logger.debug("Suppressed exception: %s", _exc)

    # 2. request.app.state (legacy)
    engine = getattr(request.app.state, "alert_engine", None)
    if engine is not None:
        return engine

    # 3. Lazy-init a minimal AlertEngine so the endpoint is always usable
    if _fallback_engine is None:
        try:
            from notifications.alert_engine import AlertEngine

            _fallback_engine = AlertEngine(config={})
            logger.info("AlertEngine: lazy-initialised fallback instance")
        except Exception as exc:
            logger.error("Alert engine unavailable: %s", exc)
            raise HTTPException(
                status_code=503,
                detail="Alert engine unavailable — check server logs",
            ) from None
    return _fallback_engine


def _serialise(alert) -> dict[str, Any]:
    """Convert an Alert dataclass / object to a JSON-safe dict."""
    d = alert.to_dict() if hasattr(alert, "to_dict") else dict(alert.__dict__)

    # Normalise enum values to strings
    for key in ("status", "priority"):
        if key in d and hasattr(d[key], "value"):
            d[key] = d[key].value

    # Normalise conditions to the frontend's [{type, threshold}] shape
    if "condition_type" in d and "conditions" not in d:
        d["conditions"] = [
            {
                "type": d["condition_type"].value if hasattr(d["condition_type"], "value") else d["condition_type"],
                "threshold": d.get("threshold", 0),
            },
        ]

    # Normalise notification channels key
    if "notify_channels" in d and "notification_channels" not in d:
        d["notification_channels"] = d.pop("notify_channels")

    # Ensure trigger_count exists
    d.setdefault("trigger_count", d.get("trigger_count", 0))

    return d


# ── Endpoints ─────────────────────────────────────────────────────────────────


@router.post("/")
async def create_alert(
    body: CreateAlertIn,
    request: Request,
    user: TokenPayload = Depends(get_current_user),
):
    """Create a price alert. Requires: authenticated user."""
    engine = _get_engine(request)

    if not body.conditions:
        raise HTTPException(status_code=400, detail="At least one condition required")

    first = body.conditions[0]

    try:
        from notifications.alert_engine import AlertConditionType, AlertPriority

        condition_type = AlertConditionType(first.type)
        priority = AlertPriority(body.priority)
    except ValueError as exc:
        logger.warning("create_alert validation error: %s", exc)
        raise HTTPException(status_code=400, detail="Invalid condition type or priority") from None

    alert = engine.create_alert(
        name=body.name,
        symbol=body.symbol,
        condition_type=condition_type,
        threshold=first.threshold,
        threshold_2=first.threshold_2,
        priority=priority,
        notify_channels=body.notification_channels,
        expires_in_hours=body.expires_in_hours,
        cooldown_minutes=body.cooldown_minutes,
        max_triggers=body.max_triggers,
    )
    return _serialise(alert)


@router.get("/")
async def list_alerts(
    request: Request,
    symbol: str | None = None,
    status: str | None = None,
    user: TokenPayload = Depends(get_current_user),
):
    """List all alerts, optionally filtered by symbol or status. Requires: authenticated user."""
    engine = _get_engine(request)

    try:
        from notifications.alert_engine import AlertStatus

        status_enum = AlertStatus(status) if status else None
    except ValueError:
        status_enum = None

    alerts = engine.get_alerts(symbol=symbol, status=status_enum)
    return [_serialise(a) for a in alerts]


@router.get("/history/triggers")
async def get_trigger_history(
    request: Request,
    symbol: str | None = None,
    alert_id: str | None = None,
    limit: int = 50,
    user: TokenPayload = Depends(get_current_user),
):
    """Return the last N alert trigger events. Requires: authenticated user."""
    engine = _get_engine(request)
    history = engine.get_trigger_history(symbol, alert_id, limit)
    # history items are plain dicts from the engine
    return history if isinstance(history, list) else []


@router.get("/active")
async def get_active_alerts(
    request: Request,
    symbol: str | None = None,
    user: TokenPayload = Depends(get_current_user),
):
    """Return only active (non-paused, non-expired) alerts. Requires: authenticated user."""
    engine = _get_engine(request)
    alerts = engine.get_active_alerts(symbol)
    return [_serialise(a) for a in alerts]


@router.get("/{alert_id}")
async def get_alert(
    alert_id: str,
    request: Request,
    user: TokenPayload = Depends(get_current_user),
):
    """Get a single alert by ID. Requires: authenticated user."""
    engine = _get_engine(request)
    alert = engine.get_alert(alert_id)
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")
    return _serialise(alert)


@router.delete("/{alert_id}")
async def delete_alert(
    alert_id: str,
    request: Request,
    user: TokenPayload = Depends(get_current_user),
):
    """Delete an alert. Requires: authenticated user."""
    engine = _get_engine(request)
    if not engine.delete_alert(alert_id):
        raise HTTPException(status_code=404, detail="Alert not found")
    return {"status": "deleted"}


@router.post("/{alert_id}/pause")
async def pause_alert(
    alert_id: str,
    request: Request,
    user: TokenPayload = Depends(get_current_user),
):
    """Pause an alert. Requires: authenticated user."""
    engine = _get_engine(request)
    if not engine.pause_alert(alert_id):
        raise HTTPException(status_code=404, detail="Alert not found")
    return {"status": "paused"}


@router.post("/{alert_id}/resume")
async def resume_alert(
    alert_id: str,
    request: Request,
    user: TokenPayload = Depends(get_current_user),
):
    """Resume a paused alert. Requires: authenticated user."""
    engine = _get_engine(request)
    if not engine.resume_alert(alert_id):
        raise HTTPException(status_code=404, detail="Alert not found")
    return {"status": "resumed"}

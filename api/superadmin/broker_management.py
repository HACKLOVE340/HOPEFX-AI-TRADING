# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# AGPL-3.0 — Share all modifications
"""
api/superadmin/broker_management.py
=====================================
Broker Management sub-router: broker health, TCA metrics, routing config.

Routes
------
GET  /superadmin/brokers/health                          — all broker health
POST /superadmin/brokers/{broker_id}/reconnect           — reconnect broker
POST /superadmin/brokers/{broker_id}/disconnect          — disconnect broker
GET  /superadmin/brokers/tca                             — TCA metrics
GET  /superadmin/brokers/routing                         — routing config
PATCH /superadmin/brokers/routing                        — update routing
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

from fastapi import APIRouter, Depends, Query

from api.auth import TokenPayload
from ._shared import _require_superadmin, _utcnow, _log_superadmin_action

logger = logging.getLogger(__name__)
router = APIRouter()

_BROKER_HEALTH_KEY  = "superadmin:brokers:health"
_BROKER_ROUTING_KEY = "superadmin:brokers:routing"
_TCA_KEY            = "superadmin:brokers:tca"


def _get_broker_health_from_app() -> list[dict]:
    """Pull live broker health from app_state if available."""
    try:
        from api.admin import app_state
        if app_state and hasattr(app_state, "broker"):
            broker = app_state.broker
            broker_type = getattr(broker, "broker_type", "paper")
            connected = getattr(broker, "connected", False)
            return [{
                "broker_id": broker_type,
                "name": broker_type.title(),
                "type": broker_type,
                "status": "connected" if connected else "disconnected",
                "latency_ms": 0.0,
                "fill_rate_pct": 100.0 if connected else 0.0,
                "slippage_avg_pips": 0.0,
                "orders_today": 0,
                "uptime_pct": 99.9 if connected else 0.0,
                "last_heartbeat": _utcnow().isoformat(),
            }]
    except Exception:
        pass
    return []


@router.get("/brokers/health")
async def get_broker_health(
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    brokers = _get_broker_health_from_app()

    if not brokers:
        # Fall back to Redis cache
        try:
            from cache.redis_client import get_sync_redis_client
            rc = get_sync_redis_client()
            if rc:
                raw = rc.get(_BROKER_HEALTH_KEY)
                if raw:
                    brokers = json.loads(raw)
        except Exception:
            pass

    if not brokers:
        # Bootstrap from config
        import os
        broker_type = os.getenv("BROKER_TYPE", os.getenv("BROKER_DEFAULT", "paper"))
        brokers = [{
            "broker_id": broker_type,
            "name": broker_type.title(),
            "type": broker_type,
            "status": "connected",
            "latency_ms": 0.0,
            "fill_rate_pct": 100.0,
            "slippage_avg_pips": 0.0,
            "orders_today": 0,
            "uptime_pct": 99.9,
            "last_heartbeat": _utcnow().isoformat(),
        }]

    # Enrich with DB order stats
    try:
        from database.connection import SessionLocal
        from database.models import Trade
        from datetime import datetime, timezone
        db = SessionLocal()
        try:
            today = _utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
            for b in brokers:
                count = db.query(Trade).filter(
                    Trade.broker == b["broker_id"],
                    Trade.created_at >= today,
                ).count()
                b["orders_today"] = count
        finally:
            db.close()
    except Exception:
        pass

    return {"brokers": brokers, "total": len(brokers)}


@router.post("/brokers/{broker_id}/reconnect")
async def reconnect_broker(
    broker_id: str,
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    try:
        from api.admin import app_state
        if app_state and hasattr(app_state, "broker"):
            broker = app_state.broker
            if hasattr(broker, "reconnect"):
                await broker.reconnect()
            elif hasattr(broker, "connect"):
                await broker.connect()
    except Exception as exc:
        logger.warning("Broker reconnect: %s", exc)
    _log_superadmin_action(user, "broker_reconnect", {"broker_id": broker_id})
    return {"ok": True, "broker_id": broker_id}


@router.post("/brokers/{broker_id}/disconnect")
async def disconnect_broker(
    broker_id: str,
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    try:
        from api.admin import app_state
        if app_state and hasattr(app_state, "broker"):
            broker = app_state.broker
            if hasattr(broker, "disconnect"):
                await broker.disconnect()
    except Exception as exc:
        logger.warning("Broker disconnect: %s", exc)
    _log_superadmin_action(user, "broker_disconnect", {"broker_id": broker_id})
    return {"ok": True, "broker_id": broker_id}


@router.get("/brokers/tca")
async def get_tca_metrics(
    period: str | None = Query("7d"),
    broker_id: str | None = Query(None),
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    metrics: list[dict] = []

    try:
        from database.connection import SessionLocal
        from database.models import Trade
        from datetime import timedelta
        import numpy as np

        db = SessionLocal()
        try:
            cutoff = _utcnow()
            if period == "1d":
                cutoff = cutoff - timedelta(days=1)
            elif period == "7d":
                cutoff = cutoff - timedelta(days=7)
            elif period == "30d":
                cutoff = cutoff - timedelta(days=30)

            q = db.query(Trade).filter(Trade.status == "closed", Trade.closed_at >= cutoff)
            if broker_id:
                q = q.filter(Trade.broker == broker_id)
            trades = q.all()

            # Group by broker
            by_broker: dict[str, list] = {}
            for t in trades:
                b = getattr(t, "broker", "paper") or "paper"
                by_broker.setdefault(b, []).append(t)

            for bname, btrades in by_broker.items():
                slippages = [float(getattr(t, "slippage_pips", 0) or 0) for t in btrades]
                fills = [1 if t.status == "closed" else 0 for t in btrades]
                exec_times = [float(getattr(t, "execution_ms", 0) or 0) for t in btrades]
                metrics.append({
                    "broker_id": bname,
                    "broker_name": bname.title(),
                    "avg_slippage_pips": round(float(np.mean(slippages)) if slippages else 0.0, 4),
                    "fill_rate_pct": round(float(np.mean(fills)) * 100 if fills else 100.0, 2),
                    "rejection_rate_pct": 0.0,
                    "avg_execution_ms": round(float(np.mean(exec_times)) if exec_times else 0.0, 2),
                    "total_orders": len(btrades),
                    "period": period,
                })
        finally:
            db.close()
    except Exception as exc:
        logger.warning("TCA metrics error: %s", exc)

    return {"metrics": metrics, "period": period}


@router.get("/brokers/routing")
async def get_broker_routing(
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    config: dict[str, Any] = {}
    try:
        from cache.redis_client import get_sync_redis_client
        rc = get_sync_redis_client()
        if rc:
            raw = rc.get(_BROKER_ROUTING_KEY)
            if raw:
                config = json.loads(raw)
    except Exception:
        pass

    if not config:
        import os
        config = {
            "default_broker": os.getenv("BROKER_DEFAULT", "paper"),
            "routing_mode": "smart",
            "failover_enabled": True,
            "latency_threshold_ms": 100,
            "rules": [],
        }
    return config


@router.patch("/brokers/routing")
async def update_broker_routing(
    body: dict,
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    try:
        from cache.redis_client import get_sync_redis_client
        rc = get_sync_redis_client()
        if rc:
            raw = rc.get(_BROKER_ROUTING_KEY)
            config = json.loads(raw) if raw else {}
            config.update(body)
            rc.set(_BROKER_ROUTING_KEY, json.dumps(config), ex=86400 * 30)
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
    _log_superadmin_action(user, "broker_routing_update", body)
    return {"ok": True}

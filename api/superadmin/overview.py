# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""SuperAdmin overview sub-router."""

import logging
from typing import Any

from fastapi import APIRouter, Depends

from api.auth import TokenPayload

from ._shared import _get_config_store, _require_superadmin, _utcnow

logger = logging.getLogger(__name__)

router = APIRouter()

# ── Overview ──────────────────────────────────────────────────────────────────


@router.get("/overview")
async def get_overview(user: TokenPayload = Depends(_require_superadmin)) -> dict[str, Any]:
    """Platform-wide health snapshot."""
    overview: dict[str, Any] = {
        "total_users": 0,
        "active_users_24h": 0,
        "new_users_7d": 0,
        "total_trades_today": 0,
        "open_positions": 0,
        "revenue_mtd": 0.0,
        "revenue_currency": "USD",
        "system_health": "healthy",
        "uptime_pct": 99.9,
        "active_sessions": 0,
        "ml_model_accuracy": 0.0,
        "signals_generated_today": 0,
        "engine_status": "running",
        "kill_switch_active": False,
        "maintenance_mode": False,
        "db_connections": 0,
        "redis_memory_mb": 0.0,
        "cpu_pct": 0.0,
        "memory_pct": 0.0,
        "error_rate_pct": 0.0,
        "avg_response_ms": 0,
    }

    # User counts from DB
    try:
        from database.connection import SessionLocal
        from database.user_models import User
        from datetime import timedelta

        db = SessionLocal()
        try:
            now = _utcnow()
            overview["total_users"] = db.query(User).count()
            overview["active_users_24h"] = (
                db.query(User).filter(User.last_login_at >= now - timedelta(hours=24)).count()
            )
            overview["new_users_7d"] = db.query(User).filter(User.created_at >= now - timedelta(days=7)).count()
        finally:
            db.close()
    except Exception as exc:
        logger.debug("overview: DB unavailable: %s", exc)

    # Kill switch + maintenance from config store
    try:
        cs = _get_config_store()
        if cs:
            ks = cs.get("kill_switch_active")
            if ks is not None:
                overview["kill_switch_active"] = bool(ks)
            mm = cs.get("maintenance_mode")
            if mm is not None:
                overview["maintenance_mode"] = bool(mm)
    except Exception:
        logger.debug("Suppressed exception (no detail) in %s", __name__)

    # Engine status
    try:
        from api.admin import app_state

        if app_state and hasattr(app_state, "engine"):
            eng = app_state.engine
            overview["engine_status"] = getattr(eng, "status", "running")
            overview["open_positions"] = len(getattr(eng, "positions", {}))
    except Exception:
        logger.debug("Suppressed exception (no detail) in %s", __name__)

    # Redis memory
    try:
        from cache.redis_client import get_redis_client

        rc = get_redis_client()
        if rc:
            info = rc.info("memory")
            overview["redis_memory_mb"] = round(info.get("used_memory", 0) / 1_048_576, 1)
    except Exception:
        logger.debug("Suppressed exception (no detail) in %s", __name__)

    # System resources
    try:
        import psutil

        overview["cpu_pct"] = psutil.cpu_percent(interval=0.1)
        overview["memory_pct"] = psutil.virtual_memory().percent
    except Exception:
        logger.debug("Suppressed exception (no detail) in %s", __name__)

    # Determine health
    if overview["kill_switch_active"] or overview["error_rate_pct"] > 10:
        overview["system_health"] = "critical"
    elif overview["maintenance_mode"] or overview["cpu_pct"] > 85 or overview["memory_pct"] > 85:
        overview["system_health"] = "degraded"

    return overview

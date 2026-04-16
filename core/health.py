# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
core/health.py
==============
Health and status check logic extracted from app.py.

Register with:
    from core.health import register_health_routes
    register_health_routes(app, app_state, kill_switch)
"""

from __future__ import annotations

import logging
import os
from typing import Any

from fastapi import FastAPI
from pydantic import BaseModel

logger = logging.getLogger(__name__)


class HealthResponse(BaseModel):
    status: str
    version: str
    environment: str
    components: dict


class StatusResponse(BaseModel):
    application: str
    version: str
    environment: str
    config_loaded: bool
    database_connected: bool
    cache_connected: bool
    api_configs: int


def _probe_components(app_state: Any, kill_switch: Any) -> dict:
    """Probe each component and return a status dict."""
    components: dict = {"api": "healthy"}

    components["config"] = "healthy" if app_state.config else "unavailable"

    if app_state.db_engine:
        try:
            from sqlalchemy import text as _text

            with app_state.db_engine.connect() as _conn:
                _conn.execute(_text("SELECT 1"))
            components["database"] = "healthy"
        except Exception as _dbe:
            logger.warning("DB health probe failed: %s", _dbe)
            components["database"] = "degraded"
    else:
        components["database"] = "unavailable"

    if app_state.cache:
        try:
            ok = app_state.cache.health_check() if hasattr(app_state.cache, "health_check") else True
            components["cache"] = "healthy" if ok else "degraded"
        except Exception:  # nosec B110 — health-check availability probe
            components["cache"] = "degraded"
    else:
        components["cache"] = "unavailable"

    components["auth"] = "healthy" if getattr(app_state, "auth_service", None) else "unavailable"
    components["risk_manager"] = "healthy" if getattr(app_state, "risk_manager", None) else "unavailable"
    components["compliance"] = "healthy" if getattr(app_state, "compliance_manager", None) else "unavailable"

    _pe = getattr(app_state, "prop_enforcer", None)
    if _pe is not None:
        _pe_status = _pe.status()
        components["prop_enforcer"] = "halted" if _pe_status.get("halted") else "healthy"
    else:
        components["prop_enforcer"] = "unavailable"

    components["strategy_brain"] = "healthy" if getattr(app_state, "strategy_brain", None) else "unavailable"
    components["websocket"] = "healthy" if getattr(app_state, "ws_manager", None) else "unavailable"

    _sg_key = os.getenv("SENDGRID_API_KEY", "")
    _smtp_host = os.getenv("SMTP_HOST", "")
    _smtp_user = os.getenv("SMTP_USER", "") or os.getenv("SMTP_USERNAME", "")
    if _sg_key or (_smtp_host and _smtp_user):
        components["email"] = "healthy"
    else:
        components["email"] = "unavailable"

    _broker = getattr(app_state, "broker", None)
    if _broker is not None:
        try:
            if hasattr(_broker, "connected"):
                components["broker"] = "healthy" if _broker.connected else "degraded"
            elif hasattr(_broker, "health_check"):
                components["broker"] = "healthy" if _broker.health_check() else "degraded"
            else:
                components["broker"] = "healthy"
        except Exception as _be:
            logger.warning("Broker health probe failed: %s", _be)
            components["broker"] = "degraded"
    else:
        components["broker"] = "unavailable"

    components["kill_switch"] = "active" if kill_switch.is_active() else "healthy"

    return components


def register_health_routes(app: FastAPI, app_state: Any, kill_switch: Any) -> None:
    """Mount /health and /status endpoints on *app*."""

    @app.get("/health", response_model=HealthResponse, tags=["System"])
    async def health_check():
        """Health check — probes each component and reports real status."""
        components = _probe_components(app_state, kill_switch)

        critical = ["api", "config", "database"]
        overall_status = "healthy" if all(components.get(c) == "healthy" for c in critical) else "degraded"
        if kill_switch.is_active():
            overall_status = "degraded"

        return HealthResponse(
            status=overall_status,
            version="2.0.0",
            environment=app_state.config.environment if app_state.config else "unknown",
            components=components,
        )

    @app.get("/api/system/status", response_model=StatusResponse, tags=["System"], include_in_schema=False)
    async def get_status():
        """System status — returns component availability summary (JSON)."""
        cache_connected = False
        if app_state.cache is not None:
            try:
                cache_connected = app_state.cache.health_check() if hasattr(app_state.cache, "health_check") else True
            except Exception as e:
                logger.warning("Cache health check failed: %s", e)

        return StatusResponse(
            application="HOPEFX AI Trading",
            version="1.0.0",
            environment=app_state.config.environment if app_state.config else "unknown",
            config_loaded=app_state.config is not None,
            database_connected=app_state.db_engine is not None,
            cache_connected=cache_connected,
            api_configs=len(app_state.config.api_configs) if app_state.config else 0,
        )

    @app.get("/ready", tags=["System"], include_in_schema=False)
    async def readiness_probe():
        """
        Kubernetes readiness probe — faster than /health.

        Returns 200 only when the application has finished initialising and
        is ready to serve traffic.  The Helm readinessProbe (successThreshold=2)
        requires two consecutive 200s before adding the pod to the Service.

        Checks (in order of cost):
          1. app_state.initialized flag set by startup_event()
          2. Database reachable (SELECT 1)
          3. HOPEFXBrain lockdown not active (pod should not receive traffic
             while a nuclear lockdown is in effect)

        Returns 503 on any failure so Kubernetes removes the pod from rotation.
        """
        from fastapi.responses import JSONResponse as _JSONResponse

        # 1. Startup complete?
        if not getattr(app_state, "initialized", False):
            return _JSONResponse(
                status_code=503,
                content={"ready": False, "reason": "initializing"},
            )

        # 2. Database reachable?
        if app_state.db_engine:
            try:
                from sqlalchemy import text as _text

                with app_state.db_engine.connect() as _conn:
                    _conn.execute(_text("SELECT 1"))
            except Exception as _dbe:
                logger.warning("Readiness: DB probe failed: %s", _dbe)
                return _JSONResponse(
                    status_code=503,
                    content={"ready": False, "reason": "database_unavailable"},
                )

        # 3. Lockdown active? Remove pod from LB during nuclear response.
        try:
            import redis as _redis_sync

            _r = _redis_sync.from_url(
                os.getenv("REDIS_URL", "redis://localhost:6379/0"),
                socket_connect_timeout=1,
                socket_timeout=1,
            )
            lockdown = _r.get("lockdown:active")
            _r.close()
            if lockdown and lockdown.decode() == "true":
                logger.warning("Readiness: lockdown active — pod not ready")
                return _JSONResponse(
                    status_code=503,
                    content={"ready": False, "reason": "lockdown_active"},
                )
        except Exception:  # nosec B110 - Redis unavailable must not block readiness probe
            # Redis unavailable is non-fatal for readiness — don't block traffic
            ...  # nosec B110

        return {"ready": True}

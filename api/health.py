# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
api/health.py
=============
Kubernetes-compatible liveness/readiness probes and component health dashboard.

Endpoints
---------
GET /api/health/live       — liveness probe (always 200 if process is alive)
GET /api/health/ready      — readiness probe; 503 when any CRITICAL component fails
GET /api/health/components — full structured JSON: every component's status + latency
GET /api/health/metrics    — Prometheus-compatible text/plain snapshot

Design invariants
-----------------
- ``/ready`` MUST return 503 (not 200) when any CRITICAL component is degraded.
- No silent degradation — operational failures surface as HTTP errors.
- All checks time-bounded at 5 s to avoid blocking Kubernetes probes.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter
from fastapi.responses import PlainTextResponse, Response
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/health", tags=["Observability"])

_CHECK_TIMEOUT_SEC: float = 5.0
_VERSION: str = os.getenv("APP_VERSION", "unknown")
_SERVICE_NAME: str = os.getenv("OTEL_SERVICE_NAME", "hopefx-trading")

# ── Module-level cached DB engine ─────────────────────────────────────────────
# Creating a new SQLAlchemy engine on every health check is extremely expensive
# (TCP handshake + SSL negotiation + pool creation).  The engine is created once
# and reused; the pool_pre_ping=True flag verifies the connection is alive on
# each use without full reconnect overhead.
_db_engine = None
_db_engine_url: str | None = None
_db_engine_lock: asyncio.Lock | None = None  # asyncio.Lock; safe to use from async coroutines


async def _get_db_engine():
    """Return the module-level DB engine, creating it if necessary.

    Async-safe via double-checked locking with an asyncio.Lock so that
    concurrent Kubernetes health probes do not race during initial creation
    without blocking the event loop.
    """
    global _db_engine, _db_engine_url, _db_engine_lock
    db_url = os.getenv("DATABASE_URL", "")
    if not db_url:
        return None, None
    # Fast path — already initialised for the current URL.
    if _db_engine is not None and _db_engine_url == db_url:
        return _db_engine, db_url

    # Slow path — acquire async lock.
    if _db_engine_lock is None:
        _db_engine_lock = asyncio.Lock()

    async with _db_engine_lock:
        # Re-check inside the lock (double-checked locking).
        if _db_engine is not None and _db_engine_url == db_url:
            return _db_engine, db_url
        try:
            from sqlalchemy.ext.asyncio import create_async_engine  # type: ignore[import]

            _db_engine = create_async_engine(db_url, pool_pre_ping=True, pool_size=1, max_overflow=0)
            _db_engine_url = db_url
            return _db_engine, db_url
        except Exception as exc:
            logger.warning("health.py: could not create DB engine: %s", exc)
            return None, db_url


# ── Pydantic models ────────────────────────────────────────────────────────────


class ComponentStatus(BaseModel):
    """Health status of a single system component."""

    name: str = Field(description="Component identifier")
    status: str = Field(description="healthy | degraded | down | unknown")
    critical: bool = Field(description="Whether degradation causes readiness failure")
    latency_ms: float | None = Field(default=None, description="Check round-trip latency in ms")
    detail: str = Field(default="", description="Human-readable detail / error message")
    version: str | None = Field(default=None, description="Component version if available")


class HealthComponents(BaseModel):
    """Full structured health report for all components."""

    service: str
    version: str
    timestamp: str
    overall: str
    components: list[ComponentStatus]


class ReadinessResponse(BaseModel):
    """Readiness probe response."""

    ready: bool
    timestamp: str
    failed_critical: list[str]
    components: list[ComponentStatus]


# ── Individual component checks ────────────────────────────────────────────────


async def _check_redis() -> ComponentStatus:
    """Ping Redis and return its component status."""
    t0 = time.perf_counter()
    try:
        redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
        import redis.asyncio as aioredis  # type: ignore[import]

        client = aioredis.from_url(redis_url, socket_connect_timeout=2, socket_timeout=2)
        pong = await asyncio.wait_for(client.ping(), timeout=_CHECK_TIMEOUT_SEC)
        await client.aclose()
        latency_ms = (time.perf_counter() - t0) * 1000
        status = "healthy" if pong else "degraded"
        return ComponentStatus(
            name="redis",
            status=status,
            critical=True,
            latency_ms=round(latency_ms, 2),
            detail="PONG received" if pong else "No PONG",
        )
    except Exception as exc:
        latency_ms = (time.perf_counter() - t0) * 1000
        return ComponentStatus(
            name="redis",
            status="down",
            critical=True,
            latency_ms=round(latency_ms, 2),
            detail=str(exc),
        )


async def _check_database() -> ComponentStatus:
    """Ping the relational database via the module-level cached SQLAlchemy engine."""
    t0 = time.perf_counter()
    engine, db_url = await _get_db_engine()
    if engine is None:
        return ComponentStatus(
            name="database",
            status="unknown",
            critical=True,
            detail="DATABASE_URL not set" if not db_url else "Engine creation failed — check logs",
        )
    try:
        from sqlalchemy import text  # type: ignore[import]

        async with engine.connect() as conn:
            await asyncio.wait_for(conn.execute(text("SELECT 1")), timeout=_CHECK_TIMEOUT_SEC)
        latency_ms = (time.perf_counter() - t0) * 1000
        return ComponentStatus(
            name="database",
            status="healthy",
            critical=True,
            latency_ms=round(latency_ms, 2),
            detail="SELECT 1 OK",
        )
    except Exception as exc:
        latency_ms = (time.perf_counter() - t0) * 1000
        return ComponentStatus(
            name="database",
            status="down",
            critical=True,
            latency_ms=round(latency_ms, 2),
            detail=str(exc),
        )


async def _check_kill_switch() -> ComponentStatus:
    """Return degraded/down if the kill switch is active."""
    t0 = time.perf_counter()
    try:
        from kill_switch import kill_switch  # type: ignore[import]

        active = kill_switch.is_active()
        reason = getattr(kill_switch, "_reason", "") if active else ""
        latency_ms = (time.perf_counter() - t0) * 1000
        return ComponentStatus(
            name="kill_switch",
            status="down" if active else "healthy",
            critical=True,
            latency_ms=round(latency_ms, 2),
            detail=f"ACTIVE: {reason}" if active else "inactive",
        )
    except Exception as exc:
        latency_ms = (time.perf_counter() - t0) * 1000
        return ComponentStatus(
            name="kill_switch",
            status="unknown",
            critical=True,
            latency_ms=round(latency_ms, 2),
            detail=str(exc),
        )


async def _check_ml_model() -> ComponentStatus:
    """Check if the primary ML model artifact exists on disk."""
    t0 = time.perf_counter()
    model_path = os.path.join(
        os.path.dirname(os.path.dirname(__file__)),
        "ml",
        "saved_models",
        "advanced_oos.pkl",
    )
    try:
        exists = os.path.isfile(model_path)
        size_kb = round(os.path.getsize(model_path) / 1024, 1) if exists else 0
        latency_ms = (time.perf_counter() - t0) * 1000
        return ComponentStatus(
            name="ml_model",
            status="healthy" if exists else "down",
            critical=True,
            latency_ms=round(latency_ms, 2),
            detail=f"{model_path} ({size_kb} KB)" if exists else f"Not found: {model_path}",
        )
    except Exception as exc:
        latency_ms = (time.perf_counter() - t0) * 1000
        return ComponentStatus(
            name="ml_model",
            status="down",
            critical=True,
            latency_ms=round(latency_ms, 2),
            detail=str(exc),
        )


async def _check_orchestrator() -> ComponentStatus:
    """Check whether the data-layer orchestrator has been started."""
    t0 = time.perf_counter()
    try:
        from data_layer.orchestrator import orchestrator  # type: ignore[import]

        started = getattr(orchestrator, "_started", False)
        latency_ms = (time.perf_counter() - t0) * 1000
        return ComponentStatus(
            name="orchestrator",
            status="healthy" if started else "degraded",
            critical=True,
            latency_ms=round(latency_ms, 2),
            detail="started" if started else "not started — call orchestrator.start()",
        )
    except Exception as exc:
        latency_ms = (time.perf_counter() - t0) * 1000
        return ComponentStatus(
            name="orchestrator",
            status="unknown",
            critical=True,
            latency_ms=round(latency_ms, 2),
            detail=str(exc),
        )


async def _run_all_checks() -> list[ComponentStatus]:
    """Run all component checks concurrently and return results.

    Returns:
        List of :class:`ComponentStatus` objects for each component.
    """
    results = await asyncio.gather(
        _check_redis(),
        _check_database(),
        _check_kill_switch(),
        _check_ml_model(),
        _check_orchestrator(),
        return_exceptions=True,
    )
    statuses: list[ComponentStatus] = []
    names = ["redis", "database", "kill_switch", "ml_model", "orchestrator"]
    for i, result in enumerate(results):
        if isinstance(result, Exception):
            statuses.append(
                ComponentStatus(
                    name=names[i],
                    status="unknown",
                    critical=True,
                    detail=str(result),
                )
            )
        else:
            statuses.append(result)  # type: ignore[arg-type]
    return statuses


# ── Endpoints ──────────────────────────────────────────────────────────────────


@router.get(
    "/live",
    summary="Liveness probe — always 200 if process is alive",
)
async def liveness() -> dict[str, Any]:
    """Kubernetes liveness probe.

    Returns HTTP 200 unconditionally as long as the Python process is running.
    An unhealthy liveness check causes Kubernetes to restart the pod.

    Returns:
        Minimal JSON with ``status`` and ``timestamp``.
    """
    return {
        "status": "alive",
        "service": _SERVICE_NAME,
        "version": _VERSION,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@router.get(
    "/ready",
    response_model=ReadinessResponse,
    summary="Readiness probe — 503 when any critical component is down",
    responses={
        200: {"description": "All critical components healthy"},
        503: {"description": "One or more critical components degraded"},
    },
)
async def readiness() -> Response:
    """Kubernetes readiness probe.

    Returns HTTP 200 when all critical components pass, HTTP 503 otherwise.
    Any traffic routed to the pod while not ready will fail probes.

    Returns:
        :class:`ReadinessResponse` JSON with component status details.
        HTTP 503 (not 200) when any CRITICAL component is down.
    """
    components = await _run_all_checks()
    failed = [c.name for c in components if c.critical and c.status in ("down", "degraded")]
    ready = len(failed) == 0

    body = ReadinessResponse(
        ready=ready,
        timestamp=datetime.now(timezone.utc).isoformat(),
        failed_critical=failed,
        components=components,
    )

    status_code = 200 if ready else 503
    return Response(
        content=body.model_dump_json(),
        status_code=status_code,
        media_type="application/json",
    )


@router.get(
    "/components",
    response_model=HealthComponents,
    summary="Full structured component health report",
)
async def components_report() -> HealthComponents:
    """Return full structured JSON with every component's status, latency, and version.

    Returns:
        :class:`HealthComponents` detailing all system components.
    """
    checks = await _run_all_checks()
    degraded = any(c.status in ("down", "degraded") for c in checks)
    unknown = all(c.status == "unknown" for c in checks)
    overall = "unknown" if unknown else ("degraded" if degraded else "healthy")

    return HealthComponents(
        service=_SERVICE_NAME,
        version=_VERSION,
        timestamp=datetime.now(timezone.utc).isoformat(),
        overall=overall,
        components=checks,
    )


@router.get(
    "/metrics",
    response_class=PlainTextResponse,
    summary="Prometheus-compatible text/plain metrics snapshot",
)
async def prometheus_metrics() -> str:
    """Return a Prometheus-compatible text/plain metrics snapshot.

    Includes component health gauges and basic process metrics.

    Returns:
        Prometheus exposition format string.
    """
    components = await _run_all_checks()

    lines: list[str] = [
        "# HELP hopefx_component_healthy 1 if component is healthy, 0 otherwise",
        "# TYPE hopefx_component_healthy gauge",
    ]
    for comp in components:
        healthy = 1 if comp.status == "healthy" else 0
        lines.append(f'hopefx_component_healthy{{component="{comp.name}",critical="{comp.critical}"}} {healthy}')

    lines += [
        "",
        "# HELP hopefx_component_latency_ms Component health check latency in milliseconds",
        "# TYPE hopefx_component_latency_ms gauge",
    ]
    for comp in components:
        if comp.latency_ms is not None:
            lines.append(f'hopefx_component_latency_ms{{component="{comp.name}"}} {comp.latency_ms}')

    # Process uptime
    try:
        import psutil  # type: ignore[import]

        proc = psutil.Process()
        mem_mb = proc.memory_info().rss / 1024 / 1024
        lines += [
            "",
            "# HELP hopefx_process_rss_mb Process RSS memory in MB",
            "# TYPE hopefx_process_rss_mb gauge",
            f"hopefx_process_rss_mb {mem_mb:.1f}",
        ]
    except ImportError:
        pass  # psutil is optional — skip memory metrics when not installed
    except Exception as exc:
        logger.debug("Failed to collect memory metrics: %s", exc)

    overall_healthy = 1 if all(c.status == "healthy" for c in components) else 0
    lines += [
        "",
        "# HELP hopefx_service_healthy 1 if all components are healthy",
        "# TYPE hopefx_service_healthy gauge",
        f'hopefx_service_healthy{{service="{_SERVICE_NAME}"}} {overall_healthy}',
        "",
    ]

    return "\n".join(lines)

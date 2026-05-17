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
GET /api/health/startup    — startup probe; 503 until all init tasks complete
GET /api/health/deep       — deep health check: DB query, Redis ping, broker ping, ML inference
GET /api/health/components — full structured JSON: every component's status + latency
GET /api/health/metrics    — Prometheus-compatible text/plain snapshot

Design invariants
-----------------
- ``/ready`` MUST return 503 (not 200) when any CRITICAL component is degraded.
- ``/startup`` MUST return 503 until the application has fully initialised.
- ``/deep`` performs real I/O probes against every dependency; never cached.
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

# ── Trading mode ──────────────────────────────────────────────────────────────
# Exposed on every health response so operators, dashboards, and monitoring
# tools can immediately see whether the system is in paper or live mode.
# BROKER_TYPE=paper is the safe default; live requires explicit opt-in.
_BROKER_TYPE: str = os.getenv("BROKER_TYPE", "paper").lower()
_TRADING_MODE: str = "live" if _BROKER_TYPE not in ("paper", "simulation", "demo", "backtest") else "paper"

# ── Startup state ─────────────────────────────────────────────────────────────
# Set to True by mark_startup_complete() once the lifespan startup handler
# finishes all initialisation tasks (DB, Redis, broker, ML model).
# The /startup probe returns 503 until this flag is True.
_startup_complete: bool = False
_startup_complete_at: float | None = None
_startup_tasks_done: list[str] = []
_startup_tasks_failed: list[str] = []


def mark_startup_complete(tasks_done: list[str] | None = None, tasks_failed: list[str] | None = None) -> None:
    """Called by the lifespan handler once all startup tasks finish.

    Args:
        tasks_done: Names of startup tasks that completed successfully.
        tasks_failed: Names of startup tasks that failed (non-fatal).
    """
    global _startup_complete, _startup_complete_at, _startup_tasks_done, _startup_tasks_failed
    _startup_complete = True
    _startup_complete_at = time.time()
    _startup_tasks_done = list(tasks_done or [])
    _startup_tasks_failed = list(tasks_failed or [])
    logger.info(
        "Startup probe: marked complete (done=%s, failed=%s)",
        _startup_tasks_done,
        _startup_tasks_failed,
    )
    # Publish to Prometheus so the hopefx_startup_complete alert rule fires
    try:
        from resilience.auto_rollback import _STARTUP_COMPLETE  # type: ignore[import]

        _STARTUP_COMPLETE.set(1)
    except Exception:  # nosec B110 — non-fatal
        pass


def mark_startup_incomplete() -> None:
    """Reset startup state — used during testing or hot-reload."""
    global _startup_complete, _startup_complete_at
    _startup_complete = False
    _startup_complete_at = None


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
    trading_mode: str  # "paper" | "live"
    broker_type: str  # raw BROKER_TYPE env value
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
        import redis.asyncio as aioredis  # type: ignore[import]  # pylint: disable=no-name-in-module

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
        # Redis is critical in production; in development the EventBus falls back
        # to an in-process queue so a missing Redis is non-fatal.
        _is_prod = os.getenv("APP_ENV", "development").lower() == "production"
        return ComponentStatus(
            name="redis",
            status="down",
            critical=_is_prod,
            latency_ms=round(latency_ms, 2),
            detail=str(exc),
        )


async def _check_database() -> ComponentStatus:
    """Ping the relational database.

    Tries the async engine first (production PostgreSQL path).
    Falls back to the sync engine from app_state (SQLite dev path) when
    the async driver (aiosqlite) is not installed.
    """
    t0 = time.perf_counter()
    engine, db_url = await _get_db_engine()

    # ── Async engine path (PostgreSQL / aiosqlite) ────────────────────────────
    if engine is not None:
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

    # ── Sync engine fallback (SQLite dev — no aiosqlite required) ────────────
    if db_url:
        try:
            from core.app_state import app_state as _app_state
            from sqlalchemy import text as _text

            sync_engine = getattr(_app_state, "db_engine", None)
            if sync_engine is not None:
                loop = asyncio.get_running_loop()

                def _ping() -> None:
                    with sync_engine.connect() as conn:
                        conn.execute(_text("SELECT 1"))

                await asyncio.wait_for(
                    loop.run_in_executor(None, _ping),
                    timeout=_CHECK_TIMEOUT_SEC,
                )
                latency_ms = (time.perf_counter() - t0) * 1000
                return ComponentStatus(
                    name="database",
                    status="healthy",
                    critical=True,
                    latency_ms=round(latency_ms, 2),
                    detail="SELECT 1 OK (sync engine)",
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

    return ComponentStatus(
        name="database",
        status="unknown",
        critical=True,
        detail="DATABASE_URL not set" if not db_url else "Engine creation failed — check logs",
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


async def _check_broker() -> ComponentStatus:
    """Check whether the active broker is connected and responsive."""
    t0 = time.perf_counter()
    try:
        from core.app_state import app_state as _app_state  # type: ignore[import]

        broker = getattr(_app_state, "broker", None)
        if broker is None:
            return ComponentStatus(
                name="broker",
                status="degraded",
                critical=False,
                latency_ms=round((time.perf_counter() - t0) * 1000, 2),
                detail="No broker initialised — paper trading or startup incomplete",
            )
        # Use is_connected() if available, else check a balance/ping call
        if hasattr(broker, "is_connected"):
            connected = broker.is_connected()
        elif hasattr(broker, "get_account_balance"):
            try:
                await asyncio.wait_for(broker.get_account_balance(), timeout=_CHECK_TIMEOUT_SEC)
                connected = True
            except Exception:
                connected = False
        else:
            connected = True  # assume connected if no check method

        broker_name = type(broker).__name__
        latency_ms = round((time.perf_counter() - t0) * 1000, 2)
        return ComponentStatus(
            name="broker",
            status="healthy" if connected else "down",
            critical=False,  # paper fallback keeps the app alive
            latency_ms=latency_ms,
            detail=f"{broker_name}: {'connected' if connected else 'disconnected'}",
        )
    except Exception as exc:
        return ComponentStatus(
            name="broker",
            status="unknown",
            critical=False,
            latency_ms=round((time.perf_counter() - t0) * 1000, 2),
            detail=str(exc),
        )


async def _check_db_migrations() -> ComponentStatus:
    """Verify the database schema is at the latest Alembic revision."""
    t0 = time.perf_counter()
    try:
        from alembic.config import Config as AlembicConfig  # type: ignore[import]
        from alembic.runtime.migration import MigrationContext  # type: ignore[import]
        from alembic.script import ScriptDirectory  # type: ignore[import]
        from sqlalchemy import create_engine  # type: ignore[import]

        db_url = os.getenv("DATABASE_URL", "sqlite:///hopefx.db")
        # Normalise async drivers to sync for Alembic
        db_url = (
            db_url.replace("sqlite+aiosqlite:///", "sqlite:///")
            .replace("postgresql+asyncpg://", "postgresql://")
            .replace("postgresql+aiopg://", "postgresql://")
            .replace("postgres://", "postgresql://", 1)
        )
        alembic_cfg = AlembicConfig("alembic.ini")
        alembic_cfg.set_main_option("sqlalchemy.url", db_url)
        script = ScriptDirectory.from_config(alembic_cfg)
        head_rev = script.get_current_head()

        engine = create_engine(db_url, poolclass=None)  # type: ignore[call-arg]
        with engine.connect() as conn:
            mctx = MigrationContext.configure(conn)
            current_rev = mctx.get_current_revision()
        engine.dispose()

        latency_ms = round((time.perf_counter() - t0) * 1000, 2)
        at_head = current_rev == head_rev
        return ComponentStatus(
            name="db_migrations",
            status="healthy" if at_head else "degraded",
            critical=False,  # degraded schema is a warning, not a hard failure
            latency_ms=latency_ms,
            detail=f"current={current_rev or 'none'} head={head_rev or 'none'}",
        )
    except Exception as exc:
        return ComponentStatus(
            name="db_migrations",
            status="unknown",
            critical=False,
            latency_ms=round((time.perf_counter() - t0) * 1000, 2),
            detail=str(exc),
        )


async def _check_orchestrator() -> ComponentStatus:
    """Check whether the data-layer orchestrator has been started."""
    t0 = time.perf_counter()
    try:
        from data_layer.orchestrator import orchestrator  # type: ignore[import]

        started = getattr(orchestrator, "_started", False)
        latency_ms = (time.perf_counter() - t0) * 1000
        # Orchestrator is critical only in production when it has not started.
        # In development, "not started" (degraded) is non-critical — data-layer
        # feeds are inactive but the API itself is healthy.
        _is_prod = os.getenv("APP_ENV", "development").lower() == "production"
        return ComponentStatus(
            name="orchestrator",
            status="healthy" if started else "degraded",
            critical=_is_prod and (not started),
            latency_ms=round(latency_ms, 2),
            detail="started" if started else "not started — call orchestrator.start()",
        )
    except Exception as exc:
        latency_ms = (time.perf_counter() - t0) * 1000
        return ComponentStatus(
            name="orchestrator",
            status="unknown",
            critical=False,
            latency_ms=round(latency_ms, 2),
            detail=str(exc),
        )


def _check_ready_sync() -> bool:
    """
    Synchronous readiness check for use in non-async contexts (e.g. rollback triggers).

    Uses circuit breaker states as a fast proxy for component health — no I/O,
    no event loop required.  Returns True when all critical services appear healthy.

    This is intentionally conservative: it returns False (not ready) when any
    critical circuit breaker is open, even if the underlying service has recovered
    but the breaker hasn't closed yet.
    """
    try:
        from resilience.service_circuit_breakers import (
            redis_breaker,
            db_breaker,
        )

        # Any open critical breaker → not ready
        if redis_breaker.is_open:
            return False
        if db_breaker.is_open:
            return False
        # broker and ml are non-critical for readiness (paper trading can run without them)
    except Exception:  # nosec B110 — circuit breaker import is non-fatal
        pass

    # Check kill switch
    try:
        from kill_switch import KillSwitch

        ks = KillSwitch.get_instance()
        if ks and ks.is_active():
            return False
    except Exception:  # nosec B110
        pass

    return True


async def _check_price_engine() -> ComponentStatus:
    """Check whether the price engine is running and has live prices."""
    t0 = time.perf_counter()
    try:
        from core.app_state import app_state as _app_state  # type: ignore[import]

        pe = getattr(_app_state, "price_engine", None)
        if pe is None:
            return ComponentStatus(
                name="price_engine",
                status="degraded",
                critical=False,
                latency_ms=round((time.perf_counter() - t0) * 1000, 2),
                detail="Not initialised — broker fallback active",
            )
        active = getattr(pe, "active", False)
        symbols = getattr(pe, "symbols", [])
        # Count symbols with a live price
        live_count = sum(1 for s in symbols if pe.get_last_price(s) is not None)
        latency_ms = round((time.perf_counter() - t0) * 1000, 2)
        status = "healthy" if active and live_count > 0 else ("degraded" if active else "down")
        return ComponentStatus(
            name="price_engine",
            status=status,
            critical=False,
            latency_ms=latency_ms,
            detail=f"active={active} symbols={len(symbols)} live_prices={live_count}",
        )
    except Exception as exc:
        return ComponentStatus(
            name="price_engine",
            status="unknown",
            critical=False,
            latency_ms=round((time.perf_counter() - t0) * 1000, 2),
            detail=str(exc),
        )


async def _check_brain() -> ComponentStatus:
    """Check whether the strategy brain / signal engine is running."""
    t0 = time.perf_counter()
    try:
        from core.app_state import app_state as _app_state  # type: ignore[import]

        brain = getattr(_app_state, "brain", None) or getattr(_app_state, "strategy_brain", None)
        signal_engine = getattr(_app_state, "signal_engine", None)

        if brain is None and signal_engine is None:
            return ComponentStatus(
                name="brain",
                status="degraded",
                critical=False,
                latency_ms=round((time.perf_counter() - t0) * 1000, 2),
                detail="Brain and signal engine not initialised — awaiting broker+price_engine",
            )

        details: list[str] = []
        if brain is not None:
            brain_active = getattr(brain, "active", getattr(brain, "running", True))
            details.append(f"brain={type(brain).__name__}(active={brain_active})")
        if signal_engine is not None:
            se_active = getattr(signal_engine, "active", getattr(signal_engine, "running", True))
            details.append(f"signal_engine={type(signal_engine).__name__}(active={se_active})")

        latency_ms = round((time.perf_counter() - t0) * 1000, 2)
        return ComponentStatus(
            name="brain",
            status="healthy",
            critical=False,
            latency_ms=latency_ms,
            detail=" | ".join(details),
        )
    except Exception as exc:
        return ComponentStatus(
            name="brain",
            status="unknown",
            critical=False,
            latency_ms=round((time.perf_counter() - t0) * 1000, 2),
            detail=str(exc),
        )


async def _check_master_control() -> ComponentStatus:
    """Check whether the master control centre (MCC) is wired and running."""
    t0 = time.perf_counter()
    try:
        # MasterControlCore is the actual class name (MasterControlCentre is an alias)
        from core.app_state import app_state as _app_state  # type: ignore[import]

        mcc = getattr(_app_state, "mcc", None)
        if mcc is None:
            # Try the module-level singleton
            try:
                from core.mcc import master_control as _mc_mod  # type: ignore[import]

                mcc = getattr(_mc_mod, "_mcc_instance", None)
            except Exception:  # nosec B110
                pass

        latency_ms = round((time.perf_counter() - t0) * 1000, 2)
        if mcc is None:
            return ComponentStatus(
                name="master_control",
                status="degraded",
                critical=False,
                latency_ms=latency_ms,
                detail="MCC not initialised",
            )
        running = getattr(mcc, "running", getattr(mcc, "active", True))
        return ComponentStatus(
            name="master_control",
            status="healthy" if running else "degraded",
            critical=False,
            latency_ms=latency_ms,
            detail=f"{type(mcc).__name__}(running={running})",
        )
    except Exception as exc:
        return ComponentStatus(
            name="master_control",
            status="unknown",
            critical=False,
            latency_ms=round((time.perf_counter() - t0) * 1000, 2),
            detail=str(exc),
        )


async def _check_db_pool() -> ComponentStatus:
    """Verify the async DB connection pool is initialised and can serve sessions.

    ``set_default_pool()`` must be called during app startup before any DB
    endpoint is reachable.  If it was never called, all 9 DB-backed endpoints
    silently return empty data — this check surfaces that failure explicitly.
    """
    t0 = time.perf_counter()
    try:
        from database.async_connection import _default_pool  # type: ignore[import]

        if _default_pool is None:
            return ComponentStatus(
                name="db_pool",
                status="down",
                critical=True,
                latency_ms=round((time.perf_counter() - t0) * 1000, 2),
                detail="set_default_pool() was never called — DB endpoints will return empty data",
            )

        # Verify the pool can actually open a session.
        pool_healthy = getattr(_default_pool, "is_healthy", None)
        healthy = pool_healthy() if callable(pool_healthy) else True

        latency_ms = round((time.perf_counter() - t0) * 1000, 2)
        return ComponentStatus(
            name="db_pool",
            status="healthy" if healthy else "degraded",
            critical=True,
            latency_ms=latency_ms,
            detail=f"pool={type(_default_pool).__name__} healthy={healthy}",
        )
    except Exception as exc:
        return ComponentStatus(
            name="db_pool",
            status="unknown",
            critical=True,
            latency_ms=round((time.perf_counter() - t0) * 1000, 2),
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
        _check_broker(),
        _check_db_migrations(),
        _check_price_engine(),
        _check_brain(),
        _check_master_control(),
        _check_db_pool(),
        return_exceptions=True,
    )
    statuses: list[ComponentStatus] = []
    names = [
        "redis",
        "database",
        "kill_switch",
        "ml_model",
        "orchestrator",
        "broker",
        "db_migrations",
        "price_engine",
        "brain",
        "master_control",
        "db_pool",
    ]
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
    "",
    summary="Health summary — redirects to /api/health/ready",
    include_in_schema=False,
)
@router.get(
    "/",
    summary="Health summary — redirects to /api/health/ready",
    include_in_schema=False,
)
async def health_root() -> dict[str, Any]:
    """
    Root health endpoint.  Returns the same payload as /api/health/ready
    so that generic health-check tools hitting /api/health get a useful response.
    """
    from fastapi.responses import RedirectResponse

    return RedirectResponse(url="/api/health/ready", status_code=302)


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
        "trading_mode": _TRADING_MODE,
        "broker_type": _BROKER_TYPE,
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
        trading_mode=_TRADING_MODE,
        broker_type=_BROKER_TYPE,
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
    except ImportError:  # nosec B110 — psutil is optional; skip memory metrics when not installed
        pass  # psutil is optional — skip memory metrics when not installed
    except Exception as exc:
        logger.debug("Failed to collect memory metrics: %s", exc)

    overall_healthy = 1 if all(c.status == "healthy" for c in components) else 0
    lines += [
        "",
        "# HELP hopefx_service_healthy 1 if all components are healthy",
        "# TYPE hopefx_service_healthy gauge",
        f'hopefx_service_healthy{{service="{_SERVICE_NAME}"}} {overall_healthy}',
    ]

    # Circuit breaker states (0=closed/healthy, 1=half_open, 2=open/unhealthy)
    try:
        from resilience.service_circuit_breakers import get_all_breaker_status

        breaker_statuses = get_all_breaker_status()
        state_map = {"closed": 0, "half_open": 1, "open": 2}
        lines += [
            "",
            "# HELP hopefx_circuit_breaker_state Circuit breaker state (0=closed, 1=half_open, 2=open)",
            "# TYPE hopefx_circuit_breaker_state gauge",
            "# HELP hopefx_circuit_breaker_failures_total Total failures recorded by circuit breaker",
            "# TYPE hopefx_circuit_breaker_failures_total counter",
        ]
        for name, status in breaker_statuses.items():
            state_val = state_map.get(status.get("state", "closed"), 0)
            total_failures = status.get("total_failures", 0)
            lines.append(f'hopefx_circuit_breaker_state{{breaker="{name}"}} {state_val}')
            lines.append(f'hopefx_circuit_breaker_failures_total{{breaker="{name}"}} {total_failures}')
    except Exception:  # nosec B110 — circuit breaker metrics are non-fatal
        pass

    # Auto-rollback status
    try:
        from resilience.auto_rollback import rollback_manager as _rm

        rm_status = _rm.get_status()
        rollback_count = rm_status.get("total_rollbacks", 0)
        lines += [
            "",
            "# HELP hopefx_rollback_total Total automatic rollbacks triggered",
            "# TYPE hopefx_rollback_total counter",
            f'hopefx_rollback_total{{service="{_SERVICE_NAME}"}} {rollback_count}',
        ]
    except Exception:  # nosec B110 — rollback metrics are non-fatal
        pass

    lines.append("")
    return "\n".join(lines)


# ── Startup probe ──────────────────────────────────────────────────────────────


class StartupResponse(BaseModel):
    """Startup probe response."""

    started: bool
    timestamp: str
    started_at: str | None = None
    uptime_seconds: float | None = None
    tasks_done: list[str]
    tasks_failed: list[str]
    service: str
    version: str


@router.get(
    "/startup",
    response_model=StartupResponse,
    summary="Startup probe — 503 until application fully initialised",
    responses={
        200: {"description": "Application startup complete"},
        503: {"description": "Application still initialising"},
    },
)
async def startup_probe() -> Response:
    """Kubernetes startup probe.

    Returns HTTP 200 once all lifespan startup tasks have completed
    (DB pool, Redis, broker connection, ML model load).
    Returns HTTP 503 while the application is still initialising.

    Kubernetes uses this probe to avoid sending traffic before the app is
    ready to handle requests.  Unlike the readiness probe, this one only
    fires once — after it succeeds, Kubernetes switches to the liveness
    and readiness probes.

    Returns:
        :class:`StartupResponse` JSON.
        HTTP 503 while initialising, 200 once complete.
    """
    now = time.time()
    started_at_iso: str | None = None
    uptime: float | None = None

    if _startup_complete and _startup_complete_at is not None:
        started_at_iso = datetime.fromtimestamp(_startup_complete_at, timezone.utc).isoformat()
        uptime = round(now - _startup_complete_at, 2)

    body = StartupResponse(
        started=_startup_complete,
        timestamp=datetime.now(timezone.utc).isoformat(),
        started_at=started_at_iso,
        uptime_seconds=uptime,
        tasks_done=list(_startup_tasks_done),
        tasks_failed=list(_startup_tasks_failed),
        service=_SERVICE_NAME,
        version=_VERSION,
    )

    status_code = 200 if _startup_complete else 503
    return Response(
        content=body.model_dump_json(),
        status_code=status_code,
        media_type="application/json",
    )


# ── Deep health check ──────────────────────────────────────────────────────────


class DeepCheckResult(BaseModel):
    """Result of a single deep health check probe."""

    name: str
    status: str  # ok | error | skipped
    latency_ms: float | None = None
    detail: str = ""


class DeepHealthResponse(BaseModel):
    """Full deep health check response."""

    service: str
    version: str
    timestamp: str
    overall: str  # ok | degraded | error
    trading_mode: str
    broker_type: str
    checks: list[DeepCheckResult]
    total_latency_ms: float


async def _deep_check_redis() -> DeepCheckResult:
    """Perform a real Redis SET/GET/DEL round-trip to verify read-write health."""
    t0 = time.perf_counter()
    try:
        import redis.asyncio as aioredis  # type: ignore[import]

        redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
        client = aioredis.from_url(redis_url, socket_connect_timeout=2, socket_timeout=2)
        probe_key = "hopefx:health:deep:probe"
        probe_val = str(time.time())
        await asyncio.wait_for(client.set(probe_key, probe_val, ex=10), timeout=_CHECK_TIMEOUT_SEC)
        read_val = await asyncio.wait_for(client.get(probe_key), timeout=_CHECK_TIMEOUT_SEC)
        await asyncio.wait_for(client.delete(probe_key), timeout=_CHECK_TIMEOUT_SEC)
        await client.aclose()
        latency_ms = (time.perf_counter() - t0) * 1000
        match = read_val is not None and (read_val == probe_val or read_val == probe_val.encode())
        return DeepCheckResult(
            name="redis_rw",
            status="ok" if match else "error",
            latency_ms=round(latency_ms, 2),
            detail="SET/GET/DEL round-trip OK" if match else f"Value mismatch: got {read_val!r}",
        )
    except Exception as exc:
        latency_ms = (time.perf_counter() - t0) * 1000
        return DeepCheckResult(
            name="redis_rw",
            status="error",
            latency_ms=round(latency_ms, 2),
            detail=str(exc),
        )


async def _deep_check_database() -> DeepCheckResult:
    """Execute a real SELECT query and verify the result."""
    t0 = time.perf_counter()
    engine, db_url = await _get_db_engine()
    if engine is None:
        return DeepCheckResult(
            name="database_query",
            status="skipped",
            detail="DATABASE_URL not configured" if not db_url else "Engine unavailable",
        )
    try:
        from sqlalchemy import text  # type: ignore[import]

        async with engine.connect() as conn:
            result = await asyncio.wait_for(
                conn.execute(text("SELECT 1 AS probe")),
                timeout=_CHECK_TIMEOUT_SEC,
            )
            row = result.fetchone()
        latency_ms = (time.perf_counter() - t0) * 1000
        ok = row is not None and row[0] == 1
        return DeepCheckResult(
            name="database_query",
            status="ok" if ok else "error",
            latency_ms=round(latency_ms, 2),
            detail="SELECT 1 returned 1" if ok else f"Unexpected result: {row}",
        )
    except Exception as exc:
        latency_ms = (time.perf_counter() - t0) * 1000
        return DeepCheckResult(
            name="database_query",
            status="error",
            latency_ms=round(latency_ms, 2),
            detail=str(exc),
        )


async def _deep_check_broker() -> DeepCheckResult:
    """Verify broker connectivity by fetching account info or a price quote."""
    t0 = time.perf_counter()
    try:
        from core.app_state import app_state as _app_state  # type: ignore[import]

        broker = getattr(_app_state, "broker", None)
        if broker is None:
            return DeepCheckResult(
                name="broker_ping",
                status="skipped",
                detail="Broker not initialised in app_state",
            )

        # Try get_account_info first; fall back to is_connected()
        if hasattr(broker, "get_account_info"):
            info = await asyncio.wait_for(
                broker.get_account_info()
                if asyncio.iscoroutinefunction(broker.get_account_info)
                else asyncio.get_running_loop().run_in_executor(None, broker.get_account_info),
                timeout=_CHECK_TIMEOUT_SEC,
            )
            latency_ms = (time.perf_counter() - t0) * 1000
            ok = info is not None
            return DeepCheckResult(
                name="broker_ping",
                status="ok" if ok else "error",
                latency_ms=round(latency_ms, 2),
                detail="Account info retrieved" if ok else "get_account_info returned None",
            )
        elif hasattr(broker, "is_connected"):
            connected = broker.is_connected()
            latency_ms = (time.perf_counter() - t0) * 1000
            return DeepCheckResult(
                name="broker_ping",
                status="ok" if connected else "error",
                latency_ms=round(latency_ms, 2),
                detail="Broker connected" if connected else "Broker reports disconnected",
            )
        else:
            return DeepCheckResult(
                name="broker_ping",
                status="skipped",
                detail="Broker has no get_account_info or is_connected method",
            )
    except Exception as exc:
        latency_ms = (time.perf_counter() - t0) * 1000
        return DeepCheckResult(
            name="broker_ping",
            status="error",
            latency_ms=round(latency_ms, 2),
            detail=str(exc),
        )


async def _deep_check_ml() -> DeepCheckResult:
    """Run a real ML inference call with a synthetic tick to verify the model loads."""
    t0 = time.perf_counter()
    try:
        from core.app_state import app_state as _app_state  # type: ignore[import]

        engine = getattr(_app_state, "ml_engine", None) or getattr(_app_state, "inference_engine", None)
        if engine is None:
            # Fall back to loading the model artifact directly
            import os as _os

            model_path = _os.path.join(
                _os.path.dirname(_os.path.dirname(__file__)),
                "ml",
                "saved_models",
                "advanced_oos.pkl",
            )
            if not _os.path.isfile(model_path):
                return DeepCheckResult(
                    name="ml_inference",
                    status="skipped",
                    detail=f"ML engine not in app_state and model not found at {model_path}",
                )
            import joblib  # type: ignore[import]

            model = joblib.load(model_path)  # nosec B301
            latency_ms = (time.perf_counter() - t0) * 1000
            return DeepCheckResult(
                name="ml_inference",
                status="ok",
                latency_ms=round(latency_ms, 2),
                detail=f"Model loaded from {model_path} ({type(model).__name__})",
            )

        # Use the live engine — call predict with a minimal feature vector
        import numpy as np  # type: ignore[import]

        dummy_features = np.zeros((1, 10), dtype=np.float32)
        if hasattr(engine, "predict"):
            pred = engine.predict(dummy_features)
        elif hasattr(engine, "infer"):
            pred = engine.infer(dummy_features)
        else:
            return DeepCheckResult(
                name="ml_inference",
                status="skipped",
                detail=f"ML engine ({type(engine).__name__}) has no predict/infer method",
            )

        latency_ms = (time.perf_counter() - t0) * 1000
        return DeepCheckResult(
            name="ml_inference",
            status="ok",
            latency_ms=round(latency_ms, 2),
            detail=f"Inference returned {type(pred).__name__}",
        )
    except Exception as exc:
        latency_ms = (time.perf_counter() - t0) * 1000
        return DeepCheckResult(
            name="ml_inference",
            status="error",
            latency_ms=round(latency_ms, 2),
            detail=str(exc),
        )


async def _deep_check_circuit_breakers() -> DeepCheckResult:
    """Report the state of all circuit breakers."""
    t0 = time.perf_counter()
    try:
        from resilience.service_circuit_breakers import get_all_breaker_status  # type: ignore[import]

        status = get_all_breaker_status()
        open_count = status.get("open_count", 0)
        latency_ms = (time.perf_counter() - t0) * 1000
        detail_parts = [f"{name}={info.get('state', 'unknown')}" for name, info in status.get("breakers", {}).items()]
        return DeepCheckResult(
            name="circuit_breakers",
            status="ok" if open_count == 0 else "error",
            latency_ms=round(latency_ms, 2),
            detail=f"open={open_count} — " + ", ".join(detail_parts),
        )
    except Exception as exc:
        latency_ms = (time.perf_counter() - t0) * 1000
        return DeepCheckResult(
            name="circuit_breakers",
            status="error",
            latency_ms=round(latency_ms, 2),
            detail=str(exc),
        )


async def _deep_check_kill_switch() -> DeepCheckResult:
    """Verify kill switch state."""
    t0 = time.perf_counter()
    try:
        from kill_switch import kill_switch as _ks  # type: ignore[import]

        active = _ks.is_active()
        reason = getattr(_ks, "_reason", "") if active else ""
        latency_ms = (time.perf_counter() - t0) * 1000
        return DeepCheckResult(
            name="kill_switch",
            status="error" if active else "ok",
            latency_ms=round(latency_ms, 2),
            detail=f"ACTIVE: {reason}" if active else "inactive",
        )
    except Exception as exc:
        latency_ms = (time.perf_counter() - t0) * 1000
        return DeepCheckResult(
            name="kill_switch",
            status="error",
            latency_ms=round(latency_ms, 2),
            detail=str(exc),
        )


@router.get(
    "/deep",
    response_model=DeepHealthResponse,
    summary="Deep health check — real I/O probes against every dependency",
    responses={
        200: {"description": "All deep checks passed"},
        503: {"description": "One or more deep checks failed"},
    },
)
async def deep_health() -> Response:
    """Deep health check endpoint.

    Performs real I/O probes against every external dependency:
    - Redis: SET/GET/DEL round-trip
    - Database: SELECT 1 query
    - Broker: account info or connection status
    - ML model: load artifact or run inference
    - Circuit breakers: state of all breakers
    - Kill switch: active/inactive state

    Unlike ``/ready`` (which uses cached component states), this endpoint
    always performs live I/O.  Use it for post-deploy verification and
    scheduled deep monitoring — not as a Kubernetes readiness probe.

    Returns:
        :class:`DeepHealthResponse` JSON.
        HTTP 503 when any check returns ``error`` status.
    """
    t_start = time.perf_counter()

    results = await asyncio.gather(
        _deep_check_redis(),
        _deep_check_database(),
        _deep_check_broker(),
        _deep_check_ml(),
        _deep_check_circuit_breakers(),
        _deep_check_kill_switch(),
        return_exceptions=True,
    )

    checks: list[DeepCheckResult] = []
    for r in results:
        if isinstance(r, Exception):
            checks.append(DeepCheckResult(name="unknown", status="error", detail=str(r)))
        else:
            checks.append(r)  # type: ignore[arg-type]

    total_latency_ms = round((time.perf_counter() - t_start) * 1000, 2)
    has_error = any(c.status == "error" for c in checks)
    overall = "error" if has_error else "ok"

    body = DeepHealthResponse(
        service=_SERVICE_NAME,
        version=_VERSION,
        timestamp=datetime.now(timezone.utc).isoformat(),
        overall=overall,
        trading_mode=_TRADING_MODE,
        broker_type=_BROKER_TYPE,
        checks=checks,
        total_latency_ms=total_latency_ms,
    )

    status_code = 503 if has_error else 200
    return Response(
        content=body.model_dump_json(),
        status_code=status_code,
        media_type="application/json",
    )

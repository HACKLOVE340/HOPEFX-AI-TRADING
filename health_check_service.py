# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
health_check_service.py
=======================
Production health-check service for HOPEFX AI Trading.

Exposes a FastAPI router at /health with three endpoints:

  GET /health          — liveness probe (always 200 when the process is alive)
  GET /health/ready    — readiness probe (200 when all critical components are up)
  GET /health/detailed — full component breakdown (admin-only)

Component checks
----------------
  redis       — PING via cache.redis_pool.borrow_client()
  database    — SELECT 1 via SQLAlchemy engine
  data_feed   — last tick age from app_state.price_engine / multi_source_feed
  broker      — account info from app_state.broker
  event_bus   — publish heartbeat on CH_HEARTBEAT
  kill_switch — kill_switch.kill_switch.is_active()
  disk        — free disk space on the data partition

Each check runs with a configurable timeout (default 3 s) and returns:
  status     : "ok" | "degraded" | "error"
  latency_ms : float
  detail     : str (human-readable, safe to expose)

Overall readiness:
  "healthy"   — all critical checks pass
  "degraded"  — at least one non-critical check failed
  "unhealthy" — at least one critical check failed

Critical checks: redis, database, data_feed
Non-critical checks: broker, event_bus, kill_switch, disk

Environment variables
---------------------
  HEALTH_CHECK_TIMEOUT_SECONDS      — per-check timeout (default: 3.0)
  HEALTH_CHECK_DISK_WARN_GB         — disk free warning threshold in GB (default: 5.0)
  HEALTH_CHECK_DISK_PATH            — path to check disk space on (default: "/")
  HEALTH_CHECK_DATA_FEED_MAX_AGE_S  — max acceptable tick age in seconds (default: 30)

Mount in app.py:
    from health_check_service import health_router
    app.include_router(health_router)
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import time
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

logger = logging.getLogger(__name__)

UTC = timezone.utc

# ── Configuration ─────────────────────────────────────────────────────────────

_TIMEOUT_S: float = float(os.environ.get("HEALTH_CHECK_TIMEOUT_SECONDS", "3.0"))
_DISK_WARN_GB: float = float(os.environ.get("HEALTH_CHECK_DISK_WARN_GB", "5.0"))
_DISK_PATH: str = os.environ.get("HEALTH_CHECK_DISK_PATH", "/")
_DATA_FEED_MAX_AGE_S: float = float(os.environ.get("HEALTH_CHECK_DATA_FEED_MAX_AGE_S", "30.0"))

# ── Schemas ───────────────────────────────────────────────────────────────────


class ComponentStatus(BaseModel):
    status: str          # "ok" | "degraded" | "error"
    latency_ms: float
    detail: str


class HealthResponse(BaseModel):
    status: str          # "healthy" | "degraded" | "unhealthy"
    timestamp: str
    uptime_seconds: float
    version: str
    components: dict[str, ComponentStatus]


class LivenessResponse(BaseModel):
    status: str = "alive"
    timestamp: str


# ── Process start time (for uptime calculation) ───────────────────────────────

_PROCESS_START = time.monotonic()


def _uptime() -> float:
    return round(time.monotonic() - _PROCESS_START, 1)


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _version() -> str:
    try:
        from importlib.metadata import version
        return version("hopefx-ai-trading")
    except Exception:
        return os.environ.get("APP_VERSION", "unknown")


# ── Individual component checks ───────────────────────────────────────────────


async def _check_redis() -> ComponentStatus:
    """PING Redis via the shared connection pool."""
    t0 = time.monotonic()
    try:
        from cache.redis_pool import borrow_client

        def _ping():
            with borrow_client() as r:
                r.ping()

        loop = asyncio.get_event_loop()
        await asyncio.wait_for(
            loop.run_in_executor(None, _ping),
            timeout=_TIMEOUT_S,
        )
        latency = (time.monotonic() - t0) * 1000
        return ComponentStatus(status="ok", latency_ms=round(latency, 2), detail="PONG")
    except asyncio.TimeoutError:
        latency = (time.monotonic() - t0) * 1000
        return ComponentStatus(status="error", latency_ms=round(latency, 2), detail=f"Timeout after {_TIMEOUT_S}s")
    except Exception as exc:
        latency = (time.monotonic() - t0) * 1000
        return ComponentStatus(status="error", latency_ms=round(latency, 2), detail=str(exc)[:200])


async def _check_database() -> ComponentStatus:
    """SELECT 1 via the SQLAlchemy engine from app_state."""
    t0 = time.monotonic()
    try:
        from core.app_state import app_state
        from sqlalchemy import text

        engine = getattr(app_state, "db_engine", None)
        if engine is None:
            return ComponentStatus(status="degraded", latency_ms=0.0, detail="DB engine not initialised")

        async def _query():
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))

        await asyncio.wait_for(_query(), timeout=_TIMEOUT_S)
        latency = (time.monotonic() - t0) * 1000
        return ComponentStatus(status="ok", latency_ms=round(latency, 2), detail="SELECT 1 OK")
    except asyncio.TimeoutError:
        latency = (time.monotonic() - t0) * 1000
        return ComponentStatus(status="error", latency_ms=round(latency, 2), detail=f"Timeout after {_TIMEOUT_S}s")
    except Exception as exc:
        latency = (time.monotonic() - t0) * 1000
        return ComponentStatus(status="error", latency_ms=round(latency, 2), detail=str(exc)[:200])


async def _check_data_feed() -> ComponentStatus:
    """Check that the data feed has produced a tick within _DATA_FEED_MAX_AGE_S."""
    t0 = time.monotonic()
    try:
        from core.app_state import app_state

        pe = getattr(app_state, "price_engine", None)
        msf = getattr(app_state, "multi_source_feed", None)
        source = pe or msf

        if source is None:
            return ComponentStatus(status="degraded", latency_ms=0.0, detail="Data feed not initialised")

        tick = None
        for sym in ("XAUUSD", "XAU_USD", "EURUSD"):
            try:
                tick = source.get_last_price(sym)
                if tick is not None:
                    break
            except Exception:
                continue

        if tick is None:
            return ComponentStatus(status="degraded", latency_ms=0.0, detail="No tick received yet")

        ts = getattr(tick, "timestamp", None)
        if ts is None:
            return ComponentStatus(status="ok", latency_ms=0.0, detail="Tick present (no timestamp)")

        age = time.time() - float(ts)
        latency = (time.monotonic() - t0) * 1000
        if age > _DATA_FEED_MAX_AGE_S:
            return ComponentStatus(
                status="degraded",
                latency_ms=round(latency, 2),
                detail=f"Last tick {age:.1f}s ago (threshold {_DATA_FEED_MAX_AGE_S}s)",
            )
        return ComponentStatus(
            status="ok",
            latency_ms=round(latency, 2),
            detail=f"Last tick {age:.1f}s ago",
        )
    except Exception as exc:
        latency = (time.monotonic() - t0) * 1000
        return ComponentStatus(status="error", latency_ms=round(latency, 2), detail=str(exc)[:200])


async def _check_broker() -> ComponentStatus:
    """Verify the broker is connected and can return account info."""
    t0 = time.monotonic()
    try:
        from core.app_state import app_state

        broker = getattr(app_state, "broker", None)
        if broker is None:
            return ComponentStatus(status="degraded", latency_ms=0.0, detail="Broker not initialised")

        def _get_info():
            return broker.get_account_info()

        loop = asyncio.get_event_loop()
        info = await asyncio.wait_for(
            loop.run_in_executor(None, _get_info),
            timeout=_TIMEOUT_S,
        )
        latency = (time.monotonic() - t0) * 1000
        balance = (
            getattr(info, "balance", None)
            or (info.get("balance") if isinstance(info, dict) else None)
        )
        return ComponentStatus(
            status="ok",
            latency_ms=round(latency, 2),
            detail=f"balance={balance}" if balance is not None else "account info OK",
        )
    except asyncio.TimeoutError:
        latency = (time.monotonic() - t0) * 1000
        return ComponentStatus(status="error", latency_ms=round(latency, 2), detail=f"Timeout after {_TIMEOUT_S}s")
    except Exception as exc:
        latency = (time.monotonic() - t0) * 1000
        return ComponentStatus(status="degraded", latency_ms=round(latency, 2), detail=str(exc)[:200])


async def _check_event_bus() -> ComponentStatus:
    """Publish a heartbeat event on CH_HEARTBEAT and verify no exception."""
    t0 = time.monotonic()
    try:
        # The module exports the singleton `bus`, not a bare `publish` function.
        from core.event_bus import bus, CH_HEARTBEAT

        await asyncio.wait_for(
            bus.publish(CH_HEARTBEAT, {"type": "health_check", "ts": time.time()}),
            timeout=_TIMEOUT_S,
        )
        latency = (time.monotonic() - t0) * 1000
        mode = "redis" if not bus._degraded else "local-fallback"
        return ComponentStatus(status="ok", latency_ms=round(latency, 2), detail=f"heartbeat published ({mode})")
    except asyncio.TimeoutError:
        latency = (time.monotonic() - t0) * 1000
        return ComponentStatus(status="error", latency_ms=round(latency, 2), detail=f"Timeout after {_TIMEOUT_S}s")
    except Exception as exc:
        latency = (time.monotonic() - t0) * 1000
        return ComponentStatus(status="degraded", latency_ms=round(latency, 2), detail=str(exc)[:200])


async def _check_kill_switch() -> ComponentStatus:
    """Report whether the kill switch is active."""
    t0 = time.monotonic()
    try:
        from kill_switch import kill_switch as ks

        active = ks.is_active()
        reason = getattr(ks, "_reason", "") if active else ""
        latency = (time.monotonic() - t0) * 1000
        if active:
            return ComponentStatus(
                status="degraded",
                latency_ms=round(latency, 2),
                detail=f"ACTIVE — {reason}" if reason else "ACTIVE",
            )
        return ComponentStatus(status="ok", latency_ms=round(latency, 2), detail="inactive")
    except Exception as exc:
        latency = (time.monotonic() - t0) * 1000
        return ComponentStatus(status="ok", latency_ms=round(latency, 2), detail=f"unavailable: {exc}")


async def _check_disk() -> ComponentStatus:
    """Check free disk space on _DISK_PATH."""
    t0 = time.monotonic()
    try:
        usage = shutil.disk_usage(_DISK_PATH)
        free_gb = usage.free / (1024 ** 3)
        total_gb = usage.total / (1024 ** 3)
        used_pct = (usage.used / usage.total) * 100
        latency = (time.monotonic() - t0) * 1000
        detail = f"{free_gb:.1f} GB free / {total_gb:.1f} GB total ({used_pct:.1f}% used)"
        if free_gb < _DISK_WARN_GB:
            return ComponentStatus(status="degraded", latency_ms=round(latency, 2), detail=detail)
        return ComponentStatus(status="ok", latency_ms=round(latency, 2), detail=detail)
    except Exception as exc:
        latency = (time.monotonic() - t0) * 1000
        return ComponentStatus(status="error", latency_ms=round(latency, 2), detail=str(exc)[:200])


async def _check_macro_calendar() -> ComponentStatus:
    """Check MacroCalendarEngine — last refresh age and event count."""
    t0 = time.monotonic()
    try:
        from data_layer.calendar.engine import macro_calendar_engine as _cal

        event_count = len(_cal._events)
        last_refresh = _cal._last_refresh  # float unix timestamp or 0
        latency = (time.monotonic() - t0) * 1000

        if last_refresh == 0:
            return ComponentStatus(
                status="degraded",
                latency_ms=round(latency, 2),
                detail="never refreshed — calendar engine may not have started",
            )

        age_s = time.time() - last_refresh
        age_min = age_s / 60
        finnhub_key = bool(os.getenv("FINNHUB_API_KEY", "").strip())
        detail = (
            f"events={event_count}, last_refresh={age_min:.1f}m ago, "
            f"finnhub_key={'yes' if finnhub_key else 'no (using fallback)'}"
        )

        # Stale threshold: 2× the configured refresh interval
        from data_layer.calendar.engine import _REFRESH_INTERVAL_S
        stale_threshold_s = _REFRESH_INTERVAL_S * 2

        if age_s > stale_threshold_s:
            return ComponentStatus(status="degraded", latency_ms=round(latency, 2), detail=detail)
        return ComponentStatus(status="ok", latency_ms=round(latency, 2), detail=detail)
    except Exception as exc:
        latency = (time.monotonic() - t0) * 1000
        return ComponentStatus(status="error", latency_ms=round(latency, 2), detail=str(exc)[:200])


async def _check_geopolitical() -> ComponentStatus:
    """Check GeopoliticalRiskProvider — cache age, source failures, and fallback state.

    Uses the module-level singleton _geopolitical_provider created by
    get_geopolitical_provider().  Returns 'ok' (not 'error') when the
    provider has not been started — it is an optional component.
    """
    t0 = time.monotonic()
    try:
        import news.geopolitical_risk as _geo_mod

        # The singleton is _geopolitical_provider (set by get_geopolitical_provider())
        provider = getattr(_geo_mod, "_geopolitical_provider", None)
        if provider is None:
            latency = (time.monotonic() - t0) * 1000
            return ComponentStatus(
                status="ok",
                latency_ms=round(latency, 2),
                detail="provider not started (optional component)",
            )

        cache_ts = getattr(provider, "_cache_timestamp", None)
        cache_events = provider._cache.get("events", [])
        all_warned = getattr(provider, "_all_sources_warned", False)
        source_failures = getattr(provider, "_source_failures", {})
        latency = (time.monotonic() - t0) * 1000

        if cache_ts is None:
            return ComponentStatus(
                status="degraded",
                latency_ms=round(latency, 2),
                detail="cache never populated — all sources may be unreachable",
            )

        from datetime import datetime, timezone as _tz
        age_s = (datetime.now(_tz.utc) - cache_ts).total_seconds()
        age_min = age_s / 60
        failed_sources = [k for k, v in source_failures.items() if v > 0]
        detail = (
            f"events={len(cache_events)}, cache_age={age_min:.1f}m, "
            f"all_sources_warned={all_warned}, "
            f"failed_sources={failed_sources or 'none'}"
        )

        if all_warned:
            return ComponentStatus(status="degraded", latency_ms=round(latency, 2), detail=detail)
        return ComponentStatus(status="ok", latency_ms=round(latency, 2), detail=detail)
    except Exception as exc:
        latency = (time.monotonic() - t0) * 1000
        return ComponentStatus(status="ok", latency_ms=round(latency, 2), detail=f"unavailable: {exc}")


# ── Aggregation ───────────────────────────────────────────────────────────────

# Checks that must pass for the service to be considered "ready"
_CRITICAL_CHECKS = {"redis", "database", "data_feed"}


async def _run_all_checks() -> dict[str, ComponentStatus]:
    """Run all component checks concurrently and return results."""
    results = await asyncio.gather(
        _check_redis(),
        _check_database(),
        _check_data_feed(),
        _check_broker(),
        _check_event_bus(),
        _check_kill_switch(),
        _check_disk(),
        _check_macro_calendar(),
        _check_geopolitical(),
        return_exceptions=True,
    )
    names = [
        "redis", "database", "data_feed", "broker", "event_bus",
        "kill_switch", "disk", "macro_calendar", "geopolitical",
    ]
    out: dict[str, ComponentStatus] = {}
    for name, result in zip(names, results):
        if isinstance(result, Exception):
            out[name] = ComponentStatus(status="error", latency_ms=0.0, detail=str(result)[:200])
        else:
            out[name] = result  # type: ignore[assignment]
    return out


def _aggregate_status(components: dict[str, ComponentStatus]) -> str:
    """Derive overall status from component statuses."""
    for name in _CRITICAL_CHECKS:
        comp = components.get(name)
        if comp and comp.status == "error":
            return "unhealthy"
    for comp in components.values():
        if comp.status in ("error", "degraded"):
            return "degraded"
    return "healthy"


# ── Router ────────────────────────────────────────────────────────────────────

health_router = APIRouter(tags=["Health"])


@health_router.get(
    "/health",
    response_model=LivenessResponse,
    summary="Liveness probe",
    description=(
        "Always returns 200 when the process is alive. "
        "Use for Kubernetes liveness probes — never checks dependencies."
    ),
)
async def liveness() -> LivenessResponse:
    """Process liveness — returns 200 as long as the event loop is running."""
    return LivenessResponse(timestamp=_now_iso())


@health_router.get(
    "/health/ready",
    summary="Readiness probe",
    description=(
        "Returns 200 when all critical components (Redis, DB, data feed) are healthy. "
        "Returns 503 when any critical component is down. "
        "Use for Kubernetes readiness probes."
    ),
)
async def readiness() -> dict[str, Any]:
    """
    Readiness probe — checks critical components only for speed.

    Returns HTTP 503 when any critical check fails so load balancers
    stop routing traffic to this instance.
    """
    t0 = time.monotonic()
    critical_results = await asyncio.gather(
        _check_redis(),
        _check_database(),
        _check_data_feed(),
        return_exceptions=True,
    )
    names = ["redis", "database", "data_feed"]
    components: dict[str, ComponentStatus] = {}
    for name, result in zip(names, critical_results):
        if isinstance(result, Exception):
            components[name] = ComponentStatus(status="error", latency_ms=0.0, detail=str(result)[:200])
        else:
            components[name] = result  # type: ignore[assignment]

    overall = _aggregate_status(components)
    total_ms = round((time.monotonic() - t0) * 1000, 2)

    body: dict[str, Any] = {
        "status": overall,
        "timestamp": _now_iso(),
        "uptime_seconds": _uptime(),
        "check_duration_ms": total_ms,
        "components": {k: v.model_dump() for k, v in components.items()},
    }

    if overall == "unhealthy":
        raise HTTPException(status_code=503, detail=body)

    return body


@health_router.get(
    "/health/detailed",
    response_model=HealthResponse,
    summary="Detailed health report",
    description=(
        "Full component breakdown including non-critical checks. "
        "Intended for monitoring dashboards and admin tooling."
    ),
)
async def detailed_health() -> HealthResponse:
    """
    Full health report — all components checked concurrently.

    Returns 200 regardless of component status so monitoring tools always
    receive the full breakdown. Use the ``status`` field to determine health.
    """
    components = await _run_all_checks()
    overall = _aggregate_status(components)

    return HealthResponse(
        status=overall,
        timestamp=_now_iso(),
        uptime_seconds=_uptime(),
        version=_version(),
        components=components,
    )


# ── Standalone runner (for Docker HEALTHCHECK) ────────────────────────────────


async def _standalone_check() -> int:
    """
    Run a quick readiness check and exit 0 (healthy) or 1 (unhealthy).

    Used by Docker HEALTHCHECK:
        HEALTHCHECK CMD python health_check_service.py || exit 1
    """
    components = {
        "redis": await _check_redis(),
        "database": await _check_database(),
        "data_feed": await _check_data_feed(),
    }
    overall = _aggregate_status(components)

    for name, comp in components.items():
        icon = "✅" if comp.status == "ok" else ("⚠️" if comp.status == "degraded" else "❌")
        print(f"  {icon} {name}: {comp.status} ({comp.latency_ms:.1f}ms) — {comp.detail}")

    print(f"\nOverall: {overall}")
    return 0 if overall != "unhealthy" else 1


if __name__ == "__main__":
    import sys

    exit_code = asyncio.run(_standalone_check())
    sys.exit(exit_code)

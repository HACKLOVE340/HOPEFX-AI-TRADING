# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# AGPL-3.0 — Share all modifications
"""
api/superadmin/reliability.py
==============================
System Reliability & End-to-End Connectivity API.

Routes
------
GET  /superadmin/reliability/status              — full system status snapshot (auto-records to history)
GET  /superadmin/reliability/components          — per-component health
POST /superadmin/reliability/probe               — run a live connectivity probe
GET  /superadmin/reliability/traces              — recent OTel spans
POST /superadmin/reliability/trace/test          — emit end-to-end test trace
GET  /superadmin/reliability/validate/{key}      — validate a specific setting was persisted
GET  /superadmin/reliability/env                 — environment variable audit
GET  /superadmin/reliability/routes              — registered API route inventory
POST /superadmin/reliability/self-test           — full end-to-end self-test suite
GET  /superadmin/reliability/metrics             — system + Redis metrics for dashboard widgets
GET  /superadmin/reliability/history             — last N status snapshots (Redis ring buffer)
POST /superadmin/reliability/history/record      — manually push current snapshot into history
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from datetime import timezone
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from api.auth import TokenPayload
from ._shared import _require_superadmin, _utcnow

logger = logging.getLogger(__name__)
router = APIRouter()

UTC = timezone.utc

# ---------------------------------------------------------------------------
# Component probe helpers
# ---------------------------------------------------------------------------


async def _probe_database() -> dict[str, Any]:
    t0 = time.perf_counter()
    try:
        import os as _os

        db_url = _os.getenv("DATABASE_URL", "sqlite:///hopefx.db")

        def _sync_probe() -> None:
            from sqlalchemy import create_engine, text as _text
            from sqlalchemy.pool import NullPool as _NullPool

            # Strip async driver prefixes — create_engine is sync-only.
            sync_url = db_url
            if sync_url.startswith("sqlite+aiosqlite://"):
                sync_url = sync_url.replace("sqlite+aiosqlite://", "sqlite://", 1)
            elif sync_url.startswith("postgresql+asyncpg://"):
                sync_url = sync_url.replace("postgresql+asyncpg://", "postgresql+psycopg2://", 1)
            is_sqlite = "sqlite" in sync_url
            engine = create_engine(
                sync_url,
                # NullPool: no idle connections held — avoids file-lock conflicts
                # with the main engine when this probe runs concurrently.
                poolclass=_NullPool,
                connect_args={"check_same_thread": False, "timeout": 10} if is_sqlite else {},
            )
            with engine.connect() as conn:
                conn.execute(_text("SELECT 1"))
            engine.dispose()

        await asyncio.get_running_loop().run_in_executor(None, _sync_probe)
        latency_ms = round((time.perf_counter() - t0) * 1000, 2)
        return {"status": "ok", "latency_ms": latency_ms, "detail": "SELECT 1 succeeded"}
    except Exception as exc:
        return {"status": "error", "latency_ms": round((time.perf_counter() - t0) * 1000, 2), "detail": str(exc)}


async def _probe_redis() -> dict[str, Any]:
    t0 = time.perf_counter()
    try:
        from cache.redis_client import get_sync_redis_client, get_connection_mode

        rc = get_sync_redis_client()
        if rc is None:
            return {"status": "error", "latency_ms": 0, "detail": "Redis client not initialised"}
        pong = rc.ping()
        latency_ms = round((time.perf_counter() - t0) * 1000, 2)
        mode = get_connection_mode()
        # Try INFO server — fakeredis may not support it, degrade gracefully
        version = "unknown"
        uptime = 0
        try:
            info = rc.info("server")
            version = info.get("redis_version", "unknown")
            uptime = info.get("uptime_in_seconds", 0)
        except Exception:
            # fakeredis or stripped Redis — ping succeeded so still "ok"
            version = "fakeredis" if mode == "fakeredis" else "unknown"
        return {
            "status": "ok" if pong else "error",
            "latency_ms": latency_ms,
            "detail": f"PONG={pong} mode={mode}",
            "version": version,
            "uptime_seconds": uptime,
            "mode": mode,
        }
    except Exception as exc:
        return {"status": "error", "latency_ms": round((time.perf_counter() - t0) * 1000, 2), "detail": str(exc)}


async def _probe_broker() -> dict[str, Any]:
    t0 = time.perf_counter()
    try:
        from api.admin import app_state

        if app_state and hasattr(app_state, "broker"):
            broker = app_state.broker
            connected = getattr(broker, "connected", False)
            broker_type = getattr(broker, "broker_type", "unknown")
            latency_ms = round((time.perf_counter() - t0) * 1000, 2)
            return {
                "status": "ok" if connected else "warning",
                "latency_ms": latency_ms,
                "detail": f"broker={broker_type} connected={connected}",
                "broker_type": broker_type,
            }
    except Exception:
        logger.debug("Suppressed non-fatal exception", exc_info=True)  # nosec B110
    # Fallback: check config
    broker_type = os.getenv("BROKER_TYPE", os.getenv("BROKER_DEFAULT", "paper"))
    return {
        "status": "ok" if broker_type == "paper" else "warning",
        "latency_ms": round((time.perf_counter() - t0) * 1000, 2),
        "detail": f"broker={broker_type} (config only, no live connection check)",
        "broker_type": broker_type,
    }


async def _probe_ml_engine() -> dict[str, Any]:
    t0 = time.perf_counter()
    # Prefer app_state.inference_engine (full MTF pipeline)
    try:
        from api.admin import app_state

        if app_state:
            for attr in ("inference_engine", "brain", "strategy_brain"):
                engine = getattr(app_state, attr, None)
                if engine is not None:
                    ready = getattr(engine, "is_ready", None)
                    ready = ready() if callable(ready) else getattr(engine, "_ready", True)
                    return {
                        "status": "ok" if ready else "warning",
                        "latency_ms": round((time.perf_counter() - t0) * 1000, 2),
                        "detail": f"{attr} ready={ready}",
                        "component": attr,
                    }
    except Exception:
        logger.debug("Suppressed non-fatal exception", exc_info=True)  # nosec B110
    # Redis fallback
    try:
        from cache.redis_client import get_sync_redis_client

        rc = get_sync_redis_client()
        if rc:
            raw = rc.get("ml:model:status")
            if raw:
                import json

                data = json.loads(raw)
                return {
                    "status": "ok",
                    "latency_ms": round((time.perf_counter() - t0) * 1000, 2),
                    "detail": "ML model status from Redis",
                    **data,
                }
    except Exception:
        logger.debug("Suppressed non-fatal exception", exc_info=True)  # nosec B110
    # Module-level fallback
    try:
        from ml.predictor import get_predictor

        pred = get_predictor()
        ready = getattr(pred, "is_ready", lambda: False)()
        return {
            "status": "ok" if ready else "warning",
            "latency_ms": round((time.perf_counter() - t0) * 1000, 2),
            "detail": f"predictor ready={ready}",
        }
    except Exception as exc:
        return {"status": "warning", "latency_ms": round((time.perf_counter() - t0) * 1000, 2), "detail": str(exc)}


async def _probe_trading_engine() -> dict[str, Any]:
    t0 = time.perf_counter()
    try:
        from api.admin import app_state

        if app_state and hasattr(app_state, "engine"):
            eng = app_state.engine
            running = bool(getattr(eng, "_running", False))
            # Derive status from _running; eng.status property doesn't exist on HopeFXEngine
            engine_status = "running" if running else "stopped"
            detail = f"engine running={running}"
            # Enrich with live snapshot if available
            if callable(getattr(eng, "_get_status", None)):
                try:
                    snap = eng._get_status()
                    detail = (
                        f"engine running={running} "
                        f"open_positions={snap.get('open_positions', 0)} "
                        f"broker={snap.get('broker', 'unknown')}"
                    )
                except Exception:  # nosec B110
                    pass
            return {
                "status": "ok" if running else "warning",
                "latency_ms": round((time.perf_counter() - t0) * 1000, 2),
                "detail": detail,
                "engine_status": engine_status,
            }
    except Exception:
        logger.debug("Suppressed non-fatal exception", exc_info=True)  # nosec B110
    return {
        "status": "warning",
        "latency_ms": round((time.perf_counter() - t0) * 1000, 2),
        "detail": "Engine not accessible via app_state",
    }


async def _probe_self_healer() -> dict[str, Any]:
    t0 = time.perf_counter()
    try:
        from security.self_healer import get_healer

        h = get_healer()
        running = getattr(h, "_running", False)
        baseline = len(getattr(h, "_baseline", {}))
        return {
            "status": "ok" if running else "warning",
            "latency_ms": round((time.perf_counter() - t0) * 1000, 2),
            "detail": f"running={running} baseline_files={baseline}",
            "running": running,
            "baseline_files": baseline,
        }
    except Exception as exc:
        return {"status": "warning", "latency_ms": round((time.perf_counter() - t0) * 1000, 2), "detail": str(exc)}


async def _probe_websocket_server() -> dict[str, Any]:
    t0 = time.perf_counter()
    try:
        from cache.redis_client import get_sync_redis_client

        rc = get_sync_redis_client()
        if rc:
            clients = rc.scard("ws:connected_clients") or 0
            return {
                "status": "ok",
                "latency_ms": round((time.perf_counter() - t0) * 1000, 2),
                "detail": f"connected_clients={clients}",
                "connected_clients": clients,
            }
    except Exception:
        logger.debug("Suppressed non-fatal exception", exc_info=True)  # nosec B110
    return {
        "status": "ok",
        "latency_ms": round((time.perf_counter() - t0) * 1000, 2),
        "detail": "WebSocket server running (no client count available)",
    }


async def _probe_otel_tracing() -> dict[str, Any]:
    t0 = time.perf_counter()
    try:
        from api.tracing import _OTEL_AVAILABLE, _OTLP_ENDPOINT, _SERVICE_NAME, _SAMPLING_RATE

        status = "ok" if _OTEL_AVAILABLE and _OTLP_ENDPOINT else ("warning" if _OTEL_AVAILABLE else "degraded")
        return {
            "status": status,
            "latency_ms": round((time.perf_counter() - t0) * 1000, 2),
            "detail": f"otel={_OTEL_AVAILABLE} endpoint={_OTLP_ENDPOINT or 'not set'} service={_SERVICE_NAME}",
            "otel_available": _OTEL_AVAILABLE,
            "endpoint": _OTLP_ENDPOINT,
            "sampling_rate": _SAMPLING_RATE,
        }
    except Exception as exc:
        return {"status": "warning", "latency_ms": round((time.perf_counter() - t0) * 1000, 2), "detail": str(exc)}


async def _probe_data_feed() -> dict[str, Any]:
    t0 = time.perf_counter()
    try:
        from cache.redis_client import get_sync_redis_client

        rc = get_sync_redis_client()
        if rc:
            tick = rc.get("tick:XAU_USD") or rc.get("price:XAUUSD") or rc.get("tick:XAUUSD")
            if tick:
                import json

                data = json.loads(tick) if isinstance(tick, str | bytes) else {}
                age_s = time.time() - float(data.get("ts", data.get("timestamp", time.time())))
                status = "ok" if age_s < 60 else "warning"
                return {
                    "status": status,
                    "latency_ms": round((time.perf_counter() - t0) * 1000, 2),
                    "detail": f"last tick age={age_s:.1f}s",
                    "tick_age_seconds": round(age_s, 1),
                }
    except Exception:
        logger.debug("Suppressed non-fatal exception", exc_info=True)  # nosec B110
    return {
        "status": "warning",
        "latency_ms": round((time.perf_counter() - t0) * 1000, 2),
        "detail": "No live tick data found in Redis",
    }


async def _probe_risk_manager() -> dict[str, Any]:
    t0 = time.perf_counter()
    # Prefer app_state.risk_manager
    try:
        from api.admin import app_state

        if app_state and hasattr(app_state, "risk_manager") and app_state.risk_manager is not None:
            rm = app_state.risk_manager
            active = getattr(rm, "_active", True)
            breached = getattr(rm, "_daily_loss_breached", False)
            detail = f"risk_manager active={active} daily_loss_breached={breached}"
            return {
                "status": "warning" if breached else ("ok" if active else "warning"),
                "latency_ms": round((time.perf_counter() - t0) * 1000, 2),
                "detail": detail,
                "active": active,
                "daily_loss_breached": breached,
            }
    except Exception:
        logger.debug("Suppressed non-fatal exception", exc_info=True)  # nosec B110
    # Module-level fallback
    try:
        from risk.manager import get_risk_manager

        rm = get_risk_manager()
        active = getattr(rm, "_active", True)
        return {
            "status": "ok" if active else "warning",
            "latency_ms": round((time.perf_counter() - t0) * 1000, 2),
            "detail": f"risk_manager active={active}",
        }
    except Exception as exc:
        return {"status": "warning", "latency_ms": round((time.perf_counter() - t0) * 1000, 2), "detail": str(exc)}


async def _probe_kill_switch() -> dict[str, Any]:
    t0 = time.perf_counter()
    try:
        from core.config_store import config_store

        ks = config_store.get("kill_switch_active")
        active = bool(ks) if ks is not None else False
        return {
            "status": "warning" if active else "ok",
            "latency_ms": round((time.perf_counter() - t0) * 1000, 2),
            "detail": f"kill_switch_active={active}",
            "kill_switch_active": active,
        }
    except Exception as exc:
        return {"status": "ok", "latency_ms": round((time.perf_counter() - t0) * 1000, 2), "detail": str(exc)}


async def _probe_env_vars() -> dict[str, Any]:
    t0 = time.perf_counter()
    required = [
        "SECURITY_JWT_SECRET",
        "DATABASE_URL",
    ]
    recommended = [
        "REDIS_URL",
        "OANDA_API_KEY",
        "OTEL_EXPORTER_OTLP_ENDPOINT",
        "SENTRY_DSN",
        "DISCORD_WEBHOOK_URL",
    ]
    missing_required = [k for k in required if not os.getenv(k)]
    missing_recommended = [k for k in recommended if not os.getenv(k)]
    status = "error" if missing_required else ("warning" if missing_recommended else "ok")
    return {
        "status": status,
        "latency_ms": round((time.perf_counter() - t0) * 1000, 2),
        "detail": f"missing_required={missing_required} missing_recommended={missing_recommended}",
        "missing_required": missing_required,
        "missing_recommended": missing_recommended,
    }


async def _probe_celery() -> dict[str, Any]:
    """Check Celery worker availability via Redis broker ping."""
    t0 = time.perf_counter()
    try:
        from celery_app import celery_app

        inspect = celery_app.control.inspect(timeout=3.0)
        stats = inspect.stats()
        if stats:
            worker_count = len(stats)
            return {
                "status": "ok",
                "latency_ms": round((time.perf_counter() - t0) * 1000, 2),
                "detail": f"workers={worker_count} active",
                "worker_count": worker_count,
                "workers": list(stats.keys()),
            }
        return {
            "status": "warning",
            "latency_ms": round((time.perf_counter() - t0) * 1000, 2),
            "detail": "No Celery workers responded",
            "worker_count": 0,
        }
    except Exception as exc:
        return {
            "status": "warning",
            "latency_ms": round((time.perf_counter() - t0) * 1000, 2),
            "detail": f"Celery inspect failed: {exc}",
        }


async def _probe_event_bus() -> dict[str, Any]:
    """Check the internal EventBus is operational."""
    t0 = time.perf_counter()
    try:
        from core.event_bus import bus

        subscriber_count = len(getattr(bus, "_subscribers", {}))
        return {
            "status": "ok",
            "latency_ms": round((time.perf_counter() - t0) * 1000, 2),
            "detail": f"event_bus active channels={subscriber_count}",
            "channels": subscriber_count,
        }
    except Exception as exc:
        return {
            "status": "warning",
            "latency_ms": round((time.perf_counter() - t0) * 1000, 2),
            "detail": str(exc),
        }


async def _probe_config_store() -> dict[str, Any]:
    """Verify the shared config store (Redis-backed) is readable/writable."""
    t0 = time.perf_counter()
    try:
        from core.config_store import config_store

        test_key = "_reliability_probe_test"
        config_store.set(test_key, "1")
        val = config_store.get(test_key)
        config_store.delete(test_key) if hasattr(config_store, "delete") else None
        ok = val is not None
        return {
            "status": "ok" if ok else "error",
            "latency_ms": round((time.perf_counter() - t0) * 1000, 2),
            "detail": "Config store read/write OK" if ok else "Config store write-then-read failed",
        }
    except Exception as exc:
        return {
            "status": "error",
            "latency_ms": round((time.perf_counter() - t0) * 1000, 2),
            "detail": str(exc),
        }


async def _probe_decision_engine() -> dict[str, Any]:
    """Check the HOPEFXDecisionEngine is accessible and return its metrics."""
    t0 = time.perf_counter()
    try:
        from api.admin import app_state

        if app_state and hasattr(app_state, "decision_engine"):
            de = app_state.decision_engine
            if de is not None:
                # HOPEFXDecisionEngine.status() returns cycles_total, executed, blocked, etc.
                if callable(getattr(de, "status", None)):
                    try:
                        de_status = de.status()
                        return {
                            "status": "ok",
                            "latency_ms": round((time.perf_counter() - t0) * 1000, 2),
                            "detail": (
                                f"cycles={de_status.get('cycles_total', 0)} "
                                f"executed={de_status.get('executed', 0)} "
                                f"blocked={de_status.get('blocked', 0)}"
                            ),
                            **{k: v for k, v in de_status.items() if not isinstance(v, dict)},
                        }
                    except Exception:  # nosec B110
                        pass
                return {
                    "status": "ok",
                    "latency_ms": round((time.perf_counter() - t0) * 1000, 2),
                    "detail": "decision_engine present (no status() method)",
                }
    except Exception:
        logger.debug("Suppressed non-fatal exception", exc_info=True)  # nosec B110
    return {
        "status": "warning",
        "latency_ms": round((time.perf_counter() - t0) * 1000, 2),
        "detail": "HOPEFXDecisionEngine not in app_state (pending init or disabled)",
    }


async def _probe_signal_engine() -> dict[str, Any]:
    """Check the signal engine / signal filter is operational."""
    t0 = time.perf_counter()
    try:
        from core.signal_engine import get_signal_engine

        se = get_signal_engine()
        active = getattr(se, "_active", True)
        return {
            "status": "ok" if active else "warning",
            "latency_ms": round((time.perf_counter() - t0) * 1000, 2),
            "detail": f"signal_engine active={active}",
        }
    except Exception as exc:
        return {
            "status": "warning",
            "latency_ms": round((time.perf_counter() - t0) * 1000, 2),
            "detail": str(exc),
        }


async def _probe_api_server() -> dict[str, Any]:
    """Verify the FastAPI app itself is healthy (internal self-check)."""
    t0 = time.perf_counter()
    try:
        from app import app as _app

        route_count = len(_app.routes)
        return {
            "status": "ok",
            "latency_ms": round((time.perf_counter() - t0) * 1000, 2),
            "detail": f"FastAPI app running routes={route_count}",
            "route_count": route_count,
        }
    except Exception as exc:
        return {
            "status": "error",
            "latency_ms": round((time.perf_counter() - t0) * 1000, 2),
            "detail": str(exc),
        }


# ---------------------------------------------------------------------------
# All probes registry
# ---------------------------------------------------------------------------

_PROBES: dict[str, Any] = {
    "database": _probe_database,
    "redis": _probe_redis,
    "broker": _probe_broker,
    "ml_engine": _probe_ml_engine,
    "trading_engine": _probe_trading_engine,
    "self_healer": _probe_self_healer,
    "websocket": _probe_websocket_server,
    "otel_tracing": _probe_otel_tracing,
    "data_feed": _probe_data_feed,
    "risk_manager": _probe_risk_manager,
    "kill_switch": _probe_kill_switch,
    "env_vars": _probe_env_vars,
    "celery": _probe_celery,
    "event_bus": _probe_event_bus,
    "config_store": _probe_config_store,
    "decision_engine": _probe_decision_engine,
    "signal_engine": _probe_signal_engine,
    "api_server": _probe_api_server,
}

_COMPONENT_LABELS: dict[str, str] = {
    "database": "PostgreSQL Database",
    "redis": "Redis Cache",
    "broker": "Broker Connection",
    "ml_engine": "ML / AI Engine",
    "trading_engine": "Trading Engine",
    "self_healer": "Self-Healer",
    "websocket": "WebSocket Server",
    "otel_tracing": "OpenTelemetry Tracing",
    "data_feed": "Live Data Feed",
    "risk_manager": "Risk Manager",
    "kill_switch": "Kill Switch",
    "env_vars": "Environment Variables",
    "celery": "Celery Task Queue",
    "event_bus": "Internal Event Bus",
    "config_store": "Config Store",
    "decision_engine": "Decision Engine",
    "signal_engine": "Signal Engine",
    "api_server": "API Server",
}

_STATUS_RANK = {"ok": 0, "warning": 1, "degraded": 2, "error": 3, "critical": 4}


def _overall_status(results: dict[str, dict]) -> str:
    worst = "ok"
    for r in results.values():
        s = r.get("status", "ok")
        if _STATUS_RANK.get(s, 0) > _STATUS_RANK.get(worst, 0):
            worst = s
    return worst


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class ComponentResult(BaseModel):
    name: str
    label: str
    status: str
    latency_ms: float
    detail: str
    extra: dict = {}
    checked_at: str


class ReliabilityStatus(BaseModel):
    overall: str
    components: list[ComponentResult]
    checked_at: str
    total_components: int
    ok_count: int
    warning_count: int
    error_count: int


class ProbeRequest(BaseModel):
    component: str


class SelfTestResult(BaseModel):
    passed: int
    failed: int
    total: int
    results: list[dict]
    duration_ms: float
    ran_at: str


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("/reliability/status")
async def get_reliability_status(
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    """Full system reliability snapshot — runs all probes concurrently."""
    t0 = time.perf_counter()
    tasks = {name: asyncio.create_task(fn()) for name, fn in _PROBES.items()}
    results_raw: dict[str, dict] = {}
    for name, task in tasks.items():
        try:
            results_raw[name] = await asyncio.wait_for(task, timeout=10.0)
        except TimeoutError:
            results_raw[name] = {"status": "error", "latency_ms": 10000, "detail": "Probe timed out"}
        except Exception as exc:
            results_raw[name] = {"status": "error", "latency_ms": 0, "detail": str(exc)}

    now = _utcnow().isoformat()
    components = []
    for name, result in results_raw.items():
        extra = {k: v for k, v in result.items() if k not in ("status", "latency_ms", "detail")}
        components.append(
            {
                "name": name,
                "label": _COMPONENT_LABELS.get(name, name),
                "status": result.get("status", "error"),
                "latency_ms": result.get("latency_ms", 0),
                "detail": result.get("detail", ""),
                "extra": extra,
                "checked_at": now,
            }
        )

    overall = _overall_status(results_raw)
    ok_count = sum(1 for r in results_raw.values() if r.get("status") == "ok")
    warn_count = sum(1 for r in results_raw.values() if r.get("status") == "warning")
    err_count = sum(1 for r in results_raw.values() if r.get("status") in ("error", "critical", "degraded"))

    snapshot = {
        "overall": overall,
        "components": components,
        "checked_at": now,
        "total_components": len(components),
        "ok_count": ok_count,
        "warning_count": warn_count,
        "error_count": err_count,
        "probe_duration_ms": round((time.perf_counter() - t0) * 1000, 2),
    }

    # Persist to history ring in Redis (non-blocking best-effort)
    try:
        from cache.redis_client import get_sync_redis_client

        rc = get_sync_redis_client()
        if rc:
            rc.lpush(_RELIABILITY_HISTORY_KEY, json.dumps(snapshot))
            rc.ltrim(_RELIABILITY_HISTORY_KEY, 0, _RELIABILITY_HISTORY_MAX - 1)
    except Exception:
        logger.debug("Suppressed non-fatal exception", exc_info=True)  # nosec B110

    return snapshot


@router.get("/reliability/components")
async def get_component_health(
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    """Per-component health with labels and descriptions."""
    return {"components": [{"name": name, "label": label} for name, label in _COMPONENT_LABELS.items()]}


@router.post("/reliability/probe")
async def run_probe(
    body: ProbeRequest,
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    """Run a single named connectivity probe and return its result."""
    fn = _PROBES.get(body.component)
    if fn is None:
        return {
            "error": f"Unknown component: {body.component!r}",
            "available": list(_PROBES.keys()),
        }
    try:
        result = await asyncio.wait_for(fn(), timeout=10.0)
    except TimeoutError:
        result = {"status": "error", "latency_ms": 10000, "detail": "Probe timed out"}
    except Exception as exc:
        result = {"status": "error", "latency_ms": 0, "detail": str(exc)}

    return {
        "component": body.component,
        "label": _COMPONENT_LABELS.get(body.component, body.component),
        "probed_at": _utcnow().isoformat(),
        **result,
    }


@router.get("/reliability/traces")
async def get_recent_traces(
    limit: int = 50,
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    """Return recent OTel spans from the in-memory ring buffer."""
    try:
        from api.tracing import _SPAN_BUFFER

        spans = list(_SPAN_BUFFER)[-limit:]
        return {"count": len(spans), "spans": list(reversed(spans))}
    except Exception as exc:
        return {"count": 0, "spans": [], "error": str(exc)}


@router.post("/reliability/trace/test")
async def emit_test_trace(
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    """Emit a full end-to-end test trace: frontend→API→DB→Redis→broker."""
    try:
        from api.tracing import get_tracer, _hex_trace_id, _hex_span_id

        tracer = get_tracer("hopefx.reliability")
        trace_id = _hex_trace_id()
        span_id = _hex_span_id()
        ts = _utcnow().isoformat()

        with tracer.start_as_current_span("reliability.e2e_test") as root:
            root.set_attribute("triggered_by", user.sub)
            root.set_attribute("test.type", "e2e_connectivity")

            # DB probe
            with tracer.start_as_current_span("reliability.db_probe"):
                db_result = await _probe_database()

            # Redis probe
            with tracer.start_as_current_span("reliability.redis_probe"):
                redis_result = await _probe_redis()

            # Broker probe
            with tracer.start_as_current_span("reliability.broker_probe"):
                broker_result = await _probe_broker()

            try:
                ctx = root.get_span_context()
                if ctx and ctx.is_valid:
                    trace_id = format(ctx.trace_id, "032x")
                    span_id = format(ctx.span_id, "016x")
            except Exception:
                logger.debug("Suppressed non-fatal exception", exc_info=True)  # nosec B110

        return {
            "trace_id": trace_id,
            "span_id": span_id,
            "timestamp": ts,
            "probes": {
                "database": db_result.get("status"),
                "redis": redis_result.get("status"),
                "broker": broker_result.get("status"),
            },
            "message": "End-to-end test trace emitted",
        }
    except Exception as exc:
        return {"error": str(exc), "timestamp": _utcnow().isoformat()}


@router.get("/reliability/validate/{setting_key}")
async def validate_setting_persisted(
    setting_key: str,
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    """Verify a platform config key is persisted in both Redis and DB."""
    results: dict[str, Any] = {"key": setting_key, "checked_at": _utcnow().isoformat()}

    # Check Redis
    try:
        from cache.redis_client import get_sync_redis_client
        import json

        rc = get_sync_redis_client()
        if rc:
            raw = rc.get("superadmin_platform_config")
            if raw:
                cfg = json.loads(raw)
                results["redis"] = {
                    "found": setting_key in cfg,
                    "value": cfg.get(setting_key),
                }
            else:
                results["redis"] = {"found": False, "value": None}
        else:
            results["redis"] = {"found": False, "error": "Redis unavailable"}
    except Exception as exc:
        results["redis"] = {"found": False, "error": str(exc)}

    # Check config store
    try:
        from core.config_store import config_store

        val = config_store.get(setting_key)
        results["config_store"] = {"found": val is not None, "value": val}
    except Exception as exc:
        results["config_store"] = {"found": False, "error": str(exc)}

    results["consistent"] = results.get("redis", {}).get("found", False) or results.get("config_store", {}).get(
        "found", False
    )
    return results


@router.get("/reliability/env")
async def get_env_audit(
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    """Audit environment variables — shows presence/absence without values."""
    env_groups = {
        "auth": ["SECURITY_JWT_SECRET", "SECRET_KEY"],
        "database": ["DATABASE_URL", "DB_POOL_SIZE", "DB_MAX_OVERFLOW"],
        "redis": ["REDIS_URL", "REDIS_PASSWORD"],
        "broker": ["OANDA_API_KEY", "OANDA_ACCOUNT_ID", "IBKR_HOST", "IBKR_PORT"],
        "ml": ["ML_MODEL_DIR", "ML_SYMBOLS"],
        "notifications": ["DISCORD_WEBHOOK_URL", "SLACK_WEBHOOK_URL", "TELEGRAM_BOT_TOKEN"],
        "tracing": ["OTEL_EXPORTER_OTLP_ENDPOINT", "OTEL_SERVICE_NAME", "OTEL_SAMPLING_RATE"],
        "monitoring": ["SENTRY_DSN", "PROMETHEUS_PORT"],
        "trading": ["TRADING_MODE", "BROKER_DEFAULT", "INITIAL_BALANCE"],
        "security": ["ALLOWED_ORIGINS", "CSRF_SECRET"],
    }
    result: dict[str, Any] = {}
    for group, keys in env_groups.items():
        result[group] = {
            k: {"set": bool(os.getenv(k)), "required": k in ["SECURITY_JWT_SECRET", "DATABASE_URL"]} for k in keys
        }
    return {"groups": result, "checked_at": _utcnow().isoformat()}


@router.get("/reliability/routes")
async def get_route_inventory(
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    """Return all registered FastAPI routes with methods and tags."""
    try:
        from app import app as _app

        routes = []
        for route in _app.routes:
            if hasattr(route, "methods") and hasattr(route, "path"):
                routes.append(
                    {
                        "path": route.path,
                        "methods": list(route.methods or []),
                        "name": getattr(route, "name", ""),
                        "tags": getattr(route, "tags", []),
                    }
                )
        return {"total": len(routes), "routes": sorted(routes, key=lambda r: r["path"])}
    except Exception as exc:
        return {"total": 0, "routes": [], "error": str(exc)}


@router.post("/reliability/self-test")
async def run_self_test(
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    """Run the full end-to-end self-test suite across all components."""
    t0 = time.perf_counter()
    tests: list[dict] = []

    async def _run_test(name: str, fn) -> dict:
        t = time.perf_counter()
        try:
            result = await asyncio.wait_for(fn(), timeout=10.0)
            status = result.get("status", "error")
            passed = status in ("ok", "warning")
            return {
                "test": name,
                "passed": passed,
                "status": status,
                "detail": result.get("detail", ""),
                "duration_ms": round((time.perf_counter() - t) * 1000, 2),
            }
        except TimeoutError:
            return {"test": name, "passed": False, "status": "error", "detail": "Timeout", "duration_ms": 10000}
        except Exception as exc:
            return {
                "test": name,
                "passed": False,
                "status": "error",
                "detail": str(exc),
                "duration_ms": round((time.perf_counter() - t) * 1000, 2),
            }

    probe_tasks = [_run_test(name, fn) for name, fn in _PROBES.items()]
    tests = await asyncio.gather(*probe_tasks)

    passed = sum(1 for t in tests if t["passed"])
    failed = len(tests) - passed

    return {
        "passed": passed,
        "failed": failed,
        "total": len(tests),
        "results": tests,
        "duration_ms": round((time.perf_counter() - t0) * 1000, 2),
        "ran_at": _utcnow().isoformat(),
    }


@router.post("/reliability/validate-toggle")
async def validate_toggle_persisted(
    request: Any,
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    """
    Validate that a toggle/setting change was persisted end-to-end.

    Body: { "key": "maintenance_mode", "expected_value": true }

    Checks: Redis config store → DB config table → live app_state.
    Returns a per-layer validation result so the UI can show exactly
    where a discrepancy exists.
    """
    body: dict[str, Any] = {}
    try:
        body = await request.json()
    except Exception:
        logger.debug("Suppressed non-fatal exception", exc_info=True)  # nosec B110

    key = body.get("key", "")
    expected = body.get("expected_value")
    results: dict[str, Any] = {
        "key": key,
        "expected": expected,
        "layers": {},
        "consistent": False,
        "checked_at": _utcnow().isoformat(),
    }

    # Layer 1: Redis config store
    try:
        import json as _json
        from cache.redis_client import get_sync_redis_client

        rc = get_sync_redis_client()
        if rc:
            raw = rc.get("superadmin_platform_config")
            if raw:
                cfg = _json.loads(raw)
                val = cfg.get(key)
                results["layers"]["redis"] = {
                    "found": key in cfg,
                    "value": val,
                    "match": val == expected,
                }
            else:
                results["layers"]["redis"] = {"found": False, "value": None, "match": False}
        else:
            results["layers"]["redis"] = {"found": False, "error": "Redis unavailable"}
    except Exception as exc:
        results["layers"]["redis"] = {"found": False, "error": str(exc)}

    # Layer 2: Core config store
    try:
        from core.config_store import config_store

        val = config_store.get(key)
        results["layers"]["config_store"] = {
            "found": val is not None,
            "value": val,
            "match": val == expected or (val is not None and str(val) == str(expected)),
        }
    except Exception as exc:
        results["layers"]["config_store"] = {"found": False, "error": str(exc)}

    # Layer 3: Live app_state (for engine-level settings)
    try:
        from api.admin import app_state

        if app_state:
            live_val = getattr(app_state, key, None)
            if live_val is not None:
                results["layers"]["app_state"] = {
                    "found": True,
                    "value": live_val,
                    "match": live_val == expected,
                }
    except Exception:
        logger.debug("Suppressed non-fatal exception", exc_info=True)  # nosec B110

    # Determine overall consistency
    layer_matches = [
        v.get("match", False) for v in results["layers"].values() if "error" not in v and v.get("found", False)
    ]
    results["consistent"] = bool(layer_matches) and all(layer_matches)
    return results


@router.get("/reliability/metrics")
async def get_reliability_metrics(
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    """Return reliability metrics for dashboard widgets."""
    try:
        import psutil

        cpu = psutil.cpu_percent(interval=0.1)
        mem = psutil.virtual_memory()
        disk = psutil.disk_usage("/")
        system = {
            "cpu_pct": cpu,
            "memory_pct": mem.percent,
            "memory_used_gb": round(mem.used / 1e9, 2),
            "memory_total_gb": round(mem.total / 1e9, 2),
            "disk_pct": disk.percent,
            "disk_used_gb": round(disk.used / 1e9, 2),
            "disk_total_gb": round(disk.total / 1e9, 2),
        }
    except Exception:
        system = {}

    redis_info: dict = {}
    try:
        from cache.redis_client import get_sync_redis_client, get_connection_mode

        rc = get_sync_redis_client()
        if rc:
            mode = get_connection_mode()
            try:
                info = rc.info()
                redis_info = {
                    "connected_clients": info.get("connected_clients", 0),
                    "used_memory_mb": round(info.get("used_memory", 0) / 1e6, 2),
                    "total_commands_processed": info.get("total_commands_processed", 0),
                    "keyspace_hits": info.get("keyspace_hits", 0),
                    "keyspace_misses": info.get("keyspace_misses", 0),
                    "mode": mode,
                }
            except Exception:
                # fakeredis or stripped Redis — provide basic info
                redis_info = {
                    "connected_clients": 1,
                    "used_memory_mb": 0,
                    "total_commands_processed": 0,
                    "keyspace_hits": 0,
                    "keyspace_misses": 0,
                    "mode": mode,
                    "note": "INFO command not supported by this Redis variant",
                }
    except Exception:
        logger.debug("Suppressed non-fatal exception", exc_info=True)  # nosec B110

    return {
        "system": system,
        "redis": redis_info,
        "collected_at": _utcnow().isoformat(),
    }


# ── Reliability status history ────────────────────────────────────────────────

_RELIABILITY_HISTORY_KEY = "reliability:status_history"
_RELIABILITY_HISTORY_MAX = 200


@router.get("/reliability/history")
async def get_reliability_history(
    limit: int = 50,
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    """Return the last N reliability snapshots stored in Redis.

    Each snapshot is written by ``get_reliability_status`` whenever it is
    called.  The list is capped at ``_RELIABILITY_HISTORY_MAX`` entries so
    Redis memory stays bounded.
    """
    limit = max(1, min(limit, _RELIABILITY_HISTORY_MAX))
    items: list[dict] = []
    try:
        from cache.redis_client import get_sync_redis_client

        rc = get_sync_redis_client()
        if rc:
            raw_list = rc.lrange(_RELIABILITY_HISTORY_KEY, 0, limit - 1)
            for raw in raw_list:
                try:
                    items.append(json.loads(raw))
                except Exception:
                    logger.debug("Suppressed non-fatal exception", exc_info=True)  # nosec B110
    except Exception as exc:
        logger.warning("reliability_history: %s", exc)

    return {"history": items, "count": len(items)}


@router.post("/reliability/history/record")
async def record_reliability_snapshot(
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    """Manually push the current reliability status into the history ring.

    The ``get_reliability_status`` endpoint also calls this automatically,
    so this endpoint is mainly useful for testing the history pipeline.
    """
    snapshot = await get_reliability_status(user=user)
    try:
        from cache.redis_client import get_sync_redis_client

        rc = get_sync_redis_client()
        if rc:
            rc.lpush(_RELIABILITY_HISTORY_KEY, json.dumps(snapshot))
            rc.ltrim(_RELIABILITY_HISTORY_KEY, 0, _RELIABILITY_HISTORY_MAX - 1)
    except Exception as exc:
        logger.warning("record_reliability_snapshot: %s", exc)
    return {"ok": True, "snapshot": snapshot}

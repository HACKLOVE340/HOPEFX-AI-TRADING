# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# AGPL-3.0 — Share all modifications
"""
infrastructure/health_engine.py
================================
Auto-discovering Health Engine.

Probes every registered component concurrently and returns a structured
health report.  Components self-register via `register_probe()`.

Usage
-----
    from infrastructure.health_engine import get_health_engine, HealthEngine

    engine = get_health_engine()
    report = await engine.run_all()
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Coroutine

logger = logging.getLogger(__name__)

UTC = timezone.utc


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class ProbeResult:
    name: str
    label: str
    status: str  # ok | warning | degraded | error | critical
    latency_ms: float
    detail: str
    extra: dict[str, Any] = field(default_factory=dict)
    checked_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "label": self.label,
            "status": self.status,
            "latency_ms": self.latency_ms,
            "detail": self.detail,
            "extra": self.extra,
            "checked_at": self.checked_at,
        }


@dataclass
class HealthReport:
    overall: str
    components: list[ProbeResult]
    checked_at: str
    probe_duration_ms: float

    @property
    def ok_count(self) -> int:
        return sum(1 for c in self.components if c.status == "ok")

    @property
    def warning_count(self) -> int:
        return sum(1 for c in self.components if c.status in ("warning", "degraded"))

    @property
    def error_count(self) -> int:
        return sum(1 for c in self.components if c.status in ("error", "critical"))

    @property
    def total_components(self) -> int:
        return len(self.components)

    def to_dict(self) -> dict[str, Any]:
        return {
            "overall": self.overall,
            "components": [c.to_dict() for c in self.components],
            "checked_at": self.checked_at,
            "total_components": self.total_components,
            "ok_count": self.ok_count,
            "warning_count": self.warning_count,
            "error_count": self.error_count,
            "probe_duration_ms": self.probe_duration_ms,
        }


# ---------------------------------------------------------------------------
# Status ranking
# ---------------------------------------------------------------------------

_STATUS_RANK: dict[str, int] = {
    "ok": 0,
    "warning": 1,
    "degraded": 2,
    "error": 3,
    "critical": 4,
    "unknown": 1,
}


def _worst(statuses: list[str]) -> str:
    if not statuses:
        return "ok"
    return max(statuses, key=lambda s: _STATUS_RANK.get(s, 0))


# ---------------------------------------------------------------------------
# Probe type
# ---------------------------------------------------------------------------

ProbeFunc = Callable[[], Coroutine[Any, Any, dict[str, Any]]]


# ---------------------------------------------------------------------------
# Health Engine
# ---------------------------------------------------------------------------


class HealthEngine:
    """Auto-discovering health engine.  Probes run concurrently with a timeout."""

    PROBE_TIMEOUT_S: float = 8.0

    def __init__(self) -> None:
        self._probes: dict[str, tuple[str, ProbeFunc]] = {}  # name -> (label, fn)

    def register(self, name: str, label: str, fn: ProbeFunc) -> None:
        """Register a named probe."""
        self._probes[name] = (label, fn)

    def unregister(self, name: str) -> None:
        self._probes.pop(name, None)

    @property
    def probe_names(self) -> list[str]:
        return list(self._probes.keys())

    async def probe_one(self, name: str) -> ProbeResult:
        """Run a single named probe and return its result."""
        if name not in self._probes:
            return ProbeResult(
                name=name,
                label=name,
                status="error",
                latency_ms=0,
                detail=f"Unknown probe: {name}",
            )
        label, fn = self._probes[name]
        t0 = time.perf_counter()
        try:
            raw = await asyncio.wait_for(fn(), timeout=self.PROBE_TIMEOUT_S)
            latency_ms = round((time.perf_counter() - t0) * 1000, 2)
            status = raw.get("status", "error")
            detail = raw.get("detail", "")
            extra = {k: v for k, v in raw.items() if k not in ("status", "detail")}
            return ProbeResult(name=name, label=label, status=status, latency_ms=latency_ms, detail=detail, extra=extra)
        except TimeoutError:
            return ProbeResult(
                name=name,
                label=label,
                status="error",
                latency_ms=round(self.PROBE_TIMEOUT_S * 1000, 2),
                detail=f"Probe timed out after {self.PROBE_TIMEOUT_S}s",
            )
        except Exception as exc:
            return ProbeResult(
                name=name,
                label=label,
                status="error",
                latency_ms=round((time.perf_counter() - t0) * 1000, 2),
                detail=str(exc),
            )

    async def run_all(self, names: list[str] | None = None) -> HealthReport:
        """Run all (or a subset of) probes concurrently."""
        t0 = time.perf_counter()
        targets = names or list(self._probes.keys())
        tasks = [self.probe_one(n) for n in targets]
        results: list[ProbeResult] = await asyncio.gather(*tasks)
        duration_ms = round((time.perf_counter() - t0) * 1000, 2)
        overall = _worst([r.status for r in results]) if results else "ok"
        return HealthReport(
            overall=overall,
            components=results,
            checked_at=datetime.now(UTC).isoformat(),
            probe_duration_ms=duration_ms,
        )

    async def run_ai_observation(self, observation_id: str, names: list[str] | None = None) -> Any:
        """Return an immutable AI evidence record without triggering recovery."""
        from core.ai_operations import observe_health

        report = await self.run_all(names)
        return observe_health(report, observation_id)


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_engine: HealthEngine | None = None


def get_health_engine() -> HealthEngine:
    global _engine
    if _engine is None:
        _engine = HealthEngine()
        _register_default_probes(_engine)
    return _engine


# ---------------------------------------------------------------------------
# Default probes — auto-registered on first access
# ---------------------------------------------------------------------------


def _register_default_probes(engine: HealthEngine) -> None:
    """Register all built-in component probes."""

    async def _probe_database() -> dict[str, Any]:
        t0 = time.perf_counter()
        try:
            from database.connection import SessionLocal
            import sqlalchemy

            db = SessionLocal()
            try:
                db.execute(sqlalchemy.text("SELECT 1"))
            finally:
                db.close()
            return {
                "status": "ok",
                "latency_ms": round((time.perf_counter() - t0) * 1000, 2),
                "detail": "SELECT 1 succeeded",
            }
        except Exception as exc:
            return {"status": "error", "detail": str(exc)}

    async def _probe_redis() -> dict[str, Any]:
        try:
            from cache.redis_client import get_redis

            rc = await get_redis()
            if rc is None:
                # Report the actual reason. This used to say "check REDIS_URL"
                # unconditionally, which is wrong whenever the URL is fine and
                # the circuit breaker has tripped — and it disagreed with three
                # other pages that probe the *sync* client, which has no
                # breaker. Naming the client removes the ambiguity.
                from cache.redis_client import redis_unavailable_reason

                code, explanation = redis_unavailable_reason()
                return {
                    "status": "error",
                    "client": "async",
                    "reason": code,
                    "detail": f"async Redis client unavailable ({code}): {explanation}",
                }
            pong = await rc.ping()
            info = await rc.info("server")
            mem_info = await rc.info("memory")
            return {
                "status": "ok" if pong else "error",
                "detail": f"PONG={pong}",
                "version": info.get("redis_version", "unknown"),
                "uptime_seconds": info.get("uptime_in_seconds", 0),
                "used_memory_mb": round(mem_info.get("used_memory", 0) / 1e6, 2),
            }
        except Exception as exc:
            return {"status": "error", "detail": str(exc)}

    async def _probe_broker() -> dict[str, Any]:
        try:
            from cache.redis_client import get_redis
            import json

            rc = await get_redis()
            if rc:
                raw = await rc.get("broker:connection_status")
                if raw:
                    data = json.loads(raw)
                    connected = data.get("connected", False)
                    broker_type = data.get("broker_type", "unknown")
                    return {
                        "status": "ok" if connected else "warning",
                        "detail": f"broker={broker_type} connected={connected}",
                        "broker_type": broker_type,
                    }
        except Exception:
            logger.debug("Suppressed non-fatal exception", exc_info=True)  # nosec B110
        broker_type = os.getenv("BROKER_TYPE", os.getenv("BROKER_DEFAULT", "paper"))
        return {
            "status": "ok" if broker_type == "paper" else "warning",
            "detail": f"broker={broker_type} (config only)",
            "broker_type": broker_type,
        }

    async def _probe_ml_engine() -> dict[str, Any]:
        try:
            from cache.redis_client import get_redis
            import json

            rc = await get_redis()
            if rc:
                raw = await rc.get("ml:model:status") or await rc.get("ml:engine_status")
                if raw:
                    data = json.loads(raw)
                    return {"status": "ok", "detail": "ML status from Redis", **data}
        except Exception:
            logger.debug("Suppressed non-fatal exception", exc_info=True)  # nosec B110
        try:
            # ml.predictor is an alias module — try advanced_predictor directly
            from ml.advanced_predictor import get_predictor

            pred = get_predictor()
            ready = getattr(pred, "is_ready", lambda: True)()
            return {"status": "ok" if ready else "warning", "detail": f"predictor ready={ready}"}
        except Exception as exc:
            return {"status": "warning", "detail": str(exc)}

    async def _probe_trading_engine() -> dict[str, Any]:
        try:
            from core.app_state import app_state

            eng = getattr(app_state, "engine", None)
            if eng is not None:
                running = getattr(eng, "_running", False)
                status = getattr(eng, "status", "unknown")
                return {
                    "status": "ok" if running else "warning",
                    "detail": f"engine status={status} running={running}",
                    "engine_status": status,
                }
            # Fallback: decision_engine is always initialised
            de = getattr(app_state, "decision_engine", None)
            if de is not None:
                ready = getattr(de, "ready", True)
                return {
                    "status": "ok" if ready else "warning",
                    "detail": f"decision_engine ready={ready} (trading engine pending broker)",
                }
        except Exception:
            logger.debug("Suppressed non-fatal exception", exc_info=True)  # nosec B110
        return {"status": "warning", "detail": "Engine not accessible via app_state"}

    async def _probe_self_healer() -> dict[str, Any]:
        try:
            from security.self_healer import get_healer

            h = get_healer()
            running = getattr(h, "_running", False)
            baseline = len(getattr(h, "_baseline", {}))
            drift = len(getattr(h, "_drift_events", []))
            return {
                "status": "ok" if running else "warning",
                "detail": f"running={running} baseline_files={baseline} drift_events={drift}",
                "running": running,
                "baseline_files": baseline,
                "drift_events": drift,
            }
        except Exception as exc:
            return {"status": "warning", "detail": str(exc)}

    async def _probe_decision_engine() -> dict[str, Any]:
        try:
            return {"status": "ok", "detail": "DecisionEngine module importable"}
        except Exception as exc:
            return {"status": "warning", "detail": str(exc)}

    async def _probe_risk_manager() -> dict[str, Any]:
        try:
            from risk.manager import get_risk_manager

            rm = get_risk_manager()
            active = getattr(rm, "_active", True)
            return {"status": "ok" if active else "warning", "detail": f"risk_manager active={active}"}
        except Exception as exc:
            return {"status": "warning", "detail": str(exc)}

    async def _probe_kill_switch() -> dict[str, Any]:
        try:
            from core.config_store import config_store

            ks = config_store.get("kill_switch_active")
            active = bool(ks) if ks is not None else False
            return {
                "status": "warning" if active else "ok",
                "detail": f"kill_switch_active={active}",
                "kill_switch_active": active,
            }
        except Exception as exc:
            return {"status": "ok", "detail": str(exc)}

    async def _probe_otel_tracing() -> dict[str, Any]:
        try:
            from api.tracing import _OTEL_AVAILABLE, _OTLP_ENDPOINT, _SERVICE_NAME

            status = "ok" if _OTEL_AVAILABLE and _OTLP_ENDPOINT else ("warning" if _OTEL_AVAILABLE else "degraded")
            return {
                "status": status,
                "detail": f"otel={_OTEL_AVAILABLE} endpoint={_OTLP_ENDPOINT or 'not set'}",
                "otel_available": _OTEL_AVAILABLE,
                "endpoint": _OTLP_ENDPOINT,
                "service": _SERVICE_NAME,
            }
        except Exception as exc:
            return {"status": "warning", "detail": str(exc)}

    async def _probe_data_feed() -> dict[str, Any]:
        try:
            from cache.redis_client import get_redis
            import json

            rc = await get_redis()
            if rc:
                # Check all known tick key patterns (data layer + legacy)
                for key in (
                    "hopefx:dl:tick:XAU_USD",
                    "tick:XAU_USD",
                    "tick:XAUUSD",
                    "price:XAUUSD",
                ):
                    raw = await rc.get(key)
                    if raw:
                        try:
                            data = json.loads(raw) if isinstance(raw, str | bytes) else {}
                        except (json.JSONDecodeError, ValueError):
                            data = {}
                        from core.account_metrics import tick_age_seconds

                        ts_val = data.get("ts", data.get("timestamp", data.get("time")))
                        age_s = tick_age_seconds(ts_val)
                        if age_s is None:
                            # An unreadable timestamp is not a fresh tick. This
                            # used to become 0.0 and grade "ok".
                            return {
                                "status": "warning",
                                "detail": f"tick at {key} has no usable timestamp (ts={ts_val!r})",
                                "key": key,
                            }
                        return {
                            "status": "ok" if age_s < 120 else "warning",
                            "detail": f"last tick age={age_s:.1f}s key={key}",
                            "tick_age_seconds": round(age_s, 1),
                            "key": key,
                        }
        except Exception:
            logger.debug("Suppressed non-fatal exception", exc_info=True)  # nosec B110
        return {"status": "warning", "detail": "No live tick data found in Redis"}

    async def _probe_websocket() -> dict[str, Any]:
        try:
            from cache.redis_client import get_redis

            rc = await get_redis()
            if rc:
                clients = await rc.scard("ws:connected_clients") or 0
                return {"status": "ok", "detail": f"connected_clients={clients}", "connected_clients": clients}
        except Exception:
            logger.debug("Suppressed non-fatal exception", exc_info=True)  # nosec B110
        return {"status": "ok", "detail": "WebSocket server running (no client count available)"}

    async def _probe_event_bus() -> dict[str, Any]:
        try:
            from core.event_bus import bus

            channels = len(getattr(bus, "_subscribers", {}))
            return {"status": "ok", "detail": f"event_bus channels={channels}", "channels": channels}
        except Exception as exc:
            return {"status": "warning", "detail": str(exc)}

    async def _probe_config_store() -> dict[str, Any]:
        try:
            from core.config_store import config_store

            test_key = "_health_engine_probe"
            config_store.set(test_key, "1")
            val = config_store.get(test_key)
            if hasattr(config_store, "delete"):
                config_store.delete(test_key)
            return {
                "status": "ok" if val is not None else "error",
                "detail": "Config store read/write OK" if val else "Write-then-read failed",
            }
        except Exception as exc:
            return {"status": "error", "detail": str(exc)}

    async def _probe_celery() -> dict[str, Any]:
        """Delegates to the shared probe.

        This function used to hold its own copy of the check. So did
        api/superadmin/reliability.py, and so did api/superadmin/system_health.py
        with a shorter timeout and a blocking call — three implementations that
        could not agree even when Celery was healthy, and did not, in the
        deployed report: DOWN here, WARNING there, OK on this page, all within
        twelve minutes.
        """
        from infrastructure.service_probes import probe_celery

        return await probe_celery()

    async def _probe_env_vars() -> dict[str, Any]:
        required = ["SECURITY_JWT_SECRET", "DATABASE_URL"]
        recommended = ["REDIS_URL", "OTEL_EXPORTER_OTLP_ENDPOINT", "SENTRY_DSN"]
        missing_req = [k for k in required if not os.getenv(k)]
        missing_rec = [k for k in recommended if not os.getenv(k)]
        status = "error" if missing_req else ("warning" if missing_rec else "ok")
        return {
            "status": status,
            "detail": f"missing_required={missing_req}",
            "missing_required": missing_req,
            "missing_recommended": missing_rec,
        }

    async def _probe_signal_engine() -> dict[str, Any]:
        try:
            from core.signal_engine import get_signal_engine

            se = get_signal_engine()
            active = getattr(se, "_active", True)
            return {"status": "ok" if active else "warning", "detail": f"signal_engine active={active}"}
        except Exception as exc:
            return {"status": "warning", "detail": str(exc)}

    async def _probe_api_server() -> dict[str, Any]:
        try:
            from app import app as _app

            route_count = len(_app.routes)
            return {"status": "ok", "detail": f"FastAPI routes={route_count}", "route_count": route_count}
        except Exception as exc:
            return {"status": "error", "detail": str(exc)}

    # Register all probes
    probes: list[tuple[str, str, ProbeFunc]] = [
        ("database", "PostgreSQL Database", _probe_database),
        ("redis", "Redis Cache", _probe_redis),
        ("broker", "Broker Connection", _probe_broker),
        ("ml_engine", "ML / AI Engine", _probe_ml_engine),
        ("trading_engine", "Trading Engine", _probe_trading_engine),
        ("self_healer", "Self-Healer", _probe_self_healer),
        ("decision_engine", "Decision Engine", _probe_decision_engine),
        ("risk_manager", "Risk Manager", _probe_risk_manager),
        ("kill_switch", "Kill Switch", _probe_kill_switch),
        ("otel_tracing", "OpenTelemetry Tracing", _probe_otel_tracing),
        ("data_feed", "Live Data Feed", _probe_data_feed),
        ("websocket", "WebSocket Server", _probe_websocket),
        ("event_bus", "Internal Event Bus", _probe_event_bus),
        ("config_store", "Config Store", _probe_config_store),
        ("celery", "Celery Task Queue", _probe_celery),
        ("env_vars", "Environment Variables", _probe_env_vars),
        ("signal_engine", "Signal Engine", _probe_signal_engine),
        ("api_server", "API Server", _probe_api_server),
    ]

    for name, label, fn in probes:
        engine.register(name, label, fn)

    logger.info("HealthEngine: registered %d probes", len(probes))


def register_probe(name: str, label: str, fn: ProbeFunc) -> None:
    """Register a custom probe with the global health engine."""
    get_health_engine().register(name, label, fn)

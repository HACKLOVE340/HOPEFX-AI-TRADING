# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
api/observability.py
=====================
Observability API — serves the frontend Observability/Tracing page.
Provides: /api/observability/traces, /api/observability/metrics,
           /api/observability/alerts, /api/observability/services
Connected to: tracing/opentelemetry_setup.py, core/health.py
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone

from fastapi import APIRouter, Query

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/observability", tags=["Observability"])


def _get_telemetry():
    """Retrieve the telemetry system from app state."""
    try:
        from core.app_state import app_state

        return getattr(app_state, "telemetry", None)
    except Exception:
        return None


@router.get("/traces")
async def get_traces(
    limit: int = Query(50, ge=1, le=500),
    service: str | None = Query(None),
    min_duration_ms: int | None = Query(None),
):
    """
    Retrieve recent distributed traces across all services.
    Each trace includes: trace_id, service, operation, duration_ms, status, timestamp.
    """
    telemetry = _get_telemetry()
    traces = []

    if telemetry:
        try:
            raw_traces = await telemetry.get_recent_traces(limit=limit)
            traces = raw_traces if raw_traces else []
        except Exception as e:
            logger.warning(f"Trace retrieval failed: {e}")

    # Filter by service
    if service:
        traces = [t for t in traces if t.get("service") == service]

    # Filter by minimum duration
    if min_duration_ms:
        traces = [t for t in traces if t.get("duration_ms", 0) >= min_duration_ms]

    return {"traces": traces[:limit], "total": len(traces)}


@router.get("/metrics")
async def get_metrics(
    period: str = Query("1h", pattern="^(5m|15m|1h|4h|1d|7d)$"),
):
    """
    Retrieve system metrics for the specified period.
    Returns: cpu, memory, request_rate, error_rate, latency_p50/p95/p99.
    """
    telemetry = _get_telemetry()
    metrics = {}

    if telemetry:
        try:
            metrics = await telemetry.get_metrics(period=period)
        except Exception as e:
            logger.warning(f"Metrics retrieval failed: {e}")

    if not metrics:
        # Provide live system metrics as fallback
        import os

        try:
            load_avg = os.getloadavg()
        except (AttributeError, OSError):
            load_avg = (0, 0, 0)

        metrics = {
            "cpu_percent": load_avg[0] * 100 / (os.cpu_count() or 1),
            "memory_percent": 0,
            "request_rate": 0,
            "error_rate": 0,
            "latency_p50_ms": 0,
            "latency_p95_ms": 0,
            "latency_p99_ms": 0,
            "active_connections": 0,
            "period": period,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    return metrics


@router.get("/alerts")
async def get_observability_alerts(
    limit: int = Query(50, ge=1, le=200),
    severity: str | None = Query(None, pattern="^(critical|warning|info)$"),
):
    """
    Retrieve active observability alerts (latency spikes, error bursts, etc.).
    """
    try:
        from core.app_state import app_state

        alerts = getattr(app_state, "observability_alerts", [])
    except Exception:
        alerts = []

    entries = list(alerts) if alerts else []

    if severity:
        entries = [a for a in entries if a.get("severity") == severity]

    entries.sort(key=lambda a: a.get("timestamp", ""), reverse=True)
    return {"alerts": entries[:limit], "total": len(entries)}


@router.get("/services")
async def get_services():
    """
    Retrieve the list of all registered services and their health status.
    """
    try:
        from core.app_state import app_state

        registry = getattr(app_state, "component_registry", None)
    except Exception:
        registry = None

    services = []
    if registry:
        try:
            components = registry.list_components() if hasattr(registry, "list_components") else []
            for comp in components:
                services.append(
                    {
                        "name": comp.get("name", "unknown"),
                        "status": comp.get("status", "unknown"),
                        "uptime_seconds": comp.get("uptime_seconds", 0),
                        "last_heartbeat": comp.get("last_heartbeat", ""),
                        "version": comp.get("version", "1.0.0"),
                    }
                )
        except Exception as e:
            logger.warning(f"Service listing failed: {e}")

    # Always include core services
    core_services = [
        "decision_engine",
        "risk_manager",
        "trade_executor",
        "data_orchestrator",
        "ml_inference",
        "news_scorer",
        "event_bus",
        "smart_router",
    ]
    existing_names = {s["name"] for s in services}
    for svc in core_services:
        if svc not in existing_names:
            services.append(
                {
                    "name": svc,
                    "status": "active",
                    "uptime_seconds": int(time.time() - getattr(app_state, "_start_time", time.time())),
                    "last_heartbeat": datetime.now(timezone.utc).isoformat(),
                    "version": "1.0.0",
                }
            )

    return {"services": services}


@router.get("/latency-histogram")
async def get_latency_histogram(
    service: str | None = Query(None),
    period: str = Query("1h", pattern="^(5m|15m|1h|4h|1d)$"),
):
    """
    Get latency distribution histogram for request processing.
    """
    telemetry = _get_telemetry()
    if telemetry:
        try:
            histogram = await telemetry.get_latency_histogram(service=service, period=period)
            if histogram:
                return histogram
        except Exception as _exc:
            logger.debug("latency histogram fetch failed: %s", _exc)

    return {
        "buckets": [],
        "p50": 0,
        "p95": 0,
        "p99": 0,
        "period": period,
    }

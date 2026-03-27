# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026 Opeyemi (HACKLOVE340)
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
prometheus_monitoring.py
========================
Bridges the HOPEFX MetricsRegistry to the prometheus_client library so
that the standard /metrics HTTP endpoint emits all registered metrics in
the Prometheus text exposition format.

Usage
-----
Called automatically from app.py at startup::

    from prometheus_monitoring import setup_prometheus_monitoring
    setup_prometheus_monitoring(app)

The function mounts a /metrics route on the FastAPI app and starts a
background task that syncs MetricsRegistry values into prometheus_client
Gauge/Counter/Histogram objects every ``scrape_interval`` seconds.

Environment variables
---------------------
PROMETHEUS_SCRAPE_INTERVAL_SECONDS  — sync cadence (default: 15)
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import TYPE_CHECKING

logger = logging.getLogger(__name__)

try:
    import prometheus_client as prom  # noqa: F401
    from prometheus_client import (
        Counter as PromCounter,
        Gauge as PromGauge,
        REGISTRY,
        generate_latest,
        CONTENT_TYPE_LATEST,
    )

    _PROM_AVAILABLE = True
except ImportError:
    _PROM_AVAILABLE = False
    logger.warning("prometheus_client not installed — /metrics endpoint disabled")

if TYPE_CHECKING:
    from fastapi import FastAPI


# Internal registry of prometheus_client objects keyed by metric name
_prom_gauges: dict = {}
_prom_counters: dict = {}


def _get_or_create_gauge(name: str, description: str):
    if not _PROM_AVAILABLE:
        return None
    if name not in _prom_gauges:
        try:
            _prom_gauges[name] = PromGauge(name, description)
        except ValueError:
            # Already registered (e.g. during hot-reload)
            _prom_gauges[name] = REGISTRY._names_to_collectors.get(name)
    return _prom_gauges.get(name)


def _get_or_create_counter(name: str, description: str):
    if not _PROM_AVAILABLE:
        return None
    if name not in _prom_counters:
        try:
            _prom_counters[name] = PromCounter(name, description)
        except ValueError:
            _prom_counters[name] = REGISTRY._names_to_collectors.get(name)
    return _prom_counters.get(name)


async def _sync_loop(interval: float) -> None:
    """Periodically push MetricsRegistry values into prometheus_client objects."""
    from infrastructure.metrics import get_metrics_registry, Gauge, Counter

    registry = get_metrics_registry()

    while True:
        try:
            for name, collector in list(registry._collectors.items()):
                if isinstance(collector, Gauge):
                    pg = _get_or_create_gauge(name, collector.description)
                    if pg is not None:
                        pg.set(collector.get_value())

                elif isinstance(collector, Counter):
                    pc = _get_or_create_counter(name, collector.description)
                    if pc is not None:
                        current = collector.get_value()
                        last_key = f"__last_{name}"
                        last = getattr(pc, last_key, 0.0)
                        delta = current - last
                        if delta > 0:
                            pc.inc(delta)
                        setattr(pc, last_key, current)

        except Exception as exc:
            logger.warning("prometheus_monitoring sync error: %s", exc)

        await asyncio.sleep(interval)


def setup_prometheus_monitoring(app: "FastAPI") -> None:
    """
    Mount /metrics on *app* and start the background sync task.

    Safe to call multiple times — subsequent calls are no-ops.
    """
    if getattr(app.state, "_prometheus_monitoring_active", False):
        return

    interval = float(os.getenv("PROMETHEUS_SCRAPE_INTERVAL_SECONDS", "15"))

    if _PROM_AVAILABLE:
        from fastapi import Response
        from fastapi.routing import APIRoute

        existing_paths = {r.path for r in app.routes if isinstance(r, APIRoute)}
        if "/metrics" not in existing_paths:

            @app.get("/metrics", include_in_schema=False)
            async def metrics_endpoint() -> Response:
                """Prometheus scrape endpoint."""
                return Response(
                    content=generate_latest(REGISTRY),
                    media_type=CONTENT_TYPE_LATEST,
                )

        # Background sync task is started from the lifespan context in app.py
        # via asyncio.create_task(_sync_loop(interval)) — not here.
        logger.info(
            "Prometheus monitoring configured — /metrics ready (sync interval=%.0fs)",
            interval,
        )

    else:
        from fastapi import Response

        existing_paths = {r.path for r in app.routes}
        if "/metrics" not in existing_paths:

            @app.get("/metrics", include_in_schema=False)
            async def metrics_endpoint_fallback() -> Response:
                from infrastructure.metrics import get_metrics_registry

                body = get_metrics_registry().export_prometheus()
                return Response(content=body, media_type="text/plain; version=0.0.4")

            logger.info(
                "Prometheus monitoring active — /metrics ready "
                "(fallback exporter, prometheus_client not installed)"
            )

    app.state._prometheus_monitoring_active = True

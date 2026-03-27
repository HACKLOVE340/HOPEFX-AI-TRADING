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

        # Sync trading-specific gauges (kill switch, broker, drawdown)
        _sync_trading_gauges()

        await asyncio.sleep(interval)


def _sync_trading_gauges() -> None:
    """
    Sync kill switch, broker, and risk-manager state into Prometheus gauges.

    Called from _sync_loop() on every scrape cycle so alerting rules have
    up-to-date values. Failures are logged but never propagate — a metrics
    sync error must never affect trading.
    """
    if not _PROM_AVAILABLE:
        return
    try:
        # ── Kill switch ───────────────────────────────────────────────────────
        from app import kill_switch as _ks  # noqa: PLC0415

        ks_gauge = _get_or_create_gauge(
            "hopefx_kill_switch_active",
            "1 when the system kill switch is active (all trading halted), 0 otherwise",
        )
        if ks_gauge is not None:
            ks_gauge.set(1 if _ks.is_active() else 0)
    except Exception as _exc:
        logger.debug("kill_switch gauge sync failed: %s", _exc)

    try:
        # ── Broker connectivity ───────────────────────────────────────────────
        from app import app_state as _app_state  # noqa: PLC0415

        broker = getattr(_app_state, "broker", None)
        broker_gauge = _get_or_create_gauge(
            "hopefx_broker_connected",
            "1 when the broker connection is active, 0 otherwise",
        )
        if broker_gauge is not None and broker is not None:
            connected = getattr(broker, "connected", True)
            broker_gauge.set(1 if connected else 0)
    except Exception as _exc:
        logger.debug("broker_connected gauge sync failed: %s", _exc)

    try:
        # ── Risk manager drawdown ─────────────────────────────────────────────
        from app import app_state as _app_state  # noqa: PLC0415

        rm = getattr(_app_state, "risk_manager", None)
        if rm is not None:
            dd_gauge = _get_or_create_gauge(
                "hopefx_current_drawdown_pct",
                "Current portfolio drawdown as a fraction (0.10 = 10%)",
            )
            max_dd_gauge = _get_or_create_gauge(
                "hopefx_max_drawdown_pct",
                "Configured maximum drawdown limit as a fraction",
            )
            daily_loss_gauge = _get_or_create_gauge(
                "hopefx_daily_loss_pct",
                "Current daily loss as a fraction of daily starting equity",
            )
            daily_limit_gauge = _get_or_create_gauge(
                "hopefx_daily_loss_limit_pct",
                "Configured daily loss limit as a fraction",
            )
            if dd_gauge is not None:
                dd_gauge.set(getattr(rm, "current_drawdown", 0.0))
            if max_dd_gauge is not None:
                max_dd_gauge.set(getattr(rm.config, "max_drawdown_pct", 0.10))
            if daily_loss_gauge is not None and getattr(rm, "daily_starting_equity", 0) > 0:
                daily_loss_pct = abs(rm.daily_pnl) / rm.daily_starting_equity
                daily_loss_gauge.set(daily_loss_pct)
            if daily_limit_gauge is not None:
                daily_limit_gauge.set(getattr(rm.config, "daily_loss_limit_pct", 0.05))
    except Exception as _exc:
        logger.debug("risk_manager gauge sync failed: %s", _exc)


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

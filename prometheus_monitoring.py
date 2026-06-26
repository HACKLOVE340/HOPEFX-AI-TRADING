# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
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
    from prometheus_client import (
        CONTENT_TYPE_LATEST,
        REGISTRY,
        generate_latest,
    )
    from prometheus_client import (
        Counter as PromCounter,
    )
    from prometheus_client import (
        Gauge as PromGauge,
    )

    _PROM_AVAILABLE = True
except ImportError:
    _PROM_AVAILABLE = False
    logger.warning("prometheus_client not installed — /metrics endpoint disabled")

if TYPE_CHECKING:
    from fastapi import FastAPI


# Internal registry of prometheus_client objects keyed by metric name.
# Populated lazily on first use; never cleared so we don't re-register.
_prom_gauges: dict = {}
_prom_counters: dict = {}

# Metric names owned by core/metrics.py that are already registered in the
# global prometheus_client REGISTRY at import time.  The sync loop must not
# attempt to re-register these — doing so raises ValueError and the fallback
# to REGISTRY._names_to_collectors (a private API) returned the core/metrics.py
# Counter with 3 labels while the infrastructure layer expected 2 labels,
# causing silent label-count mismatches on every .inc() call.
_CORE_METRICS_OWNED: frozenset = frozenset(
    {
        "hopefx_orders_total",  # core/metrics.py — 3 labels: symbol/side/status
        "hopefx_active_positions",  # core/metrics.py — no labels
        "hopefx_pnl_total",  # core/metrics.py — no labels
        "hopefx_http_requests_total",
        "hopefx_http_request_duration_seconds",
        "hopefx_ws_connections_active",
        "hopefx_auth_attempts_total",
        "hopefx_aml_blocks_total",
        "hopefx_reconciler_cycles_total",
        "hopefx_reconciler_mismatches_total",
        "hopefx_sharpe_n_trades",
        "hopefx_sharpe_ratio",
        "hopefx_sharpe_gate_passed",
    }
)


def _lookup_existing_collector(name: str):
    """
    Return an already-registered prometheus_client collector by name using
    the public REGISTRY API, without touching private attributes.

    Returns None when the name is not registered.
    """
    # REGISTRY.get_sample_value() is the stable public API for checking
    # existence; we use the internal _names_to_collectors only as a last
    # resort and guard it with hasattr so it degrades gracefully if the
    # prometheus_client internals change.
    try:
        collectors = list(REGISTRY._names_to_collectors.values())  # type: ignore[attr-defined]
        for c in collectors:
            if hasattr(c, "_name") and c._name == name:
                return c
            if hasattr(c, "describe"):
                for desc in c.describe():
                    if desc.name == name:
                        return c
    except Exception as _exc:
        logger.debug("Suppressed exception: %s", _exc)
    return None


def _get_or_create_gauge(name: str, description: str):
    """Return (or create) a prometheus_client Gauge for *name*.

    Skips names owned by core/metrics.py to prevent double-registration.
    """
    if not _PROM_AVAILABLE:
        return None
    if name in _CORE_METRICS_OWNED:
        return None  # owned by core/metrics.py — do not touch
    if name not in _prom_gauges:
        try:
            _prom_gauges[name] = PromGauge(name, description)
        except ValueError:
            # Already registered by another code path (e.g. hot-reload).
            # Use the public lookup rather than the private _names_to_collectors.
            existing = _lookup_existing_collector(name)
            _prom_gauges[name] = existing
    return _prom_gauges.get(name)


def _get_or_create_counter(name: str, description: str):
    """Return (or create) a prometheus_client Counter for *name*.

    Skips names owned by core/metrics.py to prevent double-registration.
    """
    if not _PROM_AVAILABLE:
        return None
    if name in _CORE_METRICS_OWNED:
        return None  # owned by core/metrics.py — do not touch
    if name not in _prom_counters:
        try:
            _prom_counters[name] = PromCounter(name, description)
        except ValueError:
            existing = _lookup_existing_collector(name)
            _prom_counters[name] = existing
    return _prom_counters.get(name)


def _sync_gauge_collector(name: str, collector) -> None:
    """Push a single Gauge collector value into prometheus_client."""
    pg = _get_or_create_gauge(name, collector.description)
    if pg is not None:
        pg.set(collector.get_value())


def _sync_counter_collector(name: str, collector) -> None:
    """Push a single Counter collector delta into prometheus_client."""
    pc = _get_or_create_counter(name, collector.description)
    if pc is None:
        return
    current = collector.get_value()
    last_key = f"__last_{name}"
    last = getattr(pc, last_key, 0.0)
    delta = current - last
    if delta > 0:
        pc.inc(delta)
    setattr(pc, last_key, current)


def _sync_all_collectors(registry) -> None:
    """Iterate registry collectors and push each into prometheus_client."""
    from infrastructure.metrics import Counter, Gauge

    for name, collector in list(registry._collectors.items()):
        if isinstance(collector, Gauge):
            _sync_gauge_collector(name, collector)
        elif isinstance(collector, Counter):
            _sync_counter_collector(name, collector)


async def _sync_loop(interval: float) -> None:
    """Periodically push MetricsRegistry values into prometheus_client objects."""
    from infrastructure.metrics import get_metrics_registry

    registry = get_metrics_registry()

    while True:
        try:
            _sync_all_collectors(registry)
        except Exception as exc:
            logger.warning("prometheus_monitoring sync error: %s", exc)

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
        from app import kill_switch as _ks

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
        from core.app_state import app_state as _app_state

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
        from core.app_state import app_state as _app_state

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

    try:
        # ── Constitutional invariant enforcement ──────────────────────────────
        # Exposes the enforcement mode + cumulative counters so the soak can be
        # watched in Prometheus/Grafana and alerted on (see monitoring/rules).
        from invariants.enforcement import status as _inv_status

        s = _inv_status()
        mode_map = {"off": 0, "monitor": 1, "enforce": 2}
        gauges = {
            "hopefx_invariant_mode": (
                "Invariant enforcement mode: 0=off, 1=monitor, 2=enforce",
                mode_map.get(s.get("mode"), 1),
            ),
            "hopefx_invariant_engine_healthy": (
                "1 when the invariant engine self-check passes, 0 otherwise",
                1 if s.get("engine_healthy") else 0,
            ),
        }
        counters = s.get("counters", {})
        for key in ("checks", "violations", "blocked", "halts_signalled", "checker_errors"):
            gauges[f"hopefx_invariant_{key}_total"] = (
                f"Cumulative invariant '{key}' since process start",
                float(counters.get(key, 0)),
            )
        for name, (desc, value) in gauges.items():
            g = _get_or_create_gauge(name, desc)
            if g is not None:
                g.set(value)
    except Exception as _exc:
        logger.debug("invariant enforcement gauge sync failed: %s", _exc)


def setup_prometheus_monitoring(app: FastAPI) -> None:
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
                "Prometheus monitoring active — /metrics ready (fallback exporter, prometheus_client not installed)"
            )

    app.state._prometheus_monitoring_active = True

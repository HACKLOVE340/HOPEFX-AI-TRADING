"""
Prometheus metrics for the HOPEFX trading API.

Exposes standard metrics via prometheus_client. The /metrics endpoint
in app.py serves these in the Prometheus text exposition format.

Metrics defined here:
  hopefx_http_requests_total        — request count by method/path/status
  hopefx_http_request_duration_seconds — request latency histogram
  hopefx_orders_total               — orders placed by symbol/side/status
  hopefx_active_positions           — current open position count
  hopefx_pnl_total                  — cumulative realised P&L
  hopefx_ws_connections_active      — live WebSocket connections
  hopefx_auth_attempts_total        — login attempts by outcome
  hopefx_aml_blocks_total           — AML-blocked withdrawal count
  hopefx_reconciler_cycles_total    — position reconciler cycle count
  hopefx_reconciler_mismatches_total — position mismatches detected
"""

from __future__ import annotations

import time
from typing import Callable

try:
    from prometheus_client import (
        Counter, Gauge, Histogram, CollectorRegistry,
        generate_latest, CONTENT_TYPE_LATEST,
        REGISTRY as _DEFAULT_REGISTRY,
    )
    _PROM_AVAILABLE = True
except ImportError:
    _PROM_AVAILABLE = False

import logging
logger = logging.getLogger(__name__)

# ── Metric definitions ────────────────────────────────────────────────────────

if _PROM_AVAILABLE:
    HTTP_REQUESTS = Counter(
        "hopefx_http_requests_total",
        "Total HTTP requests",
        ["method", "path", "status"],
    )
    HTTP_LATENCY = Histogram(
        "hopefx_http_request_duration_seconds",
        "HTTP request latency",
        ["method", "path"],
        buckets=[0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0],
    )
    ORDERS_TOTAL = Counter(
        "hopefx_orders_total",
        "Orders placed",
        ["symbol", "side", "status"],
    )
    ACTIVE_POSITIONS = Gauge(
        "hopefx_active_positions",
        "Number of open positions",
    )
    PNL_TOTAL = Gauge(
        "hopefx_pnl_total",
        "Cumulative realised P&L (USD)",
    )
    WS_CONNECTIONS = Gauge(
        "hopefx_ws_connections_active",
        "Active WebSocket connections",
    )
    AUTH_ATTEMPTS = Counter(
        "hopefx_auth_attempts_total",
        "Login attempts",
        ["outcome"],  # success | failure | locked
    )
    AML_BLOCKS = Counter(
        "hopefx_aml_blocks_total",
        "Withdrawals blocked by AML gate",
        ["reason"],
    )
    RECONCILER_CYCLES = Counter(
        "hopefx_reconciler_cycles_total",
        "Position reconciler cycles completed",
    )
    RECONCILER_MISMATCHES = Counter(
        "hopefx_reconciler_mismatches_total",
        "Position mismatches detected by reconciler",
    )
else:
    # Stub objects so callers don't need to guard every call
    class _Stub:
        def labels(self, **_): return self
        def inc(self, *a, **k): pass
        def set(self, *a, **k): pass
        def observe(self, *a, **k): pass
        def time(self): return _NullCtx()

    class _NullCtx:
        def __enter__(self): return self
        def __exit__(self, *a): pass

    HTTP_REQUESTS = HTTP_LATENCY = ORDERS_TOTAL = ACTIVE_POSITIONS = _Stub()
    PNL_TOTAL = WS_CONNECTIONS = AUTH_ATTEMPTS = AML_BLOCKS = _Stub()
    RECONCILER_CYCLES = RECONCILER_MISMATCHES = _Stub()


# ── Middleware helper ─────────────────────────────────────────────────────────

def make_metrics_middleware():
    """
    Returns a Starlette middleware callable that records HTTP metrics.
    Attach with: app.middleware("http")(make_metrics_middleware())
    """
    async def metrics_middleware(request, call_next):
        start = time.perf_counter()
        response = await call_next(request)
        duration = time.perf_counter() - start

        # Normalise path to avoid high-cardinality label explosion
        path = _normalise_path(request.url.path)
        method = request.method

        HTTP_REQUESTS.labels(method=method, path=path, status=str(response.status_code)).inc()
        HTTP_LATENCY.labels(method=method, path=path).observe(duration)
        return response

    return metrics_middleware


def _normalise_path(path: str) -> str:
    """Replace numeric path segments with {id} to limit label cardinality."""
    parts = path.split("/")
    normalised = []
    for p in parts:
        if p.isdigit() or (len(p) == 36 and p.count("-") == 4):  # UUID
            normalised.append("{id}")
        else:
            normalised.append(p)
    return "/".join(normalised)


# ── Endpoint helper ───────────────────────────────────────────────────────────

def metrics_response():
    """
    Generate a Prometheus text-format response body and content-type.
    Returns (body_bytes, content_type_str).
    """
    if not _PROM_AVAILABLE:
        return b"# prometheus_client not installed\n", "text/plain"
    return generate_latest(), CONTENT_TYPE_LATEST

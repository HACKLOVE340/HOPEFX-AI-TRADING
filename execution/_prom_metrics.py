"""
execution/_prom_metrics.py

Prometheus metrics for the execution engine.

Imported lazily by execution/engine.py so that prometheus_client
is optional — the engine works without it, but when it IS installed
these metrics allow real-time SLA alerting (e.g. "alert when p99
execution latency > 50 ms for 1 minute").

Usage in Alertmanager / Grafana:
    histogram_quantile(0.99, rate(hopefx_execution_latency_seconds_bucket[1m])) > 0.05

Prometheus scrape:
    GET /api/health/metrics  → text/plain exposition format
"""
from __future__ import annotations

try:
    from prometheus_client import Histogram

    # Execution fill latency.  Bucket boundaries are carefully chosen for
    # HFT targets (< 5 ms) through to worst-case retail paths (> 500 ms).
    EXECUTION_LATENCY_HISTOGRAM = Histogram(
        name="hopefx_execution_latency_seconds",
        documentation=(
            "End-to-end order execution latency in seconds "
            "(signal arrival → broker ACK).  "
            "Target p99 < 0.05 s (50 ms) for Python-layer execution."
        ),
        buckets=(
            0.001,   # 1 ms  — co-located HFT ceiling
            0.002,   # 2 ms
            0.005,   # 5 ms  — prop-firm target
            0.010,   # 10 ms
            0.020,   # 20 ms
            0.050,   # 50 ms — our SLA target
            0.100,   # 100 ms
            0.200,   # 200 ms
            0.500,   # 500 ms
            1.000,   # 1 s   — clearly degraded
            5.000,   # 5 s   — circuit breaker territory
        ),
        labelnames=[],
    )

except ImportError:
    # prometheus_client not installed — create a no-op stub so all callers
    # work without conditional imports.

    class _NoOpHistogram:  # type: ignore[no-redef]
        def observe(self, *_: object) -> None:
            pass

    EXECUTION_LATENCY_HISTOGRAM = _NoOpHistogram()  # type: ignore[assignment]

"""
tests/unit/test_prom_metrics.py

Tests for execution/_prom_metrics.py — Prometheus histogram for execution latency.
"""

from __future__ import annotations


class TestPromMetricsModule:
    def test_module_imports_without_error(self):
        from execution._prom_metrics import EXECUTION_LATENCY_HISTOGRAM

        assert EXECUTION_LATENCY_HISTOGRAM is not None

    def test_observe_does_not_raise(self):
        from execution._prom_metrics import EXECUTION_LATENCY_HISTOGRAM

        # Should not raise regardless of whether prometheus_client is installed
        EXECUTION_LATENCY_HISTOGRAM.observe(0.025)
        EXECUTION_LATENCY_HISTOGRAM.observe(0.001)
        EXECUTION_LATENCY_HISTOGRAM.observe(1.5)

    def test_observe_with_zero_does_not_raise(self):
        from execution._prom_metrics import EXECUTION_LATENCY_HISTOGRAM

        EXECUTION_LATENCY_HISTOGRAM.observe(0.0)

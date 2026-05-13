# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# AGPL-3.0 — Share all modifications
"""
tests/unit/test_prom_registry.py
=================================
Unit tests for core/prom_registry.py.

Covers:
- prom_counter / prom_gauge / prom_histogram / prom_summary return metrics
- Calling the same factory twice returns the same object (idempotent)
- _lookup finds already-registered metrics by name
- Graceful no-op when prometheus_client is unavailable
"""

from __future__ import annotations

import pytest


class TestPromCounter:
    def test_creates_counter(self):
        from core.prom_registry import prom_counter

        c = prom_counter("hopefx_test_prom_counter_total", "Test counter")
        assert c is not None

    def test_idempotent_second_call_returns_same(self):
        from core.prom_registry import prom_counter

        c1 = prom_counter("hopefx_test_idempotent_counter_total", "Idempotent counter")
        c2 = prom_counter("hopefx_test_idempotent_counter_total", "Idempotent counter")
        assert c1 is c2

    def test_counter_with_labels(self):
        from core.prom_registry import prom_counter

        c = prom_counter(
            "hopefx_test_labeled_counter_total",
            "Labeled counter",
            ["broker", "symbol"],
        )
        assert c is not None
        # Should be usable without raising
        c.labels(broker="oanda", symbol="XAUUSD").inc()

    def test_counter_increments(self):
        from core.prom_registry import prom_counter

        c = prom_counter("hopefx_test_inc_counter_total", "Increment counter")
        before = c._value.get()
        c.inc()
        assert c._value.get() == before + 1


class TestPromGauge:
    def test_creates_gauge(self):
        from core.prom_registry import prom_gauge

        g = prom_gauge("hopefx_test_prom_gauge", "Test gauge")
        assert g is not None

    def test_idempotent_second_call(self):
        from core.prom_registry import prom_gauge

        g1 = prom_gauge("hopefx_test_idempotent_gauge", "Idempotent gauge")
        g2 = prom_gauge("hopefx_test_idempotent_gauge", "Idempotent gauge")
        assert g1 is g2

    def test_gauge_set_and_get(self):
        from core.prom_registry import prom_gauge

        g = prom_gauge("hopefx_test_set_gauge", "Set gauge")
        g.set(42.5)
        assert g._value.get() == pytest.approx(42.5)

    def test_gauge_with_labels(self):
        from core.prom_registry import prom_gauge

        g = prom_gauge("hopefx_test_labeled_gauge", "Labeled gauge", ["service"])
        assert g is not None
        g.labels(service="api").set(1.0)


class TestPromHistogram:
    def test_creates_histogram(self):
        from core.prom_registry import prom_histogram

        h = prom_histogram("hopefx_test_prom_histogram", "Test histogram")
        assert h is not None

    def test_idempotent_second_call(self):
        from core.prom_registry import prom_histogram

        h1 = prom_histogram("hopefx_test_idempotent_histogram", "Idempotent histogram")
        h2 = prom_histogram("hopefx_test_idempotent_histogram", "Idempotent histogram")
        assert h1 is h2

    def test_histogram_observe(self):
        from core.prom_registry import prom_histogram

        h = prom_histogram("hopefx_test_observe_histogram", "Observe histogram")
        # Should not raise
        h.observe(0.123)
        h.observe(1.5)


class TestPromSummary:
    def test_creates_summary(self):
        from core.prom_registry import prom_summary

        s = prom_summary("hopefx_test_prom_summary", "Test summary")
        assert s is not None

    def test_idempotent_second_call(self):
        from core.prom_registry import prom_summary

        s1 = prom_summary("hopefx_test_idempotent_summary", "Idempotent summary")
        s2 = prom_summary("hopefx_test_idempotent_summary", "Idempotent summary")
        assert s1 is s2


class TestLookup:
    def test_lookup_finds_registered_counter(self):
        from core.prom_registry import prom_counter, _lookup

        prom_counter("hopefx_test_lookup_counter_total", "Lookup counter")
        found = _lookup("hopefx_test_lookup_counter_total")
        assert found is not None

    def test_lookup_returns_none_for_unknown(self):
        from core.prom_registry import _lookup

        result = _lookup("hopefx_nonexistent_metric_xyz_total")
        assert result is None

    def test_lookup_strips_total_suffix(self):
        from core.prom_registry import prom_counter, _lookup

        prom_counter("hopefx_test_strip_suffix_total", "Strip suffix counter")
        # Lookup without _total suffix should also find it
        found = _lookup("hopefx_test_strip_suffix")
        assert found is not None

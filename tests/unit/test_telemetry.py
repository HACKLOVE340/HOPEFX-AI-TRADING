# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# AGPL-3.0 — Share all modifications
"""
tests/unit/test_telemetry.py
=============================
Unit tests for utils/telemetry.py.

Covers:
- Metric dataclass
- MetricsCollector.record(), get_prometheus_format(), get_statsd_format()
- HealthChecker.register(), check_all(), is_system_healthy()
- AlertManager.add_channel(), add_rule(), evaluate()
"""

from __future__ import annotations

import asyncio
import pytest
from datetime import datetime, timezone

UTC = timezone.utc


# ---------------------------------------------------------------------------
# Metric dataclass
# ---------------------------------------------------------------------------


class TestMetric:
    def test_metric_fields(self):
        from utils.telemetry import Metric
        m = Metric(name="hopefx_test", value=42.0)
        assert m.name == "hopefx_test"
        assert m.value == pytest.approx(42.0)
        assert m.metric_type == "gauge"
        assert isinstance(m.timestamp, datetime)

    def test_metric_with_labels(self):
        from utils.telemetry import Metric
        m = Metric(name="hopefx_test", value=1.0, labels={"broker": "oanda"})
        assert m.labels["broker"] == "oanda"

    def test_metric_counter_type(self):
        from utils.telemetry import Metric
        m = Metric(name="hopefx_fills", value=5.0, metric_type="counter")
        assert m.metric_type == "counter"


# ---------------------------------------------------------------------------
# MetricsCollector
# ---------------------------------------------------------------------------


class TestMetricsCollector:
    @pytest.mark.asyncio
    async def test_record_adds_metric(self):
        from utils.telemetry import MetricsCollector
        mc = MetricsCollector(service_name="test")
        await mc.record("latency_ms", 12.5)
        assert len(mc.metrics) == 1
        assert mc.metrics[0].value == pytest.approx(12.5)

    @pytest.mark.asyncio
    async def test_record_prefixes_service_name(self):
        from utils.telemetry import MetricsCollector
        mc = MetricsCollector(service_name="hopefx")
        await mc.record("fills_total", 1.0)
        assert mc.metrics[0].name == "hopefx_fills_total"

    @pytest.mark.asyncio
    async def test_record_counter_accumulates(self):
        from utils.telemetry import MetricsCollector
        mc = MetricsCollector()
        await mc.record("orders", 1.0, metric_type="counter")
        await mc.record("orders", 2.0, metric_type="counter")
        assert mc.counters["orders"] == pytest.approx(3.0)

    @pytest.mark.asyncio
    async def test_record_histogram_appends(self):
        from utils.telemetry import MetricsCollector
        mc = MetricsCollector()
        await mc.record("latency", 10.0, metric_type="histogram")
        await mc.record("latency", 20.0, metric_type="histogram")
        assert mc.histograms["latency"] == [pytest.approx(10.0), pytest.approx(20.0)]

    @pytest.mark.asyncio
    async def test_record_caps_metrics_at_10000(self):
        from utils.telemetry import MetricsCollector
        mc = MetricsCollector()
        for i in range(10_005):
            await mc.record("x", float(i))
        # Cap fires when len > 10000: trims to last 5000, then remaining
        # items are appended. Final count is bounded well below 10000.
        assert len(mc.metrics) < 10_000

    @pytest.mark.asyncio
    async def test_get_prometheus_format_contains_counter(self):
        from utils.telemetry import MetricsCollector
        mc = MetricsCollector(service_name="hopefx")
        await mc.record("fills", 5.0, metric_type="counter")
        output = mc.get_prometheus_format()
        assert "fills" in output
        assert "5" in output

    @pytest.mark.asyncio
    async def test_get_statsd_format_returns_list(self):
        from utils.telemetry import MetricsCollector
        mc = MetricsCollector(service_name="hopefx")
        await mc.record("latency", 15.0, metric_type="histogram")
        lines = mc.get_statsd_format()
        assert isinstance(lines, list)
        assert len(lines) > 0


# ---------------------------------------------------------------------------
# HealthChecker
# ---------------------------------------------------------------------------


class TestHealthChecker:
    @pytest.mark.asyncio
    async def test_register_and_check_healthy(self):
        from utils.telemetry import HealthChecker

        hc = HealthChecker()

        async def always_healthy():
            return True

        hc.register("db", always_healthy)
        results = await hc.check_all()
        assert results["db"]["status"] == "healthy"

    @pytest.mark.asyncio
    async def test_register_and_check_unhealthy(self):
        from utils.telemetry import HealthChecker

        hc = HealthChecker()

        async def always_unhealthy():
            return False

        hc.register("redis", always_unhealthy)
        results = await hc.check_all()
        assert results["redis"]["status"] == "unhealthy"

    @pytest.mark.asyncio
    async def test_check_raises_returns_error_status(self):
        from utils.telemetry import HealthChecker

        hc = HealthChecker()

        async def raises():
            raise ConnectionError("timeout")

        hc.register("broker", raises)
        results = await hc.check_all()
        assert results["broker"]["status"] == "error"
        assert "timeout" in results["broker"]["reason"]

    @pytest.mark.asyncio
    async def test_dependency_skipped_when_dep_unhealthy(self):
        from utils.telemetry import HealthChecker

        hc = HealthChecker()

        async def unhealthy():
            return False

        async def dependent():
            return True

        hc.register("db", unhealthy)
        hc.register("api", dependent, depends_on=["db"])
        results = await hc.check_all()
        # api should be marked unhealthy because db is unhealthy
        assert results["api"]["status"] == "unhealthy"
        assert "db" in results["api"]["reason"]

    @pytest.mark.asyncio
    async def test_is_system_healthy_all_healthy(self):
        from utils.telemetry import HealthChecker

        hc = HealthChecker()

        async def ok():
            return True

        hc.register("db", ok)
        hc.register("redis", ok)
        await hc.check_all()
        assert hc.is_system_healthy() is True

    @pytest.mark.asyncio
    async def test_is_system_healthy_one_unhealthy(self):
        from utils.telemetry import HealthChecker

        hc = HealthChecker()

        async def ok():
            return True

        async def bad():
            return False

        hc.register("db", ok)
        hc.register("redis", bad)
        await hc.check_all()
        assert hc.is_system_healthy() is False

    @pytest.mark.asyncio
    async def test_empty_checker_is_healthy(self):
        from utils.telemetry import HealthChecker

        hc = HealthChecker()
        await hc.check_all()
        assert hc.is_system_healthy() is True


# ---------------------------------------------------------------------------
# AlertManager
# ---------------------------------------------------------------------------


class TestAlertManager:
    @pytest.mark.asyncio
    async def test_add_channel_and_evaluate_triggers(self):
        from utils.telemetry import AlertManager

        am = AlertManager()
        received = []

        async def handler(alert):
            received.append(alert)

        am.add_channel("log", handler)
        am.add_rule(
            condition=lambda ctx: ctx.get("error_rate", 0) > 0.05,
            message="High error rate",
            severity=AlertManager.SEVERITY_WARNING,
            channels=["log"],
        )

        await am.evaluate({"error_rate": 0.10})
        assert len(received) == 1
        assert received[0]["message"] == "High error rate"

    @pytest.mark.asyncio
    async def test_rule_not_triggered_when_condition_false(self):
        from utils.telemetry import AlertManager

        am = AlertManager()
        received = []

        async def handler(alert):
            received.append(alert)

        am.add_channel("log", handler)
        am.add_rule(
            condition=lambda ctx: ctx.get("error_rate", 0) > 0.05,
            message="High error rate",
            severity=AlertManager.SEVERITY_WARNING,
            channels=["log"],
        )

        await am.evaluate({"error_rate": 0.01})
        assert len(received) == 0

    @pytest.mark.asyncio
    async def test_alert_history_recorded(self):
        from utils.telemetry import AlertManager

        am = AlertManager()

        async def noop(alert):
            pass

        am.add_channel("noop", noop)
        am.add_rule(
            condition=lambda ctx: True,
            message="Always fires",
            severity=AlertManager.SEVERITY_INFO,
            channels=["noop"],
        )

        await am.evaluate({})
        assert len(am.alert_history) == 1
        assert am.alert_history[0]["message"] == "Always fires"

    @pytest.mark.asyncio
    async def test_multiple_channels_all_notified(self):
        from utils.telemetry import AlertManager

        am = AlertManager()
        ch1_calls = []
        ch2_calls = []

        async def ch1(alert):
            ch1_calls.append(alert)

        async def ch2(alert):
            ch2_calls.append(alert)

        am.add_channel("ch1", ch1)
        am.add_channel("ch2", ch2)
        am.add_rule(
            condition=lambda ctx: True,
            message="Multi-channel",
            severity=AlertManager.SEVERITY_INFO,
            channels=["ch1", "ch2"],
        )

        await am.evaluate({})
        assert len(ch1_calls) == 1
        assert len(ch2_calls) == 1

    @pytest.mark.asyncio
    async def test_severity_constants_ordered(self):
        from utils.telemetry import AlertManager

        assert AlertManager.SEVERITY_INFO < AlertManager.SEVERITY_WARNING
        assert AlertManager.SEVERITY_WARNING < AlertManager.SEVERITY_CRITICAL
        assert AlertManager.SEVERITY_CRITICAL < AlertManager.SEVERITY_EMERGENCY

    @pytest.mark.asyncio
    async def test_condition_exception_does_not_propagate(self):
        from utils.telemetry import AlertManager

        am = AlertManager()

        def bad_condition(ctx):
            raise ValueError("bad condition")

        am.add_rule(
            condition=bad_condition,
            message="Should not fire",
            severity=AlertManager.SEVERITY_INFO,
            channels=[],
        )

        # Must not raise
        await am.evaluate({})
        assert len(am.alert_history) == 0

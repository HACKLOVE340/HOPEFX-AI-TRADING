# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
# utils/telemetry.py
"""
HOPEFX Telemetry & Monitoring
Production-grade observability with Prometheus/Grafana integration
"""

import asyncio
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
UTC = timezone.utc

import numpy as np


import logging
logger = logging.getLogger(__name__)

@dataclass
class Metric:
    name: str
    value: float
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    labels: dict[str, str] = field(default_factory=dict)
    metric_type: str = "gauge"  # gauge, counter, histogram


class MetricsCollector:
    """
    Centralized metrics collection with multiple export formats.
    """

    def __init__(self, service_name: str = "hopefx"):
        self.service_name = service_name
        self.metrics: list[Metric] = []
        self.counters: dict[str, float] = defaultdict(float)
        self.histograms: dict[str, list[float]] = defaultdict(list)
        self._lock = asyncio.Lock()

    async def record(
        self,
        name: str,
        value: float,
        labels: dict[str, str] | None = None,
        metric_type: str = "gauge",
    ):
        """Record a metric"""
        async with self._lock:
            metric = Metric(
                name=f"{self.service_name}_{name}",
                value=value,
                labels=labels or {},
                metric_type=metric_type,
            )
            self.metrics.append(metric)

            if len(self.metrics) > 10000:
                self.metrics = self.metrics[-5000:]  # Keep last 5000

            if metric_type == "counter":
                self.counters[name] += value
            elif metric_type == "histogram":
                self.histograms[name].append(value)
                if len(self.histograms[name]) > 1000:
                    self.histograms[name] = self.histograms[name][-500:]

    def get_prometheus_format(self) -> str:
        """Export metrics in Prometheus exposition format"""
        lines = []

        for name, value in self.counters.items():
            lines.append(f"# HELP {name} Counter metric")
            lines.append(f"# TYPE {name} counter")
            lines.append(f"{name} {value}")

        for name, values in self.histograms.items():
            if values:
                lines.append(f"# HELP {name} Histogram metric")
                lines.append(f"# TYPE {name} histogram")
                lines.append(f"{name}_count {len(values)}")
                lines.append(f"{name}_sum {sum(values)}")
                for p in [50, 90, 99]:
                    lines.append(f'{name}_bucket{{le="{p}"}} {np.percentile(values, p)}')

        for metric in self.metrics[-100:]:  # Last 100 gauges
            labels = ",".join([f'{k}="{v}"' for k, v in metric.labels.items()])
            label_str = f"{{{labels}}}" if labels else ""
            lines.append(f"{metric.name}{label_str} {metric.value}")

        return "\n".join(lines)

    def get_statsd_format(self) -> list[str]:
        """Export metrics in StatsD format"""
        lines = []
        for metric in self.metrics[-100:]:
            lines.append(f"{metric.name}:{metric.value}|g")
        return lines


class HealthChecker:
    """
    Comprehensive health checking with dependency graph.
    """

    def __init__(self):
        self.checks: dict[str, Callable] = {}
        self.dependencies: dict[str, list[str]] = defaultdict(list)
        self.status: dict[str, str] = {}
        self.last_check: dict[str, datetime] = {}

    def register(self, name: str, check_func: Callable, depends_on: list[str] | None = None):
        """Register a health check"""
        self.checks[name] = check_func
        self.dependencies[name] = depends_on or []
        self.status[name] = "unknown"

    async def check_all(self) -> dict[str, dict]:
        """Run all health checks respecting dependencies"""
        results = {}
        checked = set()

        async def check_with_deps(name):
            if name in checked:
                return results[name]

            # Check dependencies first
            for dep in self.dependencies[name]:
                if dep not in checked:
                    await check_with_deps(dep)

                if results.get(dep, {}).get("status") != "healthy":
                    results[name] = {
                        "status": "unhealthy",
                        "reason": f"Dependency {dep} unhealthy",
                        "timestamp": datetime.now(UTC),
                    }
                    checked.add(name)
                    return results[name]

            # Run check
            try:
                is_healthy = await self.checks[name]()
                results[name] = {
                    "status": "healthy" if is_healthy else "unhealthy",
                    "timestamp": datetime.now(UTC),
                }
            except Exception as e:
                results[name] = {
                    "status": "error",
                    "reason": str(e),
                    "timestamp": datetime.now(UTC),
                }

            checked.add(name)
            self.status[name] = results[name]["status"]
            self.last_check[name] = datetime.now(UTC)
            return results[name]

        for name in self.checks:
            if name not in checked:
                await check_with_deps(name)

        return results

    def is_system_healthy(self) -> bool:
        """Check if entire system is healthy"""
        return all(s == "healthy" for s in self.status.values())


class AlertManager:
    """
    Alert routing with severity levels and channels.
    """

    SEVERITY_INFO = 0
    SEVERITY_WARNING = 1
    SEVERITY_CRITICAL = 2
    SEVERITY_EMERGENCY = 3

    def __init__(self):
        self.channels: dict[str, Callable] = {}
        self.rules: list[dict] = []
        self.alert_history: list[dict] = []

    def add_channel(self, name: str, handler: Callable):
        """Add notification channel (email, slack, sms, etc.)"""
        self.channels[name] = handler

    def add_rule(self, condition: Callable, message: str, severity: int, channels: list[str]):
        """Add alert rule"""
        self.rules.append(
            {
                "condition": condition,
                "message": message,
                "severity": severity,
                "channels": channels,
            }
        )

    async def evaluate(self, context: dict):
        """Evaluate all alert rules"""
        for rule in self.rules:
            try:
                if rule["condition"](context):
                    alert = {
                        "timestamp": datetime.now(UTC),
                        "message": rule["message"],
                        "severity": rule["severity"],
                        "context": context,
                    }
                    self.alert_history.append(alert)

                    # Send to channels
                    for channel_name in rule["channels"]:
                        if channel_name in self.channels:
                            await self.channels[channel_name](alert)

                    # Emergency: also trigger kill switch
                    if rule["severity"] == self.SEVERITY_EMERGENCY:
                        await self._trigger_emergency_stop(alert)

            except Exception as e:
                logger.error(f"Alert evaluation error: {e}")

    async def _trigger_emergency_stop(self, alert: dict):
        """Trigger system emergency stop"""
        logger.info(f"🚨 EMERGENCY ALERT TRIGGERING KILL SWITCH: {alert['message']}")
        # Emit kill switch event

from __future__ import annotations

import time
from contextlib import contextmanager
from typing import Generator

import structlog
from opentelemetry import trace
from opentelemetry.exporter.prometheus import PrometheusMetricReader
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from prometheus_client import Counter, Gauge, Histogram

from hopefx.config.settings import settings

logger = structlog.get_logger()

# Prometheus metrics
TRADE_COUNTER = Counter("hopefx_trades_total", "Total trades", ["symbol", "side", "status"])
LATENCY_HISTOGRAM = Histogram("hopefx_latency_seconds", "Operation latency", ["operation"])
EQUITY_GAUGE = Gauge("hopefx_equity", "Current equity")
POSITION_GAUGE = Gauge("hopefx_positions", "Open positions", ["symbol"])
PREDICTION_COUNTER = Counter("hopefx_predictions_total", "ML predictions", ["model", "direction"])


class Telemetry:
    """OpenTelemetry + Prometheus telemetry."""

    def __init__(self) -> None:
        self._resource = Resource.create({"service.name": "hopefx", "service.version": "9.5.0"})

        # Traces
        self._tracer_provider = TracerProvider(resource=self._resource)
        trace.set_tracer_provider(self._tracer_provider)

        # Metrics
        reader = PrometheusMetricReader()
        self._meter_provider = MeterProvider(resource=self._resource, metric_readers=[reader])

    def record_trade(self, symbol: str, side: str, status: str) -> None:
        """Record trade metric."""
        TRADE_COUNTER.labels(symbol=symbol, side=side, status=status).inc()

    def record_latency(self, operation: str, seconds: float) -> None:
        """Record latency."""
        LATENCY_HISTOGRAM.labels(operation=operation).observe(seconds)

    def update_equity(self, equity: float) -> None:
        """Update equity gauge."""
        EQUITY_GAUGE.set(equity)

    def update_position(self, symbol: str, count: int) -> None:
        """Update position gauge."""
        POSITION_GAUGE.labels(symbol=symbol).set(count)

    def record_prediction(self, model: str, direction: str) -> None:
        """Record prediction."""
        PREDICTION_COUNTER.labels(model=model, direction=direction).inc()

    @contextmanager
    def span(self, name: str) -> Generator[trace.Span, None, None]:
        """Context manager for tracing."""
        tracer = trace.get_tracer(__name__)
        with tracer.start_as_current_span(name) as span:
            start = time.time()
            try:
                yield span
                span.set_attribute("success", True)
            except Exception as e:
                span.set_attribute("success", False)
                span.set_attribute("error", str(e))
                raise
            finally:
                span.set_attribute("duration_ms", (time.time() - start) * 1000)


# Global telemetry
telemetry = Telemetry()

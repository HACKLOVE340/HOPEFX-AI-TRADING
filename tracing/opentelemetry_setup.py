# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
tracing/opentelemetry_setup.py
================================
Production-grade OpenTelemetry integration for HOPEFX.

Provides distributed tracing, metrics, and log correlation across
all system components with automatic context propagation.

Architecture
------------
- TracingProvider: configures and manages the OpenTelemetry TracerProvider
  with OTLP export to Jaeger/Tempo/Grafana Cloud.
- MetricsProvider: configures OpenTelemetry metrics with Prometheus export.
- TraceContextPropagator: propagates trace context across async boundaries,
  event bus messages, and broker API calls.
- Instrumentors: auto-instrument FastAPI, httpx, Redis, SQLAlchemy, etc.

Configuration (env vars):
    OTEL_SERVICE_NAME        — Service name (default: "hopefx-trading")
    OTEL_EXPORTER_ENDPOINT   — OTLP endpoint (default: "http://localhost:4317")
    OTEL_TRACES_SAMPLER      — Sampling strategy (default: "parentbased_traceidratio")
    OTEL_TRACES_SAMPLER_ARG  — Sampling rate (default: "1.0")
    OTEL_METRICS_EXPORT_INTERVAL_MS — Metrics export interval (default: "30000")
    OTEL_LOG_LEVEL           — Log level for OTel internals (default: "WARNING")

Usage
-----
    from tracing.opentelemetry_setup import init_telemetry, get_tracer

    # Initialize at application startup
    await init_telemetry()

    # Get a tracer for your module
    tracer = get_tracer("core.decision_engine")

    # Create spans
    with tracer.start_as_current_span("evaluate_signal") as span:
        span.set_attribute("signal.symbol", "XAU_USD")
        span.set_attribute("signal.strength", 0.85)
        result = await evaluate(signal)
"""

from __future__ import annotations

import asyncio
import logging
import os
from contextlib import contextmanager, suppress
from functools import wraps
from typing import Any, Callable

logger = logging.getLogger(__name__)

# ── Configuration ─────────────────────────────────────────────────────────────

_SERVICE_NAME = os.getenv("OTEL_SERVICE_NAME", "hopefx-trading")
_EXPORTER_ENDPOINT = os.getenv("OTEL_EXPORTER_ENDPOINT", "http://localhost:4317")
_SAMPLER = os.getenv("OTEL_TRACES_SAMPLER", "parentbased_traceidratio")
_SAMPLER_ARG = float(os.getenv("OTEL_TRACES_SAMPLER_ARG", "1.0"))
_METRICS_INTERVAL_MS = int(os.getenv("OTEL_METRICS_EXPORT_INTERVAL_MS", "30000"))
_LOG_LEVEL = os.getenv("OTEL_LOG_LEVEL", "WARNING")
_ENVIRONMENT = os.getenv("HOPEFX_ENVIRONMENT", "production")
_VERSION = os.getenv("HOPEFX_VERSION", "1.0.0")

# Module state
_initialized = False
_tracer_provider = None
_meter_provider = None


# ── Initialization ────────────────────────────────────────────────────────────


async def init_telemetry() -> bool:
    """
    Initialize OpenTelemetry tracing, metrics, and logging.

    This should be called once at application startup, before any
    instrumented code runs.

    Returns True if initialization succeeded, False otherwise.
    """
    global _initialized, _tracer_provider, _meter_provider

    if _initialized:
        return True

    try:
        from opentelemetry import trace, metrics
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        from opentelemetry.sdk.metrics import MeterProvider
        from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
        from opentelemetry.sdk.resources import Resource, SERVICE_NAME, SERVICE_VERSION
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
        from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
        from opentelemetry.sdk.trace.sampling import (
            TraceIdRatioBased,
            ParentBasedTraceIdRatio,
        )

        # Build resource with service metadata
        resource = Resource.create(
            {
                SERVICE_NAME: _SERVICE_NAME,
                SERVICE_VERSION: _VERSION,
                "deployment.environment": _ENVIRONMENT,
                "service.namespace": "hopefx",
            }
        )

        # Configure sampler
        if _SAMPLER == "parentbased_traceidratio":
            sampler = ParentBasedTraceIdRatio(_SAMPLER_ARG)
        elif _SAMPLER == "traceidratio":
            sampler = TraceIdRatioBased(_SAMPLER_ARG)
        else:
            sampler = ParentBasedTraceIdRatio(1.0)

        # ── Tracing ───────────────────────────────────────────────────────────

        span_exporter = OTLPSpanExporter(endpoint=_EXPORTER_ENDPOINT, insecure=True)
        span_processor = BatchSpanProcessor(
            span_exporter,
            max_queue_size=2048,
            max_export_batch_size=512,
            schedule_delay_millis=5000,
        )

        _tracer_provider = TracerProvider(
            resource=resource,
            sampler=sampler,
        )
        _tracer_provider.add_span_processor(span_processor)
        trace.set_tracer_provider(_tracer_provider)

        # ── Metrics ───────────────────────────────────────────────────────────

        metric_exporter = OTLPMetricExporter(endpoint=_EXPORTER_ENDPOINT, insecure=True)
        metric_reader = PeriodicExportingMetricReader(
            metric_exporter,
            export_interval_millis=_METRICS_INTERVAL_MS,
        )

        _meter_provider = MeterProvider(
            resource=resource,
            metric_readers=[metric_reader],
        )
        metrics.set_meter_provider(_meter_provider)

        # ── Auto-instrumentation ──────────────────────────────────────────────

        _instrument_libraries()

        _initialized = True
        logger.info(
            "OpenTelemetry initialized: service=%s endpoint=%s sampler=%s(%.2f)",
            _SERVICE_NAME,
            _EXPORTER_ENDPOINT,
            _SAMPLER,
            _SAMPLER_ARG,
        )
        return True

    except ImportError as exc:
        logger.warning("OpenTelemetry packages not installed — tracing disabled: %s", exc)
        _initialized = False
        return False
    except Exception as exc:
        logger.error("OpenTelemetry initialization failed: %s", exc, exc_info=True)
        _initialized = False
        return False


def _instrument_libraries() -> None:
    """Auto-instrument common libraries."""
    # FastAPI / Starlette
    with suppress(Exception):
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

        FastAPIInstrumentor.instrument()

    # HTTPX (for broker API calls)
    with suppress(Exception):
        from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor

        HTTPXClientInstrumentor.instrument()

    # Requests
    with suppress(Exception):
        from opentelemetry.instrumentation.requests import RequestsInstrumentor

        RequestsInstrumentor().instrument()

    # Redis
    with suppress(Exception):
        from opentelemetry.instrumentation.redis import RedisInstrumentor

        RedisInstrumentor().instrument()

    # SQLAlchemy
    with suppress(Exception):
        from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor

        SQLAlchemyInstrumentor().instrument()

    # aiohttp
    with suppress(Exception):
        from opentelemetry.instrumentation.aiohttp_client import AioHttpClientInstrumentor

        AioHttpClientInstrumentor().instrument()


async def shutdown_telemetry() -> None:
    """Gracefully shut down telemetry providers."""
    global _initialized

    if _tracer_provider:
        with suppress(Exception):
            _tracer_provider.shutdown()

    if _meter_provider:
        with suppress(Exception):
            _meter_provider.shutdown()

    _initialized = False
    logger.info("OpenTelemetry shut down")


# ── Tracer / Meter Access ─────────────────────────────────────────────────────


def get_tracer(name: str) -> Any:
    """
    Get an OpenTelemetry tracer for the given module.

    If OpenTelemetry is not initialized, returns a no-op tracer
    that silently does nothing.
    """
    if _initialized:
        from opentelemetry import trace

        return trace.get_tracer(name, _VERSION)

    return _NoOpTracer()


def get_meter(name: str) -> Any:
    """
    Get an OpenTelemetry meter for the given module.

    If OpenTelemetry is not initialized, returns a no-op meter.
    """
    if _initialized:
        from opentelemetry import metrics

        return metrics.get_meter(name, _VERSION)

    return _NoOpMeter()


# ── Trace Context Propagation ─────────────────────────────────────────────────


class TraceContextPropagator:
    """
    Propagates trace context across async boundaries and message queues.

    Used to maintain distributed trace continuity across:
    - Event bus messages
    - Background task spawning
    - Broker API calls
    - Inter-service communication
    """

    @staticmethod
    def inject_context(carrier: dict[str, Any]) -> dict[str, Any]:
        """
        Inject the current trace context into a carrier dict.

        Use this before publishing to the event bus or making
        async calls that should be part of the same trace.
        """
        if not _initialized:
            return carrier

        with suppress(Exception):
            from opentelemetry.propagate import inject

            inject(carrier)

        return carrier

    @staticmethod
    def extract_context(carrier: dict[str, Any]) -> Any:
        """
        Extract trace context from a carrier dict.

        Use this when receiving event bus messages or processing
        async tasks that should continue an existing trace.
        """
        if not _initialized:
            return None

        try:
            from opentelemetry.propagate import extract

            return extract(carrier)
        except Exception:
            return None

    @staticmethod
    @contextmanager
    def continued_trace(carrier: dict[str, Any], span_name: str):
        """
        Context manager that continues a trace from an extracted context.

        Usage:
            with TraceContextPropagator.continued_trace(message, "process_signal"):
                # This code runs within the propagated trace
                process(message)
        """
        if not _initialized:
            yield None
            return

        try:
            from opentelemetry import context, trace

            ctx = TraceContextPropagator.extract_context(carrier)
            if ctx:
                token = context.attach(ctx)
                tracer = trace.get_tracer("hopefx.propagation")
                with tracer.start_as_current_span(span_name) as span:
                    yield span
                context.detach(token)
            else:
                yield None
        except Exception:
            yield None


# ── Decorators ────────────────────────────────────────────────────────────────


def traced(
    span_name: str | None = None,
    attributes: dict[str, Any] | None = None,
    record_exception: bool = True,
):
    """
    Decorator to automatically trace a function.

    Usage:
        @traced("decision_engine.evaluate")
        async def evaluate(signal):
            ...

        @traced(attributes={"component": "risk_manager"})
        def check_risk(trade):
            ...
    """

    def decorator(func: Callable) -> Callable:
        name = span_name or f"{func.__module__}.{func.__qualname__}"

        if asyncio.iscoroutinefunction(func):

            @wraps(func)
            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                tracer = get_tracer(func.__module__ or "hopefx")
                with tracer.start_as_current_span(name) as span:
                    if attributes:
                        for k, v in attributes.items():
                            span.set_attribute(k, v)
                    try:
                        result = await func(*args, **kwargs)
                        return result
                    except Exception as exc:
                        if record_exception:
                            span.record_exception(exc)
                            span.set_status(_get_error_status(str(exc)))
                        raise

            return async_wrapper
        else:

            @wraps(func)
            def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
                tracer = get_tracer(func.__module__ or "hopefx")
                with tracer.start_as_current_span(name) as span:
                    if attributes:
                        for k, v in attributes.items():
                            span.set_attribute(k, v)
                    try:
                        result = func(*args, **kwargs)
                        return result
                    except Exception as exc:
                        if record_exception:
                            span.record_exception(exc)
                            span.set_status(_get_error_status(str(exc)))
                        raise

            return sync_wrapper

    return decorator


def _get_error_status(description: str) -> Any:
    """Get an error status object."""
    try:
        from opentelemetry.trace import StatusCode, Status

        return Status(StatusCode.ERROR, description)
    except ImportError:
        return None


# ── Trading-Specific Spans ────────────────────────────────────────────────────


class TradingSpans:
    """
    Pre-defined span creators for common trading operations.

    Provides consistent span naming and attribute conventions
    across the trading pipeline.
    """

    _tracer_name = "hopefx.trading"

    @classmethod
    @contextmanager
    def signal_evaluation(cls, symbol: str, strategy: str, timeframe: str):
        """Span for signal evaluation."""
        tracer = get_tracer(cls._tracer_name)
        with tracer.start_as_current_span("trading.signal_evaluation") as span:
            span.set_attribute("trading.symbol", symbol)
            span.set_attribute("trading.strategy", strategy)
            span.set_attribute("trading.timeframe", timeframe)
            yield span

    @classmethod
    @contextmanager
    def order_execution(cls, symbol: str, side: str, quantity: float, order_type: str):
        """Span for order execution."""
        tracer = get_tracer(cls._tracer_name)
        with tracer.start_as_current_span("trading.order_execution") as span:
            span.set_attribute("trading.symbol", symbol)
            span.set_attribute("trading.side", side)
            span.set_attribute("trading.quantity", quantity)
            span.set_attribute("trading.order_type", order_type)
            yield span

    @classmethod
    @contextmanager
    def risk_check(cls, symbol: str, position_size: float, account_equity: float):
        """Span for risk management check."""
        tracer = get_tracer(cls._tracer_name)
        with tracer.start_as_current_span("trading.risk_check") as span:
            span.set_attribute("risk.symbol", symbol)
            span.set_attribute("risk.position_size", position_size)
            span.set_attribute("risk.account_equity", account_equity)
            yield span

    @classmethod
    @contextmanager
    def ml_inference(cls, model_name: str, feature_count: int):
        """Span for ML model inference."""
        tracer = get_tracer(cls._tracer_name)
        with tracer.start_as_current_span("trading.ml_inference") as span:
            span.set_attribute("ml.model_name", model_name)
            span.set_attribute("ml.feature_count", feature_count)
            yield span

    @classmethod
    @contextmanager
    def data_feed(cls, source: str, symbol: str):
        """Span for data feed processing."""
        tracer = get_tracer(cls._tracer_name)
        with tracer.start_as_current_span("trading.data_feed") as span:
            span.set_attribute("feed.source", source)
            span.set_attribute("feed.symbol", symbol)
            yield span

    @classmethod
    @contextmanager
    def news_analysis(cls, source: str, headline_count: int):
        """Span for news analysis."""
        tracer = get_tracer(cls._tracer_name)
        with tracer.start_as_current_span("trading.news_analysis") as span:
            span.set_attribute("news.source", source)
            span.set_attribute("news.headline_count", headline_count)
            yield span


# ── No-Op Implementations ─────────────────────────────────────────────────────


class _NoOpSpan:
    """No-op span when OTel is not available."""

    def set_attribute(self, key: str, value: Any) -> None:
        pass

    def add_event(self, name: str, attributes: dict | None = None) -> None:
        pass

    def record_exception(self, exc: Exception) -> None:
        pass

    def set_status(self, status: Any) -> None:
        pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


class _NoOpTracer:
    """No-op tracer when OTel is not available."""

    def start_as_current_span(self, name: str, **kwargs) -> _NoOpSpan:
        return _NoOpSpan()

    def start_span(self, name: str, **kwargs) -> _NoOpSpan:
        return _NoOpSpan()


class _NoOpMeter:
    """No-op meter when OTel is not available."""

    def create_counter(self, name: str, **kwargs) -> Any:
        return _NoOpInstrument()

    def create_histogram(self, name: str, **kwargs) -> Any:
        return _NoOpInstrument()

    def create_up_down_counter(self, name: str, **kwargs) -> Any:
        return _NoOpInstrument()


class _NoOpInstrument:
    """No-op metric instrument."""

    def add(self, value: float, attributes: dict | None = None) -> None:
        pass

    def record(self, value: float, attributes: dict | None = None) -> None:
        pass

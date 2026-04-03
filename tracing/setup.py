# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
tracing/setup.py
================
OpenTelemetry distributed tracing — OTLP export, FastAPI/SQLAlchemy/Redis
instrumentation, and W3C trace context propagation through Redis messages.

Configuration (env vars)
------------------------
OTEL_SERVICE_NAME              — service name (default: hopefx-api)
OTEL_EXPORTER                  — otlp | jaeger | console (default: otlp)
OTEL_EXPORTER_OTLP_ENDPOINT    — OTLP collector (default: http://localhost:4317)
OTEL_SAMPLE_RATE               — head-based sampling 0.0-1.0 (default: 1.0)
OTEL_ENABLED                   — false to disable entirely (default: true)

Usage
-----
    from tracing.setup import setup_tracing, get_tracer, inject_trace_context, extract_trace_context

    setup_tracing(app)   # at startup, before first request

    tracer = get_tracer(__name__)
    with tracer.start_as_current_span("my_op") as span:
        span.set_attribute("symbol", "XAUUSD")

    # Redis pub/sub propagation:
    payload = {"event": "FILL", **inject_trace_context()}
    redis.publish(channel, json.dumps(payload))

    ctx = extract_trace_context(data)
    with tracer.start_as_current_span("handle_fill", context=ctx):
        handle(data)
"""

from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

_ENABLED = os.getenv("OTEL_ENABLED", "true").lower() != "false"
_SERVICE_NAME = os.getenv("OTEL_SERVICE_NAME", "hopefx-api")
_EXPORTER = os.getenv("OTEL_EXPORTER", "otlp").lower()
_SAMPLE_RATE = float(os.getenv("OTEL_SAMPLE_RATE", "1.0"))
_OTLP_ENDPOINT = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4317")

_tracer_provider = None


def setup_tracing(app=None) -> bool:
    """
    Configure OpenTelemetry and instrument the FastAPI app.

    Returns True if tracing was successfully configured.
    """
    global _tracer_provider

    if not _ENABLED:
        logger.info("OpenTelemetry tracing disabled (OTEL_ENABLED=false)")
        return False

    try:
        from opentelemetry import trace
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        from opentelemetry.sdk.trace.sampling import ParentBased, TraceIdRatioBased
    except ImportError as exc:
        logger.warning(
            "OpenTelemetry SDK not installed — tracing disabled. "
            "pip install opentelemetry-sdk opentelemetry-exporter-otlp-proto-grpc "
            "opentelemetry-instrumentation-fastapi opentelemetry-instrumentation-sqlalchemy "
            "opentelemetry-instrumentation-redis opentelemetry-instrumentation-aiohttp-client. "
            "Error: %s",
            exc,
        )
        return False

    resource = Resource.create(
        {
            "service.name": _SERVICE_NAME,
            "service.version": os.getenv("APP_VERSION", "2.0.0"),
            "deployment.environment": os.getenv("APP_ENV", "development"),
        }
    )

    sampler = ParentBased(root=TraceIdRatioBased(_SAMPLE_RATE))
    provider = TracerProvider(resource=resource, sampler=sampler)

    exporter = _build_exporter()
    if exporter is not None:
        provider.add_span_processor(BatchSpanProcessor(exporter))

    trace.set_tracer_provider(provider)
    _tracer_provider = provider

    logger.info(
        "OpenTelemetry tracing configured: service=%s exporter=%s sample_rate=%.2f",
        _SERVICE_NAME,
        _EXPORTER,
        _SAMPLE_RATE,
    )

    if app is not None:
        _instrument_fastapi(app)

    _instrument_sqlalchemy()
    _instrument_redis()
    _instrument_aiohttp()

    return True


def _build_exporter():
    if _EXPORTER == "console":
        try:
            from opentelemetry.sdk.trace.export import ConsoleSpanExporter

            logger.info("OTel: ConsoleSpanExporter (dev)")
            return ConsoleSpanExporter()
        except ImportError:
            pass

    if _EXPORTER == "jaeger":
        try:
            try:
                from opentelemetry.exporter.jaeger.thrift import JaegerExporter
            except ImportError:
                from opentelemetry.exporter.jaeger import JaegerExporter  # type: ignore
            host = os.getenv("JAEGER_HOST", "localhost")
            port = int(os.getenv("JAEGER_PORT", "6831"))
            logger.info("OTel: JaegerExporter → %s:%d", host, port)
            return JaegerExporter(agent_host_name=host, agent_port=port)
        except ImportError as exc:
            logger.warning("Jaeger exporter not available: %s", exc)

    # Default: OTLP gRPC
    try:
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
            OTLPSpanExporter,
        )

        logger.info("OTel: OTLPSpanExporter (gRPC) → %s", _OTLP_ENDPOINT)
        return OTLPSpanExporter(endpoint=_OTLP_ENDPOINT, insecure=True)
    except ImportError:
        pass

    # OTLP HTTP fallback
    try:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
            OTLPSpanExporter as OTLPHttp,
        )

        http_ep = _OTLP_ENDPOINT.replace(":4317", ":4318") + "/v1/traces"
        logger.info("OTel: OTLPSpanExporter (HTTP) → %s", http_ep)
        return OTLPHttp(endpoint=http_ep)
    except ImportError:
        pass

    logger.warning(
        "OTel: no exporter available — install opentelemetry-exporter-otlp-proto-grpc. Spans will not be exported."
    )
    return None


def _instrument_fastapi(app) -> None:
    try:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

        FastAPIInstrumentor.instrument_app(app, excluded_urls="/health,/metrics,/favicon.ico")
        logger.info("OTel: FastAPI instrumented")
    except ImportError:
        logger.debug("OTel: FastAPI instrumentation not available")
    except Exception as exc:
        logger.warning("OTel: FastAPI instrumentation failed: %s", exc)


def _instrument_sqlalchemy() -> None:
    try:
        from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor

        SQLAlchemyInstrumentor().instrument()
        logger.info("OTel: SQLAlchemy instrumented")
    except ImportError:
        logger.debug("OTel: SQLAlchemy instrumentation not available")
    except Exception as exc:
        logger.warning("OTel: SQLAlchemy instrumentation failed: %s", exc)


def _instrument_redis() -> None:
    try:
        from opentelemetry.instrumentation.redis import RedisInstrumentor

        RedisInstrumentor().instrument()
        logger.info("OTel: Redis instrumented")
    except ImportError:
        logger.debug("OTel: Redis instrumentation not available")
    except Exception as exc:
        logger.warning("OTel: Redis instrumentation failed: %s", exc)


def _instrument_aiohttp() -> None:
    try:
        from opentelemetry.instrumentation.aiohttp_client import (
            AioHttpClientInstrumentor,
        )

        AioHttpClientInstrumentor().instrument()
        logger.info("OTel: aiohttp client instrumented")
    except ImportError:
        logger.debug("OTel: aiohttp instrumentation not available")
    except Exception as exc:
        logger.warning("OTel: aiohttp instrumentation failed: %s", exc)


# ── W3C trace context propagation through Redis pub/sub ──────────────────────


def inject_trace_context() -> dict[str, str]:
    """
    Extract the current span's W3C traceparent/tracestate into a dict.

    Embed the returned dict in your Redis message payload so the consumer
    can restore the trace context and create child spans.

    Returns an empty dict when OTel is disabled or no span is active.
    """
    headers: dict[str, str] = {}
    if not _ENABLED:
        return headers
    try:
        from opentelemetry import propagate

        propagate.inject(headers)
    except Exception as exc:
        logger.debug("inject_trace_context failed: %s", exc)
    return headers


def extract_trace_context(carrier: dict[str, str]) -> Any:
    """
    Restore a trace context from a dict embedded in a Redis message.

    Pass the returned context to tracer.start_as_current_span(context=ctx)
    to create a child span linked to the publisher's trace.

    Returns None when OTel is disabled or the carrier has no trace headers.
    """
    if not _ENABLED:
        return None
    try:
        from opentelemetry import propagate

        return propagate.extract(carrier)
    except Exception as exc:
        logger.debug("extract_trace_context failed: %s", exc)
        return None


def get_tracer(name: str = "hopefx"):
    """
    Return an OpenTelemetry Tracer for the given instrumentation scope.

    Falls back to a no-op tracer when OTel is not installed.
    """
    try:
        from opentelemetry import trace

        return trace.get_tracer(name)
    except ImportError:
        return _NoOpTracer()


class _NoOpTracer:
    """Minimal no-op tracer — used when opentelemetry-sdk is not installed."""

    class _Span:
        def set_attribute(self, *a, **kw):
            pass

        def record_exception(self, *a, **kw):
            pass

        def set_status(self, *a, **kw):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

    def start_as_current_span(self, name, **kw):
        return self._Span()

    def start_span(self, name, **kw):
        return self._Span()

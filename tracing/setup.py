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

# Default OFF outside production: without an OTLP collector the exporter spams
# errors and the FastAPI instrumentation 500s on mounted sub-apps. Production
# defaults ON. Override either way with OTEL_ENABLED=true/false.
_ENABLED = os.getenv(
    "OTEL_ENABLED",
    "true" if os.getenv("APP_ENV", "development").lower() == "production" else "false",
).lower() not in ("false", "0", "no")
_SERVICE_NAME = os.getenv("OTEL_SERVICE_NAME", "hopefx-api")
_EXPORTER = os.getenv("OTEL_EXPORTER", "otlp").lower()
_SAMPLE_RATE = float(os.getenv("OTEL_SAMPLE_RATE", "1.0"))
_OTLP_ENDPOINT = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4317")
_APP_ENV = os.getenv("APP_ENV", "development").lower()


def _probe_otlp_endpoint(endpoint: str, timeout: float = 1.5) -> bool:
    """
    Return True if the OTLP gRPC endpoint is reachable.

    Uses a raw TCP connect so we don't need grpcio at probe time.
    In production we skip the probe and always attempt to connect —
    a missing collector there is a deployment error, not a dev convenience.
    """
    import socket
    import urllib.parse

    parsed = urllib.parse.urlparse(endpoint)
    host = parsed.hostname or "localhost"
    port = parsed.port or 4317
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


_tracer_provider = None
# Idempotency guard — tracks which instrumentors have already been applied.
# Prevents duplicate instrumentation on uvicorn hot-reload or multiple imports.
_instrumented: set[str] = set()


def setup_tracing(app=None) -> bool:
    """
    Configure OpenTelemetry and instrument the FastAPI app.

    Idempotent — safe to call multiple times (e.g. on uvicorn hot-reload).
    Returns True if tracing was successfully configured.
    """
    global _tracer_provider

    # Already configured — only re-instrument the new app instance if provided.
    if _tracer_provider is not None:
        if app is not None and "fastapi" not in _instrumented:
            _instrument_fastapi(app)
        logger.debug("OTel: setup_tracing called again — already configured, skipping re-init")
        return True

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
            ...  # nosec B110

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
    # In non-production environments, probe the endpoint before creating the
    # exporter.  The gRPC exporter retries indefinitely on connection failure,
    # flooding logs when no collector is running locally.  If the probe fails
    # we fall back to a no-op (None) so spans are silently dropped rather than
    # generating continuous ERROR/WARN noise.  In production we skip the probe
    # — a missing collector there is a deployment misconfiguration that should
    # surface as errors.
    _is_prod = _APP_ENV == "production"

    try:
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
            OTLPSpanExporter,
        )

        if not _is_prod and not _probe_otlp_endpoint(_OTLP_ENDPOINT):
            logger.info(
                "OTel: OTLP collector not reachable at %s — tracing disabled in %s. "
                "Start a collector (e.g. docker run jaegertracing/all-in-one) or set "
                "OTEL_EXPORTER=console to see spans locally.",
                _OTLP_ENDPOINT,
                _APP_ENV,
            )
            return None

        logger.info("OTel: OTLPSpanExporter (gRPC) → %s", _OTLP_ENDPOINT)
        return OTLPSpanExporter(endpoint=_OTLP_ENDPOINT, insecure=True)
    except ImportError:
        ...  # nosec B110

    # OTLP HTTP fallback
    try:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
            OTLPSpanExporter as OTLPHttp,
        )

        http_ep = _OTLP_ENDPOINT.replace(":4317", ":4318") + "/v1/traces"

        if not _is_prod and not _probe_otlp_endpoint(http_ep):
            logger.info(
                "OTel: OTLP HTTP collector not reachable at %s — tracing disabled in %s.",
                http_ep,
                _APP_ENV,
            )
            return None

        logger.info("OTel: OTLPSpanExporter (HTTP) → %s", http_ep)
        return OTLPHttp(endpoint=http_ep)
    except ImportError:
        ...  # nosec B110

    logger.warning(
        "OTel: no exporter available — install opentelemetry-exporter-otlp-proto-grpc. Spans will not be exported."
    )
    return None


def _instrument_fastapi(app) -> None:
    key = "fastapi"
    if key in _instrumented:
        logger.debug("OTel: FastAPI already instrumented — skipping")
        return
    try:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

        FastAPIInstrumentor.instrument_app(app, excluded_urls="/health,/metrics,/favicon.ico")
        _instrumented.add(key)
        logger.info("OTel: FastAPI instrumented")
    except ImportError:
        logger.debug("OTel: FastAPI instrumentation not available")
    except Exception as exc:
        logger.warning("OTel: FastAPI instrumentation failed: %s", exc)


def _instrument_sqlalchemy() -> None:
    key = "sqlalchemy"
    if key in _instrumented:
        logger.debug("OTel: SQLAlchemy already instrumented — skipping")
        return
    try:
        from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor

        instr = SQLAlchemyInstrumentor()
        if not instr.is_instrumented_by_opentelemetry:
            instr.instrument()
            _instrumented.add(key)
            logger.info("OTel: SQLAlchemy instrumented")
        else:
            _instrumented.add(key)
            logger.debug("OTel: SQLAlchemy already instrumented by opentelemetry")
    except ImportError:
        logger.debug("OTel: SQLAlchemy instrumentation not available")
    except Exception as exc:
        logger.warning("OTel: SQLAlchemy instrumentation failed: %s", exc)


def _instrument_redis() -> None:
    key = "redis"
    if key in _instrumented:
        logger.debug("OTel: Redis already instrumented — skipping")
        return
    try:
        from opentelemetry.instrumentation.redis import RedisInstrumentor

        instr = RedisInstrumentor()
        if not instr.is_instrumented_by_opentelemetry:
            instr.instrument()
            _instrumented.add(key)
            logger.info("OTel: Redis instrumented")
        else:
            _instrumented.add(key)
            logger.debug("OTel: Redis already instrumented by opentelemetry")
    except ImportError:
        logger.debug("OTel: Redis instrumentation not available")
    except Exception as exc:
        logger.warning("OTel: Redis instrumentation failed: %s", exc)


def _instrument_aiohttp() -> None:
    key = "aiohttp"
    if key in _instrumented:
        logger.debug("OTel: aiohttp already instrumented — skipping")
        return
    try:
        from opentelemetry.instrumentation.aiohttp_client import (
            AioHttpClientInstrumentor,
        )

        instr = AioHttpClientInstrumentor()
        if not instr.is_instrumented_by_opentelemetry:
            instr.instrument()
            _instrumented.add(key)
            logger.info("OTel: aiohttp client instrumented")
        else:
            _instrumented.add(key)
            logger.debug("OTel: aiohttp already instrumented by opentelemetry")
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
            pass  # healer: ignore — intentional no-op in _NoOpTracer._Span

        def set_status(self, *a, **kw):
            pass  # healer: ignore — intentional no-op in _NoOpTracer._Span

        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

    def start_as_current_span(self, name, **kw):
        return self._Span()

    def start_span(self, name, **kw):
        return self._Span()

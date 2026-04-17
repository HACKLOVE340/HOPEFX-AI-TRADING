# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
api/tracing.py
==============
OpenTelemetry distributed tracing router.

Provides endpoints for inspecting and testing the OTel tracing pipeline.
Injects trace/span IDs into every response via ``TracingMiddleware``.

Environment variables
---------------------
OTEL_EXPORTER_OTLP_ENDPOINT : str
    gRPC/HTTP OTLP collector endpoint (e.g. ``http://otel-collector:4317``).
OTEL_SERVICE_NAME : str
    Service name reported in spans (default: ``"hopefx-trading"``).
OTEL_SAMPLING_RATE : float
    Head-based sampling probability 0.0–1.0 (default: ``1.0``).
"""

from __future__ import annotations

import collections
import logging
import os
import time
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.types import ASGIApp

logger = logging.getLogger(__name__)

# ── Optional OpenTelemetry imports ─────────────────────────────────────────────
try:
    from opentelemetry import trace
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor
    from opentelemetry.sdk.trace.sampling import ParentBased, TraceIdRatioBased

    _OTEL_AVAILABLE = True
except ImportError:  # pragma: no cover
    _OTEL_AVAILABLE = False
    trace = None  # type: ignore[assignment]

# W3C TraceContext propagation — enables distributed tracing across services
# (HTTP headers: traceparent, tracestate, baggage)
try:
    from opentelemetry import propagate
    from opentelemetry.propagators.composite import CompositePropagator
    from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator
    from opentelemetry.baggage.propagation import W3CBaggagePropagator

    _PROPAGATOR_AVAILABLE = True
except ImportError:
    _PROPAGATOR_AVAILABLE = False
    propagate = None  # type: ignore[assignment]

# gRPC exporter intentionally excluded: the grpcio C extension raises SIGBUS
# (signal 7) on some platforms/containers, which kills the process and cannot
# be caught by Python's try/except.  The HTTP exporter is functionally
# equivalent and does not carry this risk.
try:
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
        OTLPSpanExporter as OTLPHTTPSpanExporter,
    )

    _OTLP_HTTP_AVAILABLE = True
except ImportError:
    _OTLP_HTTP_AVAILABLE = False

# ── Config from environment ────────────────────────────────────────────────────
_OTLP_ENDPOINT: str = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "")
_SERVICE_NAME: str = os.getenv("OTEL_SERVICE_NAME", "hopefx-trading")
_SAMPLING_RATE: float = float(os.getenv("OTEL_SAMPLING_RATE", "1.0"))

# ── In-memory span ring buffer (last 100) ─────────────────────────────────────
_SPAN_BUFFER: collections.deque[dict[str, Any]] = collections.deque(maxlen=100)

# ── Tracer singleton ───────────────────────────────────────────────────────────
_tracer: Any = None
_provider_initialized: bool = False


class _NoOpSpan:
    """Minimal no-op span used when OTel is unavailable."""

    trace_id: str = "0" * 32
    span_id: str = "0" * 16

    def set_attribute(self, *_: Any, **__: Any) -> None:
        pass

    def add_event(self, *_: Any, **__: Any) -> None:
        pass

    def record_exception(self, *_: Any, **__: Any) -> None:
        pass

    def set_status(self, *_: Any, **__: Any) -> None:
        pass

    def __enter__(self) -> _NoOpSpan:
        return self

    def __exit__(self, *_: Any) -> None:
        pass


class _NoOpTracer:
    """Minimal no-op tracer used when OTel is unavailable."""

    def start_as_current_span(self, name: str, **_: Any) -> _NoOpSpan:
        return _NoOpSpan()

    def start_span(self, name: str, **_: Any) -> _NoOpSpan:
        return _NoOpSpan()


def _initialize_provider() -> None:
    """Lazily initialise the OpenTelemetry TracerProvider.

    Defers to tracing/setup.py if it has already configured a provider —
    prevents duplicate TracerProvider registration and double instrumentation
    of FastAPI/SQLAlchemy/Redis when both modules are imported at startup.
    """
    global _provider_initialized
    if _provider_initialized:
        return

    # If tracing/setup.py already ran setup_tracing(), its provider is live.
    # Reuse it rather than creating a second one.
    try:
        from tracing.setup import _tracer_provider as _setup_provider  # type: ignore[attr-defined]

        if _setup_provider is not None:
            _provider_initialized = True
            logger.debug("api/tracing: deferred to tracing/setup.py provider — skipping duplicate init")
            return
    except Exception:  # nosec B110 — tracing/setup.py may not be importable
        pass

    _provider_initialized = True

    if not _OTEL_AVAILABLE:
        logger.warning(
            "opentelemetry-sdk not installed — tracing disabled. "
            "Install opentelemetry-sdk and opentelemetry-exporter-otlp to enable."
        )
        return

    sampler = ParentBased(TraceIdRatioBased(_SAMPLING_RATE))
    resource = Resource.create({"service.name": _SERVICE_NAME})
    provider = TracerProvider(resource=resource, sampler=sampler)

    if _OTLP_ENDPOINT:
        try:
            if _OTLP_HTTP_AVAILABLE:
                exporter = OTLPHTTPSpanExporter(endpoint=_OTLP_ENDPOINT)
                provider.add_span_processor(BatchSpanProcessor(exporter))
                logger.info("OTel OTLP HTTP exporter configured → %s", _OTLP_ENDPOINT)
            else:
                logger.warning(
                    "OTLP endpoint set but no exporter available — install opentelemetry-exporter-otlp-proto-http"
                )
        except Exception as exc:
            logger.warning("Failed to configure OTLP exporter: %s", exc)

    trace.set_tracer_provider(provider)

    # Install W3C TraceContext + Baggage propagators so that
    # ``traceparent`` / ``tracestate`` / ``baggage`` HTTP headers are
    # automatically honoured when this service acts as a downstream consumer.
    if _PROPAGATOR_AVAILABLE:
        try:
            propagate.set_global_textmap(CompositePropagator([TraceContextTextMapPropagator(), W3CBaggagePropagator()]))
            logger.info("OTel W3C TraceContext + Baggage propagators installed")
        except Exception as _prop_exc:
            logger.debug("Could not install OTel propagators: %s", _prop_exc)

    logger.info(
        "OTel TracerProvider initialised | service=%s sampling=%.2f",
        _SERVICE_NAME,
        _SAMPLING_RATE,
    )


def get_tracer(name: str = "hopefx") -> Any:
    """Return an OpenTelemetry tracer (or no-op if OTel unavailable).

    This helper is imported by other modules (e.g. execution/engine.py)
    for span creation.

    Args:
        name: Instrumentation scope name.

    Returns:
        A real ``opentelemetry.trace.Tracer`` or a :class:`_NoOpTracer`.
    """
    if not _OTEL_AVAILABLE:
        return _NoOpTracer()
    _initialize_provider()
    return trace.get_tracer(name)


def _hex_trace_id() -> str:
    """Return a fresh 128-bit hex trace ID."""
    return uuid.uuid4().hex


def _hex_span_id() -> str:
    """Return a fresh 64-bit hex span ID."""
    return uuid.uuid4().hex[:16]


def _current_trace_span_ids() -> tuple[str, str]:
    """Extract current trace/span IDs from the active OTel span, or generate new ones."""
    if _OTEL_AVAILABLE:
        try:
            span = trace.get_current_span()
            ctx = span.get_span_context()
            if ctx and ctx.is_valid:
                tid = format(ctx.trace_id, "032x")
                sid = format(ctx.span_id, "016x")
                return tid, sid
        except Exception:
            logger.debug("Suppressed exception (no detail) in %s", __name__)
    return _hex_trace_id(), _hex_span_id()


# ── Middleware ─────────────────────────────────────────────────────────────────


class TracingMiddleware(BaseHTTPMiddleware):
    """ASGI middleware that injects OTel spans into every request lifecycle.

    Sets ``X-Trace-ID`` and ``X-Span-ID`` response headers on every request.
    Buffers span metadata into the in-memory ring buffer for ``GET /spans``.
    """

    def __init__(self, app: ASGIApp, **kwargs: Any) -> None:
        super().__init__(app, **kwargs)
        _initialize_provider()

    async def dispatch(
        self,
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        """Wrap each request in an OTel span."""
        tracer = get_tracer("hopefx.middleware")
        span_name = f"http.{request.method.lower()} {request.url.path}"

        t0 = time.perf_counter()
        trace_id, span_id = _current_trace_span_ids()

        try:
            if _OTEL_AVAILABLE:
                with tracer.start_as_current_span(span_name) as span:
                    span.set_attribute("http.method", request.method)
                    span.set_attribute("http.url", str(request.url))
                    span.set_attribute("http.path", request.url.path)
                    response: Response = await call_next(request)
                    span.set_attribute("http.status_code", response.status_code)
                    ctx = span.get_span_context()
                    if ctx and ctx.is_valid:
                        trace_id = format(ctx.trace_id, "032x")
                        span_id = format(ctx.span_id, "016x")
            else:
                response = await call_next(request)
        except Exception as exc:
            logger.exception("TracingMiddleware: unhandled exception: %s", exc)
            raise

        elapsed_ms = (time.perf_counter() - t0) * 1000

        _SPAN_BUFFER.append(
            {
                "trace_id": trace_id,
                "span_id": span_id,
                "name": span_name,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "duration_ms": round(elapsed_ms, 2),
                "status_code": response.status_code,
                "path": request.url.path,
                "method": request.method,
            }
        )

        response.headers["X-Trace-ID"] = trace_id
        response.headers["X-Span-ID"] = span_id
        return response


# ── Pydantic models ────────────────────────────────────────────────────────────


class TracingConfig(BaseModel):
    """Current OpenTelemetry configuration."""

    endpoint: str = Field(description="OTLP collector endpoint (empty if unset)")
    service_name: str = Field(description="OTel service name")
    sampling_rate: float = Field(description="Head-based sampling rate (0.0–1.0)")
    otel_available: bool = Field(description="Whether opentelemetry-sdk is installed")
    otlp_exporter_available: bool = Field(description="Whether an OTLP exporter is available")
    status: str = Field(description="operational | degraded | disabled")


class SpanRecord(BaseModel):
    """Single span record from the in-memory buffer."""

    trace_id: str
    span_id: str
    name: str
    timestamp: str
    duration_ms: float
    status_code: int
    path: str
    method: str


class SpanList(BaseModel):
    """Paginated list of recent spans."""

    count: int
    spans: list[SpanRecord]


class TestSpanResponse(BaseModel):
    """Result of emitting a test span."""

    trace_id: str
    span_id: str
    name: str
    timestamp: str
    message: str


# ── JWT auth dependency (re-used from auth.router) ────────────────────────────

from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

_bearer = HTTPBearer(auto_error=False)


def _require_auth(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> str:
    """Validate Bearer JWT and return user_id.

    Args:
        credentials: HTTP Authorization header credentials.

    Returns:
        Authenticated user ID string.

    Raises:
        HTTPException: 401 when token is missing, expired, or invalid.
        HTTPException: 503 when the auth service is misconfigured.
    """
    if not credentials:
        raise HTTPException(
            status_code=401,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        import jwt  # type: ignore[import]

        from auth.service import _get_secret  # type: ignore[import]

        secret = _get_secret()
        payload = jwt.decode(
            credentials.credentials,
            secret,
            algorithms=["HS256"],
            options={"require": ["sub", "exp"]},
        )
        if payload.get("type") != "access":
            raise ValueError("Not an access token")
        return payload["sub"]
    except RuntimeError as exc:
        logger.critical("JWT secret misconfiguration in tracing router: %s", exc)
        raise HTTPException(status_code=503, detail="Authentication service misconfigured") from exc
    except Exception:
        raise HTTPException(
            status_code=401,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from None


# ── Router ─────────────────────────────────────────────────────────────────────

router = APIRouter(prefix="/api/tracing", tags=["Observability"])


@router.get(
    "/config",
    response_model=TracingConfig,
    summary="Get current OpenTelemetry configuration",
)
async def get_tracing_config() -> TracingConfig:
    """Return the current OTel configuration and status.

    Returns:
        :class:`TracingConfig` with endpoint, service name, sampling rate, and status.
    """
    otlp_available = _OTLP_HTTP_AVAILABLE

    if not _OTEL_AVAILABLE:
        status = "disabled"
    elif not _OTLP_ENDPOINT:
        status = "degraded"
    else:
        status = "operational"

    return TracingConfig(
        endpoint=_OTLP_ENDPOINT,
        service_name=_SERVICE_NAME,
        sampling_rate=_SAMPLING_RATE,
        otel_available=_OTEL_AVAILABLE,
        otlp_exporter_available=otlp_available,
        status=status,
    )


@router.get(
    "/spans",
    response_model=SpanList,
    summary="Return last 100 spans from in-memory ring buffer",
)
async def get_spans() -> SpanList:
    """Return the last 100 recorded spans from the ring buffer.

    Returns:
        :class:`SpanList` containing up to 100 span records.
    """
    spans = list(_SPAN_BUFFER)
    return SpanList(
        count=len(spans),
        spans=[SpanRecord(**s) for s in reversed(spans)],
    )


@router.post(
    "/test",
    response_model=TestSpanResponse,
    summary="Emit a test span and return its trace ID",
    status_code=201,
)
async def emit_test_span(
    _user_id: str = Depends(_require_auth),
) -> TestSpanResponse:
    """Emit a test span through the signal→gate→broker chain and return trace IDs.

    Requires JWT authentication.

    Args:
        _user_id: Authenticated user ID (injected by dependency).

    Returns:
        :class:`TestSpanResponse` with the emitted trace and span IDs.
    """
    tracer = get_tracer("hopefx.test")
    ts = datetime.now(timezone.utc).isoformat()
    trace_id = _hex_trace_id()
    span_id = _hex_span_id()

    if _OTEL_AVAILABLE:
        with tracer.start_as_current_span("hopefx.test.signal_to_broker") as root:
            root.set_attribute("test", True)
            root.set_attribute("triggered_by", _user_id)
            root.add_event("signal.received", {"symbol": "XAUUSD", "side": "BUY"})

            with tracer.start_as_current_span("hopefx.test.pre_trade_gate") as gate:
                gate.set_attribute("gate.check", "risk_limits")
                gate.add_event("gate.passed")

            with tracer.start_as_current_span("hopefx.test.broker_submit") as broker:
                broker.set_attribute("broker.name", "test_broker")
                broker.add_event("broker.ack", {"order_id": "test-0001"})

            ctx = root.get_span_context()
            if ctx and ctx.is_valid:
                trace_id = format(ctx.trace_id, "032x")
                span_id = format(ctx.span_id, "016x")
    else:
        _SPAN_BUFFER.append(
            {
                "trace_id": trace_id,
                "span_id": span_id,
                "name": "hopefx.test.signal_to_broker",
                "timestamp": ts,
                "duration_ms": 0.0,
                "status_code": 200,
                "path": "/api/tracing/test",
                "method": "POST",
            }
        )

    return TestSpanResponse(
        trace_id=trace_id,
        span_id=span_id,
        name="hopefx.test.signal_to_broker",
        timestamp=ts,
        message="Test span emitted successfully"
        if _OTEL_AVAILABLE
        else "OTel unavailable — span recorded in buffer only",
    )

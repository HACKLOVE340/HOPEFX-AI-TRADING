# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# AGPL-3.0 — Share all modifications
"""
tests/unit/test_api_tracing.py
================================
Unit tests for api/tracing.py.

Covers:
- _NoOpSpan / _NoOpTracer — no-op implementations
- _hex_trace_id / _hex_span_id — ID generation
- _current_trace_span_ids — returns valid hex strings
- get_tracer — returns a tracer (real or no-op)
- TracingMiddleware — injects X-Trace-ID / X-Span-ID headers, buffers spans
- _SPAN_BUFFER — ring buffer capped at 100
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# _NoOpSpan
# ---------------------------------------------------------------------------


class TestNoOpSpan:
    def test_set_attribute_does_not_raise(self):
        from api.tracing import _NoOpSpan
        span = _NoOpSpan()
        span.set_attribute("http.method", "GET")

    def test_add_event_does_not_raise(self):
        from api.tracing import _NoOpSpan
        span = _NoOpSpan()
        span.add_event("test_event")

    def test_record_exception_does_not_raise(self):
        from api.tracing import _NoOpSpan
        span = _NoOpSpan()
        span.record_exception(ValueError("test"))

    def test_set_status_does_not_raise(self):
        from api.tracing import _NoOpSpan
        span = _NoOpSpan()
        span.set_status("OK")

    def test_context_manager(self):
        from api.tracing import _NoOpSpan
        span = _NoOpSpan()
        with span as s:
            assert s is span

    def test_trace_id_is_zeros(self):
        from api.tracing import _NoOpSpan
        assert _NoOpSpan.trace_id == "0" * 32

    def test_span_id_is_zeros(self):
        from api.tracing import _NoOpSpan
        assert _NoOpSpan.span_id == "0" * 16


# ---------------------------------------------------------------------------
# _NoOpTracer
# ---------------------------------------------------------------------------


class TestNoOpTracer:
    def test_start_as_current_span_returns_noop_span(self):
        from api.tracing import _NoOpTracer, _NoOpSpan
        tracer = _NoOpTracer()
        span = tracer.start_as_current_span("test.span")
        assert isinstance(span, _NoOpSpan)

    def test_start_span_returns_noop_span(self):
        from api.tracing import _NoOpTracer, _NoOpSpan
        tracer = _NoOpTracer()
        span = tracer.start_span("test.span")
        assert isinstance(span, _NoOpSpan)


# ---------------------------------------------------------------------------
# ID generation helpers
# ---------------------------------------------------------------------------


class TestIdHelpers:
    def test_hex_trace_id_is_32_chars(self):
        from api.tracing import _hex_trace_id
        tid = _hex_trace_id()
        assert len(tid) == 32
        assert all(c in "0123456789abcdef" for c in tid)

    def test_hex_trace_id_unique(self):
        from api.tracing import _hex_trace_id
        ids = {_hex_trace_id() for _ in range(10)}
        assert len(ids) == 10

    def test_hex_span_id_is_16_chars(self):
        from api.tracing import _hex_span_id
        sid = _hex_span_id()
        assert len(sid) == 16
        assert all(c in "0123456789abcdef" for c in sid)

    def test_current_trace_span_ids_returns_valid_hex(self):
        from api.tracing import _current_trace_span_ids
        tid, sid = _current_trace_span_ids()
        assert len(tid) == 32
        assert len(sid) == 16
        assert all(c in "0123456789abcdef" for c in tid)
        assert all(c in "0123456789abcdef" for c in sid)

    def test_current_trace_span_ids_returns_tuple(self):
        from api.tracing import _current_trace_span_ids
        result = _current_trace_span_ids()
        assert isinstance(result, tuple)
        assert len(result) == 2


# ---------------------------------------------------------------------------
# get_tracer
# ---------------------------------------------------------------------------


class TestGetTracer:
    def test_returns_tracer_object(self):
        from api.tracing import get_tracer
        tracer = get_tracer("test")
        assert tracer is not None

    def test_tracer_has_start_as_current_span(self):
        from api.tracing import get_tracer
        tracer = get_tracer("test")
        assert hasattr(tracer, "start_as_current_span")

    def test_default_name(self):
        from api.tracing import get_tracer
        tracer = get_tracer()
        assert tracer is not None


# ---------------------------------------------------------------------------
# TracingMiddleware — via TestClient
# ---------------------------------------------------------------------------


@pytest.fixture()
def traced_app():
    """Minimal FastAPI app with TracingMiddleware attached."""
    from api.tracing import TracingMiddleware, _SPAN_BUFFER
    _SPAN_BUFFER.clear()

    app = FastAPI()
    app.add_middleware(TracingMiddleware)

    @app.get("/ping")
    def ping():
        return {"ok": True}

    @app.get("/error")
    def error():
        return {"status": "error"}, 500

    return app


class TestTracingMiddleware:
    def test_injects_x_trace_id_header(self, traced_app):
        client = TestClient(traced_app, raise_server_exceptions=False)
        r = client.get("/ping")
        assert "x-trace-id" in r.headers
        tid = r.headers["x-trace-id"]
        assert len(tid) == 32

    def test_injects_x_span_id_header(self, traced_app):
        client = TestClient(traced_app, raise_server_exceptions=False)
        r = client.get("/ping")
        assert "x-span-id" in r.headers
        sid = r.headers["x-span-id"]
        assert len(sid) == 16

    def test_span_buffered_after_request(self, traced_app):
        from api.tracing import _SPAN_BUFFER
        _SPAN_BUFFER.clear()
        client = TestClient(traced_app, raise_server_exceptions=False)
        client.get("/ping")
        assert len(_SPAN_BUFFER) == 1
        span = _SPAN_BUFFER[0]
        assert span["path"] == "/ping"
        assert span["method"] == "GET"
        assert span["status_code"] == 200

    def test_span_buffer_contains_duration(self, traced_app):
        from api.tracing import _SPAN_BUFFER
        _SPAN_BUFFER.clear()
        client = TestClient(traced_app, raise_server_exceptions=False)
        client.get("/ping")
        span = _SPAN_BUFFER[0]
        assert "duration_ms" in span
        assert span["duration_ms"] >= 0.0

    def test_span_buffer_capped_at_100(self, traced_app):
        from api.tracing import _SPAN_BUFFER
        _SPAN_BUFFER.clear()
        client = TestClient(traced_app, raise_server_exceptions=False)
        for _ in range(110):
            client.get("/ping")
        assert len(_SPAN_BUFFER) <= 100

    def test_multiple_requests_each_get_unique_trace_ids(self, traced_app):
        client = TestClient(traced_app, raise_server_exceptions=False)
        ids = {client.get("/ping").headers["x-trace-id"] for _ in range(5)}
        assert len(ids) == 5

    def test_span_buffer_records_span_name(self, traced_app):
        from api.tracing import _SPAN_BUFFER
        _SPAN_BUFFER.clear()
        client = TestClient(traced_app, raise_server_exceptions=False)
        client.get("/ping")
        span = _SPAN_BUFFER[0]
        assert "ping" in span["name"].lower() or "get" in span["name"].lower()

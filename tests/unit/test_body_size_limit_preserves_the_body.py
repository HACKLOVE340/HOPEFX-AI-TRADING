# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
tests/unit/test_body_size_limit_preserves_the_body.py
=====================================================
Every chunked request reached its handler with an empty body.

`BodySizeLimitMiddleware` has to meter requests that omit `Content-Length`,
or the header check is skipped by anyone sending `Transfer-Encoding: chunked`.
It did that by draining `request.stream()` and then reassigning
`request._receive` to replay the bytes, with a comment asserting that
"replacing the receive channel is the documented way to replay a body".

It is not, under `BaseHTTPMiddleware`. Starlette binds its own wrapped receive
before `dispatch` runs and short-circuits on `_stream_consumed`, so the
reassignment is ignored: the downstream handler sees a body of zero bytes.
Reproduced directly —

    with Content-Length:  {"len": 11}
    chunked:              {"len": 0}

— which is silent data loss on every such request, not a rejection anyone
could notice. The cap itself still worked, so the middleware looked fine.

The fix is to stop consuming the body. As a pure ASGI middleware it wraps
`receive` and counts bytes as the *handler* pulls them, so the body is never
buffered, never replayed, and the 413 still fires the moment the cap is
crossed.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI, Request

pytestmark = pytest.mark.unit


def _app():
    # Request must be resolvable from module globals: `from __future__ import
    # annotations` makes the route annotations strings, and FastAPI resolves
    # them against the defining module. Importing it inside this factory made
    # FastAPI treat `request` as a missing query parameter.
    from core.middleware import BodySizeLimitMiddleware

    app = FastAPI()
    app.add_middleware(BodySizeLimitMiddleware)

    @app.post("/echo")
    async def echo(request: Request):  # pragma: no cover - exercised via TestClient
        body = await request.body()
        return {"len": len(body), "body": body.decode()}

    @app.post("/health/echo")
    async def exempt(request: Request):  # pragma: no cover - exercised via TestClient
        body = await request.body()
        return {"len": len(body)}

    return app


def _client():
    from fastapi.testclient import TestClient

    return TestClient(_app())


def _chunks(*parts: bytes):
    def gen():
        yield from parts

    return gen()


class TestTheBodySurvives:
    def test_a_request_with_content_length_reaches_the_handler(self):
        resp = _client().post("/echo", content=b"hello world")

        assert resp.json() == {"len": 11, "body": "hello world"}

    def test_a_chunked_request_reaches_the_handler_intact(self):
        """The defect: this used to arrive as zero bytes."""
        resp = _client().post("/echo", content=_chunks(b"hello ", b"world"))

        assert resp.json() == {"len": 11, "body": "hello world"}, (
            "a chunked body was silently dropped before reaching the route"
        )

    def test_a_multi_chunk_body_is_reassembled_in_order(self):
        resp = _client().post("/echo", content=_chunks(b"a", b"b", b"c", b"d"))

        assert resp.json()["body"] == "abcd"

    def test_an_empty_body_is_still_empty(self):
        resp = _client().post("/echo", content=b"")

        assert resp.json() == {"len": 0, "body": ""}


class TestTheCapStillFires:
    def test_an_oversized_content_length_is_rejected(self, monkeypatch):
        import core.middleware as mw

        monkeypatch.setattr(mw, "_MAX_BODY_BYTES", 16)
        resp = _client().post("/echo", content=b"x" * 64)

        assert resp.status_code == 413

    def test_an_oversized_chunked_body_is_rejected(self, monkeypatch):
        """Without this the header check is bypassed by sending chunked."""
        import core.middleware as mw

        monkeypatch.setattr(mw, "_MAX_BODY_BYTES", 16)
        resp = _client().post("/echo", content=_chunks(b"x" * 8, b"y" * 8, b"z" * 8))

        assert resp.status_code == 413

    def test_a_body_exactly_at_the_cap_is_allowed(self, monkeypatch):
        import core.middleware as mw

        monkeypatch.setattr(mw, "_MAX_BODY_BYTES", 16)
        resp = _client().post("/echo", content=_chunks(b"x" * 16))

        assert resp.status_code == 200

    def test_a_malformed_content_length_is_a_400(self):
        resp = _client().post("/echo", content=b"hi", headers={"content-length": "not-a-number"})

        assert resp.status_code in (400, 422)


class TestExemptPaths:
    def test_an_exempt_prefix_still_receives_its_body(self):
        resp = _client().post("/health/echo", content=_chunks(b"ping"))

        assert resp.json() == {"len": 4}

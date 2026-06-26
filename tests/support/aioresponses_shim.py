# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
tests/support/aioresponses_shim.py
==================================
A tiny, dependency-free drop-in for the subset of the ``aioresponses`` API our
async HTTP-source tests use. The upstream ``aioresponses`` library (0.7.9) is
incompatible with ``aiohttp >= 3.14`` (it builds ``ClientResponse`` without the
new required ``stream_writer`` argument), which blocked us from taking the
aiohttp 3.14 security patches.

This shim patches ``aiohttp.ClientSession.get``/``.post`` directly, so it works
on any aiohttp version. It supports exactly what the tests need:

    with aioresponses() as m:
        m.get(url_or_regex, payload={...})          # JSON body
        m.get(url_or_regex, status=429)             # HTTP status (raise_for_status)
        m.get(url_or_regex, exception=ClientError)  # raised on entry

URL matching accepts a plain string (exact or prefix match) or a compiled
``re.Pattern`` (searched against the request URL). Query params passed via the
``params=`` kwarg are intentionally ignored for matching — the sources pass the
base URL plus ``params=``, and the test regexes already end in ``.*``.
"""

from __future__ import annotations

import re
import types
from typing import Any
from unittest.mock import patch

import aiohttp


class _FakeResponse:
    """Async-context-manager stand-in for an aiohttp response."""

    def __init__(self, *, status: int = 200, payload: Any = None, body: str | None = None) -> None:
        self.status = status
        self._payload = payload
        self._body = body if body is not None else ""

    async def __aenter__(self) -> _FakeResponse:
        return self

    async def __aexit__(self, *_exc: object) -> bool:
        return False

    async def json(self, **_kwargs: Any) -> Any:
        return self._payload

    async def text(self, **_kwargs: Any) -> str:
        return self._body

    def raise_for_status(self) -> None:
        if self.status >= 400:
            raise aiohttp.ClientResponseError(
                request_info=types.SimpleNamespace(real_url="mock://test", url="mock://test"),
                history=(),
                status=self.status,
                message=f"HTTP {self.status}",
            )


class _ExceptionCtx:
    """Async context manager that raises on entry — models a connection error."""

    def __init__(self, exc: BaseException) -> None:
        self._exc = exc

    async def __aenter__(self) -> Any:
        raise self._exc

    async def __aexit__(self, *_exc: object) -> bool:
        return False


class aioresponses:
    """Minimal aiohttp request mocker compatible with aiohttp >= 3.14."""

    def __init__(self) -> None:
        # (method, pattern, payload, status, exception, body)
        self._rules: list[tuple[str, Any, Any, int, BaseException | None, str | None]] = []
        self._patchers: list[Any] = []

    # ── registration ────────────────────────────────────────────────────────
    def _register(
        self,
        method: str,
        url: Any,
        *,
        payload: Any = None,
        status: int = 200,
        exception: BaseException | None = None,
        body: str | None = None,
        **_ignored: Any,
    ) -> None:
        self._rules.append((method.upper(), url, payload, status, exception, body))

    def get(self, url: Any, **kwargs: Any) -> None:
        self._register("GET", url, **kwargs)

    def post(self, url: Any, **kwargs: Any) -> None:
        self._register("POST", url, **kwargs)

    # ── matching ──────────────────────────────────────────────────────────────
    def _match(self, method: str, url: Any):
        url_s = str(url)
        for m, pat, payload, status, exception, body in self._rules:
            if m != method:
                continue
            matched = pat.search(url_s) is not None if isinstance(pat, re.Pattern) else url_s.startswith(str(pat))
            if matched:
                return payload, status, exception, body
        raise AssertionError(f"aioresponses_shim: no mock registered for {method} {url_s}")

    def _make_handler(self, method: str):
        def _handler(_session: Any, url: Any, **_kwargs: Any):
            payload, status, exception, body = self._match(method, url)
            if exception is not None:
                return _ExceptionCtx(exception)
            return _FakeResponse(status=status, payload=payload, body=body)

        return _handler

    # ── context manager ─────────────────────────────────────────────────────
    def __enter__(self) -> aioresponses:
        for meth in ("get", "post"):
            p = patch.object(aiohttp.ClientSession, meth, new=self._make_handler(meth.upper()))
            p.start()
            self._patchers.append(p)
        return self

    def __exit__(self, *_exc: object) -> bool:
        for p in reversed(self._patchers):
            p.stop()
        self._patchers.clear()
        return False

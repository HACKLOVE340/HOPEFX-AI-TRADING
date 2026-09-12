# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""`core/metrics.py` — the Prometheus surface, and what it fails to count.

The middleware is live: `core/middleware.py:273` attaches it to the app. So
unlike most of what this programme has found, these are not latent.

The module measured 33%, and the uncovered two-thirds was the middleware itself,
the path normaliser, the response helper, and the entire no-prometheus fallback
— that last one unreachable in place because `prometheus_client` *is* installed,
so the `else` branch that defines the stubs never executes. It is reached here
by loading the module a second time with the library blocked.
"""

from __future__ import annotations

import builtins
import importlib.util
import pathlib
import sys
import types

import pytest
from prometheus_client import REGISTRY
from starlette.applications import Starlette
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import PlainTextResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from core import metrics

pytestmark = pytest.mark.unit

REPO = pathlib.Path(__file__).resolve().parents[2]
MODULE_PATH = REPO / "core" / "metrics.py"


def _requests_counted(path: str, status: str | None = None) -> float:
    """How many requests Prometheus has recorded for *path*."""
    total = 0.0
    for metric in REGISTRY.collect():
        if metric.name != "hopefx_http_requests":
            continue
        for sample in metric.samples:
            if not sample.name.endswith("_total"):
                continue
            if sample.labels.get("path") != path:
                continue
            if status is not None and sample.labels.get("status") != status:
                continue
            total += sample.value
    return total


def _latency_count(path: str) -> float:
    for metric in REGISTRY.collect():
        if metric.name != "hopefx_http_request_duration_seconds":
            continue
        for sample in metric.samples:
            if sample.name.endswith("_count") and sample.labels.get("path") == path:
                return sample.value
    return 0.0


@pytest.fixture
def client() -> TestClient:
    async def ok(_request):
        return PlainTextResponse("ok")

    async def not_found(_request):
        return PlainTextResponse("nope", status_code=404)

    async def boom(_request):
        raise RuntimeError("handler blew up")

    app = Starlette(
        routes=[
            Route("/probe-ok", ok),
            Route("/probe-404", not_found),
            Route("/probe-boom", boom),
        ]
    )
    app.add_middleware(BaseHTTPMiddleware, dispatch=metrics.make_metrics_middleware())
    return TestClient(app, raise_server_exceptions=False)


class TestTheMiddlewareCountsWhatMatters:
    def test_a_successful_request_is_counted_with_its_status(self, client: TestClient) -> None:
        before = _requests_counted("/probe-ok", "200")
        client.get("/probe-ok")
        assert _requests_counted("/probe-ok", "200") == before + 1

    def test_a_handled_error_response_is_counted_with_its_own_status(self, client: TestClient) -> None:
        before = _requests_counted("/probe-404", "404")
        client.get("/probe-404")
        assert _requests_counted("/probe-404", "404") == before + 1

    def test_a_request_that_raises_is_still_counted(self, client: TestClient) -> None:
        """The one that matters.

        `response = await call_next(request)` propagates a handler exception
        straight out of the middleware, so the `.inc()` below it never runs.
        Starlette's own error middleware then turns it into a 500 the client
        sees — and `hopefx_http_requests_total` never hears about it.

        An error-rate alert built on `status=~"5.."` therefore reads zero during
        exactly the outage it exists to catch: the requests it counts are the
        ones that worked.
        """
        before = _requests_counted("/probe-boom")
        response = client.get("/probe-boom")
        assert response.status_code == 500
        assert _requests_counted("/probe-boom") == before + 1

    def test_a_request_that_raises_is_counted_as_a_server_error(self, client: TestClient) -> None:
        before = _requests_counted("/probe-boom", "500")
        client.get("/probe-boom")
        assert _requests_counted("/probe-boom", "500") == before + 1

    def test_the_latency_of_a_failing_request_is_observed_too(self, client: TestClient) -> None:
        """Failing requests are often the slow ones; losing them skews the
        histogram toward health."""
        before = _latency_count("/probe-boom")
        client.get("/probe-boom")
        assert _latency_count("/probe-boom") == before + 1

    def test_the_exception_is_not_swallowed(self) -> None:
        """Counting it must not turn a crash into a silent success."""

        async def boom(_request):
            raise RuntimeError("handler blew up")

        app = Starlette(routes=[Route("/raises", boom)])
        app.add_middleware(BaseHTTPMiddleware, dispatch=metrics.make_metrics_middleware())

        with pytest.raises(RuntimeError, match="handler blew up"):
            TestClient(app, raise_server_exceptions=True).get("/raises")


class TestPathNormalisation:
    """Every distinct label value is a new Prometheus time series, so a path
    that carries an identifier is a cardinality leak."""

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("/api/orders/12345", "/api/orders/{id}"),
            ("/api/users/550e8400-e29b-41d4-a716-446655440000", "/api/users/{id}"),
            ("/api/orders/7/fills/99", "/api/orders/{id}/fills/{id}"),
            ("/api/health", "/api/health"),
            ("/", "/"),
            ("", ""),
        ],
    )
    def test_identifiers_collapse_and_names_survive(self, raw: str, expected: str) -> None:
        assert metrics._normalise_path(raw) == expected

    def test_a_symbol_is_not_mistaken_for_an_identifier(self) -> None:
        """XAUUSD is one of a handful of values; collapsing it would lose the
        breakdown the metric exists for."""
        assert metrics._normalise_path("/api/positions/XAUUSD") == "/api/positions/XAUUSD"


class TestMetricsResponse:
    def test_it_returns_the_prometheus_exposition_format(self) -> None:
        body, content_type = metrics.metrics_response()
        assert isinstance(body, bytes)
        assert "text/plain" in content_type
        assert b"hopefx_" in body


# ---------------------------------------------------------------------------
# The fallback that CI cannot otherwise reach
# ---------------------------------------------------------------------------


def _load_without_prometheus(app_env: str) -> types.ModuleType:
    """Load `core/metrics.py` a second time with `prometheus_client` absent."""
    real_import = builtins.__import__

    def _blocked(name: str, *args, **kwargs):
        if name == "prometheus_client" or name.startswith("prometheus_client."):
            raise ImportError("simulated: prometheus_client is not installed")
        return real_import(name, *args, **kwargs)

    import os

    previous_env = os.environ.get("APP_ENV")
    os.environ["APP_ENV"] = app_env
    builtins.__import__ = _blocked
    name = "_core_metrics_no_prometheus"
    try:
        spec = importlib.util.spec_from_file_location(name, MODULE_PATH)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
        return module
    finally:
        builtins.__import__ = real_import
        sys.modules.pop(name, None)
        if previous_env is None:
            os.environ.pop("APP_ENV", None)
        else:
            os.environ["APP_ENV"] = previous_env


class TestWithoutPrometheusInstalled:
    def test_the_module_still_imports(self) -> None:
        module = _load_without_prometheus("development")
        assert module._PROM_AVAILABLE is False

    def test_every_metric_call_becomes_a_no_op(self) -> None:
        """The stubs exist so callers do not have to guard every call. If one
        raised, an absent optional dependency would take down a request."""
        module = _load_without_prometheus("development")
        for name in (
            "HTTP_REQUESTS",
            "HTTP_LATENCY",
            "ORDERS_TOTAL",
            "ACTIVE_POSITIONS",
            "PNL_TOTAL",
            "WS_CONNECTIONS",
            "AUTH_ATTEMPTS",
            "AML_BLOCKS",
            "RECONCILER_CYCLES",
            "RECONCILER_MISMATCHES",
            "NEWS_QUEUE_ENQUEUED",
            "NEWS_QUEUE_DROPS",
        ):
            stub = getattr(module, name)
            stub.labels(method="GET", path="/x", status="200").inc()
            stub.set(1.0)
            stub.observe(0.1)
            with stub.time():
                pass

    def test_the_middleware_still_serves_requests(self) -> None:
        """An absent metrics library must cost observability, not availability."""
        module = _load_without_prometheus("development")

        async def ok(_request):
            return PlainTextResponse("ok")

        app = Starlette(routes=[Route("/x", ok)])
        app.add_middleware(BaseHTTPMiddleware, dispatch=module.make_metrics_middleware())
        assert TestClient(app).get("/x").status_code == 200

    def test_the_response_helper_says_so_rather_than_pretending(self) -> None:
        module = _load_without_prometheus("development")
        body, content_type = module.metrics_response()
        assert b"not installed" in body
        assert content_type == "text/plain"

    @pytest.mark.parametrize("env", ["production", "staging"])
    def test_production_is_warned_that_metrics_are_off(self, env: str, caplog: pytest.LogCaptureFixture) -> None:
        with caplog.at_level("WARNING"):
            _load_without_prometheus(env)
        assert any("DISABLED" in record.message for record in caplog.records)

    def test_development_is_not_nagged(self, caplog: pytest.LogCaptureFixture) -> None:
        with caplog.at_level("WARNING"):
            _load_without_prometheus("development")
        assert not [r for r in caplog.records if "DISABLED" in r.message]

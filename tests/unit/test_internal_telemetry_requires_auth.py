# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# AGPL-3.0 — Share all modifications
"""
tests/unit/test_internal_telemetry_requires_auth.py
====================================================
Regression tests: the operator-facing read endpoints must not be anonymous.

Pre-launch checklist findings P-01 and P-02 (docs/HARDENING_BACKLOG.md).

P-01 — five routers exposed operational internals with no dependency at all:

    /api/observability/{traces,metrics,alerts,services,latency-histogram}
    /api/mlops/{health,drift,shadow,retrain/history,models/{id}/metrics}
    /api/tracing/{config,spans}
    /api/ml/{drift-report,drift/status,sharpe-circuit-breaker/status,
             model-drift,ab-tests,training-jobs,explain/{m},
             feature-importance/{m}}
    /api/transparency/audit-log

Round 4 Slice F4 audited the *frontend* side of this and found it clean:
`/observability` and `/ml-ops` both go through `adminOnly()` in `App.tsx`, and
the guards were pinned by tests. That is what made the gap easy to miss — the
restriction genuinely existed, but only in the SPA. Nothing stopped a caller
from skipping the React app and reading the same JSON straight off the API,
which is the whole reason authorization cannot live in a frontend.

Two of these are worth naming individually. `/api/ml/explain/{model}` returns
SHAP feature importances for the deployed model — on a trading system that is
the edge itself, and the *same data* was already gated at
`require_role("trader")` on the sibling `/api/ml/feature-importances` route, so
the codebase disagreed with itself about whether it was public. And
`/api/transparency/audit-log` returns config changes and risk events, while its
neighbours in that router (`/decisions`, `/explain/{trade}`, `/stats`,
`/statement`) are deliberately public for client/auditor verification — so the
fix there had to be one route, not the router.

P-02 — `GET /api/macro/refresh` invalidated the 1-hour FRED cache and re-fetched
on every call, unauthenticated, then wrote the result into `MacroStore` where
live inference reads it. The sibling `/api/macro/features` already required a
token; this one read like a health check and was not treated as a write.

These tests assert on the resolved dependency graph rather than on source text,
so moving a guard between the route and the router keeps them passing while
removing one fails.
"""

from __future__ import annotations

import importlib

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

# (module, path) pairs that must reject an anonymous caller.
GATED_READS: list[tuple[str, str]] = [
    ("api.observability", "/api/observability/traces"),
    ("api.observability", "/api/observability/metrics"),
    ("api.observability", "/api/observability/alerts"),
    ("api.observability", "/api/observability/services"),
    ("api.observability", "/api/observability/latency-histogram"),
    ("api.ml_ops", "/api/mlops/health"),
    ("api.ml_ops", "/api/mlops/drift"),
    ("api.ml_ops", "/api/mlops/shadow"),
    ("api.ml_ops", "/api/mlops/retrain/history"),
    ("api.ml_ops", "/api/mlops/models/v1/metrics"),
    ("api.tracing", "/api/tracing/config"),
    ("api.tracing", "/api/tracing/spans"),
    ("api.transparency", "/api/transparency/audit-log"),
    ("api.macro", "/api/macro/refresh"),
    ("api.ml", "/api/ml/drift-report"),
    ("api.ml", "/api/ml/drift/status"),
    ("api.ml", "/api/ml/sharpe-circuit-breaker/status"),
    ("api.ml", "/api/ml/model-drift"),
    ("api.ml", "/api/ml/ab-tests"),
    ("api.ml", "/api/ml/training-jobs"),
    ("api.ml", "/api/ml/explain/xgboost"),
    ("api.ml", "/api/ml/feature-importance/xgboost"),
]

# Routes in api/transparency.py that are public on purpose. Gating these would
# defeat the router's stated reason to exist, so a fix that over-corrects and
# closes them is also a regression.
INTENTIONALLY_PUBLIC: list[str] = [
    "/api/transparency/decisions",
    "/api/transparency/stats",
    "/api/transparency/statement",
]


def _client(module_name: str) -> TestClient:
    mod = importlib.import_module(module_name)
    app = FastAPI()
    app.include_router(mod.router)
    # raise_server_exceptions=False so a handler that would 500 on missing app
    # state still reports its status code — we are asserting on the guard, and a
    # 500 would mean the request reached the body, i.e. the guard did not fire.
    return TestClient(app, raise_server_exceptions=False)


@pytest.mark.unit
class TestInternalTelemetryRejectsAnonymous:
    @pytest.mark.parametrize(("module_name", "path"), GATED_READS, ids=[p for _, p in GATED_READS])
    def test_anonymous_request_is_rejected(self, module_name: str, path: str):
        """No token → 401/403, never a 200 body and never a 500 from the handler."""
        response = _client(module_name).get(path)
        assert response.status_code in (401, 403), (
            f"{path} answered {response.status_code} without a token. "
            "Operator telemetry and model internals must be gated server-side; "
            "the adminOnly() wrapper in App.tsx only hides the page (P-01)."
        )


@pytest.mark.unit
class TestTransparencyStaysPublicWhereIntended:
    @pytest.mark.parametrize("path", INTENTIONALLY_PUBLIC)
    def test_public_transparency_routes_still_answer(self, path: str):
        """The auditor-facing surface must survive the audit-log fix (P-01)."""
        response = _client("api.transparency").get(path)
        assert response.status_code == 200, (
            f"{path} answered {response.status_code}. The transparency router is "
            "deliberately readable without an account so a client or auditor can "
            "verify behaviour; only /audit-log is gated."
        )


@pytest.mark.unit
class TestGuardsAreOnTheDependencyGraph:
    """Assert the guard is a real dependency, not a docstring promise."""

    @pytest.mark.parametrize(
        "module_name",
        ["api.observability", "api.ml_ops", "api.tracing"],
    )
    def test_router_level_dependency_present(self, module_name: str):
        mod = importlib.import_module(module_name)
        assert mod.router.dependencies, (
            f"{module_name} declares no router-level dependency. These routers are "
            "entirely operator-facing, so the guard belongs on the router where it "
            "also covers routes added later (P-01)."
        )

    def test_macro_refresh_has_a_route_dependency(self):
        """macro's router is mixed-access, so /refresh carries its own guard."""
        from api.macro import router

        # route.path is prefix-inclusive (the router declares prefix="/api/macro"),
        # and an endswith match would also catch /api/macro/wgc/refresh.
        refresh = [r for r in router.routes if getattr(r, "path", "") == "/api/macro/refresh"]
        assert refresh, "GET /api/macro/refresh is missing from the router."
        names = {d.call.__name__ for d in refresh[0].dependant.dependencies if getattr(d, "call", None)}
        assert names, (
            "GET /api/macro/refresh has no dependency. It bypasses the FRED cache "
            "on every call and writes into MacroStore, so it is a write with a "
            "cost attached, not a health check (P-02)."
        )

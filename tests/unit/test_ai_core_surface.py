"""Task 13 — the AI Core page reads real endpoints, and they are gated.

The page's done-condition is "every panel reads a real endpoint, and no control
is decorative" — the D6 rule applied page-wide. That condition is only
meaningful if the endpoints exist, return live state, and enforce the Part 1B
matrix, so those three things are asserted here rather than assumed by the UI.

Three properties carry over from the modules the page reports on:

* **Admin is gated below superadmin.** `require_role` is a minimum-rank check,
  so every "admin" gate admits a superadmin too. The reverse must not hold, and
  an admin must not be able to read another operator's spend or call history —
  that is reconnaissance for the overtake case D7 closed.
* **No endpoint returns a prompt.** Prompts carry position data. The gateway's
  audit record keeps a digest; the read surface must not widen that.
* **A capability with no row is a refusal.** An endpoint added here without a
  row in `ai.policy.roles` has no declared authorization.
"""

from __future__ import annotations

import ast
import pathlib

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ai.policy import roles as policy
from api.ai_core import router
from api.auth import TokenPayload, get_current_user

_MODULE = pathlib.Path("api/ai_core.py")

VIEW_PATHS = [
    "/api/ai-core/summary",
    "/api/ai-core/capabilities",
    "/api/ai-core/chain",
    "/api/ai-core/budget",
    "/api/ai-core/calls",
    "/api/ai-core/cache",
    "/api/ai-core/evals",
]


def _client(role: str, sub: str = "op-admin") -> TestClient:
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_current_user] = lambda: TokenPayload(sub=sub, role=role)
    return TestClient(app)


@pytest.fixture(autouse=True)
def _clean_gateway_state():
    from ai.gateway import audit, budget

    audit.reset_for_testing()
    budget.reset_for_testing()
    yield
    audit.reset_for_testing()
    budget.reset_for_testing()


# ── the matrix is complete and drift-proof ────────────────────────────────────


def test_every_endpoint_is_classified() -> None:
    """An endpoint with no capability row has no declared authorization."""
    tree = ast.parse(_MODULE.read_text(encoding="utf-8"))
    endpoints = {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
        and any(
            isinstance(d, ast.Call)
            and isinstance(d.func, ast.Attribute)
            and isinstance(d.func.value, ast.Name)
            and d.func.value.id == "router"
            for d in node.decorator_list
        )
    }
    assert endpoints, "no endpoints found — the AST walk is not reading the module"
    unclassified = sorted(endpoints - set(policy.CAPABILITIES))
    assert not unclassified, f"endpoints with no capability row: {unclassified}"


# ── who may read it ───────────────────────────────────────────────────────────


@pytest.mark.parametrize("path", VIEW_PATHS)
def test_an_admin_may_read_the_page(path: str) -> None:
    assert _client("admin").get(path).status_code == 200


@pytest.mark.parametrize("path", VIEW_PATHS)
def test_a_superadmin_may_read_the_page(path: str) -> None:
    assert _client("superadmin", sub="op-super").get(path).status_code == 200


@pytest.mark.parametrize("path", VIEW_PATHS)
@pytest.mark.parametrize("role", ["starter", "user", "trader"])
def test_below_admin_is_refused(path: str, role: str) -> None:
    """The AI control plane starts at admin. Rank 2 does not reach it."""
    assert _client(role, sub="op-trader").get(path).status_code == 403


# ── an admin cannot see what a superadmin sees ────────────────────────────────


def test_an_admin_sees_only_their_own_spend() -> None:
    from ai.gateway import budget

    budget.charge("op-admin", 1.0)
    budget.charge("someone-else", 7.0)

    body = _client("admin").get("/api/ai-core/budget").json()

    assert body["scope"] == "self"
    assert body["operator"] == "op-admin"
    assert body["spent_usd"] == pytest.approx(1.0)
    assert "operators" not in body, "an admin was shown another operator's spend"
    assert "7" not in str(body.get("operators", "")), "another operator's spend leaked"


def test_a_superadmin_sees_every_operator() -> None:
    from ai.gateway import budget

    budget.charge("op-admin", 1.0)
    budget.charge("someone-else", 7.0)

    body = _client("superadmin", sub="op-super").get("/api/ai-core/budget").json()

    assert body["scope"] == "platform"
    assert body["operators"]["someone-else"] == pytest.approx(7.0)
    assert body["global_spent_usd"] == pytest.approx(8.0)


def test_an_admin_sees_only_their_own_calls() -> None:
    from ai.gateway import audit

    audit.record_call(
        operator="op-admin",
        role="reasoning",
        prompt="mine",
        attempts=[],
        served_by="anthropic",
        model="m",
        latency_ms=1.0,
        cost_usd=0.0,
        tokens_in=0,
        tokens_out=0,
    )
    audit.record_call(
        operator="someone-else",
        role="reasoning",
        prompt="theirs",
        attempts=[],
        served_by="anthropic",
        model="m",
        latency_ms=1.0,
        cost_usd=0.0,
        tokens_in=0,
        tokens_out=0,
    )

    body = _client("admin").get("/api/ai-core/calls").json()

    operators = {call["operator"] for call in body["calls"]}
    assert operators == {"op-admin"}, f"an admin read another operator's call history: {operators}"

    everything = _client("superadmin", sub="op-super").get("/api/ai-core/calls").json()
    assert {call["operator"] for call in everything["calls"]} == {"op-admin", "someone-else"}


def test_no_call_record_carries_a_prompt() -> None:
    from ai.gateway import audit

    audit.record_call(
        operator="op-admin",
        role="reasoning",
        prompt="our stop is 2381.40 on 12 lots",
        attempts=[],
        served_by="anthropic",
        model="m",
        latency_ms=1.0,
        cost_usd=0.0,
        tokens_in=0,
        tokens_out=0,
    )

    raw = _client("admin").get("/api/ai-core/calls").text

    assert "2381.40" not in raw, "the read surface returned prompt text"
    assert "prompt_sha256" in raw, "the digest that makes calls comparable is missing"


# ── the panels report live state, not a fixture ───────────────────────────────


def test_capabilities_tell_the_ui_what_this_role_may_do() -> None:
    """The UI gates on this; a decorative control is one the server would refuse."""
    admin = _client("admin").get("/api/ai-core/capabilities").json()
    superadmin = _client("superadmin", sub="op-super").get("/api/ai-core/capabilities").json()

    by_name = {row["name"]: row for row in admin["capabilities"]}
    assert by_name["execute_proposal"]["permitted"] is False
    assert by_name["execute_proposal"]["requires_2fa"] is True
    assert by_name["create_proposal"]["permitted"] is True

    super_by_name = {row["name"]: row for row in superadmin["capabilities"]}
    assert super_by_name["execute_proposal"]["permitted"] is True
    assert admin["role"] == "admin" and superadmin["role"] == "superadmin"


def test_the_chain_panel_reports_the_resolved_chain_and_reachability() -> None:
    body = _client("admin").get("/api/ai-core/chain").json()

    reasoning = next(role for role in body["roles"] if role["role"] == "reasoning")
    assert [leg["model"] for leg in reasoning["legs"]][:1] == ["claude-opus-5"]
    assert len(reasoning["legs"]) >= 2, "a chain with no second leg has no fallback"
    assert all("reachable" in leg for leg in reasoning["legs"])
    assert all("api_key" not in str(leg).lower() for leg in reasoning["legs"])


def test_the_chain_panel_never_returns_a_credential() -> None:
    """Reachability is a boolean. The key itself never leaves the process."""
    import os

    # A fabricated value, set only so the assertion below has something to
    # look for. pragma: allowlist secret
    os.environ["ANTHROPIC_API_KEY"] = "sk-should-never-appear"  # pragma: allowlist secret
    try:
        raw = _client("superadmin", sub="op-super").get("/api/ai-core/chain").text
    finally:
        os.environ.pop("ANTHROPIC_API_KEY", None)
    assert "sk-should-never-appear" not in raw


def test_the_cache_panel_reports_the_live_store() -> None:
    body = _client("admin").get("/api/ai-core/cache").json()
    assert {"enabled", "entries", "hits", "misses", "hit_rate"} <= set(body)


def test_the_summary_is_one_call_and_names_what_is_degraded() -> None:
    """The header must not need seven round trips to render."""
    body = _client("admin").get("/api/ai-core/summary").json()
    assert {"role", "reasoning_primary", "fallback_available", "providers_reachable", "calls_recorded"} <= set(body)


def test_the_evals_panel_is_honest_when_no_suite_has_run() -> None:
    """'No report' is a state the page must show, not one it may hide."""
    body = _client("admin").get("/api/ai-core/evals").json()
    assert body["report"] is None or "score" in body["report"]
    assert "promotion_allowed" in body


def test_the_router_is_registered_where_production_runs() -> None:
    """`api/superadmin/ai_operations.py` was registered only in
    `api/server.py::create_api_app`, which production never calls — so its
    endpoints existed and were unreachable. A read surface nobody can reach is
    the same defect in a new module."""
    registry = pathlib.Path("core/router_registry.py").read_text(encoding="utf-8")
    assert "from api.ai_core import router as ai_core_router" in registry
    assert "ai_core_router," in registry


def test_the_page_reads_no_endpoint_that_can_mutate() -> None:
    """Read-only by construction, asserted rather than intended."""
    from api.ai_core import router as ai_core_router

    methods = {method for route in ai_core_router.routes for method in getattr(route, "methods", set())}
    assert methods <= {"GET", "HEAD"}, f"the AI Core read surface exposes {sorted(methods - {'GET', 'HEAD'})}"

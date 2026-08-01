# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
tests/unit/test_nocode_plan_gate.py
===================================
The no-code Strategy Builder is a professional-tier feature.

The frontend nav has always advertised it that way (``navConfig``:
``plan: 'professional'``), and ``/templates`` was deliberately locked down with
the note that templates are "proprietary strategy IP". But every route in
``api/nocode.py`` depended on ``get_current_user`` alone, which checks
*authentication* and never *plan*. So the advertised gate existed on neither
side: any logged-in free-tier account could list the proprietary templates and
call ``POST /api/nocode/deploy``, which compiles a strategy, registers it and
then **auto-activates it against live trading**.

These tests pin the gate at the only boundary that counts — the server.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.auth import TokenPayload, get_current_user
from monetization.subscription import (
    SubscriptionStatus,
    SubscriptionTier,
    subscription_manager,
)

pytestmark = pytest.mark.unit


FREE_USER = "free-tier-user"
PRO_USER = "professional-user"


@pytest.fixture
def client(monkeypatch):
    """Mount the nocode router with a caller of the requested plan."""

    def _build(user_id: str, role: str = "user") -> TestClient:
        import api.nocode as nocode

        app = FastAPI()
        app.include_router(nocode.router)

        def _fake_user() -> TokenPayload:
            return TokenPayload(sub=user_id, role=role)

        # require_plan resolves get_current_user at import time via its own
        # Depends, so both must be overridden for the dependency graph.
        app.dependency_overrides[get_current_user] = _fake_user
        return TestClient(app, raise_server_exceptions=False)

    return _build


@pytest.fixture(autouse=True)
def _subscriptions():
    """Give PRO_USER an active professional subscription; FREE_USER none."""
    sub = subscription_manager.create_subscription(
        PRO_USER, SubscriptionTier.PROFESSIONAL, duration_days=30
    )
    # create_subscription opens a *paid* tier as PENDING — only activation marks
    # it ACTIVE, and require_plan reads `sub.is_active()`. Mirror what
    # monetization.activation.activate_paid_plan does on a successful payment.
    sub.status = SubscriptionStatus.ACTIVE
    yield
    subscription_manager._user_subscriptions.pop(PRO_USER, None)
    subscription_manager._subscriptions.pop(sub.subscription_id, None)


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("get", "/api/nocode/templates", None),
        ("post", "/api/nocode/deploy", {"template_id": "smc_breakout"}),
        ("post", "/api/nocode/validate", {"nodes": [], "edges": []}),
    ],
)
def test_free_tier_is_refused(client, method, path, body):
    """A free-tier account must not reach templates, deploy or validate."""
    c = client(FREE_USER)
    res = getattr(c, method)(path, json=body) if body is not None else c.get(path)

    assert res.status_code == 403, (
        f"{method.upper()} {path} let a free-tier user through with "
        f"{res.status_code} — this endpoint deploys live strategies"
    )
    detail = res.json()["detail"]
    assert detail["error"] == "PLAN_LIMIT_EXCEEDED"
    assert detail["required_plan"] == "professional"
    assert detail["current_plan"] == "free"


def test_deploy_is_refused_before_any_strategy_is_registered(client, monkeypatch):
    """The 403 must come from the dependency, not from inside the handler.

    A gate that runs after compilation would still have registered and
    activated the strategy.
    """
    registered: list[str] = []

    class _Registry:
        async def register_strategy(self, **kwargs):
            registered.append(kwargs.get("name", "?"))
            return "v1"

        async def activate_strategy(self, version_id):
            registered.append(f"activate:{version_id}")

    import strategies.dynamic_registry as reg

    monkeypatch.setattr(reg, "get_dynamic_registry", lambda: _Registry())

    res = client(FREE_USER).post("/api/nocode/deploy", json={"template_id": "smc_breakout"})

    assert res.status_code == 403
    assert registered == [], "strategy was registered/activated despite the plan gate"


def test_professional_tier_passes_the_gate(client):
    """A professional subscriber is not blocked by the plan check."""
    res = client(PRO_USER).get("/api/nocode/templates")
    assert res.status_code == 200
    assert "templates" in res.json()


def test_admin_bypasses_the_plan_gate(client):
    """Operators keep full feature access regardless of their own tier."""
    res = client("some-admin", role="admin").get("/api/nocode/templates")
    assert res.status_code == 200


def test_node_types_requires_authentication(client):
    """The node taxonomy is the same proprietary surface as /templates.

    It previously had no auth dependency at all, so it was fully public. It
    stays at authentication rather than the professional gate so the builder can
    render its palette for an upgrade preview.
    """
    import api.nocode as nocode

    app = FastAPI()
    app.include_router(nocode.router)
    anonymous = TestClient(app, raise_server_exceptions=False)

    assert anonymous.get("/api/nocode/node-types").status_code in (401, 403)

    # A free-tier *authenticated* user may still read it.
    assert client(FREE_USER).get("/api/nocode/node-types").status_code == 200


def test_deployed_strategy_is_attributed_to_the_deploying_user(client, monkeypatch):
    """author_id was the constant "nocode_builder".

    A live strategy could not be traced back to whoever activated it, which
    matters when the thing being activated trades real money.
    """
    seen: dict[str, object] = {}

    class _Registry:
        async def register_strategy(self, **kwargs):
            seen.update(kwargs)
            return "v1"

        async def activate_strategy(self, version_id):
            return None

    class _Builder:
        async def compile_template(self, **kwargs):
            return {"name": "compiled", "source_code": "pass"}

    import strategies.dynamic_registry as reg
    import nocode.builder as builder_mod

    monkeypatch.setattr(reg, "get_dynamic_registry", lambda: _Registry())
    monkeypatch.setattr(builder_mod, "NoCodeStrategyBuilder", _Builder)

    res = client(PRO_USER).post("/api/nocode/deploy", json={"template_id": "smc_breakout"})

    assert res.status_code == 200, res.text
    assert seen["author_id"] == PRO_USER

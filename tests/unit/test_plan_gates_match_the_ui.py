# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
tests/unit/test_plan_gates_match_the_ui.py
==========================================
F4-01b — the subscription gate must exist on the side that counts.

``SubscriptionGate`` is a React component and ``PLAN_FEATURES`` is a TypeScript
object. Neither is an authorization boundary: anyone with devtools can set the
store's plan, and nothing stops a direct call with a valid free-tier token. The
gate is real only where the server enforces it.

This gap was already found once, for the no-code Strategy Builder, and the note
left behind says it exactly:

    "every route in api/nocode.py depended on get_current_user alone, which
     checks *authentication* and never *plan*. So the advertised gate existed
     on neither side."
                            — tests/unit/test_nocode_plan_gate.py

``api/nocode.py`` was fixed. The same shape survived in six more routers, all
advertised in ``frontend/src/lib/subscription.ts`` as paid features and all
depending on ``get_current_user`` alone:

    /api/copy-trading/*             copy-trading   professional
    /api/custom-indicators/*        indicators     professional
    /api/risk/prop-firm/*           prop-firm      professional
    /api/accounts/sub-accounts/*    sub-accounts   elite
    /api/accounts/teams/*           teams          enterprise
    /api/alerts/*                   alerts         starter
    /api/risk/calculator/*          risk-calculator starter

A free-tier account could reach every one of them.

Deliberately **not** gated, and worth stating so the omissions read as decisions:

  * ``/api/custom-indicators/builtin`` — a list of standard indicator definitions, no
    user data and nothing proprietary. It has no auth dependency at all today
    and that is left alone.
  * ``/api/risk/live-price/{symbol}`` — a mid price, not the paid feature. The
    sizing arithmetic runs in the browser; what a subscription buys is the saved
    calculation history. Gating a quote would protect nothing and would break
    the entry auto-fill. Pinned open below.
  * ``/api/billing/*`` — mostly open, on purpose: billing is *how a user
    upgrades*, so gating ``/plans``, ``/subscription``, ``/stripe/*``,
    ``/payments/*`` or ``/payment-methods`` would lock a free account out of the
    page that sells them the plan. Pinned open below. Two groups within it are
    gated: ``/elite/*`` at elite (account manager, support tickets, custom dev —
    each labelled "(Elite)" in its own summary and previously reachable by any
    authenticated free account) and ``/balance`` + ``/transactions`` at starter,
    which are the ``wallet`` feature itself.
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

FREE_USER = "free-tier-user-f4"
ELITE_USER = "elite-user-f4"


@pytest.fixture(autouse=True)
def _subscriptions():
    """FREE_USER has no subscription; ELITE_USER has an active elite one."""
    sub = subscription_manager.create_subscription(ELITE_USER, SubscriptionTier.ELITE, duration_days=30)
    # create_subscription opens a paid tier PENDING; require_plan reads
    # is_active(). Mirror what activation.activate_paid_plan does on payment.
    sub.status = SubscriptionStatus.ACTIVE
    yield
    subscription_manager._user_subscriptions.pop(ELITE_USER, None)
    subscription_manager._subscriptions.pop(sub.subscription_id, None)


def _client(module_name: str, user_id: str, role: str = "user") -> TestClient:
    import importlib

    mod = importlib.import_module(f"api.{module_name}")
    app = FastAPI()
    app.include_router(mod.router)

    def _fake_user() -> TokenPayload:
        return TokenPayload(sub=user_id, role=role)

    app.dependency_overrides[get_current_user] = _fake_user
    return TestClient(app, raise_server_exceptions=False)


# (module, method, path, body, advertised plan)
GATED = [
    ("copy_trading", "get", "/api/copy-trading/my-copies", None, "professional"),
    ("copy_trading", "post", "/api/copy-trading/copies/c1/pause", None, "professional"),
    ("custom_indicators", "get", "/api/custom-indicators", None, "professional"),
    ("custom_indicators", "post", "/api/custom-indicators", {"name": "x", "formula": "close"}, "professional"),
    ("accounts", "get", "/api/accounts/sub-accounts", None, "elite"),
    ("accounts", "post", "/api/accounts/sub-accounts", {"name": "x"}, "elite"),
    ("alerts", "get", "/api/alerts/", None, "starter"),
    ("alerts", "get", "/api/alerts/active", None, "starter"),
    ("prop_firm", "get", "/api/risk/prop-firm/history", None, "professional"),
    ("prop_firm", "get", "/api/risk/prop-firm/challenges", None, "professional"),
    ("prop_firm", "get", "/api/risk/prop-firm/daily-stats", None, "professional"),
    ("risk_calculator", "get", "/api/risk/calculator/history", None, "starter"),
    ("risk_calculator", "post", "/api/risk/calculator/history", {"symbol": "XAUUSD"}, "starter"),
    ("billing", "get", "/api/billing/balance", None, "starter"),
    ("billing", "get", "/api/billing/transactions", None, "starter"),
    ("billing", "get", "/api/billing/elite/account-manager", None, "elite"),
    ("billing", "get", "/api/billing/elite/support/tickets", None, "elite"),
]

# Billing routes that must stay reachable on any plan: this router is *how a
# user upgrades*, and gating it would lock a free account out of the page that
# sells them the plan.
BILLING_OPEN = [
    ("get", "/api/billing/plans"),
    ("get", "/api/billing/subscription"),
    ("get", "/api/billing/payment-methods"),
    ("get", "/api/billing/stripe/config"),
]


@pytest.mark.parametrize(("method", "path"), BILLING_OPEN)
def test_the_upgrade_path_stays_open_to_a_free_account(method, path):
    c = _client("billing", FREE_USER)
    res = c.request(method, path)
    if res.status_code == 403:
        detail = res.json().get("detail")
        err = detail.get("error") if isinstance(detail, dict) else None
        assert err != "PLAN_LIMIT_EXCEEDED", (
            f"{method.upper()} {path} is gated behind a plan, but it is part of "
            f"how a user buys a plan — this locks a free account out of "
            f"upgrading (F4-01b)."
        )


@pytest.mark.parametrize(("module", "method", "path", "body", "plan"), GATED)
def test_a_free_account_is_refused(module, method, path, body, plan):
    c = _client(module, FREE_USER)
    res = c.request(method, path, json=body) if body is not None else c.request(method, path)

    assert res.status_code == 403, (
        f"{method.upper()} {path} let a free-tier account through with "
        f"{res.status_code}. The UI advertises this as a {plan} feature and "
        f"gates it in React only — which is not a gate (F4-01b)."
    )
    detail = res.json()["detail"]
    assert detail["error"] == "PLAN_LIMIT_EXCEEDED"
    assert detail["required_plan"] == plan
    assert detail["current_plan"] == "free"


@pytest.mark.parametrize(("module", "method", "path", "body", "plan"), GATED)
def test_a_paid_account_is_not_refused_by_the_plan_gate(module, method, path, body, plan):
    """The gate must let a sufficient plan past.

    A gate that refuses everyone is not a fix. This asserts only that the
    failure is not PLAN_LIMIT_EXCEEDED — the handler is free to 404 on a
    made-up copy id, and that is a different thing entirely.
    """
    c = _client(module, ELITE_USER)
    res = c.request(method, path, json=body) if body is not None else c.request(method, path)

    if res.status_code == 403:
        detail = res.json().get("detail")
        err = detail.get("error") if isinstance(detail, dict) else None
        assert err != "PLAN_LIMIT_EXCEEDED", (
            f"{method.upper()} {path} refused an ELITE account on plan grounds "
            f"(required {plan}) — the gate is set above the advertised tier."
        )


def test_admin_bypasses_the_plan_gate():
    """Admins keep full access regardless of tier — the documented behaviour of
    require_plan, and the thing that would silently break support workflows if
    a gate were added without it."""
    c = _client("copy_trading", "admin-user-f4", role="admin")
    res = c.get("/api/copy-trading/my-copies")
    assert res.status_code != 403 or res.json().get("detail", {}).get("error") != "PLAN_LIMIT_EXCEEDED"


def test_live_price_stays_open_to_any_authenticated_user():
    """Not the paid feature — see the module docstring. Pinned so the gate on
    the calculator history does not creep onto the quote beside it."""
    c = _client("risk_calculator", FREE_USER)
    res = c.get("/api/risk/live-price/XAU_USD")
    assert res.status_code != 403 or res.json().get("detail", {}).get("error") != "PLAN_LIMIT_EXCEEDED"


def test_builtin_indicators_stay_open():
    """Not a paid feature: standard indicator definitions, no user data. Pinned
    so the gate above does not creep onto it."""
    c = _client("custom_indicators", FREE_USER)
    res = c.get("/api/custom-indicators/builtin")
    assert res.status_code != 403, (
        "the built-in indicator list is not the 'indicators' paid feature — "
        "gating it locks free users out of the chart's standard toolset"
    )

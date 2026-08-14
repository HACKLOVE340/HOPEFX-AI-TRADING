# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
tests/unit/test_billing_routes_are_registered.py
================================================
The Wallet page showed two red 404s, and I caused it.

``scripts/bootstrap_env.py`` forces ``FEATURE_BILLING_SUBSCRIPTION=false`` so a
fresh deployment does not require Stripe credentials — billing configurable
after deploy, which is what was asked for. But ``core/router_registry.py`` used
that flag to gate registration of the **entire** billing router::

    if feature_flags.BILLING_SUBSCRIPTION:
        _include_router_deduped(app, billing_router)

So all 31 endpoints disappeared, and the Wallet page — which calls
``/api/billing/balance`` and ``/api/billing/transactions`` on every load —
rendered::

    ✕ No route for GET /api/billing/balance
    ✕ No route for GET /api/billing/transactions

Two things make this a design defect rather than a bad flag value:

1. **The flag's blast radius was 31× its stated scope.** Its own description in
   ``config/feature_flags.py`` says it governs "GET /api/billing/subscription
   endpoint returning the authenticated user's tier" — one endpoint.

2. **Neither setting was correct.** Off: the Wallet page 404s. On: production
   startup *hard-fails* without ``STRIPE_WEBHOOK_SECRET``
   (``config/startup_validator.py`` appends to ``errors``). There was no value
   of this flag that produced "billing optional, app runs, wallet works".

The platform's own diagnostics engine reported the same thing from the other
side, at CRITICAL: *"route_families — 1 endpoint famil(y/ies) are not
registered… Every page under a missing prefix will 404."*

The router is now always registered. Endpoints that move money answer **503**
("exists, not configured") rather than **404** ("does not exist"), which is both
true and actionable. The Stripe webhook keeps its own fail-closed check.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit


# ── The read paths need no payment provider ──────────────────────────────────


def test_balance_and_transactions_are_not_payment_endpoints():
    """Pins why they must never be gated on payments.

    /balance reads the broker's account; /transactions documents that it
    "returns an empty list when no payment provider is configured". Both are
    built for a deployment that has not set up billing.
    """
    import inspect

    from api import billing

    balance_src = inspect.getsource(billing.get_balance)
    assert "broker" in balance_src, "/balance no longer reads the broker account"

    tx_src = inspect.getsource(billing.get_transactions)
    assert "empty list when no payment provider is configured" in tx_src


@pytest.mark.parametrize("endpoint", ["get_balance", "get_transactions"])
def test_the_read_paths_do_not_carry_the_payment_guard(endpoint):
    """A 503 on the Wallet page would be no better than the 404 it replaced."""
    from api import billing

    route = next(r for r in billing.router.routes if r.endpoint is getattr(billing, endpoint))
    dep_names = [getattr(d.call, "__name__", "") for d in route.dependant.dependencies]
    assert "require_payments_configured" not in dep_names


# ── The money paths do ───────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "path",
    [
        "/api/billing/stripe/payment-intent",
        "/api/billing/stripe/config",
        "/api/billing/payments/flutterwave/init",
        "/api/billing/payments/flutterwave/verify",
        "/api/billing/payments/flutterwave/status",
        "/api/billing/crypto/rates",
        "/api/billing/crypto/order",
    ],
)
def test_money_moving_endpoints_are_guarded(path):
    from api import billing

    route = next(r for r in billing.router.routes if getattr(r, "path", None) == path)
    dep_names = [getattr(d.call, "__name__", "") for d in route.dependant.dependencies]
    assert "require_payments_configured" in dep_names, f"{path} is unguarded"


def test_the_guard_reports_503_not_404(monkeypatch):
    """404 says the feature does not exist. 503 says it exists and is not
    configured — which is the truth, and tells the operator what to do."""
    from fastapi import HTTPException

    from api import billing

    for var in ("STRIPE_SECRET_KEY", "FLUTTERWAVE_SECRET_KEY", "CRYPTO_WEBHOOK_SECRET"):
        monkeypatch.delenv(var, raising=False)

    with pytest.raises(HTTPException) as exc:
        billing.require_payments_configured()

    assert exc.value.status_code == 503
    detail = str(exc.value.detail)
    assert "STRIPE_SECRET_KEY" in detail, "the operator is not told what to set"
    assert "balance" in detail, "must say the read paths are unaffected"


@pytest.mark.parametrize("var", ["STRIPE_SECRET_KEY", "FLUTTERWAVE_SECRET_KEY", "CRYPTO_WEBHOOK_SECRET"])
def test_any_configured_provider_opens_the_gate(monkeypatch, var):
    from api import billing

    for v in ("STRIPE_SECRET_KEY", "FLUTTERWAVE_SECRET_KEY", "CRYPTO_WEBHOOK_SECRET"):
        monkeypatch.delenv(v, raising=False)
    monkeypatch.setenv(var, "configured")

    assert billing.payments_configured() is True
    billing.require_payments_configured()  # must not raise


# ── Registration no longer depends on the flag ───────────────────────────────


def test_the_router_is_registered_with_the_flag_off():
    """The regression itself."""
    import inspect

    import core.router_registry as reg

    src = inspect.getsource(reg)
    marker = "from api.billing import router as billing_router"
    assert marker in src
    before = src[: src.index(marker)]
    # The last conditional before the import must not be the billing flag.
    assert "if feature_flags.BILLING_SUBSCRIPTION:" not in before.rsplit("\n\n", 1)[-1], (
        "billing registration is conditional again — with the flag off, every page under /api/billing will 404"
    )


def test_the_flag_still_governs_something_visible():
    """Turning the flag off must remain meaningful, not silently ignored."""
    import inspect

    import core.router_registry as reg

    src = inspect.getsource(reg)
    assert "FEATURE_BILLING_SUBSCRIPTION is off" in src, "the operator gets no signal that billing is disabled"


def test_the_webhook_keeps_its_fail_closed_check():
    """Registering the router must not expose an unsigned webhook.

    verify_webhook raises RuntimeError in production when STRIPE_WEBHOOK_SECRET
    is absent, so an unsigned event is never accepted. That check is the actual
    security control — the route being hidden was never what protected it.
    """
    import inspect

    from monetization.stripe_live import StripeProductionClient

    src = inspect.getsource(StripeProductionClient.verify_webhook)
    assert "is_production" in src
    assert "raise RuntimeError" in src
    assert "STRIPE_WEBHOOK_SECRET" in src


def test_the_stripe_client_survives_being_unconfigured():
    """Registration is only safe because the client does not raise on import or
    construction when no key is set."""
    import os

    from monetization.stripe_live import StripeProductionClient

    saved = os.environ.pop("STRIPE_SECRET_KEY", None)
    try:
        client = StripeProductionClient()
        assert client.mode == "simulation"
    finally:
        if saved is not None:
            os.environ["STRIPE_SECRET_KEY"] = saved


# ── The frontend calls these unconditionally ─────────────────────────────────


def test_the_frontend_calls_balance_and_transactions_without_a_feature_check():
    """Pins the other half of the contract. If the UI ever starts gating these
    calls, the backend guarantee above can be relaxed — until then it cannot."""
    import pathlib

    src = (pathlib.Path(__file__).resolve().parents[2] / "frontend/src/hooks/useApi.ts").read_text()
    assert "api.get('/billing/balance')" in src
    assert "api.get('/billing/transactions'" in src

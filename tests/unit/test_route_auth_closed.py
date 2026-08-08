"""Regression tests: auth must fail closed, and order data must not be public.

Round 3 audit findings S6-01, S6-02 and S6-03 (docs/HARDENING_BACKLOG.md).

S6-01 — ``api/dynamic_strategies.py`` wrapped its auth dependency in
``try/except ImportError`` and returned ``None`` on failure. Used as a default
argument, that is evaluated **once at import**: a failed ``api.auth`` import
(circular import, missing transitive dependency, syntax error) would mount all
seven endpoints with no authentication for the process lifetime — including
``POST /register``, which accepts and compiles **arbitrary Python source**. An
auth module that fails to import should take the router down loudly, not open
it quietly.

S6-02 — ``api/advanced_orders.py`` declared its router with no ``dependencies``
and three routes with no auth and no ownership check. ``GET /active`` returned
**every** user's live stop-loss, take-profit and trailing levels, and
``GET /{order_id}`` allowed enumeration. On a trading platform those levels are
the most sensitive data in the system: an observer who knows where stops sit
knows where forced liquidations will occur. No global middleware compensates —
``SubscriptionPaywallMiddleware`` passes unauthenticated requests through by
design, leaving 401s to each route's own dependency.

S6-03 — the Onfido and Sumsub webhook HMAC keys defaulted to the empty string,
so unset configuration made signatures *publicly computable* rather than
disabling the webhook.
"""

import inspect

import pytest


@pytest.mark.unit
class TestAuthDependencyFailsClosed:
    def test_dynamic_strategies_auth_helper_does_not_swallow_importerror(self):
        """A failed auth import must not silently remove authentication (S6-01)."""
        from api import dynamic_strategies as mod

        src = inspect.getsource(mod)
        assert "except ImportError:\n        return None" not in src, (
            "The auth helpers in api/dynamic_strategies.py must not return None "
            "on ImportError — as default arguments evaluated once at import, "
            "that mounts every endpoint unauthenticated for the process "
            "lifetime, including one that compiles arbitrary Python (S6-01)."
        )

    def test_dynamic_strategies_router_is_gated(self):
        """Router-level auth so a new route cannot be added without it."""
        from api.dynamic_strategies import router

        assert router.dependencies, (
            "api/dynamic_strategies.py registers and activates trading "
            "strategies from submitted source; its router must require "
            "authentication (S6-01)."
        )

    def test_every_dynamic_strategy_route_is_protected(self):
        """No route may be reachable unauthenticated, router- or route-level."""
        from api.dynamic_strategies import router

        for route in router.routes:
            dependant = getattr(route, "dependant", None)
            if dependant is None:
                continue
            assert dependant.dependencies or router.dependencies, f"{route.path} has no auth dependency (S6-01)."


@pytest.mark.unit
class TestAdvancedOrdersRequireAuth:
    def test_router_declares_an_auth_dependency(self):
        """The router must be gated; there is no global auth middleware (S6-02)."""
        from api.advanced_orders import router

        assert router.dependencies, (
            "api/advanced_orders.py exposes every user's stop-loss and "
            "take-profit levels; its router must require authentication (S6-02)."
        )

    def test_every_route_is_protected(self):
        """No route in this module may be reachable unauthenticated."""
        from api.advanced_orders import router

        for route in router.routes:
            dependant = getattr(route, "dependant", None)
            if dependant is None:
                continue
            assert dependant.dependencies or router.dependencies, f"{route.path} is unauthenticated (S6-02)."


@pytest.mark.unit
class TestWebhookSecretsAreRequired:
    def test_empty_secret_rejects_every_signature(self):
        """An unset secret must disable the webhook, not make it signable (S6-03)."""
        import hashlib
        import hmac

        from compliance.kyc_provider import OnfidoProvider

        provider = OnfidoProvider.__new__(OnfidoProvider)
        payload = b'{"payload":{"resource_type":"check","action":"check.completed"}}'
        # What an attacker would compute when the secret is unset.
        forged = hmac.new(b"", payload, hashlib.sha256).hexdigest()

        import os

        old = os.environ.pop("ONFIDO_WEBHOOK_TOKEN", None)
        try:
            assert provider.verify_webhook(payload, forged) is False, (
                "HMAC keyed with an empty string is a well-defined function, so "
                "an unset secret makes the webhook publicly signable rather than "
                "disabled (S6-03)."
            )
        finally:
            if old is not None:
                os.environ["ONFIDO_WEBHOOK_TOKEN"] = old

    def test_sumsub_empty_secret_rejects(self):
        """Same for Sumsub."""
        import hashlib
        import hmac

        from compliance.kyc_provider import SumsubProvider

        provider = SumsubProvider.__new__(SumsubProvider)
        provider._secret = ""
        payload = b'{"applicantId":"abc","reviewResult":{"reviewAnswer":"GREEN"}}'
        forged = hmac.new(b"", payload, hashlib.sha256).hexdigest()

        assert provider.verify_webhook(payload, forged) is False

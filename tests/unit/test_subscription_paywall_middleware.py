# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
tests/unit/test_subscription_paywall_middleware.py
==================================================
core.middleware.SubscriptionPaywallMiddleware.

The paywall is enforced in middleware rather than as a per-route dependency so
that a newly added endpoint is gated the moment it exists. These tests pin the
behaviour that makes that safe: off by default, operators exempt, allowlist
honoured, and the SPA shell always served so the browser can render the
upgrade wall instead of receiving raw JSON.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.middleware import SubscriptionPaywallMiddleware


@pytest.fixture
def client(monkeypatch):
    def _build(enabled: bool):
        monkeypatch.setenv("HOPEFX_PAYWALL_ENABLED", "true" if enabled else "false")
        app = FastAPI()
        app.add_middleware(SubscriptionPaywallMiddleware)

        @app.get("/api/trading/positions")
        async def _positions():
            return {"ok": True}

        @app.get("/api/pricing/plans")
        async def _plans():
            return {"ok": True}

        @app.get("/dashboard")
        async def _spa():
            return {"ok": True}

        return TestClient(app)

    return _build


def _auth(monkeypatch, role: str, active_sub: bool):
    """Stub token decoding and the subscription lookup."""

    class _Payload:
        sub = "user-123"

    _Payload.role = role

    import api.auth as _auth_mod

    monkeypatch.setattr(_auth_mod, "_decode_token", lambda _t: _Payload(), raising=False)

    class _Tier:
        value = "starter" if active_sub else "free"

    class _Sub:
        tier = _Tier()

        def is_active(self):
            return active_sub

    import monetization.subscription as _sub_mod

    monkeypatch.setattr(
        _sub_mod.subscription_manager, "get_user_subscription", lambda _uid: _Sub(), raising=False
    )


HDR = {"Authorization": "Bearer tok"}


def test_disabled_by_default_lets_everything_through(client, monkeypatch):
    _auth(monkeypatch, "user", active_sub=False)
    assert client(False).get("/api/trading/positions", headers=HDR).status_code == 200


def test_enabled_blocks_user_without_subscription(client, monkeypatch):
    _auth(monkeypatch, "user", active_sub=False)
    resp = client(True).get("/api/trading/positions", headers=HDR)
    assert resp.status_code == 402
    body = resp.json()
    assert body["error"] == "SUBSCRIPTION_REQUIRED"
    assert body["checkout_url"] == "/pricing"


def test_enabled_allows_user_with_active_subscription(client, monkeypatch):
    _auth(monkeypatch, "user", active_sub=True)
    assert client(True).get("/api/trading/positions", headers=HDR).status_code == 200


@pytest.mark.parametrize("role", ["admin", "superadmin"])
def test_operators_are_never_paywalled(client, monkeypatch, role):
    """Also the safety valve — an operator can always get in to switch it off."""
    _auth(monkeypatch, role, active_sub=False)
    assert client(True).get("/api/trading/positions", headers=HDR).status_code == 200


def test_allowlisted_api_routes_stay_reachable(client, monkeypatch):
    """A user who cannot pay for the app must still be able to read the plans."""
    _auth(monkeypatch, "user", active_sub=False)
    assert client(True).get("/api/pricing/plans", headers=HDR).status_code == 200


def test_spa_shell_is_never_gated(client, monkeypatch):
    """Non-/api paths must render, or the browser gets JSON instead of the wall."""
    _auth(monkeypatch, "user", active_sub=False)
    assert client(True).get("/dashboard", headers=HDR).status_code == 200


def test_unauthenticated_request_is_left_to_the_route(client, monkeypatch):
    """401 is the route's job — the paywall must not turn it into a 402."""
    _auth(monkeypatch, "user", active_sub=False)
    assert client(True).get("/api/trading/positions").status_code == 200

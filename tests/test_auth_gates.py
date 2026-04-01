# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
tests/test_auth_gates.py
========================
Verify that admin, brain, and alert endpoints reject unauthenticated
and under-privileged requests with the correct HTTP status codes.

These tests use FastAPI's TestClient and a minimal in-process app so
they run without a database, Redis, or broker.
"""

from __future__ import annotations

import os
import time
from collections.abc import Generator

import jwt
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

# ── Minimal secret for test tokens ───────────────────────────────────────────
# Force-set (not setdefault) so this module's tokens always verify correctly
# regardless of which other test module ran first and set a different secret.
_SECRET = "test-secret-key-that-is-long-enough-for-hs256-validation"
os.environ["SECURITY_JWT_SECRET"] = _SECRET


def _make_token(role: str = "user", sub: str = "test-user") -> str:
    payload = {
        "sub": sub,
        "role": role,
        "exp": int(time.time()) + 3600,
        "iat": int(time.time()),
        "type": "access",
    }
    return jwt.encode(payload, _SECRET, algorithm="HS256")


# ── Build a minimal test app with the three routers ──────────────────────────


@pytest.fixture(scope="module")
def client() -> Generator[TestClient, None, None]:
    # Pin the JWT secret for the entire module so tokens signed with _SECRET
    # verify correctly even when other test modules set a different secret.
    original_secret = os.environ.get("SECURITY_JWT_SECRET")
    os.environ["SECURITY_JWT_SECRET"] = _SECRET

    app = FastAPI()

    from api.admin import router as admin_router
    from api.brain import router as brain_router
    from api.alerts import router as alerts_router

    app.include_router(admin_router)
    app.include_router(brain_router)
    app.include_router(alerts_router)

    with TestClient(app, raise_server_exceptions=False) as c:
        yield c

    # Restore original value so we don't pollute other modules
    if original_secret is not None:
        os.environ["SECURITY_JWT_SECRET"] = original_secret
    else:
        os.environ.pop("SECURITY_JWT_SECRET", None)


# ── Helpers ───────────────────────────────────────────────────────────────────


def auth(role: str) -> dict:
    return {"Authorization": f"Bearer {_make_token(role)}"}


# ═══════════════════════════════════════════════════════════════════════════════
# Admin routes — must reject unauthenticated and non-admin callers
# ═══════════════════════════════════════════════════════════════════════════════

ADMIN_GET_ROUTES = [
    "/api/admin/system-info",
    "/api/admin/settings",
    "/api/admin/activity",
    "/api/admin/dashboard-data",
    "/api/admin/system-metrics",
    "/api/admin/logs",
    "/api/admin/",
    "/api/admin/kyc/pending",
]

ADMIN_POST_ROUTES = [
    "/api/admin/pause",
    "/api/admin/resume",
]


@pytest.mark.parametrize("path", ADMIN_GET_ROUTES)
def test_admin_get_rejects_unauthenticated(client: TestClient, path: str):
    """GET admin routes must return 401 without a token."""
    resp = client.get(path)
    assert resp.status_code == 401, f"{path} returned {resp.status_code}, expected 401"


@pytest.mark.parametrize("path", ADMIN_GET_ROUTES)
def test_admin_get_rejects_user_role(client: TestClient, path: str):
    """GET admin routes must return 403 for role='user'."""
    resp = client.get(path, headers=auth("user"))
    assert resp.status_code == 403, f"{path} returned {resp.status_code}, expected 403"


@pytest.mark.parametrize("path", ADMIN_GET_ROUTES)
def test_admin_get_rejects_trader_role(client: TestClient, path: str):
    """GET admin routes must return 403 for role='trader'."""
    resp = client.get(path, headers=auth("trader"))
    assert resp.status_code == 403, f"{path} returned {resp.status_code}, expected 403"


@pytest.mark.parametrize("path", ADMIN_POST_ROUTES)
def test_admin_post_rejects_unauthenticated(client: TestClient, path: str):
    """POST admin routes must return 401 without a token."""
    resp = client.post(path)
    assert resp.status_code == 401, f"{path} returned {resp.status_code}, expected 401"


@pytest.mark.parametrize("path", ADMIN_POST_ROUTES)
def test_admin_post_rejects_trader_role(client: TestClient, path: str):
    """POST admin routes must return 403 for role='trader'."""
    resp = client.post(path, headers=auth("trader"))
    assert resp.status_code == 403, f"{path} returned {resp.status_code}, expected 403"


def test_admin_settings_post_rejects_unauthenticated(client: TestClient):
    resp = client.post("/api/admin/settings", json={"max_risk_per_trade": 1.0})
    assert resp.status_code == 401


def test_admin_settings_post_rejects_user_role(client: TestClient):
    resp = client.post(
        "/api/admin/settings",
        json={"max_risk_per_trade": 1.0},
        headers=auth("user"),
    )
    assert resp.status_code == 403


# ═══════════════════════════════════════════════════════════════════════════════
# Brain routes — must reject unauthenticated and non-admin callers
# ═══════════════════════════════════════════════════════════════════════════════


def test_generate_strategy_rejects_unauthenticated(client: TestClient):
    resp = client.post(
        "/api/brain/generate-strategy",
        json={"prompt": "RSI crossover strategy"},
    )
    assert resp.status_code == 401


def test_generate_strategy_rejects_user_role(client: TestClient):
    resp = client.post(
        "/api/brain/generate-strategy",
        json={"prompt": "RSI crossover strategy"},
        headers=auth("user"),
    )
    assert resp.status_code == 403


def test_generate_strategy_rejects_trader_role(client: TestClient):
    resp = client.post(
        "/api/brain/generate-strategy",
        json={"prompt": "RSI crossover strategy"},
        headers=auth("trader"),
    )
    assert resp.status_code == 403


def test_generate_strategy_allows_admin(client: TestClient):
    """Admin token must reach the handler (200 or 422 on bad body, never 401/403)."""
    resp = client.post(
        "/api/brain/generate-strategy",
        json={"prompt": "RSI crossover strategy"},
        headers=auth("admin"),
    )
    assert resp.status_code not in (
        401,
        403,
    ), f"Admin was rejected with {resp.status_code}"


def test_deploy_strategy_rejects_unauthenticated(client: TestClient):
    resp = client.post(
        "/api/brain/deploy-strategy",
        json={"strategy_name": "Test", "strategy_code": "pass"},
    )
    assert resp.status_code == 401


def test_deploy_strategy_rejects_trader_role(client: TestClient):
    resp = client.post(
        "/api/brain/deploy-strategy",
        json={"strategy_name": "Test", "strategy_code": "pass"},
        headers=auth("trader"),
    )
    assert resp.status_code == 403


# ═══════════════════════════════════════════════════════════════════════════════
# Alert routes — must reject unauthenticated callers (any authenticated user OK)
# ═══════════════════════════════════════════════════════════════════════════════

ALERT_GET_ROUTES = [
    "/api/alerts/",
    "/api/alerts/active",
    "/api/alerts/history/triggers",
    "/api/alerts/some-alert-id",
]

ALERT_POST_ROUTES = [
    "/api/alerts/some-alert-id/pause",
    "/api/alerts/some-alert-id/resume",
]


@pytest.mark.parametrize("path", ALERT_GET_ROUTES)
def test_alert_get_rejects_unauthenticated(client: TestClient, path: str):
    """Alert GET routes must return 401 without a token."""
    resp = client.get(path)
    assert resp.status_code == 401, f"{path} returned {resp.status_code}, expected 401"


@pytest.mark.parametrize("path", ALERT_POST_ROUTES)
def test_alert_post_rejects_unauthenticated(client: TestClient, path: str):
    """Alert POST routes must return 401 without a token."""
    resp = client.post(path)
    assert resp.status_code == 401, f"{path} returned {resp.status_code}, expected 401"


def test_alert_create_rejects_unauthenticated(client: TestClient):
    resp = client.post(
        "/api/alerts/",
        json={
            "name": "Gold spike",
            "symbol": "XAUUSD",
            "conditions": [{"type": "price_above", "threshold": 2500.0}],
        },
    )
    assert resp.status_code == 401


def test_alert_delete_rejects_unauthenticated(client: TestClient):
    resp = client.delete("/api/alerts/some-alert-id")
    assert resp.status_code == 401

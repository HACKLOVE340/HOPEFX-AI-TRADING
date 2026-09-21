# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# AGPL-3.0 — Share all modifications
"""
tests/unit/test_custom_indicators_api.py
=========================================
Unit tests for api/custom_indicators.py.

Covers:
  - GET  /api/custom-indicators              — list indicators
  - POST /api/custom-indicators              — create indicator
  - GET  /api/custom-indicators/{id}         — get indicator
  - PUT  /api/custom-indicators/{id}         — replace indicator (full update)
  - PATCH /api/custom-indicators/{id}        — partial update
  - DELETE /api/custom-indicators/{id}       — delete indicator
  - POST /api/custom-indicators/{id}/test    — test indicator
  - POST /api/custom-indicators/{id}/deploy  — deploy indicator
  - GET  /api/custom-indicators/builtin      — list built-in indicators

The prefix was `/api/indicators` until S-32. These tests mount this router
*alone*, which is exactly why they never noticed that `api/advanced_trading.py`
also owned that prefix in the real app and shadowed half of these endpoints —
mounting one router in isolation cannot see a collision with another. The
registry-level guard for that lives in
tests/unit/test_router_prefix_ownership.py.
"""

from __future__ import annotations

import os
from typing import Any
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("SECURITY_JWT_SECRET", "unit-test-indicators-secret-key-32chars!!")

from api.auth import TokenPayload, get_current_user
from api.custom_indicators import router as indicators_router
from monetization.subscription import (
    SubscriptionStatus,
    SubscriptionTier,
    subscription_manager,
)

# Custom indicators are a professional-tier feature and the router now enforces
# that server-side (F4-01b) — it previously depended on `get_current_user`
# alone, which checks authentication and never plan. These tests exercise
# handler behaviour (CRUD, 404s, deploy), not the gate, so the caller is given
# the plan the feature is advertised at. The gate itself is covered by
# tests/unit/test_plan_gates_match_the_ui.py.
_INDICATORS_USER = "test-indicators-user"


@pytest.fixture(autouse=True)
def _professional_subscription():
    sub = subscription_manager.create_subscription(_INDICATORS_USER, SubscriptionTier.PROFESSIONAL, duration_days=30)
    # create_subscription opens a paid tier PENDING; require_plan reads
    # is_active(). Mirror activation.activate_paid_plan on a successful payment.
    sub.status = SubscriptionStatus.ACTIVE
    yield
    subscription_manager._user_subscriptions.pop(_INDICATORS_USER, None)
    subscription_manager._subscriptions.pop(sub.subscription_id, None)


def _make_app() -> tuple[FastAPI, dict[str, Any]]:
    """Create an app with an in-memory db_store mock."""
    app = FastAPI()
    _user = TokenPayload(sub=_INDICATORS_USER, role="trader")
    app.dependency_overrides[get_current_user] = lambda: _user
    app.include_router(indicators_router)
    # In-memory store shared across requests within one test
    store: dict[str, Any] = {}
    return app, store


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture()
def store() -> dict[str, Any]:
    return {}


@pytest.fixture()
def client(store: dict[str, Any]) -> TestClient:
    app = FastAPI()
    _user = TokenPayload(sub=_INDICATORS_USER, role="trader")
    app.dependency_overrides[get_current_user] = lambda: _user
    app.include_router(indicators_router)

    def _db_get(key: str) -> Any:
        return store.get(key)

    def _db_set(key: str, value: Any, **_kwargs) -> None:
        store[key] = value

    # Patch db_store in the custom_indicators module
    with (
        patch("api.custom_indicators.db_get", side_effect=_db_get),
        patch("api.custom_indicators.db_set", side_effect=_db_set),
    ):
        yield TestClient(app, raise_server_exceptions=True)


@pytest.fixture()
def indicator_id(client: TestClient) -> str:
    """Create one indicator and return its ID."""
    resp = client.post(
        "/api/custom-indicators",
        json={
            "name": "My SMA",
            "type": "sma",
            "params": {"period": 20},
            "description": "20-period SMA",
            "color": "#ff0000",
        },
    )
    assert resp.status_code == 200
    return resp.json()["indicator_id"]


# ── Tests ─────────────────────────────────────────────────────────────────────


class TestListIndicators:
    def test_returns_empty_list_initially(self, client: TestClient):
        resp = client.get("/api/custom-indicators")
        assert resp.status_code == 200
        data = resp.json()
        assert "indicators" in data
        assert "total" in data
        assert data["total"] == 0

    def test_created_indicator_appears(self, client: TestClient, indicator_id: str):
        resp = client.get("/api/custom-indicators")
        assert resp.status_code == 200
        ids = [i["indicator_id"] for i in resp.json()["indicators"]]
        assert indicator_id in ids

    def test_total_count_is_accurate(self, client: TestClient):
        for n in ("Alpha", "Beta", "Gamma"):
            client.post("/api/custom-indicators", json={"name": n, "type": "ema", "params": {}})
        resp = client.get("/api/custom-indicators")
        assert resp.json()["total"] == 3


class TestCreateIndicator:
    def test_returns_indicator_with_id(self, client: TestClient):
        resp = client.post(
            "/api/custom-indicators",
            json={"name": "Test EMA", "type": "ema", "params": {"period": 14}},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "indicator_id" in data
        assert data["name"] == "Test EMA"
        assert data["type"] == "ema"

    def test_indicator_id_starts_with_ind(self, client: TestClient):
        resp = client.post(
            "/api/custom-indicators",
            json={"name": "RSI", "type": "rsi", "params": {"period": 14}},
        )
        assert resp.json()["indicator_id"].startswith("ind_")

    def test_description_and_color_stored(self, client: TestClient):
        resp = client.post(
            "/api/custom-indicators",
            json={
                "name": "MACD",
                "type": "macd",
                "params": {},
                "description": "MACD crossover",
                "color": "#00ff00",
            },
        )
        data = resp.json()
        assert data["description"] == "MACD crossover"
        assert data["color"] == "#00ff00"


class TestGetIndicator:
    def test_returns_indicator_by_id(self, client: TestClient, indicator_id: str):
        resp = client.get(f"/api/custom-indicators/{indicator_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["indicator_id"] == indicator_id
        assert data["name"] == "My SMA"

    def test_missing_indicator_returns_404(self, client: TestClient):
        resp = client.get("/api/custom-indicators/nonexistent-id")
        assert resp.status_code == 404


class TestUpdateIndicator:
    def test_put_replaces_indicator(self, client: TestClient, indicator_id: str):
        resp = client.put(
            f"/api/custom-indicators/{indicator_id}",
            json={
                "name": "Updated SMA",
                "type": "sma",
                "params": {"period": 50},
                "description": "New description",
                "color": "#0000ff",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "Updated SMA"
        assert data["params"]["period"] == 50

    def test_put_missing_indicator_returns_404(self, client: TestClient):
        resp = client.put(
            "/api/custom-indicators/nonexistent",
            json={"name": "X", "type": "sma", "params": {}},
        )
        assert resp.status_code == 404

    def test_patch_updates_partial_fields(self, client: TestClient, indicator_id: str):
        resp = client.patch(
            f"/api/custom-indicators/{indicator_id}",
            json={"name": "Patched SMA"},
        )
        assert resp.status_code == 200
        assert resp.json()["name"] == "Patched SMA"

    def test_patch_missing_indicator_returns_404(self, client: TestClient):
        resp = client.patch(
            "/api/custom-indicators/nonexistent",
            json={"name": "X"},
        )
        assert resp.status_code == 404


class TestDeleteIndicator:
    def test_delete_returns_ok(self, client: TestClient, indicator_id: str):
        resp = client.delete(f"/api/custom-indicators/{indicator_id}")
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    def test_deleted_indicator_not_in_list(self, client: TestClient, indicator_id: str):
        client.delete(f"/api/custom-indicators/{indicator_id}")
        resp = client.get("/api/custom-indicators")
        ids = [i["indicator_id"] for i in resp.json()["indicators"]]
        assert indicator_id not in ids

    def test_delete_missing_indicator_returns_404(self, client: TestClient):
        resp = client.delete("/api/custom-indicators/nonexistent-id")
        assert resp.status_code == 404


class TestTestIndicator:
    def test_test_returns_result_struct(self, client: TestClient, indicator_id: str):
        resp = client.post(
            f"/api/custom-indicators/{indicator_id}/test",
            json={"symbol": "XAUUSD", "timeframe": "H1", "limit": 100},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "indicator_id" in data
        assert "passed" in data
        assert "sample_values" in data

    def test_test_missing_indicator_returns_404(self, client: TestClient):
        resp = client.post(
            "/api/custom-indicators/nonexistent/test",
            json={"symbol": "XAUUSD", "timeframe": "H1"},
        )
        assert resp.status_code == 404


class TestDeployIndicator:
    def test_deploy_marks_indicator_as_deployed(self, client: TestClient, indicator_id: str):
        resp = client.post(f"/api/custom-indicators/{indicator_id}/deploy")
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["deployed"] is True
        assert "deployed_at" in data

    def test_deploy_missing_indicator_returns_404(self, client: TestClient):
        resp = client.post("/api/custom-indicators/nonexistent/deploy")
        assert resp.status_code == 404


class TestBuiltinIndicators:
    def test_returns_builtin_list(self, client: TestClient):
        resp = client.get("/api/custom-indicators/builtin")
        assert resp.status_code == 200
        data = resp.json()
        assert "indicators" in data
        assert len(data["indicators"]) >= 5

    def test_each_builtin_has_type_and_name(self, client: TestClient):
        resp = client.get("/api/custom-indicators/builtin")
        for ind in resp.json()["indicators"]:
            assert "type" in ind
            assert "name" in ind

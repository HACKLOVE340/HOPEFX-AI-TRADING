# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# AGPL-3.0 -- Share all modifications
"""
tests/unit/test_sub_accounts_api.py
=====================================
Unit tests for api/accounts.py sub-account endpoints.

Covers:
  - GET    /api/accounts/sub-accounts          — list sub-accounts
  - POST   /api/accounts/sub-accounts          — create sub-account
  - GET    /api/accounts/sub-accounts/{id}     — get by ID
  - PATCH  /api/accounts/sub-accounts/{id}     — update label/active
  - DELETE /api/accounts/sub-accounts/{id}     — delete
  - POST   /api/accounts/sub-accounts/{id}/transfer — transfer balance

The db_store helpers are imported inside functions in api/accounts.py, so
we patch 'api.db_store.db_get' and 'api.db_store.db_set' with an in-memory
dict to provide persistence within a single test.
"""

from __future__ import annotations

import os
from typing import Any
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("SECURITY_JWT_SECRET", "unit-test-accounts-secret-32chars!!")

from api.accounts import router as accounts_router
from api.auth import TokenPayload, get_current_user


# ---- Fixtures ----------------------------------------------------------------


@pytest.fixture()
def db_store() -> dict[str, Any]:
    """In-memory dict that simulates the db_store KV store."""
    return {}


@pytest.fixture()
def client(db_store: dict[str, Any]) -> TestClient:
    """TestClient with auth overridden and db_store patched."""
    app = FastAPI()
    app.include_router(accounts_router)

    _user = TokenPayload(sub="accounts-test-user", role="admin")
    app.dependency_overrides[get_current_user] = lambda: _user

    def _db_get(key: str, *args, **kwargs):
        return db_store.get(key)

    def _db_set(key: str, value: Any, *args, **kwargs):
        db_store[key] = value

    def _db_delete(key: str, *args, **kwargs):
        db_store.pop(key, None)

    with (
        patch("api.db_store.db_get", side_effect=_db_get),
        patch("api.db_store.db_set", side_effect=_db_set),
        patch("api.db_store.db_delete", side_effect=_db_delete),
        # Force the db_store fallback path by making all SQLAlchemy helpers
        # return None — this keeps tests hermetic and independent of any
        # SQLite/PostgreSQL state on the test machine.
        patch("api.accounts._db_list_sub_accounts", return_value=None),
        patch("api.accounts._db_create_sub_account", return_value=None),
        patch("api.accounts._db_update_sub_account", return_value=None),
    ):
        yield TestClient(app, raise_server_exceptions=True)


# ---- Helper ------------------------------------------------------------------


def _create_account(client: TestClient, label: str = "Test Account", balance: float = 5000.0) -> dict:
    """Create a sub-account and return its data."""
    resp = client.post(
        "/api/accounts/sub-accounts",
        json={"label": label, "broker": "oanda_paper", "initial_balance": balance},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


# ---- Tests: list sub-accounts ------------------------------------------------


class TestListSubAccounts:
    def test_list_empty_returns_empty_list(self, client: TestClient):
        resp = client.get("/api/accounts/sub-accounts")
        assert resp.status_code == 200
        data = resp.json()
        assert data["accounts"] == []
        assert data["total"] == 0

    def test_list_after_create_shows_account(self, client: TestClient):
        _create_account(client, "MyAcc")
        resp = client.get("/api/accounts/sub-accounts")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["accounts"][0]["label"] == "MyAcc"

    def test_list_returns_all_accounts(self, client: TestClient):
        _create_account(client, "Acc1")
        _create_account(client, "Acc2")
        _create_account(client, "Acc3")
        resp = client.get("/api/accounts/sub-accounts")
        assert resp.json()["total"] == 3


# ---- Tests: create sub-account -----------------------------------------------


class TestCreateSubAccount:
    def test_create_minimal_fields(self, client: TestClient):
        resp = client.post(
            "/api/accounts/sub-accounts",
            json={"label": "Scalping Desk"},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["label"] == "Scalping Desk"
        assert "account_id" in data
        assert data["active"] is True

    def test_create_with_custom_balance(self, client: TestClient):
        resp = client.post(
            "/api/accounts/sub-accounts",
            json={"label": "Big Account", "initial_balance": 100_000.0},
        )
        assert resp.status_code == 201
        assert resp.json()["balance"] == 100_000.0

    def test_create_sets_owner_id(self, client: TestClient):
        acc = _create_account(client)
        assert acc["owner_id"] == "accounts-test-user"

    def test_create_sets_broker(self, client: TestClient):
        resp = client.post(
            "/api/accounts/sub-accounts",
            json={"label": "Broker Test", "broker": "alpaca_paper"},
        )
        assert resp.status_code == 201
        assert resp.json()["broker"] == "alpaca_paper"

    def test_create_empty_label_returns_422(self, client: TestClient):
        resp = client.post(
            "/api/accounts/sub-accounts",
            json={"label": ""},
        )
        assert resp.status_code == 422

    def test_create_missing_label_returns_422(self, client: TestClient):
        resp = client.post("/api/accounts/sub-accounts", json={})
        assert resp.status_code == 422

    def test_create_max_10_accounts(self, client: TestClient):
        for i in range(10):
            resp = client.post(
                "/api/accounts/sub-accounts",
                json={"label": f"Account {i}"},
            )
            assert resp.status_code == 201
        resp = client.post("/api/accounts/sub-accounts", json={"label": "One Too Many"})
        assert resp.status_code == 400
        assert "Maximum" in resp.json()["detail"]


# ---- Tests: get sub-account by ID --------------------------------------------


class TestGetSubAccount:
    def test_get_existing_account(self, client: TestClient):
        acc = _create_account(client, "Target")
        resp = client.get(f"/api/accounts/sub-accounts/{acc['account_id']}")
        assert resp.status_code == 200
        assert resp.json()["label"] == "Target"

    def test_get_nonexistent_returns_404(self, client: TestClient):
        resp = client.get("/api/accounts/sub-accounts/nonexistent-id")
        assert resp.status_code == 404

    def test_get_returns_all_fields(self, client: TestClient):
        acc = _create_account(client)
        resp = client.get(f"/api/accounts/sub-accounts/{acc['account_id']}")
        data = resp.json()
        for field in ("account_id", "owner_id", "label", "broker", "balance", "active", "created_at"):
            assert field in data


# ---- Tests: update sub-account -----------------------------------------------


class TestUpdateSubAccount:
    def test_update_label(self, client: TestClient):
        acc = _create_account(client, "Old Label")
        resp = client.patch(
            f"/api/accounts/sub-accounts/{acc['account_id']}",
            json={"label": "New Label"},
        )
        assert resp.status_code == 200
        assert resp.json()["label"] == "New Label"

    def test_update_active_status(self, client: TestClient):
        acc = _create_account(client)
        resp = client.patch(
            f"/api/accounts/sub-accounts/{acc['account_id']}",
            json={"active": False},
        )
        assert resp.status_code == 200
        assert resp.json()["active"] is False

    def test_update_nonexistent_returns_404(self, client: TestClient):
        resp = client.patch(
            "/api/accounts/sub-accounts/does-not-exist",
            json={"label": "Irrelevant"},
        )
        assert resp.status_code == 404


# ---- Tests: delete sub-account -----------------------------------------------


class TestDeleteSubAccount:
    def test_delete_one_of_two_accounts(self, client: TestClient):
<<<<<<< HEAD
        _create_account(client, "Keep")
=======
        _acc1 = _create_account(client, "Keep")
>>>>>>> origin/main
        acc2 = _create_account(client, "Remove")
        resp = client.delete(f"/api/accounts/sub-accounts/{acc2['account_id']}")
        assert resp.status_code == 204
        list_resp = client.get("/api/accounts/sub-accounts")
        assert list_resp.json()["total"] == 1

    def test_delete_only_active_account_returns_400(self, client: TestClient):
        acc = _create_account(client)
        resp = client.delete(f"/api/accounts/sub-accounts/{acc['account_id']}")
        assert resp.status_code == 400
        assert "last active" in resp.json()["detail"]

    def test_delete_nonexistent_returns_404(self, client: TestClient):
        resp = client.delete("/api/accounts/sub-accounts/no-such-id")
        assert resp.status_code == 404


# ---- Tests: transfer balance -------------------------------------------------


class TestTransferBalance:
    def test_transfer_between_two_accounts(self, client: TestClient):
        src = _create_account(client, "Source", balance=10_000.0)
        dst = _create_account(client, "Destination", balance=2_000.0)
        resp = client.post(
            f"/api/accounts/sub-accounts/{src['account_id']}/transfer",
            json={"to_account_id": dst["account_id"], "amount": 3_000.0, "note": "test"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["from_balance"] == 7_000.0
        assert data["to_balance"] == 5_000.0

    def test_transfer_updates_source_and_destination(self, client: TestClient):
        src = _create_account(client, "Src", balance=5_000.0)
        dst = _create_account(client, "Dst", balance=1_000.0)
        client.post(
            f"/api/accounts/sub-accounts/{src['account_id']}/transfer",
            json={"to_account_id": dst["account_id"], "amount": 500.0},
        )
        src_resp = client.get(f"/api/accounts/sub-accounts/{src['account_id']}")
        dst_resp = client.get(f"/api/accounts/sub-accounts/{dst['account_id']}")
        assert src_resp.json()["balance"] == 4_500.0
        assert dst_resp.json()["balance"] == 1_500.0

    def test_transfer_same_account_returns_400(self, client: TestClient):
        acc = _create_account(client)
        resp = client.post(
            f"/api/accounts/sub-accounts/{acc['account_id']}/transfer",
            json={"to_account_id": acc["account_id"], "amount": 100.0},
        )
        assert resp.status_code == 400
        assert "different" in resp.json()["detail"]

    def test_transfer_insufficient_balance_returns_400(self, client: TestClient):
        src = _create_account(client, "Poor", balance=100.0)
        dst = _create_account(client, "Rich", balance=1_000.0)
        resp = client.post(
            f"/api/accounts/sub-accounts/{src['account_id']}/transfer",
            json={"to_account_id": dst["account_id"], "amount": 999.0},
        )
        assert resp.status_code == 400
        assert "Insufficient" in resp.json()["detail"]

    def test_transfer_nonexistent_source_returns_404(self, client: TestClient):
        dst = _create_account(client, "Dest")
        resp = client.post(
            "/api/accounts/sub-accounts/nonexistent-src/transfer",
            json={"to_account_id": dst["account_id"], "amount": 50.0},
        )
        assert resp.status_code == 404

    def test_transfer_nonexistent_destination_returns_404(self, client: TestClient):
        src = _create_account(client, "Src", balance=500.0)
        resp = client.post(
            f"/api/accounts/sub-accounts/{src['account_id']}/transfer",
            json={"to_account_id": "nonexistent-dst", "amount": 50.0},
        )
        assert resp.status_code == 404

    def test_transfer_zero_amount_returns_422(self, client: TestClient):
        src = _create_account(client, "SrcZ")
        dst = _create_account(client, "DstZ")
        resp = client.post(
            f"/api/accounts/sub-accounts/{src['account_id']}/transfer",
            json={"to_account_id": dst["account_id"], "amount": 0.0},
        )
        assert resp.status_code == 422

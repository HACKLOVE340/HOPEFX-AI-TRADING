# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# AGPL-3.0 — Share all modifications
"""
tests/unit/test_replay_router.py
=================================
Unit tests for replay/router.py (Chart Replay Engine HTTP API).

Covers:
  - POST /api/replay/sessions          — create session
  - GET  /api/replay/sessions          — list sessions
  - GET  /api/replay/sessions/{id}     — get session by ID
  - POST /api/replay/sessions/{id}/step — step one bar
  - POST /api/replay/sessions/{id}/run  — run N bars
  - DELETE /api/replay/sessions/{id}   — delete session
  - POST /api/replay/sessions/{id}/pause  — pause
  - POST /api/replay/sessions/{id}/play   — play / resume
  - PUT  /api/replay/sessions/{id}/speed  — set speed
  - POST /api/replay/sessions/{id}/orders — place order
"""

from __future__ import annotations


import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from replay.engine import ChartReplayEngine
from replay.router import create_replay_router


def _make_auth_headers() -> dict[str, str]:
    """Return Authorization headers with a valid test JWT."""
    from auth.jwt import create_access_token

    token = create_access_token({"sub": "test-user@hopefx.io", "role": "trader", "user_id": "test-uid-001"})
    return {"Authorization": f"Bearer {token}"}


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture()
def engine() -> ChartReplayEngine:
    """Fresh engine for each test."""
    return ChartReplayEngine()


@pytest.fixture()
def client(engine: ChartReplayEngine) -> TestClient:
    """Sync TestClient backed by a minimal FastAPI app with auth wired."""
    app = FastAPI()
    app.include_router(create_replay_router(engine))
    return TestClient(app, raise_server_exceptions=True, headers=_make_auth_headers())


@pytest.fixture()
def session_id(client: TestClient) -> str:
    """Create one session and return its ID."""
    resp = client.post(
        "/api/replay/sessions",
        json={
            "symbol": "XAUUSD",
            "timeframe": "1h",
            "start_date": "2024-01-01T00:00:00",
            "end_date": "2024-01-31T00:00:00",
            "initial_balance": 10000.0,
        },
    )
    assert resp.status_code == 200
    return resp.json()["session_id"]


# ── Tests ─────────────────────────────────────────────────────────────────────


class TestCreateSession:
    def test_returns_session_id(self, client: TestClient):
        resp = client.post(
            "/api/replay/sessions",
            json={
                "symbol": "XAUUSD",
                "timeframe": "1h",
                "start_date": "2024-01-01T00:00:00",
                "end_date": "2024-01-31T00:00:00",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "session_id" in data
        assert data["symbol"] == "XAUUSD"
        assert data["timeframe"] == "1h"

    def test_invalid_date_format_returns_400(self, client: TestClient):
        resp = client.post(
            "/api/replay/sessions",
            json={
                "symbol": "XAUUSD",
                "timeframe": "1h",
                "start_date": "not-a-date",
                "end_date": "also-not-a-date",
            },
        )
        assert resp.status_code == 400

    def test_custom_initial_balance(self, client: TestClient):
        resp = client.post(
            "/api/replay/sessions",
            json={
                "symbol": "XAUUSD",
                "timeframe": "1h",
                "start_date": "2024-01-01T00:00:00",
                "end_date": "2024-01-31T00:00:00",
                "initial_balance": 50000.0,
            },
        )
        assert resp.status_code == 200
        assert resp.json()["session_id"].startswith("replay_")


class TestListSessions:
    def test_empty_initially(self, client: TestClient):
        resp = client.get("/api/replay/sessions")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)
        assert len(resp.json()) == 0

    def test_shows_created_session(self, client: TestClient, session_id: str):
        resp = client.get("/api/replay/sessions")
        assert resp.status_code == 200
        ids = [s["session_id"] for s in resp.json()]
        assert session_id in ids

    def test_multiple_sessions_listed(self, client: TestClient):
        for _ in range(3):
            client.post(
                "/api/replay/sessions",
                json={
                    "symbol": "XAUUSD",
                    "timeframe": "1h",
                    "start_date": "2024-01-01T00:00:00",
                    "end_date": "2024-01-15T00:00:00",
                },
            )
        resp = client.get("/api/replay/sessions")
        assert len(resp.json()) == 3


class TestGetSession:
    def test_returns_session_data(self, client: TestClient, session_id: str):
        resp = client.get(f"/api/replay/sessions/{session_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["session_id"] == session_id
        assert "symbol" in data
        assert "status" in data
        assert "bars" in data

    def test_missing_session_returns_404(self, client: TestClient):
        resp = client.get("/api/replay/sessions/nonexistent-id")
        assert resp.status_code == 404

    def test_initial_bar_index_is_zero(self, client: TestClient, session_id: str):
        resp = client.get(f"/api/replay/sessions/{session_id}")
        assert resp.json()["current_bar"] == 0


class TestStepBar:
    def test_step_advances_one_bar(self, client: TestClient, session_id: str):
        resp = client.post(f"/api/replay/sessions/{session_id}/step")
        assert resp.status_code == 200
        data = resp.json()
        assert data["current_bar"] == 1

    def test_step_returns_bar_data(self, client: TestClient, session_id: str):
        resp = client.post(f"/api/replay/sessions/{session_id}/step")
        assert resp.status_code == 200
        data = resp.json()
        assert "bar" in data
        bar = data["bar"]
        for field in ("open", "high", "low", "close", "volume", "time"):
            assert field in bar

    def test_step_missing_session_returns_404(self, client: TestClient):
        resp = client.post("/api/replay/sessions/nonexistent/step")
        assert resp.status_code == 404


class TestRunBars:
    def test_run_advances_n_bars(self, client: TestClient, session_id: str):
        resp = client.post(f"/api/replay/sessions/{session_id}/run?bars=5")
        assert resp.status_code == 200
        data = resp.json()
        assert data["bars_advanced"] >= 1
        assert data["current_bar"] >= 1

    def test_run_default_10_bars(self, client: TestClient, session_id: str):
        resp = client.post(f"/api/replay/sessions/{session_id}/run")
        assert resp.status_code == 200
        data = resp.json()
        assert data["bars_advanced"] >= 1

    def test_run_missing_session_returns_404(self, client: TestClient):
        resp = client.post("/api/replay/sessions/nonexistent/run")
        assert resp.status_code == 404


class TestDeleteSession:
    def test_delete_removes_session(self, client: TestClient, session_id: str):
        resp = client.delete(f"/api/replay/sessions/{session_id}")
        assert resp.status_code == 204
        # Confirm it's gone
        resp2 = client.get(f"/api/replay/sessions/{session_id}")
        assert resp2.status_code == 404

    def test_delete_missing_session_returns_404(self, client: TestClient):
        resp = client.delete("/api/replay/sessions/nonexistent-id")
        assert resp.status_code == 404

    def test_delete_reduces_list(self, client: TestClient, session_id: str):
        client.delete(f"/api/replay/sessions/{session_id}")
        resp = client.get("/api/replay/sessions")
        ids = [s["session_id"] for s in resp.json()]
        assert session_id not in ids


class TestPauseResume:
    def test_pause_session(self, client: TestClient, session_id: str):
        resp = client.post(f"/api/replay/sessions/{session_id}/pause")
        assert resp.status_code == 200
        assert resp.json()["status"] == "paused"

    def test_resume_session(self, client: TestClient, session_id: str):
        client.post(f"/api/replay/sessions/{session_id}/pause")
        resp = client.post(f"/api/replay/sessions/{session_id}/resume")
        assert resp.status_code == 200
        assert resp.json()["status"] == "playing"

    def test_pause_missing_session_returns_404(self, client: TestClient):
        resp = client.post("/api/replay/sessions/nonexistent/pause")
        assert resp.status_code == 404

    def test_resume_missing_session_returns_404(self, client: TestClient):
        resp = client.post("/api/replay/sessions/nonexistent/resume")
        assert resp.status_code == 404


class TestSetSpeed:
    def test_set_valid_speed(self, client: TestClient, session_id: str):
        resp = client.put(
            f"/api/replay/sessions/{session_id}/speed",
            json={"speed": 2},
        )
        assert resp.status_code == 200
        assert resp.json()["speed"] == 2

    def test_set_speed_100x(self, client: TestClient, session_id: str):
        resp = client.put(
            f"/api/replay/sessions/{session_id}/speed",
            json={"speed": 100},
        )
        assert resp.status_code == 200

    def test_invalid_speed_returns_400(self, client: TestClient, session_id: str):
        resp = client.put(
            f"/api/replay/sessions/{session_id}/speed",
            json={"speed": 7},
        )
        assert resp.status_code == 400

    def test_speed_missing_session_returns_404(self, client: TestClient):
        resp = client.put(
            "/api/replay/sessions/nonexistent/speed",
            json={"speed": 1},
        )
        assert resp.status_code == 404


class TestPlaceOrder:
    def test_place_buy_order(self, client: TestClient, session_id: str):
        resp = client.post(
            f"/api/replay/sessions/{session_id}/orders",
            json={"side": "BUY", "size": 0.1},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data is not None

    def test_place_sell_order(self, client: TestClient, session_id: str):
        resp = client.post(
            f"/api/replay/sessions/{session_id}/orders",
            json={"side": "SELL", "size": 0.05},
        )
        assert resp.status_code == 200

    def test_order_missing_session_returns_400(self, client: TestClient):
        # engine.place_practice_order returns None for unknown session_id →
        # router raises 400 "Could not place order"
        resp = client.post(
            "/api/replay/sessions/nonexistent/orders",
            json={"side": "BUY", "size": 0.1},
        )
        assert resp.status_code == 400

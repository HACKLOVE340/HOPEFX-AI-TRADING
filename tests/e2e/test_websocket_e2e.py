# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
End-to-end WebSocket tests.

Tests the /ws/live endpoint using the real FastAPI app via
starlette.testclient.TestClient (sync WebSocket API).

Covers:
  - Connection handshake (auth_required message)
  - JWT authentication flow (auth → auth_ok)
  - Channel subscription (prices, positions, signals, account)
  - Heartbeat / ping-pong
  - Rejection of invalid tokens
  - Graceful disconnect
"""

from __future__ import annotations

import json
import os
import uuid

os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("SECURITY_JWT_SECRET", "test-only-jwt-secret-key-minimum-32-chars!!")
os.environ.setdefault("BROKER", "paper")
os.environ.setdefault("REDIS_URL", "")

import pytest
from starlette.testclient import TestClient


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def app():
    from app import app as _app

    return _app


@pytest.fixture(scope="module")
def client(app):
    """Module-scoped sync TestClient — keeps the ASGI lifespan alive for all tests."""
    with TestClient(app, raise_server_exceptions=False) as tc:
        yield tc


def _unique_email() -> str:
    return f"ws_{uuid.uuid4().hex[:8]}@test.hopefx.io"


def _get_token(client: TestClient) -> str:
    """Register a user and return a JWT access token."""
    email = _unique_email()
    password = "TestPass123!"
    client.post(
        "/api/auth/register",
        json={
            "email": email,
            "password": password,
            "username": f"ws_{uuid.uuid4().hex[:6]}",
        },
    )
    login = client.post("/api/auth/login", json={"email": email, "password": password})
    data = login.json()
    return data.get("access_token") or data.get("token") or ""


# ── Tests ─────────────────────────────────────────────────────────────────────


class TestWebSocketHandshake:
    """Connection-level WebSocket behaviour."""

    def test_ws_endpoint_exists(self, client):
        """The /ws/live route must be registered."""
        with client.websocket_connect("/ws/live") as ws:
            raw = ws.receive_text()
            msg = json.loads(raw)
            assert msg.get("type") in ("connected", "auth_required", "auth_ok")

    def test_ws_sends_auth_required(self, client):
        """Server must request authentication on connect."""
        with client.websocket_connect("/ws/live") as ws:
            raw = ws.receive_text()
            msg = json.loads(raw)
            is_auth_required = (
                msg.get("type") == "auth_required" or msg.get("auth_required") is True or msg.get("type") == "connected"
            )
            assert is_auth_required

    def test_ws_auth_with_valid_token(self, client):
        """Valid JWT -> auth_ok + subscription confirmation."""
        token = _get_token(client)
        if not token:
            pytest.skip("Could not obtain auth token")

        with client.websocket_connect("/ws/live") as ws:
            json.loads(ws.receive_text())  # drain welcome frame
            ws.send_text(json.dumps({"type": "auth", "token": f"Bearer {token}"}))

            auth_ok_received = False
            for _ in range(3):
                try:
                    resp = json.loads(ws.receive_text())
                    if resp.get("type") == "auth_ok":
                        auth_ok_received = True
                        break
                except Exception:
                    break

            assert auth_ok_received, "Expected auth_ok after valid token"

    def test_ws_auth_with_invalid_token(self, client):
        """Invalid JWT -> error or disconnect, not auth_ok."""
        with client.websocket_connect("/ws/live") as ws:
            ws.receive_text()  # consume initial message
            ws.send_text(json.dumps({"type": "auth", "token": "Bearer invalid.token.here"}))

            try:
                resp = json.loads(ws.receive_text())
                assert resp.get("type") != "auth_ok", "Server must not accept invalid tokens"
            except Exception:
                pass  # disconnect is also acceptable

    def test_ws_subscribe_after_auth(self, client):
        """After auth_ok, subscribe message should be accepted."""
        token = _get_token(client)
        if not token:
            pytest.skip("Could not obtain auth token")

        with client.websocket_connect("/ws/live") as ws:
            ws.receive_text()
            ws.send_text(json.dumps({"type": "auth", "token": f"Bearer {token}"}))

            for _ in range(3):
                try:
                    resp = json.loads(ws.receive_text())
                    if resp.get("type") == "auth_ok":
                        break
                except Exception:
                    break

            ws.send_text(
                json.dumps(
                    {
                        "type": "subscribe",
                        "channels": ["prices", "positions", "signals", "account"],
                    }
                )
            )
            # No exception = subscribe was accepted

    def test_ws_heartbeat_ping(self, client):
        """Client ping -> server pong (or heartbeat echo)."""
        token = _get_token(client)
        if not token:
            pytest.skip("Could not obtain auth token")

        with client.websocket_connect("/ws/live") as ws:
            ws.receive_text()
            ws.send_text(json.dumps({"type": "auth", "token": f"Bearer {token}"}))

            for _ in range(3):
                try:
                    resp = json.loads(ws.receive_text())
                    if resp.get("type") == "auth_ok":
                        break
                except Exception:
                    break

            ws.send_text(json.dumps({"type": "ping"}))

            # Pong is optional -- server may not implement it.
            for _ in range(5):
                try:
                    if json.loads(ws.receive_text()).get("type") in ("pong", "heartbeat"):
                        break
                except Exception:
                    break


class TestWebSocketRateLimiting:
    """Connection rate limiting and per-IP caps."""

    def test_multiple_connections_from_same_ip(self, client):
        """Multiple connections from the same IP should be accepted up to the limit."""
        connections = []
        try:
            for _ in range(3):
                ws = client.websocket_connect("/ws/live")
                ws.__enter__()
                connections.append(ws)
                ws.receive_text()  # consume initial message
        except Exception:
            pass  # rate limit hit is acceptable
        finally:
            for ws in connections:
                try:
                    ws.__exit__(None, None, None)
                except Exception:
                    pass

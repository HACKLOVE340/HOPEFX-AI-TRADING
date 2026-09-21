# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# AGPL-3.0 — Share all modifications
"""
tests/unit/test_mobile_register_fails_closed.py
================================================
Regression tests for finding R-08: mobile registration issued credentials for
users it never created.

``MobileAPIServer._register_auth_routes`` guarded every database call with
``if self.db``:

    if self.db and self.db.user_exists(user.email): ...   # duplicate check
    if self.db: self.db.save_user({...})                  # persistence
    access_token = self._generate_token(user_id, ...)     # NOT guarded

With no database the first two were skipped and the third still ran, so the
endpoint returned a signed 24-hour access token and a 7-day refresh token for a
freshly generated uuid that exists nowhere.

That was the live configuration, not a hypothetical: ``_build_module_app()``
constructs ``MobileAPIServer(jwt_secret=...)`` with **no** ``db`` argument, and
``core/router_registry.py`` mounts exactly that app at ``/mobile``.

``login()`` in the same class already handled this correctly — 503 "Database
unavailable". The two disagreed, and register was the permissive one. Issuing a
credential is precisely the operation that must not proceed when the store
backing it is missing.

Scope, checked rather than assumed: the token carries ``{sub, exp, iat}`` and no
``type`` claim, while ``api.auth._decode_token`` requires ``type == "access"``.
The main API therefore rejects these tokens — this was **not** a cross-surface
authentication bypass. ``test_main_api_still_rejects_mobile_tokens`` pins that
boundary so it cannot quietly erode.
"""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

_SECRET = "mobile-register-test-secret-key-min-32-chars"  # pragma: allowlist secret


@pytest.fixture(autouse=True)
def _jwt_secret(monkeypatch):
    monkeypatch.setenv("SECURITY_JWT_SECRET", _SECRET)


class _FakeDB:
    """Minimal store implementing the two methods register touches."""

    def __init__(self) -> None:
        self.users: dict[str, dict] = {}

    def user_exists(self, email: str) -> bool:
        return email in self.users

    def save_user(self, record: dict) -> None:
        self.users[record["email"]] = record


def _server(db=None):
    from mobile.api_v2 import MobileAPIServer

    return MobileAPIServer(jwt_secret=os.environ["SECURITY_JWT_SECRET"], db=db)


def _payload(email: str = "user@example.com") -> dict:
    return {
        "email": email,
        "username": "someuser",
        "password": "Str0ngPassw0rd!",  # pragma: allowlist secret
        "device_id": "device-1",
        "platform": "ios",
    }


@pytest.mark.unit
class TestRegisterWithoutAStore:
    def test_no_database_returns_503_not_a_token(self):
        srv = _server(db=None)
        client = TestClient(srv.app, raise_server_exceptions=False)

        response = client.post("/api/v2/auth/register", json=_payload())

        assert response.status_code == 503, (
            f"register answered {response.status_code} with no database. It must "
            "refuse, exactly as login() already does — otherwise it hands out "
            "credentials for a user that was never created (R-08)."
        )
        assert "access_token" not in response.json()

    def test_the_mounted_app_is_the_one_with_no_database(self):
        """The defect was live, not theoretical."""
        from mobile.api_v2 import MobileAPIServer

        srv = MobileAPIServer(jwt_secret=os.environ["SECURITY_JWT_SECRET"])
        assert srv.db is None, (
            "_build_module_app() constructs this server without a db and "
            "router_registry mounts it, which is why the unguarded token issue "
            "mattered in production rather than only in theory (R-08)."
        )

    def test_register_and_login_agree_when_the_store_is_missing(self):
        """The bug was the disagreement, not either endpoint alone."""
        srv = _server(db=None)
        client = TestClient(srv.app, raise_server_exceptions=False)

        register = client.post("/api/v2/auth/register", json=_payload())
        login = client.post(
            "/api/v2/auth/login",
            params={"email": "user@example.com", "password": "Str0ngPassw0rd!"},  # pragma: allowlist secret
        )
        assert register.status_code == login.status_code == 503


@pytest.mark.unit
class TestRegisterWithAStore:
    def test_normal_registration_still_works(self):
        db = _FakeDB()
        client = TestClient(_server(db=db).app, raise_server_exceptions=False)

        response = client.post("/api/v2/auth/register", json=_payload("real@example.com"))

        assert response.status_code == 200
        assert response.json().get("access_token")
        assert "real@example.com" in db.users, "the user must actually be persisted"

    def test_duplicate_registration_is_rejected(self):
        """Unreachable before: the check sat behind `if self.db`."""
        db = _FakeDB()
        client = TestClient(_server(db=db).app, raise_server_exceptions=False)

        client.post("/api/v2/auth/register", json=_payload("dupe@example.com"))
        second = client.post("/api/v2/auth/register", json=_payload("dupe@example.com"))

        assert second.status_code == 409


@pytest.mark.unit
class TestCrossSurfaceBoundary:
    def test_main_api_still_rejects_mobile_tokens(self):
        """Mobile tokens must not authenticate against the main API.

        They omit the ``type`` claim that ``api.auth._decode_token`` requires.
        That is the only thing that kept R-08 from being a full authentication
        bypass, so it is worth pinning explicitly rather than leaving implicit.
        """
        import jwt as _jwt
        from fastapi import HTTPException

        from api.auth import _decode_token

        srv = _server(db=_FakeDB())
        mobile_token = srv._generate_token("some-user-id")

        # Sanity: it really is signed with the shared secret.
        decoded = _jwt.decode(mobile_token, _SECRET, algorithms=["HS256"])
        assert decoded["sub"] == "some-user-id"
        assert "type" not in decoded

        # 401 specifically — a token missing `type` is rejected as unauthenticated,
        # not accepted or failed in some other way.
        with pytest.raises(HTTPException) as exc:
            _decode_token(mobile_token)
        assert exc.value.status_code == 401

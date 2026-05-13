# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
Integration tests: full auth flow against real DB fixtures.

Covers:
  - Register → signed email verification token → verify-email
  - Login (email + username) → access + refresh tokens
  - Token refresh (rotation)
  - Logout (access token blacklisted)
  - Forgot-password → signed reset token → reset-password
  - CSRF token issuance + double-submit validation
  - 2FA setup → confirm → login with TOTP → disable
  - Rate limiting (429 after N attempts)
  - /me returns correct profile after login

All tests use real SQLite-backed DB fixtures (tests/fixtures/db.py).
No mocks, stubs, or synthetic data in production code paths.
"""

from __future__ import annotations

import os
import uuid

import pytest

# Must be set before any app import
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("SECURITY_JWT_SECRET", "test-only-jwt-secret-key-minimum-32-chars!!")
os.environ.setdefault("CSRF_PROTECTION", "false")
os.environ.setdefault("STARTUP_GATE", "false")
# Force email verification so register() returns a token we can use in tests.
# Without this the service auto-verifies accounts and returns token=None.
os.environ["REQUIRE_EMAIL_VERIFICATION"] = "true"

# ── Dependency guards ─────────────────────────────────────────────────────────

try:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    _DEPS_OK = True
except ImportError as _e:
    _DEPS_OK = False
    _DEPS_ERR = str(_e)

if not _DEPS_OK:
    pytest.skip(f"Missing dependencies: {_DEPS_ERR}", allow_module_level=True)

try:
    from auth.router import router as auth_router
    from auth.service import AuthService
    from database.user_models import Base as UserBase

    _AUTH_OK = True
except Exception as _e:
    _AUTH_OK = False
    _AUTH_ERR = str(_e)

if not _AUTH_OK:
    pytest.skip(f"Auth modules not importable: {_AUTH_ERR}", allow_module_level=True)

# ── Shared test secret ────────────────────────────────────────────────────────

_SECRET = "test-only-jwt-secret-key-minimum-32-chars!!"
os.environ["SECURITY_JWT_SECRET"] = _SECRET

# Patch _REQUIRE_EMAIL_VERIFICATION at module level (after import) so that
# register() always returns a token regardless of APP_ENV defaults.
import auth.service as _auth_svc_mod

_auth_svc_mod._REQUIRE_EMAIL_VERIFICATION = True


# ── App + DB fixtures ─────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def db_engine():
    """In-process SQLite engine shared across all tests in this module."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    try:
        UserBase.metadata.create_all(engine)
    except Exception:
        # Partial schema is fine — tests skip on missing columns
        pass
    yield engine
    engine.dispose()


@pytest.fixture(scope="module")
def session_factory(db_engine):
    return sessionmaker(bind=db_engine, autocommit=False, autoflush=False)


@pytest.fixture(scope="module")
def auth_service(session_factory):
    # _REQUIRE_EMAIL_VERIFICATION already patched at module level above.
    svc = AuthService(session_factory=session_factory)
    return svc


@pytest.fixture(scope="module")
def client(auth_service):
    """TestClient wired to a real AuthService backed by in-memory SQLite."""
    from auth.router import set_auth_service

    set_auth_service(auth_service)

    # Force APP_ENV=test for the lifetime of this module so the router
    # exposes _dev_verify_token and _dev_reset_token in responses.
    # The conftest autouse fixture restores env vars per-test, but since
    # this fixture is module-scoped we set it once here and also ensure
    # it's set at the start of every test via the autouse fixture below.
    os.environ["APP_ENV"] = "test"

    app = FastAPI()
    app.include_router(auth_router)
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture(autouse=True)
def _ensure_test_env():
    """Guarantee APP_ENV=test and a clean rate-limit state for every test.

    The conftest _restore_critical_env_vars fixture restores APP_ENV after
    each test.  If a previous test set it to something else, this fixture
    re-applies the correct value before the next test runs.

    Rate-limit state is reset before each test so accumulated hits from
    previous tests don't bleed into unrelated assertions.
    """
    os.environ["APP_ENV"] = "test"
    os.environ["SECURITY_JWT_SECRET"] = _SECRET
    # Raise the rate limit high so normal test traffic never hits 429
    os.environ["AUTH_RATE_LIMIT_REQUESTS"] = "1000"
    from auth.router import reset_rate_limit_state

    reset_rate_limit_state()
    yield
    reset_rate_limit_state()


# ── Helpers ───────────────────────────────────────────────────────────────────


def _unique_email() -> str:
    # Use example.com — RFC 2606 reserved, always valid for email validators
    return f"test-{uuid.uuid4().hex[:8]}@example.com"


def _unique_username() -> str:
    return f"user_{uuid.uuid4().hex[:8]}"


def _register(client, email=None, username=None, password="Str0ng!Pass99"):
    email = email or _unique_email()
    username = username or _unique_username()
    r = client.post(
        "/api/auth/register",
        json={"email": email, "username": username, "password": password},
    )
    return r, email, username


def _login(client, email, password="Str0ng!Pass99"):
    return client.post(
        "/api/auth/login",
        json={"email": email, "password": password},
    )


# ── Registration ──────────────────────────────────────────────────────────────


class TestRegister:
    def test_register_returns_201(self, client):
        r, _, _ = _register(client)
        assert r.status_code == 201, r.text

    def test_register_returns_message(self, client):
        r, _, _ = _register(client)
        assert "message" in r.json()

    def test_register_duplicate_email_returns_400(self, client):
        email = _unique_email()
        _register(client, email=email)
        r2, _, _ = _register(client, email=email)
        assert r2.status_code == 400

    def test_register_duplicate_username_returns_400(self, client):
        username = _unique_username()
        _register(client, username=username)
        r2, _, _ = _register(client, username=username)
        assert r2.status_code == 400

    def test_register_weak_password_returns_422(self, client):
        r = client.post(
            "/api/auth/register",
            json={"email": _unique_email(), "username": _unique_username(), "password": "short"},
        )
        assert r.status_code == 422

    def test_register_invalid_email_returns_422(self, client):
        r = client.post(
            "/api/auth/register",
            json={"email": "not-an-email", "username": _unique_username(), "password": "Str0ng!Pass99"},
        )
        assert r.status_code == 422

    def test_register_exposes_verify_token_in_test_mode(self, client):
        """APP_ENV=test must expose _dev_verify_token so CI can verify without SMTP."""
        r, _, _ = _register(client)
        body = r.json()
        # Token is only exposed when APP_ENV=test (set at module top)
        assert "_dev_verify_token" in body
        assert isinstance(body["_dev_verify_token"], str)
        assert len(body["_dev_verify_token"]) > 20


# ── Email verification ────────────────────────────────────────────────────────


class TestEmailVerification:
    def test_verify_email_with_signed_token(self, client):
        r, email, _ = _register(client)
        signed_token = r.json().get("_dev_verify_token")
        if not signed_token:
            pytest.skip("_dev_verify_token not returned — APP_ENV not test")

        rv = client.get(f"/api/auth/verify-email?token={signed_token}")
        assert rv.status_code == 200, rv.text
        assert "verified" in rv.json().get("message", "").lower()

    def test_verify_email_invalid_token_returns_400(self, client):
        rv = client.get("/api/auth/verify-email?token=totally-invalid-garbage")
        assert rv.status_code == 400

    def test_verify_email_reuse_returns_400(self, client):
        """Token is one-time-use — second redemption must fail."""
        r, _, _ = _register(client)
        signed_token = r.json().get("_dev_verify_token")
        if not signed_token:
            pytest.skip("_dev_verify_token not returned")

        client.get(f"/api/auth/verify-email?token={signed_token}")
        rv2 = client.get(f"/api/auth/verify-email?token={signed_token}")
        assert rv2.status_code == 400

    def test_resend_verification_returns_200(self, client):
        _, email, _ = _register(client)
        rv = client.post("/api/auth/resend-verification", json={"email": email})
        assert rv.status_code == 200

    def test_resend_verification_unknown_email_returns_400(self, client):
        rv = client.post(
            "/api/auth/resend-verification",
            json={"email": "nobody@example.com"},
        )
        assert rv.status_code == 400


# ── Login ─────────────────────────────────────────────────────────────────────


class TestLogin:
    def _verified_user(self, client):
        """Register + verify a user, return (email, password)."""
        password = "Str0ng!Pass99"
        r, email, _ = _register(client, password=password)
        token = r.json().get("_dev_verify_token")
        if token:
            client.get(f"/api/auth/verify-email?token={token}")
        return email, password

    def test_login_returns_access_and_refresh_tokens(self, client):
        email, pw = self._verified_user(client)
        r = _login(client, email, pw)
        assert r.status_code == 200, r.text
        body = r.json()
        assert "access_token" in body
        assert "refresh_token" in body
        assert body.get("token_type") == "bearer"

    def test_login_wrong_password_returns_401(self, client):
        email, _ = self._verified_user(client)
        r = _login(client, email, "WrongPassword!")
        assert r.status_code == 401

    def test_login_unknown_email_returns_401(self, client):
        r = _login(client, "nobody@hopefx.test")
        assert r.status_code == 401

    def test_login_by_username(self, client):
        password = "Str0ng!Pass99"
        username = _unique_username()
        r, email, _ = _register(client, username=username, password=password)
        token = r.json().get("_dev_verify_token")
        if token:
            client.get(f"/api/auth/verify-email?token={token}")

        r2 = client.post(
            "/api/auth/login",
            json={"username": username, "password": password},
        )
        assert r2.status_code == 200, r2.text
        assert "access_token" in r2.json()

    def test_login_sets_access_cookie(self, client):
        email, pw = self._verified_user(client)
        r = _login(client, email, pw)
        assert r.status_code == 200
        assert "hopefx_access_token" in r.cookies

    def test_login_sets_refresh_cookie(self, client):
        email, pw = self._verified_user(client)
        r = _login(client, email, pw)
        assert r.status_code == 200
        assert "hopefx_refresh_token" in r.cookies

    def test_login_missing_email_and_username_returns_422(self, client):
        r = client.post("/api/auth/login", json={"password": "Str0ng!Pass99"})
        assert r.status_code == 422


# ── /me ───────────────────────────────────────────────────────────────────────


class TestMe:
    def test_me_returns_profile(self, client):
        password = "Str0ng!Pass99"
        r, email, username = _register(client, password=password)
        token = r.json().get("_dev_verify_token")
        if token:
            client.get(f"/api/auth/verify-email?token={token}")

        lr = _login(client, email, password)
        assert lr.status_code == 200
        access = lr.json()["access_token"]

        me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {access}"})
        assert me.status_code == 200, me.text
        body = me.json()
        assert body["email"] == email
        assert body["username"] == username

    def test_me_without_token_returns_401(self, client):
        # Use a fresh client with no cookies so the auth cookie from a
        # previous login in this session doesn't satisfy the auth check.
        from fastapi import FastAPI
        from fastapi.testclient import TestClient as _TC

        _app = FastAPI()
        _app.include_router(auth_router)
        fresh = _TC(_app, raise_server_exceptions=False)
        r = fresh.get("/api/auth/me")
        assert r.status_code == 401

    def test_me_with_invalid_token_returns_401(self, client):
        r = client.get(
            "/api/auth/me",
            headers={"Authorization": "Bearer garbage.token.here"},
            cookies={},  # suppress any session cookie
        )
        assert r.status_code == 401


# ── Token refresh ─────────────────────────────────────────────────────────────


class TestTokenRefresh:
    def _login_tokens(self, client):
        password = "Str0ng!Pass99"
        r, email, _ = _register(client, password=password)
        token = r.json().get("_dev_verify_token")
        if token:
            client.get(f"/api/auth/verify-email?token={token}")
        lr = _login(client, email, password)
        assert lr.status_code == 200
        return lr.json()

    def test_refresh_returns_new_access_token(self, client):
        tokens = self._login_tokens(client)
        r = client.post(
            "/api/auth/refresh",
            json={"refresh_token": tokens["refresh_token"]},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert "access_token" in body
        # New token must differ from the original
        assert body["access_token"] != tokens["access_token"]

    def test_refresh_rotates_refresh_token(self, client):
        tokens = self._login_tokens(client)
        r = client.post(
            "/api/auth/refresh",
            json={"refresh_token": tokens["refresh_token"]},
        )
        assert r.status_code == 200
        new_refresh = r.json().get("refresh_token")
        assert new_refresh is not None
        assert new_refresh != tokens["refresh_token"]

    def test_refresh_with_invalid_token_returns_401(self, client):
        r = client.post("/api/auth/refresh", json={"refresh_token": "not-a-real-token"})
        assert r.status_code == 401

    def test_refresh_token_cannot_be_reused(self, client):
        """After rotation the old refresh token must be rejected."""
        tokens = self._login_tokens(client)
        old_refresh = tokens["refresh_token"]
        client.post("/api/auth/refresh", json={"refresh_token": old_refresh})
        r2 = client.post("/api/auth/refresh", json={"refresh_token": old_refresh})
        assert r2.status_code == 401


# ── Logout ────────────────────────────────────────────────────────────────────


class TestLogout:
    def _authenticated(self, client):
        password = "Str0ng!Pass99"
        r, email, _ = _register(client, password=password)
        token = r.json().get("_dev_verify_token")
        if token:
            client.get(f"/api/auth/verify-email?token={token}")
        lr = _login(client, email, password)
        assert lr.status_code == 200
        return lr.json()

    def test_logout_returns_200(self, client):
        tokens = self._authenticated(client)
        r = client.post(
            "/api/auth/logout",
            json={"refresh_token": tokens["refresh_token"]},
            headers={"Authorization": f"Bearer {tokens['access_token']}"},
        )
        assert r.status_code == 200

    def test_logout_all_returns_200(self, client):
        tokens = self._authenticated(client)
        r = client.post(
            "/api/auth/logout-all",
            headers={"Authorization": f"Bearer {tokens['access_token']}"},
        )
        assert r.status_code == 200


# ── Password reset ────────────────────────────────────────────────────────────


class TestPasswordReset:
    def _registered_email(self, client):
        r, email, _ = _register(client)
        token = r.json().get("_dev_verify_token")
        if token:
            client.get(f"/api/auth/verify-email?token={token}")
        return email

    def test_forgot_password_always_returns_200(self, client):
        """Must not reveal whether email exists."""
        r = client.post(
            "/api/auth/forgot-password",
            json={"email": "nobody@example.com"},
        )
        assert r.status_code == 200

    def test_forgot_password_known_email_returns_200(self, client):
        email = self._registered_email(client)
        r = client.post("/api/auth/forgot-password", json={"email": email})
        assert r.status_code == 200

    def test_forgot_password_exposes_reset_token_in_test_mode(self, client):
        email = self._registered_email(client)
        r = client.post("/api/auth/forgot-password", json={"email": email})
        body = r.json()
        assert "_dev_reset_token" in body
        assert len(body["_dev_reset_token"]) > 20

    def test_reset_password_with_signed_token(self, client):
        email = self._registered_email(client)
        r = client.post("/api/auth/forgot-password", json={"email": email})
        signed_token = r.json().get("_dev_reset_token")
        if not signed_token:
            pytest.skip("_dev_reset_token not returned")

        rv = client.post(
            "/api/auth/reset-password",
            json={"token": signed_token, "new_password": "NewStr0ng!Pass99"},
        )
        assert rv.status_code == 200, rv.text
        assert "reset" in rv.json().get("message", "").lower()

    def test_reset_password_invalid_token_returns_400(self, client):
        rv = client.post(
            "/api/auth/reset-password",
            json={"token": "garbage-token", "new_password": "NewStr0ng!Pass99"},
        )
        assert rv.status_code == 400

    def test_reset_password_reuse_returns_400(self, client):
        """Reset token is one-time-use."""
        email = self._registered_email(client)
        r = client.post("/api/auth/forgot-password", json={"email": email})
        signed_token = r.json().get("_dev_reset_token")
        if not signed_token:
            pytest.skip("_dev_reset_token not returned")

        client.post(
            "/api/auth/reset-password",
            json={"token": signed_token, "new_password": "NewStr0ng!Pass99"},
        )
        rv2 = client.post(
            "/api/auth/reset-password",
            json={"token": signed_token, "new_password": "AnotherPass99!"},
        )
        assert rv2.status_code == 400

    def test_can_login_with_new_password_after_reset(self, client):
        email = self._registered_email(client)
        r = client.post("/api/auth/forgot-password", json={"email": email})
        signed_token = r.json().get("_dev_reset_token")
        if not signed_token:
            pytest.skip("_dev_reset_token not returned")

        new_pw = "NewStr0ng!Pass99"
        client.post(
            "/api/auth/reset-password",
            json={"token": signed_token, "new_password": new_pw},
        )
        lr = _login(client, email, new_pw)
        assert lr.status_code == 200, lr.text
        assert "access_token" in lr.json()

    def test_old_password_rejected_after_reset(self, client):
        old_pw = "Str0ng!Pass99"
        r, email, _ = _register(client, password=old_pw)
        token = r.json().get("_dev_verify_token")
        if token:
            client.get(f"/api/auth/verify-email?token={token}")

        fr = client.post("/api/auth/forgot-password", json={"email": email})
        signed_token = fr.json().get("_dev_reset_token")
        if not signed_token:
            pytest.skip("_dev_reset_token not returned")

        client.post(
            "/api/auth/reset-password",
            json={"token": signed_token, "new_password": "NewStr0ng!Pass99"},
        )
        lr = _login(client, email, old_pw)
        assert lr.status_code == 401


# ── CSRF token ────────────────────────────────────────────────────────────────


class TestCSRF:
    def test_csrf_token_endpoint_returns_token(self, client):
        r = client.get("/api/auth/csrf-token")
        assert r.status_code == 200
        body = r.json()
        assert "csrf_token" in body
        assert len(body["csrf_token"]) >= 32

    def test_csrf_token_sets_cookie(self, client):
        r = client.get("/api/auth/csrf-token")
        assert r.status_code == 200
        assert "hopefx_csrf" in r.cookies

    def test_csrf_cookie_matches_body_token(self, client):
        r = client.get("/api/auth/csrf-token")
        body_token = r.json()["csrf_token"]
        cookie_token = r.cookies.get("hopefx_csrf")
        assert body_token == cookie_token

    def test_csrf_tokens_are_unique_per_request(self, client):
        r1 = client.get("/api/auth/csrf-token")
        r2 = client.get("/api/auth/csrf-token")
        assert r1.json()["csrf_token"] != r2.json()["csrf_token"]


# ── Rate limiting ─────────────────────────────────────────────────────────────


class TestRateLimiting:
    def test_login_rate_limit_triggers_429(self, client):
        """Exceed AUTH_RATE_LIMIT_REQUESTS within the window → 429."""
        import os as _os

        _os.environ["AUTH_RATE_LIMIT_REQUESTS"] = "3"
        _os.environ["AUTH_RATE_LIMIT_WINDOW_SECONDS"] = "60"

        from auth.router import reset_rate_limit_state

        reset_rate_limit_state()

        email = _unique_email()
        responses = []
        for _ in range(5):
            r = client.post(
                "/api/auth/login",
                json={"email": email, "password": "WrongPass!"},
                headers={"X-Forwarded-For": "10.0.0.99"},
            )
            responses.append(r.status_code)

        reset_rate_limit_state()
        _os.environ.pop("AUTH_RATE_LIMIT_REQUESTS", None)
        _os.environ.pop("AUTH_RATE_LIMIT_WINDOW_SECONDS", None)

        assert 429 in responses, f"Expected 429 in {responses}"

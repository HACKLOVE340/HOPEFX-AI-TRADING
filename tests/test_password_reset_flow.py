"""
Password Reset Flow Tests

Covers the full cycle:
  1. request_password_reset() — generates token, no email enumeration
  2. reset_password() — validates token, updates hash, revokes sessions
  3. Invalid / expired token handling
  4. Minimum password length enforcement
  5. Login with new password after reset
"""

import os

os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("SECURITY_JWT_SECRET", "test-only-jwt-secret-key-minimum-32-chars!!")

import pytest
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

UTC = timezone.utc


# ---------------------------------------------------------------------------
# Minimal in-memory session factory (avoids DB dependency)
# ---------------------------------------------------------------------------


class _FakeUser:
    def __init__(self, email="trader@example.com", password="hashedpw"):
        self.id = "user-001"
        self.email = email
        self.hashed_password = password
        self.password_reset_token = None
        self.password_reset_expires = None
        self.is_active = True
        self.is_verified = True


class _FakeSession:
    def __init__(self, user=None):
        self._user = user

    def query(self, model):
        return self

    def filter_by(self, **kwargs):
        if self._user and all(getattr(self._user, k, None) == v for k, v in kwargs.items()):
            return self
        # Return empty result if no match
        self._no_match = True
        return self

    def first(self):
        if getattr(self, "_no_match", False):
            return None
        return self._user

    def commit(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


@contextmanager
def _sf_with_user(user):
    yield _FakeSession(user=user)


@contextmanager
def _sf_no_user():
    yield _FakeSession(user=None)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_service(user=None):
    from auth.service import AuthService

    svc = AuthService.__new__(AuthService)
    if user is not None:
        svc._sf = lambda: _sf_with_user(user)
    else:
        svc._sf = lambda: _sf_no_user()
    return svc


# ---------------------------------------------------------------------------
# Tests: request_password_reset
# ---------------------------------------------------------------------------


class TestRequestPasswordReset:
    def test_unknown_email_returns_success_no_token(self):
        """Email enumeration protection: always returns True with no raw token."""
        svc = _make_service(user=None)
        ok, msg, token = svc.request_password_reset("nobody@example.com")
        assert ok is True
        assert token is None  # no token — user doesn't exist

    def test_known_email_returns_token(self):
        user = _FakeUser()
        svc = _make_service(user=user)
        ok, msg, token = svc.request_password_reset(user.email)
        assert ok is True
        assert token is not None
        assert len(token) > 10  # secrets.token_urlsafe(32) → 43 chars

    def test_token_hash_stored_on_user(self):
        """reset_token stored as hash, not plaintext."""
        user = _FakeUser()
        svc = _make_service(user=user)
        _, _, token = svc.request_password_reset(user.email)
        assert user.password_reset_token is not None
        assert user.password_reset_token != token  # must be hashed

    def test_expiry_set_to_one_hour(self):
        user = _FakeUser()
        svc = _make_service(user=user)
        before = datetime.now(UTC)
        svc.request_password_reset(user.email)
        after = datetime.now(UTC)
        exp = user.password_reset_expires
        if exp and not exp.tzinfo:
            exp = exp.replace(tzinfo=UTC)
        assert exp is not None
        assert before + timedelta(minutes=59) < exp <= after + timedelta(minutes=61)

    def test_email_normalised_to_lowercase(self):
        """Email matching is case-insensitive."""
        user = _FakeUser(email="trader@example.com")

        # Rewrite _sf to match case-insensitively
        class _CISession(_FakeSession):
            def filter_by(self, **kwargs):
                email = kwargs.get("email", "")
                if self._user and self._user.email == email:
                    return self
                self._no_match = True
                return self

        from contextlib import contextmanager as cm

        @cm
        def sf():
            yield _CISession(user=user)

        from auth.service import AuthService

        svc = AuthService.__new__(AuthService)
        svc._sf = sf

        ok, _, token = svc.request_password_reset("TRADER@EXAMPLE.COM")
        assert ok is True
        assert token is not None


# ---------------------------------------------------------------------------
# Tests: reset_password
# ---------------------------------------------------------------------------


class TestResetPassword:
    def _user_with_token(self, token_raw, expired=False):
        """Build a user whose reset token matches token_raw."""
        from auth.service import _hash_token

        user = _FakeUser()
        user.password_reset_token = _hash_token(token_raw)
        if expired:
            user.password_reset_expires = datetime.now(UTC) - timedelta(hours=2)
        else:
            user.password_reset_expires = datetime.now(UTC) + timedelta(hours=1)
        return user

    def test_valid_token_resets_password(self):
        token = "validtokenABCDEF1234567890"
        user = self._user_with_token(token)
        original_hash = user.hashed_password

        svc = _make_service(user=user)
        # patch logout_all so we don't need a full session factory
        with patch.object(svc, "logout_all", return_value=None):
            ok, msg = svc.reset_password(token, "NewSecurePass1!")

        assert ok is True
        assert user.hashed_password != original_hash
        assert user.password_reset_token is None  # one-time use: token cleared

    def test_invalid_token_returns_error(self):
        _user = self._user_with_token("correcttoken")
        svc = _make_service(user=None)  # no matching user for wrong token
        ok, msg = svc.reset_password("wrongtoken", "NewSecurePass1!")
        assert ok is False
        assert "invalid" in msg.lower() or "expired" in msg.lower()

    def test_expired_token_returns_error(self):
        token = "expiredtokenABC123"
        user = self._user_with_token(token, expired=True)
        svc = _make_service(user=user)
        ok, msg = svc.reset_password(token, "NewSecurePass1!")
        assert ok is False
        assert "expired" in msg.lower()

    def test_short_password_rejected(self):
        token = "shorttesttoken12345678"
        user = self._user_with_token(token)
        svc = _make_service(user=user)
        ok, msg = svc.reset_password(token, "short")
        assert ok is False
        assert "8" in msg or "characters" in msg.lower()

    def test_sessions_revoked_after_reset(self):
        token = "validtok123456789abcdef"
        user = self._user_with_token(token)
        svc = _make_service(user=user)
        revoked_ids = []

        def fake_logout_all(uid):
            revoked_ids.append(uid)

        with patch.object(svc, "logout_all", side_effect=fake_logout_all):
            ok, _ = svc.reset_password(token, "NewSecurePass99!")

        assert ok is True
        assert user.id in revoked_ids

    def test_password_stored_as_bcrypt_hash(self):
        from auth.jwt import verify_password

        token = "anothertesttoken9876543"
        user = self._user_with_token(token)
        new_pw = "MyNewPassword123!"
        svc = _make_service(user=user)
        with patch.object(svc, "logout_all", return_value=None):
            ok, _ = svc.reset_password(token, new_pw)
        assert ok is True
        # The stored hash must verify against the new password
        assert verify_password(new_pw, user.hashed_password)


# ---------------------------------------------------------------------------
# Tests: full router round-trip (httpx TestClient)
# ---------------------------------------------------------------------------


class TestPasswordResetRouter:
    """Integration-level tests through the FastAPI router."""

    @pytest.fixture(autouse=True)
    def _mock_service(self, monkeypatch):
        """Inject a mock AuthService into the router."""
        from auth import router as _router

        self._mock_svc = MagicMock()
        monkeypatch.setattr(_router, "_svc", lambda: self._mock_svc)

    def _client(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from auth.router import router as auth_router

        app = FastAPI()
        # Router already has prefix="/api/auth" baked in
        app.include_router(auth_router)
        return TestClient(app, raise_server_exceptions=False)

    def test_forgot_password_always_200(self):
        self._mock_svc.request_password_reset.return_value = (
            True,
            "If that email is registered, a reset link has been sent.",
            None,
        )
        client = self._client()
        r = client.post(
            "/api/auth/forgot-password",
            json={"email": "user@example.com"},
            headers={"X-CSRF-Token": "skip", "X-Forwarded-For": "127.0.0.1"},
        )
        assert r.status_code == 200

    def test_reset_password_success_200(self):
        self._mock_svc.reset_password.return_value = (True, "Password reset successfully.")
        # Build a properly signed token so the router's signature check passes.
        from auth.router import _make_signed_token, _SALT_PASSWORD_RESET, _PASSWORD_RESET_TTL
        signed = _make_signed_token(
            {"tok": "rawtoken123", "email": "user@example.com"},
            salt=_SALT_PASSWORD_RESET,
            max_age_seconds=_PASSWORD_RESET_TTL,
        )
        client = self._client()
        r = client.post(
            "/api/auth/reset-password",
            json={"token": signed, "new_password": "Secure123!"},
            headers={"X-CSRF-Token": "skip"},
        )
        assert r.status_code == 200

    def test_reset_password_bad_token_400(self):
        self._mock_svc.reset_password.return_value = (False, "Invalid or expired reset token")
        client = self._client()
        r = client.post(
            "/api/auth/reset-password",
            json={"token": "badtoken", "new_password": "Secure123!"},
            headers={"X-CSRF-Token": "skip"},
        )
        assert r.status_code == 400

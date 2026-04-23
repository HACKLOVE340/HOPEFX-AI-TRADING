# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
Tests for the JWT empty-secret bypass fix in auth/router.py.

Verifies that _get_current_user_id:
  1. Raises HTTP 503 when SECURITY_JWT_SECRET is unset (not 401).
  2. Raises HTTP 503 when SECURITY_JWT_SECRET is too short (< 32 chars).
  3. Raises HTTP 401 for a token signed with an empty string (old bypass vector).
  4. Raises HTTP 401 for a token signed with a different valid secret.
  5. Returns the user_id for a legitimately signed access token.
  6. Raises HTTP 401 for an expired token.
  7. Raises HTTP 401 for a token whose 'type' claim is not 'access'.
  8. Raises HTTP 401 for a completely malformed token string.
"""

import sys
import time

import jwt
import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials

# ── Constants ─────────────────────────────────────────────────────────────────

_VALID_SECRET = "a-valid-secret-that-is-at-least-32-chars-long!"  # pragma: allowlist secret
_OTHER_SECRET = "another-valid-secret-that-is-32-chars-long!!"  # pragma: allowlist secret


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_token(  # nosec B107 - test file
    secret: str,
    sub: str = "user-123",
    token_type: str = "access",
    exp_offset: int = 3600,
) -> str:
    payload = {
        "sub": sub,
        "type": token_type,
        "exp": int(time.time()) + exp_offset,
    }
    return jwt.encode(payload, secret, algorithm="HS256")


def _credentials(token: str) -> HTTPAuthorizationCredentials:
    return HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)


class _FakeRequest:
    """Minimal Request stub — no cookie fallback needed for these tests."""

    cookies: dict = {}


def _call(token: str):
    """
    Import and call _get_current_user_id directly.
    Re-imports auth.router each call so the module picks up the current env.
    """
    # Force fresh import so _get_secret() re-reads the env var
    for key in list(sys.modules.keys()):
        if key in ("auth.router", "auth.service", "auth"):
            del sys.modules[key]

    import auth.router as router_mod

    return router_mod._get_current_user_id(_FakeRequest(), _credentials(token))


# ── Tests: server misconfiguration → 503 ─────────────────────────────────────


class TestJWTSecretMisconfiguration:
    """Misconfigured secret must surface as 503, not silently accept tokens."""

    def test_unset_secret_returns_503(self, monkeypatch):
        # Remove all JWT secret aliases so _load_secret() raises RuntimeError
        monkeypatch.delenv("SECURITY_JWT_SECRET", raising=False)
        monkeypatch.delenv("JWT_SECRET_KEY", raising=False)
        monkeypatch.delenv("JWT_SECRET", raising=False)
        forged = _make_token(secret="")  # old bypass vector  # nosec B106 - test file
        with pytest.raises(HTTPException) as exc_info:
            _call(forged)
        assert exc_info.value.status_code == 503, (
            f"Expected 503 (misconfigured), got {exc_info.value.status_code}. Empty-secret bypass may still be present."
        )

    def test_short_secret_returns_503(self, monkeypatch):
        monkeypatch.setenv("SECURITY_JWT_SECRET", "tooshort")
        forged = _make_token(secret="tooshort")
        with pytest.raises(HTTPException) as exc_info:
            _call(forged)
        assert exc_info.value.status_code == 503, f"Expected 503 (misconfigured), got {exc_info.value.status_code}."


# ── Tests: invalid tokens → 401 ──────────────────────────────────────────────


class TestEmptySecretBypass:
    """Core regression: tokens signed with '' must be rejected."""

    def test_empty_string_signed_token_rejected(self, monkeypatch):
        monkeypatch.setenv("SECURITY_JWT_SECRET", _VALID_SECRET)
        forged = _make_token(secret="")  # nosec B106 - test file
        with pytest.raises(HTTPException) as exc_info:
            _call(forged)
        assert exc_info.value.status_code == 401, (
            f"Expected 401 for empty-secret token, got {exc_info.value.status_code}. "
            "Empty-secret bypass may still be present."
        )

    def test_wrong_secret_signed_token_rejected(self, monkeypatch):
        monkeypatch.setenv("SECURITY_JWT_SECRET", _VALID_SECRET)
        forged = _make_token(secret=_OTHER_SECRET)
        with pytest.raises(HTTPException) as exc_info:
            _call(forged)
        assert exc_info.value.status_code == 401


# ── Tests: valid token → success ─────────────────────────────────────────────


class TestValidToken:
    """Correctly signed access tokens must be accepted."""

    def test_valid_access_token_returns_user_id(self, monkeypatch):
        monkeypatch.setenv("SECURITY_JWT_SECRET", _VALID_SECRET)
        token = _make_token(secret=_VALID_SECRET, sub="user-abc")
        user_id = _call(token)
        assert user_id == "user-abc"


# ── Tests: invalid claims → 401 ──────────────────────────────────────────────


class TestTokenClaimsValidation:
    """Invalid claims must be rejected with 401."""

    def test_expired_token_rejected(self, monkeypatch):
        monkeypatch.setenv("SECURITY_JWT_SECRET", _VALID_SECRET)
        token = _make_token(secret=_VALID_SECRET, exp_offset=-10)
        with pytest.raises(HTTPException) as exc_info:
            _call(token)
        assert exc_info.value.status_code == 401

    def test_refresh_token_type_rejected(self, monkeypatch):
        monkeypatch.setenv("SECURITY_JWT_SECRET", _VALID_SECRET)
        token = _make_token(secret=_VALID_SECRET, token_type="refresh")
        with pytest.raises(HTTPException) as exc_info:
            _call(token)
        assert exc_info.value.status_code == 401

    def test_malformed_token_rejected(self, monkeypatch):
        monkeypatch.setenv("SECURITY_JWT_SECRET", _VALID_SECRET)
        with pytest.raises(HTTPException) as exc_info:
            _call("not.a.jwt")
        assert exc_info.value.status_code == 401

# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# AGPL-3.0 — Share all modifications
"""
tests/unit/test_password_change_and_enumeration.py
===================================================
Regression tests for the pre-launch pt.2 findings Q-01, Q-02 and Q-03.

Q-01 — POST /api/auth/change-password could not work. Three independent defects,
each fatal on its own:

  1. It read/wrote ``user.password_hash``. The column on
     ``database.user_models.User`` is ``hashed_password`` and no
     ``password_hash`` attribute exists, so the first comparison raised
     AttributeError, the route's broad ``except Exception`` caught it, and every
     request returned 500. No user could ever change their password — which
     means a user who believed their credential was compromised had no way to
     rotate it.
  2. It hashed with bare ``bcrypt.hashpw``. Registration and login use
     ``auth.jwt.hash_password``/``verify_password``, which BLAKE2b pre-hash to
     avoid bcrypt's 72-byte truncation. With the column fixed but the scheme
     wrong, ``checkpw`` would reject every correct current password, and any
     hash written would not verify at login. auth/service.py carries a comment
     about this precise failure happening once already (pbkdf2 vs bcrypt).
  3. It never revoked sessions, so a password change left every existing
     session valid — defeating the reason people change passwords.

Q-02 — /forgot-password and /resend-verification enumerated the user table.
forgot-password always returned 200 and its docstring claimed enumeration was
prevented, but the body differed: "Password reset email sent" for a known
address vs "If that email is registered, a reset link has been sent." for an
unknown one. resend-verification was blunter still — 400 "Email not found".

Q-03 — request bodies were capped only by nginx's client_max_body_size.
docker-compose publishes the app on 8000:8000, so a direct caller bypassed it
entirely; setup_compression() in core/middleware.py already documents that same
bypass as its own reason to exist.
"""

from __future__ import annotations

import ast
import inspect
import textwrap

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


def _code_of(func) -> str:
    """Return a function's source with its docstring stripped.

    These handlers document the defects they fixed, quoting the old broken code
    verbatim ("it read user.password_hash", "entered with ctx.__enter__()"). A
    naive substring search over the raw source therefore matches the explanation
    and reports the bug as still present. Assert against the executable body
    only, so the prose can describe the past without failing the build.
    """
    src = textwrap.dedent(inspect.getsource(func))
    tree = ast.parse(src)
    node = tree.body[0]
    assert isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    body = node.body
    if (
        body
        and isinstance(body[0], ast.Expr)
        and isinstance(body[0].value, ast.Constant)
        and isinstance(body[0].value.value, str)
    ):
        body = body[1:]  # drop the docstring
    return "\n".join(ast.unparse(stmt) for stmt in body)


# ── Q-01: change-password ─────────────────────────────────────────────────────


@pytest.mark.unit
class TestChangePasswordUsesTheRealSchema:
    def test_does_not_reference_a_nonexistent_password_hash_column(self):
        """The User model has hashed_password, not password_hash."""
        from database.models import User

        assert hasattr(User, "hashed_password"), "model changed — update this test"
        assert not hasattr(User, "password_hash"), (
            "A password_hash attribute now exists; the Q-01 reasoning needs revisiting."
        )

        from api import settings_extended

        src = _code_of(settings_extended.change_password)
        assert ".password_hash" not in src, (
            "change-password references user.password_hash, which does not exist on the "
            "model — every call raises AttributeError and 500s (Q-01)."
        )
        assert "hashed_password" in src, "change-password must use the real column (Q-01)."

    def test_uses_the_canonical_hashing_helpers_not_raw_bcrypt(self):
        """A second hashing scheme in a second file is how Q-01 defect 2 happened."""
        from api import settings_extended

        src = _code_of(settings_extended.change_password)
        assert "bcrypt.hashpw" not in src and "bcrypt.checkpw" not in src, (
            "change-password hashes with raw bcrypt while login verifies via "
            "auth.jwt (BLAKE2b pre-hash). The two disagree, so the user gets "
            "locked out of their own account (Q-01)."
        )
        assert "hash_password" in src and "verify_password" in src, (
            "change-password must go through auth.jwt.hash_password / verify_password (Q-01)."
        )

    def test_revokes_sessions_after_a_successful_change(self):
        from api import settings_extended

        src = _code_of(settings_extended.change_password)
        assert "logout_all" in src, (
            "Changing a password must revoke existing sessions — otherwise someone "
            "who already has a session keeps it, which is the case the user is "
            "trying to fix by changing the password (Q-01)."
        )

    def test_hash_round_trips_through_the_canonical_helpers(self):
        """The property that was broken: what we write, login can verify."""
        from auth.jwt import hash_password, verify_password

        stored = hash_password("correct horse battery staple")
        assert verify_password("correct horse battery staple", stored)
        assert not verify_password("wrong password", stored)

    def test_raw_bcrypt_hash_is_not_verifiable_by_login(self):
        """Proves defect 2 was real rather than cosmetic."""
        import bcrypt

        from auth.jwt import verify_password

        raw = bcrypt.hashpw(b"correct horse battery staple", bcrypt.gensalt()).decode()
        assert not verify_password("correct horse battery staple", raw), (
            "If a raw-bcrypt hash verified via auth.jwt, the two schemes would be "
            "compatible and Q-01 defect 2 would be a non-issue. It does not."
        )

    def test_db_session_is_context_managed(self):
        """`ctx.__enter__()` with no matching exit leaked a session per call."""
        from api import settings_extended

        src = _code_of(settings_extended.change_password)
        assert "__enter__" not in src, (
            "change-password entered the session context manually and never exited "
            "it, leaking a DB session on every call (Q-01)."
        )
        assert "with mgr.session()" in src


# ── Q-02: user enumeration ────────────────────────────────────────────────────


@pytest.mark.unit
class TestNoUserEnumeration:
    def test_reset_and_verify_messages_are_single_constants(self):
        from auth import router

        assert isinstance(router._ENUMERATION_SAFE_RESET_MESSAGE, str)
        assert isinstance(router._ENUMERATION_SAFE_VERIFY_MESSAGE, str)

    def test_forgot_password_returns_the_fixed_message_on_every_path(self):
        from auth import router

        src = _code_of(router.forgot_password)
        assert "_ENUMERATION_SAFE_RESET_MESSAGE" in src, (
            "forgot-password must return one fixed string. Returning the service's "
            "`msg` leaks existence: known addresses got 'Password reset email sent' "
            "and unknown ones got 'If that email is registered...' (Q-02)."
        )
        assert '{"message": msg}' not in src

    def test_resend_verification_never_returns_email_not_found(self):
        from auth import router

        src = _code_of(router.resend_verification)
        assert "_ENUMERATION_SAFE_VERIFY_MESSAGE" in src, "resend-verification must answer uniformly (Q-02)."
        assert "status_code=400, detail=msg" not in src, (
            "resend-verification raised 400 with the service message, which is "
            "'Email not found' for an unknown address — direct enumeration (Q-02)."
        )

    def test_service_still_distinguishes_internally(self):
        """The service may know; only the HTTP response must not say."""
        from auth import service

        src = inspect.getsource(service.AuthService.resend_verification)
        assert "Email not found" in src, (
            "This test pins that the fix is at the HTTP boundary, not by making the "
            "service lie to its own callers. If the service message changed, "
            "re-check that the route still cannot leak."
        )


# ── Q-03: request body cap ────────────────────────────────────────────────────


def _body_limited_app(limit: int):
    import core.middleware as cm

    cm._MAX_BODY_BYTES = limit
    app = FastAPI()
    app.add_middleware(cm.BodySizeLimitMiddleware)

    @app.post("/api/echo")
    async def echo(payload: dict | None = None):
        return {"ok": True}

    return app


@pytest.mark.unit
class TestBodySizeLimit:
    def test_oversized_content_length_is_rejected_with_413(self):
        client = TestClient(_body_limited_app(1024))
        response = client.post("/api/echo", content=b"x" * 4096)
        assert response.status_code == 413, (
            f"expected 413 for an oversized body, got {response.status_code}. nginx's "
            "client_max_body_size does not help a caller who reaches the app "
            "directly on :8000 (Q-03)."
        )

    def test_normal_body_still_passes_and_is_readable_downstream(self):
        client = TestClient(_body_limited_app(1_000_000))
        response = client.post("/api/echo", json={"hello": "world"})
        assert response.status_code == 200, f"the limiter must not break ordinary requests, got {response.status_code}"
        assert response.json() == {"ok": True}

    def test_upload_routes_are_exempt(self):
        """Uploads carry the largest legitimate bodies and cap themselves."""
        import core.middleware as cm

        assert any("avatar" in p for p in cm._BODY_LIMIT_EXEMPT_PREFIXES)
        assert any("kyc" in p for p in cm._BODY_LIMIT_EXEMPT_PREFIXES)

    def test_middleware_is_registered_by_register_all(self):
        import core.middleware as cm

        app = FastAPI()
        cm.register_all(app)
        assert cm.BodySizeLimitMiddleware in {m.cls for m in app.user_middleware}, (
            "BodySizeLimitMiddleware exists but is not installed — which is the "
            "same 'configured but never applied' shape as finding P-03."
        )

# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
tests/unit/test_audit_fixes.py
================================
Regression tests for all six issues identified in the auth/admin audit:

1. impersonate_user() — token must carry 'type':'access' and 'jti' claims
2. reset_user_password() — must use BLAKE2b+bcrypt (auth.jwt.hash_password)
3. Superadmin users API — plan/country/total_trades/revenue_generated from DB
4. .env.example — BOOTSTRAP_*_PASSWORD keys present
5. auth.js roleRedirect — admin → /audit (not /dashboard)
6. setup_rate_limiting() — ImportError raises in production, logs CRITICAL in dev
7. User model — plan and country columns exist

Tests that require fastapi/sqlalchemy/jwt are skipped when those packages are
not installed (bare pytest venv). They run in full CI with requirements.txt.
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent


# ---------------------------------------------------------------------------
# 4. .env.example — BOOTSTRAP_*_PASSWORD keys present
# Pure-Python, no external deps — always runs.
# ---------------------------------------------------------------------------


class TestEnvExample:
    """All three BOOTSTRAP_*_PASSWORD keys must be present in .env.example."""

    @pytest.fixture(scope="class")
    def env_example_content(self):
        path = ROOT / ".env.example"
        assert path.exists(), ".env.example not found"
        return path.read_text()

    def test_bootstrap_superadmin_password_key_present(self, env_example_content):
        assert "BOOTSTRAP_SUPERADMIN_PASSWORD" in env_example_content, (
            "BOOTSTRAP_SUPERADMIN_PASSWORD missing from .env.example — "
            "manual setup path broken (bootstrap_dev.py raises RuntimeError without it)"
        )

    def test_bootstrap_admin_password_key_present(self, env_example_content):
        assert "BOOTSTRAP_ADMIN_PASSWORD" in env_example_content, (
            "BOOTSTRAP_ADMIN_PASSWORD missing from .env.example"
        )

    def test_bootstrap_trader_password_key_present(self, env_example_content):
        assert "BOOTSTRAP_TRADER_PASSWORD" in env_example_content, (
            "BOOTSTRAP_TRADER_PASSWORD missing from .env.example"
        )

    def test_bootstrap_keys_have_change_me_placeholder(self, env_example_content):
        """Keys must have CHANGE_ME placeholders so operators know to replace them."""
        for key in (
            "BOOTSTRAP_SUPERADMIN_PASSWORD",
            "BOOTSTRAP_ADMIN_PASSWORD",
            "BOOTSTRAP_TRADER_PASSWORD",
        ):
            line = next(
                (ln for ln in env_example_content.splitlines() if ln.startswith(key + "=")),
                None,
            )
            assert line is not None, f"{key} line not found in .env.example"
            assert "CHANGE_ME" in line, (
                f"{key} in .env.example does not have a CHANGE_ME placeholder"
            )


# ---------------------------------------------------------------------------
# 5. auth.js roleRedirect — admin → /audit
# Pure-Python, no external deps — always runs.
# ---------------------------------------------------------------------------


class TestAuthJsRoleRedirect:
    """auth.js roleRedirect() must send admin to /audit, not /dashboard."""

    @pytest.fixture(scope="class")
    def auth_js_content(self):
        path = ROOT / "templates" / "auth.js"
        assert path.exists(), "templates/auth.js not found"
        return path.read_text()

    def test_role_redirect_function_present(self, auth_js_content):
        assert "function roleRedirect" in auth_js_content

    def test_admin_redirects_to_audit(self, auth_js_content):
        """roleRedirect must map admin → /audit."""
        lines = auth_js_content.splitlines()
        for i, line in enumerate(lines):
            if "role === 'admin'" in line:
                context = "\n".join(lines[i : i + 3])
                assert "/audit" in context, (
                    f"admin redirect block does not contain /audit:\n{context}\n"
                    "Expected /audit to match React Login.tsx resolveDestination()"
                )
                return
        pytest.fail("admin role check not found in auth.js")

    def test_admin_does_not_redirect_to_dashboard_in_role_redirect(self, auth_js_content):
        """The admin-specific redirect in roleRedirect must NOT go to /dashboard."""
        in_func = False
        brace_depth = 0
        lines = auth_js_content.splitlines()
        for line in lines:
            if "function roleRedirect" in line:
                in_func = True
            if not in_func:
                continue
            brace_depth += line.count("{") - line.count("}")
            if "role === 'admin'" in line and "/dashboard" in line:
                pytest.fail(
                    f"admin redirect in roleRedirect still points to /dashboard: {line.strip()!r}"
                )
            if in_func and brace_depth <= 0 and "{" in auth_js_content.split("function roleRedirect")[1][:10]:
                break

    def test_superadmin_redirects_to_superadmin(self, auth_js_content):
        """superadmin redirect must remain /superadmin."""
        found = any(
            "role === 'superadmin'" in line and "/superadmin" in line
            for line in auth_js_content.splitlines()
        )
        assert found, "superadmin redirect to /superadmin not found in auth.js"

    def test_require_role_admin_fallback_is_audit(self, auth_js_content):
        """requireRole insufficient-role fallback for admin must go to /audit."""
        lines = auth_js_content.splitlines()
        in_require_role = False
        for i, line in enumerate(lines):
            if "function requireRole" in line:
                in_require_role = True
            if in_require_role and "role === 'admin'" in line:
                context = "\n".join(lines[i : i + 3])
                assert "/audit" in context, (
                    f"requireRole admin fallback does not redirect to /audit:\n{context}"
                )
                return
        # No admin-specific branch in requireRole is also acceptable


# ---------------------------------------------------------------------------
# 1. impersonate_user() — token structure
# Requires fastapi + jwt — skipped in bare pytest venv.
# ---------------------------------------------------------------------------


class TestImpersonateToken:
    """The impersonation token must be accepted by decode_access_token()."""

    @pytest.fixture(autouse=True)
    def _require_deps(self):
        pytest.importorskip("fastapi", reason="fastapi not installed")
        pytest.importorskip("jwt", reason="PyJWT not installed")

    def _call_impersonate(self, target_user_id: str, secret: str = "a" * 32):
        import time

        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from api.auth import TokenPayload, require_role
        from api.superadmin.users import router

        app = FastAPI()
        app.include_router(router, prefix="/superadmin")
        dep = require_role("superadmin")
        app.dependency_overrides[dep] = lambda: TokenPayload(sub="sa-001", role="superadmin")

        mock_user = MagicMock()
        mock_user.id = target_user_id
        mock_user.username = "targetuser"
        mock_user.email = "target@hopefx.io"
        mock_user.role = "trader"

        mock_db = MagicMock()
        mock_db.query.return_value.filter_by.return_value.first.return_value = mock_user

        with (
            patch("api.superadmin.users.SessionLocal", return_value=mock_db),
            patch.dict(os.environ, {"SECURITY_JWT_SECRET": secret}),
        ):
            client = TestClient(app, raise_server_exceptions=True)
            return client.post(f"/superadmin/users/{target_user_id}/impersonate")

    def test_impersonate_returns_200(self):
        assert self._call_impersonate("user-abc").status_code == 200

    def test_impersonate_token_has_type_access(self):
        import jwt

        secret = "b" * 32
        resp = self._call_impersonate("user-abc", secret=secret)
        assert resp.status_code == 200
        payload = jwt.decode(resp.json()["access_token"], secret, algorithms=["HS256"])
        assert payload.get("type") == "access", (
            "impersonation token missing 'type':'access' — decode_access_token() will reject it"
        )

    def test_impersonate_token_has_jti(self):
        import jwt

        secret = "c" * 32
        resp = self._call_impersonate("user-abc", secret=secret)
        assert resp.status_code == 200
        payload = jwt.decode(resp.json()["access_token"], secret, algorithms=["HS256"])
        assert payload.get("jti"), (
            "impersonation token missing 'jti' — token cannot be revoked via blacklist"
        )

    def test_impersonate_token_accepted_by_decode_access_token(self):
        """decode_access_token() must accept the impersonation token without raising."""
        import jwt

        secret = "d" * 32
        resp = self._call_impersonate("user-abc", secret=secret)
        assert resp.status_code == 200

        with patch.dict(os.environ, {"SECURITY_JWT_SECRET": secret}):
            from auth.jwt import decode_access_token

            payload = decode_access_token(resp.json()["access_token"])
            assert payload["sub"] == "user-abc"
            assert payload["type"] == "access"

    def test_impersonate_token_carries_impersonated_by(self):
        import jwt

        secret = "e" * 32
        resp = self._call_impersonate("user-xyz", secret=secret)
        assert resp.status_code == 200
        payload = jwt.decode(resp.json()["access_token"], secret, algorithms=["HS256"])
        assert payload.get("impersonated_by") == "sa-001"

    def test_impersonate_superadmin_blocked(self):
        """Cannot impersonate another superadmin."""
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from api.auth import TokenPayload, require_role
        from api.superadmin.users import router

        app = FastAPI()
        app.include_router(router, prefix="/superadmin")
        dep = require_role("superadmin")
        app.dependency_overrides[dep] = lambda: TokenPayload(sub="sa-001", role="superadmin")

        mock_user = MagicMock()
        mock_user.id = "sa-002"
        mock_user.role = "superadmin"

        mock_db = MagicMock()
        mock_db.query.return_value.filter_by.return_value.first.return_value = mock_user

        with (
            patch("api.superadmin.users.SessionLocal", return_value=mock_db),
            patch.dict(os.environ, {"SECURITY_JWT_SECRET": "f" * 32}),
        ):
            resp = TestClient(app, raise_server_exceptions=False).post(
                "/superadmin/users/sa-002/impersonate"
            )

        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# 2. reset_user_password() — must use BLAKE2b+bcrypt
# Requires fastapi + bcrypt — skipped in bare pytest venv.
# ---------------------------------------------------------------------------


class TestResetUserPassword:
    """Temporary password set by reset_user_password() must verify at login."""

    @pytest.fixture(autouse=True)
    def _require_deps(self):
        pytest.importorskip("fastapi", reason="fastapi not installed")
        pytest.importorskip("bcrypt", reason="bcrypt not installed")

    def _call_reset(self, user_id: str = "user-001"):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from api.auth import TokenPayload, require_role
        from api.superadmin.users import router

        app = FastAPI()
        app.include_router(router, prefix="/superadmin")
        dep = require_role("superadmin")
        app.dependency_overrides[dep] = lambda: TokenPayload(sub="sa-001", role="superadmin")

        mock_user = MagicMock()
        mock_user.id = user_id
        mock_user.hashed_password = None

        mock_db = MagicMock()
        mock_db.query.return_value.filter_by.return_value.first.return_value = mock_user

        with patch("api.superadmin.users.SessionLocal", return_value=mock_db):
            resp = TestClient(app, raise_server_exceptions=True).post(
                f"/superadmin/users/{user_id}/reset-password"
            )

        return resp, mock_user

    def test_reset_returns_200_with_temp_password(self):
        resp, _ = self._call_reset()
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert "temp_password" in data
        assert len(data["temp_password"]) >= 16

    def test_reset_password_verifies_with_auth_jwt(self):
        """The stored hash must verify using auth.jwt.verify_password (BLAKE2b+bcrypt)."""
        from auth.jwt import verify_password

        resp, mock_user = self._call_reset()
        assert resp.status_code == 200
        temp_pw = resp.json()["temp_password"]
        stored_hash = mock_user.hashed_password

        assert stored_hash is not None, "hashed_password was never set on the user object"
        assert verify_password(temp_pw, stored_hash), (
            "reset_user_password() stored a hash that auth.jwt.verify_password() cannot verify — "
            "wrong hash scheme (raw passlib instead of BLAKE2b+bcrypt)"
        )

    def test_reset_password_wrong_password_fails(self):
        from auth.jwt import verify_password

        resp, mock_user = self._call_reset()
        assert resp.status_code == 200
        assert not verify_password("completely-wrong-password", mock_user.hashed_password)

    def test_reset_password_hash_is_bcrypt(self):
        """The stored hash must be a bcrypt hash (starts with $2b$ or $2a$)."""
        resp, mock_user = self._call_reset()
        assert resp.status_code == 200
        stored = mock_user.hashed_password
        assert stored.startswith(("$2b$", "$2a$")), (
            f"Expected bcrypt hash, got: {stored[:20]}..."
        )


# ---------------------------------------------------------------------------
# 3. Superadmin users API — real DB fields
# Requires fastapi — skipped in bare pytest venv.
# ---------------------------------------------------------------------------


class TestSuperadminUserStats:
    """plan/country come from User model; total_trades/revenue from DB queries."""

    @pytest.fixture(autouse=True)
    def _require_deps(self):
        pytest.importorskip("fastapi", reason="fastapi not installed")

    def _make_mock_user(self, plan="professional", country="GB"):
        from datetime import datetime, timezone

        u = MagicMock()
        u.id = "user-001"
        u.username = "testtrader"
        u.email = "trader@hopefx.io"
        u.role = "trader"
        u.plan = plan
        u.status = "active"
        u.country = country
        u.totp_enabled = False
        u.created_at = datetime(2025, 1, 1, tzinfo=timezone.utc)
        u.last_login_at = datetime(2025, 6, 1, tzinfo=timezone.utc)
        return u

    def _make_app(self):
        from fastapi import FastAPI

        from api.auth import TokenPayload, require_role
        from api.superadmin.users import router

        app = FastAPI()
        app.include_router(router, prefix="/superadmin")
        dep = require_role("superadmin")
        app.dependency_overrides[dep] = lambda: TokenPayload(sub="sa-001", role="superadmin")
        return app

    def _make_mock_db(self, user):
        mock_db = MagicMock()
        mock_db.query.return_value.filter_by.return_value.first.return_value = user
        mock_db.query.return_value.filter.return_value.all.return_value = []
        mock_db.query.return_value.filter.return_value.scalar.return_value = 0
        return mock_db

    def test_get_user_returns_real_plan(self):
        from fastapi.testclient import TestClient

        mock_user = self._make_mock_user(plan="enterprise", country="US")
        with patch("api.superadmin.users.SessionLocal", return_value=self._make_mock_db(mock_user)):
            resp = TestClient(self._make_app()).get("/superadmin/users/user-001")

        assert resp.status_code == 200
        data = resp.json()
        assert data["plan"] == "enterprise", (
            f"Expected plan='enterprise' from DB, got '{data['plan']}' — stub not replaced"
        )
        assert data["country"] == "US", (
            f"Expected country='US' from DB, got '{data['country']}' — stub not replaced"
        )

    def test_get_user_plan_not_hardcoded_free(self):
        from fastapi.testclient import TestClient

        mock_user = self._make_mock_user(plan="starter")
        with patch("api.superadmin.users.SessionLocal", return_value=self._make_mock_db(mock_user)):
            resp = TestClient(self._make_app()).get("/superadmin/users/user-001")

        assert resp.json()["plan"] == "starter"

    def test_country_not_hardcoded_none(self):
        from fastapi.testclient import TestClient

        mock_user = self._make_mock_user(country="DE")
        with patch("api.superadmin.users.SessionLocal", return_value=self._make_mock_db(mock_user)):
            resp = TestClient(self._make_app()).get("/superadmin/users/user-001")

        assert resp.json()["country"] == "DE", (
            "country is still hardcoded None — stub not replaced with real DB value"
        )

    def test_set_user_plan_persists_to_db(self):
        from fastapi.testclient import TestClient

        mock_user = self._make_mock_user(plan="free")
        mock_db = MagicMock()
        mock_db.query.return_value.filter_by.return_value.first.return_value = mock_user

        with patch("api.superadmin.users.SessionLocal", return_value=mock_db):
            resp = TestClient(self._make_app()).patch(
                "/superadmin/users/user-001/plan",
                json={"plan": "professional"},
            )

        assert resp.status_code == 200
        assert resp.json()["plan"] == "professional"
        assert mock_user.plan == "professional", (
            "set_user_plan() did not persist the plan change to the User row"
        )
        mock_db.commit.assert_called_once()

    def test_set_user_plan_rejects_invalid_plan(self):
        from fastapi.testclient import TestClient

        with patch("api.superadmin.users.SessionLocal", return_value=MagicMock()):
            resp = TestClient(self._make_app(), raise_server_exceptions=False).patch(
                "/superadmin/users/user-001/plan",
                json={"plan": "diamond"},
            )

        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# 6. setup_rate_limiting() — fail-loud behaviour
# Requires fastapi — skipped in bare pytest venv.
# ---------------------------------------------------------------------------


class TestSetupRateLimiting:
    """setup_rate_limiting() must raise in production and log CRITICAL in dev."""

    @pytest.fixture(autouse=True)
    def _require_deps(self):
        pytest.importorskip("fastapi", reason="fastapi not installed")

    def _call_setup_no_slowapi(self, app_env: str):
        """Call setup_rate_limiting with slowapi import forced to fail."""
        import sys

        from fastapi import FastAPI

        from api.platform import setup_rate_limiting

        test_app = FastAPI()

        # Force slowapi to be unimportable for this call
        saved = sys.modules.get("slowapi")
        sys.modules["slowapi"] = None  # type: ignore[assignment]
        try:
            with patch.dict(os.environ, {"APP_ENV": app_env}):
                return setup_rate_limiting(test_app)
        finally:
            if saved is not None:
                sys.modules["slowapi"] = saved
            else:
                sys.modules.pop("slowapi", None)

    def test_production_raises_on_missing_slowapi(self):
        """In production, missing slowapi must raise RuntimeError at startup."""
        with pytest.raises((RuntimeError, ImportError)):
            self._call_setup_no_slowapi("production")

    def test_development_returns_none_on_missing_slowapi(self):
        """In development, missing slowapi must return None (not crash)."""
        result = self._call_setup_no_slowapi("development")
        assert result is None

    def test_development_logs_critical_on_missing_slowapi(self, caplog):
        """In development, missing slowapi must log at CRITICAL level."""
        import logging

        with caplog.at_level(logging.CRITICAL, logger="api.platform"):
            self._call_setup_no_slowapi("development")

        assert any(r.levelno >= logging.CRITICAL for r in caplog.records), (
            "Expected a CRITICAL log when slowapi is missing in development"
        )

    def test_slowapi_installed_returns_limiter(self):
        """When slowapi is installed, setup_rate_limiting must return a Limiter."""
        try:
            import slowapi  # noqa: F401
        except ImportError:
            pytest.skip("slowapi not installed in this environment")

        from fastapi import FastAPI

        from api.platform import setup_rate_limiting

        test_app = FastAPI()
        with patch.dict(os.environ, {"APP_ENV": "development"}):
            result = setup_rate_limiting(test_app)

        assert result is not None


# ---------------------------------------------------------------------------
# 7. User model — plan and country columns exist
# Requires sqlalchemy — skipped in bare pytest venv.
# ---------------------------------------------------------------------------


class TestUserModelColumns:
    """User model must have plan and country columns after the migration."""

    @pytest.fixture(autouse=True)
    def _require_deps(self):
        pytest.importorskip("sqlalchemy", reason="sqlalchemy not installed")

    def _get_columns(self):
        from sqlalchemy import create_engine
        from sqlalchemy import inspect as sa_inspect

        from database.models import Base
        import database.user_models  # noqa: F401 — registers User with Base

        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        return {c["name"] for c in sa_inspect(engine).get_columns("users")}

    def test_user_has_plan_column(self):
        assert "plan" in self._get_columns(), (
            "'plan' column missing from users table — migration g1h2i3j4k5l6 not applied"
        )

    def test_user_has_country_column(self):
        assert "country" in self._get_columns(), (
            "'country' column missing from users table — migration g1h2i3j4k5l6 not applied"
        )

    def test_user_plan_default_is_free(self):
        from database.user_models import User

        u = User(
            id=str(uuid.uuid4()),
            email="test@hopefx.io",
            username="testuser",
            hashed_password="$2b$12$fakehash",
        )
        assert u.plan == "free", f"Expected default plan='free', got '{u.plan}'"

    def test_user_country_default_is_none(self):
        from database.user_models import User

        u = User(
            id=str(uuid.uuid4()),
            email="test2@hopefx.io",
            username="testuser2",
            hashed_password="$2b$12$fakehash",
        )
        assert u.country is None, f"Expected default country=None, got '{u.country}'"

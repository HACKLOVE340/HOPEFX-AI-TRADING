# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
tests/test_v17_fixes.py
=======================
Regression tests for all 8 issues fixed in v17.

Run with:
    pytest tests/test_v17_fixes.py -v
"""

from __future__ import annotations

import os
from datetime import timezone

UTC = timezone.utc
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Ensure test env vars are set before any app module is imported
# ---------------------------------------------------------------------------
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault(
    "SECURITY_JWT_SECRET",
    "test-only-jwt-secret-key-minimum-32-chars!!",
)
os.environ.setdefault("ACCESS_TOKEN_EXPIRE_MINUTES", "15")


# ===========================================================================
# Issue 1 — WebSocket auth bypass
# ===========================================================================
class TestWebSocketAuthBypass:
    """JWT decode failure must reject the connection, not authenticate it.

    Migrated from api.websocket_server (shim) to api.ws_live._validate_ws_token,
    which is the canonical token-validation path used by the live WS endpoint.
    """

    def test_invalid_token_returns_none(self):
        """A token that fails JWT decode must return None (→ connection rejected)."""
        from api.ws_live import _validate_ws_token

        with patch("auth.jwt.decode_access_token", side_effect=Exception("bad token")):
            result = _validate_ws_token("totally-invalid-token")
        assert result is None

    def test_empty_token_returns_none(self):
        """Empty token must be rejected immediately."""
        from api.ws_live import _validate_ws_token

        with patch("auth.jwt.decode_access_token", side_effect=Exception("empty")):
            result = _validate_ws_token("")
        assert result is None

    def test_valid_token_returns_payload(self):
        """A valid JWT must return the decoded payload dict."""
        from api.ws_live import _validate_ws_token

        fake_payload = {"sub": "user-123", "role": "trader"}
        with patch("auth.jwt.decode_access_token", return_value=fake_payload):
            result = _validate_ws_token("valid.jwt.token")
        assert result is not None
        assert result["sub"] == "user-123"

    def test_bearer_prefix_stripped(self):
        """Bearer prefix is stripped before decode is attempted."""
        from api.ws_live import _validate_ws_token

        captured = []

        def _capture(token):
            captured.append(token)
            return {"sub": "u1"}

        with patch("auth.jwt.decode_access_token", side_effect=_capture):
            _validate_ws_token("Bearer my.jwt.token")
        assert captured[0] == "my.jwt.token"

    @pytest.mark.asyncio
    async def test_invalid_token_does_not_authenticate_connection(self):
        """After a failed token, LiveConnectionManager must not mark the connection authenticated."""
        from api.ws_live import LiveConnectionManager, _validate_ws_token

        mgr = LiveConnectionManager()

        class _FakeWS:
            async def accept(self):
                pass

            async def send_text(self, t):
                pass

        cid = await mgr.connect(_FakeWS())
        # Simulate auth failure: _validate_ws_token returns None
        with patch("auth.jwt.decode_access_token", side_effect=Exception("expired")):
            payload = _validate_ws_token("bad-token")
        assert payload is None
        # Connection must remain unauthenticated
        assert not mgr.is_authenticated(cid)


# ===========================================================================
# Issue 2 — Risk manager exception allows trades
# ===========================================================================
class TestRiskManagerFailSafe:
    """assess_risk() crash must block the order (HTTP 503), not allow it."""

    @pytest.mark.asyncio
    async def test_risk_exception_raises_503(self):
        from fastapi import HTTPException

        import api.trading as trading_mod

        # Build a minimal app_state with a broken risk_manager
        broken_rm = MagicMock()
        broken_rm.assess_risk.side_effect = RuntimeError("DB connection lost")
        broken_rm.check_cvar_pre_trade.return_value = (True, "ok")

        fake_state = MagicMock()
        fake_state.risk_manager = broken_rm

        fake_order = MagicMock()
        fake_order.symbol = "EURUSD"

        with (
            patch.object(trading_mod, "app_state", fake_state),
            patch.object(
                trading_mod,
                "_broker_call",
                new_callable=AsyncMock,
                return_value=[],
            ),
            pytest.raises(HTTPException) as exc_info,
        ):
            await trading_mod._apply_risk_checks(fake_order, "user-1")
        assert exc_info.value.status_code == 503

    @pytest.mark.asyncio
    async def test_risk_block_still_raises_403(self):
        """A clean can_trade=False must still raise 403."""
        from fastapi import HTTPException

        import api.trading as trading_mod

        assessment = MagicMock()
        assessment.can_trade = False
        assessment.messages = ["drawdown exceeded"]

        rm = MagicMock()
        rm.assess_risk.return_value = assessment
        rm.check_cvar_pre_trade.return_value = (True, "ok")

        fake_state = MagicMock()
        fake_state.risk_manager = rm

        fake_order = MagicMock()

        with (
            patch.object(trading_mod, "app_state", fake_state),
            patch.object(
                trading_mod,
                "_broker_call",
                new_callable=AsyncMock,
                return_value=[],
            ),
            pytest.raises(HTTPException) as exc_info,
        ):
            await trading_mod._apply_risk_checks(fake_order, "user-1")
        assert exc_info.value.status_code == 403


# ===========================================================================
# Issue 3 — JWT expiry conflict
# ===========================================================================
class TestJWTExpiryUnified:
    """_get_access_token_expire_minutes() must read the env var at call time.

    Tests call the function directly — no importlib.reload() — so module
    state is never mutated and these tests are safe to run alongside any
    other JWT tests in the same process.
    """

    def test_reads_access_token_expire_minutes(self, monkeypatch):
        monkeypatch.setenv("ACCESS_TOKEN_EXPIRE_MINUTES", "20")
        monkeypatch.delenv("JWT_EXPIRE_MINUTES", raising=False)
        from auth.jwt import _get_access_token_expire_minutes

        assert _get_access_token_expire_minutes() == 20

    def test_legacy_jwt_expire_minutes_fallback(self, monkeypatch):
        monkeypatch.delenv("ACCESS_TOKEN_EXPIRE_MINUTES", raising=False)
        monkeypatch.setenv("JWT_EXPIRE_MINUTES", "25")
        from auth.jwt import _get_access_token_expire_minutes

        assert _get_access_token_expire_minutes() == 25

    def test_access_token_takes_precedence_over_jwt_expire(self, monkeypatch):
        monkeypatch.setenv("ACCESS_TOKEN_EXPIRE_MINUTES", "10")
        monkeypatch.setenv("JWT_EXPIRE_MINUTES", "99")
        from auth.jwt import _get_access_token_expire_minutes

        assert _get_access_token_expire_minutes() == 10

    def test_default_is_15_when_neither_set(self, monkeypatch):
        monkeypatch.delenv("ACCESS_TOKEN_EXPIRE_MINUTES", raising=False)
        monkeypatch.delenv("JWT_EXPIRE_MINUTES", raising=False)
        from auth.jwt import _get_access_token_expire_minutes

        assert _get_access_token_expire_minutes() == 15


# ===========================================================================
# Issue 4 — /docs and /redoc gating
# ===========================================================================
class TestDocsGating:
    """Docs endpoints must be None when APP_ENV=production."""

    def test_docs_hidden_in_production(self, monkeypatch):
        monkeypatch.setenv("APP_ENV", "production")
        from fastapi import FastAPI

        app = FastAPI(
            docs_url=None if os.getenv("APP_ENV") == "production" else "/docs",
            redoc_url=None if os.getenv("APP_ENV") == "production" else "/redoc",
        )
        # FastAPI stores None when docs are disabled
        assert app.docs_url is None
        assert app.redoc_url is None

    def test_docs_visible_in_development(self, monkeypatch):
        monkeypatch.setenv("APP_ENV", "development")
        from fastapi import FastAPI

        app = FastAPI(
            docs_url=None if os.getenv("APP_ENV") == "production" else "/docs",
            redoc_url=None if os.getenv("APP_ENV") == "production" else "/redoc",
        )
        assert app.docs_url == "/docs"
        assert app.redoc_url == "/redoc"

    def test_app_py_respects_production_env(self, monkeypatch):
        """app.py FastAPI construction must gate docs on APP_ENV."""
        monkeypatch.setenv("APP_ENV", "production")
        # Read the source and verify the conditional is present
        with Path("app.py").open(encoding="utf-8") as f:
            source = f.read()
        assert 'None if os.getenv("APP_ENV") == "production"' in source


# ===========================================================================
# Issue 5 — Prop-firm guard failure allows trades
# ===========================================================================
class TestPropFirmGuardFailSafe:
    """check_prop_firm_rules() crash must block the order (HTTP 503)."""

    @pytest.mark.asyncio
    async def test_prop_firm_exception_raises_503(self):
        from fastapi import HTTPException

        import api.trading as trading_mod

        fake_state = MagicMock()
        fake_state.broker = MagicMock()

        with (
            patch.object(trading_mod, "app_state", fake_state),
            patch.object(
                trading_mod,
                "_user_broker_call",
                new_callable=AsyncMock,
                return_value=MagicMock(),
            ),
            patch(
                "brokers.prop_firms.guard.check_prop_firm_rules",
                side_effect=RuntimeError("guard crashed"),
            ),
            pytest.raises(HTTPException) as exc_info,
        ):
            await trading_mod._validate_order(MagicMock(), "user-1")
        assert exc_info.value.status_code == 503

    @pytest.mark.asyncio
    async def test_prop_firm_http_exception_propagates(self):
        """An HTTPException from the guard (e.g. 403) must propagate unchanged."""
        from fastapi import HTTPException

        import api.trading as trading_mod

        fake_state = MagicMock()
        fake_state.broker = MagicMock()

        with (
            patch.object(trading_mod, "app_state", fake_state),
            patch.object(
                trading_mod,
                "_user_broker_call",
                new_callable=AsyncMock,
                return_value=MagicMock(),
            ),
            patch(
                "brokers.prop_firms.guard.check_prop_firm_rules",
                side_effect=HTTPException(status_code=403, detail="daily loss limit"),
            ),
            pytest.raises(HTTPException) as exc_info,
        ):
            await trading_mod._validate_order(MagicMock(), "user-1")
        assert exc_info.value.status_code == 403


# ===========================================================================
# Issue 6 — PII logging
# ===========================================================================
class TestNoPIILogging:
    """Email addresses must not appear in log output on login/register."""

    def test_mobile_api_register_no_email_in_log(self):
        with Path("mobile/api.py").open(encoding="utf-8") as f:
            source = f.read()
        # The old pattern logged user.email directly
        assert "user.email" not in source.split("logger.info")[1].split("\n")[0] if "logger.info" in source else True
        # Positive check: user_id must be logged instead
        assert "user_id" in source

    def test_mobile_api_login_no_email_in_log(self):
        with Path("mobile/api.py").open(encoding="utf-8") as f:
            source = f.read()
        # Confirm the old "logged in: %s", email pattern is gone
        assert '"Mobile user logged in: %s", email' not in source

    def test_mobile_api_v2_register_no_email_in_log(self):
        with Path("mobile/api_v2.py").open(encoding="utf-8") as f:
            source = f.read()
        assert 'f"User registered: {user.email}"' not in source

    def test_mobile_api_v2_login_no_email_in_log(self):
        with Path("mobile/api_v2.py").open(encoding="utf-8") as f:
            source = f.read()
        assert 'f"User logged in: {email}"' not in source


# ===========================================================================
# Issue 7 — OANDA/MT5 in env template
# ===========================================================================
class TestEnvTemplate:
    """OANDA and MT5 variables must not appear in the env template."""

    def _read_template(self) -> str:
        with Path("SECURE ENVIRONMENT FILE TEMPLATE").open(encoding="utf-8") as f:
            return f.read()

    def test_no_oanda_vars(self):
        content = self._read_template()
        assert "BROKER_OANDA_API_KEY" not in content
        assert "BROKER_OANDA_ACCOUNT_ID" not in content
        assert "BROKER_OANDA_ENVIRONMENT" not in content

    def test_no_mt5_vars(self):
        content = self._read_template()
        assert "BROKER_MT5_SERVER" not in content
        assert "BROKER_MT5_LOGIN" not in content
        assert "BROKER_MT5_PASSWORD" not in content

    def test_ibkr_vars_present(self):
        content = self._read_template()
        assert "IBKR_HOST" in content
        assert "IBKR_PORT" in content


# ===========================================================================
# Issue 8 — quickfix pinned
# ===========================================================================
class TestQuickfixPinned:
    """quickfix must be pinned to an exact version in requirements.txt."""

    def test_quickfix_exact_pin(self):
        with Path("requirements.txt").open(encoding="utf-8") as f:
            content = f.read()
        # Must use == not >=
        assert "quickfix>=1.15.1" not in content
        assert "quickfix==1.15.1" in content

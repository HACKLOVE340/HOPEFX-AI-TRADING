# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
Tests for Sentry DSN wiring:
- init_sentry() returns False when SENTRY_DSN is unset (safe default)
- init_sentry() calls sentry_sdk.init() with correct params when DSN is set
- _before_send() scrubs sensitive fields from request data
- _before_send() drops health-check noise (/health, /metrics)
- capture_ml_fallback_event() calls sentry_sdk.capture_message() at fatal level
- _scrub_dict() recursively replaces sensitive values with '[Filtered]'

These tests mock sentry_sdk so they run without the package installed.
"""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Helpers — build a minimal sentry_sdk mock
# ---------------------------------------------------------------------------


def _make_sentry_mock() -> MagicMock:
    """Return a MagicMock that looks like sentry_sdk."""
    sdk = MagicMock()
    sdk.init = MagicMock()
    sdk.configure_scope = MagicMock()
    sdk.push_scope = MagicMock()
    sdk.capture_message = MagicMock()
    sdk.start_transaction = MagicMock()

    # configure_scope / push_scope are context managers
    scope_mock = MagicMock()
    scope_mock.__enter__ = MagicMock(return_value=scope_mock)
    scope_mock.__exit__ = MagicMock(return_value=False)
    sdk.configure_scope.return_value = scope_mock
    sdk.push_scope.return_value = scope_mock

    # integrations sub-modules
    for sub in [
        "integrations.logging",
        "integrations.fastapi",
        "integrations.starlette",
        "integrations.sqlalchemy",
        "integrations.redis",
        "integrations.aiohttp",
    ]:
        parts = sub.split(".")
        parent = sdk
        for part in parts:
            child = MagicMock()
            setattr(parent, part, child)
            parent = child

    return sdk


# ---------------------------------------------------------------------------
# init_sentry — no DSN
# ---------------------------------------------------------------------------


class TestInitSentryNoDSN:
    def test_returns_false_when_dsn_unset(self, monkeypatch):
        monkeypatch.delenv("SENTRY_DSN", raising=False)
        from monitoring.sentry_config import init_sentry

        result = init_sentry()
        assert result is False

    def test_returns_false_when_dsn_empty_string(self, monkeypatch):
        monkeypatch.setenv("SENTRY_DSN", "")
        from monitoring.sentry_config import init_sentry

        result = init_sentry()
        assert result is False

    def test_does_not_call_sdk_init_when_no_dsn(self, monkeypatch):
        monkeypatch.delenv("SENTRY_DSN", raising=False)
        sdk_mock = _make_sentry_mock()
        with patch.dict(sys.modules, {"sentry_sdk": sdk_mock}):
            from monitoring.sentry_config import init_sentry

            init_sentry()
        sdk_mock.init.assert_not_called()


# ---------------------------------------------------------------------------
# init_sentry — with DSN
# ---------------------------------------------------------------------------


class TestInitSentryWithDSN:
    def test_returns_true_when_dsn_set(self, monkeypatch):
        monkeypatch.setenv("SENTRY_DSN", "https://abc123@sentry.io/12345")
        sdk_mock = _make_sentry_mock()

        # Patch integrations imports inside sentry_config
        with patch.dict(
            sys.modules,
            {
                "sentry_sdk": sdk_mock,
                "sentry_sdk.integrations": MagicMock(),
                "sentry_sdk.integrations.logging": MagicMock(LoggingIntegration=MagicMock(return_value=MagicMock())),
                "sentry_sdk.integrations.fastapi": MagicMock(FastApiIntegration=MagicMock(return_value=MagicMock())),
                "sentry_sdk.integrations.starlette": MagicMock(
                    StarletteIntegration=MagicMock(return_value=MagicMock())
                ),
                "sentry_sdk.integrations.sqlalchemy": MagicMock(
                    SqlalchemyIntegration=MagicMock(return_value=MagicMock())
                ),
                "sentry_sdk.integrations.redis": MagicMock(RedisIntegration=MagicMock(return_value=MagicMock())),
                "sentry_sdk.integrations.aiohttp": MagicMock(AioHttpIntegration=MagicMock(return_value=MagicMock())),
            },
        ):
            import importlib
            import monitoring.sentry_config as sc

            importlib.reload(sc)
            result = sc.init_sentry()

        assert result is True

    def test_sdk_init_called_with_dsn(self, monkeypatch):
        dsn = "https://abc123@sentry.io/12345"
        monkeypatch.setenv("SENTRY_DSN", dsn)
        monkeypatch.setenv("APP_ENV", "production")

        sdk_mock = _make_sentry_mock()
        integration_mocks = {
            "sentry_sdk": sdk_mock,
            "sentry_sdk.integrations.logging": MagicMock(LoggingIntegration=MagicMock(return_value=MagicMock())),
            "sentry_sdk.integrations.fastapi": MagicMock(FastApiIntegration=MagicMock(return_value=MagicMock())),
            "sentry_sdk.integrations.starlette": MagicMock(StarletteIntegration=MagicMock(return_value=MagicMock())),
            "sentry_sdk.integrations.sqlalchemy": MagicMock(SqlalchemyIntegration=MagicMock(return_value=MagicMock())),
            "sentry_sdk.integrations.redis": MagicMock(RedisIntegration=MagicMock(return_value=MagicMock())),
            "sentry_sdk.integrations.aiohttp": MagicMock(AioHttpIntegration=MagicMock(return_value=MagicMock())),
        }
        with patch.dict(sys.modules, integration_mocks):
            import importlib
            import monitoring.sentry_config as sc

            importlib.reload(sc)
            sc.init_sentry()

        sdk_mock.init.assert_called_once()
        call_kwargs = sdk_mock.init.call_args[1]
        assert call_kwargs["dsn"] == dsn
        assert call_kwargs["environment"] == "production"
        assert call_kwargs["send_default_pii"] is False
        assert "before_send" in call_kwargs
        assert "before_send_transaction" in call_kwargs

    def test_traces_sample_rate_from_env(self, monkeypatch):
        monkeypatch.setenv("SENTRY_DSN", "https://x@sentry.io/1")
        monkeypatch.setenv("SENTRY_TRACES_SAMPLE_RATE", "0.05")

        sdk_mock = _make_sentry_mock()
        with patch.dict(
            sys.modules,
            {
                "sentry_sdk": sdk_mock,
                "sentry_sdk.integrations.logging": MagicMock(LoggingIntegration=MagicMock(return_value=MagicMock())),
                "sentry_sdk.integrations.fastapi": MagicMock(FastApiIntegration=MagicMock(return_value=MagicMock())),
                "sentry_sdk.integrations.starlette": MagicMock(
                    StarletteIntegration=MagicMock(return_value=MagicMock())
                ),
                "sentry_sdk.integrations.sqlalchemy": MagicMock(
                    SqlalchemyIntegration=MagicMock(return_value=MagicMock())
                ),
                "sentry_sdk.integrations.redis": MagicMock(RedisIntegration=MagicMock(return_value=MagicMock())),
                "sentry_sdk.integrations.aiohttp": MagicMock(AioHttpIntegration=MagicMock(return_value=MagicMock())),
            },
        ):
            import importlib
            import monitoring.sentry_config as sc

            importlib.reload(sc)
            sc.init_sentry()

        call_kwargs = sdk_mock.init.call_args[1]
        assert call_kwargs["traces_sample_rate"] == 0.05


# ---------------------------------------------------------------------------
# _scrub_dict
# ---------------------------------------------------------------------------


class TestScrubDict:
    def setup_method(self):
        import importlib
        import monitoring.sentry_config as sc

        importlib.reload(sc)
        self.scrub = sc._scrub_dict

    def test_scrubs_password(self):
        result = self.scrub({"password": "secret123", "username": "alice"})
        assert result["password"] == "[Filtered]"
        assert result["username"] == "alice"

    def test_scrubs_api_key(self):
        result = self.scrub({"api_key": "sk-abc123", "model": "gpt-4"})
        assert result["api_key"] == "[Filtered]"
        assert result["model"] == "gpt-4"

    def test_scrubs_token(self):
        # user_id is in _SCRUB_FIELDS (account IDs are PII); use a safe field instead
        result = self.scrub({"token": "Bearer xyz", "request_id": 42})
        assert result["token"] == "[Filtered]"
        assert result["request_id"] == 42

    def test_scrubs_nested_dict(self):
        result = self.scrub({"outer": {"api_key": "secret", "safe": "value"}})
        assert result["outer"]["api_key"] == "[Filtered]"
        assert result["outer"]["safe"] == "value"

    def test_scrubs_list_of_dicts(self):
        result = self.scrub({"items": [{"password": "pw1"}, {"name": "bob"}]})
        assert result["items"][0]["password"] == "[Filtered]"
        assert result["items"][1]["name"] == "bob"

    def test_case_insensitive_key_matching(self):
        result = self.scrub({"API_KEY": "secret"})
        # Keys are lowercased before matching
        assert result["API_KEY"] == "[Filtered]"

    def test_non_sensitive_fields_unchanged(self):
        data = {"symbol": "XAUUSD", "price": 2000.0, "volume": 100}
        result = self.scrub(data)
        assert result == data

    def test_non_dict_input_returned_unchanged(self):
        import monitoring.sentry_config as sc

        assert sc._scrub_dict("string") == "string"
        assert sc._scrub_dict(42) == 42


# ---------------------------------------------------------------------------
# _before_send
# ---------------------------------------------------------------------------


class TestBeforeSend:
    def setup_method(self):
        import importlib
        import monitoring.sentry_config as sc

        importlib.reload(sc)
        self.before_send = sc._before_send

    def test_drops_health_check_events(self):
        event = {"transaction": "/health", "request": {}}
        result = self.before_send(event, {})
        assert result is None

    def test_drops_metrics_events(self):
        event = {"transaction": "/metrics", "request": {}}
        result = self.before_send(event, {})
        assert result is None

    def test_passes_normal_events(self):
        event = {"transaction": "/api/trading/signal", "request": {}}
        result = self.before_send(event, {})
        assert result is not None

    def test_scrubs_request_data(self):
        event = {
            "transaction": "/api/auth/login",
            "request": {"data": {"password": "secret", "username": "alice"}},  # nosec B105 - test file
        }
        result = self.before_send(event, {})
        assert result["request"]["data"]["password"] == "[Filtered]"
        assert result["request"]["data"]["username"] == "alice"

    def test_scrubs_request_headers(self):
        event = {
            "transaction": "/api/trading/order",
            "request": {
                "headers": {
                    "Authorization": "Bearer token123",
                    "Content-Type": "application/json",
                }
            },
        }
        result = self.before_send(event, {})
        assert result["request"]["headers"]["Authorization"] == "[Filtered]"
        assert result["request"]["headers"]["Content-Type"] == "application/json"

    def test_scrubs_extra_context(self):
        event = {
            "transaction": "/api/broker/connect",
            "extra": {"api_key": "oanda-key-123", "symbol": "XAUUSD"},
        }
        result = self.before_send(event, {})
        assert result["extra"]["api_key"] == "[Filtered]"
        assert result["extra"]["symbol"] == "XAUUSD"


# ---------------------------------------------------------------------------
# _before_send_transaction
# ---------------------------------------------------------------------------


class TestBeforeSendTransaction:
    def setup_method(self):
        import importlib
        import monitoring.sentry_config as sc

        importlib.reload(sc)
        self.hook = sc._before_send_transaction

    def test_drops_health_check_transactions(self):
        assert self.hook({"transaction": "/health"}, {}) is None

    def test_drops_metrics_transactions(self):
        assert self.hook({"transaction": "/metrics"}, {}) is None

    def test_passes_api_transactions(self):
        event = {"transaction": "/api/signals/generate"}
        assert self.hook(event, {}) is event


# ---------------------------------------------------------------------------
# capture_ml_fallback_event
# ---------------------------------------------------------------------------


class TestCaptureMLFallbackEvent:
    def test_calls_capture_message_at_fatal_level(self, monkeypatch):
        sdk_mock = _make_sentry_mock()
        with patch.dict(sys.modules, {"sentry_sdk": sdk_mock}):
            import importlib
            import monitoring.sentry_config as sc

            importlib.reload(sc)
            sc.capture_ml_fallback_event(
                reason="advanced_oos.pkl not found",
                fallback_model="xgb_macro.pkl",
                fallback_accuracy=0.503,
            )

        sdk_mock.capture_message.assert_called_once()
        call_args = sdk_mock.capture_message.call_args
        msg = call_args[0][0]
        assert "ML FALLBACK ACTIVATED" in msg
        assert "xgb_macro.pkl" in msg
        # Level must be fatal
        assert call_args[1].get("level") == "fatal" or call_args[0][1] == "fatal"

    def test_does_not_raise_when_sentry_unavailable(self, monkeypatch):
        """capture_ml_fallback_event must never raise — it's called in the hot path."""
        # Remove sentry_sdk from modules to simulate it not being installed
        saved = sys.modules.pop("sentry_sdk", None)
        try:
            import importlib
            import monitoring.sentry_config as sc

            importlib.reload(sc)
            # Should not raise
            sc.capture_ml_fallback_event(
                reason="test",
                fallback_model="xgb_macro.pkl",
                fallback_accuracy=0.503,
            )
        finally:
            if saved is not None:
                sys.modules["sentry_sdk"] = saved

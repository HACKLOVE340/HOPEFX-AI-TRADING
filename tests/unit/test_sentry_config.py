# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
tests/unit/test_sentry_config.py
=================================
Unit tests for monitoring/sentry_config.py.

Verifies:
- init_sentry() returns False when SENTRY_DSN is unset (safe default)
- init_sentry() returns True when a DSN is provided
- _scrub_dict() redacts all sensitive field names
- _before_send() drops health-check noise
- _before_send() preserves normal events
- capture_ml_fallback_event() does not raise when Sentry is uninitialised
- start_transaction() returns a no-op context manager when Sentry is off
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_event(transaction: str = "/api/signals") -> dict[str, Any]:
    return {
        "transaction": transaction,
        "request": {
            "data": {"username": "alice", "password": "s3cr3t"},  # nosec B105 - test file
            "headers": {"Authorization": "Bearer tok123"},
        },
        "extra": {"api_key": "key_abc", "note": "ok"},
    }


# ── init_sentry ───────────────────────────────────────────────────────────────


class TestInitSentry:
    def test_returns_false_when_dsn_unset(self, monkeypatch):
        monkeypatch.delenv("SENTRY_DSN", raising=False)
        from monitoring.sentry_config import init_sentry

        assert init_sentry() is False

    def test_returns_true_when_dsn_set(self, monkeypatch):
        monkeypatch.setenv("SENTRY_DSN", "https://fake@o0.ingest.sentry.io/0")
        monkeypatch.setenv("APP_ENV", "production")
        from monitoring.sentry_config import init_sentry

        assert init_sentry() is True

    def test_returns_false_when_sentry_sdk_missing(self, monkeypatch):
        monkeypatch.setenv("SENTRY_DSN", "https://fake@o0.ingest.sentry.io/0")
        with patch.dict("sys.modules", {"sentry_sdk": None}):
            # Re-import to pick up the patched sys.modules
            import importlib

            import monitoring.sentry_config as sc

            importlib.reload(sc)
            result = sc.init_sentry()
        assert result is False


# ── _scrub_dict ───────────────────────────────────────────────────────────────


class TestScrubDict:
    def setup_method(self):
        from monitoring.sentry_config import _scrub_dict

        self._scrub = _scrub_dict

    def test_scrubs_password(self):
        out = self._scrub({"password": "hunter2", "username": "alice"})
        assert out["password"] == "[Filtered]"
        assert out["username"] == "alice"

    def test_scrubs_api_key(self):
        out = self._scrub({"api_key": "sk-abc123"})
        assert out["api_key"] == "[Filtered]"

    def test_scrubs_authorization_header(self):
        out = self._scrub({"authorization": "Bearer tok"})
        assert out["authorization"] == "[Filtered]"

    def test_scrubs_nested_dict(self):
        out = self._scrub({"outer": {"token": "t", "safe": "yes"}})
        assert out["outer"]["token"] == "[Filtered]"
        assert out["outer"]["safe"] == "yes"

    def test_scrubs_list_of_dicts(self):
        out = self._scrub({"items": [{"secret": "x"}, {"safe": "y"}]})
        assert out["items"][0]["secret"] == "[Filtered]"
        assert out["items"][1]["safe"] == "y"

    def test_preserves_non_sensitive_fields(self):
        out = self._scrub({"symbol": "XAUUSD", "price": 2050.0})
        assert out == {"symbol": "XAUUSD", "price": 2050.0}

    def test_handles_non_dict_input(self):
        from monitoring.sentry_config import _scrub_dict

        assert _scrub_dict("plain string") == "plain string"  # type: ignore[arg-type]


# ── _before_send ──────────────────────────────────────────────────────────────


class TestBeforeSend:
    def setup_method(self):
        from monitoring.sentry_config import _before_send

        self._hook = _before_send

    def test_drops_health_check(self):
        event = _make_event(transaction="/health")
        assert self._hook(event, {}) is None

    def test_drops_metrics(self):
        event = _make_event(transaction="/metrics")
        assert self._hook(event, {}) is None

    def test_drops_favicon(self):
        event = _make_event(transaction="/favicon.ico")
        assert self._hook(event, {}) is None

    def test_passes_normal_event(self):
        event = _make_event(transaction="/api/signals")
        result = self._hook(event, {})
        assert result is not None

    def test_scrubs_password_in_request_data(self):
        event = _make_event()
        result = self._hook(event, {})
        assert result["request"]["data"]["password"] == "[Filtered]"
        assert result["request"]["data"]["username"] == "alice"

    def test_scrubs_authorization_header(self):
        event = _make_event()
        result = self._hook(event, {})
        assert result["request"]["headers"]["Authorization"] == "[Filtered]"

    def test_scrubs_extra_api_key(self):
        event = _make_event()
        result = self._hook(event, {})
        assert result["extra"]["api_key"] == "[Filtered]"
        assert result["extra"]["note"] == "ok"


# ── _before_send_transaction ──────────────────────────────────────────────────


class TestBeforeSendTransaction:
    def setup_method(self):
        from monitoring.sentry_config import _before_send_transaction

        self._hook = _before_send_transaction

    def test_drops_health(self):
        assert self._hook({"transaction": "/health"}, {}) is None

    def test_passes_api_transaction(self):
        event = {"transaction": "/api/trading/order"}
        assert self._hook(event, {}) is event


# ── capture_ml_fallback_event ─────────────────────────────────────────────────


class TestCaptureMlFallbackEvent:
    def test_does_not_raise_when_sentry_uninitialised(self):
        """Must be safe to call even when Sentry SDK is not initialised."""
        from monitoring.sentry_config import capture_ml_fallback_event

        # Should not raise regardless of Sentry state
        capture_ml_fallback_event(
            reason="advanced_oos.pkl not found",
            fallback_model="xgb_macro.pkl",
            fallback_accuracy=0.503,
        )

    def test_calls_sentry_capture_message(self, monkeypatch):
        mock_sdk = MagicMock()
        mock_scope = MagicMock()
        mock_sdk.push_scope.return_value.__enter__ = MagicMock(return_value=mock_scope)
        mock_sdk.push_scope.return_value.__exit__ = MagicMock(return_value=False)

        with patch.dict("sys.modules", {"sentry_sdk": mock_sdk}):
            from monitoring import sentry_config

            sentry_config.capture_ml_fallback_event(
                reason="test",
                fallback_model="xgb_macro.pkl",
                fallback_accuracy=0.503,
            )
        mock_sdk.capture_message.assert_called_once()
        call_args = mock_sdk.capture_message.call_args
        assert "ML FALLBACK" in call_args[0][0]
        assert call_args[1]["level"] == "fatal"


# ── start_transaction ─────────────────────────────────────────────────────────


class TestStartTransaction:
    def test_returns_context_manager_when_sentry_off(self, monkeypatch):
        monkeypatch.delenv("SENTRY_DSN", raising=False)
        from monitoring.sentry_config import start_transaction

        with start_transaction("test_task", op="task") as txn:
            txn.set_tag("k", "v")  # must not raise

    def test_returns_sentry_transaction_when_on(self, monkeypatch):
        monkeypatch.setenv("SENTRY_DSN", "https://fake@o0.ingest.sentry.io/0")
        mock_sdk = MagicMock()
        mock_txn = MagicMock()
        mock_sdk.start_transaction.return_value = mock_txn
        with patch.dict("sys.modules", {"sentry_sdk": mock_sdk}):
            from monitoring import sentry_config

            result = sentry_config.start_transaction("my_task", op="task")
        assert result is mock_txn

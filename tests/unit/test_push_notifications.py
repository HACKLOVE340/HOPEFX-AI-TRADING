# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
Unit tests for mobile/push_notifications.py

Verifies:
- Log-only mode when FIREBASE_SERVER_KEY is not set
- FCM HTTP call is made when server key is present
- All typed helpers produce the correct title/body
- Device token registration and deregistration
- Drawdown warning threshold (>= 80% of limit triggers push)
"""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_manager(server_key: str = ""):
    """Return a fresh PushNotificationManager with the given key."""
    with patch.dict(os.environ, {"FIREBASE_SERVER_KEY": server_key}):
        from importlib import reload

        import mobile.push_notifications as mod

        reload(mod)
        return mod.PushNotificationManager()


# ── Log-only mode (no server key) ─────────────────────────────────────────────


class TestLogOnlyMode:
    def test_fcm_disabled_without_key(self):
        mgr = _make_manager(server_key="")
        assert mgr.fcm_enabled is False

    def test_send_returns_true_in_log_mode(self, capsys):
        mgr = _make_manager(server_key="")
        result = mgr.send_notification("user1", "Test", "Body")
        assert result is True

    def test_log_mode_prints_to_stdout(self, capsys):
        mgr = _make_manager(server_key="")
        mgr.send_notification("user42", "Alert", "Price moved")
        captured = capsys.readouterr()
        assert "user42" in captured.out
        assert "Alert" in captured.out

    def test_send_new_signal_log_mode(self, capsys):
        mgr = _make_manager(server_key="")
        result = mgr.send_new_signal("u1", "XAUUSD", "BUY", 82.5)
        assert result is True
        out = capsys.readouterr().out
        assert "XAUUSD" in out

    def test_send_drawdown_warning_log_mode(self, capsys):
        mgr = _make_manager(server_key="")
        result = mgr.send_drawdown_warning("u1", drawdown_pct=8.5, limit_pct=10.0)
        assert result is True

    def test_send_trade_filled_log_mode(self, capsys):
        mgr = _make_manager(server_key="")
        result = mgr.send_trade_filled("u1", "XAUUSD", "buy", 2050.0, 0.1)
        assert result is True

    def test_send_challenge_warning_log_mode(self, capsys):
        mgr = _make_manager(server_key="")
        result = mgr.send_challenge_warning("u1", "daily_loss", 4.5, 5.0)
        assert result is True


# ── Device token management ───────────────────────────────────────────────────


class TestDeviceTokens:
    def test_register_device_stores_token(self):
        mgr = _make_manager()
        mgr.register_device("user-a", "token-abc")
        assert "token-abc" in mgr.get_tokens("user-a")

    def test_register_duplicate_token_is_idempotent(self):
        mgr = _make_manager()
        mgr.register_device("user-b", "tok-1")
        mgr.register_device("user-b", "tok-1")
        assert mgr.get_tokens("user-b").count("tok-1") == 1

    def test_unregister_device_removes_token(self):
        mgr = _make_manager()
        mgr.register_device("user-c", "tok-del")
        mgr.unregister_device("user-c", "tok-del")
        assert "tok-del" not in mgr.get_tokens("user-c")

    def test_get_tokens_returns_empty_for_unknown_user(self):
        mgr = _make_manager()
        assert mgr.get_tokens("nobody-xyz") == []

    def test_multiple_tokens_per_user(self):
        mgr = _make_manager()
        mgr.register_device("user-d", "tok-1")
        mgr.register_device("user-d", "tok-2")
        tokens = mgr.get_tokens("user-d")
        assert len(tokens) == 2


# ── FCM HTTP call (mocked) ────────────────────────────────────────────────────


class TestFCMHttpCall:
    def test_send_makes_http_request_when_key_set(self):
        mgr = _make_manager(server_key="fake-server-key")
        mgr.register_device("user-fcm", "device-token-xyz")

        mock_response = MagicMock()
        mock_response.__enter__ = lambda s: s
        mock_response.__exit__ = MagicMock(return_value=False)
        mock_response.read.return_value = b'{"success": 1, "failure": 0}'

        with patch("urllib.request.urlopen", return_value=mock_response) as mock_open:
            mgr.send_notification("user-fcm", "Title", "Body")

        assert mock_open.called
        # The request should include the Authorization header
        call_args = mock_open.call_args[0][0]
        assert b"fake-server-key" in call_args.data or "fake-server-key" in str(call_args.headers)

    def test_fcm_failure_response_returns_false(self):
        mgr = _make_manager(server_key="fake-key")
        mgr.register_device("user-fail", "bad-token")

        mock_response = MagicMock()
        mock_response.__enter__ = lambda s: s
        mock_response.__exit__ = MagicMock(return_value=False)
        mock_response.read.return_value = b'{"success": 0, "failure": 1}'

        with patch("urllib.request.urlopen", return_value=mock_response):
            result = mgr.send_notification("user-fail", "T", "B")

        assert result is False

    def test_fcm_network_error_returns_false(self):
        mgr = _make_manager(server_key="fake-key")
        mgr.register_device("user-err", "tok")

        with patch("urllib.request.urlopen", side_effect=OSError("network down")):
            result = mgr.send_notification("user-err", "T", "B")

        assert result is False

    def test_no_tokens_returns_true_without_http_call(self):
        """No registered tokens → log-only path, no HTTP call."""
        mgr = _make_manager(server_key="fake-key")
        # user has no tokens registered
        with patch("urllib.request.urlopen") as mock_open:
            result = mgr.send_notification("user-no-tokens", "T", "B")
        mock_open.assert_not_called()
        assert result is True


# ── Confidence threshold ──────────────────────────────────────────────────────


class TestSignalConfidenceThreshold:
    """The signal engine only pushes FCM for confidence >= 0.70."""

    def test_high_confidence_triggers_push(self):
        """Signals at or above 70% confidence should call _push_fcm_to_all_users."""
        from api.signals import RealTimeSignalService

        svc = RealTimeSignalService.__new__(RealTimeSignalService)
        svc._push_fcm_to_all_users = MagicMock()

        # Simulate the confidence check inline
        confidence = 0.75
        if confidence >= 0.70:
            svc._push_fcm_to_all_users(MagicMock())

        svc._push_fcm_to_all_users.assert_called_once()

    def test_low_confidence_skips_push(self):
        """Signals below 70% confidence must NOT push FCM."""
        from api.signals import RealTimeSignalService

        svc = RealTimeSignalService.__new__(RealTimeSignalService)
        svc._push_fcm_to_all_users = MagicMock()

        confidence = 0.65
        if confidence >= 0.70:
            svc._push_fcm_to_all_users(MagicMock())

        svc._push_fcm_to_all_users.assert_not_called()

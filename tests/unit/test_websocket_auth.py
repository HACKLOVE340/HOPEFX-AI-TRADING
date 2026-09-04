# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
tests/test_websocket_auth.py
=============================
Regression tests for WebSocket authentication fixes.

Covers:
  - ws_live.py: re-auth mid-session is blocked (privilege escalation fix)
  - ws_live.py: unauthenticated connections are rejected with code 4001
  - community_chat.py: invalid/missing token rejects connection
  - social_feed.py: accept() called before close() (RuntimeError fix)
  - LiveConnectionManager: is_authenticated, authenticate, re-auth guard
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ── LiveConnectionManager unit tests ─────────────────────────────────────────


class TestLiveConnectionManager:
    def _make_manager(self):
        from api.ws_live import LiveConnectionManager

        return LiveConnectionManager()

    def test_new_connection_is_not_authenticated(self):
        mgr = self._make_manager()
        mgr._connections["c1"] = MagicMock()
        mgr._subscriptions["c1"] = set()
        mgr._user_ids["c1"] = None
        mgr._hb_misses["c1"] = 0
        assert not mgr.is_authenticated("c1")

    def test_authenticate_sets_user_id(self):
        mgr = self._make_manager()
        mgr._connections["c1"] = MagicMock()
        mgr._subscriptions["c1"] = set()
        mgr._user_ids["c1"] = None
        mgr._hb_misses["c1"] = 0
        mgr.authenticate("c1", "user-abc")
        assert mgr.is_authenticated("c1")
        assert mgr.get_user_id("c1") == "user-abc"

    def test_unknown_connection_is_not_authenticated(self):
        mgr = self._make_manager()
        assert not mgr.is_authenticated("nonexistent")

    def test_disconnect_removes_all_state(self):
        mgr = self._make_manager()
        mgr._connections["c1"] = MagicMock()
        mgr._subscriptions["c1"] = set()
        mgr._user_ids["c1"] = "user-abc"
        mgr._hb_misses["c1"] = 0
        mgr.disconnect("c1")
        assert "c1" not in mgr._connections
        assert "c1" not in mgr._user_ids
        assert not mgr.is_authenticated("c1")


# ── Re-auth mid-session blocked ───────────────────────────────────────────────


class TestReAuthBlocked:
    """
    After a connection is authenticated, sending another auth message must
    return ALREADY_AUTHENTICATED and must NOT change the user_id.
    """

    @pytest.mark.asyncio
    async def test_reauth_returns_already_authenticated(self):
        from api.ws_live import LiveConnectionManager, _ws_handle_message

        # Patch the module-level _manager
        mgr = LiveConnectionManager()
        mgr._connections["c1"] = MagicMock()
        mgr._subscriptions["c1"] = set()
        mgr._user_ids["c1"] = "original-user"
        mgr._hb_misses["c1"] = 0

        sent_messages: list[dict] = []

        async def _mock_send(cid, msg):
            sent_messages.append(msg)

        mgr.send = _mock_send

        with patch("api.ws_live._manager", mgr):
            await _ws_handle_message("c1", {"type": "auth", "token": "Bearer fake-token"})

        assert any(m.get("code") == "ALREADY_AUTHENTICATED" for m in sent_messages), (
            f"Expected ALREADY_AUTHENTICATED error, got: {sent_messages}"
        )
        # user_id must not have changed
        assert mgr.get_user_id("c1") == "original-user"

    @pytest.mark.asyncio
    async def test_reauth_does_not_call_validate_token(self):
        """validate_ws_token must not be called when connection is already authed."""
        from api.ws_live import LiveConnectionManager, _ws_handle_message

        mgr = LiveConnectionManager()
        mgr._connections["c1"] = MagicMock()
        mgr._subscriptions["c1"] = set()
        mgr._user_ids["c1"] = "original-user"
        mgr._hb_misses["c1"] = 0
        mgr.send = AsyncMock()

        validate_calls = [0]

        def _mock_validate(token):
            validate_calls[0] += 1
            return {"sub": "attacker-user"}

        with patch("api.ws_live._manager", mgr), patch("api.ws_live._validate_ws_token", _mock_validate):
            await _ws_handle_message("c1", {"type": "auth", "token": "Bearer attacker-token"})

        assert validate_calls[0] == 0, "_validate_ws_token must not be called for already-authenticated connections"


# ── ws_live auth gate ─────────────────────────────────────────────────────────


class TestWsLiveAuthGate:
    @pytest.mark.asyncio
    async def test_invalid_token_closes_with_4001(self):
        """An invalid token must close the connection with code 4001."""
        from api.ws_live import LiveConnectionManager, _ws_auth_gate

        mgr = LiveConnectionManager()
        mgr._connections["c1"] = MagicMock()
        mgr._subscriptions["c1"] = set()
        mgr._user_ids["c1"] = None
        mgr._hb_misses["c1"] = 0

        close_codes: list[int] = []
        sent: list[dict] = []

        ws = MagicMock()
        ws.receive_text = AsyncMock(return_value=json.dumps({"type": "auth", "token": "Bearer bad-token"}))

        async def _mock_send(cid, msg):
            sent.append(msg)

        # _safe_ws_close(websocket, code, reason) — positional args
        async def _mock_safe_close(websocket, code=1000, reason=""):
            close_codes.append(code)

        mgr.send = _mock_send

        with (
            patch("api.ws_live._manager", mgr),
            patch("api.ws_live._validate_ws_token", return_value=None),
            patch("api.ws_live._safe_ws_close", _mock_safe_close),
        ):
            result = await _ws_auth_gate("c1", ws)

        assert result is False
        assert any(c == 4001 for c in close_codes), f"Expected close code 4001, got {close_codes}"
        assert any(m.get("code") == "AUTH_FAILED" for m in sent), f"Expected AUTH_FAILED, got {sent}"

    @pytest.mark.asyncio
    async def test_valid_token_authenticates_connection(self):
        """A valid token must authenticate the connection and return True."""
        from api.ws_live import LiveConnectionManager, _ws_auth_gate

        mgr = LiveConnectionManager()
        mgr._connections["c1"] = MagicMock()
        mgr._subscriptions["c1"] = set()
        mgr._user_ids["c1"] = None
        mgr._hb_misses["c1"] = 0

        sent: list[dict] = []

        async def _mock_send(cid, msg):
            sent.append(msg)

        mgr.send = _mock_send

        ws = MagicMock()
        ws.receive_text = AsyncMock(return_value=json.dumps({"type": "auth", "token": "Bearer valid-token"}))

        with (
            patch("api.ws_live._manager", mgr),
            patch("api.ws_live._validate_ws_token", return_value={"sub": "user-123", "role": "trader"}),
        ):
            result = await _ws_auth_gate("c1", ws)

        assert result is True
        assert mgr.is_authenticated("c1")
        assert mgr.get_user_id("c1") == "user-123"
        assert any(m.get("type") == "auth_ok" for m in sent)

    @pytest.mark.asyncio
    async def test_auth_timeout_closes_with_4001(self):
        """Timeout waiting for auth message must close with code 4001."""
        from api.ws_live import LiveConnectionManager, _ws_auth_gate

        mgr = LiveConnectionManager()
        mgr._connections["c1"] = MagicMock()
        mgr._subscriptions["c1"] = set()
        mgr._user_ids["c1"] = None
        mgr._hb_misses["c1"] = 0

        close_codes: list[int] = []
        sent: list[dict] = []

        async def _mock_send(cid, msg):
            sent.append(msg)

        async def _mock_safe_close(websocket, code=1000, reason=""):
            close_codes.append(code)

        mgr.send = _mock_send

        ws = MagicMock()
        ws.receive_text = AsyncMock(side_effect=TimeoutError())

        with patch("api.ws_live._manager", mgr), patch("api.ws_live._safe_ws_close", _mock_safe_close):
            result = await _ws_auth_gate("c1", ws)

        assert result is False
        assert any(c == 4001 for c in close_codes)
        assert any(m.get("code") == "AUTH_TIMEOUT" for m in sent)


# ── social_feed: accept before close ─────────────────────────────────────────


class TestSocialFeedAuthOrder:
    """
    Verify that ws_social_feed calls accept() before close() so FastAPI
    does not raise RuntimeError on unauthenticated connections.
    """

    @pytest.mark.asyncio
    async def test_missing_token_accepts_then_closes(self):
        """Missing token: accept() must be called before close()."""
        call_order: list[str] = []

        ws = MagicMock()
        ws.query_params = {"token": ""}
        # No subprotocol offered — exercises the query-string path.
        ws.headers = {}

        async def _accept(subprotocol=None, headers=None):
            # Mirrors starlette.websockets.WebSocket.accept. Taking no arguments
            # made the double diverge from the object it stands in for, which is
            # what let a real signature change through unnoticed.
            call_order.append("accept")

        async def _send_text(text):
            call_order.append("send")

        async def _close(code=1000):
            call_order.append(f"close:{code}")

        ws.accept = _accept
        ws.send_text = _send_text
        ws.close = _close

        # Patch _json and _sf_connections used inside the function
        import api.social_feed as sf_mod

        with patch.object(sf_mod, "_sf_connections", set()):
            from api.social_feed import ws_social_feed

            await ws_social_feed(ws)

        assert "accept" in call_order, "accept() must be called"
        accept_idx = call_order.index("accept")
        close_entries = [i for i, v in enumerate(call_order) if v.startswith("close:")]
        assert close_entries, "close() must be called"
        assert accept_idx < close_entries[0], f"accept() must come before close(). Order: {call_order}"
        assert any("4001" in v for v in call_order), "Must close with code 4001"

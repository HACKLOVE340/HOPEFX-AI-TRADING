# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""The three post-auth WebSocket endpoints, driven from connect to teardown.

Until the loop bodies were extracted (§E45) these endpoints could not be run in
a test at all: each ended in a `while True:` with no exit, so calling one hung
the suite. The sentinel contract changed that — a body that returns None ends
the loop — and a fake socket that disconnects is now enough to drive an
endpoint through **connect → auth → stream → teardown** and have it return.

That is what these tests do. They are the reason the extraction was worth
doing: the auth branches below decide who gets an audit feed and who gets a
customer's notifications, and none of them had ever executed.
"""

from __future__ import annotations

import json

import pytest

pytestmark = [pytest.mark.unit]


class _Headers(dict):
    def get(self, key, default=None):  # case-insensitive, like Starlette's
        return super().get(key.lower(), default)


class _FakeWS:
    """Enough of a Starlette WebSocket to drive an endpoint.

    `receive_text` hands back queued frames and then raises
    `WebSocketDisconnect`, which is how a real client leaving looks. That is
    the exit these endpoints rely on, so it is also how the test ends.
    """

    def __init__(self, *, headers: dict | None = None, incoming: list[str] | None = None):
        self.headers = _Headers({k.lower(): v for k, v in (headers or {}).items()})
        self.query_params: dict[str, str] = {}
        self.scope: dict = {"type": "websocket", "headers": []}
        self.sent: list[dict] = []
        self.accepted = False
        self.closed: tuple[int, str] | None = None
        self._incoming = list(incoming or [])

    async def accept(self, subprotocol=None):
        self.accepted = True
        self.subprotocol = subprotocol

    async def send_text(self, text: str):
        self.sent.append(json.loads(text))

    async def receive_text(self) -> str:
        from fastapi import WebSocketDisconnect

        if self._incoming:
            return self._incoming.pop(0)
        raise WebSocketDisconnect(1000)

    async def close(self, code: int = 1000, reason: str = ""):
        self.closed = (code, reason)

    def types(self) -> list[str]:
        return [m.get("type") for m in self.sent]


def _auth(msg_token: str = "Bearer tok") -> list[str]:
    return [json.dumps({"type": "auth", "token": msg_token})]


@pytest.fixture
def redis_returns_none(monkeypatch):
    """The factory answers, with nothing. The endpoint closes the socket."""
    import cache.redis_client as rc

    async def _none(*_a, **_k):
        return None

    monkeypatch.setattr(rc, "get_redis", _none)


@pytest.fixture
def redis_raises(monkeypatch):
    """The factory fails. The endpoint degrades to a keepalive-only loop.

    These two are *not* the same path, and the endpoints treat them
    differently — see `TestARedisOutageHasTwoDistinctShapes`.
    """
    import cache.redis_client as rc

    async def _boom(*_a, **_k):
        raise ConnectionError("redis down")

    monkeypatch.setattr(rc, "get_redis", _boom)


class TestNotificationsEndpoint:
    @pytest.mark.asyncio
    async def test_an_unauthenticated_client_is_refused_and_closed(self, monkeypatch):
        from api import ws_live

        monkeypatch.setattr(ws_live, "_validate_ws_token", lambda _t: None)
        ws = _FakeWS(incoming=_auth())
        await ws_live.ws_notifications(ws)

        assert ws.types() == ["connected", "error"]
        assert ws.sent[-1]["code"] == "AUTH_FAILED"
        assert ws.closed is not None and ws.closed[0] == 4001

    @pytest.mark.asyncio
    async def test_a_first_message_that_is_not_auth_is_refused(self, monkeypatch):
        from api import ws_live

        monkeypatch.setattr(ws_live, "_validate_ws_token", lambda _t: None)
        ws = _FakeWS(incoming=[json.dumps({"type": "subscribe", "channels": ["fills"]})])
        await ws_live.ws_notifications(ws)

        assert ws.sent[-1]["code"] == "AUTH_REQUIRED"
        assert ws.closed[0] == 4001

    @pytest.mark.asyncio
    async def test_a_client_that_never_authenticates_is_dropped(self, monkeypatch):
        from api import ws_live

        monkeypatch.setattr(ws_live, "_validate_ws_token", lambda _t: None)
        ws = _FakeWS()  # receive_text disconnects immediately
        await ws_live.ws_notifications(ws)

        assert ws.types() == ["connected"]

    @pytest.mark.asyncio
    async def test_an_authenticated_client_reaches_the_stream_and_teardown(self, monkeypatch, redis_raises):
        from api import ws_live

        monkeypatch.setattr(ws_live, "_validate_ws_token", lambda _t: {"sub": "user-9"})
        ws = _FakeWS(incoming=_auth())
        await ws_live.ws_notifications(ws)

        assert ws.types()[:2] == ["connected", "auth_ok"]
        assert ws.sent[1]["user_id"] == "user-9"
        assert ws.closed is None, "a client that simply left must not be force-closed"


class TestAuditEventsEndpointIsAdminOnly:
    """S6-02 shape: the audit stream is every superadmin action on the
    platform. A non-admin reaching it is an information-disclosure defect, and
    the check that stops it had never run."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("role", ["trader", "starter", "", "administrator", "ADMIN"])
    async def test_a_non_admin_role_is_refused(self, monkeypatch, role):
        from api import ws_live

        monkeypatch.setattr(ws_live, "_validate_ws_token", lambda _t: {"sub": "u1", "role": role})
        ws = _FakeWS(incoming=_auth())
        await ws_live.ws_audit_events(ws)

        assert ws.sent[-1]["code"] == "FORBIDDEN", f"role {role!r} reached the audit stream"
        assert ws.closed[0] == 4003

    @pytest.mark.asyncio
    @pytest.mark.parametrize("role", ["admin", "superadmin"])
    async def test_an_admin_reaches_the_stream(self, monkeypatch, redis_raises, role):
        from api import ws_live

        monkeypatch.setattr(ws_live, "_validate_ws_token", lambda _t: {"sub": "ops-ren", "role": role})
        ws = _FakeWS(incoming=_auth())
        await ws_live.ws_audit_events(ws)

        assert ws.types()[:2] == ["connected", "auth_ok"]
        assert ws.sent[1]["role"] == role


class TestNuclearEndpoint:
    @pytest.mark.asyncio
    async def test_it_says_so_when_the_engine_did_not_load(self, monkeypatch):
        """Rather than streaming null state every two seconds at an operator."""
        import sys
        import types

        from api import ws_live

        monkeypatch.setattr(ws_live, "_validate_ws_token", lambda _t: {"sub": "ops-ren"})
        fake_app = types.ModuleType("app")
        fake_app.app = types.SimpleNamespace(state=types.SimpleNamespace(nuclear_available=False))
        monkeypatch.setitem(sys.modules, "app", fake_app)

        ws = _FakeWS(incoming=_auth())
        await ws_live.ws_nuclear(ws)

        assert ws.types() == ["connected", "auth_ok", "nuclear_unavailable"]
        assert ws.closed[0] == 1001

    @pytest.mark.asyncio
    async def test_an_authenticated_operator_reaches_the_stream(self, monkeypatch):
        import sys
        import types

        from api import ws_live

        monkeypatch.setattr(ws_live, "_validate_ws_token", lambda _t: {"sub": "ops-ren"})
        monkeypatch.setattr(ws_live, "_get_nuclear_state", lambda: {"severity": 2, "action": "HOLD"})
        fake_app = types.ModuleType("app")
        fake_app.app = types.SimpleNamespace(state=types.SimpleNamespace(nuclear_available=True))
        monkeypatch.setitem(sys.modules, "app", fake_app)

        ws = _FakeWS(incoming=_auth())
        await ws_live.ws_nuclear(ws)

        assert ws.types()[:2] == ["connected", "auth_ok"]
        assert "nuclear_chart_update" in ws.types()

    @pytest.mark.asyncio
    async def test_a_bad_token_never_reaches_the_kill_switch_feed(self, monkeypatch):
        from api import ws_live

        monkeypatch.setattr(ws_live, "_validate_ws_token", lambda _t: None)
        ws = _FakeWS(incoming=_auth())
        await ws_live.ws_nuclear(ws)

        assert ws.sent[-1]["code"] == "AUTH_FAILED"
        assert "nuclear_chart_update" not in ws.types()


class TestARedisOutageHasTwoDistinctShapes:
    """A Redis outage reaches these endpoints two different ways, and they
    behave differently — worth pinning rather than discovering during one.

    * The factory **raises** → the endpoint degrades to a keepalive-only loop
      and the socket stays up.
    * The factory **returns None** → the endpoint closes the socket with 1011.

    Only the first is a fallback. Recorded as observed behaviour, not endorsed:
    changing which one a client gets is a product decision, not a test fixture.
    """

    @pytest.mark.asyncio
    @pytest.mark.parametrize("endpoint", ["ws_notifications", "ws_audit_events"])
    async def test_a_raising_factory_degrades_to_keepalive(self, monkeypatch, redis_raises, endpoint):
        from api import ws_live

        monkeypatch.setattr(ws_live, "_validate_ws_token", lambda _t: {"sub": "u1", "role": "admin"})
        ws = _FakeWS(incoming=_auth())
        await getattr(ws_live, endpoint)(ws)

        assert ws.closed is None
        assert ws.types()[-1] == "auth_ok"

    @pytest.mark.asyncio
    @pytest.mark.parametrize("endpoint", ["ws_notifications", "ws_audit_events"])
    async def test_a_none_returning_factory_closes_the_socket(self, monkeypatch, redis_returns_none, endpoint):
        from api import ws_live

        monkeypatch.setattr(ws_live, "_validate_ws_token", lambda _t: {"sub": "u1", "role": "admin"})
        ws = _FakeWS(incoming=_auth())
        await getattr(ws_live, endpoint)(ws)

        assert ws.closed == (1011, ""), "the two outage shapes have converged — check which one clients now get"

# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""Whether a customer's notification actually gets delivered.

`ws_notifications`' pump decides that, and it lived inside a `while True` that
never returns — so it had never run inside a test (§E44). Extracted in §E45
with a sentinel contract: the body returns the new heartbeat stamp, or **None
when the socket should close**, because the `break` it replaced cannot cross a
function boundary.

Two properties matter here and neither is about the number:

* **A dead socket ends the loop.** A pump that keeps polling Redis for a client
  that has gone holds a subscription and a connection slot forever.
* **A malformed payload is skipped, not fatal.** One bad notification must not
  end the stream for every notification after it.
"""

from __future__ import annotations

import json

import pytest

pytestmark = [pytest.mark.unit]


class _Sock:
    def __init__(self, *, send_fails: bool = False, incoming: list[str] | None = None):
        self.sent: list[dict] = []
        self.send_fails = send_fails
        self._incoming = list(incoming or [])

    async def send_text(self, text: str):
        if self.send_fails:
            raise RuntimeError("socket gone")
        self.sent.append(json.loads(text))

    async def receive_text(self) -> str:
        from fastapi import WebSocketDisconnect

        if self._incoming:
            return self._incoming.pop(0)
        raise WebSocketDisconnect(1000)


def _pubsub(message):
    async def get_message(**_k):
        return message

    return type("P", (), {"get_message": staticmethod(get_message)})()


class TestTheNotificationPump:
    @pytest.mark.asyncio
    async def test_a_notification_reaches_the_customer(self):
        from api import ws_live

        sock = _Sock()
        pubsub = _pubsub({"type": "message", "data": json.dumps({"title": "Fill", "body": "XAUUSD filled"})})

        nxt = await ws_live._pubsub_pump_once(sock, pubsub, last_heartbeat=1e12, message_type="notification")

        assert nxt is not None, "the pump asked to close on a healthy socket"
        assert sock.sent[-1]["type"] == "notification"
        assert sock.sent[-1]["data"]["title"] == "Fill"

    @pytest.mark.asyncio
    async def test_a_malformed_payload_is_skipped_not_fatal(self):
        """One bad notification must not end the stream for every later one."""
        from api import ws_live

        sock = _Sock()
        pubsub = _pubsub({"type": "message", "data": "{not json"})

        nxt = await ws_live._pubsub_pump_once(sock, pubsub, last_heartbeat=1e12, message_type="notification")

        assert nxt is not None, "a malformed payload closed the socket"
        assert sock.sent == []

    @pytest.mark.asyncio
    async def test_no_message_is_not_an_event(self):
        from api import ws_live

        sock = _Sock()
        nxt = await ws_live._pubsub_pump_once(sock, _pubsub(None), last_heartbeat=1e12, message_type="notification")

        assert nxt is not None
        assert sock.sent == []

    @pytest.mark.asyncio
    async def test_a_due_heartbeat_is_sent_and_the_stamp_advances(self):
        from api import ws_live

        sock = _Sock()
        nxt = await ws_live._pubsub_pump_once(sock, _pubsub(None), last_heartbeat=0.0, message_type="notification")

        assert any(m["type"] == "heartbeat" for m in sock.sent)
        assert nxt is not None and nxt > 0.0, "the heartbeat stamp did not advance"

    @pytest.mark.asyncio
    async def test_a_dead_socket_asks_the_loop_to_stop(self):
        """The sentinel that replaced `break`. Without it the pump keeps
        polling Redis for a client that has gone, holding a subscription and a
        connection slot forever."""
        from api import ws_live

        sock = _Sock(send_fails=True)

        assert (
            await ws_live._pubsub_pump_once(sock, _pubsub(None), last_heartbeat=0.0, message_type="notification")
            is None
        )

    @pytest.mark.asyncio
    async def test_a_redis_timeout_is_normal_and_keeps_the_loop_alive(self):
        from api import ws_live

        async def slow(**_k):
            raise TimeoutError

        pubsub = type("P", (), {"get_message": staticmethod(slow)})()
        assert (
            await ws_live._pubsub_pump_once(_Sock(), pubsub, last_heartbeat=1e12, message_type="notification")
            is not None
        )


class TestTheHeartbeatOnlyFallback:
    """Used when Redis is unavailable. The socket stays useful as a keepalive
    rather than being dropped."""

    @pytest.mark.asyncio
    async def test_it_keeps_the_socket_alive_between_heartbeats(self):
        from api import ws_live

        sock = _Sock(incoming=["ping"])
        assert await ws_live._heartbeat_only_once(sock, last_heartbeat=1e12) is not None

    @pytest.mark.asyncio
    async def test_a_disconnecting_client_ends_it(self):
        from api import ws_live

        sock = _Sock(incoming=[])  # receive_text raises WebSocketDisconnect
        assert await ws_live._heartbeat_only_once(sock, last_heartbeat=1e12) is None

    @pytest.mark.asyncio
    async def test_a_failed_heartbeat_ends_it(self):
        from api import ws_live

        assert await ws_live._heartbeat_only_once(_Sock(send_fails=True), last_heartbeat=0.0) is None

    @pytest.mark.asyncio
    async def test_a_due_heartbeat_is_sent(self):
        from api import ws_live

        sock = _Sock(incoming=["x"])
        await ws_live._heartbeat_only_once(sock, last_heartbeat=0.0)

        assert any(m["type"] == "heartbeat" for m in sock.sent)


class TestTheShellsStillDrainTheirBodies:
    """The refactor's own failure mode: a `while True` that no longer calls
    anything, on a socket a customer is waiting on.

    An earlier version of this test re-implemented the shell inside the test
    and drove *that*. It passed whatever `api/ws_live.py` contained — including
    a shell that had lost its call entirely, which is the one thing it was
    written to catch. The module's own loops are read here instead.
    """

    BODIES = (
        "_pubsub_pump_once",
        "_heartbeat_only_once",
        "_nuclear_stream_once",
    )

    @staticmethod
    def _loops():
        import ast
        import pathlib as _p

        src = _p.Path("api/ws_live.py").read_text()
        return ast.parse(src), src

    def test_the_module_parses_and_has_loops(self):
        """Liveness: without this, every assertion below is vacuously true."""
        import ast

        tree, _ = self._loops()
        whiles = [n for n in ast.walk(tree) if isinstance(n, ast.While)]
        assert whiles, "no loops found — the harness is reading the wrong file"

    @pytest.mark.parametrize("name", BODIES)
    def test_each_body_is_called_from_a_loop_that_acts_on_the_sentinel(self, name):
        import ast

        tree, _ = self._loops()

        shells = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.While):
                continue
            calls = {c.func.id for c in ast.walk(node) if isinstance(c, ast.Call) and isinstance(c.func, ast.Name)}
            if name in calls:
                shells.append(node)

        assert shells, f"{name} is defined but no loop calls it — the shell lost its body"

        for shell in shells:
            breaks_on_none = any(
                isinstance(n, ast.If)
                and isinstance(n.test, ast.Compare)
                and isinstance(n.test.ops[0], ast.Is)
                and isinstance(n.test.comparators[0], ast.Constant)
                and n.test.comparators[0].value is None
                and any(isinstance(b, ast.Break) for b in n.body)
                for n in ast.walk(shell)
            )
            assert breaks_on_none, f"a loop calling {name} ignores the None sentinel and would spin on a dead socket"

# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""The audit stream and the nuclear stream, one pass at a time.

Both lived inside `while True:` loops that never return, so neither had ever
run inside a test (§E44). The audit pump is the same shape as the notification
pump and differs only in the message type it emits — which is exactly the kind
of difference a copy-paste loses, so it is asserted here rather than assumed.

The nuclear body carries **two** pieces of state across passes, and the second
one is the interesting one: `last_severity` is what makes an alert fire once on
the crossing rather than on every tick, and a resume fire once on the way back
down. A body that forgot it would alert forever, and nothing outside this file
would notice.

Sentinel contract, as in §E45: the body returns the next state, or **None when
the socket should close** — `break` cannot cross a function boundary.
"""

from __future__ import annotations

import ast
import json
import pathlib

import pytest

pytestmark = [pytest.mark.unit]


class _Sock:
    """A socket that behaves like a real one when the client is merely quiet.

    `on_empty` defaults to "timeout" because that is what a connected client
    with nothing to say produces: `asyncio.wait_for` raises `TimeoutError` and
    the stream continues. A fake that disconnects instead makes every pass look
    like a closing socket, which silently turns assertions about the stream
    into assertions about the teardown.
    """

    def __init__(
        self,
        *,
        send_fails: bool = False,
        incoming: list[str] | None = None,
        on_empty: str = "timeout",
    ):
        self.sent: list[dict] = []
        self.send_fails = send_fails
        self._incoming = list(incoming or [])
        self._on_empty = on_empty

    async def send_text(self, text: str):
        if self.send_fails:
            raise RuntimeError("socket gone")
        self.sent.append(json.loads(text))

    async def receive_text(self) -> str:
        from fastapi import WebSocketDisconnect

        if self._incoming:
            return self._incoming.pop(0)
        if self._on_empty == "disconnect":
            raise WebSocketDisconnect(1000)
        raise TimeoutError


def _pubsub(message):
    async def get_message(**_k):
        return message

    return type("P", (), {"get_message": staticmethod(get_message)})()


class TestTheAuditPumpEmitsAuditEvents:
    """The channel is admin-only; the message type is what the client keys on."""

    @pytest.mark.asyncio
    async def test_an_audit_event_reaches_the_admin_under_its_own_type(self):
        from api import ws_live

        sock = _Sock()
        msg = {"type": "message", "data": json.dumps({"action": "kill_switch", "actor": "ops-ren"})}
        out = await ws_live._pubsub_pump_once(sock, _pubsub(msg), 1e18, message_type="audit_event")

        assert out == 1e18
        assert sock.sent == [{"type": "audit_event", "data": {"action": "kill_switch", "actor": "ops-ren"}}]

    @pytest.mark.asyncio
    async def test_the_same_body_still_emits_notifications_for_the_other_caller(self):
        from api import ws_live

        sock = _Sock()
        msg = {"type": "message", "data": json.dumps({"title": "filled"})}
        await ws_live._pubsub_pump_once(sock, _pubsub(msg), 1e18, message_type="notification")

        assert sock.sent == [{"type": "notification", "data": {"title": "filled"}}]

    @pytest.mark.asyncio
    async def test_a_malformed_audit_payload_is_skipped_not_fatal(self):
        from api import ws_live

        sock = _Sock()
        msg = {"type": "message", "data": "{not json"}
        out = await ws_live._pubsub_pump_once(sock, _pubsub(msg), 1e18, message_type="audit_event")

        assert out == 1e18, "one bad audit record must not end the admin's stream"
        assert sock.sent == []

    @pytest.mark.asyncio
    async def test_a_dead_socket_asks_the_audit_loop_to_stop(self):
        from api import ws_live

        sock = _Sock(send_fails=True)
        out = await ws_live._pubsub_pump_once(sock, _pubsub(None), 0.0, message_type="audit_event")

        assert out is None


class TestTheNuclearStreamBody:
    @pytest.mark.asyncio
    async def test_a_state_snapshot_is_pushed_to_the_client(self, monkeypatch):
        from api import ws_live

        monkeypatch.setattr(ws_live, "_get_nuclear_state", lambda: {"severity": 3, "action": "HOLD"})
        sock = _Sock()
        out = await ws_live._nuclear_stream_once(sock, 1e18, -1)

        assert out == (1e18, 3)
        assert sock.sent == [{"type": "nuclear_chart_update", "data": {"severity": 3, "action": "HOLD"}}]

    @pytest.mark.asyncio
    async def test_no_state_means_no_message(self, monkeypatch):
        from api import ws_live

        monkeypatch.setattr(ws_live, "_get_nuclear_state", lambda: None)
        sock = _Sock()
        out = await ws_live._nuclear_stream_once(sock, 1e18, -1)

        assert out == (1e18, -1), "severity must not be invented from a missing snapshot"
        assert sock.sent == []

    @pytest.mark.asyncio
    async def test_crossing_severity_seven_alerts_once(self, monkeypatch):
        from api import ws_live

        monkeypatch.setattr(
            ws_live, "_get_nuclear_state", lambda: {"severity": 8, "action": "FLATTEN", "explanation": "gap risk"}
        )
        sock = _Sock()

        first = await ws_live._nuclear_stream_once(sock, 1e18, 2)
        assert [m["type"] for m in sock.sent] == ["nuclear_chart_update", "nuclear_alert"]
        assert sock.sent[1]["data"]["severity"] == 8
        assert sock.sent[1]["data"]["action"] == "FLATTEN"

        assert first == (1e18, 8)
        sock.sent.clear()
        await ws_live._nuclear_stream_once(sock, 1e18, first[1])
        assert [m["type"] for m in sock.sent] == ["nuclear_chart_update"], (
            "an alert must fire on the crossing, not every tick"
        )

    @pytest.mark.asyncio
    async def test_falling_back_below_seven_resumes_once(self, monkeypatch):
        from api import ws_live

        monkeypatch.setattr(ws_live, "_get_nuclear_state", lambda: {"severity": 1, "action": "HOLD"})
        sock = _Sock()

        out = await ws_live._nuclear_stream_once(sock, 1e18, 9)
        assert [m["type"] for m in sock.sent] == ["nuclear_chart_update", "nuclear_resume"]

        sock.sent.clear()
        await ws_live._nuclear_stream_once(sock, 1e18, out[1])
        assert [m["type"] for m in sock.sent] == ["nuclear_chart_update"]

    @pytest.mark.asyncio
    async def test_a_due_heartbeat_is_sent_and_the_stamp_advances(self, monkeypatch):
        from api import ws_live

        monkeypatch.setattr(ws_live, "_get_nuclear_state", lambda: None)
        sock = _Sock()
        out = await ws_live._nuclear_stream_once(sock, 0.0, -1)

        assert out is not None and out[0] > 0.0
        assert sock.sent[0]["type"] == "heartbeat"

    @pytest.mark.asyncio
    async def test_a_dead_socket_asks_the_nuclear_loop_to_stop(self, monkeypatch):
        from api import ws_live

        monkeypatch.setattr(ws_live, "_get_nuclear_state", lambda: None)
        sock = _Sock(send_fails=True)
        out = await ws_live._nuclear_stream_once(sock, 0.0, -1)

        assert out is None

    @pytest.mark.asyncio
    async def test_a_ping_is_answered_with_a_pong(self, monkeypatch):
        from api import ws_live

        monkeypatch.setattr(ws_live, "_get_nuclear_state", lambda: None)
        sock = _Sock(incoming=[json.dumps({"type": "ping"})])
        out = await ws_live._nuclear_stream_once(sock, 1e18, -1)

        assert out == (1e18, -1)
        assert sock.sent == [{"type": "pong"}]

    @pytest.mark.asyncio
    async def test_a_disconnecting_client_ends_the_nuclear_loop(self, monkeypatch):
        from api import ws_live

        monkeypatch.setattr(ws_live, "_get_nuclear_state", lambda: None)
        sock = _Sock(on_empty="disconnect")
        out = await ws_live._nuclear_stream_once(sock, 1e18, -1)

        assert out is None


class TestEachEndpointLabelsItsOwnStream:
    """The shared pump takes the label from its caller, so the caller is what
    has to be checked.

    Swapping `"audit_event"` for `"notification"` in `ws_audit_events` leaves
    every direct test of the body green — the body does exactly what it is
    told — while the admin client, which keys on the type, silently stops
    seeing audit records. Nothing but the call site proves this.
    """

    EXPECTED = {"ws_notifications": "notification", "ws_audit_events": "audit_event"}

    @staticmethod
    def _labels_in(func_name: str) -> list[str]:
        tree = ast.parse(pathlib.Path("api/ws_live.py").read_text())
        fn = next(
            n for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef | ast.FunctionDef) and n.name == func_name
        )
        return [
            kw.value.value
            for call in ast.walk(fn)
            if isinstance(call, ast.Call) and isinstance(call.func, ast.Name) and call.func.id == "_pubsub_pump_once"
            for kw in call.keywords
            if kw.arg == "message_type" and isinstance(kw.value, ast.Constant)
        ]

    @pytest.mark.parametrize(("endpoint", "label"), sorted(EXPECTED.items()))
    def test_the_endpoint_passes_its_own_message_type(self, endpoint, label):
        labels = self._labels_in(endpoint)

        assert labels, f"{endpoint} does not call the shared pump with a literal message_type"
        assert set(labels) == {label}, f"{endpoint} emits {sorted(set(labels))}, expected {label!r}"

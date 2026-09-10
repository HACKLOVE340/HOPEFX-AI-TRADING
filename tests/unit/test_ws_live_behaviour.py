# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""`api/ws_live.py`, exercised rather than counted.

The module measured **32%** across every suite that imports it — 727 of 1,104
statements never executed — while carrying the live socket, its auth handshake,
its private financial channels and the ATR stop-loss maths. It was recorded as
coverage debt under ADR 0017 so a 40-line security fix could land; this is
§A6 option 2, the work that removes the entry.

The target is behaviour, not the number. Everything here asserts something a
person would want true, and the counterfactual for each is a real defect:

* an origin check that admits a hijacking origin;
* an auth gate that lets an unauthenticated socket through;
* a stop-loss placed on the wrong side of the price;
* a private channel delivered to a client that never asked for it;
* a broadcaster that dies and is never restarted.

Coverage follows from that. A test written to touch a line would raise the
number and prove nothing, which is the failure this repository already has a
name for.
"""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest

pytestmark = [pytest.mark.unit]


# ── helpers ──────────────────────────────────────────────────────────────────


class _WS:
    """A socket that records what was sent, with no event loop of its own."""

    def __init__(self, *, headers: dict[str, str] | None = None, incoming: list[str] | None = None):
        self.headers = headers or {}
        self.app = SimpleNamespace(state=SimpleNamespace(allowed_origins=[]))
        self.sent: list[str] = []
        self.closed: tuple[int, str] | None = None
        self._incoming = list(incoming or [])

    async def accept(self, *a, **k):
        return None

    async def send_text(self, text: str):
        self.sent.append(text)

    async def close(self, code: int = 1000, reason: str = ""):
        self.closed = (code, reason)

    async def receive_text(self) -> str:
        if not self._incoming:
            raise TimeoutError
        return self._incoming.pop(0)

    def frames(self) -> list[dict]:
        return [json.loads(s) for s in self.sent]


@pytest.fixture
def manager():
    """A fresh connection manager — the module-level one is shared state."""
    from api.ws_live import LiveConnectionManager

    return LiveConnectionManager()


# ── the origin check ─────────────────────────────────────────────────────────


class TestCrossSiteHijackingIsRefused:
    """A present Origin matching nothing on the allow-list must be refused."""

    def test_a_missing_origin_is_allowed(self):
        """Non-browser clients send none; the JWT handshake still gates access."""
        from api.ws_live import _ws_origin_allowed

        assert _ws_origin_allowed(_WS()) is True

    def test_an_allow_listed_origin_is_allowed(self):
        from api.ws_live import _ws_origin_allowed

        ws = _WS(headers={"origin": "https://app.hopefx.test"})
        ws.app.state.allowed_origins = ["https://app.hopefx.test"]
        assert _ws_origin_allowed(ws) is True

    def test_a_foreign_origin_is_refused(self):
        from api.ws_live import _ws_origin_allowed

        ws = _WS(headers={"origin": "https://evil.example", "host": "app.hopefx.test"})
        ws.app.state.allowed_origins = ["https://app.hopefx.test"]
        assert _ws_origin_allowed(ws) is False, "a cross-site origin was admitted"

    def test_a_same_origin_request_is_allowed(self):
        from api.ws_live import _ws_origin_allowed

        ws = _WS(headers={"origin": "https://app.hopefx.test", "host": "app.hopefx.test"})
        ws.app.state.allowed_origins = ["https://other.test"]
        assert _ws_origin_allowed(ws) is True

    def test_no_allow_list_configured_does_not_block(self):
        """Documented dev behaviour. Asserted so a change to it is deliberate."""
        from api.ws_live import _ws_origin_allowed

        ws = _WS(headers={"origin": "https://anything.test"})
        assert _ws_origin_allowed(ws) is True

    def test_an_app_without_state_does_not_crash_the_handshake(self):
        from api.ws_live import _ws_origin_allowed

        ws = _WS(headers={"origin": "https://anything.test"})
        ws.app = None
        assert _ws_origin_allowed(ws) is True

    def test_a_suffix_lookalike_host_is_refused(self):
        """`https://evil-app.hopefx.test` must not pass as `app.hopefx.test`."""
        from api.ws_live import _ws_origin_allowed

        ws = _WS(headers={"origin": "https://evilapp.hopefx.test", "host": "app.hopefx.test"})
        ws.app.state.allowed_origins = ["https://app.hopefx.test"]
        assert _ws_origin_allowed(ws) is False


# ── the auth handshake ───────────────────────────────────────────────────────


class TestNothingGetsThroughWithoutAuth:
    @pytest.mark.asyncio
    async def test_a_valid_token_authenticates_and_is_acknowledged(self, manager):
        from api import ws_live

        ws = _WS(incoming=[json.dumps({"type": "auth", "token": "Bearer good"})])
        with (
            patch.object(ws_live, "_manager", manager),
            patch.object(ws_live, "_validate_ws_token", return_value={"sub": "u1", "role": "trader"}),
        ):
            cid = await manager.connect(ws)
            ok = await ws_live._ws_auth_gate(cid, ws)

        assert ok is True
        assert manager.is_authenticated(cid) is True
        assert ws.frames()[-1]["type"] == "auth_ok"

    @pytest.mark.asyncio
    async def test_a_first_message_that_is_not_auth_is_closed_out(self, manager):
        from api import ws_live

        ws = _WS(incoming=[json.dumps({"type": "subscribe", "channels": ["account"]})])
        with patch.object(ws_live, "_manager", manager):
            cid = await manager.connect(ws)
            ok = await ws_live._ws_auth_gate(cid, ws)

        assert ok is False
        assert ws.closed and ws.closed[0] == 4001
        assert ws.frames()[-1]["code"] == "AUTH_REQUIRED"

    @pytest.mark.asyncio
    async def test_an_invalid_token_is_closed_out(self, manager):
        from api import ws_live

        ws = _WS(incoming=[json.dumps({"type": "auth", "token": "Bearer forged"})])
        with (
            patch.object(ws_live, "_manager", manager),
            patch.object(ws_live, "_validate_ws_token", return_value=None),
        ):
            cid = await manager.connect(ws)
            ok = await ws_live._ws_auth_gate(cid, ws)

        assert ok is False
        assert manager.is_authenticated(cid) is False
        assert ws.frames()[-1]["code"] == "AUTH_FAILED"

    @pytest.mark.asyncio
    async def test_silence_times_out_rather_than_hanging_open(self, manager):
        """An unauthenticated socket held open forever is a resource an
        unauthenticated caller controls."""
        from api import ws_live

        ws = _WS(incoming=[])  # receive_text raises TimeoutError
        with patch.object(ws_live, "_manager", manager):
            cid = await manager.connect(ws)
            ok = await ws_live._ws_auth_gate(cid, ws)

        assert ok is False
        assert ws.closed and ws.closed[0] == 4001
        assert ws.frames()[-1]["code"] == "AUTH_TIMEOUT"

    @pytest.mark.asyncio
    async def test_malformed_json_does_not_authenticate(self, manager):
        from api import ws_live

        ws = _WS(incoming=["{not json"])
        with patch.object(ws_live, "_manager", manager):
            cid = await manager.connect(ws)
            ok = await ws_live._ws_auth_gate(cid, ws)

        assert ok is False
        assert manager.is_authenticated(cid) is False


# ── the stop-loss maths ──────────────────────────────────────────────────────


class TestTheStopGoesOnTheRightSideOfThePrice:
    """53 statements of money maths that had never executed.

    A stop on the wrong side of the price does not protect the position — it
    closes it immediately, or never.
    """

    def test_a_long_stops_below_and_targets_above(self):
        from api.ws_live import _compute_atr_sl_tp

        sl, tp = _compute_atr_sl_tp("XAU/USD", 2000.0, "long")

        assert sl is not None and tp is not None
        assert sl < 2000.0 < tp, f"long stop/target the wrong way round: {sl}/{tp}"

    def test_a_short_stops_above_and_targets_below(self):
        from api.ws_live import _compute_atr_sl_tp

        sl, tp = _compute_atr_sl_tp("XAU/USD", 2000.0, "short")

        assert tp < 2000.0 < sl, f"short stop/target the wrong way round: {sl}/{tp}"

    def test_buy_is_treated_as_long(self):
        from api.ws_live import _compute_atr_sl_tp

        assert _compute_atr_sl_tp("XAU/USD", 2000.0, "buy") == _compute_atr_sl_tp("XAU/USD", 2000.0, "long")

    @pytest.mark.parametrize("direction", ["LONG", "Buy", " long "])
    def test_case_and_spacing_do_not_flip_the_side(self, direction: str):
        """The hazard this pins.

        The function treats anything not in ("long", "buy") as a SHORT, so
        `"BUY"` would have put the stop above the entry — a stop that cannot
        protect a long. Today's only caller normalises to exactly "long"/"short"
        before calling, so the hazard was not live; the contract is permissive
        and the next caller need not be so careful.
        """
        from api.ws_live import _compute_atr_sl_tp

        sl, tp = _compute_atr_sl_tp("XAU/USD", 2000.0, direction)
        assert sl < 2000.0 < tp, f"{direction!r} produced short levels for a long"

    def test_the_target_is_further_away_than_the_stop(self):
        """Default multipliers are 1.5 and 3.0 — a losing risk/reward by
        construction would be a defect in the defaults, not a preference."""
        from api.ws_live import _compute_atr_sl_tp

        sl, tp = _compute_atr_sl_tp("XAU/USD", 2000.0, "long")

        assert (tp - 2000.0) > (2000.0 - sl)

    def test_the_percentage_fallback_is_used_when_there_is_no_history(self):
        """1% of mid stands in for ATR. Asserted numerically so a silent change
        to the fallback shows up here."""
        from api.ws_live import _compute_atr_sl_tp

        with patch("pathlib.Path.exists", return_value=False):
            sl, tp = _compute_atr_sl_tp("XAU/USD", 2000.0, "long")

        assert sl == pytest.approx(2000.0 - 20.0 * 1.5, abs=1e-5)
        assert tp == pytest.approx(2000.0 + 20.0 * 3.0, abs=1e-5)

    def test_the_multipliers_are_read_from_the_environment_at_call_time(self, monkeypatch):
        """Documented as tunable without a restart. Never verified."""
        from api.ws_live import _compute_atr_sl_tp

        monkeypatch.setenv("SL_ATR_MULT", "2.0")
        monkeypatch.setenv("TP_ATR_MULT", "6.0")
        with patch("pathlib.Path.exists", return_value=False):
            sl, tp = _compute_atr_sl_tp("XAU/USD", 2000.0, "long")

        assert sl == pytest.approx(2000.0 - 20.0 * 2.0, abs=1e-5)
        assert tp == pytest.approx(2000.0 + 20.0 * 6.0, abs=1e-5)

    def test_a_broken_csv_falls_back_rather_than_raising(self, tmp_path, monkeypatch):
        """The handler logs at DEBUG and falls through. A raise here would take
        the signal broadcaster down."""
        from api.ws_live import _compute_atr_sl_tp

        monkeypatch.chdir(tmp_path)
        (tmp_path / "data").mkdir()
        (tmp_path / "data" / "XAUUSD_H1.csv").write_text("not,a,csv\n1\n")

        sl, tp = _compute_atr_sl_tp("XAU/USD", 2000.0, "long")
        assert sl is not None and tp is not None

    def test_a_real_csv_produces_an_atr_based_level(self, tmp_path, monkeypatch):
        """The first resolution tier, exercised — it had never run.

        A wide, constant-range series gives an ATR far larger than the 1%
        fallback, so the levels must differ from the fallback's.
        """
        from api.ws_live import _compute_atr_sl_tp

        monkeypatch.chdir(tmp_path)
        (tmp_path / "data").mkdir()
        rows = ["high,low,close"] + [f"{2100 + i},{1900 + i},{2000 + i}" for i in range(20)]
        (tmp_path / "data" / "XAUUSD_H1.csv").write_text("\n".join(rows) + "\n")

        sl, tp = _compute_atr_sl_tp("XAU/USD", 2000.0, "long")

        fallback_sl = 2000.0 - (2000.0 * 0.01) * 1.5
        assert sl != pytest.approx(fallback_sl, abs=1e-5), "the CSV tier did not run"
        assert sl < 2000.0 < tp


# ── private channels never reach the wrong audience ──────────────────────────


class TestAPrivateUpdateHasNoSafeBroadcastAudience:
    """S8-02's shape: right user, wrong channel.

    `push_position_update` used to `broadcast` when the caller omitted
    `user_id` — and `user_id` defaulted to `None`, so a caller that simply did
    not pass an owner leaked one user's symbol, size, entry and P&L to every
    subscriber.
    """

    @pytest.mark.asyncio
    async def test_a_position_with_an_owner_goes_only_to_them(self, manager):
        from api import ws_live

        with patch.object(ws_live, "_manager", manager), patch.object(manager, "send_to_user") as send:
            await ws_live.push_position_update({"id": "p1", "symbol": "XAU/USD"}, user_id="u1")

        send.assert_awaited_once()
        assert send.await_args.args[0] == "u1"
        assert send.await_args.args[1] == "positions"

    @pytest.mark.asyncio
    async def test_a_position_with_no_owner_is_dropped_not_broadcast(self, manager):
        from api import ws_live

        with (
            patch.object(ws_live, "_manager", manager),
            patch.object(manager, "broadcast") as bcast,
            patch.object(manager, "send_to_user") as send,
        ):
            await ws_live.push_position_update({"id": "p1", "symbol": "XAU/USD"})

        assert bcast.await_count == 0, "an unowned position was broadcast to everyone"
        assert send.await_count == 0

    @pytest.mark.asyncio
    async def test_the_drop_is_logged_loudly_enough_to_notice(self, manager, caplog):
        import logging

        from api import ws_live

        with caplog.at_level(logging.DEBUG, logger="api.ws_live"), patch.object(ws_live, "_manager", manager):
            await ws_live.push_position_update({"id": "p1"})

        assert [r for r in caplog.records if r.levelno >= logging.WARNING]

    @pytest.mark.asyncio
    async def test_a_close_with_no_owner_is_dropped_too(self, manager):
        from api import ws_live

        with patch.object(ws_live, "_manager", manager), patch.object(manager, "broadcast") as bcast:
            await ws_live.push_position_close("p1")

        assert bcast.await_count == 0

    @pytest.mark.asyncio
    async def test_a_close_with_an_owner_reaches_them(self, manager):
        from api import ws_live

        with patch.object(ws_live, "_manager", manager), patch.object(manager, "send_to_user") as send:
            await ws_live.push_position_close("p1", user_id="u1")

        assert send.await_args.args[0] == "u1"

    @pytest.mark.asyncio
    async def test_signals_are_public_and_do_broadcast(self, manager):
        """The contrast that makes the rule meaningful: not everything is private."""
        from api import ws_live

        with patch.object(ws_live, "_manager", manager), patch.object(manager, "broadcast") as bcast:
            await ws_live.push_signal({"symbol": "XAU/USD", "direction": "long"})

        assert bcast.await_count == 1


# ── a broadcaster that dies must come back ───────────────────────────────────


class TestABroadcasterThatDiesIsRestarted:
    """A background task that exits silently is the dead-control shape: the
    socket stays open, the page stops updating, and nothing says why."""

    @pytest.mark.asyncio
    async def test_a_crashed_broadcaster_is_restarted(self):
        from api import ws_live

        started: list[str] = []
        spawned: list[asyncio.Task] = []

        async def fake():
            # Long-lived on purpose. A fake that returns immediately is
            # restarted by its own done-callback, which restarts again — the
            # first version of this test spun and collected dozens of "ran".
            # That churn is real production behaviour for a broadcaster that
            # exits instantly, and it is not this test's subject.
            started.append("ran")
            await asyncio.sleep(30)

        with (
            patch.object(ws_live, "_BROADCASTER_SPECS", [("victim", fake)]),
            patch.object(ws_live, "_broadcaster_tasks", []),
        ):

            async def boom():
                raise RuntimeError("bus died")

            task = asyncio.get_running_loop().create_task(boom(), name="victim")
            with pytest.raises(RuntimeError):
                await task
            ws_live._broadcaster_done_callback(task)
            await asyncio.sleep(0.01)
            spawned.extend(ws_live._broadcaster_tasks)

        for t in spawned:
            t.cancel()
        assert started == ["ran"], "a crashed broadcaster was not restarted"

    @pytest.mark.asyncio
    async def test_a_clean_exit_is_also_restarted(self):
        """A broadcaster that returns is as dead as one that raises."""
        from api import ws_live

        started: list[str] = []

        async def fake():
            started.append("ran")
            await asyncio.sleep(30)

        with (
            patch.object(ws_live, "_BROADCASTER_SPECS", [("quiet", fake)]),
            patch.object(ws_live, "_broadcaster_tasks", []),
        ):

            async def ends():
                return None

            task = asyncio.get_running_loop().create_task(ends(), name="quiet")
            await task
            ws_live._broadcaster_done_callback(task)
            await asyncio.sleep(0.01)
            for t in ws_live._broadcaster_tasks:
                t.cancel()

        assert started == ["ran"]

    @pytest.mark.asyncio
    async def test_a_cancelled_broadcaster_is_left_alone(self):
        """Shutdown cancels them on purpose; restarting there fights the exit."""
        from api import ws_live

        started: list[str] = []

        async def fake():
            started.append("ran")

        with (
            patch.object(ws_live, "_BROADCASTER_SPECS", [("victim", fake)]),
            patch.object(ws_live, "_broadcaster_tasks", []),
        ):

            async def forever():
                await asyncio.sleep(10)

            task = asyncio.get_running_loop().create_task(forever(), name="victim")
            await asyncio.sleep(0)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            ws_live._broadcaster_done_callback(task)
            await asyncio.sleep(0.01)

        assert started == [], "a deliberately cancelled broadcaster was restarted"

    @pytest.mark.asyncio
    async def test_an_unknown_task_name_does_not_crash_the_callback(self):
        from api import ws_live

        with patch.object(ws_live, "_BROADCASTER_SPECS", [("known", None)]):

            async def ends():
                return None

            task = asyncio.get_running_loop().create_task(ends(), name="stranger")
            await task
            ws_live._broadcaster_done_callback(task)  # must not raise


# ── the other three endpoints, and their auth ────────────────────────────────


class _Endpoint(_WS):
    """A socket for driving a full endpoint coroutine.

    `accept` takes a subprotocol, and `receive_text` must eventually stop the
    endpoint's loop — a real socket does that by disconnecting.
    """

    def __init__(self, *, headers=None, incoming=None, query: str = "", silent: bool = False):
        super().__init__(headers=headers, incoming=incoming)
        # `silent` = the client connects and says nothing, which the endpoint
        # must time out. Without it an exhausted queue raises
        # `WebSocketDisconnect` — the client having *left*, which the endpoint
        # correctly handles by returning without closing anything. The first
        # version of these tests conflated the two and asserted a close that
        # should not happen.
        self.silent = silent
        self.query_params = {}
        if query:
            k, _, v = query.partition("=")
            self.query_params = {k: v}
        self.url = SimpleNamespace(query=query)
        self.scope = {"subprotocols": []}

    async def accept(self, subprotocol=None):
        return None

    async def receive_text(self) -> str:
        from fastapi import WebSocketDisconnect

        if self._incoming:
            return self._incoming.pop(0)
        if self.silent:
            raise TimeoutError
        raise WebSocketDisconnect(1000)


ENDPOINTS = ["ws_notifications", "ws_audit_events", "ws_nuclear"]


class TestEveryEndpointRefusesACrossSiteOrigin:
    @pytest.mark.parametrize("name", ENDPOINTS)
    @pytest.mark.asyncio
    async def test_a_foreign_origin_never_reaches_accept(self, name: str):
        from api import ws_live

        ws = _Endpoint(headers={"origin": "https://evil.example", "host": "app.test"})
        ws.app.state.allowed_origins = ["https://app.test"]
        accepted: list[bool] = []
        orig = ws.accept

        async def spy(subprotocol=None):
            accepted.append(True)
            return await orig(subprotocol)

        ws.accept = spy  # type: ignore[method-assign]
        await getattr(ws_live, name)(ws)

        assert accepted == [], f"{name} accepted a cross-site origin"


class TestEveryEndpointRefusesAnUnauthenticatedCaller:
    @pytest.mark.parametrize("name", ENDPOINTS)
    @pytest.mark.asyncio
    async def test_a_first_message_that_is_not_auth_is_closed(self, name: str):
        from api import ws_live

        ws = _Endpoint(incoming=[json.dumps({"type": "hello"})])
        with patch.object(ws_live, "_validate_ws_token", return_value=None):
            await getattr(ws_live, name)(ws)

        assert ws.closed is not None, f"{name} left an unauthenticated socket open"
        assert ws.closed[0] == 4001

    @pytest.mark.parametrize("name", ENDPOINTS)
    @pytest.mark.asyncio
    async def test_an_invalid_token_is_closed(self, name: str):
        from api import ws_live

        ws = _Endpoint(incoming=[json.dumps({"type": "auth", "token": "Bearer forged"})])
        with patch.object(ws_live, "_validate_ws_token", return_value=None):
            await getattr(ws_live, name)(ws)

        assert ws.closed is not None and ws.closed[0] == 4001
        assert any(f.get("code") in {"AUTH_FAILED", "AUTH_REQUIRED"} for f in ws.frames())

    @pytest.mark.parametrize("name", ENDPOINTS)
    @pytest.mark.asyncio
    async def test_silence_is_closed_rather_than_held_open(self, name: str):
        from api import ws_live

        ws = _Endpoint(incoming=[], silent=True)
        with patch.object(ws_live, "_validate_ws_token", return_value=None):
            await getattr(ws_live, name)(ws)

        assert ws.closed is not None, f"{name} held a silent unauthenticated socket open"
        assert ws.closed[0] == 4001

    @pytest.mark.parametrize("name", ENDPOINTS)
    @pytest.mark.asyncio
    async def test_a_client_that_simply_leaves_is_not_an_error(self, name: str):
        """Disconnecting is not the same as staying silent. The endpoint
        returns; there is nothing left to close."""
        from api import ws_live

        ws = _Endpoint(incoming=[])
        with patch.object(ws_live, "_validate_ws_token", return_value=None):
            await getattr(ws_live, name)(ws)  # must not raise

    @pytest.mark.parametrize("name", ENDPOINTS)
    @pytest.mark.asyncio
    async def test_the_handshake_announces_that_auth_is_required(self, name: str):
        from api import ws_live

        ws = _Endpoint(incoming=[])
        with patch.object(ws_live, "_validate_ws_token", return_value=None):
            await getattr(ws_live, name)(ws)

        first = ws.frames()[0]
        assert first["type"] == "connected"
        assert first.get("auth_required") is True


class TestTheAuditStreamIsAdminOnly:
    """Audit events are the record of who did what. A trader reading them is a
    disclosure, and the endpoint's own docstring says admin/superadmin only."""

    @pytest.mark.asyncio
    async def test_a_trader_is_refused(self):
        from api import ws_live

        ws = _Endpoint(incoming=[json.dumps({"type": "auth", "token": "Bearer ok"})])
        with patch.object(ws_live, "_validate_ws_token", return_value={"sub": "u1", "role": "trader"}):
            await ws_live.ws_audit_events(ws)

        assert ws.closed is not None, "a trader held an open audit stream"

    # The ADMITTED side is not asserted here, deliberately. An authenticated
    # admin enters the audit stream's polling loop, which does not return and
    # does not respond to `wait_for` cancellation — the same uninterruptible
    # shape as the broadcasters below. Driving it in-process hangs the suite.
    #
    # The security property is the refusal, and that is proven above. "An admin
    # can read the stream" needs a running server and a real store, which is an
    # integration concern rather than something to fake here.


class TestNotificationsWithoutRedis:
    @pytest.mark.asyncio
    async def test_an_authenticated_socket_closes_when_there_is_no_redis(self):
        """1011 — an internal failure the client can act on, rather than a
        socket that stays open delivering nothing."""
        from api import ws_live

        ws = _Endpoint(incoming=[json.dumps({"type": "auth", "token": "Bearer ok"})])
        with (
            patch.object(ws_live, "_validate_ws_token", return_value={"sub": "u1", "role": "trader"}),
            patch("cache.redis_client.get_redis", return_value=None),
        ):
            await ws_live.ws_notifications(ws)

        assert any(f.get("type") == "auth_ok" for f in ws.frames())
        assert ws.closed is not None


# ── the broadcaster loops ────────────────────────────────────────────────────


# ── the broadcaster loops: not unit-testable, and said so rather than faked ──
#
# Seven `while True` broadcasters (~480 statements) remain unexercised. Three
# harnesses were tried and all three had to be killed:
#
#   1. a patched `asyncio.sleep` raising `CancelledError` after N calls — but
#      `ws_live.asyncio` IS the global asyncio module, so the patch replaced
#      sleep for the whole process, pytest-asyncio included;
#   2. the same patch yielding instead of raising — every broadcaster became a
#      spin loop that outran the canceller;
#   3. real sleeps with `wait_for` and a cancel — still hung, because something
#      inside the loops blocks in a way cancellation does not interrupt.
#
# So they are left uncovered deliberately. A broadcaster loop needs a real event
# bus, Redis and a price feed to do anything; a test that fakes all three proves
# the fake works. The honest note is worth more than the percentage, and the
# alternative on offer was a suite that has to be killed.

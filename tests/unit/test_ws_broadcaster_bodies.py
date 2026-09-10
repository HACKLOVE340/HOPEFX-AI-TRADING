# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""The broadcaster loop bodies, made callable so they can be exercised.

§E44 measured the ceiling: seven `while True` broadcasters (~269 statements)
and three endpoint post-auth loops block uninterruptibly in-process. Three
harnesses were killed trying to drive them, so `api/ws_live.py` was stuck under
the coverage floor with its fan-out — the code that decides who receives a
price, a balance, a signal — never once executed by a test.

Owner authorised the extraction (§A6 option 2). Each loop becomes:

    async def _x_once() -> None:      # the body, callable and testable
        ...
    async def _x_broadcaster() -> None:
        while True:
            await asyncio.sleep(N)
            await _x_once()

The `while True` shell stays untestable and is now three lines. The body is
everything that was worth testing.

## The refactor's own failure mode

A shell that no longer calls its body is a broadcaster that runs forever doing
nothing — the dead-control shape, introduced *by* the fix. So every loop here
has a test that the shell still reaches the body, driven through one real
iteration by a sleep that raises on its second call.

## `continue` becomes `return`

A `continue` cannot cross a function boundary. Converting the loop's top-level
guard `continue` to `return` is equivalent **only because the sleep stays in
the shell** — a body that returned early while owning the sleep would spin.
Asserted per loop: an idle server does nothing and still sleeps.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

pytestmark = [pytest.mark.unit]


@pytest.fixture
def manager():
    from api.ws_live import LiveConnectionManager

    return LiveConnectionManager()


class _SleepThenStop:
    """Run exactly one loop iteration, then break out.

    The shell is `while True: await sleep(); await body()`. Letting the second
    sleep raise gives one full iteration and a deterministic exit — no
    cancellation, which is what the three killed harnesses relied on.
    """

    class Stop(Exception):
        pass

    def __init__(self, iterations: int = 1):
        self.left = iterations
        self.calls = 0

    async def __call__(self, *_a, **_k):
        self.calls += 1
        self.left -= 1
        if self.left < 0:
            raise _SleepThenStop.Stop


async def run_one_iteration(loop_fn, *, sleeper: _SleepThenStop | None = None) -> _SleepThenStop:
    """Drive a broadcaster shell through one iteration and stop it."""
    from api import ws_live

    sleeper = sleeper or _SleepThenStop(1)
    with patch.object(ws_live.asyncio, "sleep", sleeper):
        with pytest.raises(_SleepThenStop.Stop):
            await loop_fn()
    return sleeper


# ── heartbeat ────────────────────────────────────────────────────────────────


class TestTheHeartbeatBody:
    @pytest.mark.asyncio
    async def test_an_idle_server_sends_nothing(self, manager):
        from api import ws_live

        with patch.object(ws_live, "_manager", manager):
            await ws_live._heartbeat_once()  # must not raise

        assert manager.connection_count == 0

    @pytest.mark.asyncio
    async def test_every_connection_gets_a_heartbeat(self, manager):
        from api import ws_live

        sent: list[tuple[str, dict]] = []

        async def send(cid, msg):
            sent.append((cid, msg))

        manager._connections = {"c1": object(), "c2": object()}
        manager._hb_misses = {"c1": 0, "c2": 0}
        with patch.object(ws_live, "_manager", manager), patch.object(manager, "send", send):
            await ws_live._heartbeat_once()

        assert {cid for cid, _ in sent} == {"c1", "c2"}
        assert all(m["type"] == "heartbeat" for _, m in sent)

    @pytest.mark.asyncio
    async def test_a_connection_past_the_miss_limit_is_closed(self, manager):
        """A socket that stopped answering holds a slot and receives nothing."""
        from api import ws_live

        closed: list[int] = []

        class _WS:
            async def close(self, code=1000, reason=""):
                closed.append(code)

        manager._connections = {"c1": _WS()}
        manager._subscriptions = {"c1": set()}
        manager._user_ids = {"c1": None}
        manager._roles = {"c1": None}
        manager._hb_misses = {"c1": ws_live.HEARTBEAT_MISS_LIMIT + 5}

        with patch.object(ws_live, "_manager", manager), patch.object(manager, "send", AsyncMock()):
            await ws_live._heartbeat_once()

        assert closed == [1001], "a stale connection was left open"
        assert "c1" not in manager._connections

    @pytest.mark.asyncio
    async def test_a_healthy_connection_is_not_closed(self, manager):
        from api import ws_live

        closed: list[int] = []

        class _WS:
            async def close(self, code=1000, reason=""):
                closed.append(code)

        manager._connections = {"c1": _WS()}
        manager._hb_misses = {"c1": 0}
        with patch.object(ws_live, "_manager", manager), patch.object(manager, "send", AsyncMock()):
            await ws_live._heartbeat_once()

        assert closed == []

    @pytest.mark.asyncio
    async def test_one_dead_connection_does_not_abort_the_sweep(self, manager):
        """The regression the extraction nearly shipped.

        `if cid not in _manager._connections: continue` skips ONE connection
        whose send already disconnected it. The first extractor converted it to
        `return` — it decided which loop a `continue` belonged to by
        indentation — so the first dead socket abandoned the whole sweep and
        every connection after it went unpinged, its miss counter frozen,
        forever.

        Caught by reading the extracted output, and pinned here so no future
        edit can reintroduce it.
        """
        from api import ws_live

        pinged: list[str] = []

        async def send(cid, msg):
            pinged.append(cid)
            if cid == "dead":
                # send() disconnects on failure; the sweep must carry on.
                manager._connections.pop(cid, None)

        manager._connections = {"dead": object(), "alive": object()}
        manager._hb_misses = {"dead": 0, "alive": 0}
        with patch.object(ws_live, "_manager", manager), patch.object(manager, "send", send):
            await ws_live._heartbeat_once()

        assert pinged == ["dead", "alive"], (
            f"a dead connection aborted the heartbeat sweep — every later connection went unpinged (reached: {pinged})"
        )

    @pytest.mark.asyncio
    async def test_the_shell_still_calls_the_body(self, manager):
        """The refactor's own failure mode: a loop that no longer does anything."""
        from api import ws_live

        with (
            patch.object(ws_live, "_manager", manager),
            patch.object(ws_live, "_heartbeat_once", AsyncMock()) as body,
        ):
            await run_one_iteration(ws_live._heartbeat_broadcaster)

        assert body.await_count == 1, "the heartbeat shell no longer reaches its body"

    @pytest.mark.asyncio
    async def test_the_shell_sleeps_even_when_idle(self, manager):
        """The guard became `return`, which is only safe because the shell owns
        the sleep. A body that returned early while owning it would spin."""
        from api import ws_live

        with patch.object(ws_live, "_manager", manager):
            sleeper = await run_one_iteration(ws_live._heartbeat_broadcaster, sleeper=_SleepThenStop(3))

        assert sleeper.calls >= 2


# ── account updates ──────────────────────────────────────────────────────────


class TestTheAccountUpdateBody:
    """One user's balance must never reach another's socket."""

    @pytest.mark.asyncio
    async def test_an_idle_server_resolves_nothing(self, manager):
        from api import ws_live

        with (
            patch.object(ws_live, "_manager", manager),
            patch("core.account_registry.get_account_registry") as reg,
        ):
            await ws_live._account_update_once()

        assert reg.call_count == 0, "an idle server still hit the account registry"

    @pytest.mark.asyncio
    async def test_a_resolved_isolated_account_goes_only_to_its_owner(self, manager):
        from api import ws_live

        # `connection_count` reads `_connections`; without it the body returns
        # at its guard and the test passes for the wrong reason.
        manager._connections = {"c1": object()}
        manager._user_ids = {"c1": "u1"}
        resolution = type("R", (), {"broker": object(), "isolated": True})()

        registry = type("Reg", (), {"resolve": AsyncMock(return_value=resolution)})()
        with (
            patch.object(ws_live, "_manager", manager),
            patch("core.account_registry.get_account_registry", return_value=registry),
            patch.object(ws_live, "_build_account_message", AsyncMock(return_value={"equity": 1})),
            patch.object(manager, "send_to_user", AsyncMock()) as send,
        ):
            await ws_live._account_update_once()

        assert send.await_count == 1
        assert send.await_args.args[0] == "u1"
        assert send.await_args.args[1] == "account"

    @pytest.mark.asyncio
    async def test_a_shared_venue_account_is_never_sent(self, manager):
        """The bug this broadcaster was rewritten to fix: a single-account venue
        is the deployment's account, not this user's."""
        from api import ws_live

        manager._connections = {"c1": object()}
        manager._user_ids = {"c1": "u1"}
        resolution = type("R", (), {"broker": object(), "isolated": False})()
        registry = type("Reg", (), {"resolve": AsyncMock(return_value=resolution)})()

        with (
            patch.object(ws_live, "_manager", manager),
            patch("core.account_registry.get_account_registry", return_value=registry),
            patch.object(manager, "send_to_user", AsyncMock()) as send,
        ):
            await ws_live._account_update_once()

        assert send.await_count == 0, "a shared venue account was sent to a user as their own"

    @pytest.mark.asyncio
    async def test_a_user_with_no_broker_is_skipped(self, manager):
        from api import ws_live

        manager._connections = {"c1": object()}
        manager._user_ids = {"c1": "u1"}
        resolution = type("R", (), {"broker": None, "isolated": True})()
        registry = type("Reg", (), {"resolve": AsyncMock(return_value=resolution)})()

        with (
            patch.object(ws_live, "_manager", manager),
            patch("core.account_registry.get_account_registry", return_value=registry),
            patch.object(manager, "send_to_user", AsyncMock()) as send,
        ):
            await ws_live._account_update_once()

        assert send.await_count == 0

    @pytest.mark.asyncio
    async def test_one_user_failing_does_not_stop_the_others(self, manager):
        """A per-user exception is caught per user. Without that, one broken
        account silently stops every other user's balance updating."""
        from api import ws_live

        manager._connections = {"c1": object(), "c2": object()}
        manager._user_ids = {"c1": "u1", "c2": "u2"}
        good = type("R", (), {"broker": object(), "isolated": True})()

        async def resolve(user_id):
            if user_id == "u1":
                raise RuntimeError("registry blew up for u1")
            return good

        # An INSTANCE attribute, not a class one: a plain function assigned to a
        # class becomes a method, so `registry.resolve("u1")` would pass `self`
        # and shift the argument. The resulting TypeError is swallowed by the
        # per-user `except` under test, and the test would fail for a reason
        # that has nothing to do with failure isolation.
        registry = SimpleNamespace(resolve=resolve)
        with (
            patch.object(ws_live, "_manager", manager),
            patch("core.account_registry.get_account_registry", return_value=registry),
            patch.object(ws_live, "_build_account_message", AsyncMock(return_value={"equity": 1})),
            patch.object(manager, "send_to_user", AsyncMock()) as send,
        ):
            await ws_live._account_update_once()

        assert send.await_count == 1
        assert send.await_args.args[0] == "u2"

    @pytest.mark.asyncio
    async def test_the_shell_still_calls_the_body(self, manager):
        from api import ws_live

        with (
            patch.object(ws_live, "_manager", manager),
            patch.object(ws_live, "_account_update_once", AsyncMock()) as body,
        ):
            await run_one_iteration(ws_live._account_update_broadcaster)

        assert body.await_count == 1, "the account shell no longer reaches its body"


# ── every shell still reaches its body ───────────────────────────────────────


class TestNoShellLostItsBody:
    """The refactor's own failure mode, checked for all seven.

    A `while True` that no longer calls anything is a broadcaster running
    forever doing nothing — the dead-control shape, introduced *by* the fix
    meant to make these testable. Nothing else in the suite would notice.
    """

    SLEEP_SHELLS = [
        ("_heartbeat_broadcaster", "_heartbeat_once"),
        ("_account_update_broadcaster", "_account_update_once"),
        ("_price_broadcaster_live_only", "_price_live_only_once"),
        ("_yfinance_price_broadcaster", "_yfinance_price_once"),
        ("_chartbot_broadcaster", "_chartbot_once"),
    ]

    @pytest.mark.parametrize(("shell", "body"), SLEEP_SHELLS)
    @pytest.mark.asyncio
    async def test_the_shell_calls_its_body_once_per_iteration(self, shell, body, manager):
        from api import ws_live

        with (
            patch.object(ws_live, "_manager", manager),
            patch.object(ws_live, body, AsyncMock()) as fn,
        ):
            await run_one_iteration(getattr(ws_live, shell))

        assert fn.await_count == 1, f"{shell} no longer reaches {body}"

    @pytest.mark.parametrize(("shell", "body"), SLEEP_SHELLS)
    @pytest.mark.asyncio
    async def test_the_shell_sleeps_between_iterations(self, shell, body, manager):
        """The bodies' guards became `return`. That is only equivalent to the
        `continue` it replaced because the sleep stayed out here."""
        from api import ws_live

        with (
            patch.object(ws_live, "_manager", manager),
            patch.object(ws_live, body, AsyncMock()),
        ):
            sleeper = await run_one_iteration(getattr(ws_live, shell), sleeper=_SleepThenStop(3))

        assert sleeper.calls >= 2, f"{shell} stopped sleeping — an early return would spin"


class TestTheTickShellThreadsItsRetryCounter:
    """`attempt` is mutated across iterations, so it round-trips through the
    return value. A parameter reassigned inside a function does not persist:
    the backoff would have been flat at delay[0] forever, and silently."""

    @pytest.mark.asyncio
    async def test_the_shell_feeds_back_what_the_body_returned(self):
        from api import ws_live

        seen: list[int] = []

        async def body(attempt: int) -> int:
            seen.append(attempt)
            if len(seen) >= 3:
                raise _SleepThenStop.Stop
            return attempt + 1

        with patch.object(ws_live, "_eventbus_tick_once", body):
            with pytest.raises(_SleepThenStop.Stop):
                await ws_live._eventbus_tick_broadcaster()

        assert seen == [0, 1, 2], f"the retry counter was not threaded through: {seen}"

    def test_the_body_returns_an_int_on_every_path(self):
        """The success path fell off the end returning None, which would index
        the backoff table with None on the next failure — a TypeError inside
        the one handler that must not raise."""
        import ast
        import inspect

        from api import ws_live

        tree = ast.parse(inspect.getsource(ws_live._eventbus_tick_once))
        fn = tree.body[0]
        assert isinstance(fn.body[-1], ast.Return), "the tick body can fall through returning None"


class TestTheSignalHandlerIsPerMessage:
    @pytest.mark.asyncio
    async def test_a_non_signal_event_is_ignored(self, manager):
        from api import ws_live

        with patch.object(ws_live, "_manager", manager), patch.object(manager, "broadcast") as bcast:
            await ws_live._signal_message_once({"type": "something_else"})

        assert bcast.await_count == 0

    @pytest.mark.asyncio
    async def test_an_idle_server_does_not_fan_out(self, manager):
        from api import ws_live

        with patch.object(ws_live, "_manager", manager), patch.object(manager, "broadcast") as bcast:
            await ws_live._signal_message_once({"type": "signal_event", "direction": "buy"})

        assert bcast.await_count == 0

    @pytest.mark.asyncio
    async def test_a_buy_signal_carries_computed_stop_and_target(self, manager):
        """The money path, reachable from a test for the first time.

        `_compute_atr_sl_tp` is called from here, and this `async for` never
        returns — so neither the call nor its result had ever been exercised.
        """
        from api import ws_live

        manager._connections = {"c1": object()}
        sent: list[dict] = []

        async def bcast(channel, msg):
            sent.append(msg)

        with (
            patch.object(ws_live, "_manager", manager),
            patch.object(manager, "broadcast", bcast),
        ):
            await ws_live._signal_message_once(
                {"type": "signal_event", "direction": "buy", "mid": 2000.0, "symbol": "XAU/USD"}
            )

        assert sent, "a signal with connections attached fanned out nothing"
        data = sent[-1]["data"]
        assert data["stop_loss"] < 2000.0 < data["take_profit"], (
            f"a long signal got its stop and target the wrong way round: {data}"
        )

    @pytest.mark.asyncio
    async def test_an_upstream_stop_is_not_overwritten(self, manager):
        """The signal engine's own levels win; ATR only fills a gap."""
        from api import ws_live

        manager._connections = {"c1": object()}
        sent: list[dict] = []

        async def bcast(channel, msg):
            sent.append(msg)

        with (
            patch.object(ws_live, "_manager", manager),
            patch.object(manager, "broadcast", bcast),
        ):
            await ws_live._signal_message_once(
                {
                    "type": "signal_event",
                    "direction": "buy",
                    "mid": 2000.0,
                    "symbol": "XAU/USD",
                    "stop_loss": 1990.0,
                    "take_profit": 2050.0,
                }
            )

        data = sent[-1]["data"]
        assert data["stop_loss"] == 1990.0
        assert data["take_profit"] == 2050.0

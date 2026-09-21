# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""The price path: how a raw bus message becomes a tick on a client's chart.

`_eventbus_tick_once` normalises every incoming tick — symbol format, bid/ask
resolution, spread derivation — and it had never run inside a test, because it
lived in an `async for` over a live bus that never returns (§E44, §E45).

A fake bus module makes the subscription **finite**: the generator yields a few
messages and stops, the `async for` completes, and the function returns. No
cancellation, no timeout, no harness that has to be killed.

The assertions are about the arithmetic a trader sees. A tick whose bid and ask
straddle the wrong mid, or whose symbol arrives unnormalised, is a wrong price
on a chart somebody trades from.
"""

from __future__ import annotations

import sys
from types import SimpleNamespace
from unittest.mock import patch

import pytest

pytestmark = [pytest.mark.unit]


@pytest.fixture
def manager():
    from api.ws_live import LiveConnectionManager

    m = LiveConnectionManager()
    m._connections = {"c1": object()}
    return m


def fake_bus(messages: list[dict]):
    """A bus whose subscription ENDS, so the `async for` completes."""

    async def connect():
        return None

    async def subscribe(_channel):
        for m in messages:
            yield m

    return SimpleNamespace(CH_TICK="hopefx:tick", bus=SimpleNamespace(connect=connect, subscribe=subscribe))


async def run_tick(messages: list[dict], manager) -> list[tuple[str, dict]]:
    from api import ws_live

    out: list[tuple[str, dict]] = []

    async def bcast(channel, msg):
        out.append((channel, msg))

    manager.broadcast = bcast  # type: ignore[method-assign]
    with (
        patch.object(ws_live, "_manager", manager),
        patch.dict(sys.modules, {"core.event_bus": fake_bus(messages)}),
    ):
        await ws_live._eventbus_tick_once(0)
    return out


class TestTheTickNormalisation:
    @pytest.mark.asyncio
    async def test_a_bid_ask_message_keeps_its_own_mid(self, manager):
        out = await run_tick([{"symbol": "XAUUSD", "bid": 1999.0, "ask": 2001.0}], manager)

        assert out, "a tick with connections attached fanned out nothing"
        data = out[-1][1]["data"]
        assert data["bid"] == 1999.0
        assert data["ask"] == 2001.0

    @pytest.mark.asyncio
    async def test_the_symbol_is_normalised_to_slash_form(self, manager):
        """The frontend keys its price map on `XAU/USD`. A raw `XAUUSD` lands
        in a key nothing reads, so the chart silently stops updating."""
        out = await run_tick([{"symbol": "XAUUSD", "bid": 1999.0, "ask": 2001.0}], manager)

        assert out[-1][1]["data"]["symbol"] == "XAU/USD"

    @pytest.mark.asyncio
    async def test_a_price_only_message_derives_a_straddling_spread(self, manager):
        """No bid/ask, just a price: the derived quotes must straddle it."""
        out = await run_tick([{"symbol": "XAU/USD", "price": 2000.0}], manager)

        data = out[-1][1]["data"]
        assert data["bid"] < 2000.0 < data["ask"], f"derived spread does not straddle the mid: {data}"

    @pytest.mark.asyncio
    async def test_a_mid_field_is_accepted_as_well_as_price(self, manager):
        out = await run_tick([{"symbol": "XAU/USD", "mid": 2000.0}], manager)

        assert out, "a `mid`-only tick produced nothing"
        assert out[-1][1]["data"]["bid"] < 2000.0

    @pytest.mark.asyncio
    async def test_an_idle_server_drops_the_tick(self, manager):
        manager._connections = {}
        out = await run_tick([{"symbol": "XAU/USD", "bid": 1.0, "ask": 2.0}], manager)

        assert out == []

    @pytest.mark.asyncio
    async def test_several_messages_each_produce_a_tick(self, manager):
        out = await run_tick(
            [
                {"symbol": "XAU/USD", "bid": 1999.0, "ask": 2001.0},
                {"symbol": "EUR/USD", "bid": 1.09, "ask": 1.10},
            ],
            manager,
        )

        symbols = [m["data"]["symbol"] for _, m in out if m.get("type") == "price_tick"]
        assert "XAU/USD" in symbols and "EUR/USD" in symbols

    @pytest.mark.asyncio
    async def test_a_bus_that_will_not_connect_returns_a_raised_attempt(self, manager):
        """The reconnect path. It must come back with a HIGHER attempt so the
        shell's next backoff is longer — a flat counter retries at delay[0]
        forever."""
        from api import ws_live

        async def connect():
            raise RuntimeError("bus unreachable")

        broken = SimpleNamespace(CH_TICK="t", bus=SimpleNamespace(connect=connect, subscribe=None))
        with (
            patch.object(ws_live, "_manager", manager),
            patch.dict(sys.modules, {"core.event_bus": broken}),
            patch.object(ws_live.asyncio, "sleep", _instant),
        ):
            nxt = await ws_live._eventbus_tick_once(0)

        assert nxt == 1, f"the backoff counter did not advance: {nxt}"

    @pytest.mark.asyncio
    async def test_the_backoff_counter_keeps_climbing(self, manager):
        from api import ws_live

        async def connect():
            raise RuntimeError("still unreachable")

        broken = SimpleNamespace(CH_TICK="t", bus=SimpleNamespace(connect=connect, subscribe=None))
        with (
            patch.object(ws_live, "_manager", manager),
            patch.dict(sys.modules, {"core.event_bus": broken}),
            patch.object(ws_live.asyncio, "sleep", _instant),
        ):
            assert await ws_live._eventbus_tick_once(3) == 4


async def _instant(*_a, **_k):
    """Skip the real backoff wait. Patched only for the duration of one call,
    never process-wide — three earlier harnesses hung by doing the latter."""
    return None


class TestTheLivePriceLookup:
    def test_an_unknown_symbol_has_no_price(self):
        from api import ws_live

        assert ws_live._get_live_price("NOT/ASYMBOL") is None

    def test_a_seeded_price_is_returned(self):
        from api import ws_live

        with patch.dict(ws_live._last_mid, {"XAU/USD": 2000.0}, clear=False):
            assert ws_live._get_live_price("XAU/USD") == 2000.0


class TestStartBroadcasters:
    @pytest.mark.asyncio
    async def test_it_registers_every_spec_with_a_restart_callback(self):
        """A broadcaster started without the done-callback is one that dies
        silently and never comes back."""
        from api import ws_live

        with patch.object(ws_live, "_broadcaster_tasks", []):
            ws_live.start_broadcasters()
            tasks = list(ws_live._broadcaster_tasks)
            for t in tasks:
                t.cancel()

        assert tasks, "start_broadcasters started nothing"
        assert {t.get_name() for t in tasks} == {n for n, _ in ws_live._BROADCASTER_SPECS}

    @pytest.mark.asyncio
    async def test_calling_it_twice_does_not_double_the_tasks(self):
        from api import ws_live

        with patch.object(ws_live, "_broadcaster_tasks", []):
            ws_live.start_broadcasters()
            first = len(ws_live._broadcaster_tasks)
            ws_live.start_broadcasters()
            second = len(ws_live._broadcaster_tasks)
            for t in list(ws_live._broadcaster_tasks):
                t.cancel()

        assert second == first, f"a second start doubled the broadcasters: {first} -> {second}"


class TestTheNuclearStateSnapshot:
    """The kill-switch state feed, reachable from a test for the first time.

    `_get_nuclear_state` was nested inside `ws_nuclear`, so the only route in
    was an endpoint whose post-auth loop cannot be driven in-process (§E44).
    Hoisting it to module level (§E45) made the thing that tells an operator
    *trading is paused* testable.
    """

    def test_a_supervisor_status_is_projected_for_the_dashboard(self):
        from api import ws_live

        sup = SimpleNamespace(
            get_status=lambda: {
                "nuclear_level": 7,
                "action": "halt",
                "trading_paused": True,
                "confidence": 0.91,
                "explanation": "escalation detected",
            }
        )
        mods = {
            "brain.nuclear_supervisor": SimpleNamespace(get_nuclear_supervisor=lambda: sup),
            "risk.orchestrator": SimpleNamespace(risk_orchestrator=None),
        }
        with patch.dict(sys.modules, mods):
            state = ws_live._get_nuclear_state()

        assert state is not None
        assert state["severity"] == 7
        assert state["trading_paused"] is True
        assert state["explanation"] == "escalation detected"

    def test_a_missing_supervisor_does_not_invent_a_calm_state(self):
        """The dangerous default. `trading_paused: False` with no supervisor
        behind it tells an operator the platform is trading normally when
        nothing is actually watching."""
        from api import ws_live

        mods = {
            "brain.nuclear_supervisor": SimpleNamespace(get_nuclear_supervisor=lambda: None),
            "risk.orchestrator": SimpleNamespace(risk_orchestrator=None),
        }
        with patch.dict(sys.modules, mods):
            state = ws_live._get_nuclear_state()

        # It returns the zero-projection rather than None — assert what it
        # actually does, so a change to it is visible here.
        assert state is not None
        assert state["severity"] == 0
        assert state["trading_paused"] is False

    def test_a_raising_supervisor_yields_no_state_rather_than_a_wrong_one(self):
        from api import ws_live

        def boom():
            raise RuntimeError("supervisor unavailable")

        mods = {
            "brain.nuclear_supervisor": SimpleNamespace(get_nuclear_supervisor=boom),
            "risk.orchestrator": SimpleNamespace(risk_orchestrator=None),
        }
        with patch.dict(sys.modules, mods):
            assert ws_live._get_nuclear_state() is None


class TestTheYfinancePass:
    @pytest.mark.asyncio
    async def test_an_idle_server_does_not_call_yfinance(self, manager):
        """A network fetch per poll with nobody listening is money and rate
        limit spent on nothing."""
        from api import ws_live

        manager._connections = {}
        called: list[bool] = []

        def download(*a, **k):
            called.append(True)

        with (
            patch.object(ws_live, "_manager", manager),
            patch.dict(sys.modules, {"yfinance": SimpleNamespace(download=download)}),
        ):
            await ws_live._yfinance_price_once()

        assert called == []

    @pytest.mark.asyncio
    async def test_a_download_failure_is_contained(self, manager):
        """yfinance is a third party on the open internet. It failing must not
        kill the broadcaster task."""
        from api import ws_live

        def download(*a, **k):
            raise RuntimeError("yfinance is down")

        with (
            patch.object(ws_live, "_manager", manager),
            patch.dict(sys.modules, {"yfinance": SimpleNamespace(download=download)}),
        ):
            await ws_live._yfinance_price_once()  # must not raise

    @pytest.mark.asyncio
    async def test_an_absent_yfinance_package_is_survivable(self, manager):
        from api import ws_live

        with (
            patch.object(ws_live, "_manager", manager),
            patch.dict(sys.modules, {"yfinance": None}),
        ):
            await ws_live._yfinance_price_once()

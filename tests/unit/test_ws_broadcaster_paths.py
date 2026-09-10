# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""What the extracted broadcaster bodies actually do.

The extraction (§E45) made them callable. This is the part that was the point:
the fan-out logic — which client receives which price, which panel gets a
sentiment score, what happens when a data source is missing — had never run
inside a test.

Each body is one `try`-wrapped pass built to survive a degraded platform. That
is the property under test throughout: **a missing data source must produce a
quieter broadcast, never an exception**, because an exception here kills the
task and `_broadcaster_done_callback` restarts it straight back into the same
crash.
"""

from __future__ import annotations

from datetime import UTC, datetime
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


@pytest.fixture
def captured(manager):
    """Every (channel, message) the body fans out."""
    out: list[tuple[str, dict]] = []

    async def bcast(channel, msg):
        out.append((channel, msg))

    manager.broadcast = bcast  # type: ignore[method-assign]
    return out


def _snapshot():
    return SimpleNamespace(
        timestamp=datetime(2026, 9, 10, 4, 0, tzinfo=UTC),
        bid=1999.5,
        ask=2000.5,
        spread=1.0,
        spread_pct=0.05,
        volume_delta=12.0,
        cumulative_delta=340.0,
        buy_pressure=0.6,
        sell_pressure=0.4,
        order_flow_imbalance=0.2,
        trade_pressure=0.55,
        vwap=2000.1,
        tick_count=1200,
    )


# ── the chartbot pass ────────────────────────────────────────────────────────


class TestTheChartbotPass:
    @pytest.mark.asyncio
    async def test_a_microstructure_snapshot_reaches_two_channels(self, manager, captured):
        """One snapshot feeds both the microstructure panel and the volume-delta
        strip; they are separate channels because they are separate panels."""
        from api import ws_live

        orch = SimpleNamespace(get_microstructure_snapshot=lambda: _snapshot())
        with (
            patch.object(ws_live, "_manager", manager),
            patch.dict("sys.modules", {"data_layer.orchestrator": SimpleNamespace(orchestrator=orch)}),
        ):
            await ws_live._chartbot_once()

        channels = [c for c, _ in captured]
        assert "microstructure" in channels
        assert "volume_delta" in channels

    @pytest.mark.asyncio
    async def test_the_microstructure_payload_carries_the_snapshot(self, manager, captured):
        from api import ws_live

        orch = SimpleNamespace(get_microstructure_snapshot=lambda: _snapshot())
        with (
            patch.object(ws_live, "_manager", manager),
            patch.dict("sys.modules", {"data_layer.orchestrator": SimpleNamespace(orchestrator=orch)}),
        ):
            await ws_live._chartbot_once()

        micro = next(m for c, m in captured if c == "microstructure")
        assert micro["data"]["bid"] == 1999.5
        assert micro["data"]["vwap"] == 2000.1
        assert micro["data"]["tick_count"] == 1200

    @pytest.mark.asyncio
    async def test_no_snapshot_broadcasts_nothing_and_does_not_raise(self, manager, captured):
        from api import ws_live

        orch = SimpleNamespace(get_microstructure_snapshot=lambda: None)
        with (
            patch.object(ws_live, "_manager", manager),
            patch.dict("sys.modules", {"data_layer.orchestrator": SimpleNamespace(orchestrator=orch)}),
        ):
            await ws_live._chartbot_once()

        assert not any(c == "microstructure" for c, _ in captured)

    @pytest.mark.asyncio
    async def test_a_raising_source_is_contained_not_propagated(self, manager, captured):
        """The property the whole body is built around.

        An escaping exception kills the task, and the done-callback restarts it
        straight back into the same crash — a hot restart loop that never
        recovers and never reports.
        """
        from api import ws_live

        def boom():
            raise RuntimeError("orchestrator is down")

        orch = SimpleNamespace(get_microstructure_snapshot=boom)
        with (
            patch.object(ws_live, "_manager", manager),
            patch.dict("sys.modules", {"data_layer.orchestrator": SimpleNamespace(orchestrator=orch)}),
        ):
            await ws_live._chartbot_once()  # must not raise

    @pytest.mark.asyncio
    async def test_an_absent_orchestrator_is_survivable(self, manager):
        """A deployment without the data layer still keeps its socket."""
        from api import ws_live

        with (
            patch.object(ws_live, "_manager", manager),
            patch.dict("sys.modules", {"data_layer.orchestrator": None}),
        ):
            await ws_live._chartbot_once()


# ── the live-only price pass ─────────────────────────────────────────────────


class TestTheLiveOnlyPricePass:
    @pytest.mark.asyncio
    async def test_an_idle_server_does_nothing(self, manager, captured):
        from api import ws_live

        manager._connections = {}
        with patch.object(ws_live, "_manager", manager):
            await ws_live._price_live_only_once(set(), 0.0)

        assert captured == []

    @pytest.mark.asyncio
    async def test_a_real_tick_is_broadcast_and_clears_the_warning(self, manager, captured):
        from api import ws_live

        warned = {"XAU/USD"}
        tick = {"type": "price_tick", "data": {"symbol": "XAU/USD", "bid": 1999.0, "ask": 2001.0}}
        with (
            patch.object(ws_live, "_manager", manager),
            patch.object(ws_live, "_broadcastable_symbols", lambda: ["XAU/USD"]),
            patch.object(ws_live, "_make_tick", lambda s: tick),
        ):
            await ws_live._price_live_only_once(warned, 0.0)

        assert ("prices", tick) in captured
        assert "XAU/USD" not in warned, "a live symbol stayed on the no-feed warned list"

    @pytest.mark.asyncio
    async def test_the_yfinance_cache_stands_in_when_there_is_no_tick(self, manager, captured):
        """Level 5: a cached price is still a price, and the no-feed banner
        should not appear while yfinance is working."""
        from api import ws_live

        with (
            patch.object(ws_live, "_manager", manager),
            patch.object(ws_live, "_broadcastable_symbols", lambda: ["XAU/USD"]),
            patch.object(ws_live, "_make_tick", lambda s: None),
            patch.dict(ws_live._yf_last_prices, {"XAU/USD": 2000.0}, clear=True),
        ):
            await ws_live._price_live_only_once(set(), 0.0)

        prices = [m for c, m in captured if c == "prices"]
        assert prices, "a cached yfinance price produced no tick"
        data = prices[-1]["data"]
        assert data["bid"] < 2000.0 < data["ask"], "the synthesised spread straddles the wrong price"

    @pytest.mark.asyncio
    async def test_a_symbol_with_no_source_at_all_is_warned_once(self, manager, captured):
        from api import ws_live

        warned: set[str] = set()
        with (
            patch.object(ws_live, "_manager", manager),
            patch.object(ws_live, "_broadcastable_symbols", lambda: ["XAU/USD"]),
            patch.object(ws_live, "_make_tick", lambda s: None),
            patch.dict(ws_live._yf_last_prices, {}, clear=True),
        ):
            await ws_live._price_live_only_once(warned, 0.0)
            await ws_live._price_live_only_once(warned, 0.0)

        assert warned == {"XAU/USD"}, "the warned-set memo did not persist across calls"


# ── the account message ──────────────────────────────────────────────────────


class TestTheAccountMessage:
    @pytest.mark.asyncio
    async def test_an_empty_account_yields_no_message(self):
        """Better no account frame than a frame of zeros presented as a balance."""
        from api import ws_live

        class _Broker:
            async def get_account_info(self):
                return None

        assert await ws_live._build_account_message(_Broker()) is None

    @pytest.mark.asyncio
    async def test_a_raising_broker_propagates_to_its_per_user_handler(self):
        """Not swallowed here. `_account_update_once` catches per user, so one
        broken broker skips one user; swallowing it here would instead send
        that user nothing forever with no record of why."""
        from api import ws_live

        class _Broker:
            async def get_account_info(self):
                raise RuntimeError("broker down")

        with pytest.raises(RuntimeError):
            await ws_live._build_account_message(_Broker())

    @pytest.mark.asyncio
    async def test_a_none_broker_yields_no_message(self):
        from api import ws_live

        assert await ws_live._build_account_message(None) is None


# `_broadcast_no_live_feed` is NOT tested here. It looked like a helper and is
# actually a polling loop of its own — a `while` that re-notifies every 30s —
# so it belongs with the loops §E44 established cannot be driven in-process.
# The first version of this file invented a `symbol` argument for it and would
# have "passed" against a signature that does not exist.

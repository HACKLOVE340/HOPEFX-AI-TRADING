# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""Markets & Execution — the read half, and a deliberate stop before the rest.

Spec §4 Cluster A, fourth and last department. `sync_positions` and
`query_broker_status` are implemented. `place_order` and `cancel_order` are
**not**, and that is a decision I am making explicitly rather than an omission.

Three reasons, and the first is the one that decides it:

1. This session found three live paths where the AI reached money without a
   gate — a `hasattr` for a method nobody wrote, a kill switch wired in one
   direction only, and a budget with no rate limit. Building a fourth AI-to-broker
   path today, in the same codebase, would be the wrong lesson to draw from that.
2. The OANDA adapter has never been run against the venue (audit item 7, owner
   -blocked). An order handler would be the first thing to find out.
3. Nobody asked for an agent that places orders. The spec lists the action; it
   does not say an agent should be able to fire it unsupervised, and the two
   refusals already in front of it exist because the answer is "not yet".

**`sync_positions` reports divergence; it does not correct it.** "Sync" can be
read as "make them match", and making them match means closing or opening
positions to reach agreement with the broker — an action, on the money path,
dressed as a read. It returns the differences and changes nothing, and a test
below asserts no mutating broker method is ever called.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from ai import departments
from ai.departments import markets_execution
from core.ai_tool_permissions import ToolRisk

pytestmark = pytest.mark.unit


# ── what is wired, and what is refused ───────────────────────────────────────


def test_the_two_read_actions_are_implemented():
    for name in ("sync_positions", "query_broker_status"):
        action = departments.action_by_name(f"markets_execution.{name}")
        assert action.handler is not None, name
        assert action.risk is ToolRisk.READ_ONLY, name


def test_the_order_actions_remain_unimplemented():
    """Declared, doubly gated, and deliberately without a handler."""
    for name in ("place_order", "cancel_order"):
        action = departments.action_by_name(f"markets_execution.{name}")
        assert action.handler is None, name
        assert action.risk is ToolRisk.LIVE_TRADING
        assert action.requires_approval is True


def test_nothing_on_the_bus_can_move_money():
    """The invariant for the whole of Cluster A as it stands."""
    for action in departments.implemented_actions():
        assert action.risk is ToolRisk.READ_ONLY, action.name
        assert action.requires_approval is False, action.name


def test_place_order_is_refused_even_with_approval_when_not_live():
    """Two independent refusals, so neither alone is what protects the account."""
    from ai.tools.bus import ToolDenied

    bus = departments.build_tool_bus(live_mode=False)
    with pytest.raises(ToolDenied) as excinfo:
        bus.invoke(
            "markets_execution.place_order",
            operator="tester",
            allowed_actions={"markets_execution.place_order"},
            approved=True,
        )
    assert "live_tool_requires_live_mode" in excinfo.value.reason_codes


def test_place_order_in_live_mode_with_approval_still_has_no_handler():
    """Both gates cleared and it STILL does nothing — because nothing is wired."""
    from ai.tools.bus import ToolDenied

    bus = departments.build_tool_bus(live_mode=True)
    with pytest.raises(ToolDenied) as excinfo:
        bus.invoke(
            "markets_execution.place_order",
            operator="tester",
            allowed_actions={"markets_execution.place_order"},
            approved=True,
        )
    assert "tool_not_implemented" in excinfo.value.reason_codes


# ── sync_positions reads; it must never write ────────────────────────────────


def _broker(positions=None, connected=True):
    broker = MagicMock()
    broker.is_connected.return_value = connected
    broker.get_positions = AsyncMock(return_value=positions or [])
    return broker


def test_sync_positions_reports_divergence():
    remote = [MagicMock(symbol="XAUUSD", quantity=1.0)]
    tracker = MagicMock()
    tracker.get_all_positions.return_value = [MagicMock(symbol="EURUSD", quantity=2.0)]

    result = markets_execution.sync_positions(broker=_broker(remote), position_tracker=tracker)

    assert result["available"] is True
    assert "XAUUSD" in result["only_at_broker"]
    assert "EURUSD" in result["only_local"]


def test_sync_positions_never_calls_a_mutating_broker_method():
    """ "Sync" must not mean "make them match" — that is an order, not a read."""
    broker = _broker([MagicMock(symbol="XAUUSD", quantity=1.0)])
    tracker = MagicMock()
    tracker.get_all_positions.return_value = []

    markets_execution.sync_positions(broker=broker, position_tracker=tracker)

    for forbidden in ("place_order", "place_market_order", "close_position", "close_all_positions", "cancel_order"):
        assert not getattr(broker, forbidden).called, f"sync_positions called {forbidden}"


def test_sync_positions_without_a_broker_says_so():
    result = markets_execution.sync_positions(broker=None, position_tracker=MagicMock())
    assert result["available"] is False
    assert "broker" in result["reason"]
    assert "only_local" not in result, "an unavailable reconciliation must not report a result"


def test_a_broker_that_raises_is_reported():
    broker = MagicMock()
    broker.get_positions = AsyncMock(side_effect=RuntimeError("socket closed"))
    result = markets_execution.sync_positions(broker=broker, position_tracker=MagicMock())
    assert result["available"] is False
    assert "socket closed" in result["reason"]


def test_an_async_broker_call_works_from_inside_a_running_loop():
    """The bus calls handlers synchronously; brokers are async.

    asyncio.run() raises inside a running loop, so a handler that used it would
    work in a unit test and fail in the API process — the worst combination.
    """
    import asyncio

    async def drive():
        return markets_execution.sync_positions(
            broker=_broker([MagicMock(symbol="XAUUSD", quantity=1.0)]),
            position_tracker=MagicMock(get_all_positions=MagicMock(return_value=[])),
        )

    result = asyncio.run(drive())
    assert result["available"] is True


# ── query_broker_status ──────────────────────────────────────────────────────


def test_broker_status_reports_disconnected_without_pretending():
    result = markets_execution.query_broker_status(broker=_broker(connected=False))
    assert result["available"] is True
    assert result["connected"] is False


def test_broker_status_without_a_broker_is_not_disconnected():
    """No broker configured and a broker that is down are different facts."""
    result = markets_execution.query_broker_status(broker=None)
    assert result["available"] is False
    assert "connected" not in result


# ── through the bus ──────────────────────────────────────────────────────────


def test_query_broker_status_runs_through_the_bus():
    bus = departments.build_tool_bus()
    result = bus.invoke(
        "markets_execution.query_broker_status",
        operator="tester",
        allowed_actions={"markets_execution.query_broker_status"},
        broker=_broker(connected=True),
    )
    assert result.allowed is True
    assert result.value["connected"] is True

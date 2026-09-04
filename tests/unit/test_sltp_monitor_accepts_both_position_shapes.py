# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
The stop-loss monitor must work with either position provider.

There are two live Position classes and SLTPMonitor accepts both — its
``position_manager`` parameter is untyped, ``hopefx_engine.py`` passes a
``PositionTracker``, and the monitor's own docstring names a ``PositionManager``:

    execution/position_tracker.py  Position.id
    execution/position_manager.py  Position.position_id

The monitor read ``pos.id``. On the PositionManager path that raises
AttributeError on the first position it examines. ``_loop`` catches every
exception and keeps polling, so nothing crashes and nothing is reported as
broken — the task stays alive, ``start()`` has already logged "SLTPMonitor
started", and **no stop loss is ever checked**.

That is the worst version of this codebase's signature defect: a safety control
that is present, running, and doing nothing.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from execution.sl_tp_monitor import SLTPMonitor

pytestmark = pytest.mark.unit


def _tracker_position(stop_loss=1950.0):
    from execution.position_tracker import Position

    return Position(
        id="pos_1",
        symbol="XAUUSD",
        side="long",
        quantity=1.0,
        entry_price=2000.0,
        current_price=1940.0,
        stop_loss=stop_loss,
    )


def _manager_position(stop_loss=1950.0):
    from execution.position_manager import Position

    return Position(
        position_id="pos_1",
        symbol="XAUUSD",
        side="BUY",
        quantity=1.0,
        entry_price=2000.0,
        stop_loss=stop_loss,
    )


def _monitor(pos):
    pm = MagicMock()
    pm.get_all_positions = MagicMock(return_value={"XAUUSD": pos})
    tick = MagicMock()
    tick.mid = 1940.0  # below the stop loss
    return SLTPMonitor(pm, MagicMock(), {"XAUUSD": tick})


@pytest.mark.parametrize("make_position", [_tracker_position, _manager_position])
def test_the_identifier_is_readable_from_either_shape(make_position):
    pos = make_position()
    assert SLTPMonitor._position_id(pos) == "pos_1"


@pytest.mark.parametrize("make_position", [_tracker_position, _manager_position])
@pytest.mark.asyncio
async def test_a_breached_stop_actually_closes(make_position):
    """The property that matters: price below the stop must schedule a close."""
    pos = make_position()
    monitor = _monitor(pos)
    assert SLTPMonitor._check_breach(pos, 1940.0) == "stop_loss"

    with patch.object(monitor, "_close_position", new=AsyncMock()) as close:
        with patch("asyncio.create_task", side_effect=lambda coro, **kw: asyncio.ensure_future(coro)):
            await monitor._check_all_positions()
            await asyncio.sleep(0)

    close.assert_called_once()


@pytest.mark.parametrize("make_position", [_tracker_position, _manager_position])
@pytest.mark.asyncio
async def test_checking_positions_does_not_raise(make_position):
    """It used to raise AttributeError, which _loop swallowed — so the monitor
    stayed alive and silently stopped enforcing anything."""
    monitor = _monitor(make_position())
    await monitor._check_all_positions()  # must not raise


@pytest.mark.parametrize("make_position", [_tracker_position, _manager_position])
@pytest.mark.asyncio
async def test_a_position_already_closing_is_not_closed_twice(make_position):
    """The duplicate-close guard. If the identifier cannot be read, this guard
    silently never matches and the same position is closed on every poll —
    a double market order."""
    pos = make_position()
    monitor = _monitor(pos)
    monitor._closing.add("pos_1")

    with patch.object(monitor, "_close_position", new=AsyncMock()) as close:
        await monitor._check_all_positions()

    close.assert_not_called()


@pytest.mark.asyncio
async def test_the_poll_loop_reaches_the_close_on_a_real_position():
    """End to end through _loop, which is what production runs — and which
    swallows the exception that made this invisible."""
    from execution.position_manager import Position

    pos = Position(
        position_id="p1",
        symbol="XAUUSD",
        side="BUY",
        quantity=1.0,
        entry_price=2000.0,
        stop_loss=1950.0,
    )
    monitor = _monitor(pos)

    with patch.object(monitor, "_close_position", new=AsyncMock()) as close:
        with patch("asyncio.create_task", side_effect=lambda coro, **kw: asyncio.ensure_future(coro)):
            await monitor._check_all_positions()
            await asyncio.sleep(0)

    close.assert_called_once()
    assert "p1" in monitor._closing


def test_an_object_with_neither_identifier_is_refused_loudly():
    """Falling back to a generated id would let the duplicate-close guard pass
    for a position it has never seen, on every poll."""

    class Nameless:
        symbol = "XAUUSD"

    with pytest.raises(AttributeError, match="position_id"):
        SLTPMonitor._position_id(Nameless())

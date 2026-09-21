# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
tests/unit/test_kill_switch_awaits_the_broker.py
=================================================
S12-04e — the kill switch could not close a single position against an async
broker.

The never-awaited-coroutine family, at its worst site. ``BaseBroker``'s methods
are all ``async def``; ``CircuitBreaker._execute_kill_switch`` called them as if
they were not:

    positions = self.broker.get_positions()      # coroutine object
    if not positions:                            # a coroutine is truthy → passes
        break
    self.broker.cancel_all_orders()              # coroutine, discarded
    for position in positions:                   # TypeError: not iterable
        self.broker.close_position(position, …)

What actually happens against an async broker:

1. ``get_positions()`` returns a coroutine. It is truthy, so the "nothing to
   close" early-exit does not fire.
2. ``cancel_all_orders()`` builds a second coroutine and drops it. No orders are
   cancelled.
3. ``for position in positions`` raises ``TypeError: 'coroutine' object is not
   iterable``, which the surrounding ``except Exception`` swallows and logs as
   "Kill switch attempt N failed".
4. Three retries do the same thing.
5. Final verification calls ``get_positions()`` again, gets another truthy
   coroutine, and ``len()`` raises inside the escalation branch.

So the most important control in the product **cannot close anything**, and the
operator is told it partially failed — which is at least loud, but the positions
are still open and the log says "MANUAL INTERVENTION REQUIRED" for a mechanism
that never ran.

``execution/broker_call.call_broker`` already exists for exactly this — it awaits
a coroutine function and runs a sync one in an executor, so one call site works
against both broker shapes. It was written for S12-04 and never reached here.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit


class _AsyncBroker:
    """A broker with the real ``BaseBroker`` shape: everything is ``async def``."""

    def __init__(self, positions):
        self._positions = list(positions)
        self.cancelled = 0
        self.closed: list[str] = []

    async def get_positions(self):
        return list(self._positions)

    async def cancel_all_orders(self):
        self.cancelled += 1
        return True

    async def close_position(self, position, order_type="MARKET"):
        self.closed.append(position)
        self._positions = [p for p in self._positions if p != position]
        return True


class _SyncBroker(_AsyncBroker):
    """Some adapters in this repo are still sync. Both must work."""

    def get_positions(self):  # type: ignore[override]
        return list(self._positions)

    def cancel_all_orders(self):  # type: ignore[override]
        self.cancelled += 1
        return True

    def close_position(self, position, order_type="MARKET"):  # type: ignore[override]
        self.closed.append(position)
        self._positions = [p for p in self._positions if p != position]
        return True


def _breaker(broker):
    from risk.circuit_breakers import CircuitBreaker

    cb = CircuitBreaker.__new__(CircuitBreaker)
    cb.broker = broker
    cb._broker_level_cancel_all = lambda *_a, **_k: None
    cb._send_emergency_alert = lambda *_a, **_k: None
    return cb


@pytest.mark.asyncio
async def test_the_kill_switch_closes_every_position_on_an_async_broker():
    broker = _AsyncBroker(["EURUSD-1", "XAUUSD-2"])
    await _breaker(broker)._execute_kill_switch("test")

    assert broker.closed == ["EURUSD-1", "XAUUSD-2"], (
        "the kill switch closed nothing: get_positions() returned a coroutine, "
        "which is truthy, and iterating it raised TypeError into the retry "
        "loop's except-block (S12-04e)"
    )


@pytest.mark.asyncio
async def test_it_cancels_pending_orders_before_closing():
    broker = _AsyncBroker(["EURUSD-1"])
    await _breaker(broker)._execute_kill_switch("test")
    assert broker.cancelled >= 1, "pending orders were never cancelled — the coroutine was discarded"


@pytest.mark.asyncio
async def test_it_still_works_against_a_sync_broker():
    """Not every adapter here is async. The fix must not trade one shape for
    the other."""
    broker = _SyncBroker(["EURUSD-1"])
    await _breaker(broker)._execute_kill_switch("test")
    assert broker.closed == ["EURUSD-1"]


@pytest.mark.asyncio
async def test_a_flat_account_exits_early_without_closing_anything():
    broker = _AsyncBroker([])
    await _breaker(broker)._execute_kill_switch("test")
    assert broker.closed == []


@pytest.mark.asyncio
async def test_one_failing_close_does_not_abandon_the_rest():
    """A kill switch that stops at the first error leaves the remaining
    exposure open, which is the thing it exists to prevent."""

    class _Flaky(_AsyncBroker):
        async def close_position(self, position, order_type="MARKET"):
            if position == "BAD":
                raise RuntimeError("broker rejected")
            return await super().close_position(position, order_type)

    broker = _Flaky(["BAD", "GOOD"])
    await _breaker(broker)._execute_kill_switch("test")
    assert "GOOD" in broker.closed

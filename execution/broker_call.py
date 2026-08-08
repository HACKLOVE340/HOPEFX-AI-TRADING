# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
execution/broker_call.py
========================
One way to call a broker method, whether it is sync or async.

Every method on ``brokers.base.BaseBroker`` is ``async def``, but the paper
broker (``brokers/paper_trading.py``) is synchronous and blocking. Call sites
handled that by running the call in a thread pool::

    order = await loop.run_in_executor(None, lambda: broker.place_order(...))

which is right for the sync broker and silently wrong for every async one: the
worker thread only *constructs* a coroutine, and awaiting the executor future
returns that coroutine object. Nothing runs it, so the broker is never called.

Nothing raises at the call site, and what happens next depends on what the
caller does with the "result":

* ``SLTPMonitor._close_position`` — a coroutine is not ``None``, so the monitor
  booked the position closed and alerted "STOP_LOSS HIT: Closed ..." while the
  position stayed open at the broker (S12-04).
* ``ExecutionEngine._check_margin`` — ``getattr(account, "equity", ...)`` gave
  ``0.0``; the buffer test is guarded by ``equity > 0``, so the margin gate was
  skipped entirely and blocked nothing (S12-04a, fail-open).
* ``ExecutionEngine._check_leverage`` — the same ``0.0`` tripped
  ``equity <= 0`` and blocked *every* order with the false reason
  "Account equity is zero or negative".

``call_broker`` keeps the thread-pool hop that protects the event loop from a
blocking sync broker, and awaits the result when the broker turns out to be
async. See docs/HARDENING_BACKLOG.md S12-04 / S12-04a.
"""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Callable
from typing import Any, TypeVar

T = TypeVar("T")


async def call_broker(method: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    """Invoke a broker *method* and return its actual result.

    Works for both shapes of broker:

    * ``async def`` — the coroutine is awaited on the event loop.
    * plain ``def``  — the call runs in the default thread pool, so a blocking
      broker SDK cannot stall the loop.

    Exceptions propagate to the caller: a broker error must reach the gate that
    decides whether to block the trade, never be swallowed here.
    """
    if inspect.iscoroutinefunction(method):
        # Awaiting directly is correct *and* cheaper than a thread hop: an
        # async broker does its own I/O without blocking.
        return await method(*args, **kwargs)

    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(None, lambda: method(*args, **kwargs))

    # A sync wrapper may still hand back an awaitable (e.g. a partial, a
    # functools.wraps'd coroutine function, or a Mock configured as async).
    if inspect.isawaitable(result):
        result = await result
    return result

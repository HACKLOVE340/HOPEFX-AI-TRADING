# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""Markets & Execution — the read half. Spec §4 Cluster A.

`place_order` and `cancel_order` are declared in the department table and have
**no handler here**, deliberately:

* This session found three live paths where the AI reached money with no gate —
  a `hasattr` for a method nobody wrote, a kill switch wired in one direction
  only, and a budget with no rate limit. Adding a fourth AI-to-broker path in
  the same codebase, the same day, is the wrong lesson to draw from that.
* The OANDA adapter has never been run against the venue (audit item 7, owner
  -blocked). An order handler would be the thing that finds out.
* The spec lists the action; it does not say an agent may fire it unsupervised.
  The two refusals already in front of it — human approval AND live mode —
  exist because the answer is "not yet".

**`sync_positions` reports divergence and corrects nothing.** "Sync" reads
naturally as "make them match", and making them match means opening or closing
positions to agree with the broker — an action on the money path wearing a
read's name. This returns the differences.

**The async problem, because it is a real trap.** Brokers expose
`async def get_positions`, and `ToolBus.invoke` calls handlers synchronously.
`asyncio.run()` raises inside a running loop, so a handler using it would pass
every unit test and fail inside the API process — the worst combination. These
run the coroutine on a worker thread when a loop is already running.
"""

from __future__ import annotations

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Final

logger = logging.getLogger(__name__)

#: Two position quantities closer than this are the same position. Float
#: quantities arrive from two systems that rounded them differently; an exact
#: comparison would report every position as mismatched forever.
QUANTITY_TOLERANCE: Final = 1e-9


def _unavailable(reason: str, **extra: Any) -> dict[str, Any]:
    """No result keys. An unavailable read must not answer the question."""
    return {"available": False, "reason": reason, **extra}


def _await(coro: Any) -> Any:
    """Resolve a coroutine from synchronous code, loop or no loop.

    `asyncio.run` is correct only when nothing else is running. Inside the API
    process there IS a loop, so the coroutine goes to a worker thread with its
    own loop instead of raising.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    with ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()


def _symbols(positions: Any) -> dict[str, float]:
    """symbol -> quantity, for whatever position shape the caller has."""
    out: dict[str, float] = {}
    for position in positions or []:
        symbol = str(getattr(position, "symbol", "") or getattr(position, "instrument", "") or "")
        if not symbol:
            continue
        try:
            quantity = float(getattr(position, "quantity", 0) or getattr(position, "units", 0) or 0)
        except (TypeError, ValueError):
            quantity = 0.0
        out[symbol] = out.get(symbol, 0.0) + quantity
    return out


def sync_positions(*, broker: Any = None, position_tracker: Any = None, **_: Any) -> dict[str, Any]:
    """Report how local positions differ from the broker's. Corrects nothing."""
    if broker is None:
        return _unavailable("broker_unavailable")

    try:
        remote_raw = broker.get_positions()
        remote_raw = _await(remote_raw) if asyncio.iscoroutine(remote_raw) else remote_raw
    except Exception as exc:
        logger.warning("markets_execution.sync_positions: broker read failed (%s)", exc)
        return _unavailable(f"broker_read_failed: {exc}")

    remote = _symbols(remote_raw)

    local: dict[str, float] = {}
    if position_tracker is not None:
        try:
            local = _symbols(position_tracker.get_all_positions())
        except Exception as exc:
            logger.warning("markets_execution.sync_positions: local read failed (%s)", exc)
            return _unavailable(f"local_read_failed: {exc}")

    mismatched = {
        symbol: {"local": local[symbol], "broker": remote[symbol]}
        for symbol in set(local) & set(remote)
        if abs(local[symbol] - remote[symbol]) > QUANTITY_TOLERANCE
    }

    return {
        "available": True,
        # Named for what they are: differences, not instructions. Reconciling
        # them is a human decision and, if it becomes an action, its own tool
        # at its own risk tier.
        "only_at_broker": sorted(set(remote) - set(local)),
        "only_local": sorted(set(local) - set(remote)),
        "quantity_mismatch": mismatched,
        "in_agreement": len(set(local) & set(remote)) - len(mismatched),
    }


def query_broker_status(*, broker: Any = None, **_: Any) -> dict[str, Any]:
    """Broker connection state.

    An absent broker is not a disconnected one: "nothing is configured" and
    "the venue dropped us" are different facts and an operator needs to tell
    them apart, so the first has no `connected` key at all.
    """
    if broker is None:
        return _unavailable("broker_unavailable")

    try:
        connected = bool(broker.is_connected())
    except Exception as exc:
        logger.warning("markets_execution.query_broker_status failed (%s)", exc)
        return _unavailable(f"status_read_failed: {exc}")

    return {
        "available": True,
        "connected": connected,
        "broker": type(broker).__name__,
    }


__all__ = ["query_broker_status", "sync_positions"]

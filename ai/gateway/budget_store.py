# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""A Redis-backed spend counter, shared across workers and across restarts.

`ai/gateway/budget.py` held the month's spend in a module global. That broke
the ceiling in two ways, one live and one waiting:

* Every restart reset the month to $0. A deployment that restarts daily had no
  effective monthly cap at all.
* `API_WORKERS` defaults to 1, but at any higher value each worker process kept
  its own `_spend` dict. Four workers meant four full allowances — the number in
  the settings form silently stopped meaning what it said.

**Synchronous by design.** The gateway is synchronous and its callers already
wrap it in `asyncio.to_thread` (`api/brain.py:663`, `security/llm_wrapper.py:92`),
so this runs on a worker thread where a blocking client is the correct choice.
Reaching for the async client here would mean driving a loop from inside a
thread that is itself standing in for one.

**Atomicity matters more than it looks.** `HINCRBYFLOAT` is a single round trip
that both increments and returns the new total, so two workers charging at the
same instant cannot read-modify-write over each other. A `GET` then `SET` would
lose one of the two charges, and a lost charge is a ceiling that does not bind.
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any

logger = logging.getLogger(__name__)

#: One key per calendar month, so the period rolls by expiry rather than by a
#: process remembering to clear anything.
_SPEND_KEY = "hopefx:ai:budget:spend:{period}"
_EVENTS_KEY = "hopefx:ai:budget:events"

#: Spend keys outlive their month by a margin, so a report run on the 1st can
#: still read December. 70 days covers two full months plus slack.
_SPEND_TTL_S = 70 * 24 * 3600

#: The velocity window is an hour; keep a little more so an in-flight read
#: cannot race the trim.
_EVENTS_TTL_S = 2 * 3600

#: `timestamp|operator|cost`. A member that does not split into exactly this
#: many parts was written by something else and is skipped rather than guessed at.
_EVENT_FIELDS = 3


class RedisBudgetStore:
    """`BudgetStore` over a synchronous Redis client.

    Constructed with an already-connected client rather than building one, so
    the TLS enforcement and password injection in `cache/redis_client.py` stay
    the single place that knows how to reach Redis safely.
    """

    #: Durable AND shared: this is what makes `store_is_shared()` answer True.
    shared = True

    def __init__(self, client: Any) -> None:
        self._r = client

    # -- monthly spend ---------------------------------------------------------

    def get_spend(self, period: str) -> dict[str, float]:
        raw = self._r.hgetall(_SPEND_KEY.format(period=period)) or {}
        out: dict[str, float] = {}
        for key, value in raw.items():
            operator = key.decode() if isinstance(key, bytes) else str(key)
            try:
                out[operator] = float(value)
            except (TypeError, ValueError):
                # A non-numeric value means something else wrote to our key.
                # Skipping it under-reports, so it is reported rather than
                # silently dropped.
                logger.error("ai.gateway.budget: non-numeric spend for %r in %s", operator, period)
        return out

    def add_spend(self, period: str, operator: str, cost: float) -> None:
        key = _SPEND_KEY.format(period=period)
        pipe = self._r.pipeline()
        pipe.hincrbyfloat(key, operator, float(cost))
        pipe.expire(key, _SPEND_TTL_S)
        pipe.execute()

    # -- velocity window -------------------------------------------------------

    def record_event(self, ts: float, operator: str, cost: float) -> None:
        """Append one call to the rolling window.

        Scored by wall clock, not by the caller's `time.monotonic()`: monotonic
        clocks are per-process and not comparable between workers, so a shared
        window has to agree on an absolute scale. `window_events` converts back
        to the caller's monotonic frame.

        `ts` is CONVERTED, not ignored. An earlier draft computed its own
        `time.time()` and discarded the argument, which happened to be right in
        production — `charge()` always passes the current instant — and was
        wrong for any other caller, silently filing a backdated event as though
        it had just happened. A parameter a function accepts and does not use is
        a trap for whoever passes it next.
        """
        offset = time.time() - time.monotonic()
        at = ts + offset
        member = f"{at:.6f}|{operator}|{cost:.6f}"
        pipe = self._r.pipeline()
        pipe.zadd(_EVENTS_KEY, {member: at})
        pipe.zremrangebyscore(_EVENTS_KEY, 0, time.time() - _EVENTS_TTL_S)
        pipe.expire(_EVENTS_KEY, _EVENTS_TTL_S)
        pipe.execute()

    def window_events(self, since_ts: float) -> list[tuple[float, str, float]]:
        """Events since `since_ts`, expressed in the caller's monotonic frame.

        `since_ts` arrives as a monotonic value. The offset between the two
        clocks is computed per call rather than cached, because a cached offset
        drifts and a drifting window silently changes how long an hour is.
        """
        offset = time.time() - time.monotonic()
        raw = self._r.zrangebyscore(_EVENTS_KEY, since_ts + offset, "+inf") or []
        out: list[tuple[float, str, float]] = []
        for member in raw:
            text = member.decode() if isinstance(member, bytes) else str(member)
            parts = text.split("|")
            if len(parts) != _EVENT_FIELDS:
                continue
            try:
                out.append((float(parts[0]) - offset, parts[1], float(parts[2])))
            except ValueError:
                continue
        return out


def build_from_env() -> RedisBudgetStore | None:
    """A store from this deployment's Redis, or None when there is none.

    None is a legitimate answer — a single-worker dev box with no Redis runs on
    the in-memory counter exactly as before. The caller reports which of the two
    happened; it does not treat None as an error.
    """
    url = (os.getenv("REDIS_URL") or "").strip()
    if not url:
        return None
    try:
        from redis import Redis

        from cache.redis_client import _enforce_tls, inject_redis_password

        url = _enforce_tls(url)
        url = inject_redis_password(url, os.getenv("REDIS_PASSWORD"))
        client = Redis.from_url(url, socket_timeout=2.0, socket_connect_timeout=2.0)
        # Proving it answers here rather than on the first charge: a store that
        # cannot be reached should decline to install, not install and then fail
        # loudly on every model call for the life of the process.
        client.ping()
        return RedisBudgetStore(client)
    except Exception as exc:
        logger.error(
            "ai.gateway.budget: could not build the shared Redis counter (%s); "
            "the monthly ceiling will be per-process until this is resolved",
            exc,
        )
        return None


__all__ = ["RedisBudgetStore", "build_from_env"]

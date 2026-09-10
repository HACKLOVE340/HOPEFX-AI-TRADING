# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""What the platform does with work that arrives while the price feed is down.

## What already existed

`data_layer/feeds/gold/manager.py` fails over across six providers in priority
order with a circuit breaker per feed and a confidence-weighted consensus.
`MarketDataOrchestrator.get_latest_tick()` refuses a cached tick that carries no
source, discards one that is stale *or* future-dated, and returns `None` rather
than answering with a price it cannot stand behind. That machinery is real and
production constructs it in `MarketDataOrchestrator.start()`.

## What did not

When every source is down, work still arrives — a signal fires, an operator
clicks, a scheduled rebalance comes due — and the only answers were `None` and a
log line. Nothing recorded that the platform was in an outage, when it started,
or what it had been asked to do meanwhile. So an outage left no trace beyond the
absence of trades, which is indistinguishable from a quiet market.

This module is that record. It holds two things and ties them together:

* **`FeedHealth`** — healthy / degraded / outage, the age of the last tick, and
  how many sources are up. Serialisable, so an API and a dashboard can show the
  same answer the engine acted on.
* **`DeferredWorkQueue`** — a bounded record of what was asked for during the
  outage, each item carrying how long it waited and what the price was believed
  to be at the time.

## The rule that shapes everything here

**A deferred trade action is never replayed automatically.**

The market moved while the feed was down. An intent formed against a price from
before the outage is not a valid intent after it — acting on it is serving a
stale tick one layer up, with an order at the end. So this module has no broker,
no OMS, and no execute path; `drain()` returns data and the caller re-decides. A
test asserts that surface stays free of `execute`/`submit`/`send`, because the
tempting future edit is an `on_drain` callback that quietly turns a
forty-minute-old signal into a live order.

Two consequences follow from the same rule:

* An item older than `max_replay_age_s` comes back marked `expired` rather than
  dropped. An expired intent is evidence that a signal fired and nothing
  happened; discarding it silently would recreate the invisibility this
  programme keeps removing.
* The queue is bounded. An unbounded one turns a feed outage into an
  out-of-memory outage. When it overflows the *oldest* goes first — during a
  long outage the newest intents are the ones formed against the most recent
  known price — and the drop is counted, never silent.

## Rule 2 at the feed layer

`age_s` is `None` when there has never been a tick, not `0.0`. A zero age reads
as "perfectly fresh", which is the most dangerous possible reading of "we have
never received a price". Every unmeasured value in this module is absent.

And a recent tick is not proof the feed is up: if every provider is down, the
next second there will be no tick at all. `from_tick` reports `outage` in that
case however fresh the last tick was — reporting `healthy` there is how an
operator learns about an outage from a customer.
"""

from __future__ import annotations

import logging
import os
from collections import deque
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

logger = logging.getLogger(__name__)

__all__ = [
    "DeferredItem",
    "DeferredWorkQueue",
    "FeedHealth",
    "FeedOutageSupervisor",
]

FeedState = Literal["healthy", "degraded", "outage"]

#: Matches the orchestrator's own gate so one tick is not "live" here and
#: "stale" there. Read from the environment for the same reason it is there.
STALE_THRESHOLD_S = float(os.getenv("DQE_STALE_THRESHOLD_S", "30.0"))

#: How old a deferred intent may be and still be worth re-deciding. Past this
#: it is returned marked expired: five minutes of gold can move further than
#: most stops.
DEFAULT_MAX_REPLAY_AGE_S = float(os.getenv("FEED_REPLAY_MAX_AGE_S", "300.0"))

#: Bounded so an outage cannot become an out-of-memory incident.
DEFAULT_QUEUE_MAXLEN = int(os.getenv("FEED_DEFERRED_MAXLEN", "500"))


def _now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class FeedHealth:
    """Whether the price feed can be believed, and how stale it is."""

    state: FeedState
    is_live: bool
    age_s: float | None
    sources_up: int
    sources_total: int
    observed_at: str

    @classmethod
    def from_tick(
        cls,
        *,
        last_tick_at: datetime | None,
        sources_up: int,
        sources_total: int,
        stale_threshold_s: float = STALE_THRESHOLD_S,
    ) -> FeedHealth:
        """Judge the feed from its last tick and how many providers answer.

        Both inputs matter and neither is sufficient. A fresh tick with every
        provider dead is an outage that has not surfaced yet; a live provider
        with a 45-second-old tick is degraded, not healthy.
        """
        age_s: float | None = None
        if last_tick_at is not None:
            age_s = (_now() - last_tick_at).total_seconds()

        if sources_up <= 0 or age_s is None:
            state: FeedState = "outage"
        elif age_s > stale_threshold_s or age_s < 0:
            # A negative age is upstream clock skew or a parse error. It is not
            # freshness, and treating it as such lets it pass every upper bound.
            state = "degraded"
        else:
            state = "healthy"

        return cls(
            state=state,
            is_live=state == "healthy",
            age_s=age_s,
            sources_up=int(sources_up),
            sources_total=int(sources_total),
            observed_at=_now().isoformat(),
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "state": self.state,
            "is_live": self.is_live,
            "age_s": self.age_s,
            "sources_up": self.sources_up,
            "sources_total": self.sources_total,
            "observed_at": self.observed_at,
        }


@dataclass
class DeferredItem:
    """One thing the platform was asked to do while it could not see a price."""

    kind: str
    payload: dict[str, Any]
    reason: str
    deferred_at: datetime
    price_context: dict[str, Any] | None = None
    expired: bool = False

    def age_s(self) -> float:
        return (_now() - self.deferred_at).total_seconds()

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "payload": self.payload,
            "reason": self.reason,
            "deferred_at": self.deferred_at.isoformat(),
            "age_s": self.age_s(),
            "price_context": self.price_context,
            "expired": self.expired,
        }


class DeferredWorkQueue:
    """A bounded hold for work that arrived during an outage.

    Deliberately inert. It stores and returns; it cannot act. See the module
    docstring for why that is the design and not an omission.
    """

    def __init__(
        self,
        maxlen: int = DEFAULT_QUEUE_MAXLEN,
        max_replay_age_s: float = DEFAULT_MAX_REPLAY_AGE_S,
    ) -> None:
        if maxlen < 1:
            raise ValueError("maxlen must be at least 1")
        self._items: deque[DeferredItem] = deque(maxlen=maxlen)
        self._max_replay_age_s = float(max_replay_age_s)
        self.dropped = 0

    def defer(
        self,
        *,
        kind: str,
        payload: dict[str, Any],
        reason: str,
        at: datetime | None = None,
        price_context: dict[str, Any] | None = None,
    ) -> DeferredItem:
        """Hold one piece of work, with what was known about the price."""
        if len(self._items) == self._items.maxlen:
            # deque silently evicts; counting it is the difference between a
            # bounded queue and a lossy one nobody can audit.
            self.dropped += 1
            logger.warning(
                "DeferredWorkQueue full (maxlen=%d) — dropping the oldest deferred %s. Total dropped this outage: %d",
                self._items.maxlen,
                self._items[0].kind,
                self.dropped,
            )

        item = DeferredItem(
            kind=kind,
            payload=payload,
            reason=reason,
            deferred_at=at or _now(),
            price_context=price_context,
        )
        self._items.append(item)
        return item

    def pending(self) -> int:
        return len(self._items)

    def drain(self) -> list[DeferredItem]:
        """Hand back everything held, marked with its age. Executes nothing.

        Expired items are returned too. The caller decides what a stale intent
        means; this only refuses to pretend it is fresh.
        """
        items = list(self._items)
        self._items.clear()
        for item in items:
            item.expired = item.age_s() > self._max_replay_age_s
        return items

    def as_dict(self) -> dict[str, Any]:
        return {
            "pending": self.pending(),
            "dropped": self.dropped,
            "maxlen": self._items.maxlen,
            "max_replay_age_s": self._max_replay_age_s,
        }


class FeedOutageSupervisor:
    """Tracks feed health and holds work across an outage.

    `observe()` is the single entry point: give it what the orchestrator knows
    and it returns the deferred work at the moment the feed recovers, and
    `None` at every other moment. That asymmetry matters — handing work back on
    every healthy observation would replay it forever.
    """

    def __init__(
        self,
        maxlen: int = DEFAULT_QUEUE_MAXLEN,
        max_replay_age_s: float = DEFAULT_MAX_REPLAY_AGE_S,
    ) -> None:
        self.queue = DeferredWorkQueue(maxlen=maxlen, max_replay_age_s=max_replay_age_s)
        self.health: FeedHealth = FeedHealth.from_tick(last_tick_at=None, sources_up=0, sources_total=0)
        self.outage_since: datetime | None = None
        self._was_serving = False

    def observe(
        self, *, last_tick_at: datetime | None, sources_up: int, sources_total: int
    ) -> list[DeferredItem] | None:
        """Record the feed's state; return held work only on the recovery edge."""
        self.health = FeedHealth.from_tick(
            last_tick_at=last_tick_at, sources_up=sources_up, sources_total=sources_total
        )
        serving = self.health.is_live

        recovered: list[DeferredItem] | None = None
        if serving and not self._was_serving:
            held = self.queue.pending()
            recovered = self.queue.drain()
            if self.outage_since is not None:
                logger.info(
                    "Feed recovered after %.1fs — %d deferred item(s) returned for re-decision "
                    "(not replayed; the caller re-validates each against the current price)",
                    (_now() - self.outage_since).total_seconds(),
                    held,
                )
            self.outage_since = None
        elif not serving and self._was_serving:
            self.outage_since = _now()
            # ERROR, not warning: the platform has stopped being able to see a
            # price. A handler that whispers is how the last one stayed unseen.
            logger.error(
                "Feed is no longer live (state=%s, sources_up=%d/%d, age=%s) — "
                "work arriving now will be deferred, not executed",
                self.health.state,
                self.health.sources_up,
                self.health.sources_total,
                "never" if self.health.age_s is None else f"{self.health.age_s:.1f}s",
            )
        elif not serving and self.outage_since is None:
            # First observation already down: the outage started no later than now.
            self.outage_since = _now()

        self._was_serving = serving
        return recovered

    def defer(
        self,
        *,
        kind: str,
        payload: dict[str, Any],
        reason: str = "feed_outage",
        price_context: dict[str, Any] | None = None,
    ) -> DeferredItem:
        return self.queue.defer(kind=kind, payload=payload, reason=reason, price_context=price_context)

    def as_dict(self) -> dict[str, Any]:
        return {
            "health": self.health.as_dict(),
            "queue": self.queue.as_dict(),
            "outage_since": self.outage_since.isoformat() if self.outage_since else None,
        }


#: Process-wide supervisor. One per process so the API, the engine and the
#: dashboard report the same outage rather than three views of it.
_supervisor: FeedOutageSupervisor | None = None


def get_supervisor() -> FeedOutageSupervisor:
    # One supervisor per process is the point: the API, the engine and the
    # dashboard must report the same outage, not three views of it.
    global _supervisor
    if _supervisor is None:
        _supervisor = FeedOutageSupervisor()
    return _supervisor

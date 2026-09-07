# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""A priority queue that cannot starve what is at the bottom of it. §14.

## The defect every plain priority queue has

A low-priority job that never runs because higher-priority work keeps arriving
is a job that silently never happens. The operator watching it sees `queued`,
and `queued` looks exactly the same whether the job is about to start or will
never start at all. Every priority scheme without ageing has this; the only
question is whether anyone has hit it yet.

So the number items are compared on is not their priority. It is

    rank = tier - (seconds waited / ageing_s)

Lower runs first. A `background` item is three tiers below `critical`, so after
three ageing periods of waiting it draws level with a `critical` item that has
just arrived, and after that it wins. The wait needed to overtake is exactly
the tier gap, which makes starvation bounded and stated rather than absent and
hoped for.

## FIFO inside a rank

Two items with the same effective rank come out in arrival order. Without that
tiebreak the order depends on dictionary iteration, which is not an order — and
a queue whose output order is incidental is one whose behaviour changes when
something unrelated is refactored.

## The tiers are §8's, not a second vocabulary

`ai.hub.contracts.PRIORITIES` already names them, in order of loudness. A
second list here would be free to drift from the one the surfaces use.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any, Final

from ai.hub.contracts import PRIORITIES
from ai.jobs.runner import QueueFull

#: Seconds of waiting worth one priority tier. Thirty seconds means a
#: background job overtakes a freshly-arrived critical one after 90 seconds of
#: waiting -- long enough that priority means something, short enough that
#: nothing is stuck behind a busy period.
DEFAULT_AGEING_S: Final[float] = 30.0

DEFAULT_MAX_QUEUED: Final[int] = 32

#: tier index by name, from the shared vocabulary rather than a second copy.
_TIER: Final[dict[str, int]] = {name: index for index, name in enumerate(PRIORITIES)}


@dataclass(frozen=True)
class Queued:
    """One waiting item: what it is, how loud, and since when."""

    id: str
    priority: str
    operator: str
    enqueued_at: float
    payload: Any = None
    #: Monotonically increasing, so equal ranks keep arrival order even when two
    #: items share a timestamp.
    sequence: int = 0


@dataclass
class AgeingPriorityQueue:
    """Priority with a bounded, provable worst case for the bottom tier."""

    max_queued: int = DEFAULT_MAX_QUEUED
    ageing_s: float = DEFAULT_AGEING_S
    _items: list[Queued] = field(default_factory=list, init=False, repr=False)
    _lock: threading.RLock = field(default_factory=threading.RLock, init=False, repr=False)
    _sequence: int = field(default=0, init=False, repr=False)

    def push(
        self,
        id: str,
        *,
        priority: str,
        operator: str,
        payload: Any = None,
        now: float | None = None,
    ) -> Queued:
        """Add an item. Raises `QueueFull` at the ceiling.

        An unrecognised priority is refused rather than defaulted: guessing
        would silently file work in a tier nobody chose.
        """
        if priority not in _TIER:
            raise ValueError(f"unknown priority {priority!r}; expected one of {', '.join(PRIORITIES)}")
        if not operator or not operator.strip():
            raise ValueError("queued work needs an operator; an unscoped item belongs to everybody")

        with self._lock:
            if len(self._items) >= self.max_queued:
                raise QueueFull(f"{len(self._items)} items are already waiting; the ceiling is {self.max_queued}")
            self._sequence += 1
            item = Queued(
                id=id,
                priority=priority,
                operator=operator,
                enqueued_at=now if now is not None else time.time(),
                payload=payload,
                sequence=self._sequence,
            )
            self._items.append(item)
            return item

    def rank(self, item: Queued, *, now: float | None = None) -> float:
        """Effective rank. Lower runs first. Falls as an item waits."""
        moment = now if now is not None else time.time()
        waited = max(0.0, moment - item.enqueued_at)
        return _TIER[item.priority] - (waited / self.ageing_s)

    def pop(self, *, now: float | None = None) -> Queued | None:
        """The item that should run next, or None when nothing is waiting."""
        moment = now if now is not None else time.time()
        with self._lock:
            if not self._items:
                return None
            best = min(self._items, key=lambda i: (self.rank(i, now=moment), i.sequence))
            self._items.remove(best)
            return best

    def remove(self, id: str) -> bool:
        """Drop a waiting item, e.g. because its job was cancelled."""
        with self._lock:
            for item in self._items:
                if item.id == id:
                    self._items.remove(item)
                    return True
        return False

    def waiting(self) -> int:
        with self._lock:
            return len(self._items)

    def snapshot(self, *, now: float | None = None) -> dict[str, Any]:
        """Depth AND the longest wait.

        Depth alone hides starvation: three waiting items could be three seconds
        old or three hours old, and only one of those is a problem.
        """
        moment = now if now is not None else time.time()
        with self._lock:
            by_priority: dict[str, int] = {}
            for item in self._items:
                by_priority[item.priority] = by_priority.get(item.priority, 0) + 1
            longest = max((moment - i.enqueued_at for i in self._items), default=0.0)
            return {
                "waiting": len(self._items),
                "by_priority": by_priority,
                "longest_wait_s": round(longest, 3),
                "ageing_s": self.ageing_s,
                "max_queued": self.max_queued,
            }


__all__ = ["DEFAULT_AGEING_S", "DEFAULT_MAX_QUEUED", "AgeingPriorityQueue", "Queued"]

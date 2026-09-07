# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""Events that start work, without the bus becoming the thing that does it. §14.

## The rule this module is built around

Phase A's rule was that **a message bus is not an execution path**. A trigger
that ran its task inside the subscriber callback would make it one: publishing
an event would then be indistinguishable from calling a function, and the two
gates in `ai/tools/bus.py` would sit beside the path rather than in front of
it.

So a trigger does exactly one thing when it matches: it puts an item on
`ai/jobs/priority.py`'s queue. Something else, later, with its own authority,
decides whether to run it. This module cannot import `ai.tools`, and a test
parses it to keep that true.

## Depth, because a task can publish what triggers it

`review-exposure` publishing a `drawdown` event is a loop that consumes the
whole queue. Every triggered item carries a depth, one higher than the message
that caused it, and a trigger refuses to fire past its ceiling. That is a
narrow guard for a specific shape; §26's "prevent runaway recursive delegation"
is a broader row and is not claimed by it.

## A failing trigger is recorded, not swallowed and not fatal

A predicate that raises, or a queue that is full, must not come back to the
publisher as a broken subscriber — the message was delivered correctly and the
trigger is what failed. Both are recorded on the registry, where somebody can
see that a trigger has stopped firing, which is the thing that would otherwise
be invisible.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Final

from ai.hub.contracts import PRIORITIES, AgentMessage

logger = logging.getLogger(__name__)

#: Where a triggered item's recursion depth lives, in the message body and in
#: the queued payload. One name, so the chain is readable end to end.
DEPTH_KEY: Final[str] = "trigger_depth"

#: How many hops a chain may take before a trigger stops firing.
DEFAULT_MAX_DEPTH: Final[int] = 2

_FAILURE_LIMIT: Final[int] = 100


@dataclass(frozen=True)
class Trigger:
    """When `when` holds for a message on `topic`, enqueue `task`."""

    name: str
    topic: str
    when: Callable[[AgentMessage], bool]
    task: str
    priority: str = "secondary"
    max_depth: int = DEFAULT_MAX_DEPTH

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("a trigger needs a name; an anonymous one cannot be reported as failing")
        if not self.task.strip():
            raise ValueError("a trigger needs a task to enqueue")
        if self.priority not in PRIORITIES:
            raise ValueError(f"unknown priority {self.priority!r}")
        if self.max_depth < 1:
            raise ValueError("max_depth below 1 disables the trigger; remove it instead of configuring it off")


@dataclass
class TriggerRegistry:
    """Subscribes triggers to a bus and enqueues what they match."""

    bus: Any
    queue: Any
    _failures: list[tuple[str, str]] = field(default_factory=list, init=False, repr=False)
    _fired: int = field(default=0, init=False, repr=False)

    def register(self, trigger: Trigger, *, operator: str) -> Any:
        """Subscribe `trigger` for one operator. Returns the subscription handle."""

        def _on_message(message: AgentMessage) -> None:
            self._consider(trigger, message, operator=operator)

        return self.bus.subscribe(
            trigger.topic,
            _on_message,
            operator=operator,
            subscriber=f"trigger:{trigger.name}",
        )

    def _consider(self, trigger: Trigger, message: AgentMessage, *, operator: str) -> None:
        depth = message.body.get(DEPTH_KEY, 0)
        try:
            depth = int(depth)
        except (TypeError, ValueError):
            depth = 0
        if depth >= trigger.max_depth:
            self._record(trigger.name, f"depth ceiling {trigger.max_depth} reached; not firing")
            return

        try:
            matched = bool(trigger.when(message))
        except Exception as exc:
            self._record(trigger.name, f"the predicate raised {type(exc).__name__}: {exc}")
            return
        if not matched:
            return

        payload = {
            "task": trigger.task,
            "trigger": trigger.name,
            "message_id": message.message_id,
            "task_id": message.task_id,
            "correlation_id": message.correlation_id,
            DEPTH_KEY: depth + 1,
        }
        try:
            self.queue.push(
                f"{trigger.name}:{message.message_id}",
                priority=trigger.priority,
                operator=operator,
                payload=payload,
            )
        except Exception as exc:
            # A full queue is the queue working. It is still recorded, because
            # "the trigger stopped firing" is otherwise invisible.
            self._record(trigger.name, f"the queue is full or refused the item: {exc}")
            return
        self._fired += 1

    def _record(self, name: str, why: str) -> None:
        logger.info("ai.bus.triggers: %s did not fire — %s", name, why)
        self._failures.append((name, why))
        if len(self._failures) > _FAILURE_LIMIT:
            del self._failures[:-_FAILURE_LIMIT]

    def failures(self) -> tuple[tuple[str, str], ...]:
        """`(trigger, why)` for every trigger that did not fire when it might have."""
        return tuple(self._failures)

    def fired(self) -> int:
        return self._fired


__all__ = ["DEFAULT_MAX_DEPTH", "DEPTH_KEY", "Trigger", "TriggerRegistry"]

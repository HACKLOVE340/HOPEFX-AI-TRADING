# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""Task lifecycle events and streaming partials, over the agent bus. §12.

§12 asks for two things this module provides together, because they are the
same thing seen twice: a task announces every state it enters, and while it is
`running` it announces what it has produced so far.

## The vocabulary was already decided

`ai.hub.contracts.MESSAGE_STATUSES` holds §12's seven statuses, and
`cancelled` and `timed_out` are deliberately distinct from `failed` because an
operator's next move differs for each: retry a failure, raise the ceiling for a
timeout, do nothing for a cancel. A lifecycle that collapsed them would erase
the only reason to have three words.

## Illegal transitions are refused, not logged

Terminal is terminal. A task that reports `succeeded` and then `running` has
told the screen two incompatible things, and whichever arrives second wins —
which means the displayed state depends on delivery order. Refusing at the
call site keeps that impossible rather than unlikely.

## Partials carry a sequence, so a gap is visible

A stream of partials rendered in arrival order is correct only if none is lost.
Numbering them from 1 lets a consumer notice `1, 2, 4` and say so, instead of
concatenating text that is missing a piece and looking complete.
"""

from __future__ import annotations

import threading
from typing import Any

from ai.hub.contracts import PRIORITIES, AgentMessage

#: Statuses after which nothing more may be said about this task.
_TERMINAL: frozenset[str] = frozenset({"succeeded", "failed", "cancelled", "timed_out"})

#: What may follow what. `queued` is the state a lifecycle starts in.
_ALLOWED: dict[str, frozenset[str]] = {
    "queued": frozenset({"running", "cancelled", "timed_out", "failed"}),
    "running": frozenset({"partial", "succeeded", "failed", "cancelled", "timed_out"}),
    # A partial is a state a task passes through repeatedly while running.
    "partial": frozenset({"partial", "succeeded", "failed", "cancelled", "timed_out"}),
}


class TaskLifecycle:
    """Publishes one task's state changes as `AgentMessage`s on the agent bus.

    Holds no bus authority of its own: it publishes, which moves data. Acting on
    what it publishes is somebody else's call through `ai/tools/bus.py`.
    """

    def __init__(
        self,
        bus: Any,
        *,
        operator: str,
        task_id: str,
        sender: str,
        recipient: str,
        priority: str = "primary",
        correlation_id: str = "",
    ) -> None:
        if priority not in PRIORITIES:
            raise ValueError(f"unknown priority {priority!r}")
        self._bus = bus
        self._operator = operator
        self._task_id = task_id
        self._sender = sender
        self._recipient = recipient
        self._priority = priority
        self._correlation_id = correlation_id or task_id
        self._status = "queued"
        self._sequence = 0
        self._lock = threading.RLock()

    @property
    def status(self) -> str:
        return self._status

    @property
    def sequence(self) -> int:
        """How many partials have been emitted. Zero is a measurement."""
        return self._sequence

    # -- transitions -----------------------------------------------------------

    def started(self, **body: Any) -> AgentMessage:
        return self._transition("running", body)

    def partial(self, body: dict[str, Any] | None = None, **extra: Any) -> AgentMessage:
        """One streamed fragment. Numbered from 1 so a gap can be detected."""
        with self._lock:
            payload = {**(body or {}), **extra}
            message = self._transition("partial", payload, _sequence_next=True)
        return message

    def succeeded(self, **body: Any) -> AgentMessage:
        return self._transition("succeeded", body)

    def failed(self, **body: Any) -> AgentMessage:
        return self._transition("failed", body)

    def cancelled(self, **body: Any) -> AgentMessage:
        return self._transition("cancelled", body)

    def timed_out(self, **body: Any) -> AgentMessage:
        return self._transition("timed_out", body)

    # -- the one path that builds and publishes --------------------------------

    def _transition(self, status: str, body: dict[str, Any], *, _sequence_next: bool = False) -> AgentMessage:
        with self._lock:
            current = self._status
            if current in _TERMINAL:
                raise ValueError(
                    f"task {self._task_id!r} is already {current}; "
                    f"{status!r} after a terminal status would contradict what was already reported",
                )
            allowed = _ALLOWED.get(current, frozenset())
            if status not in allowed:
                raise ValueError(
                    f"task {self._task_id!r} cannot go from {current!r} to {status!r}; "
                    f"allowed from here: {', '.join(sorted(allowed))}",
                )
            payload = dict(body)
            if _sequence_next:
                self._sequence += 1
                payload["sequence"] = self._sequence

            message = AgentMessage(
                task_id=self._task_id,
                sender=self._sender,
                recipient=self._recipient,
                correlation_id=self._correlation_id,
                priority=self._priority,  # type: ignore[arg-type]
                status=status,  # type: ignore[arg-type]
                body=payload,
            )
            self._status = status
        self._bus.publish(message, operator=self._operator)
        return message

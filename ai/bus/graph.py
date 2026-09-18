# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""A task graph, not a queue. §12.

A queue says what runs next. A graph says what *may* run next — which is a
different answer whenever two pieces of work depend on the same thing and on
nothing else. Fetching prices, then analysing technicals and sentiment from
them, then synthesising both, is a diamond: a queue offers one branch, a graph
offers both, and the difference is wall-clock time on every multi-agent task.

## A cycle is refused when the edge is added

`A -> B -> A` detected at schedule time means A has already run. There is no
undo for that: the model call was paid for, the memory write happened, the
notification went out. `add()` is the last moment at which nothing has
happened yet, so that is where the refusal lives — `add()` walks the edge it is
about to create and raises `CycleRefused` naming the cycle it found.

## Nothing is skipped quietly

A dependency that fails does not let its dependents run, and does not make them
disappear either. They become `blocked`, and `blocked()` names what blocked
each one. A dependent that vanished from the report would look, to whoever
reads it, exactly like a dependent that succeeded.

A dependency that was never added at all is not a silent no-op: it is listed by
`unknown_dependencies()`, and while any exists `ready()` returns nothing.
Offering work from a graph with a dangling edge means running a plan that was
not fully described.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Final, Literal

#: `pending` is not one of §12's message statuses — it is this graph's own word
#: for "declared, dependencies not yet satisfied". `blocked` likewise: it is
#: distinct from `failed` because the task itself did not fail.
TaskStatus = Literal["pending", "running", "succeeded", "failed", "cancelled", "timed_out", "blocked"]

#: Only these let a dependent proceed. A timeout is not a success: the work may
#: still be running somewhere, and its result was never seen.
_SATISFYING: Final[frozenset[str]] = frozenset({"succeeded"})

#: Outcomes that end a task without satisfying anything downstream.
_UNSATISFYING_TERMINAL: Final[frozenset[str]] = frozenset({"failed", "cancelled", "timed_out"})


class CycleRefused(ValueError):
    """The edge would close a cycle, so it was not created."""


@dataclass
class _Task:
    id: str
    depends_on: tuple[str, ...]
    status: TaskStatus = "pending"
    #: Which dependency blocked it. Empty while nothing has.
    blocked_by: str = ""
    payload: dict[str, Any] = field(default_factory=dict)


class TaskGraph:
    """A directed acyclic graph of tasks, acyclic by refusal rather than by hope."""

    def __init__(self) -> None:
        self._tasks: dict[str, _Task] = {}

    # -- construction ----------------------------------------------------------

    def add(self, task_id: str, *, depends_on: tuple[str, ...] = (), **payload: Any) -> None:
        """Declare a task. Raises `CycleRefused` if its edges close a cycle."""
        if not task_id or not task_id.strip():
            raise ValueError("a task needs an id")
        if task_id in self._tasks:
            raise ValueError(f"task {task_id!r} is already in this graph; a duplicate id makes the report ambiguous")
        deps = tuple(dict.fromkeys(depends_on))
        if task_id in deps:
            raise CycleRefused(f"{task_id} cannot depend on itself")

        # Walk forward from each dependency: if any path reaches `task_id`, the
        # edge about to be created closes a cycle.
        for dep in deps:
            path = self._path_to(dep, task_id)
            if path is not None:
                cycle = " -> ".join((task_id, *path))
                raise CycleRefused(f"adding {task_id!r} would close a cycle: {cycle} -> {task_id}")

        self._tasks[task_id] = _Task(id=task_id, depends_on=deps, payload=dict(payload))

    def _path_to(self, start: str, target: str) -> tuple[str, ...] | None:
        """A dependency path from `start` to `target`, or None."""
        if start == target:
            return (start,)
        task = self._tasks.get(start)
        if task is None:
            return None
        for dep in task.depends_on:
            found = self._path_to(dep, target)
            if found is not None:
                return (start, *found)
        return None

    # -- reading ---------------------------------------------------------------

    def unknown_dependencies(self) -> tuple[str, ...]:
        """Dependencies named by a task and never added. Sorted, deduplicated."""
        missing = {dep for task in self._tasks.values() for dep in task.depends_on if dep not in self._tasks}
        return tuple(sorted(missing))

    def ready(self) -> tuple[str, ...]:
        """Tasks that may run now.

        Empty while any dependency is unknown: a graph that is not fully
        described must not offer work, because the plan being executed is not
        the plan that was written.
        """
        if self.unknown_dependencies():
            return ()
        out = [
            task.id
            for task in self._tasks.values()
            if task.status == "pending" and all(self._tasks[dep].status in _SATISFYING for dep in task.depends_on)
        ]
        return tuple(out)

    def status(self, task_id: str) -> TaskStatus:
        return self._require(task_id).status

    def blocked(self) -> tuple[tuple[str, str], ...]:
        """`(task, the dependency that blocked it)` for every blocked task."""
        return tuple((task.id, task.blocked_by) for task in self._tasks.values() if task.status == "blocked")

    def report(self) -> dict[str, Any]:
        """Counts by state. `complete` is derived, never asserted.

        Unstarted work is counted as `pending`, not omitted: a report whose
        numbers only cover what has been touched reads as finished long before
        it is.
        """
        counts: dict[str, int] = {}
        for task in self._tasks.values():
            counts[task.status] = counts.get(task.status, 0) + 1
        total = len(self._tasks)
        settled = sum(v for k, v in counts.items() if k in _SATISFYING | _UNSATISFYING_TERMINAL | {"blocked"})
        return {
            "total": total,
            "pending": counts.get("pending", 0),
            "running": counts.get("running", 0),
            "succeeded": counts.get("succeeded", 0),
            "failed": counts.get("failed", 0),
            "cancelled": counts.get("cancelled", 0),
            "timed_out": counts.get("timed_out", 0),
            "blocked": counts.get("blocked", 0),
            "unknown_dependencies": self.unknown_dependencies(),
            "complete": total > 0 and settled == total,
        }

    # -- transitions -----------------------------------------------------------

    def started(self, task_id: str) -> None:
        task = self._require(task_id)
        if task.status != "pending":
            raise ValueError(f"task {task_id!r} is {task.status}, not pending; it cannot start")
        unknown = self.unknown_dependencies()
        if unknown:
            raise ValueError(
                f"this graph names dependencies that were never added ({', '.join(unknown)}); "
                "running it would execute a plan that was not fully described",
            )
        if task_id not in self.ready():
            unmet = [d for d in task.depends_on if self._tasks[d].status not in _SATISFYING]
            raise ValueError(f"task {task_id!r} is not ready: {', '.join(unmet)} has not succeeded")
        task.status = "running"

    def completed(self, task_id: str, status: TaskStatus) -> None:
        """Record an outcome. A task that never started cannot have one."""
        task = self._require(task_id)
        if status not in _SATISFYING | _UNSATISFYING_TERMINAL:
            raise ValueError(f"{status!r} is not an outcome; expected one of succeeded, failed, cancelled, timed_out")
        if task.status != "running":
            raise ValueError(
                f"task {task_id!r} is {task.status}; only a running task has an outcome, "
                "and recording one for a task that never ran invents a result",
            )
        task.status = status
        if status in _UNSATISFYING_TERMINAL:
            self._block_dependents()

    def _block_dependents(self) -> None:
        """Mark everything downstream blocked, transitively, naming the cause."""
        changed = True
        while changed:
            changed = False
            for task in self._tasks.values():
                if task.status != "pending":
                    continue
                for dep in task.depends_on:
                    upstream = self._tasks.get(dep)
                    if upstream is None:
                        continue
                    if upstream.status in _UNSATISFYING_TERMINAL or upstream.status == "blocked":
                        task.status = "blocked"
                        task.blocked_by = dep
                        changed = True
                        break

    def _require(self, task_id: str) -> _Task:
        task = self._tasks.get(task_id)
        if task is None:
            raise KeyError(f"no task {task_id!r} in this graph")
        return task

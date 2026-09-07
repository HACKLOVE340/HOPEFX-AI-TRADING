# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""Decompose, allocate, track, merge, resolve. §11's orchestrator row.

## It executes a graph; it does not re-implement ordering

`ai/bus/graph.py` already decides what may run: it refuses a cycle at
construction, offers every task whose dependencies have succeeded, and blocks
dependents of a failure by name. A second scheduler here would be how the graph
stops being the thing that decides — two orderings that agree until the day
they do not, and then disagree silently.

So `decompose` builds a `TaskGraph` and hands it back. `ready()` is the
orchestrator's answer to "what next", and there is no sorting anywhere in this
module.

## Decomposition is declared, not invented

`decompose` takes the steps it is given. Turning "what is gold doing" into a
list of steps is a planner's job and a paid model call; keeping that out of here
makes the graph deterministic, the tests real, and the model's output something
that passes through a contract rather than becoming one.

## Allocation names what it could not place

A step whose department does not exist, or whose action is not implemented, or
whose action would WRITE, is not assigned — and appears in `unassignable` with
the reason. A step dropped from the plan reads, in the report, exactly like a
step that ran and returned nothing.

Write actions are refused outright. The orchestrator plans; acting stays behind
`ai/tools/bus.py` and its two gates, where an operator and an approval exist.

## Merging keeps the silence

`merge` reports which tasks produced nothing, separately from what the others
produced. A result set that simply omits them is one where "no answer" and "no
task" look the same.

## Conflicts go to a debate, never to an average

Two agents reaching opposite conclusions is evidence about the question, not
noise to be smoothed. `ai/debate/session.py` scores the positions and is
allowed to answer UNRESOLVED — which averaging cannot do, and which is the
honest answer when the evidence has not separated the sides.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from ai.bus.graph import TaskGraph

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Step:
    """One declared unit of a plan."""

    task_id: str
    department: str
    action: str
    depends_on: tuple[str, ...] = ()
    params: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Assignment:
    """A step that can actually be carried out, and by what."""

    task_id: str
    department: str
    action: str


@dataclass(frozen=True)
class OrchestrationPlan:
    """The graph, what was allocated, and what could not be."""

    request: str
    graph: TaskGraph
    steps: tuple[Step, ...]
    assignments: tuple[Assignment, ...] = ()
    #: `(task_id, why)`. Never empty when a step was skipped.
    unassignable: tuple[tuple[str, str], ...] = ()

    def summary(self) -> dict[str, Any]:
        return {
            "request": self.request,
            "steps": len(self.steps),
            "assigned": len(self.assignments),
            "unassignable": [{"task_id": t, "why": w} for t, w in self.unassignable],
            "ready": list(self.graph.ready()),
            "graph": self.graph.report(),
        }


def decompose(request: str, steps: list[Step] | tuple[Step, ...]) -> OrchestrationPlan:
    """Build the graph for `steps`, then allocate them.

    Raises `CycleRefused` if the declared plan contains one — at construction,
    which is the last moment at which nothing has run.
    """
    if not request or not request.strip():
        raise ValueError("an orchestration needs a request it can be traced back to")

    graph = TaskGraph()
    for step in steps:
        graph.add(step.task_id, depends_on=step.depends_on)

    assignments, unassignable = _allocate(steps)
    return OrchestrationPlan(
        request=request,
        graph=graph,
        steps=tuple(steps),
        assignments=assignments,
        unassignable=unassignable,
    )


def _allocate(steps) -> tuple[tuple[Assignment, ...], tuple[tuple[str, str], ...]]:
    """Match each step to an implemented, read-only department action."""
    from ai.departments import DEPARTMENTS, implemented_actions

    available = {a.name: a for a in implemented_actions()}
    assigned: list[Assignment] = []
    refused: list[tuple[str, str]] = []

    for step in steps:
        if step.department not in DEPARTMENTS:
            refused.append((step.task_id, f"no department named {step.department!r}"))
            continue
        qualified = f"{step.department}.{step.action}"
        action = available.get(qualified)
        if action is None:
            refused.append(
                (step.task_id, f"{qualified} is not an implemented action; it cannot be allocated to anything")
            )
            continue
        if action.risk.name != "READ_ONLY":
            refused.append(
                (
                    step.task_id,
                    f"{qualified} is {action.risk.name}, not read-only; the orchestrator plans, and acting "
                    "stays behind the tool bus where an operator and an approval exist",
                )
            )
            continue
        assigned.append(Assignment(task_id=step.task_id, department=step.department, action=step.action))

    return tuple(assigned), tuple(refused)


def track(plan: OrchestrationPlan, task_id: str, status: str, *, bus: Any, operator: str) -> Any:
    """Publish one task's state change on the agent bus.

    Reuses §12's lifecycle vocabulary rather than inventing a second one, so a
    subscriber written for job progress reads orchestration progress too.
    """
    from ai.hub.contracts import AgentMessage

    step = next((s for s in plan.steps if s.task_id == task_id), None)
    if step is None:
        raise KeyError(f"no task {task_id!r} in this plan")

    message = AgentMessage(
        task_id=task_id,
        sender="orchestrator",
        recipient=step.department,
        correlation_id=plan.request[:64] or task_id,
        status=status,  # type: ignore[arg-type]
        body={"action": step.action, "request": plan.request},
    )
    bus.publish(message, operator=operator)
    return message


def merge(plan: OrchestrationPlan, results: dict[str, Any]) -> dict[str, Any]:
    """Combine what came back, and say what did not.

    `missing` is the point of this function. A result set that omits the tasks
    that answered nothing makes "no answer" and "no task" identical.
    """
    known = [s.task_id for s in plan.steps]
    present = {k: v for k, v in results.items() if k in known}
    missing = tuple(t for t in known if t not in present)
    unexpected = tuple(k for k in results if k not in known)
    return {
        "request": plan.request,
        "results": present,
        "missing": missing,
        "unexpected": unexpected,
        "complete": not missing,
    }


def resolve(*, subject: str, positions: list[Any], now: Any = None) -> Any:
    """Send a conflict to a debate. Never an average.

    Averaging two opposite conclusions produces a number nobody argued for and
    that no evidence supports. `debate` scores the positions and is allowed to
    answer UNRESOLVED, which is the honest outcome when the evidence has not
    separated the sides — and is not an outcome an average can express.

    A single stance is refused by `debate` itself: dressing one position as a
    debate implies an opposing view was sought and found wanting.
    """
    from ai.debate.session import debate

    return debate(subject=subject, positions=positions, now=now)


__all__ = ["Assignment", "OrchestrationPlan", "Step", "decompose", "merge", "resolve", "track"]

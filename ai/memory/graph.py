# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""§16: a knowledge graph across entities, projects and tasks.

What connects to what — a job to the report it produced, a symbol to the
position held in it, a proposal to the incident that prompted it. The value is
not the storage; it is being able to answer "why is this here?" a week later.

## The relations are declared, not invented

`RELATIONS` is a fixed vocabulary. A caller cannot link two things with a
relation nobody wrote down, for the same reason `hub/summary.ts` refuses to
invent a connection between two panels: an edge is a claim, and a claim the
reader cannot check is worse than no edge — they believe it.

## Per operator, and deletable

Edges are keyed by operator, and `ai/memory/governance.py` clears them when
somebody exercises a deletion. A deletion that left the graph behind would
leave the *shape* of what was deleted — who worked on what, and when — which is
most of what the graph was recording.

## Bounded

An edge list that only grows is a slow leak with no upper bound. The oldest go
first, which is the right end: the recent past is what "why is this here?" is
usually about.
"""

from __future__ import annotations

import threading
from collections import deque
from dataclasses import dataclass
from datetime import UTC, datetime

#: The relations this graph can express. Adding one is a deliberate act.
RELATIONS: frozenset[str] = frozenset(
    {
        "produced",  # a job produced a report
        "caused",  # an event caused another
        "relates_to",  # a general, weak association
        "part_of",  # a task is part of a project
        "supersedes",  # a newer fact replaces an older one
        "contradicts",  # two findings disagree
        "observed_by",  # a fact came from a department or watcher
        "concerns",  # a proposal concerns an instrument or account
    }
)

#: Edges kept per operator.
MAX_EDGES = 2000


@dataclass(frozen=True)
class Edge:
    """One directed, attributed relation."""

    subject: str
    relation: str
    entity: str
    source: str
    at: str


_LOCK = threading.Lock()
_EDGES: dict[str, deque[Edge]] = {}


def _edges(operator: str) -> deque[Edge]:
    if operator not in _EDGES:
        _EDGES[operator] = deque(maxlen=MAX_EDGES)
    return _EDGES[operator]


def link(subject: str, relation: str, entity: str, *, operator: str, source: str = "") -> Edge:
    """Record that `subject` stands in `relation` to `entity`."""
    if relation not in RELATIONS:
        raise ValueError(
            f"unknown relation {relation!r}; the graph expresses {sorted(RELATIONS)} and "
            "an invented edge is a claim the reader cannot check"
        )
    if not subject.strip() or not entity.strip():
        raise ValueError("an edge needs both ends")
    if not operator.strip():
        raise ValueError("an edge belongs to one operator")

    edge = Edge(
        subject=subject,
        relation=relation,
        entity=entity,
        source=source or "unattributed",
        at=datetime.now(UTC).isoformat(),
    )
    with _LOCK:
        _edges(operator).append(edge)
    return edge


def neighbours(subject: str, *, operator: str, relation: str | None = None) -> list[Edge]:
    """What this subject is connected to, for this operator."""
    with _LOCK:
        rows = list(_EDGES.get(operator, ()))
    return [e for e in rows if e.subject == subject and (relation is None or e.relation == relation)]


def incoming(entity: str, *, operator: str) -> list[Edge]:
    """What points AT this entity. The half a subject-keyed lookup misses."""
    with _LOCK:
        rows = list(_EDGES.get(operator, ()))
    return [e for e in rows if e.entity == entity]


def edge_count(operator: str) -> int:
    with _LOCK:
        return len(_EDGES.get(operator, ()))


def forget_operator(operator: str) -> int:
    """Drop this operator's whole graph. Called by the governed deletion path."""
    with _LOCK:
        edges = _EDGES.pop(operator, None)
        return len(edges) if edges else 0


def reset_for_testing() -> None:
    with _LOCK:
        _EDGES.clear()


__all__ = [
    "MAX_EDGES",
    "RELATIONS",
    "Edge",
    "edge_count",
    "forget_operator",
    "incoming",
    "link",
    "neighbours",
    "reset_for_testing",
]

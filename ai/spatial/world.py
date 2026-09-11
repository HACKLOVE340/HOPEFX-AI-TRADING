# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""A world is a graph of components, not a pile of triangles.

The first slice of the Universal 3D Builder, and deliberately not its renderer.
Every question the surrounding capabilities actually ask is a graph question:

    "What is this connected to?"        connections_of
    "What happens if I remove it?"      removal_impact
    "In what order is it built?"        assembly_order
    "What does it take to build?"       bill_of_materials

The Construction Brain, the Time Machine, the What-If Laboratory and the
documentation generator all need those answers, and none of them needs geometry
to get one. Geometry attaches to a component later; a component cannot attach to
geometry retroactively without redoing the model, which is why this is the slice
that goes first.

## A load path is a claim, not a fact

`removal_impact` returns `PROCEDURALLY_GENERATED` and never more. The graph
knows this beam supports that floor because **somebody declared the
connection** — an assertion about a drawing, not a measurement of a building.
Whether the structure stands without it is a question for a solver that has not
run. Returning this result at any higher rung would be the exact failure
`ai/spatial/assurance.py` exists to prevent, arriving through the back door.

## Refusals, taken from code that already works here

**A cycle is refused when the edge is added** — `ai/bus/graph.py`'s rule. A
support cycle found at traversal time means a structure has already been
ordered, costed, or drawn on the assumption it was sound. `connect()` is the
last moment at which nothing has been built on it.

Only `SUPPORTS` must be acyclic. Pipes and wiring legitimately form loops; a
ring main is not a structural impossibility, and refusing it would teach people
to model plumbing as something else.

**An unknown id raises** — `frontend/src/hub/sceneGraph.ts`'s rule. Returning an
empty list for a typo reads identically to returning one for a component that
genuinely carries nothing. One is a misspelling, the other is a cantilever.

**A connection to a component that does not exist is refused**, rather than
recorded and resolved later. A dangling edge means the model is not fully
described, and every count taken from it afterwards is wrong by an unknown
amount.

Pure and side-effect free: no renderer, no solver, no I/O. The predicates in
`invariants/spatial.py` enforce the assurance rules where these results cross
into a decision.
"""

from __future__ import annotations

from collections import Counter, deque
from dataclasses import dataclass
from enum import Enum

from ai.spatial.assurance import Assurance

__all__ = [
    "Component",
    "Connection",
    "ConnectionKind",
    "ConnectionRefused",
    "RemovalImpact",
    "UnknownComponent",
    "World",
]


class ConnectionKind(Enum):
    """How one component relates to another.

    `SUPPORTS` is the only structural one, and the only one held acyclic — it is
    the relation that carries load, and load cannot travel in a circle.
    """

    SUPPORTS = "supports"
    FEEDS = "feeds"
    FASTENS = "fastens"
    ENCLOSES = "encloses"


class UnknownComponent(KeyError):
    """An id that is not in this world.

    A `KeyError` rather than a returned empty result, because "no such
    component" and "that component holds nothing up" are different answers and
    only one of them is a bug.
    """


class ConnectionRefused(ValueError):
    """An edge that would make the model describe an impossible structure."""


@dataclass(frozen=True)
class Component:
    """One part of a world — a beam, a slab, a motor, a wall panel."""

    id: str
    kind: str
    material: str


@dataclass(frozen=True)
class Connection:
    source: str
    target: str
    kind: ConnectionKind


@dataclass(frozen=True)
class RemovalImpact:
    """What taking one component out would do to the rest of the model.

    `assurance` is carried on the result rather than left to the caller to
    remember. A finding that travels without its rung is a finding that will be
    read as a structural conclusion.
    """

    removed: str
    unsupported: tuple[str, ...]
    disconnected: tuple[str, ...]
    assurance: Assurance = Assurance.PROCEDURALLY_GENERATED


class World:
    """A named collection of components and the relations between them."""

    def __init__(self, name: str) -> None:
        self.name = name
        self._components: dict[str, Component] = {}
        self._connections: list[Connection] = []

    # ── building ────────────────────────────────────────────────────────────

    def add(self, component: Component) -> None:
        if component.id in self._components:
            raise ValueError(
                f"component {component.id!r} is already in this world; "
                "a duplicate id makes every count taken from the model ambiguous"
            )
        self._components[component.id] = component

    def connect(self, source: str, target: str, kind: ConnectionKind) -> None:
        """Relate two components, refusing anything the model cannot mean."""
        for cid in (source, target):
            if cid not in self._components:
                raise UnknownComponent(f"no component {cid!r} in world {self.name!r}")
        if source == target:
            raise ConnectionRefused(f"{source!r} cannot connect to itself")
        if kind is ConnectionKind.SUPPORTS and self._would_close_support_cycle(source, target):
            raise ConnectionRefused(
                f"{source!r} supporting {target!r} would close a support cycle; load cannot travel in a circle"
            )
        self._connections.append(Connection(source=source, target=target, kind=kind))

    def _would_close_support_cycle(self, source: str, target: str) -> bool:
        """True if `target` already supports `source`, directly or through others."""
        seen: set[str] = set()
        queue = deque([target])
        while queue:
            node = queue.popleft()
            if node == source:
                return True
            if node in seen:
                continue
            seen.add(node)
            queue.extend(self.supports(node))
        return False

    # ── interrogating ───────────────────────────────────────────────────────

    def _require(self, component_id: str) -> None:
        if component_id not in self._components:
            raise UnknownComponent(f"no component {component_id!r} in world {self.name!r}")

    def component_ids(self) -> tuple[str, ...]:
        return tuple(self._components)

    def component(self, component_id: str) -> Component:
        """The component itself, raising on an id this world does not hold."""
        self._require(component_id)
        return self._components[component_id]

    @property
    def connections(self) -> tuple[Connection, ...]:
        return tuple(self._connections)

    def supports(self, component_id: str) -> tuple[str, ...]:
        """What this component holds up, directly."""
        self._require(component_id)
        return tuple(
            c.target for c in self._connections if c.source == component_id and c.kind is ConnectionKind.SUPPORTS
        )

    def supported_by(self, component_id: str) -> tuple[str, ...]:
        """What holds this component up, directly."""
        self._require(component_id)
        return tuple(
            c.source for c in self._connections if c.target == component_id and c.kind is ConnectionKind.SUPPORTS
        )

    def connections_of(self, component_id: str) -> tuple[Connection, ...]:
        """Every relation this component takes part in, in either direction."""
        self._require(component_id)
        return tuple(c for c in self._connections if component_id in (c.source, c.target))

    # ── derived answers ─────────────────────────────────────────────────────

    def assembly_order(self) -> tuple[str, ...]:
        """An order in which nothing is installed before what carries it.

        A component connected to nothing still appears. An orphan dropped from
        the sequence is a part nobody installs and nothing reports missing —
        `ai/bus/graph.py`'s "nothing is skipped quietly", applied to a build.

        Ties are broken by insertion order so the sequence is deterministic:
        two runs producing different valid orders would make a Time Machine
        replay irreproducible.
        """
        remaining = {cid: set(self.supported_by(cid)) for cid in self._components}
        order: list[str] = []
        while remaining:
            ready = [cid for cid in self._components if cid in remaining and not remaining[cid]]
            if not ready:  # pragma: no cover - connect() refuses the cycles that cause this
                raise ConnectionRefused(f"support cycle among {sorted(remaining)}")
            for cid in ready:
                order.append(cid)
                del remaining[cid]
            for deps in remaining.values():
                deps.difference_update(ready)
        return tuple(order)

    def removal_impact(self, component_id: str) -> RemovalImpact:
        """What loses its load path, and what loses its connection, if this goes.

        A component with another support left is NOT reported unsupported. A
        warning that fires on every removal is one people switch off, and the
        second beam is the whole reason the floor is still up.

        The result is `PROCEDURALLY_GENERATED`: the graph is repeating what was
        declared, not predicting what a building would do.
        """
        self._require(component_id)

        unsupported: list[str] = []
        frontier = deque([component_id])
        gone = {component_id}
        while frontier:
            for dependent in self.supports(frontier.popleft()):
                if dependent in gone:
                    continue
                if set(self.supported_by(dependent)) - gone:
                    continue  # something else still holds it up
                gone.add(dependent)
                unsupported.append(dependent)
                frontier.append(dependent)

        disconnected = sorted(
            {
                (c.target if c.source == component_id else c.source)
                for c in self.connections_of(component_id)
                if c.kind is not ConnectionKind.SUPPORTS
            }
        )
        return RemovalImpact(
            removed=component_id,
            unsupported=tuple(unsupported),
            disconnected=tuple(disconnected),
        )

    def bill_of_materials(self) -> dict[tuple[str, str], int]:
        """How many of each (kind, material) the model calls for."""
        return dict(Counter((c.kind, c.material) for c in self._components.values()))

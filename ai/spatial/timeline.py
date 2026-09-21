# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""The Construction Time Machine — step through a build, and fork it anywhere.

Capability #5. `World.assembly_order()` already returns a deterministic sequence
in which nothing is installed before what carries it. This turns that sequence
into something you can stop inside, look around, and branch from.

Branching is here rather than later because the What-If Laboratory (#8) is built
on it: *"what if this building were twice as tall"* is a branch taken at a stage,
re-derived, and compared against the trunk. That comparison means nothing unless
the trunk is still exactly what it was, which is what most of the rules below
protect.

## A Construction snapshots

`World` is mutable — `add` and `connect` are public and are how anything gets
built. A Construction holding a live reference would let history rewrite itself:
edit the world, and the build you recorded an hour ago silently becomes a
different build, with no diff and no event. **A time machine whose past changes
is not a time machine**, so the world is copied at construction time.

The copy is the same shape as `World`, not a deep clone of arbitrary objects:
`Component` and `Connection` are frozen dataclasses, so copying the containers is
sufficient and there is no shared mutable state to leak.

## A stage is PROCEDURALLY_GENERATED and never more

The sequence is derived from declared dependencies. Nobody watched this get
built. If real site telemetry is fed in later that is a different rung entirely,
and the field exists so the difference can be represented rather than argued
about.

## A connection is live only when both its ends exist

Otherwise stage 1 shows a beam bolted to a floor that has not been built. The
connection is real in the *design* from the moment it is declared; it is real in
the *build* only once both components are standing, and a time machine is
showing the build.

## Out of range raises

Clamping `at(999)` to the last stage answers a question about a build that never
had 999 steps with a picture of a finished building. `StageOutOfRange` names the
step it was given and the range that exists.
"""

from __future__ import annotations

from dataclasses import dataclass

from ai.spatial.assurance import Assurance
from ai.spatial.world import Component, Connection, World

__all__ = ["Construction", "Stage", "StageOutOfRange", "WorldState"]


class StageOutOfRange(IndexError):
    """A step that this build does not have."""


@dataclass(frozen=True)
class Stage:
    """One installation in the sequence.

    `assurance` rides on the stage rather than being left for the caller to
    remember, for the same reason `RemovalImpact` carries its own: a finding that
    travels without its rung gets read as a stronger claim than it is.
    """

    index: int
    installed: str
    assurance: Assurance = Assurance.PROCEDURALLY_GENERATED


@dataclass(frozen=True)
class WorldState:
    """What exists after some number of installations."""

    step: int
    components: tuple[str, ...]
    connections: tuple[Connection, ...]


def _copy_world(source: World) -> World:
    """A structural copy. `Component` and `Connection` are frozen, so the
    containers are the only mutable state and copying them is the whole job."""
    copy = World(name=source.name)
    for cid in source.component_ids():
        c = source.component(cid)
        copy.add(Component(id=c.id, kind=c.kind, material=c.material))
    for conn in source.connections:
        copy.connect(conn.source, conn.target, conn.kind)
    return copy


class Construction:
    """A recorded build of one world, steppable and branchable."""

    def __init__(
        self,
        world: World,
        *,
        name: str = "trunk",
        diverged_from: Construction | None = None,
        diverged_at: int | None = None,
    ) -> None:
        self.name = name
        self.world = _copy_world(world)
        self.diverged_from = diverged_from
        self.diverged_at = diverged_at
        self._stages = tuple(Stage(index=i, installed=cid) for i, cid in enumerate(self.world.assembly_order()))

    def stages(self) -> tuple[Stage, ...]:
        return self._stages

    def at(self, step: int) -> WorldState:
        """The model as it stands after `step` installations.

        `step` counts installations, so 0 is the empty site and
        `len(stages())` is the finished build.
        """
        if step < 0 or step > len(self._stages):
            raise StageOutOfRange(f"step {step} is outside this build, which has steps 0..{len(self._stages)}")
        installed = tuple(s.installed for s in self._stages[:step])
        standing = set(installed)
        return WorldState(
            step=step,
            components=installed,
            connections=tuple(c for c in self.world.connections if c.source in standing and c.target in standing),
        )

    def branch(self, at_step: int, name: str) -> Construction:
        """Fork the build at `at_step`, keeping everything installed by then.

        The branch gets its own world, so editing it cannot reach the trunk, and
        it records where it came from so the What-If Laboratory can compare the
        two without being told.
        """
        state = self.at(at_step)  # raises StageOutOfRange before anything is copied
        standing = set(state.components)

        forked = World(name=f"{self.world.name}:{name}")
        for cid in state.components:
            c = self.world.component(cid)
            forked.add(Component(id=c.id, kind=c.kind, material=c.material))
        for conn in self.world.connections:
            if conn.source in standing and conn.target in standing:
                forked.connect(conn.source, conn.target, conn.kind)

        return Construction(forked, name=name, diverged_from=self, diverged_at=at_step)

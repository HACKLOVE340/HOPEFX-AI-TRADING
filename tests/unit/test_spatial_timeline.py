# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""The Construction Time Machine: step through the build, and branch from any point.

Capability #5. `World.assembly_order()` already returns a deterministic sequence
in which nothing is installed before what carries it; this turns that sequence
into something you can stop inside, look around, and fork.

The What-If Laboratory (#8) is the reason branching is here and not later: "what
if this building were twice as tall" is a branch taken at a stage, re-derived,
and compared against the trunk. That comparison is only meaningful if the trunk
is still exactly what it was, which is what most of the rules below protect.

Five rules:

1. A Construction SNAPSHOTS its world. `World` is mutable — `add` and `connect`
   are public — so a Construction holding a live reference would let history
   rewrite itself. A time machine whose past changes is not a time machine.
2. A stage is `PROCEDURALLY_GENERATED`. It is a sequence derived from declared
   dependencies, not an observation of anybody building anything.
3. `at()` out of range RAISES. Clamping would answer "step 999" with a finished
   building, which is a confident answer to a question about a build that never
   had 999 steps.
4. A connection becomes live only when BOTH its endpoints exist. Otherwise the
   model shows a beam bolted to a floor that has not been built.
5. A branch never mutates its parent.
"""

from __future__ import annotations

import pytest

from ai.spatial.assurance import Assurance
from ai.spatial.timeline import Construction, StageOutOfRange
from ai.spatial.world import Component, ConnectionKind, World

pytestmark = pytest.mark.unit


def _house() -> World:
    w = World(name="house")
    for cid, kind, material in [
        ("foundation", "foundation", "concrete"),
        ("slab", "slab", "concrete"),
        ("beam", "beam", "steel"),
        ("floor", "floor", "timber"),
    ]:
        w.add(Component(id=cid, kind=kind, material=material))
    w.connect("foundation", "slab", ConnectionKind.SUPPORTS)
    w.connect("slab", "beam", ConnectionKind.SUPPORTS)
    w.connect("beam", "floor", ConnectionKind.SUPPORTS)
    return w


# ── Rule 1: the past does not change ────────────────────────────────────────


class TestAConstructionSnapshots:
    def test_the_construction_does_not_hold_the_callers_world(self) -> None:
        w = _house()
        assert Construction(w).world is not w, "a live reference lets the caller rewrite recorded history"

    def test_a_connection_added_later_between_installed_components_does_not_appear(self) -> None:
        """The behavioural half, and the one that actually discriminates.

        Asserting on `stages()` alone does NOT: it is computed once in
        `__init__` and frozen, so it is unchanged whether the world is copied or
        merely referenced — a mutation replacing the copy with a live reference
        left all fourteen tests green. Neither does adding a new component,
        because `at()` filters connections to what is standing and the newcomer
        never is.

        A connection between two components that are ALREADY installed passes
        that filter. With a live reference it appears in a state recorded before
        it was drawn; with a snapshot it cannot.
        """
        w = _house()
        c = Construction(w)
        w.connect("foundation", "beam", ConnectionKind.FASTENS)
        pairs = [(x.source, x.target) for x in c.at(3).connections]
        assert ("foundation", "beam") not in pairs, "history acquired a connection drawn after it was recorded"

    def test_editing_the_world_afterwards_does_not_change_the_recorded_build(self) -> None:
        w = _house()
        c = Construction(w)
        before = c.stages()

        w.add(Component(id="chimney", kind="chimney", material="brick"))
        w.connect("floor", "chimney", ConnectionKind.SUPPORTS)

        assert c.stages() == before, "the recorded build changed when the world was edited afterwards"
        assert "chimney" not in c.at(len(before)).components

    def test_a_later_construction_sees_the_edit(self) -> None:
        """The snapshot is of the world AT CONSTRUCTION TIME, not a permanent
        freeze of the world object."""
        w = _house()
        first = Construction(w)
        w.add(Component(id="chimney", kind="chimney", material="brick"))
        second = Construction(w)
        assert len(second.stages()) == len(first.stages()) + 1


# ── Rule 2: a derived order is not an observed one ──────────────────────────


def test_a_stage_is_procedurally_generated_and_never_more() -> None:
    """The sequence comes from declared dependencies. Nobody watched this get
    built, and if site telemetry is fed in later that is a different rung."""
    assert Construction(_house()).stages()[0].assurance is Assurance.PROCEDURALLY_GENERATED


# ── Stepping through ────────────────────────────────────────────────────────


class TestSteppingThroughTheBuild:
    def test_the_sequence_respects_the_load_path(self) -> None:
        installed = [s.installed for s in Construction(_house()).stages()]
        assert installed == ["foundation", "slab", "beam", "floor"]

    def test_the_state_at_a_step_holds_everything_installed_so_far(self) -> None:
        c = Construction(_house())
        assert c.at(0).components == ()
        assert c.at(2).components == ("foundation", "slab")
        assert c.at(4).components == ("foundation", "slab", "beam", "floor")

    def test_a_connection_is_live_only_once_both_ends_exist(self) -> None:
        """Rule 4. At step 1 the foundation stands alone: the connection to the
        slab is real in the design and not yet real in the build."""
        c = Construction(_house())
        assert c.at(1).connections == ()
        assert [(x.source, x.target) for x in c.at(2).connections] == [("foundation", "slab")]

    def test_asking_for_a_step_that_does_not_exist_raises(self) -> None:
        """Rule 3. Clamping would answer with a finished building."""
        c = Construction(_house())
        with pytest.raises(StageOutOfRange, match="999"):
            c.at(999)
        with pytest.raises(StageOutOfRange):
            c.at(-1)

    def test_the_sequence_is_deterministic_across_constructions(self) -> None:
        """A replay that came back different each time would make every
        comparison in the What-If Laboratory meaningless."""
        assert Construction(_house()).stages() == Construction(_house()).stages()


# ── Branching ───────────────────────────────────────────────────────────────


class TestBranching:
    def test_a_branch_shares_history_up_to_the_divergence_point(self) -> None:
        trunk = Construction(_house())
        branch = trunk.branch(at_step=2, name="taller")
        assert [s.installed for s in branch.stages()[:2]] == ["foundation", "slab"]

    def test_a_branch_records_where_it_diverged_and_from_what(self) -> None:
        """The What-If Laboratory compares a branch against its trunk. It cannot
        do that if the branch does not know what it came from."""
        trunk = Construction(_house())
        branch = trunk.branch(at_step=2, name="taller")
        assert branch.name == "taller"
        assert branch.diverged_from is trunk
        assert branch.diverged_at == 2

    def test_editing_a_branch_does_not_touch_the_trunk(self) -> None:
        """Rule 5. The comparison is only meaningful if the trunk is untouched."""
        trunk = Construction(_house())
        before = trunk.stages()
        branch = trunk.branch(at_step=2, name="taller")
        branch.world.add(Component(id="storey_2", kind="floor", material="timber"))
        branch.world.connect("slab", "storey_2", ConnectionKind.SUPPORTS)
        assert trunk.stages() == before
        assert "storey_2" not in trunk.at(4).components

    def test_a_branch_rebuilt_after_an_edit_reflects_it(self) -> None:
        trunk = Construction(_house())
        branch = trunk.branch(at_step=2, name="taller")
        branch.world.add(Component(id="storey_2", kind="floor", material="timber"))
        branch.world.connect("slab", "storey_2", ConnectionKind.SUPPORTS)
        # Three components: foundation and slab from the divergence, plus the
        # new storey. Written as at(5) first, and StageOutOfRange refused it —
        # the guard catching an off-by-three in the test that wrote it.
        rebuilt = Construction(branch.world)
        assert len(rebuilt.stages()) == 3
        assert "storey_2" in rebuilt.at(3).components

    def test_branching_at_an_impossible_step_raises(self) -> None:
        with pytest.raises(StageOutOfRange):
            Construction(_house()).branch(at_step=99, name="nowhere")

    def test_branching_at_zero_is_allowed(self) -> None:
        """Starting over from nothing is a legitimate what-if."""
        branch = Construction(_house()).branch(at_step=0, name="clean-sheet")
        assert branch.diverged_at == 0
        assert branch.world.component_ids() == ()

# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""The component graph: what is connected to what, and what breaks if it goes.

The first slice of the Universal 3D Builder, and deliberately not its renderer.
"What is this connected to?", "what happens if I remove it?", assembly order and
a bill of materials are all graph questions, and every later capability -- the
Construction Brain, the Time Machine, the What-If Laboratory, the documentation
generator -- needs the answers before any of them needs triangles.

Two disciplines carried in from code that already exists here:

* `ai/bus/graph.py` -- a cycle is refused when the EDGE IS ADDED, because by the
  time a cycle is noticed at traversal the plan has already been walked into.
  A dangling edge is named, never silently skipped.
* `frontend/src/hub/sceneGraph.ts` -- an unknown id RAISES. Returning empty
  reads identically to "nothing is connected to this", and those are different
  bugs -- one is a typo, the other is a cantilever.

And the rule from the assurance ladder: a load path is a claim. The graph knows
this beam supports that floor because somebody declared the connection, which is
PROCEDURALLY_GENERATED and never more. Whether the structure actually stands
without it is a question for a solver that has not run.
"""

from __future__ import annotations

import pytest

from ai.spatial.assurance import Assurance
from ai.spatial.world import (
    Component,
    ConnectionRefused,
    ConnectionKind,
    UnknownComponent,
    World,
)

pytestmark = pytest.mark.unit


def _house() -> World:
    """A deliberately small structure with one real load path.

    foundation -> ground_floor_slab -> beam_a -> upper_floor
                                    -> beam_b -> upper_floor
    and a kitchen sink that is plumbed but carries nothing.
    """
    w = World(name="test-house")
    for cid, kind, material in [
        ("foundation", "foundation", "concrete"),
        ("slab", "slab", "concrete"),
        ("beam_a", "beam", "steel"),
        ("beam_b", "beam", "steel"),
        ("upper_floor", "floor", "timber"),
        ("sink", "fixture", "ceramic"),
        ("water_main", "supply", "copper"),
    ]:
        w.add(Component(id=cid, kind=kind, material=material))
    w.connect("foundation", "slab", ConnectionKind.SUPPORTS)
    w.connect("slab", "beam_a", ConnectionKind.SUPPORTS)
    w.connect("slab", "beam_b", ConnectionKind.SUPPORTS)
    w.connect("beam_a", "upper_floor", ConnectionKind.SUPPORTS)
    w.connect("beam_b", "upper_floor", ConnectionKind.SUPPORTS)
    w.connect("water_main", "sink", ConnectionKind.FEEDS)
    return w


# ── Building the graph ──────────────────────────────────────────────────────


class TestTheGraphRefusesRatherThanGuesses:
    def test_a_duplicate_id_is_refused(self) -> None:
        w = World(name="w")
        w.add(Component(id="beam", kind="beam", material="steel"))
        with pytest.raises(ValueError, match="already"):
            w.add(Component(id="beam", kind="beam", material="timber"))

    def test_a_connection_to_an_unknown_component_is_refused_at_connect_time(self) -> None:
        """`ai/bus/graph.py`'s rule. The last moment at which nothing has been
        built on a false assumption is when the edge is made.

        Deliberately FEEDS, not SUPPORTS. With SUPPORTS this test passed even
        with the endpoint guard deleted, because the cycle check then walked
        `supports('ghost')` and raised the same exception from a different rule
        — a test green for a reason that was not the one it named. FEEDS never
        reaches the cycle check, so only the endpoint guard can refuse it.
        """
        w = World(name="w")
        w.add(Component(id="beam", kind="beam", material="steel"))
        with pytest.raises(UnknownComponent, match="ghost"):
            w.connect("beam", "ghost", ConnectionKind.FEEDS)
        assert w.connections == (), "a refused connection must leave no dangling edge behind"

    def test_a_component_cannot_support_itself(self) -> None:
        w = World(name="w")
        w.add(Component(id="beam", kind="beam", material="steel"))
        with pytest.raises(ConnectionRefused, match="itself"):
            w.connect("beam", "beam", ConnectionKind.SUPPORTS)

    def test_a_support_cycle_is_refused_when_the_edge_is_added(self) -> None:
        """A supports B supports A is not a structure, it is a drawing error.
        Caught at the edge, not at the traversal."""
        w = World(name="w")
        for cid in ("a", "b", "c"):
            w.add(Component(id=cid, kind="beam", material="steel"))
        w.connect("a", "b", ConnectionKind.SUPPORTS)
        w.connect("b", "c", ConnectionKind.SUPPORTS)
        with pytest.raises(ConnectionRefused, match="cycle"):
            w.connect("c", "a", ConnectionKind.SUPPORTS)

    def test_a_non_structural_cycle_is_allowed(self) -> None:
        """Pipes and wiring legitimately form loops. Only SUPPORTS must be
        acyclic — a ring main is not a structural impossibility."""
        w = World(name="w")
        for cid in ("p1", "p2"):
            w.add(Component(id=cid, kind="pipe", material="copper"))
        w.connect("p1", "p2", ConnectionKind.FEEDS)
        w.connect("p2", "p1", ConnectionKind.FEEDS)
        assert len(w.connections) == 2

    def test_a_pipe_may_feed_back_to_the_thing_that_holds_it_up(self) -> None:
        """The case that actually discriminates a kind-scoped cycle check.

        A pure FEEDS loop cannot: the detector only walks SUPPORTS edges, so it
        is invisible to the check whether or not the check is kind-scoped, and
        the test above passes either way. Here the SUPPORTS edge makes the loop
        visible — a riser supports a pump that feeds back into it, which is
        ordinary plumbing and must not be refused as a structural cycle.
        """
        w = World(name="w")
        w.add(Component(id="riser", kind="pipe", material="copper"))
        w.add(Component(id="pump", kind="pump", material="steel"))
        w.connect("riser", "pump", ConnectionKind.SUPPORTS)
        w.connect("pump", "riser", ConnectionKind.FEEDS)
        assert len(w.connections) == 2

    def test_the_cycle_check_terminates_on_a_diamond(self) -> None:
        """Two beams on one slab, both carrying one floor, is a diamond: walking
        forward reaches `upper_floor` by two paths. Without the visited set the
        detector re-walks the whole subtree per path, which is exponential on a
        real structure and would make `connect()` the slowest call in the
        builder. Adding a column under the slab is the edge that forces the
        traversal through it.
        """
        w = _house()
        w.add(Component(id="column", kind="column", material="steel"))
        w.connect("column", "slab", ConnectionKind.SUPPORTS)
        assert set(w.supported_by("slab")) == {"foundation", "column"}

    def test_an_unknown_id_raises_rather_than_returning_nothing(self) -> None:
        """sceneGraph.ts's rule: an empty answer for a typo is indistinguishable
        from an empty answer for a component that genuinely carries nothing."""
        with pytest.raises(UnknownComponent):
            _house().supported_by("gost_beam")


# ── What is connected to what ───────────────────────────────────────────────


class TestInterrogatingTheModel:
    def test_what_a_component_directly_supports(self) -> None:
        assert set(_house().supports("slab")) == {"beam_a", "beam_b"}

    def test_what_holds_a_component_up(self) -> None:
        assert set(_house().supported_by("upper_floor")) == {"beam_a", "beam_b"}

    def test_connections_are_reported_with_their_kind(self) -> None:
        conns = _house().connections_of("sink")
        assert [(c.source, c.kind) for c in conns] == [("water_main", ConnectionKind.FEEDS)]

    def test_a_component_carrying_nothing_reports_an_empty_list_not_an_error(self) -> None:
        """The distinction the raise above protects: a KNOWN component with no
        dependents is a real, ordinary answer."""
        assert _house().supports("sink") == ()


# ── Assembly order ──────────────────────────────────────────────────────────


class TestAssemblyOrder:
    def test_a_supporting_component_is_always_assembled_before_what_it_carries(self) -> None:
        order = _house().assembly_order()
        pos = {cid: i for i, cid in enumerate(order)}
        assert pos["foundation"] < pos["slab"] < pos["beam_a"] < pos["upper_floor"]
        assert pos["beam_b"] < pos["upper_floor"]

    def test_every_component_appears_exactly_once(self) -> None:
        order = _house().assembly_order()
        assert sorted(order) == sorted(_house().component_ids())
        assert len(order) == len(set(order))

    def test_an_unconnected_component_is_still_in_the_order(self) -> None:
        """An orphan that vanished from the build sequence would be a part
        nobody installs, and nothing would report it missing."""
        w = _house()
        w.add(Component(id="doormat", kind="fixture", material="coir"))
        assert "doormat" in w.assembly_order()


# ── Removal impact — the capability this exists for ─────────────────────────


class TestRemovalImpact:
    def test_removing_a_support_reports_what_loses_its_load_path(self) -> None:
        impact = _house().removal_impact("slab")
        assert set(impact.unsupported) == {"beam_a", "beam_b", "upper_floor"}

    def test_a_component_with_a_second_support_is_not_reported_unsupported(self) -> None:
        """upper_floor rests on two beams. Removing one leaves it held. Reporting
        it as unsupported would cry wolf, and a warning that cries wolf gets
        switched off."""
        impact = _house().removal_impact("beam_a")
        assert "upper_floor" not in impact.unsupported
        assert impact.unsupported == ()

    def test_removal_impact_reports_severed_non_structural_connections_too(self) -> None:
        impact = _house().removal_impact("water_main")
        assert "sink" in impact.disconnected

    def test_the_finding_is_procedurally_generated_and_never_simulated(self) -> None:
        """THE rule. The graph knows the beam supports the floor because somebody
        declared it. Whether the building stands is a question for a solver that
        has not run, and this result must never be mistaken for its answer."""
        assert _house().removal_impact("slab").assurance is Assurance.PROCEDURALLY_GENERATED

    def test_removing_an_unknown_component_raises(self) -> None:
        with pytest.raises(UnknownComponent):
            _house().removal_impact("nonesuch")


# ── Bill of materials (capability 11's foundation) ──────────────────────────


class TestBillOfMaterials:
    def test_components_are_counted_by_kind_and_material(self) -> None:
        bom = _house().bill_of_materials()
        assert bom[("beam", "steel")] == 2
        assert bom[("foundation", "concrete")] == 1

    def test_an_empty_world_yields_an_empty_bill_not_an_error(self) -> None:
        assert World(name="empty").bill_of_materials() == {}

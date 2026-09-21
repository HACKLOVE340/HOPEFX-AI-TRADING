# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""Phase H7 — §4's four layers, measured instead of asserted.

The plan kept these two rows last "so they cannot be claimed early". That is a
scheduling answer to a structural problem, and it only works while somebody
remembers. A roll-up whose state is TYPED is a claim about other claims with
nothing measuring it — F176's exact shape, one level up: `scripts/
invariant_coverage.py` certified components by counting hand-typed `True`
literals and could not print anything except full coverage.

So `layer_state` derives each roll-up from the rows beneath it. Every
capability already carries its layer, so no new bookkeeping is introduced —
the information was there and nothing was reading it.

## What the derivation found

`arch.layer_c.workforce` was marked **live** while two of its eighty-two rows
were staged. That is the overstatement this file exists to make impossible, and
it was written by hand, in good faith, by somebody who had just finished four
of its departments.

Deriving it costs a live row. That is the correct direction: a headline number
that goes down when you start measuring it was wrong before, not now.
"""

from __future__ import annotations

import pytest

from ai.hub.capabilities import REGISTRY, ROLLUP_IDS, layer_state

pytestmark = pytest.mark.unit


def _constituents(layer: str) -> list:
    """Every row in a layer that is not itself a roll-up."""
    return [c for c in REGISTRY if c.layer == layer and c.id not in ROLLUP_IDS]


class TestTheRollupsAreDerivedRatherThanTyped:
    @pytest.mark.parametrize("layer", ["A", "B", "C", "D"])
    def test_each_layer_has_exactly_one_rollup(self, layer: str) -> None:
        found = [c for c in REGISTRY if c.id in ROLLUP_IDS and c.layer == layer]
        assert len(found) == 1, f"layer {layer} has {len(found)} roll-up rows"

    @pytest.mark.parametrize("layer", ["A", "B", "C", "D"])
    def test_the_rollup_state_matches_what_the_layer_measures(self, layer: str) -> None:
        rollup = next(c for c in REGISTRY if c.id in ROLLUP_IDS and c.layer == layer)
        assert rollup.state == layer_state(layer), (
            f"{rollup.id} says {rollup.state!r} and its rows measure {layer_state(layer)!r}"
        )

    @pytest.mark.parametrize("layer", ["A", "B", "C", "D"])
    def test_a_layer_is_live_only_when_every_row_in_it_is(self, layer: str) -> None:
        not_live = [c.id for c in _constituents(layer) if c.state != "live"]
        if layer_state(layer) == "live":
            assert not_live == [], f"layer {layer} claims live with {not_live} outstanding"
        else:
            assert not_live, f"layer {layer} is not live and every row in it is"

    def test_a_layer_with_nothing_started_is_planned_not_staged(self) -> None:
        # Synthetic: no layer is in this state today, and the rule still has to
        # exist — a roll-up over nothing begun must not read as partly done.
        assert layer_state("A", rows=[]) == "planned"

    def test_one_started_row_makes_a_layer_staged(self) -> None:
        class _Row:
            state = "staged"

        assert layer_state("A", rows=[_Row()]) == "staged"

    def test_one_outstanding_row_is_enough_to_stop_live(self) -> None:
        class _Row:
            def __init__(self, state: str) -> None:
                self.state = state

        assert layer_state("A", rows=[_Row("live"), _Row("live")]) == "live"
        assert layer_state("A", rows=[_Row("live"), _Row("staged")]) == "staged"
        assert layer_state("A", rows=[_Row("live"), _Row("planned")]) == "staged"


class TestTheRollupsCarryNoEvidenceOfTheirOwn:
    def test_a_rollup_points_at_the_derivation_not_at_a_module(self) -> None:
        # A roll-up naming one module would be claiming a whole layer on one
        # file's existence, which is how `agents.system` came to point at
        # `platform_engineering` — two rows, one module, twelve agents reported
        # and eleven present.
        for rollup in (c for c in REGISTRY if c.id in ROLLUP_IDS):
            if rollup.state == "planned":
                assert rollup.evidence == "", f"{rollup.id} is planned and carries evidence"
            else:
                assert "capabilities" in rollup.evidence, (
                    f"{rollup.id} points at {rollup.evidence!r} rather than at the derivation"
                )

    def test_every_rollup_says_what_is_outstanding(self) -> None:
        for rollup in (c for c in REGISTRY if c.id in ROLLUP_IDS):
            if rollup.state == "live":
                continue
            outstanding = [c.id for c in _constituents(rollup.layer) if c.state != "live"]
            for row in outstanding:
                assert row in rollup.note, f"{rollup.id} does not name {row} as outstanding"


class TestTheDerivationCannotBeBypassed:
    def test_coverage_still_resolves_every_claim(self) -> None:
        from ai.hub.capabilities import coverage

        report = coverage()
        assert report["discrepancies"] == []
        assert report["verified"] == report["checked"]

    def test_the_headline_counts_add_up(self) -> None:
        from ai.hub.capabilities import coverage

        report = coverage()
        assert report["live"] + report["staged"] + report["planned"] == report["total"]
        assert report["total"] == len(REGISTRY)

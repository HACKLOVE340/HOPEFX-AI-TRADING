# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""The volume index is generated, and says so — so it has to still match.

A document that claims "generated from the source" while nobody can regenerate it
is worse than one edited by hand, because the claim discourages the checking the
hand-edited version would get. The generator is `scripts/group4_index.py`; this
pins that the committed file is still its output.
"""

from __future__ import annotations

import pytest

from scripts.group4_index import INDEX, OWNER, render

pytestmark = [pytest.mark.unit]


class TestTheCommittedIndexMatchesItsGenerator:
    def test_it_has_not_drifted(self) -> None:
        assert INDEX.read_text(encoding="utf-8") == render(), (
            "docs/ai/specs/GROUP4_VOLUME_INDEX.md differs from its generator — "
            "run `python scripts/group4_index.py --generate`"
        )

    def test_the_generator_produced_a_real_document(self) -> None:
        # The comparison above passes if `render()` returned the empty string and
        # the file were empty too.
        text = render()
        assert len(text) > 20_000, len(text)
        assert text.count("\n| ") > 290, "fewer table rows than there are source titles"


class TestRoutingIsCompleteAndDeliberate:
    def test_every_volume_has_an_owner(self) -> None:
        # An unrouted volume is a volume nobody will build. The renderer prints
        # "Unrouted" rather than crashing, so the check belongs here.
        assert "Unrouted" not in render()

    def test_all_twenty_volumes_are_routed(self) -> None:
        assert len(OWNER) == 20, sorted(OWNER)

    def test_no_owner_entry_is_blank(self) -> None:
        assert all(owner.strip() and covers.strip() for owner, covers in OWNER.values())

# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""The spatial specification's status table, made unable to lie.

`docs/ai/specs/SPATIAL_INTELLIGENCE.md` carries sixteen capabilities and a
status for each: built, partial, or planned. That table is the answer to "what
can this system actually do", and as prose it rots the moment a module is
renamed — the row keeps saying `partial` and pointing at a file that is gone.

This is the same problem `AOS_INVARIANT_REGISTER.toml` had, solved the same way:
the statuses move into TOML, every claim names evidence, and a checker RESOLVES
the evidence instead of reading it.

The rules, each tested below:

1. `built` and `partial` must carry evidence, and every piece must resolve — a
   module that imports, an attribute that exists, a path on disk.
2. `planned` must carry NO evidence. The capability registry's own words: "a
   pointer to nothing reads as progress".
3. `partial` and `planned` must state a gap; `built` must not.
4. The declared entry count must match the rows.
5. Positive control: if nothing can be resolved against, refuse rather than
   report. A checker with an empty universe agrees with every claim.
"""

from __future__ import annotations

import pytest

from scripts import spatial_capabilities as sc

pytestmark = pytest.mark.unit


def _reg(body: str, entries: int = 1) -> str:
    return f'[meta]\nspec = "test"\nentries = {entries}\nmapped_on = "2026-09-11"\n\n{body}'


def _write(tmp_path, body: str, entries: int = 1):
    p = tmp_path / "caps.toml"
    p.write_text(_reg(body, entries), encoding="utf-8")
    return p


# ── Refusals: the check itself must be trustworthy ──────────────────────────


def test_a_missing_register_is_refused(tmp_path):
    with pytest.raises(sc.RegisterBroken, match="not found"):
        sc.check(tmp_path / "nope.toml")


def test_a_register_with_no_entries_is_refused(tmp_path):
    p = tmp_path / "caps.toml"
    p.write_text('[meta]\nspec = "t"\nentries = 0\nmapped_on = "2026-09-11"\n', encoding="utf-8")
    with pytest.raises(sc.RegisterBroken, match="no entries"):
        sc.check(p)


def test_a_declared_count_that_disagrees_is_refused(tmp_path):
    body = '[cap-0]\ntitle = "t"\nstatus = "planned"\nevidence = []\ngap = "g"\n'
    with pytest.raises(sc.RegisterBroken, match="declares 16"):
        sc.check(_write(tmp_path, body, entries=16))


def test_an_unresolvable_universe_is_refused(tmp_path, monkeypatch):
    """The positive control. If the spatial package cannot be seen at all, every
    `built` row would resolve to "missing" — or, with the comparison the other
    way round, to silent agreement. Neither is an answer."""
    monkeypatch.setattr(sc, "_universe_is_live", lambda: False)
    body = '[cap-0]\ntitle = "t"\nstatus = "planned"\nevidence = []\ngap = "g"\n'
    with pytest.raises(sc.RegisterBroken, match="cannot be resolved"):
        sc.check(_write(tmp_path, body))


# ── Blocking findings ───────────────────────────────────────────────────────


def test_evidence_naming_a_module_that_does_not_exist_blocks(tmp_path):
    body = '[cap-0]\ntitle = "t"\nstatus = "built"\nevidence = ["ai.spatial.no_such_module"]\ngap = ""\n'
    report = sc.check(_write(tmp_path, body))
    assert any("no_such_module" in b for b in report.blocking)


def test_evidence_naming_an_attribute_that_does_not_exist_blocks(tmp_path):
    body = '[cap-0]\ntitle = "t"\nstatus = "built"\nevidence = ["ai.spatial.world:NoSuchClass"]\ngap = ""\n'
    report = sc.check(_write(tmp_path, body))
    assert any("NoSuchClass" in b for b in report.blocking)


def test_evidence_naming_a_path_that_does_not_exist_blocks(tmp_path):
    body = '[cap-0]\ntitle = "t"\nstatus = "built"\nevidence = ["ai/spatial/ghost.py"]\ngap = ""\n'
    report = sc.check(_write(tmp_path, body))
    assert any("ghost.py" in b for b in report.blocking)


def test_a_dotted_attribute_resolves_to_a_method(tmp_path):
    """`World.assembly_order` is better evidence than `World`: it names the thing
    the capability actually needs, so renaming the method breaks the claim rather
    than leaving it pointing vaguely at a class that still exists."""
    body = '[cap-0]\ntitle = "t"\nstatus = "built"\nevidence = ["ai.spatial.world:World.assembly_order"]\ngap = ""\n'
    assert sc.check(_write(tmp_path, body)).blocking == []


def test_a_dotted_attribute_that_does_not_exist_blocks(tmp_path):
    body = '[cap-0]\ntitle = "t"\nstatus = "built"\nevidence = ["ai.spatial.world:World.no_such_method"]\ngap = ""\n'
    report = sc.check(_write(tmp_path, body))
    assert any("no_such_method" in b for b in report.blocking)


def test_a_built_capability_with_no_evidence_blocks(tmp_path):
    body = '[cap-0]\ntitle = "t"\nstatus = "built"\nevidence = []\ngap = ""\n'
    report = sc.check(_write(tmp_path, body))
    assert any("no evidence" in b for b in report.blocking)


def test_a_planned_capability_that_names_evidence_blocks(tmp_path):
    """A pointer to nothing reads as progress — the capability registry's own rule."""
    body = '[cap-0]\ntitle = "t"\nstatus = "planned"\nevidence = ["ai.spatial.world"]\ngap = "g"\n'
    report = sc.check(_write(tmp_path, body))
    assert any("planned" in b.lower() for b in report.blocking)


def test_a_partial_capability_without_a_gap_blocks(tmp_path):
    body = '[cap-0]\ntitle = "t"\nstatus = "partial"\nevidence = ["ai.spatial.world"]\ngap = ""\n'
    report = sc.check(_write(tmp_path, body))
    assert any("gap" in b for b in report.blocking)


def test_a_partial_capability_with_no_evidence_blocks(tmp_path):
    """Partial means SOME of it exists, so it must name which part. Found by
    mutation: neutralising this branch left all seventeen tests green, because
    only the `built` equivalent was covered."""
    body = '[cap-0]\ntitle = "t"\nstatus = "partial"\nevidence = []\ngap = "g"\n'
    report = sc.check(_write(tmp_path, body))
    assert any("no evidence" in b for b in report.blocking)


def test_a_planned_capability_without_a_gap_blocks(tmp_path):
    """Planned with no gap is a row that says only "not done" — it carries no
    information a reader can act on. Also found by mutation."""
    body = '[cap-0]\ntitle = "t"\nstatus = "planned"\nevidence = []\ngap = ""\n'
    report = sc.check(_write(tmp_path, body))
    assert any("gap" in b for b in report.blocking)


def test_a_built_capability_that_states_a_gap_blocks(tmp_path):
    body = '[cap-0]\ntitle = "t"\nstatus = "built"\nevidence = ["ai.spatial.world"]\ngap = "still missing things"\n'
    report = sc.check(_write(tmp_path, body))
    assert any("gap" in b for b in report.blocking)


def test_an_unknown_status_blocks(tmp_path):
    body = '[cap-0]\ntitle = "t"\nstatus = "nearly"\nevidence = []\ngap = "g"\n'
    report = sc.check(_write(tmp_path, body))
    assert any("nearly" in b for b in report.blocking)


def test_resolvable_evidence_is_accepted(tmp_path):
    body = (
        '[cap-0]\ntitle = "t"\nstatus = "built"\n'
        'evidence = ["ai.spatial.world:World", "ai/spatial/timeline.py"]\ngap = ""\n'
    )
    report = sc.check(_write(tmp_path, body))
    assert report.blocking == []
    assert report.built == 1


# ── The shipped register ────────────────────────────────────────────────────


def test_the_shipped_register_resolves_clean():
    report = sc.check()
    assert report.blocking == [], report.blocking


def test_the_shipped_register_covers_every_capability_in_the_specification():
    """Sixteen capabilities: the epistemic ladder plus the owner's fifteen. A
    capability missing from here is one that can be forgotten."""
    report = sc.check()
    assert report.entries == 16
    assert report.built + report.partial + report.planned == report.entries

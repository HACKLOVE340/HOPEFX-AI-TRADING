# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""The AOS conformance register must be unable to claim coverage it does not have.

`docs/ai/specs/AOS_INVARIANT_REGISTER.toml` maps the 26 invariants of the
MASTER_AI_OPERATING_SYSTEM specification's §30 onto what this repository
actually enforces. A prose map goes stale silently: a predicate gets renamed,
the row keeps naming it, and the register reads as coverage forever.

`scripts/aos_conformance.py` resolves every claim against the live
`invariants.registry` and against the filesystem, so a row cannot rot into
fiction. These tests prove the checker can fail — Group 2's Rule 1. Every case
below constructs a register that SHOULD be refused and asserts it is.
"""

from __future__ import annotations

import pytest

from scripts import aos_conformance as aos

pytestmark = pytest.mark.unit


def _register(body: str, entries: int = 1) -> str:
    return f'[meta]\nspec = "test"\nsection = "test"\nentries = {entries}\nmapped_on = "2026-09-10"\n\n{body}'


def _write(tmp_path, body: str, entries: int = 1):
    path = tmp_path / "register.toml"
    path.write_text(_register(body, entries), encoding="utf-8")
    return path


# ── Positive control: the checker must refuse to run against nothing ─────────


def test_a_registry_that_discovers_nothing_is_refused(tmp_path, monkeypatch):
    """F255: a harness that never ran agrees with every assertion.

    If `discover_predicates()` returns nothing, every `predicates = [...]` claim
    would resolve to "not found" — or, worse, a checker written the other way
    round would find nothing to contradict. Either way the answer is meaningless,
    so the checker refuses rather than reporting."""
    monkeypatch.setattr(aos, "discover_predicates", dict)
    path = _write(tmp_path, '[AOS-X-001]\ntitle = "t"\nstatus = "ABSENT"\npredicates = []\ngap = "none"\n')
    with pytest.raises(aos.ConformanceBroken, match="no predicates"):
        aos.check(path)


def test_an_empty_register_is_refused(tmp_path):
    path = tmp_path / "register.toml"
    path.write_text('[meta]\nspec = "t"\nsection = "t"\nentries = 0\nmapped_on = "2026-09-10"\n', encoding="utf-8")
    with pytest.raises(aos.ConformanceBroken, match="no entries"):
        aos.check(path)


def test_a_missing_register_is_refused(tmp_path):
    with pytest.raises(aos.ConformanceBroken, match="not found"):
        aos.check(tmp_path / "absent.toml")


def test_a_declared_entry_count_that_disagrees_is_refused(tmp_path):
    """meta.entries is the spec's own count. If the file has drifted from it,
    a row was dropped or duplicated and every total below it is wrong."""
    path = _write(tmp_path, '[AOS-X-001]\ntitle = "t"\nstatus = "ABSENT"\npredicates = []\ngap = "g"\n', entries=26)
    with pytest.raises(aos.ConformanceBroken, match="declares 26"):
        aos.check(path)


# ── Blocking findings: rows that claim more than the repository has ──────────


def test_a_predicate_that_does_not_exist_blocks(tmp_path):
    body = (
        '[AOS-X-001]\ntitle = "t"\nstatus = "COVERED"\n'
        'predicates = ["verify_no_such_predicate_exists_anywhere"]\ngap = ""\n'
    )
    report = aos.check(_write(tmp_path, body))
    assert any("verify_no_such_predicate_exists_anywhere" in b for b in report.blocking)


def test_covered_with_no_evidence_blocks(tmp_path):
    body = '[AOS-X-001]\ntitle = "t"\nstatus = "COVERED"\npredicates = []\ngap = ""\n'
    report = aos.check(_write(tmp_path, body))
    assert any("no evidence" in b for b in report.blocking)


def test_absent_that_names_a_predicate_blocks(tmp_path):
    """ABSENT means nothing enforces this. Naming a predicate contradicts that."""
    body = '[AOS-X-001]\ntitle = "t"\nstatus = "ABSENT"\npredicates = ["verify_human_can_stop"]\ngap = "g"\n'
    report = aos.check(_write(tmp_path, body))
    assert any("ABSENT" in b for b in report.blocking)


def test_partial_without_a_gap_blocks(tmp_path):
    """PARTIAL without a gap is the label doing no work — it reads as coverage."""
    body = '[AOS-X-001]\ntitle = "t"\nstatus = "PARTIAL"\npredicates = ["verify_human_can_stop"]\ngap = ""\n'
    report = aos.check(_write(tmp_path, body))
    assert any("gap" in b for b in report.blocking)


def test_covered_carrying_a_gap_blocks(tmp_path):
    body = (
        '[AOS-X-001]\ntitle = "t"\nstatus = "COVERED"\npredicates = ["verify_human_can_stop"]\ngap = "missing bits"\n'
    )
    report = aos.check(_write(tmp_path, body))
    assert any("gap" in b for b in report.blocking)


def test_an_unknown_status_blocks(tmp_path):
    body = '[AOS-X-001]\ntitle = "t"\nstatus = "MOSTLY"\npredicates = []\ngap = "g"\n'
    report = aos.check(_write(tmp_path, body))
    assert any("MOSTLY" in b for b in report.blocking)


def test_a_mechanism_path_that_does_not_exist_blocks(tmp_path):
    """A row may be COVERED by a script+test rather than a predicate. That claim
    is only worth anything if the files are still there."""
    body = (
        '[AOS-X-001]\ntitle = "t"\nstatus = "COVERED"\npredicates = []\ngap = ""\n'
        'mechanism = ["scripts/no_such_generator.py"]\n'
    )
    report = aos.check(_write(tmp_path, body))
    assert any("no_such_generator" in b for b in report.blocking)


def test_a_mechanism_path_that_exists_is_accepted(tmp_path):
    body = (
        '[AOS-X-001]\ntitle = "t"\nstatus = "COVERED"\npredicates = []\ngap = ""\n'
        'mechanism = ["scripts/gate_evidence.py"]\n'
    )
    report = aos.check(_write(tmp_path, body))
    assert report.blocking == []
    assert report.covered == 1


# ── The shipped register ────────────────────────────────────────────────────


def test_the_shipped_register_resolves_clean():
    report = aos.check()
    assert report.blocking == [], report.blocking


def test_the_shipped_register_totals_reconcile():
    report = aos.check()
    assert report.entries == 26
    assert report.covered + report.partial + report.absent == report.entries


# ── Name collisions ─────────────────────────────────────────────────────────
#
# `verify_dual_control` is defined TWICE — in `invariants/assurance.py` as
# (action_sensitive: bool, distinct_approvers: int) under "No Loss Of Human
# Control", and in `invariants/governance.py` as (approvals, required) under
# "No Unauthorized Capital Movement". Different signatures, different rules,
# same name. Python keeps them apart by module; a register that names
# predicates as bare strings cannot. So the checker says so rather than
# resolving to whichever it found first.


def test_an_ambiguous_bare_name_is_noted_not_silently_resolved(tmp_path):
    body = '[AOS-X-001]\ntitle = "t"\nstatus = "COVERED"\npredicates = ["verify_dual_control"]\ngap = ""\n'
    report = aos.check(_write(tmp_path, body))
    assert report.blocking == []
    assert any("verify_dual_control" in n and "assurance" in n and "governance" in n for n in report.notes)


def test_a_module_qualified_name_resolves(tmp_path):
    body = '[AOS-X-001]\ntitle = "t"\nstatus = "COVERED"\npredicates = ["governance.verify_dual_control"]\ngap = ""\n'
    report = aos.check(_write(tmp_path, body))
    assert report.blocking == []
    assert report.notes == []


def test_a_qualified_name_naming_the_wrong_module_blocks(tmp_path):
    """`verify_dual_control` exists — but not in `risk`. Resolving on the bare
    name alone would call this claim good."""
    body = '[AOS-X-001]\ntitle = "t"\nstatus = "COVERED"\npredicates = ["risk.verify_dual_control"]\ngap = ""\n'
    report = aos.check(_write(tmp_path, body))
    assert any("risk.verify_dual_control" in b for b in report.blocking)


def test_definitions_and_unique_names_are_reported_separately():
    """CLAUDE.md and the invariants skill both state 339 predicates. That is the
    DEFINITION count. Unique names is one lower, because of the collision above.
    Reporting only the unique count would read as a contradiction of both docs."""
    from invariants.registry import predicate_count

    report = aos.check()
    assert report.definitions == predicate_count()
    assert report.known_predicates == report.definitions - 1

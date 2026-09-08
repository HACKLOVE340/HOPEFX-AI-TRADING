# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""Rule 1, made checkable instead of remembered.

> A control that cannot fail is not a control. Every gate ships with evidence it
> is capable of returning a negative result.

The evidence existed — in commit messages, terminal scrollback and test
docstrings. None of that is auditable, so the rule was enforced by whoever
happened to remember it. Seven controls that could not fail have been found in
this repository; two of them today, in code that had been running nightly.

This is the ledger that fixes it. Gates are **discovered**, never hand-listed, so
a new gate cannot be added and quietly omitted. Each needs a row saying whether
its ability to fail has been demonstrated, by what injection, and where that
injection lives as a re-runnable test.

The debt is ratcheted: the gates that have no evidence today are the baseline,
and that number may only fall.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.gate_evidence import (
    EvidenceBroken,
    check,
    discover_gates,
    load,
)

pytestmark = [pytest.mark.unit]

REPO = Path(__file__).resolve().parents[2]


class TestGatesAreDiscoveredNotListed:
    """A hand-maintained list of gates is a list that goes stale the first time
    somebody adds a gate — and the omission looks exactly like compliance."""

    def test_every_ci_gate_script_is_found(self) -> None:
        found = {g.id for g in discover_gates()}
        on_disk = {p.stem for p in (REPO / "scripts" / "ci").glob("gate_*.py")}
        assert on_disk <= found, f"not discovered: {sorted(on_disk - found)}"

    def test_repo_local_precommit_hooks_are_found(self) -> None:
        ids = {g.id for g in discover_gates()}
        # Hooks that run this repository's own scripts. Third-party tools are
        # excluded deliberately — see the module docstring in gate_evidence.py.
        for expected in ("docs-registry", "docs-freshness", "group4-preservation"):
            assert expected in ids, f"{expected} not discovered"

    def test_discovery_finds_a_substantial_surface(self) -> None:
        # The positive control. Every assertion in this file passes against a
        # discoverer that returns nothing.
        assert len(discover_gates()) >= 18, len(discover_gates())

    def test_no_gate_is_discovered_twice(self) -> None:
        ids = [g.id for g in discover_gates()]
        assert len(ids) == len(set(ids)), sorted({i for i in ids if ids.count(i) > 1})


class TestTheLedgerIsHonest:
    def test_every_discovered_gate_has_a_row(self) -> None:
        rows = {e.id for e in load()[0]}
        missing = sorted({g.id for g in discover_gates()} - rows)
        assert missing == [], (
            f"gates with no row in docs/GATE_EVIDENCE.toml: {missing}. "
            "Run `python scripts/gate_evidence.py --generate`."
        )

    def test_claimed_evidence_points_at_a_file_that_exists(self) -> None:
        for entry in load()[0]:
            if entry.evidence:
                assert (REPO / entry.evidence).exists(), f"{entry.id} cites missing evidence {entry.evidence}"

    def test_a_gate_with_evidence_says_what_was_injected(self) -> None:
        # "There is a test" is not the claim Rule 1 makes. The claim is that a
        # specific defect was introduced and the control fired.
        for entry in load()[0]:
            if entry.evidence:
                assert entry.injected.strip(), f"{entry.id} cites evidence but records no injected defect"

    def test_gate_l_is_recorded_as_proven(self) -> None:
        # The one this phase demonstrated: seven incidents injected into a
        # copied tree, seven refusals.
        entry = next(e for e in load()[0] if e.id == "gate_l_safety_invariants")
        assert entry.evidence, "gate L was proven in this phase but the ledger does not say so"
        assert (REPO / entry.evidence).exists()


class TestTheRatchet:
    def test_the_unproven_count_has_not_increased(self) -> None:
        report = check()
        assert not report.blocking, "\n".join(report.blocking)

    def test_a_new_gate_without_a_row_blocks(self, tmp_path: Path) -> None:
        # The mechanism's whole purpose: a gate arriving with no evidence must
        # stop the commit rather than join a backlog nobody reads.
        report = check(extra_gate_ids=["gate_z_invented_for_this_test"])
        assert any("gate_z_invented" in b for b in report.blocking), report.blocking

    def test_evidence_that_stopped_existing_blocks(self) -> None:
        report = check(evidence_override={"gate_l_safety_invariants": "tests/unit/test_deleted.py"})
        assert any("gate_l" in b for b in report.blocking), report.blocking


class TestItRefusesRatherThanReportingClean:
    def test_an_empty_discovery_raises(self, tmp_path: Path) -> None:
        # Rule 3, and the ripgrep lesson: a sweep that examined nothing must not
        # report "nothing wrong".
        with pytest.raises(EvidenceBroken):
            check(repo=tmp_path)

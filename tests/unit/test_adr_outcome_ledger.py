# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""The ADR outcome ledger — the half of Chapter 9 that records what happened.

Not to be confused with `test_decision_ledger.py`, which covers `ai/ledger/` —
the *operational* ledger of decisions the platform takes at runtime (Group 3
Chapters 7 and 8, ADR 0010). This file is about *design* decisions by humans:
`docs/decisions/` and its outcomes.

ADR-LEDGER. `GROUP4_CONSTITUTION.md` Chapter 9 requires an Architecture
Decision Registry **and** a Decision Ledger across seven fields: context,
alternatives, evidence, decision, expected outcome, actual outcome, lessons.
`scripts/adr.py` enforced the first five. Nothing asked for the last two, and no
record carried one — so every decision was a minute and none was memory.

The fix could not be an edit to the record. An accepted ADR is immutable but for
its status line (Group 3 Ch 3 — "editing a record destroys the only evidence of
what was known when"), and building the ledger by relaxing that would have paid
for the second half by destroying the first. So the outcome lives in a second,
deliberately mutable artefact keyed by decision number: `docs/decisions/outcomes/NNNN.md`.
ADR 0020 records that choice and the option it beat.

These tests hold four things the mechanism must do, and the last two are the
ones that stop it from becoming a box to tick:

1. Tell a decision that has an outcome from one that does not.
2. Leave ADR immutability **exactly** as strict as it was.
3. Distinguish an outcome that was *observed* from one that is merely *pending*
   — otherwise eighteen placeholder files would read as a complete ledger.
4. Fail when a pending review falls due. A ledger whose obligation never comes
   due is a measurement that cannot fail (`hopefx-dead-controls`).
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import re
import subprocess  # nosec B404 — git, fixed args, test-only
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

#: Named by GROUP4_CONSTITUTION Chapter 9, not read from the implementation —
#: a parametrize over `adr.OUTCOME_SECTIONS` turns a missing attribute into a
#: collection error, which takes every other test in this file down with it and
#: reports nothing about what is wrong.
REQUIRED = ("Expected", "Actual outcome", "Lessons")

_spec = importlib.util.spec_from_file_location("_adr_under_test", ROOT / "scripts" / "adr.py")
adr = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
# Registered before exec: `@dataclasses.dataclass` resolves annotations through
# `sys.modules[cls.__module__]`, so a module executed outside it raises.
sys.modules[_spec.name] = adr
_spec.loader.exec_module(adr)


RECORD = """# {n:04d}. A decision that was made

- Status: {status}
- Date: 2026-01-01

## Context

Something forced a choice.

## Options considered

- **A.** Costs: one thing.
- **B.** Costs: another.

## Decision

A.

## Consequences

It makes X easy and Y hard.

## Evidence

`python -c "print(1)"`
"""

OBSERVED = """# Outcome {n:04d} — A decision that was made

- Decision: {n:04d}
- Status: observed
- Observed: 2026-02-01

## Expected

X would get easier.

## Actual outcome

X got easier; Y got harder than expected, by a factor of two.

## Lessons

The cost estimate for Y was drawn from one module and applied to twelve.
"""

PENDING = """# Outcome {n:04d} — A decision that was made

- Decision: {n:04d}
- Status: pending
- Review by: {review}

## Expected

X would get easier.

## Actual outcome

Not yet observable — the change has not been through a release.

## Lessons

Pending.
"""


def _tree(tmp_path: Path, records: dict[int, str], outcomes: dict[int, str]) -> tuple[Path, Path]:
    decisions = tmp_path / "decisions"
    decisions.mkdir()
    (decisions / "outcomes").mkdir()
    for number, text in records.items():
        (decisions / f"{number:04d}-a-decision.md").write_text(text, encoding="utf-8")
    for number, text in outcomes.items():
        (decisions / "outcomes" / f"{number:04d}.md").write_text(text, encoding="utf-8")
    return decisions, decisions / "outcomes"


def _messages(problems) -> str:
    return "\n".join(p.message for p in problems)


class TestTheLedgerTellsThemApart:
    def test_an_accepted_decision_with_no_outcome_is_a_problem(self, tmp_path):
        decisions, outs = _tree(tmp_path, {1: RECORD.format(n=1, status="accepted")}, {})
        problems = adr.outcome_problems(decisions, outs)
        assert problems, "an accepted decision with no outcome record must be refused"
        assert "outcome" in _messages(problems).lower()

    def test_the_same_decision_with_an_outcome_is_clean(self, tmp_path):
        decisions, outs = _tree(
            tmp_path,
            {1: RECORD.format(n=1, status="accepted")},
            {1: OBSERVED.format(n=1)},
        )
        assert adr.outcome_problems(decisions, outs) == []

    def test_a_proposed_decision_is_not_yet_owed_an_outcome(self, tmp_path):
        # Nothing has happened yet, so demanding what happened would manufacture
        # a placeholder — which is the failure mode this whole mechanism is for.
        decisions, outs = _tree(tmp_path, {1: RECORD.format(n=1, status="proposed")}, {})
        assert adr.outcome_problems(decisions, outs) == []

    def test_a_superseded_decision_still_owes_one(self, tmp_path):
        # A reversal is the single most informative outcome there is.
        decisions, outs = _tree(
            tmp_path,
            {1: RECORD.format(n=1, status="superseded by 0002"), 2: RECORD.format(n=2, status="accepted")},
            {2: OBSERVED.format(n=2)},
        )
        assert any("0001" in p.message for p in adr.outcome_problems(decisions, outs))

    def test_an_outcome_for_a_decision_that_does_not_exist_is_refused(self, tmp_path):
        decisions, outs = _tree(
            tmp_path,
            {1: RECORD.format(n=1, status="accepted")},
            {1: OBSERVED.format(n=1), 7: OBSERVED.format(n=7)},
        )
        assert any("0007" in p.message for p in adr.outcome_problems(decisions, outs))

    @pytest.mark.parametrize("section", REQUIRED)
    def test_an_empty_required_section_is_refused(self, tmp_path, section):
        """A heading with nothing under it is what a template leaves behind."""
        gutted = re.sub(
            rf"(?ms)^## {re.escape(section)}\n.*?(?=^## |\Z)",
            f"## {section}\n\n",
            OBSERVED.format(n=1),
        )
        assert f"## {section}" in gutted and gutted != OBSERVED.format(n=1), "the fixture did not gut anything"
        decisions, outs = _tree(tmp_path, {1: RECORD.format(n=1, status="accepted")}, {1: gutted})
        problems = adr.outcome_problems(decisions, outs)
        assert any(section.lower() in p.message.lower() for p in problems), f"an empty `## {section}` must be refused"


class TestTheSectionsAreTheConstitutionS:
    def test_the_gate_requires_exactly_chapter_nines_fields(self):
        assert tuple(adr.OUTCOME_SECTIONS) == REQUIRED


class TestPendingIsNotObserved:
    def test_a_pending_outcome_satisfies_the_structure_but_is_not_counted_as_observed(self, tmp_path):
        future = (dt.date.today() + dt.timedelta(days=90)).isoformat()
        decisions, outs = _tree(
            tmp_path,
            {1: RECORD.format(n=1, status="accepted"), 2: RECORD.format(n=2, status="accepted")},
            {1: OBSERVED.format(n=1), 2: PENDING.format(n=2, review=future)},
        )
        assert adr.outcome_problems(decisions, outs, today=dt.date.today()) == []
        found = adr.outcomes(outs)
        assert [o.number for o in found if o.status == "observed"] == [1]
        assert [o.number for o in found if o.status == "pending"] == [2]

    def test_a_pending_outcome_with_no_review_date_is_refused(self, tmp_path):
        undated = PENDING.format(n=1, review="2026-12-01").replace("- Review by: 2026-12-01\n", "")
        decisions, outs = _tree(tmp_path, {1: RECORD.format(n=1, status="accepted")}, {1: undated})
        assert any("review" in p.message.lower() for p in adr.outcome_problems(decisions, outs))

    def test_an_overdue_review_fails(self, tmp_path):
        """The obligation has to come due, or nothing ever returns to look."""
        past = (dt.date.today() - dt.timedelta(days=1)).isoformat()
        decisions, outs = _tree(
            tmp_path,
            {1: RECORD.format(n=1, status="accepted")},
            {1: PENDING.format(n=1, review=past)},
        )
        problems = adr.outcome_problems(decisions, outs, today=dt.date.today())
        assert any("overdue" in p.message.lower() for p in problems), (
            "a pending review whose date has passed must fail the gate"
        )

    def test_the_same_file_one_day_earlier_is_clean(self, tmp_path):
        """Positive control: the failure above is the date, not the file."""
        today = dt.date.today()
        decisions, outs = _tree(
            tmp_path,
            {1: RECORD.format(n=1, status="accepted")},
            {1: PENDING.format(n=1, review=(today - dt.timedelta(days=1)).isoformat())},
        )
        assert adr.outcome_problems(decisions, outs, today=today - dt.timedelta(days=2)) == []


class TestImmutabilityIsUnchanged:
    """The ledger must not be bought by making decision records mutable."""

    def test_an_edited_accepted_record_is_still_refused(self, tmp_path):
        repo = tmp_path / "repo"
        (repo / "docs" / "decisions" / "outcomes").mkdir(parents=True)
        decisions = repo / "docs" / "decisions"
        (decisions / "0001-a-decision.md").write_text(RECORD.format(n=1, status="accepted"), encoding="utf-8")

        def git(*args):
            subprocess.run(  # nosec B603 B607 — fixed args, throwaway repo
                ["git", *args], cwd=str(repo), check=True, capture_output=True
            )

        git("init", "-q")
        git("config", "user.email", "t@example.com")
        git("config", "user.name", "t")
        git("add", "-A")
        git("commit", "-qm", "record")

        # Pointing adr.ROOT at the throwaway repo is how immutability_problems
        # finds the history; it shells out to `git -C ROOT show`.
        original_root = adr.ROOT
        try:
            adr.ROOT = repo
            assert adr.immutability_problems(decisions) == []
            (decisions / "0001-a-decision.md").write_text(
                RECORD.format(n=1, status="accepted").replace("A.\n", "B.\n"), encoding="utf-8"
            )
            problems = adr.immutability_problems(decisions)
            assert problems, "editing an accepted record must still be refused"
            assert "supersede" in _messages(problems).lower()
        finally:
            adr.ROOT = original_root

    def test_outcome_files_are_deliberately_mutable(self, tmp_path):
        """They are the artefact you come back and write in. Being edited is the point."""
        decisions, outs = _tree(
            tmp_path,
            {1: RECORD.format(n=1, status="accepted")},
            {1: OBSERVED.format(n=1)},
        )
        # An outcome is not a decision record: it must not be picked up by the
        # registry's own validation, or a rewrite would read as tampering and
        # `0001.md` would read as a numbering violation.
        assert [r.number for r in adr.records(decisions)] == [1]
        assert adr.validate_directory(decisions) == []


class TestTheRealRepository:
    def test_the_gate_asks_for_both_missing_fields(self):
        gate = (ROOT / "scripts" / "adr.py").read_text(encoding="utf-8")
        for field in ("Actual outcome", "Lessons"):
            assert field in gate, f"adr.py must require `{field}`, or the ledger is voluntary"

    def test_every_decision_this_repository_has_accepted_carries_an_outcome(self):
        problems = adr.outcome_problems()
        assert problems == [], _messages(problems)

    def test_the_ledger_is_mostly_observed_rather_than_mostly_pending(self):
        found = adr.outcomes()
        observed = [o for o in found if o.status == "observed"]
        assert found, "no outcome records at all"
        assert len(observed) > len(found) - len(observed), (
            f"only {len(observed)} of {len(found)} outcomes are observed — a ledger of placeholders "
            "is the same minute the registry already was"
        )

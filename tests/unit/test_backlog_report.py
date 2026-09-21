# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""The backlog report — Group 3 Chapter 11.

One command answering "what is left to build or fix" from measured sources. The
properties worth pinning are not the numbers, which change every phase, but the
report's honesty: that it separates measured from told, that a source it cannot
read is reported absent rather than as zero, and that it parses the right table.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.backlog_report import (
    Section,
    _group4_invariants,
    _group4_preservation,
    _group4_verifiers,
    _ranked_gaps,
    build,
    render,
)

pytestmark = [pytest.mark.unit]

SPECS = Path(__file__).resolve().parent.parent.parent / "docs" / "ai" / "specs"


class TestItSeparatesMeasuredFromTold:
    def test_every_section_declares_which_it_is(self) -> None:
        # A ranked list written in prose is an intention. A registry count is a
        # fact. Presenting them identically invites a reader to trust the first
        # as much as the second.
        for s in build():
            assert "[MEASURED" in s.title or "[TOLD" in s.title, s.title

    def test_the_capability_and_document_sections_are_measured(self) -> None:
        titles = [s.title for s in build()]
        assert any("capabilities not yet live" in t and "MEASURED" in t for t in titles)
        assert any("Documentation debt" in t and "MEASURED" in t for t in titles)

    def test_the_ranked_gap_lists_are_labelled_told(self) -> None:
        assert all("TOLD" in s.title for s in build() if "gaps" in s.title)


class TestAnUnreadableSourceIsAbsentNotZero:
    def test_a_missing_document_reports_unmeasured(self, tmp_path: Path) -> None:
        # Rule 2. A report that renders a missing measurement as 0 is worse than
        # one that omits the line, because zero looks like success.
        s = _ranked_gaps(tmp_path / "nope.md", "X")
        assert "unmeasured" in s.note
        assert s.lines == []

    def test_a_document_without_a_gap_list_reports_unmeasured(self, tmp_path: Path) -> None:
        doc = tmp_path / "d.md"
        doc.write_text("# Title\n\nNo gap list here.\n", encoding="utf-8")
        s = _ranked_gaps(doc, "X")
        assert "unmeasured" in s.note


class TestItParsesTheRightTable:
    def test_it_ignores_a_numbered_table_that_is_not_the_gap_list(self, tmp_path: Path) -> None:
        # The first version matched the disaster-recovery tier table, whose rows
        # also begin `| 1 |`, and reported "Pod/node loss" as an outstanding gap.
        doc = tmp_path / "d.md"
        doc.write_text(
            "## Recovery\n\n"
            "| 1 | Pod loss | < 1 min | AVAILABLE |\n\n"
            "### The prioritised gap list\n\n"
            "| # | Gap | Chapter | Priority |\n"
            "|---|---|---|---|\n"
            "| 1 | A real gap | 9 | **Critical** |\n",
            encoding="utf-8",
        )
        s = _ranked_gaps(doc, "X")
        assert len(s.lines) == 1
        assert "A real gap" in s.lines[0]
        assert "Pod loss" not in "".join(s.lines)

    def test_it_stops_at_the_next_heading(self, tmp_path: Path) -> None:
        doc = tmp_path / "d.md"
        doc.write_text(
            "### The prioritised gap list\n\n"
            "| 1 | Inside | 9 | **Critical** |\n\n"
            "## Appendix\n\n"
            "| 2 | Outside | 9 | **High** |\n",
            encoding="utf-8",
        )
        s = _ranked_gaps(doc, "X")
        assert len(s.lines) == 1 and "Inside" in s.lines[0]

    def test_the_real_specifications_still_parse(self) -> None:
        # The positive control. The two tests above would pass against a parser
        # that found nothing at all.
        for name in (
            "GROUP2_platform_engineering_operations_governance.md",
            "GROUP3_documentation_knowledge_architecture_governance.md",
        ):
            s = _ranked_gaps(SPECS / name, "X")
            assert len(s.lines) >= 5, f"{name} produced {len(s.lines)} rows"


class TestTheRenderedReport:
    def test_it_names_every_section_and_ends_with_the_re_run_instruction(self) -> None:
        text = render(build())
        assert "WHAT IS LEFT TO BUILD OR FIX" in text
        # The whole point: a copy of this output goes stale, the command does not.
        assert "Re-run rather than trusting a copy" in text

    def test_a_section_note_is_rendered_rather_than_swallowed(self) -> None:
        text = render([Section("T  [MEASURED]", note="unmeasured — because")])
        assert "unmeasured — because" in text


class TestGroupFourReachesTheReport:
    """Option B put Group 4's Volume I above every group as the constitution.

    A constitutional layer nobody can see in the one place the owner looks is a
    document, not a constitution — so it has to reach the generated answer.
    """

    def test_group_4_has_a_section(self) -> None:
        assert any("Group 4" in s.title for s in build())

    def test_the_invariant_statuses_are_labelled_told(self) -> None:
        # The status column is the constitution's own prose. Measured is the
        # verifier resolution below, not this.
        titles = [s.title for s in build() if "Group 4" in s.title and "invariants" in s.title]
        assert titles and all("TOLD" in t for t in titles)

    def test_the_verifier_resolution_is_labelled_measured(self) -> None:
        titles = [s.title for s in build() if "Group 4" in s.title and "verifier" in s.title]
        assert titles and all("MEASURED" in t for t in titles)


class TestTheConstitutionsInvariantStatuses:
    def test_only_the_unfinished_invariants_are_listed(self, tmp_path: Path) -> None:
        doc = tmp_path / "c.md"
        doc.write_text(
            "| ID | Invariant | Status | Evidence |\n"
            "|---|---|---|---|\n"
            "| INV-01 | Done thing | **AVAILABLE** | here |\n"
            "| INV-02 | Half a thing | PARTIAL | there |\n"
            "| INV-03 | No thing | **NEW** | nowhere |\n",
            encoding="utf-8",
        )
        s = _group4_invariants(doc)
        body = "\n".join(s.lines)
        assert "INV-02" in body and "INV-03" in body
        assert "INV-01" not in body

    def test_a_missing_constitution_reports_unmeasured(self, tmp_path: Path) -> None:
        s = _group4_invariants(tmp_path / "nope.md")
        assert "unmeasured" in s.note and s.lines == []

    def test_the_real_constitution_still_parses(self) -> None:
        # Positive control. The two tests above pass against a parser that finds
        # nothing at all in the real document.
        s = _group4_invariants(SPECS / "GROUP4_CONSTITUTION.md")
        assert len(s.lines) >= 10, f"parsed {len(s.lines)} rows"


class TestTheVerifiersTheConstitutionNames:
    """Rule 4: evidence that resolves is not evidence that runs — but evidence
    that does *not* resolve is a document naming a symbol the code has renamed
    or deleted, which is the drift this section exists to catch."""

    def test_every_verifier_named_by_the_real_constitution_resolves(self) -> None:
        s = _group4_verifiers(SPECS / "GROUP4_CONSTITUTION.md")
        assert not s.note, s.note
        unresolved = [ln for ln in s.lines if "MISSING" in ln]
        assert unresolved == [], "\n".join(unresolved)

    def test_it_still_examined_something(self) -> None:
        # A checker that read nothing reports a clean result. This is the guard
        # against that: the real document names verifiers, and the count says so.
        s = _group4_verifiers(SPECS / "GROUP4_CONSTITUTION.md")
        assert "12 named" in s.lines[0] or "named" in s.lines[0]
        assert s.lines[0].split()[0].isdigit() and int(s.lines[0].split()[0]) >= 10

    def test_a_verifier_the_code_does_not_have_is_flagged(self, tmp_path: Path) -> None:
        # Defect injection. Rename a predicate in the document and the section
        # must say so rather than pass quietly.
        doc = tmp_path / "c.md"
        doc.write_text(
            "Enforced by `verify_no_self_replication` and `verify_a_thing_that_never_existed`.\n",
            encoding="utf-8",
        )
        s = _group4_verifiers(doc)
        body = "\n".join(s.lines)
        assert "verify_a_thing_that_never_existed" in body and "MISSING" in body
        assert "verify_no_self_replication" not in body

    def test_a_missing_constitution_reports_unmeasured(self, tmp_path: Path) -> None:
        s = _group4_verifiers(tmp_path / "nope.md")
        assert "unmeasured" in s.note and s.lines == []


class TestACompletedGapIsCountedNotSilentlyDropped:
    """Group 3 strikes finished rows through — `| ~~1~~ | ~~Done thing~~ |`.

    The parser drops them, which is right: they are not outstanding. But a
    reader seeing a list that starts at 5 cannot tell "four are done" from
    "the parser lost four rows", and those two readings lead somewhere very
    different. So the count is stated.
    """

    def test_struck_through_rows_are_reported_as_done(self, tmp_path: Path) -> None:
        doc = tmp_path / "d.md"
        doc.write_text(
            "### The prioritised gap list\n\n"
            "| ~~1~~ | ~~Finished~~ | 2 | **DONE** | shipped |\n"
            "| ~~2~~ | ~~Also finished~~ | 3 | **DONE** | shipped |\n"
            "| 3 | Still open | 4 | **High** | not yet |\n",
            encoding="utf-8",
        )
        s = _ranked_gaps(doc, "X")
        joined = "\n".join(s.lines)
        assert "2 already done" in joined
        assert "Still open" in joined
        assert "Finished" not in joined

    def test_a_list_with_nothing_done_says_nothing_about_done(self, tmp_path: Path) -> None:
        doc = tmp_path / "d.md"
        doc.write_text(
            "### The prioritised gap list\n\n| 1 | Open | 4 | **High** | x |\n",
            encoding="utf-8",
        )
        assert not any("already done" in ln for ln in _ranked_gaps(doc, "X").lines)

    def test_the_real_group_3_list_reports_its_completed_rows(self) -> None:
        s = _ranked_gaps(SPECS / "GROUP3_documentation_knowledge_architecture_governance.md", "X")
        assert any("already done" in ln for ln in s.lines), "\n".join(s.lines[:3])


class TestThePreservationRuleReachesTheReport:
    """The source's own opening rule — never silently remove — is the one
    obligation that spans every group. If it is broken, that outranks every
    ranked gap in the report, so it appears there."""

    def test_it_is_measured_not_told(self) -> None:
        titles = [s.title for s in build() if "preservation" in s.title.lower()]
        assert titles and all("MEASURED" in t for t in titles)

    def test_it_reports_both_sources_and_no_omissions(self) -> None:
        s = _group4_preservation()
        assert not s.note, s.note
        assert "304 source titles" in s.lines[0] or "source titles" in s.lines[0]
        assert not any("MISSING" in ln for ln in s.lines), "\n".join(s.lines)

    def test_a_broken_checker_is_reported_unmeasured_not_clean(self, tmp_path: Path) -> None:
        # Rule 3 again. If the corpus cannot be read the line must say so; a
        # silent "0 missing" from a checker that read nothing is the worst of
        # the three possible outputs.
        s = _group4_preservation(corpus_dir=tmp_path)
        assert "unmeasured" in s.note and s.lines == []

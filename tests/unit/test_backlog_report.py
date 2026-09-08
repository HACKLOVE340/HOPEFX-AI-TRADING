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

from scripts.backlog_report import Section, _ranked_gaps, build, render

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

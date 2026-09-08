# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""Nothing from either Group 4 source may go missing.

The source document opens with one rule: **ADD AND EXPAND; NEVER SILENTLY
REMOVE.** Two sources now exist — the 186-chapter table of contents (v1) and the
complete Volumes I–XX document (v2) — and they do not enumerate the same things.
v2 has 117 substantive sections where v1 had 186 numbered chapters, so adopting
either one alone drops titles the other names.

A rule enforced by intention is not enforced. This is the mechanical version: every
title from both sources must still appear in the repository's Group 4 documents.
It is the same anti-omission role the capability registry plays for Group 0.
"""

from __future__ import annotations

import pytest

from scripts.group4_preservation import (
    PreservationBroken,
    check,
    v1_chapters,
    v2_sections,
)

pytestmark = [pytest.mark.unit]


class TestBothSourcesAreActuallyRead:
    """Rule 1. A checker that parsed nothing reports everything preserved."""

    def test_v1_yields_its_186_chapters(self) -> None:
        chapters = v1_chapters()
        assert len(chapters) == 186, f"parsed {len(chapters)}"

    def test_v2_yields_its_substantive_sections(self) -> None:
        sections = v2_sections()
        assert len(sections) >= 110, f"parsed {len(sections)}"

    def test_v2_does_not_return_the_repeated_boilerplate(self) -> None:
        # "Mandatory Engineering Requirements" is stamped 111 times and
        # "Implementation Backlog Preservation" 20 times. Counting those as
        # preserved content would inflate the total and hide a real omission.
        titles = [s.title for s in v2_sections()]
        assert titles.count("Implementation Backlog Preservation") <= 1
        assert "Mandatory Engineering Requirements" not in titles

    def test_no_section_title_is_empty(self) -> None:
        assert all(s.title.strip() for s in v2_sections())


class TestEveryTitleIsStillAccountedFor:
    def test_the_repository_preserves_every_source_title(self) -> None:
        report = check()
        assert report.missing == [], "\n".join(f"{m.source} · {m.volume} · {m.title}" for m in report.missing)

    def test_the_check_examined_a_real_corpus(self) -> None:
        # The positive control for the assertion above: it passes trivially if
        # `check()` looked at no documents or no titles.
        report = check()
        assert report.documents_read >= 2, report.documents_read
        assert report.titles_checked >= 290, report.titles_checked


class TestTheCheckerRefusesRatherThanReportingClean:
    def test_a_missing_source_raises_instead_of_passing(self, tmp_path) -> None:
        # Rule 3: fail closed. A source file that cannot be read must not be
        # reported as "nothing missing" — that is a clean bill of health issued
        # by a checker that read nothing.
        with pytest.raises(PreservationBroken):
            check(sources=[tmp_path / "absent.txt"])

    def test_a_corpus_with_no_documents_raises(self, tmp_path) -> None:
        with pytest.raises(PreservationBroken):
            check(corpus_dir=tmp_path)

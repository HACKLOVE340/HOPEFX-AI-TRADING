# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""The master specifications must read in the order they are numbered.

Group 2's Part VIII (Acceleration, absorbed from Group 4 Volume VIII under Option
B) was first appended between Chapter 25 and Chapter 26, so the document ran
25 → 29…35 → 26 → 27 → 28. Nothing failed. Every gate was green: ruff does not
read markdown, the registry checks paths, and the freshness checker follows
links. A reader was the only control, and readers skim.

So the ordering becomes a checked property. It is cheap, and the failure it
catches is exactly the one already made.
"""

from __future__ import annotations

import re
from itertools import pairwise
from pathlib import Path

import pytest

pytestmark = [pytest.mark.unit]

SPECS = Path(__file__).resolve().parent.parent.parent / "docs" / "ai" / "specs"

#: Chapter headings are `## Chapter 7 — Title`; Parts are `# PART VII — Title`.
_CHAPTER = re.compile(r"^#{2,3} Chapter (\d+) — ", re.M)
_PART = re.compile(r"^# PART ([IVX]+) — ", re.M)

_ROMAN = {"I": 1, "V": 5, "X": 10}


def _roman(value: str) -> int:
    total = 0
    for i, ch in enumerate(value):
        n = _ROMAN[ch]
        total += -n if i + 1 < len(value) and _ROMAN[value[i + 1]] > n else n
    return total


_NUMBERED_SPECS = [
    "GROUP2_platform_engineering_operations_governance.md",
    "GROUP3_documentation_knowledge_architecture_governance.md",
    # Added after the same defect recurred here: the complete v2 source added six
    # chapters, the two that already existed were renumbered to make room, and
    # the document silently ran 1-5, 8-13 with 6 and 7 vacant — while other
    # documents went on citing "Group 4 Ch 6".
    "GROUP4_CONSTITUTION.md",
]


@pytest.mark.parametrize("name", _NUMBERED_SPECS)
class TestChaptersAppearInNumericalOrder:
    def test_chapter_numbers_only_increase(self, name: str) -> None:
        text = (SPECS / name).read_text(encoding="utf-8")
        numbers = [int(m.group(1)) for m in _CHAPTER.finditer(text)]
        assert numbers, f"{name}: no chapter headings found — the parser read nothing"
        out_of_order = [(a, b) for a, b in pairwise(numbers) if b <= a]
        assert out_of_order == [], f"{name}: chapter {out_of_order}"

    def test_no_chapter_number_is_used_twice(self, name: str) -> None:
        text = (SPECS / name).read_text(encoding="utf-8")
        numbers = [int(m.group(1)) for m in _CHAPTER.finditer(text)]
        duplicates = sorted({n for n in numbers if numbers.count(n) > 1})
        assert duplicates == [], f"{name}: chapters {duplicates} appear more than once"

    def test_there_are_no_gaps_in_the_numbering(self, name: str) -> None:
        # A missing chapter number is a chapter someone deleted or a renumbering
        # that stopped halfway. Either way the reader is left hunting for it.
        text = (SPECS / name).read_text(encoding="utf-8")
        numbers = [int(m.group(1)) for m in _CHAPTER.finditer(text)]
        expected = list(range(numbers[0], numbers[-1] + 1))
        assert numbers == expected, f"{name}: missing {sorted(set(expected) - set(numbers))}"


class TestPartsAppearInNumericalOrder:
    def test_group_2_parts_only_increase(self) -> None:
        text = (SPECS / _NUMBERED_SPECS[0]).read_text(encoding="utf-8")
        parts = [_roman(m.group(1)) for m in _PART.finditer(text)]
        assert len(parts) >= 8, f"only {len(parts)} Parts found — the parser read almost nothing"
        assert parts == sorted(parts), f"Parts out of order: {parts}"
        assert parts == list(range(1, len(parts) + 1)), f"Parts are not contiguous: {parts}"


class TestTheRomanParserItself:
    """The ordering check is only as good as the numeral parser under it. A
    parser that returned a constant would make every Part list look sorted."""

    @pytest.mark.parametrize(
        ("numeral", "value"),
        [("I", 1), ("II", 2), ("IV", 4), ("V", 5), ("VI", 6), ("VIII", 8), ("IX", 9), ("X", 10)],
    )
    def test_it_reads_the_numerals_this_document_uses(self, numeral: str, value: int) -> None:
        assert _roman(numeral) == value

# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""The generated API reference says what each endpoint DOES — Phase API-1.

Five documents claimed to describe this API. `docs/API_ENDPOINTS.md` is the one
that cannot drift, because it is generated from the routers the application
mounts, and it was therefore made canonical over a hand-written reference that
covered 18% of the surface: a reference where four lookups in five fail, and
where a reader cannot tell a missing endpoint from an undocumented one.

But its Summary column was empty for all 1,127 routes, because only
``route.summary`` was read and only 337 routes set it. Another 809 carry an
endpoint docstring. Three quarters of the API could say what it does and said
nothing.
"""

from __future__ import annotations

import pytest

from scripts.api_documentation_generator import _one_line, _SUMMARY_MAX_CHARS, _summary_for

pytestmark = [pytest.mark.unit]


class _Route:
    def __init__(self, summary: str | None = None, doc: str | None = None) -> None:
        self.summary = summary

        def endpoint() -> None:
            pass

        endpoint.__doc__ = doc
        self.endpoint = endpoint


class TestWhereTheSummaryComesFrom:
    def test_an_explicit_summary_wins(self) -> None:
        # A decision somebody made about how this endpoint should be described
        # beats what was written for the next programmer.
        assert _summary_for(_Route(summary="Cancel an order.", doc="Internal notes.")) == "Cancel an order."

    def test_a_docstring_is_used_when_there_is_no_summary(self) -> None:
        # The 809 routes the first version ignored.
        assert _summary_for(_Route(doc="List the open positions.")) == "List the open positions."

    def test_only_the_first_line_of_a_docstring_is_used(self) -> None:
        route = _Route(doc="Close a position.\n\nRaises ValueError when the id is unknown.\n")
        assert _summary_for(route) == "Close a position."

    def test_a_route_with_neither_stays_empty(self) -> None:
        # An invented summary is worse than a blank one. A blank cell reads as
        # "nobody wrote this down"; a function name dressed up as prose reads as
        # documentation.
        assert _summary_for(_Route()) == ""

    def test_whitespace_only_sources_count_as_absent(self) -> None:
        assert _summary_for(_Route(summary="   ", doc="  \n ")) == ""


class TestItCannotBreakTheTableItRendersInto:
    def test_a_pipe_is_escaped(self) -> None:
        # An unescaped pipe silently splits the row and shifts every later column.
        assert "\\|" in _one_line("Filter by a|b")

    def test_newlines_are_flattened(self) -> None:
        assert "\n" not in _one_line("One\nTwo\nThree")
        assert _one_line("One\nTwo") == "One Two"

    def test_a_long_summary_is_truncated_visibly(self) -> None:
        out = _one_line("x" * 400)
        assert len(out) <= _SUMMARY_MAX_CHARS
        # Ellipsis, so a reader knows it was cut rather than that the endpoint
        # has a strange name.
        assert out.endswith("…")

    def test_a_short_summary_is_untouched(self) -> None:
        assert _one_line("Fetch the balance.") == "Fetch the balance."


class TestTheGeneratedDocument:
    def test_most_endpoints_now_carry_a_summary(self) -> None:
        # The measurable outcome: 0 before, 859 of 1,137 after. The floor is set
        # well below the measurement so an endpoint losing its docstring does not
        # fail the build, but a regression to the empty column does.
        from pathlib import Path

        doc = Path(__file__).resolve().parent.parent.parent / "docs" / "API_ENDPOINTS.md"
        rows = [line for line in doc.read_text(encoding="utf-8").splitlines() if line.startswith("| `")]
        assert len(rows) > 1000, f"only {len(rows)} endpoint rows"
        filled = [r for r in rows if r.split("|")[4].strip()]
        assert len(filled) > 700, f"only {len(filled)} of {len(rows)} rows carry a summary"

    def test_the_stale_fork_is_gone(self) -> None:
        # docs/api.md was a fork of this generated file predating the generator:
        # 580 unique lines, 4 in common. Two documents with the same title and
        # different content is the conflict the consolidation removed.
        from pathlib import Path

        assert not (Path(__file__).resolve().parent.parent.parent / "docs" / "api.md").exists()

    def test_the_curated_reference_declares_its_coverage(self) -> None:
        # Preserved, not deleted — its worked examples are the thing the
        # generated list does not have. But a reader landing on it must know it
        # is a subset, or they conclude a missing endpoint does not exist.
        from pathlib import Path

        ref = (Path(__file__).resolve().parent.parent.parent / "docs" / "API_REFERENCE.md").read_text(encoding="utf-8")
        # Matching on 'complete list' rather than the whole sentence: the
        # document writes '**not** the complete list' in markdown bold, and the
        # first version of this assertion looked for the unbolded string and
        # failed against a document that says exactly what it should.
        assert "complete list" in ref
        assert "API_ENDPOINTS.md" in ref

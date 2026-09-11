# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""Numbers written into a document must still match what the code measures.

The owner's standing rule is that documentation ships with every push. The
failure mode that rule is guarding against is not a missing file — it is a
document that still *looks* current while carrying a number that stopped being
true three commits ago.

`docs_freshness.py` catches a path that no longer exists and a claim the tree
contradicts. It does not check arithmetic. So "22 gates · 12 proven" stays in a
document forever after the ledger moves on, and a reader — human or agent — acts
on a figure nobody re-measured.

This closes that. Each claim shape below is tied to the script that measures it,
and a mismatch blocks rather than accumulating.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.doc_metrics import (
    CLAIMS,
    MetricsBroken,
    check,
    measure,
    scan,
)

pytestmark = [pytest.mark.unit]

REPO = Path(__file__).resolve().parents[2]


def _bump(shape: str, metric: str) -> str:
    r"""Make `shape` state a WRONG value for `metric`.

    Uses the claim's own pattern to find the number it captures, rather than
    assuming it is the first number in the line. Neighbour-anchored patterns
    (`covered · (\d+) partial`) capture the second, and a helper that bumped the
    first produced a line that was still correct — a test that failed while the
    code was right.
    """
    claim = next(c for c in CLAIMS if c.metric == metric)
    match = claim.pattern.search(shape)
    assert match, f"{shape!r} does not match the {metric} pattern at all"
    wrong = str(measure()[metric] + 7)
    return shape[: match.start(1)] + wrong + shape[match.end(1) :]


class TestTheMeasurementsAreReal:
    """Every claim is only as good as the number it is compared against."""

    def test_every_claim_resolves_to_a_measurement(self) -> None:
        measured = measure()
        for claim in CLAIMS:
            assert claim.metric in measured, f"{claim.metric} has no measurement"

    def test_no_measurement_is_none(self) -> None:
        # Rule 2. A metric that could not be read must refuse, not report zero —
        # zero would silently "match" a document claiming zero.
        for name, value in measure().items():
            assert value is not None, f"{name} measured as None"

    def test_the_measurements_are_plausible(self) -> None:
        m = measure()
        assert m["gates_total"] >= 18, m["gates_total"]
        assert m["gates_proven"] + m["gates_unproven"] == m["gates_total"]
        assert m["source_titles"] >= 290, m["source_titles"]
        assert m["documents_registered"] >= 190, m["documents_registered"]


class TestItActuallyReadsTheDocuments:
    def test_the_scan_finds_claims_in_the_real_documents(self) -> None:
        # The positive control: every assertion below passes against a scanner
        # that found nothing at all.
        found = scan()
        assert len(found) >= 4, f"only {len(found)} claims found — the scanner read almost nothing"

    def test_every_found_claim_names_its_file_and_line(self) -> None:
        for hit in scan():
            assert hit.path.exists(), hit.path
            assert hit.line > 0
            assert hit.stated >= 0


class TestTheRepositoryIsCurrent:
    def test_no_document_states_a_stale_number(self) -> None:
        report = check()
        assert not report.drift, "\n".join(
            f"{d.path.relative_to(REPO)}:{d.line} states {d.metric}={d.stated}, measured {d.measured}"
            for d in report.drift
        )


class TestTheCheckCanActuallyFail:
    """Rule 1. A drift checker that never reports drift is decoration."""

    def test_a_wrong_number_is_reported(self, tmp_path: Path) -> None:
        doc = tmp_path / "STALE.md"
        doc.write_text("The ledger holds 999 gates, most of them proven.\n", encoding="utf-8")
        report = check(extra_documents=[doc])
        assert any(d.path == doc and d.stated == 999 for d in report.drift), report.drift

    def test_a_correct_number_is_not_reported(self, tmp_path: Path) -> None:
        measured = measure()["gates_total"]
        doc = tmp_path / "FRESH.md"
        doc.write_text(f"The ledger holds {measured} gates, all listed.\n", encoding="utf-8")
        assert not [d for d in check(extra_documents=[doc]).drift if d.path == doc]

    @pytest.mark.parametrize("shape", ["23 gates · 15 proven", "23 gates, 15 proven", "23 gates discovered"])
    def test_the_total_shapes_documents_actually_use_are_matched(self, tmp_path: Path, shape: str) -> None:
        # The positive control for the narrowing below: tightening the pattern
        # must not stop it matching the shapes real documents write.
        measured = measure()["gates_total"]
        doc = tmp_path / "SHAPE.md"
        doc.write_text(shape.replace("23", str(measured + 1)) + "\n", encoding="utf-8")
        assert [d for d in check(extra_documents=[doc]).drift if d.metric == "gates_total"], shape


class TestACountOfWhatRemainsIsNotATotal:
    r"""`(\d+)\s+gates` also matched "8 gates left" — a true sentence the checker
    called drift. A check that forces awkward prose gets worked around, so the
    pattern narrowed rather than the writing. This pins that."""

    @pytest.mark.parametrize(
        "sentence",
        [
            "Finish the ratchet — 8 gates left.",
            "There are 8 gates still unproven in the ledger",
            "roughly 4 gates per phase at the current rate",
        ],
    )
    def test_a_remaining_count_is_not_read_as_a_total(self, tmp_path: Path, sentence: str) -> None:
        doc = tmp_path / "PROSE.md"
        doc.write_text(sentence + "\n", encoding="utf-8")
        # Scoped to this fixture. Filtering on the metric alone made these three
        # go red for any stale figure anywhere in docs/ — a true finding, but
        # reported under a name that says the opposite of what happened.
        drift = [d for d in check(extra_documents=[doc]).drift if d.path == doc and d.metric == "gates_total"]
        assert not drift, f"{sentence!r} was read as a total: {drift}"


class TestItRefusesRatherThanReportingClean:
    def test_an_unmeasurable_repository_raises(self, tmp_path: Path) -> None:
        with pytest.raises(MetricsBroken):
            check(repo=tmp_path)


class TestTheAOSConformanceFiguresAreRatcheted:
    """`docs/ai/specs/AOS_INVARIANT_REGISTER.toml` maps the AOS specification's
    §30 onto this repository, and the three totals it produces — covered,
    partial, absent — are exactly the kind of figure a document states once and
    then carries forever. `scripts/aos_conformance.py` keeps the register from
    lying about predicates; this keeps the documents from lying about the
    register."""

    def test_the_aos_metrics_are_measured(self) -> None:
        m = measure()
        for name in ("aos_entries", "aos_covered", "aos_partial", "aos_absent"):
            assert name in m, f"{name} has no measurement"
        assert m["aos_covered"] + m["aos_partial"] + m["aos_absent"] == m["aos_entries"]

    @pytest.mark.parametrize(
        ("shape", "metric"),
        [
            ("26 AOS invariants", "aos_entries"),
            ("26 invariants · 2 covered", "aos_covered"),
            ("2 covered · 13 partial", "aos_partial"),
            ("13 partial · 11 absent", "aos_absent"),
        ],
    )
    def test_a_stale_aos_figure_is_reported(self, tmp_path: Path, shape: str, metric: str) -> None:
        doc = tmp_path / "AOS_SHAPE.md"
        doc.write_text(_bump(shape, metric) + "\n", encoding="utf-8")
        drift = [d for d in check(extra_documents=[doc]).drift if d.path == doc and d.metric == metric]
        assert drift, shape

    @pytest.mark.parametrize(
        "sentence",
        [
            "The owner was absent for the review.",
            "Coverage is partial in three modules.",
            "All 26 endpoints are covered by tests.",
            # The spatial register's own line. It carries "9 partial ·", which
            # the pre-2026-09-11 aos_partial pattern read as an AOS figure.
            "16 spatial capabilities · 1 built · 9 partial · 6 planned",
        ],
    )
    def test_ordinary_prose_is_not_read_as_an_aos_figure(self, tmp_path: Path, sentence: str) -> None:
        doc = tmp_path / "AOS_PROSE.md"
        doc.write_text(sentence + "\n", encoding="utf-8")
        drift = [d for d in check(extra_documents=[doc]).drift if d.metric.startswith("aos_")]
        assert not drift, f"{sentence!r} was read as an AOS figure: {drift}"


class TestTheSpatialFiguresAreRatchetedWithoutCryingWolf:
    """The spatial register's three figures, and the neighbouring registry's."""

    def test_the_spatial_metrics_are_measured(self) -> None:
        m = measure()
        for name in ("spatial_total", "spatial_built", "spatial_planned"):
            assert name in m, f"{name} has no measurement"
        assert m["spatial_built"] <= m["spatial_total"]

    @pytest.mark.parametrize(
        ("shape", "metric"),
        [
            ("16 spatial capabilities", "spatial_total"),
            ("16 capabilities · 1 built", "spatial_built"),
            ("9 partial · 6 planned", "spatial_planned"),
        ],
    )
    def test_a_stale_spatial_figure_is_reported(self, tmp_path: Path, shape: str, metric: str) -> None:
        doc = tmp_path / "SPATIAL_SHAPE.md"
        doc.write_text(_bump(shape, metric) + "\n", encoding="utf-8")
        drift = [d for d in check(extra_documents=[doc]).drift if d.path == doc and d.metric == metric]
        assert drift, shape

    @pytest.mark.parametrize(
        "sentence",
        [
            "233 rows · 233 live · 0 staged · 0 planned · 233/233 evidence resolves",
            "The migration is planned for next quarter.",
            "3 built, 2 bought.",
        ],
    )
    def test_the_capability_registrys_own_line_is_not_read_as_a_spatial_figure(
        self, tmp_path: Path, sentence: str
    ) -> None:
        """The AI Hub registry reports "0 planned ·" about 233 rows of its own.
        A looser pattern read that as the spatial planned count and called a true
        sentence drift."""
        doc = tmp_path / "OTHER.md"
        doc.write_text(sentence + "\n", encoding="utf-8")
        drift = [d for d in check(extra_documents=[doc]).drift if d.path == doc and d.metric.startswith("spatial_")]
        assert not drift, f"{sentence!r} was read as a spatial figure: {drift}"

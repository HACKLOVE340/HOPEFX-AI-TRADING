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
    def test_the_total_shapes_documents_actually_use_are_matched(
        self, tmp_path: Path, shape: str
    ) -> None:
        # The positive control for the narrowing below: tightening the pattern
        # must not stop it matching the shapes real documents write.
        measured = measure()["gates_total"]
        doc = tmp_path / "SHAPE.md"
        doc.write_text(shape.replace("23", str(measured + 1)) + "\n", encoding="utf-8")
        assert [d for d in check(extra_documents=[doc]).drift if d.metric == "gates_total"], shape


class TestACountOfWhatRemainsIsNotATotal:
    """`(\d+)\s+gates` also matched "8 gates left" — a true sentence the checker
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
        drift = [d for d in check(extra_documents=[doc]).drift if d.metric == "gates_total"]
        assert not drift, f"{sentence!r} was read as a total: {drift}"


class TestItRefusesRatherThanReportingClean:
    def test_an_unmeasurable_repository_raises(self, tmp_path: Path) -> None:
        with pytest.raises(MetricsBroken):
            check(repo=tmp_path)

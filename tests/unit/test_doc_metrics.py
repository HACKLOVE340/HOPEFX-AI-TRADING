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
        # `policed_drift`, not `drift`: `commits_ahead` / `files_ahead` change
        # on every commit and this module MAINTAINS them rather than policing
        # them (see TestSyncKeepsTheVolatileFiguresTrueWithoutNagging, and
        # TestTheVolatilePairIsMaintainedNotPoliced for why this assertion used
        # to be red through nobody's fault). Everything else still fails hard.
        report = check()
        assert not report.policed_drift, "\n".join(
            f"{d.path.relative_to(REPO)}:{d.line} states {d.metric}={d.stated}, measured {d.measured}"
            for d in report.policed_drift
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


class TestTheOwnerDecisionCountIsRatcheted:
    """MASTER_OUTSTANDING's summary said "Four of them" while §A carried
    seventeen. Nothing measured it, so nothing caught it, and a reader trusting
    the summary believed the owner's queue was a quarter of its real size — the
    same "figure describing a ratchet, going stale for want of a ratchet" shape
    the coverage_debt claim above was added for."""

    def test_the_count_is_measured_from_the_headings(self) -> None:
        import re
        from pathlib import Path as _Path

        from scripts.doc_metrics import REPO, measure

        measured = measure()["owner_decisions"]
        headings = re.findall(
            r"(?m)^###\s+A\d+\.",
            _Path(REPO, "docs/ai/MASTER_OUTSTANDING.md").read_text(encoding="utf-8"),
        )
        assert measured == len(headings) > 0

    def test_a_wrong_owner_count_is_reported(self, tmp_path: Path) -> None:
        from scripts.doc_metrics import measure

        wrong = measure()["owner_decisions"] + 1
        doc = tmp_path / "SUMMARY.md"
        doc.write_text(
            f"* **§A — Decisions only the owner can make.** {wrong} of them. Nothing moves.\n",
            encoding="utf-8",
        )
        drift = [d for d in check(extra_documents=[doc]).drift if d.metric == "owner_decisions"]
        assert drift, "a wrong owner-decision count was not reported"

    def test_the_right_owner_count_is_not_reported(self, tmp_path: Path) -> None:
        from scripts.doc_metrics import measure

        doc = tmp_path / "SUMMARY.md"
        doc.write_text(
            f"* **§A — Decisions only the owner can make.** {measure()['owner_decisions']} of them.\n",
            encoding="utf-8",
        )
        drift = [d for d in check(extra_documents=[doc]).drift if d.metric == "owner_decisions"]
        assert not drift

    @pytest.mark.parametrize(
        "sentence",
        [
            "There are 4 of them in the backlog.",
            "Decisions only the operator can make. 4 of them.",
            "5 of them are already done.",
        ],
    )
    def test_an_unrelated_count_is_not_read_as_the_owner_count(self, tmp_path: Path, sentence: str) -> None:
        """The pattern is anchored to §A's exact phrasing. A bare `(\\d+) of them`
        would match most of this repository's prose."""
        doc = tmp_path / "OTHER.md"
        doc.write_text(sentence + "\n", encoding="utf-8")
        drift = [d for d in check(extra_documents=[doc]).drift if d.metric == "owner_decisions"]
        assert not drift, f"{sentence!r} was read as the owner-decision count"


class TestTheBranchDistanceIsRatcheted:
    """`LANDING_PLAN.md` and `CLAUDE.md` both state how far this branch is from
    `main`. Neither figure was measured by anything, so both drifted: they read
    565 commits / 1,246 files while the branch was at 588 / 1,321. A contributor
    sizing the landing work from either document was reading a number that
    stopped being true 23 commits earlier — the same shape as the "Four of them"
    owner-decision count, and the reason that one is now measured too."""

    def test_this_checkout_can_actually_measure_the_distance(self) -> None:
        """The guard on every skip below.

        The other tests in this class skip when `origin/main` is absent, which
        is right for a shallow clone and useless here: without this, a
        measurement that was never wired would skip forever and read as green.
        This checkout has the ref, so this test must run.
        """
        import subprocess

        from scripts.doc_metrics import REPO, measure

        resolves = (
            subprocess.run(
                ["git", "rev-parse", "--verify", "--quiet", "origin/main"],
                cwd=REPO,
                capture_output=True,
                check=False,
            ).returncode
            == 0
        )
        if not resolves:
            pytest.skip("origin/main is genuinely absent from this checkout")

        missing = {"commits_ahead", "files_ahead", "commits_behind"} - set(measure())
        assert not missing, f"origin/main resolves but these are not measured: {sorted(missing)}"

    def test_the_distance_is_measured_from_git(self) -> None:
        import subprocess

        from scripts.doc_metrics import REPO, measure

        measured = measure()
        if "commits_ahead" not in measured:
            pytest.skip("origin/main is not available in this checkout")

        ahead = subprocess.run(
            ["git", "rev-list", "--count", "origin/main..HEAD"],
            cwd=REPO,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        assert measured["commits_ahead"] == int(ahead)
        assert measured["files_ahead"] > 0
        assert measured["commits_behind"] >= 0

    @pytest.mark.parametrize(
        ("metric", "sentence"),
        [
            ("commits_ahead", "is **{n} commits and 1,246 files ahead of `main`**"),
            ("files_ahead", "is **565 commits and {n} files ahead of `main`**"),
            ("commits_behind", "`git rev-list --count HEAD..origin/main` is **{n}**"),
        ],
    )
    def test_a_wrong_distance_is_reported(self, tmp_path: Path, metric: str, sentence: str) -> None:
        from scripts.doc_metrics import measure

        measured = measure()
        if metric not in measured:
            pytest.skip("origin/main is not available in this checkout")

        doc = tmp_path / "PLAN.md"
        doc.write_text(sentence.format(n=measured[metric] + 7) + "\n", encoding="utf-8")
        drift = [d for d in check(extra_documents=[doc]).drift if d.path == doc and d.metric == metric]
        assert drift, f"a wrong {metric} was not reported"

    def test_a_thousands_separator_is_read_as_a_number(self, tmp_path: Path) -> None:
        """The documents write `1,246`, not `1246`.

        `int("1,246")` raises, and a pattern that captured only the digits
        before the comma would have read it as 1 — drift against 1,321 for the
        wrong reason, every run, until someone deleted the check.
        """
        from scripts.doc_metrics import measure

        measured = measure()
        if "files_ahead" not in measured:
            pytest.skip("origin/main is not available in this checkout")

        doc = tmp_path / "PLAN.md"
        doc.write_text(
            f"is **{measured['commits_ahead']} commits and {measured['files_ahead']:,} files ahead of `main`**\n",
            encoding="utf-8",
        )
        drift = [
            d
            for d in check(extra_documents=[doc]).drift
            if d.path == doc and d.metric in {"commits_ahead", "files_ahead"}
        ]
        assert not drift, f"a comma-formatted figure was misread: {drift}"

    @pytest.mark.parametrize(
        "sentence",
        [
            "(measured 2026-09-13; this read 551 and 1,227 when the plan was written).",
            "a temporal cut through 551 interleaved commits",
            "The branch has 551 commits worth reviewing.",
            "1,246 files were touched in total.",
        ],
    )
    def test_prose_and_historical_records_are_not_read_as_claims(self, tmp_path: Path, sentence: str) -> None:
        """`LANDING_PLAN.md` line 4 deliberately records what the figure *was*
        when the plan was written. A pattern loose enough to match it would call
        a true historical sentence drift, and the fix a reader reaches for is to
        delete the record."""
        doc = tmp_path / "OTHER.md"
        doc.write_text(sentence + "\n", encoding="utf-8")
        drift = [
            d
            for d in check(extra_documents=[doc]).drift
            if d.path == doc and d.metric in {"commits_ahead", "files_ahead", "commits_behind"}
        ]
        assert not drift, f"{sentence!r} was read as a branch-distance claim"


class TestAnUnmeasurableFigureIsReportedNotSkipped:
    """`origin/main` is not always fetched — a shallow or single-branch clone has
    no such ref. Reporting 0 would be rule 2's defect (an unmeasured value is
    never zero) and would drift against every document. Raising would take the
    whole gate down for everyone in that checkout. So the figure is reported as
    unmeasurable, by name, and the run says so out loud."""

    def test_a_repository_without_origin_main_measures_nothing(self, tmp_path: Path) -> None:
        import subprocess

        from scripts.doc_metrics import _branch_distance

        subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
        assert _branch_distance(tmp_path) == {}, (
            "a checkout with no origin/main must yield no figure at all — not a zero"
        )

    def test_the_report_names_what_it_could_not_measure(self, tmp_path: Path) -> None:
        from scripts.doc_metrics import check as _check

        doc = tmp_path / "PLAN.md"
        doc.write_text("is **999 commits and 999 files ahead of `main`**\n", encoding="utf-8")
        report = _check(extra_documents=[doc])
        # Either it measured (and this is drift) or it could not (and this is
        # unmeasured) — silence is the one outcome that must not happen.
        touched = [d for d in report.drift if d.path == doc and d.metric in {"commits_ahead", "files_ahead"}]
        unmeasured = [h for h in report.unmeasured if h.path == doc and h.metric in {"commits_ahead", "files_ahead"}]
        assert touched or unmeasured, "a branch-distance claim was neither checked nor reported as unmeasurable"


class TestRefreshRewritesRatherThanNags:
    """`commits_ahead` moves with every commit. A check that demands a hand-edit
    that often is the check this module's docstring warns about — the one people
    answer with `--no-verify`. `--refresh` makes the fix one command."""

    def _doc(self, tmp_path: Path, stated: int, separator: bool = False) -> Path:
        doc = tmp_path / "PLAN.md"
        shown = f"{stated:,}" if separator else str(stated)
        doc.write_text(f"is **{shown} commits and 9 files ahead of `main`**\n", encoding="utf-8")
        return doc

    def test_a_drifted_figure_is_rewritten_to_the_measurement(self, tmp_path: Path, monkeypatch) -> None:
        from scripts import doc_metrics as dm

        doc = self._doc(tmp_path, 111)
        monkeypatch.setattr(dm, "_documents", lambda repo, extra=None: [doc])
        monkeypatch.setattr(dm, "measure", lambda repo=None: {"commits_ahead": 588, "files_ahead": 9})

        changed = dm.refresh()
        assert [(c.metric, c.stated, c.measured) for c in changed] == [("commits_ahead", 111, 588)]
        assert "588 commits and 9 files ahead" in doc.read_text(encoding="utf-8")

    def test_a_thousands_separator_is_preserved(self, tmp_path: Path, monkeypatch) -> None:
        """Rewriting `1,246` as `1321` restyles prose the author chose."""
        from scripts import doc_metrics as dm

        doc = self._doc(tmp_path, 1246, separator=True)
        monkeypatch.setattr(dm, "_documents", lambda repo, extra=None: [doc])
        monkeypatch.setattr(dm, "measure", lambda repo=None: {"commits_ahead": 1321, "files_ahead": 9})

        dm.refresh()
        assert "1,321 commits" in doc.read_text(encoding="utf-8")

    def test_refreshing_twice_changes_nothing_the_second_time(self, tmp_path: Path, monkeypatch) -> None:
        from scripts import doc_metrics as dm

        doc = self._doc(tmp_path, 111)
        monkeypatch.setattr(dm, "_documents", lambda repo, extra=None: [doc])
        monkeypatch.setattr(dm, "measure", lambda repo=None: {"commits_ahead": 588, "files_ahead": 9})

        dm.refresh()
        after_first = doc.read_text(encoding="utf-8")
        assert dm.refresh() == []
        assert doc.read_text(encoding="utf-8") == after_first

    def test_a_correct_document_is_left_byte_for_byte_alone(self, tmp_path: Path, monkeypatch) -> None:
        """Refresh must not reformat, reflow or re-end a document it agrees with."""
        from scripts import doc_metrics as dm

        doc = self._doc(tmp_path, 588)
        before = doc.read_bytes()
        monkeypatch.setattr(dm, "_documents", lambda repo, extra=None: [doc])
        monkeypatch.setattr(dm, "measure", lambda repo=None: {"commits_ahead": 588, "files_ahead": 9})

        assert dm.refresh() == []
        assert doc.read_bytes() == before

    def test_the_committed_documents_need_no_refresh(self) -> None:
        """The repository's own state: whatever is committed must already agree.

        This is what makes the ratchet real rather than aspirational — if it
        fails, a figure in a living document is stale right now.

        `policed_drift`: the branch-distance pair is maintained by `--sync`, not
        enforced, and asserting on it here made this test red after any
        code-only commit.
        """
        from scripts.doc_metrics import check

        assert check().policed_drift == []


class TestTheCommitBoundaryDoesNotMakeItPermanentlyRed:
    """A figure written during commit N states the distance as of N-1.

    `pre-commit` runs before the commit exists, so `git rev-list --count
    origin/main..HEAD` cannot include the commit being written. The document is
    therefore correct when the hook checks it and one stale the instant it
    lands — and the next doc-touching commit reports drift of exactly 1, is
    refreshed, lands, and is off by one again. An exact check is red forever,
    which is the check this module's docstring warns about.

    So a branch-distance figure is accepted if it matches the distance at HEAD
    **or** at HEAD's parent. That is not a fudge factor: it is the commit
    boundary stated in git's own terms, and it tolerates exactly one commit of
    staleness and no more.
    """

    def test_the_distance_one_commit_ago_is_also_accepted(self, tmp_path: Path) -> None:
        from scripts.doc_metrics import REPO, _branch_distance_at, check

        here = _branch_distance_at(REPO, "HEAD")
        before = _branch_distance_at(REPO, "HEAD~1")
        if not here or not before:
            pytest.skip("origin/main or HEAD~1 is not available in this checkout")
        assert before["commits_ahead"] == here["commits_ahead"] - 1

        doc = tmp_path / "PLAN.md"
        doc.write_text(
            f"is **{before['commits_ahead']} commits and {before['files_ahead']} files ahead of `main`**\n",
            encoding="utf-8",
        )
        drift = [d for d in check(extra_documents=[doc]).drift if d.path == doc]
        assert not drift, f"a figure one commit stale was reported as drift: {drift}"

    def test_two_commits_of_staleness_is_still_drift(self, tmp_path: Path) -> None:
        """The tolerance is the commit boundary, not a licence to go stale."""
        from scripts.doc_metrics import measure

        measured = measure()
        if "commits_ahead" not in measured:
            pytest.skip("origin/main is not available in this checkout")

        doc = tmp_path / "PLAN.md"
        doc.write_text(
            f"is **{measured['commits_ahead'] - 2} commits and 9 files ahead of `main`**\n",
            encoding="utf-8",
        )
        drift = [d for d in check(extra_documents=[doc]).drift if d.path == doc and d.metric == "commits_ahead"]
        assert drift, "a figure two commits stale was accepted"

    def test_the_committed_tree_is_green_right_now(self) -> None:
        """The point of the whole class: this must hold immediately after a
        commit lands, or the gate is red for everyone until someone refreshes.

        It must also hold two commits later, which is why it reads
        `policed_drift`. The one-commit tolerance above answers "is this figure
        acceptable at the instant the hook runs"; it cannot answer "is this
        tree in order", because the answer to that changes with every commit
        whether or not anyone has touched a document.
        """
        from scripts.doc_metrics import check

        assert check().policed_drift == []


class TestSyncKeepsTheVolatileFiguresTrueWithoutNagging:
    """`commits_ahead` and `files_ahead` change on EVERY commit, and the hook
    runs only when a document or a measuring script changes. So a run of
    code-only commits silently takes the figures several commits stale, and the
    next doc-touching commit is blocked through no fault of its author — which
    is how a gate teaches `--no-verify`.

    `--sync` rewrites those two figures and then checks everything else. The
    volatile pair is maintained rather than policed; every other claim still
    fails hard, because `gates_total` drifting is a fact someone must look at,
    not something a script should quietly paper over.
    """

    def test_sync_rewrites_a_volatile_figure(self, tmp_path: Path, monkeypatch) -> None:
        from scripts import doc_metrics as dm

        doc = tmp_path / "PLAN.md"
        doc.write_text("is **100 commits and 9 files ahead of `main`**\n", encoding="utf-8")
        monkeypatch.setattr(dm, "_documents", lambda repo, extra=None: [doc])
        monkeypatch.setattr(dm, "measure", lambda repo=None: {"commits_ahead": 590, "files_ahead": 9})

        assert dm.main(["--sync"]) == 0
        assert "590 commits" in doc.read_text(encoding="utf-8")

    def test_sync_does_not_paper_over_a_real_metric(self, tmp_path: Path, monkeypatch) -> None:
        """The whole point of the split. A wrong gate count must still fail."""
        from scripts import doc_metrics as dm

        doc = tmp_path / "GATES.md"
        doc.write_text("34 gates · 34 proven\n", encoding="utf-8")
        monkeypatch.setattr(dm, "_documents", lambda repo, extra=None: [doc])
        monkeypatch.setattr(dm, "measure", lambda repo=None: {"gates_total": 41, "gates_proven": 41})

        assert dm.main(["--sync"]) == 1
        assert "34 gates" in doc.read_text(encoding="utf-8"), "sync rewrote a figure it must only report"

    def test_refresh_only_volatile_leaves_the_rest_alone(self, tmp_path: Path, monkeypatch) -> None:
        from scripts import doc_metrics as dm

        doc = tmp_path / "BOTH.md"
        doc.write_text("34 gates · 34 proven\nis **100 commits and 9 files ahead of `main`**\n", encoding="utf-8")
        monkeypatch.setattr(dm, "_documents", lambda repo, extra=None: [doc])
        monkeypatch.setattr(
            dm,
            "measure",
            lambda repo=None: {"gates_total": 41, "gates_proven": 41, "commits_ahead": 590, "files_ahead": 9},
        )

        changed = dm.refresh(only=dm._COMMIT_BOUNDARY)
        assert {c.metric for c in changed} == {"commits_ahead"}
        text = doc.read_text(encoding="utf-8")
        assert "590 commits" in text and "34 gates" in text

    def test_sync_is_what_pre_commit_runs(self) -> None:
        """A flag nothing invokes maintains nothing.

        The hook entry is the wiring; without this, `--sync` could be correct
        and never run, which is the dead-control shape this repository keeps
        finding.
        """
        from pathlib import Path as _Path

        from scripts.doc_metrics import REPO

        config = _Path(REPO, ".pre-commit-config.yaml").read_text(encoding="utf-8")
        assert "doc_metrics.py --sync" in config, (
            "pre-commit still runs --check, so the figures are policed not maintained"
        )


class TestTheVolatilePairIsMaintainedNotPoliced:
    """The suite contradicted its own design, and was red most of the time.

    `TestSyncKeepsTheVolatileFiguresTrueWithoutNagging` states the rule: a
    figure that changes on every commit "cannot be enforced by hand — the hook
    only runs on doc changes, so a run of code-only commits takes it several
    commits stale and blocks the next doc commit through no fault of its
    author, which is how a gate teaches `--no-verify`."

    Three tests in this file then asserted `check().drift == []` against the
    LIVE tree, which polices exactly that pair. Measured 2026-09-15 they were
    red, and the mechanism is structural rather than bad luck:

      * `_accepted` tolerates the distance at HEAD~1 — correct, because the
        hook runs BEFORE the commit exists.
      * `refresh` selected its work from `check(repo).drift`, which applies the
        same tolerance. So `--sync` REWROTE NOTHING while the figure was one
        commit stale.
      * The document therefore kept the oldest value tolerance allowed, the
        commit landed, and one further commit made it two stale — hard drift,
        with nothing scheduled to fix it until some later documentation commit.

    Reproduced on the real tree: `LANDING_PLAN.md` was last written in
    `b12df894`, stating 639 while the distance at that commit's parent was 639
    and at HEAD was 640. Two commits later the measurement was 641 against a
    stated 639, and three tests in this file were red through nobody's fault.

    Two fixes, and both are needed:

      1. `--sync` now rewrites the volatile pair to the MEASURED value rather
         than only when it falls outside tolerance, so a documentation commit
         always banks the freshest figure it can.
      2. The live-tree assertions use `policed_drift`, which excludes the pair
         the design says is maintained. A test that polices what the design
         says must not be policed is a test that teaches people to ignore the
         suite.
    """

    def test_sync_banks_the_freshest_figure_rather_than_the_oldest_allowed(self, tmp_path: Path, monkeypatch) -> None:
        """The root cause. A figure one commit stale is ACCEPTED by the gate and
        must still be rewritten, or it is two stale at the next commit."""
        from scripts import doc_metrics as dm

        measured = dm.measure()
        if "commits_ahead" not in measured:
            pytest.skip("origin/main is not available in this checkout")
        previous = dm._branch_distance_at(dm.REPO, "HEAD~1")
        if previous.get("commits_ahead") == measured["commits_ahead"]:
            pytest.skip("HEAD and HEAD~1 are the same distance")

        doc = tmp_path / "PLAN.md"
        # Exactly the tolerated value: one commit stale, so `check` reports no
        # drift for it. Before the fix, `refresh` therefore left it alone.
        doc.write_text(
            f"is **{previous['commits_ahead']} commits and 9 files ahead of `main`**\n",
            encoding="utf-8",
        )
        monkeypatch.setattr(dm, "_documents", lambda repo, extra=None: [doc])
        dm.refresh(only=dm._COMMIT_BOUNDARY)
        assert f"{measured['commits_ahead']} commits" in doc.read_text(encoding="utf-8"), (
            "sync left the document at the oldest figure tolerance allowed, "
            "which is two commits stale the moment one more commit lands"
        )

    def test_policed_drift_excludes_the_pair_the_design_maintains(self) -> None:
        from scripts.doc_metrics import _COMMIT_BOUNDARY, check

        report = check()
        assert all(d.metric not in _COMMIT_BOUNDARY for d in report.policed_drift)

    def test_policed_drift_keeps_every_other_metric(self, tmp_path: Path) -> None:
        """The floor. A `policed_drift` that filtered everything would make the
        three live-tree assertions vacuous and this whole file decorative."""
        from scripts.doc_metrics import check

        doc = tmp_path / "OUT.md"
        doc.write_text("`GATE_EVIDENCE.toml` (999 gates, 999 proven).\n", encoding="utf-8")
        report = check(extra_documents=[doc])
        assert any(d.path == doc and d.metric == "gates_total" for d in report.policed_drift)

    def test_the_committed_tree_has_no_policed_drift(self) -> None:
        """What `test_the_committed_tree_is_green_right_now` meant to assert,
        stated so that a code-only commit cannot make it false."""
        from scripts.doc_metrics import check

        assert check().policed_drift == []

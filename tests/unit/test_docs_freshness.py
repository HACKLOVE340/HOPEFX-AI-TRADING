# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""Documentation freshness — Group 3 Chapter 15, and a correction to it.

The chapter asserted that a referential check "would have caught the Python 3.10
error, the prop_firm_mode.json error, and every stale path reference". That was
written without testing it and it is **wrong**: in all three historical errors
every referenced path existed, and the false part was never the reference.

So the module has two layers, and these tests pin both — including the explicit
record of which layer catches which historical error, so the corrected claim
cannot quietly drift back.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.docs_freshness import Baseline, check_all, check_document, checkable_documents

pytestmark = [pytest.mark.unit]


def _doc(tmp_path: Path, name: str, body: str) -> Path:
    p = tmp_path / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body, encoding="utf-8")
    return p


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A miniature repository with the real shapes the checker reasons about."""
    (tmp_path / "ai" / "gateway").mkdir(parents=True)
    (tmp_path / "ai" / "gateway" / "client.py").write_text("", encoding="utf-8")
    (tmp_path / "ml").mkdir()
    (tmp_path / "ml" / "inference_engine.py").write_text("", encoding="utf-8")
    (tmp_path / "Dockerfile").write_text("FROM python:3.12-slim\n", encoding="utf-8")
    return tmp_path


class TestTheThreeHistoricalErrors:
    """The correction, pinned. Referential catches none of them."""

    def test_the_python_version_error_needs_the_CLAIM_layer(self, repo: Path) -> None:
        # "Python 3.10 ... is what `Dockerfile` runs". `Dockerfile` EXISTS, so
        # nothing referential is wrong. Only comparing the stated version against
        # the image catches it.
        doc = _doc(repo, "d.md", "**Python 3.10** is the production target — it is what `Dockerfile` runs.\n")
        rules = {f.rule for f in check_document(doc, repo)}
        assert rules == {"python_version_claim"}

    def test_the_gitignore_error_needs_the_CLAIM_layer(self, tmp_path: Path) -> None:
        # `prop_firm_mode.json` existed. The false part was its STATUS.
        # Run against the real repository, because the claim is checked with
        # `git check-ignore` and needs a real work tree to mean anything.
        real = Path(__file__).resolve().parent.parent.parent
        doc = _doc(tmp_path, "d.md", "`prop_firm_mode.json` is gitignored.\n")
        rules = {f.rule for f in check_document(doc, real)}
        assert rules == {"gitignore_claim"}

    def test_a_true_gitignore_claim_is_not_reported(self, tmp_path: Path) -> None:
        # WORDMAP.json genuinely is ignored. A checker that fired here would be
        # reporting correct documentation as wrong.
        real = Path(__file__).resolve().parent.parent.parent
        doc = _doc(tmp_path, "d.md", "`WORDMAP.json` is gitignored.\n")
        assert check_document(doc, real) == []

    def test_the_semantic_error_is_caught_by_NEITHER_layer(self, repo: Path) -> None:
        # "`ml/` is legacy data files" — the path exists and no claim pattern
        # covers "what a package is for". Stated so the module's limits are pinned
        # rather than implied.
        doc = _doc(repo, "d.md", "The `ml/` directory holds legacy data files that are no longer used.\n")
        assert check_document(doc, repo) == []


class TestItDistinguishesAssertingFromQuoting:
    def test_a_document_reporting_the_old_error_is_not_reported(self, repo: Path) -> None:
        # The first version fired on two documents that DESCRIBE the historical
        # mistake — a backlog table quoting the old wording and the chapter citing
        # it. Same shape as a guard test that banned the strings its own docstrings
        # contained: a checker that cannot tell asserting from quoting fires
        # hardest on the documents written to record the problem.
        doc = _doc(repo, "d.md", "`CLAUDE.md` stated Python 3.10 matched the Docker image. It did not.\n")
        assert check_document(doc, repo) == []

    def test_a_quoted_claim_is_not_reported(self, repo: Path) -> None:
        doc = _doc(repo, "d.md", 'The old text read "Python 3.10 is the production target" in the Dockerfile note.\n')
        assert check_document(doc, repo) == []

    def test_but_the_present_tense_claim_still_fires(self, repo: Path) -> None:
        # The half that proves the narrowing did not simply disable the rule.
        doc = _doc(repo, "d.md", "**Python 3.11** is the production target — it is what `Dockerfile` runs.\n")
        assert [f.rule for f in check_document(doc, repo)] == ["python_version_claim"]


class TestPrecisionOverRecall:
    def test_a_missing_file_in_an_existing_directory_is_reported(self, repo: Path) -> None:
        doc = _doc(repo, "d.md", "See `ai/gateway/gone.py` for details.\n")
        assert [f.rule for f in check_document(doc, repo)] == ["stale_path"]

    def test_a_path_whose_parent_does_not_exist_is_an_illustration(self, repo: Path) -> None:
        # `made_up/` does not exist at all, so this is almost certainly an example
        # rather than a file that moved. Reporting it is how a checker earns a
        # reputation for noise and gets disabled.
        doc = _doc(repo, "d.md", "Put it in `made_up/thing.py` when you get there.\n")
        assert check_document(doc, repo) == []

    def test_a_module_reference_without_its_extension_resolves(self, repo: Path) -> None:
        # `ml/inference_engine` is an ordinary way to name `ml/inference_engine.py`.
        # Both of the first version's findings in the CONSTITUTION documents were
        # exactly this, and being wrong there costs most.
        doc = _doc(repo, "d.md", "Strict typing on `ml/inference_engine` and `ai/gateway/client`.\n")
        assert check_document(doc, repo) == []

    def test_fenced_code_blocks_are_skipped(self, repo: Path) -> None:
        # The path is BACKTICKED inside the fence. The first version of this test
        # used a bare path, which `_candidate_paths` would not have seen anywhere
        # — so it passed whether or not fences were skipped, and proved nothing.
        doc = _doc(repo, "d.md", "Text.\n\n```bash\ncat `ai/gateway/whatever.py`\n```\n\nMore.\n")
        assert check_document(doc, repo) == []

    def test_the_same_path_outside_a_fence_is_reported(self, repo: Path) -> None:
        # The positive control that makes the test above mean something.
        doc = _doc(repo, "d.md", "Read `ai/gateway/whatever.py` first.\n")
        assert [f.rule for f in check_document(doc, repo)] == ["stale_path"]

    def test_placeholders_are_skipped(self, repo: Path) -> None:
        for body in ("Use `ai/gateway/<your-file>.py`.", "See `path/to/thing.py`.", "Try `ai/gateway/example.py`."):
            doc = _doc(repo, "d.md", body + "\n")
            assert check_document(doc, repo) == [], body

    def test_an_absolute_path_is_about_the_host_not_the_repo(self, repo: Path) -> None:
        # This crashed the first version rather than being skipped.
        doc = _doc(repo, "d.md", "Logs go to `/var/log/hopefx.log`.\n")
        assert check_document(doc, repo) == []

    def test_a_missing_but_gitignored_path_is_not_reported(self, tmp_path: Path) -> None:
        # data/oanda_paper_start.json is gitignored (.gitignore:166) — it is
        # written at runtime by _stamp_oanda_paper_start() on first OANDA
        # connection and is legitimately absent from a fresh checkout. CHANGELOG.md
        # and docs/roadmap.md both reference it correctly; the checker was
        # reporting an accurate description of a generated artefact as stale.
        # Needs the real work tree, same as the gitignore_claim tests above —
        # git check-ignore has nothing to check in a tmp_path with no .git.
        real = Path(__file__).resolve().parent.parent.parent
        doc = _doc(tmp_path, "d.md", "Gate: `data/oanda_paper_start.json`, started 2026-03-27.\n")
        assert check_document(doc, real) == []

    def test_a_missing_path_that_is_not_gitignored_is_still_reported(self, tmp_path: Path) -> None:
        # The positive control: gitignore-awareness must not swallow every miss,
        # only the ones the repo has actually declared as generated.
        real = Path(__file__).resolve().parent.parent.parent
        doc = _doc(tmp_path, "d.md", "See `ai/gateway/definitely_does_not_exist_xyz.py`.\n")
        assert [f.rule for f in check_document(doc, real)] == ["stale_path"]


class TestItIsScopedWhereStalenessIsADefect:
    def test_records_and_archived_material_are_not_checked(self) -> None:
        # A postmortem naming a file that later moved is still an accurate record
        # of what was true then. 172 of the first 250 findings were in
        # docs/archive/, and reporting those every run buries the ones that matter.
        checkable = set(checkable_documents(Path(__file__).resolve().parent.parent.parent))
        assert not [p for p in checkable if p.startswith("docs/archive/")]

    def test_the_living_corpus_is_actually_checked(self) -> None:
        # The positive control. A scope that excluded everything would pass the
        # test above and prove nothing.
        checkable = checkable_documents(Path(__file__).resolve().parent.parent.parent)
        assert len(checkable) > 50
        assert "CLAUDE.md" in checkable and "ARCHITECTURE.md" in checkable


class TestTheRatchet:
    def test_the_committed_baseline_holds_the_corpus_clean(self) -> None:
        blocking = [f for f in check_all() if f.blocking]
        assert not blocking, "new findings: " + "; ".join(f"{f.document}:{f.line} {f.detail}" for f in blocking[:5])

    def test_the_baseline_has_not_silenced_the_checker(self) -> None:
        # Baselined is not the same as gone. If this reaches zero it means the
        # checker stopped looking, not that every reference was fixed.
        #
        # This floor was 40 (measured ~45) until the stale_path check itself
        # gained gitignore-awareness: it was reporting accurate references to
        # runtime-generated artefacts (data/oanda_paper_start.json,
        # backtest/results/multi_symbol_report.json) as stale. Fixing that false
        # positive dropped the real, unbaselined count to 37 — a genuine
        # reduction in checker error, not the checker looking away. Floor kept
        # well below the new count so a real regression still trips this.
        assert len(check_all(baseline=Baseline())) >= 30

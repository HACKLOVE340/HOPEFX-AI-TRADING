# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""Rule 1 evidence for the `change-record` gate: the defects it must refuse.

A gate ships with proof it can fail, or it is treated as absent. Each case below
introduces a defect and asserts the refusal — and the clean case is asserted
first, so a gate that refused everything could not pass as one that works.

The gate itself was nearly exempt: discovery in `scripts/gate_evidence.py`
matched only `scripts/*.py` entries, and this hook runs
`python -m deployment.change_records`. It was invisible, so the ledger reported
the same gate count before and after it was added. Widened, and this file is
what the widening then demanded.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit

from deployment import change_records as cr


def _record(paths: tuple[str, ...], expected: str | None) -> cr.ChangeRecord:
    return cr.ChangeRecord(
        change_id="test",
        at="2026-09-09T00:00:00+00:00",
        actor="test",
        commits=("abc",),
        paths=paths,
        expected_effect=expected,
    )


class TestTheGateRefusesEachDefect:
    def test_the_clean_case_passes_first(self) -> None:
        assert cr.validate(_record(("risk/manager.py",), "refusals fall to zero")) == []

    def test_a_core_change_with_no_prediction(self) -> None:
        assert cr.validate(_record(("risk/manager.py",), None))

    def test_a_core_change_with_a_blank_prediction(self) -> None:
        # A trailer with whitespace after it is somebody satisfying a linter.
        assert cr.validate(_record(("execution/oms.py",), "   "))

    def test_an_unclassified_package(self) -> None:
        # Fail closed: the first new package must not be the one that ships
        # without a prediction.
        assert cr.validate(_record(("some_new_package/x.py",), None))

    def test_a_root_entry_point(self) -> None:
        assert cr.validate(_record(("app.py",), None))

    def test_ci_configuration(self) -> None:
        assert cr.validate(_record((".github/workflows/ci.yml",), None))

    def test_and_a_presentation_change_is_not_refused(self) -> None:
        # The other half of a working gate: it must let the right things past.
        assert cr.validate(_record(("docs/x.md", "frontend/src/app.tsx"), None)) == []


class TestTheTrailerParserRefusesWhatItShould:
    @pytest.mark.parametrize(
        "message",
        [
            "Fix a thing\n",
            "Fix\n\nExpected-Effect:\n",
            "Fix\n\nExpected-Effect:    \n",
            "Fix\n\nExpectedEffect: no hyphen so not the trailer\n",
        ],
    )
    def test_no_prediction_is_read(self, message: str) -> None:
        assert cr.expected_effect(message) is None

    def test_a_real_one_is_read(self) -> None:
        assert cr.expected_effect("Fix\n\nExpected-Effect: latency drops\n") == "latency drops"


class TestItWarnsByDefaultAndEnforcesOnRequest:
    """The owner chose warn over block on 2026-09-09 (ADR 0012).

    The concern with warning is real and stated in that record: a gate that only
    warns is a gate people learn to scroll past. Three things keep this one
    honest rather than decorative, and each is asserted here:

    * the warning is loud and names the exact trailer to add, so acting on it is
      cheaper than ignoring it;
    * `CHANGE_RECORD_ENFORCE=1` turns it into a block with no code change, so
      the decision can be revisited by configuration;
    * `--report` measures the real KPI over a range, so "how often is a
      prediction actually stated" is a number somebody can look at rather than a
      claim. A warning whose effect is never measured is the thing the concern
      is about.
    """

    def test_by_default_a_missing_prediction_warns_rather_than_blocks(self, tmp_path, monkeypatch) -> None:
        message = tmp_path / "COMMIT_EDITMSG"
        message.write_text("Change the risk manager\n", encoding="utf-8")
        monkeypatch.setattr(cr, "_git", lambda *args: "risk/manager.py\n")
        monkeypatch.delenv("CHANGE_RECORD_ENFORCE", raising=False)
        assert cr.main(["--check-message", str(message)]) == 0

    def test_the_warning_says_what_to_add(self, tmp_path, monkeypatch, capsys) -> None:
        message = tmp_path / "COMMIT_EDITMSG"
        message.write_text("Change the risk manager\n", encoding="utf-8")
        monkeypatch.setattr(cr, "_git", lambda *args: "risk/manager.py\n")
        monkeypatch.delenv("CHANGE_RECORD_ENFORCE", raising=False)
        cr.main(["--check-message", str(message)])
        text = capsys.readouterr().err
        assert "Expected-Effect:" in text
        assert "WARN" in text.upper()

    def test_the_warning_names_the_switch_that_enforces_it(self, tmp_path, monkeypatch, capsys) -> None:
        # Otherwise the only way to find it is reading this module.
        message = tmp_path / "COMMIT_EDITMSG"
        message.write_text("Change the risk manager\n", encoding="utf-8")
        monkeypatch.setattr(cr, "_git", lambda *args: "risk/manager.py\n")
        monkeypatch.delenv("CHANGE_RECORD_ENFORCE", raising=False)
        cr.main(["--check-message", str(message)])
        assert "CHANGE_RECORD_ENFORCE" in capsys.readouterr().err

    def test_enforcement_blocks(self, tmp_path, monkeypatch) -> None:
        message = tmp_path / "COMMIT_EDITMSG"
        message.write_text("Change the risk manager\n", encoding="utf-8")
        monkeypatch.setattr(cr, "_git", lambda *args: "risk/manager.py\n")
        monkeypatch.setenv("CHANGE_RECORD_ENFORCE", "1")
        assert cr.main(["--check-message", str(message)]) == 1

    def test_enforcement_does_not_block_a_compliant_change(self, tmp_path, monkeypatch) -> None:
        message = tmp_path / "COMMIT_EDITMSG"
        message.write_text("Change it\n\nExpected-Effect: refusals fall to zero\n", encoding="utf-8")
        monkeypatch.setattr(cr, "_git", lambda *args: "risk/manager.py\n")
        monkeypatch.setenv("CHANGE_RECORD_ENFORCE", "1")
        assert cr.main(["--check-message", str(message)]) == 0

    def test_validate_itself_still_reports_the_problem(self) -> None:
        """Warn-or-block is a decision about the EXIT CODE, not about the truth.

        `validate()` keeps returning the problem either way, so `--report` and
        any future consumer measure what is actually missing rather than what
        the current exit policy happens to surface.
        """
        assert cr.validate(_record(("risk/manager.py",), None))


class TestTheKpiIsMeasured:
    """Chapter 6's KPI: change records with a stated expected effect, target
    100% of core-tier. Warning instead of blocking makes that number fall below
    100 — which is fine, and only fine if the number is visible."""

    def test_it_reports_a_coverage_figure(self, monkeypatch) -> None:
        report = cr.coverage_report("HEAD~5..HEAD")
        assert set(report) >= {"changes", "needing_prediction", "with_prediction", "coverage"}
        assert report["changes"] >= 1

    def test_coverage_is_none_when_nothing_needed_one(self, monkeypatch) -> None:
        # Rule 2: no core-tier changes in the range means the KPI is UNDEFINED,
        # not 100%. A perfect score from an empty denominator is the oldest
        # fabricated metric there is.
        monkeypatch.setattr(cr, "_commits_in", lambda _r: [("abc", "Tidy docs", ("docs/x.md",))])
        assert cr.coverage_report("x..y")["coverage"] is None


class TestTheCommandLineRefuses:
    def test_the_same_change_with_a_trailer_passes(self, tmp_path, monkeypatch) -> None:
        message = tmp_path / "COMMIT_EDITMSG"
        message.write_text(
            "Change the risk manager\n\nExpected-Effect: refused trades fall to zero\n", encoding="utf-8"
        )
        monkeypatch.setattr(cr, "_git", lambda *args: "risk/manager.py\n")
        assert cr.main(["--check-message", str(message)]) == 0

    def test_a_docs_only_change_passes_without_one(self, tmp_path, monkeypatch) -> None:
        message = tmp_path / "COMMIT_EDITMSG"
        message.write_text("Tidy the README\n", encoding="utf-8")
        monkeypatch.setattr(cr, "_git", lambda *args: "README.md\n")
        assert cr.main(["--check-message", str(message)]) == 0

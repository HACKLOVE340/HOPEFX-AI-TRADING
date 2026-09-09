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


class TestTheCommandLineRefuses:
    def test_a_core_change_with_no_trailer_exits_non_zero(self, tmp_path, monkeypatch) -> None:
        """End to end through `main`, which is what the hook actually runs."""
        message = tmp_path / "COMMIT_EDITMSG"
        message.write_text("Change the risk manager\n", encoding="utf-8")
        monkeypatch.setattr(cr, "_git", lambda *args: "risk/manager.py\n")
        assert cr.main(["--check-message", str(message)]) == 1

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

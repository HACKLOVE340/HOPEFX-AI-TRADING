# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""`scripts/model_provenance_report.py` — and whether it can report bad news.

A measurement that cannot produce a failing answer is the third sub-shape in
`hopefx-dead-controls`: `scripts/invariant_coverage.py` counted hand-typed
`True` literals and could not print anything but full coverage. These tests put
each bad condition on disk and assert the report names it, so the numbers it
prints about this repository are numbers it could have printed differently.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import pathlib
import sys

import pytest

pytestmark = pytest.mark.unit

REPO = pathlib.Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "model_provenance_report.py"


def _load_report():
    spec = importlib.util.spec_from_file_location("_model_provenance_report", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["_model_provenance_report"] = module
    try:
        spec.loader.exec_module(module)
        return module
    finally:
        sys.modules.pop("_model_provenance_report", None)


@pytest.fixture
def report():
    return _load_report()


def _artifact(directory: pathlib.Path, name: str, payload: bytes) -> pathlib.Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_bytes(payload)
    return path


def _baseline(directory: pathlib.Path, entries: dict[str, str]) -> None:
    (directory / "model_checksums.json").write_text(json.dumps(entries, indent=2))


class TestIdentityCanSayNo:
    def test_a_matching_artifact_reads_ok(self, report, tmp_path, monkeypatch) -> None:
        art = _artifact(tmp_path, "good.pkl", b"weights")
        _baseline(tmp_path, {"good.pkl": hashlib.sha256(b"weights").hexdigest()})
        monkeypatch.setattr(report, "MODEL_DIRS", (tmp_path,))
        monkeypatch.setattr(report, "REPO", tmp_path.parent)

        (row,) = [r for r in report.survey_identity() if r["path"].endswith("good.pkl")]
        assert row["verdict"] == "ok"
        assert art.exists()

    def test_a_changed_artifact_reads_mismatch(self, report, tmp_path, monkeypatch) -> None:
        _artifact(tmp_path, "drifted.pkl", b"retrained weights")
        _baseline(tmp_path, {"drifted.pkl": hashlib.sha256(b"the original").hexdigest()})
        monkeypatch.setattr(report, "MODEL_DIRS", (tmp_path,))
        monkeypatch.setattr(report, "REPO", tmp_path.parent)

        (row,) = [r for r in report.survey_identity() if r["path"].endswith("drifted.pkl")]
        assert row["verdict"] == "MISMATCH"

    def test_an_artifact_with_no_entry_reads_not_listed(self, report, tmp_path, monkeypatch) -> None:
        """The condition that matters most: a model file nobody recorded."""
        _artifact(tmp_path, "arrived.pkl", b"where did this come from")
        _baseline(tmp_path, {})
        monkeypatch.setattr(report, "MODEL_DIRS", (tmp_path,))
        monkeypatch.setattr(report, "REPO", tmp_path.parent)

        (row,) = [r for r in report.survey_identity() if r["path"].endswith("arrived.pkl")]
        assert row["verdict"] == "NOT LISTED"

    def test_an_entry_with_no_file_reads_listed_but_absent(self, report, tmp_path, monkeypatch) -> None:
        _artifact(tmp_path, "present.pkl", b"x")
        _baseline(tmp_path, {"present.pkl": hashlib.sha256(b"x").hexdigest(), "vanished.pt": "deadbeef"})
        monkeypatch.setattr(report, "MODEL_DIRS", (tmp_path,))
        monkeypatch.setattr(report, "REPO", tmp_path.parent)

        verdicts = {r["path"].rsplit("/", 1)[-1]: r["verdict"] for r in report.survey_identity()}
        assert verdicts["vanished.pt"] == "LISTED BUT ABSENT"

    def test_a_missing_baseline_does_not_read_as_ok(self, report, tmp_path, monkeypatch) -> None:
        """No record is not a clean bill of health."""
        _artifact(tmp_path, "unrecorded.pkl", b"x")
        monkeypatch.setattr(report, "MODEL_DIRS", (tmp_path,))
        monkeypatch.setattr(report, "REPO", tmp_path.parent)

        (row,) = report.survey_identity()
        assert row["verdict"] == "NOT LISTED"
        assert row["baseline"] == "absent"

    def test_an_unreadable_baseline_is_reported_rather_than_swallowed(self, report, tmp_path, monkeypatch) -> None:
        _artifact(tmp_path, "x.pkl", b"x")
        (tmp_path / "model_checksums.json").write_text("{ not json")
        monkeypatch.setattr(report, "MODEL_DIRS", (tmp_path,))
        monkeypatch.setattr(report, "REPO", tmp_path.parent)

        (row,) = report.survey_identity()
        assert row["baseline"].startswith("unreadable")
        assert row["verdict"] == "NOT LISTED"


class TestWiringCanSayNo:
    def test_a_loader_with_no_check_is_named(self, report, tmp_path, monkeypatch) -> None:
        package = tmp_path / "ml"
        package.mkdir()
        (package / "bare.py").write_text("import joblib\nm = joblib.load('x.pkl')\n")
        monkeypatch.setattr(report, "REPO", tmp_path)

        (row,) = [r for r in report.survey_wiring() if r["module"].endswith("bare.py")]
        assert row["gates"] == []
        assert "joblib.load" in row["loader_calls"]

    def test_either_integrity_check_counts(self, report, tmp_path, monkeypatch) -> None:
        """Reporting the absence of one particular gate as "unguarded" is the
        same defect pointed the other way. Both must count."""
        package = tmp_path / "ml"
        package.mkdir()
        (package / "checksum_gate.py").write_text("import joblib\n_verify_checksum(p)\njoblib.load(p)\n")
        (package / "registry_gate.py").write_text("import joblib\nself._verify_integrity()\njoblib.load(p)\n")
        monkeypatch.setattr(report, "REPO", tmp_path)

        gates = {r["module"].rsplit("/", 1)[-1]: r["gates"] for r in report.survey_wiring()}
        assert gates["checksum_gate.py"] == ["ml._verify_checksum"]
        assert gates["registry_gate.py"] == ["registry digest"]

    def test_a_module_that_loads_nothing_is_not_reported(self, report, tmp_path, monkeypatch) -> None:
        package = tmp_path / "ml"
        package.mkdir()
        (package / "pure.py").write_text("def add(a, b):\n    return a + b\n")
        monkeypatch.setattr(report, "REPO", tmp_path)

        assert [r for r in report.survey_wiring() if r["module"].endswith("pure.py")] == []


class TestItLeavesNoTrace:
    """The report must not become the thing it reports on.

    Writing this report, the author called `ml._verify_checksum` directly on
    three artifacts with APP_ENV=production to see what the gate would say.
    Because `_bootstrap_allowed` exempts every directory that is not the
    packaged one, the call did not merely answer — it wrote a brand-new trust
    baseline into `ml/saved_models/GCF/`, `ml/saved_models/XAU_USD/` and
    `ml/rl_models/`, recording as canonical whatever happened to be on disk at
    that moment. Three untracked `model_checksums.json` files appeared, and had
    they been committed they would have silently settled one of the open
    questions in MASTER_OUTSTANDING A7 in the worst possible direction.

    That is the finding demonstrating itself, and it is why the report is
    read-only and why that is held by a test rather than by intention.
    """

    def test_surveying_a_directory_creates_no_baseline(self, report, tmp_path, monkeypatch) -> None:
        _artifact(tmp_path, "unrecorded.pkl", b"weights")
        monkeypatch.setattr(report, "MODEL_DIRS", (tmp_path,))
        monkeypatch.setattr(report, "REPO", tmp_path.parent)

        before = {p.name for p in tmp_path.iterdir()}
        report.survey_identity()
        report.survey_reach()

        assert {p.name for p in tmp_path.iterdir()} == before
        assert not (tmp_path / "model_checksums.json").exists()

    def test_the_real_survey_writes_nothing_into_the_repository(self, report, tmp_path) -> None:
        """Run it against the actual model directories, as CI and an operator
        would, and assert the tree is unchanged afterwards."""
        watched = [d for d in report.MODEL_DIRS if d.is_dir()]
        before = {d: {p.name for p in d.iterdir()} for d in watched}

        report.survey_identity()
        report.survey_reach()
        report.survey_wiring()

        for directory in watched:
            assert {p.name for p in directory.iterdir()} == before[directory], (
                f"{directory} gained or lost a file while being measured"
            )


class TestItNeverRepairs:
    def test_a_mismatch_leaves_both_the_file_and_the_record_alone(self, report, tmp_path, monkeypatch) -> None:
        """Recomputing a mismatched hash destroys the only evidence that the
        artifact and its record ever disagreed."""
        art = _artifact(tmp_path, "drifted.pkl", b"retrained")
        recorded = hashlib.sha256(b"original").hexdigest()
        _baseline(tmp_path, {"drifted.pkl": recorded})
        monkeypatch.setattr(report, "MODEL_DIRS", (tmp_path,))
        monkeypatch.setattr(report, "REPO", tmp_path.parent)

        report.survey_identity()

        assert art.read_bytes() == b"retrained"
        assert json.loads((tmp_path / "model_checksums.json").read_text())["drifted.pkl"] == recorded

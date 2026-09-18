# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""The model-provenance ratchet must be able to fail.

Measured 2026-09-13, and the second number is the one that matters:

    2 of 12 recorded artifacts MISMATCH their sha256
    2 of 14 ml/ modules that load a model reach any integrity check at all

`ml/__init__.py::_verify_checksum` is fail-closed in production and gates a
`pickle.load`, so what it permits is arbitrary code execution rather than merely
a wrong prediction. Twelve modules do not reach it — including
`ml/inference_engine.py`, which is the live inference path.

Neither number is closed by this ratchet, deliberately, and the module docstring
of `check()` says why: "which bytes are the real ones" for the two mismatches is
an owner decision (MASTER_OUTSTANDING A8), and adding a fail-closed check to
`inference_engine.py` today would refuse a model that currently loads and halt
live inference. Both are decisions with a blast radius.

What the ratchet refuses is the thirteenth ungated loader and the eighth
unlisted artifact — so the hole stops growing while the decisions are made.

Every rule below is exercised by introducing the defect, because
`hopefx-dead-controls` is about gates that read correctly and never fire.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "model_provenance_report.py"
BASELINE = REPO / "docs" / "MODEL_PROVENANCE_DEBT.json"


def run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
        cwd=str(REPO),
        check=False,  # inspecting non-zero exits is the point
    )


@pytest.fixture
def restore_baseline():
    """Edits to the committed baseline, undone whatever the test does."""
    original = BASELINE.read_text(encoding="utf-8")
    yield
    BASELINE.write_text(original, encoding="utf-8")


def test_the_committed_baseline_matches_the_tree():
    result = run("--check")
    assert result.returncode == 0, result.stderr


def test_the_baseline_records_the_measured_scale():
    """A sanity floor: if these collapse, the surveys broke, not the debt."""
    recorded = json.loads(BASELINE.read_text(encoding="utf-8"))
    assert len(recorded["ungated_loaders"]) >= 8, "the ungated-loader survey stopped matching"
    assert len(recorded["unlisted_artifacts"]) >= 4, "the unlisted-artifact survey stopped matching"


def test_the_live_inference_path_is_named_in_the_debt():
    """The entry a reader must not miss.

    `ml/inference_engine.py` is the module the running platform predicts from,
    and it reaches no integrity check. If it ever leaves this list, it is
    because it was fixed — and it must leave, because the rule below refuses a
    stale entry.
    """
    recorded = json.loads(BASELINE.read_text(encoding="utf-8"))
    assert "ml/inference_engine.py" in recorded["ungated_loaders"]


def test_a_thirteenth_ungated_loader_blocks(restore_baseline):
    """The injection. A new bare loader must not be absorbed silently."""
    recorded = json.loads(BASELINE.read_text(encoding="utf-8"))
    recorded["ungated_loaders"] = [m for m in recorded["ungated_loaders"] if m != "ml/pipeline.py"]
    BASELINE.write_text(json.dumps(recorded, indent=1, sort_keys=True) + "\n", encoding="utf-8")

    result = run("--check")
    assert result.returncode == 1, "an ungated loader missing from the baseline must block"
    assert "ml/pipeline.py" in result.stderr
    assert "joblib.load gates arbitrary code execution" in result.stderr


def test_an_eighth_unlisted_artifact_blocks(restore_baseline):
    """Same rule, other list: a committed binary no baseline records."""
    recorded = json.loads(BASELINE.read_text(encoding="utf-8"))
    dropped = recorded["unlisted_artifacts"].pop()
    BASELINE.write_text(json.dumps(recorded, indent=1, sort_keys=True) + "\n", encoding="utf-8")

    result = run("--check")
    assert result.returncode == 1, "an unlisted artifact missing from the baseline must block"
    assert dropped in result.stderr


def test_a_cleared_entry_must_leave_the_list(restore_baseline):
    """An entry that no longer describes anything is how a ratchet stops being one.

    The same rule the colour, emoji and coverage ratchets enforce. Without it the
    list becomes permission rather than debt.
    """
    recorded = json.loads(BASELINE.read_text(encoding="utf-8"))
    recorded["ungated_loaders"].append("ml/a_module_that_is_not_ungated.py")
    BASELINE.write_text(json.dumps(recorded, indent=1, sort_keys=True) + "\n", encoding="utf-8")

    result = run("--check")
    assert result.returncode == 1
    assert "must leave" in result.stderr


def test_artifact_identity_is_outside_this_gate_entirely(restore_baseline):
    """The deliberate exemption, asserted so it cannot be quietly tightened.

    This test used to assert that the two A8 mismatches existed and did not
    block, and it carried a note to revisit itself if they ever cleared. They
    have: `feature_scaler.pkl` and `stacking_ensemble.pkl` were re-recorded once
    git history showed the manifest had never matched any committed version of
    them, while the bytes on disk trace to a deliberate fix (776b59cf, F145). So
    the original assertion can no longer hold, and the test does what its own
    note said to do.

    What still needs pinning is the SCOPE: this ratchet is about ungated loaders
    and unlisted artifacts, and it must not start blocking on artifact identity.
    Identity is `_verify_checksum`'s job at load time and the manifest gate's job
    at commit time; a third opinion here would mean a mismatch blocks every
    unrelated commit, which is how A8 would have been decided by attrition.

    The report still SURVEYS identity — that capability is what found A8 — and
    the gate still passes while the survey is non-clean.
    """
    report = run("--json")
    assert report.returncode == 0, report.stderr
    identity = json.loads(report.stdout)["identity"]

    verdicts = {r["verdict"] for r in identity}
    assert verdicts - {"ok"}, (
        "the identity survey is entirely clean, so this test proves nothing about scope; "
        "if that is now true of the repository, assert it directly instead"
    )

    assert run("--check").returncode == 0, (
        "the ratchet blocked on an identity verdict — it is scoped to ungated loaders and "
        "unlisted artifacts, and identity belongs to _verify_checksum and the manifest gate"
    )


def test_the_a8_mismatches_stay_fixed():
    """The two artifacts that did not load in production must keep loading.

    `_verify_checksum` is fail-closed in production, so a mismatch here is not a
    stale number — it is a model the platform refuses to load.
    """
    report = run("--json")
    identity = json.loads(report.stdout)["identity"]
    mismatched = [r["path"] for r in identity if r["verdict"] == "MISMATCH"]
    assert mismatched == [], f"an artifact stopped matching its recorded sha256: {mismatched}"


def test_check_without_a_baseline_refuses(tmp_path, restore_baseline):
    """Fail closed: a gate that cannot find its baseline must not certify."""
    moved = tmp_path / "moved.json"
    shutil.move(str(BASELINE), str(moved))
    try:
        result = run("--check")
        assert result.returncode == 1
        assert "no baseline" in result.stderr
    finally:
        shutil.move(str(moved), str(BASELINE))

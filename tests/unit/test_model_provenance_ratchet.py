# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""The model-provenance ratchet must be able to fail.

Measured 2026-09-18:

    0 of 17 recorded artifacts MISMATCH their sha256
    12 of 14 ml/ modules that load a model reach an integrity check

`ml/__init__.py::_verify_checksum` is fail-closed in production and gates a
`pickle.load`, so what it permits is arbitrary code execution rather than merely
a wrong prediction.

Measured 2026-09-13 it read 2 of 12 mismatching and 2 of 14 reaching a check,
and five assertions below were written around those figures — a floor of eight
ungated loaders, a named entry for `ml/inference_engine.py`, an injection that
dropped `ml/pipeline.py` from the list, an injection that popped an unlisted
artifact off it, and a scope pin that required the identity survey to be
non-clean. Each is rewritten here, and each says in its own docstring what it
used to claim, because a floor under the debt is a test that fails when the
debt is repaid.

What the ratchet refuses is the FOURTH ungated loader and the FIRST new
unlisted artifact.

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


def test_the_surveys_still_match_something():
    """A scan that matched nothing agrees with every rule (F255).

    This used to assert `len(ungated_loaders) >= 8` and
    `len(unlisted_artifacts) >= 4` — a floor UNDER THE DEBT, which reads as a
    sanity check and behaves as a requirement that the hole stay open. Ten
    loaders were routed through the gate and all seven unlisted artifacts were
    recorded on 2026-09-18, and the assertion that survived the repair is the
    one it was actually for: that the surveys are still looking at something.

    So it asserts the surveys, not the baseline. `check()` has its own guard for
    an empty wiring survey; this covers the identity survey too, and it cannot
    be satisfied by repaying debt.
    """
    report = run("--json")
    assert report.returncode == 0, report.stderr
    measured = json.loads(report.stdout)

    assert len(measured["wiring"]) >= 10, "the loader-call survey stopped matching ml/ modules"
    assert len(measured["identity"]) >= 15, "the artifact survey stopped matching committed binaries"
    assert len(measured["reach"]) >= 4, "the model-directory survey stopped matching directories"


def test_the_live_inference_path_reaches_the_gate():
    """It left the debt list, so this asserts the fix rather than the hole.

    This used to assert `"ml/inference_engine.py" in recorded["ungated_loaders"]`
    and carried a note that it must leave the list once fixed. It has:
    `_load_calibrator` now runs `ml._verify_checksum` before `joblib.load`, and
    `tests/unit/test_model_loaders_reach_the_integrity_gate.py` corrupts a real
    calibrator and asserts the load is refused.

    `ml/inference_engine.py` is the module the running platform predicts from,
    so it is named here rather than left to the aggregate count.
    """
    report = run("--json")
    wiring = {r["module"]: r["gates"] for r in json.loads(report.stdout)["wiring"]}

    assert "ml/inference_engine.py" in wiring, "the wiring survey stopped seeing the live inference path"
    assert wiring["ml/inference_engine.py"], "the live inference path reaches no integrity check"

    recorded = json.loads(BASELINE.read_text(encoding="utf-8"))
    assert "ml/inference_engine.py" not in recorded["ungated_loaders"]


def test_an_ungated_loader_missing_from_the_baseline_blocks(restore_baseline):
    """The injection. A new bare loader must not be absorbed silently.

    It used to drop the hard-coded `"ml/pipeline.py"` from the list. That module
    was gated on 2026-09-18, so the removal became a no-op and the injection
    quietly stopped injecting anything — the test passed while proving nothing.
    The module now comes from the recorded list, so it cannot rot the same way.
    """
    recorded = json.loads(BASELINE.read_text(encoding="utf-8"))
    assert recorded["ungated_loaders"], "no ungated loader left to inject with — assert the fix instead"
    victim = recorded["ungated_loaders"][0]
    recorded["ungated_loaders"] = [m for m in recorded["ungated_loaders"] if m != victim]
    BASELINE.write_text(json.dumps(recorded, indent=1, sort_keys=True) + "\n", encoding="utf-8")

    result = run("--check")
    assert result.returncode == 1, "an ungated loader missing from the baseline must block"
    assert victim in result.stderr
    assert "joblib.load gates arbitrary code execution" in result.stderr


def test_a_new_unlisted_artifact_blocks():
    """Same rule, other list: a model binary no baseline records.

    It used to `.pop()` an entry off `unlisted_artifacts` and assert the gate
    noticed it was gone. All seven were recorded on 2026-09-18, so that list is
    empty and `.pop()` raises IndexError — there is nothing left to remove. The
    injection now puts a REAL unrecorded artifact in a real model directory,
    which is both the defect's actual shape and something that cannot be
    disarmed by repaying the debt.
    """
    probe = REPO / "ml" / "rl_models" / "ratchet_probe.pkl"
    assert not probe.exists(), "a leftover probe from an earlier run — remove it before trusting this"
    probe.write_bytes(b"pretend model bytes")
    try:
        result = run("--check")
        assert result.returncode == 1, "an unrecorded model binary must block"
        assert "ml/rl_models/ratchet_probe.pkl" in result.stderr
        assert "record it in the baseline its directory uses" in result.stderr
    finally:
        probe.unlink()

    assert run("--check").returncode == 0, "the probe was not cleaned up"


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

    Rewritten 2026-09-18. It used to assert the identity survey was non-clean,
    relying on a mismatch this repository happened to be carrying, and carried a
    note to assert the scope directly once the survey came clean. It has: all 17
    artifacts match. So the mismatch is now INJECTED — a real artifact with a
    deliberately wrong recorded hash — which pins the scope without depending on
    the repository staying broken.
    """
    directory = REPO / "ml" / "rl_models"
    manifest = directory / "model_checksums.json"
    probe = directory / "identity_probe.pkl"
    original = manifest.read_text(encoding="utf-8")
    assert not probe.exists(), "a leftover probe from an earlier run — remove it before trusting this"

    try:
        probe.write_bytes(b"bytes that will not match")
        recorded = json.loads(original)
        recorded[probe.name] = "0" * 64
        manifest.write_text(json.dumps(recorded, indent=2) + "\n", encoding="utf-8")

        report = run("--json")
        assert report.returncode == 0, report.stderr
        identity = json.loads(report.stdout)["identity"]
        verdicts = {r["path"]: r["verdict"] for r in identity}
        assert verdicts["ml/rl_models/identity_probe.pkl"] == "MISMATCH", (
            "the injection did not produce a MISMATCH, so this proves nothing about scope"
        )

        assert run("--check").returncode == 0, (
            "the ratchet blocked on an identity verdict — it is scoped to ungated loaders and "
            "unlisted artifacts, and identity belongs to _verify_checksum and the manifest gate"
        )
    finally:
        probe.unlink(missing_ok=True)
        manifest.write_text(original, encoding="utf-8")

    assert run("--check").returncode == 0, "the injection was not cleaned up"


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

# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""The manifest gate must refuse a model artefact that changed without its checksum.

Group 2 Rule 1: a gate nobody has watched fail is not a gate. Each test below
stages a real change in a real throwaway repository and asserts the gate's
verdict — no mocking of git, because the thing being tested is what `git show
:path` returns for a staged file, which is precisely what a mock would get wrong.

Why the gate exists is in `scripts/model_artifact_manifest_gate.py`: two
committed artefacts do not load in production today because their recorded
checksums went stale when a leaking test suite got them committed alongside
unrelated work (MASTER_OUTSTANDING §A8).
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[2]
GATE = ROOT / "scripts" / "model_artifact_manifest_gate.py"


def _run(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(GATE), *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, capture_output=True, check=True)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A throwaway repository shaped like this one's model directory."""
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "t@example.test")
    _git(tmp_path, "config", "user.name", "t")

    models = tmp_path / "ml" / "saved_models"
    models.mkdir(parents=True)
    (models / "advanced_oos.pkl").write_bytes(b"original model bytes")
    (models / "feature_scaler.pkl").write_bytes(b"original scaler bytes")
    (models / "model_checksums.json").write_text(
        json.dumps(
            {
                "advanced_oos.pkl": hashlib.sha256(b"original model bytes").hexdigest(),
                "feature_scaler.pkl": hashlib.sha256(b"original scaler bytes").hexdigest(),
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-qm", "baseline")
    return tmp_path


def _regenerate_manifest(repo: Path) -> None:
    models = repo / "ml" / "saved_models"
    digests = {
        p.name: hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(models.iterdir())
        if p.is_file() and p.name != "model_checksums.json"
    }
    (models / "model_checksums.json").write_text(json.dumps(digests, indent=2, sort_keys=True), encoding="utf-8")


def test_a_clean_commit_passes(repo: Path):
    """The positive control.

    Without it, every refusal below is satisfied by a gate that refuses
    everything — which would pass the injections and prove nothing.
    """
    (repo / "unrelated.py").write_text("x = 1\n", encoding="utf-8")
    _git(repo, "add", "unrelated.py")

    r = _run(repo)
    assert r.returncode == 0, r.stdout


def test_an_artefact_changed_without_its_checksum_is_refused(repo: Path):
    """The defect this gate exists for, in the shape it actually happened."""
    (repo / "ml" / "saved_models" / "feature_scaler.pkl").write_bytes(b"retrained bytes")
    _git(repo, "add", "ml/saved_models/feature_scaler.pkl")

    r = _run(repo)
    assert r.returncode != 0, r.stdout
    assert "feature_scaler.pkl" in r.stdout
    assert "REFUSED" in r.stdout


def test_an_artefact_changed_with_its_checksum_is_allowed(repo: Path):
    """The intended workflow must not be blocked, or the gate gets bypassed."""
    (repo / "ml" / "saved_models" / "feature_scaler.pkl").write_bytes(b"retrained bytes")
    _regenerate_manifest(repo)
    _git(repo, "add", "-A")

    r = _run(repo)
    assert r.returncode == 0, r.stdout


def test_a_new_artefact_the_manifest_does_not_mention_is_refused(repo: Path):
    """An unlisted artefact is one _verify_checksum refuses to load in production."""
    (repo / "ml" / "saved_models" / "brand_new.pkl").write_bytes(b"new model")
    _git(repo, "add", "ml/saved_models/brand_new.pkl")

    r = _run(repo)
    assert r.returncode != 0, r.stdout
    assert "brand_new.pkl" in r.stdout
    assert "not listed" in r.stdout


def test_a_pre_existing_mismatch_does_not_block_an_unrelated_commit(repo: Path):
    """The deliberate exemption, and it needs a test or somebody will remove it.

    Two artefacts mismatch in the real repository today, and whether to
    regenerate, gate or investigate is an owner decision (§A8). A gate that
    blocked every commit until that decision was made would decide it by
    attrition. So a mismatch this commit did not create is not this commit's
    problem.
    """
    models = repo / "ml" / "saved_models"
    models.joinpath("feature_scaler.pkl").write_bytes(b"drifted long ago")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "artefact drifted, manifest not updated")

    (repo / "unrelated.py").write_text("x = 1\n", encoding="utf-8")
    _git(repo, "add", "unrelated.py")

    r = _run(repo)
    assert r.returncode == 0, r.stdout


def test_the_gate_reads_staged_bytes_not_the_working_tree(repo: Path):
    """Staging the fix and then breaking the file again must still pass.

    A gate that hashed the working tree would refuse a commit whose recorded
    content is correct, and — worse in the other direction — would accept one
    whose staged content is wrong while the file on disk happens to be right.
    What gets committed is what was staged.
    """
    models = repo / "ml" / "saved_models"
    models.joinpath("feature_scaler.pkl").write_bytes(b"retrained bytes")
    _regenerate_manifest(repo)
    _git(repo, "add", "-A")

    # Disk now diverges from the index; the index is what this commit records.
    models.joinpath("feature_scaler.pkl").write_bytes(b"scribbled after staging")

    r = _run(repo)
    assert r.returncode == 0, r.stdout


def test_the_audit_mode_reports_the_committed_tree(repo: Path):
    models = repo / "ml" / "saved_models"
    models.joinpath("feature_scaler.pkl").write_bytes(b"drifted")

    r = _run(repo, "--all")
    assert r.returncode == 0
    assert "1 mismatch" in r.stdout
    assert "feature_scaler.pkl" in r.stdout


def test_a_training_report_beside_the_artefacts_is_not_refused(repo: Path):
    """Scope, and the reason it needed narrowing.

    The manifest lists only what the loader verifies — `.pkl`, `.pt`, `.zip`.
    The ten `.json` files in `ml/saved_models/` are metadata and training
    reports that nothing checksums. The first version of this gate treated every
    file in the directory as an artefact and refused a staged
    `advanced_oos_meta.json` for "not being listed" in a manifest that is not
    supposed to list it. Caught end to end against the real repository, not in
    review.

    That matters more than a false positive usually does: a gate which refuses
    correct commits is one people switch off, and a gate that is switched off
    protects nothing. So the exemption gets a test of its own.
    """
    (repo / "ml" / "saved_models" / "advanced_training_report.json").write_text(
        '{"feature_count": 100}', encoding="utf-8"
    )
    _git(repo, "add", "ml/saved_models/advanced_training_report.json")

    r = _run(repo)
    assert r.returncode == 0, r.stdout

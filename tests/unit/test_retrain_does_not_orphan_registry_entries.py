# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
tests/unit/test_retrain_does_not_orphan_registry_entries.py
===========================================================
The mechanism that produced the registry corruption, rather than its symptoms.

``repair_model_registry.py --resync`` fixed the manifest: three entries recorded
0.5650 for an artifact whose own sidecar measured 0.5734. That repaired the
damage and left the cause running.

The cause is that ``ml/train_advanced.py`` writes ``advanced_oos.pkl`` with
``joblib.dump`` and **never touches the registry** — a grep for "registry" in
that module returns nothing. So every retrain overwrites the bytes that existing
entries describe, in place, silently. Four entries ended up pointing at one file
with two different recorded accuracies, because three of them were describing a
model that no longer existed at that path. ``MODEL_IDENTITY.md`` records the
same thing in prose: *"retrained in place on 2026-06-26 ... left every older
registry entry pointing at the new file while still describing the model it
replaced."*

Re-running the trainer today would reproduce it exactly.

The fix is to stop destroying the old bytes. Before overwriting, the artifact is
copied to a content-addressed name (``advanced_oos.<sha12>.pkl``) and every
registry entry whose recorded ``sha256`` matches those bytes is repointed at the
copy. The entry then describes a file that still exists and still contains what
it says it does, and the audit stays clean across a retrain.

The sidecar is archived with it, for provenance rather than for the audit.
``audit_manifest`` resolves ``<stem>_meta.json`` from the artifact's own stem,
so an archived ``.pkl`` with no archived sidecar simply has none — the audit
does not fall back to the new model's metadata, and treats missing metadata as
"no evidence of a mismatch" rather than a fault.

Dropping it fails more quietly: the archived bytes would carry no record of
what they measured, so the accuracy recorded on the registry entry could never
be verified against anything again. That is exactly the position ``--resync``
had to resolve by hand.
"""

from __future__ import annotations

import hashlib
import json
import pathlib

import pytest

pytestmark = pytest.mark.unit


def _sha256(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


@pytest.fixture
def trained(tmp_path, monkeypatch):
    """An artifact + sidecar + a registry entry describing them."""
    import ml.train_advanced as ta

    monkeypatch.setattr(ta, "MODEL_DIR", tmp_path)

    artifact = tmp_path / "advanced_oos.pkl"
    artifact.write_bytes(b"model-v1-bytes")
    (tmp_path / "advanced_oos_meta.json").write_text(json.dumps({"oos_accuracy": 0.5650}))

    manifest = tmp_path / "registry.json"
    manifest.write_text(
        json.dumps(
            {
                "active_version": "v1",
                "versions": {
                    "v1": {"file": str(artifact), "sha256": _sha256(artifact), "oos_accuracy": 0.5650},
                    "unrelated_v1": {"file": str(tmp_path / "other.pkl"), "sha256": "f" * 64, "oos_accuracy": 0.61},
                },
            }
        )
    )
    return artifact, manifest


def _registry(manifest):
    from ml.model_registry import ModelRegistry

    return ModelRegistry(registry_path=manifest)


# ── The old bytes survive ────────────────────────────────────────────────────


def test_the_previous_artifact_is_preserved(trained):
    from ml.train_advanced import archive_artifact_before_overwrite

    artifact, manifest = trained
    original_sha = _sha256(artifact)

    archive = archive_artifact_before_overwrite(artifact, registry=_registry(manifest))

    assert archive is not None and archive.exists()
    assert _sha256(archive) == original_sha, "the archived copy is not the bytes that were there"
    assert original_sha[:12] in archive.name, "the archive name is not content-addressed"


def test_the_sidecar_is_archived_with_it(trained):
    """Provenance: without the sidecar the archived bytes carry no record of
    what they measured, so the entry's recorded accuracy can never be checked
    against anything again — the position --resync had to resolve by hand."""
    from ml.train_advanced import archive_artifact_before_overwrite

    artifact, manifest = trained
    archive = archive_artifact_before_overwrite(artifact, registry=_registry(manifest))

    sidecar = archive.with_name(f"{archive.stem}_meta.json")
    assert sidecar.exists(), f"no sidecar archived beside {archive.name}"
    assert json.loads(sidecar.read_text())["oos_accuracy"] == pytest.approx(0.5650)


def test_entries_describing_those_bytes_are_repointed(trained):
    from ml.train_advanced import archive_artifact_before_overwrite

    artifact, manifest = trained
    archive = archive_artifact_before_overwrite(artifact, registry=_registry(manifest))

    versions = json.loads(manifest.read_text())["versions"]
    assert versions["v1"]["file"] == str(archive), "the entry still points at the path about to be overwritten"
    assert versions["v1"]["sha256"] == _sha256(archive), "the recorded digest no longer matches its file"


def test_unrelated_entries_are_untouched(trained):
    from ml.train_advanced import archive_artifact_before_overwrite

    artifact, manifest = trained
    before = json.loads(manifest.read_text())["versions"]["unrelated_v1"]

    archive_artifact_before_overwrite(artifact, registry=_registry(manifest))

    after = json.loads(manifest.read_text())["versions"]["unrelated_v1"]
    assert after == before, "an entry describing different bytes was rewritten"


# ── The end state is what matters ────────────────────────────────────────────


def test_the_audit_stays_clean_across_a_retrain(trained):
    """The whole point. Archive, overwrite, and the manifest still describes
    files that exist and contain what it says."""
    from ml.train_advanced import archive_artifact_before_overwrite

    artifact, manifest = trained

    archive_artifact_before_overwrite(artifact, registry=_registry(manifest))

    # The retrain: new bytes at the same path, new sidecar.
    artifact.write_bytes(b"model-v2-bytes-different")
    (artifact.parent / "advanced_oos_meta.json").write_text(json.dumps({"oos_accuracy": 0.5734}))

    audit = _registry(manifest).audit_manifest()
    assert audit["stale_metrics"] == [], f"retraining still orphaned an entry: {audit['stale_metrics']}"
    # `unrelated_v1` points at a file the fixture never creates — that is
    # deliberate, so the "unrelated entries are untouched" test has something
    # to be untouched. Assert only that the retrained entry still resolves.
    assert "v1" not in audit["missing_artifacts"], (
        f"the archived entry no longer resolves to a file: {audit['missing_artifacts']}"
    )


def test_without_the_archive_the_retrain_orphans_the_entry(trained):
    """Proves the test above is not vacuous — the unarchived path is exactly
    the deployed defect, reproduced."""
    artifact, manifest = trained

    artifact.write_bytes(b"model-v2-bytes-different")
    (artifact.parent / "advanced_oos_meta.json").write_text(json.dumps({"oos_accuracy": 0.5734}))

    audit = _registry(manifest).audit_manifest()
    stale = {i["version"] for i in audit["stale_metrics"]}
    assert "v1" in stale, "expected the in-place retrain to orphan v1"


# ── Safety ───────────────────────────────────────────────────────────────────


def test_archives_are_not_committed_to_the_repository():
    """Pins the trade-off rather than leaving it implicit.

    Archives match `ml/saved_models/*.pkl` in .gitignore and are runtime state,
    not repository content — a copy of every historical model would bloat the
    repo. The consequence is that a fresh clone reports the repointed entries
    as `missing_artifacts`, which `--prune-missing` clears.

    That is the intended outcome: an entry naming an honestly-absent file is a
    reportable finding, where an entry naming a file that exists and holds a
    different model is a silent lie. If someone whitelists archives later, this
    fails and forces the repo-size question to be answered deliberately.
    """
    import subprocess

    root = pathlib.Path(__file__).resolve().parents[2]
    probe = "ml/saved_models/advanced_oos.0123456789ab.pkl"
    result = subprocess.run(
        ["git", "check-ignore", probe],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, f"{probe} is no longer gitignored — every retrain would commit a full model artifact"


def test_a_missing_artifact_is_a_no_op(tmp_path, monkeypatch):
    """First-ever training run: nothing to preserve."""
    import ml.train_advanced as ta

    monkeypatch.setattr(ta, "MODEL_DIR", tmp_path)
    assert ta.archive_artifact_before_overwrite(tmp_path / "advanced_oos.pkl") is None


def test_archiving_twice_does_not_duplicate(trained):
    """Content-addressed: the same bytes archive to the same name."""
    from ml.train_advanced import archive_artifact_before_overwrite

    artifact, manifest = trained
    first = archive_artifact_before_overwrite(artifact, registry=_registry(manifest))
    second = archive_artifact_before_overwrite(artifact, registry=_registry(manifest))

    assert first == second
    assert len(list(artifact.parent.glob("advanced_oos.*.pkl"))) == 1


def test_it_works_without_a_registry(trained):
    """Preserving the bytes must not depend on a manifest being available."""
    from ml.train_advanced import archive_artifact_before_overwrite

    artifact, _ = trained
    archive = archive_artifact_before_overwrite(artifact, registry=None)
    assert archive is not None and archive.exists()


def test_a_registry_failure_does_not_lose_the_artifact(trained, monkeypatch):
    """Training must not die because the manifest could not be rewritten, and
    the archived bytes must survive regardless."""
    from ml.train_advanced import archive_artifact_before_overwrite

    artifact, manifest = trained

    class _Broken:
        def _load(self):
            raise OSError("manifest unreadable")

    archive = archive_artifact_before_overwrite(artifact, registry=_Broken())
    assert archive is not None and archive.exists()


# ── It is actually wired in ──────────────────────────────────────────────────


def test_the_trainer_archives_before_dumping():
    """Defining the function is not enough — oos_eval_advanced must call it
    before joblib.dump overwrites the artifact."""
    import inspect

    import ml.train_advanced as ta

    src = inspect.getsource(ta.oos_eval_advanced)
    assert "archive_artifact_before_overwrite" in src, (
        "the OOS save path still overwrites advanced_oos.pkl without preserving the previous model"
    )
    archive_at = src.index("archive_artifact_before_overwrite")
    dump_at = src.index("joblib.dump")
    assert archive_at < dump_at, "the archive happens after the overwrite, which is too late"

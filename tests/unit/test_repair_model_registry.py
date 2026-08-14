# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
tests/unit/test_repair_model_registry.py
========================================
A CRITICAL finding with a prescribed fix and no way to apply it.

``ModelRegistry.audit_manifest()`` correctly diagnoses the deployed finding, and
running it against the real registry reproduces the screenshot exactly::

    Registry: 8 version(s), active='xgb_horizon5_v3'
      3 entr(y/ies) disagree with their artifact's own metadata:
        advanced_oos_v1   recorded=0.5650  artifact=0.5734
        advanced_oos_v2   recorded=0.5650  artifact=0.5734
        xgb_horizon5_v1   recorded=0.5650  artifact=0.5734
      1 entr(y/ies) point at a file that does not exist: mtf_ensemble_v1
      1 artifact(s) carry conflicting metrics across entries:
        sha dc7454d8  advanced_oos_v1, advanced_oos_v2, xgb_horizon5_v1,
                      xgb_horizon5_v3  <-- SERVING INFERENCE

Worth stating plainly, because the alert reads worse than the situation: the
version actually serving inference, ``xgb_horizon5_v3``, is the one whose
recorded accuracy **matches** its artifact. The three disagreeing entries are
historical rows describing a model that was overwritten in place. Nothing is
serving a mislabelled score.

The audit is read-only on purpose — rewriting a stale entry to the current
artifact's number would assert it describes the current model, which it does
not — so the remediation text told an operator to "delete or re-register them"
with no tool for either. This is that tool.

It refuses to choose between the two interpretations, because they are
opposites: ``--resync`` says the entry is meant to describe the current
artifact, ``--prune-stale`` says it describes one that no longer exists. Asking
for both is an error rather than a precedence rule.
"""

from __future__ import annotations

import json
import pathlib
import sys

import pytest

pytestmark = pytest.mark.unit

_ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT))

from scripts.repair_model_registry import main as repair_main


@pytest.fixture
def registry(tmp_path, monkeypatch):
    """A manifest with one stale entry, one missing artifact, one clean entry."""
    artifact = tmp_path / "model.pkl"
    artifact.write_bytes(b"artifact")
    (tmp_path / "model_meta.json").write_text(
        json.dumps({"oos_accuracy": 0.5734, "trained_at": "2026-06-26T22:30:43+00:00"})
    )

    manifest = tmp_path / "registry.json"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "active_version": "current_v2",
                "versions": {
                    "stale_v1": {"file": str(artifact), "sha256": "aaa", "oos_accuracy": 0.5650},
                    "current_v2": {"file": str(artifact), "sha256": "aaa", "oos_accuracy": 0.5734},
                    "gone_v1": {"file": str(tmp_path / "vanished.pkl"), "sha256": "bbb", "oos_accuracy": 0.61},
                },
            }
        )
    )

    from ml.model_registry import ModelRegistry

    import scripts.repair_model_registry as tool

    monkeypatch.setattr(tool, "_registry", lambda: ModelRegistry(registry_path=manifest))
    return manifest


def _versions(manifest: pathlib.Path) -> dict:
    return json.loads(manifest.read_text())["versions"]


# ── Reporting ────────────────────────────────────────────────────────────────


def test_reporting_changes_nothing(registry, capsys):
    before = registry.read_text()
    code = repair_main([])
    assert code == 1, "findings exist, so the exit code must be non-zero"
    assert registry.read_text() == before
    out = capsys.readouterr().out
    assert "stale_v1" in out
    assert "gone_v1" in out


def test_the_report_marks_the_version_serving_inference(registry, capsys):
    """A conflict that includes the active version is a different severity from
    one that does not."""
    repair_main([])
    assert "SERVING INFERENCE" in capsys.readouterr().out


def test_a_dry_run_with_actions_still_writes_nothing(registry, capsys):
    before = registry.read_text()
    assert repair_main(["--prune-stale"]) == 1
    assert registry.read_text() == before
    assert "Dry run" in capsys.readouterr().out


# ── The two interpretations are not interchangeable ──────────────────────────


def test_resync_and_prune_stale_together_is_an_error(registry, capsys):
    """They assert opposite things about the same entry. A precedence rule
    would silently pick one meaning on the operator's behalf."""
    assert repair_main(["--resync", "--prune-stale", "--apply"]) == 2
    assert "opposites" in capsys.readouterr().err


def test_resync_copies_the_artifact_measurement_onto_the_entry(registry):
    assert repair_main(["--resync", "--apply"]) == 0
    assert _versions(registry)["stale_v1"]["oos_accuracy"] == pytest.approx(0.5734)


def test_resync_never_averages(registry):
    """The remediation text is explicit: "Do not average conflicting scores."
    0.565 and 0.5734 would average to 0.5692, which describes no model."""
    repair_main(["--resync", "--apply"])
    value = _versions(registry)["stale_v1"]["oos_accuracy"]
    assert value in (pytest.approx(0.5734),), f"got {value}, which is neither recorded nor measured"


def test_prune_stale_removes_the_entry_and_leaves_the_artifact(registry, tmp_path):
    assert repair_main(["--prune-stale", "--apply"]) == 0
    versions = _versions(registry)
    assert "stale_v1" not in versions
    assert "current_v2" in versions, "a correct entry was pruned"
    assert (tmp_path / "model.pkl").exists(), "the tool deleted a model file"


def test_prune_missing_removes_only_the_dangling_entry(registry):
    assert repair_main(["--prune-missing", "--apply"]) == 0
    versions = _versions(registry)
    assert "gone_v1" not in versions
    assert "stale_v1" in versions, "prune-missing also removed a stale-metrics entry"


# ── The active version is protected ──────────────────────────────────────────


def test_pruning_the_active_version_is_refused(tmp_path, monkeypatch, capsys):
    """Removing the entry that serves inference is not a cleanup."""
    artifact = tmp_path / "m.pkl"
    artifact.write_bytes(b"x")
    (tmp_path / "m_meta.json").write_text(json.dumps({"oos_accuracy": 0.99}))
    manifest = tmp_path / "r.json"
    manifest.write_text(
        json.dumps(
            {
                "active_version": "active_v1",
                "versions": {"active_v1": {"file": str(artifact), "sha256": "a", "oos_accuracy": 0.10}},
            }
        )
    )

    from ml.model_registry import ModelRegistry

    import scripts.repair_model_registry as tool

    monkeypatch.setattr(tool, "_registry", lambda: ModelRegistry(registry_path=manifest))

    assert repair_main(["--prune-stale", "--apply"]) == 3
    assert "active_v1" in json.loads(manifest.read_text())["versions"]
    assert "refusing to prune" in capsys.readouterr().err


def test_the_active_version_can_be_pruned_deliberately(tmp_path, monkeypatch):
    artifact = tmp_path / "m.pkl"
    artifact.write_bytes(b"x")
    (tmp_path / "m_meta.json").write_text(json.dumps({"oos_accuracy": 0.99}))
    manifest = tmp_path / "r.json"
    manifest.write_text(
        json.dumps(
            {
                "active_version": "active_v1",
                "versions": {"active_v1": {"file": str(artifact), "sha256": "a", "oos_accuracy": 0.10}},
            }
        )
    )

    from ml.model_registry import ModelRegistry

    import scripts.repair_model_registry as tool

    monkeypatch.setattr(tool, "_registry", lambda: ModelRegistry(registry_path=manifest))

    assert repair_main(["--prune-stale", "--allow-active", "--apply"]) == 0
    assert json.loads(manifest.read_text())["versions"] == {}


# ── Safety ───────────────────────────────────────────────────────────────────


def test_a_backup_is_written_before_any_change(registry):
    repair_main(["--prune-stale", "--apply"])
    backups = list(registry.parent.glob(f"{registry.name}.*.bak"))
    assert len(backups) == 1
    saved = json.loads(backups[0].read_text())
    assert "stale_v1" in saved["versions"], "the backup does not contain the pre-change state"


def test_a_clean_registry_reports_ok_and_exits_zero(tmp_path, monkeypatch, capsys):
    manifest = tmp_path / "r.json"
    manifest.write_text(json.dumps({"active_version": None, "versions": {}}))

    from ml.model_registry import ModelRegistry

    import scripts.repair_model_registry as tool

    monkeypatch.setattr(tool, "_registry", lambda: ModelRegistry(registry_path=manifest))

    assert repair_main([]) == 0
    assert "no findings" in capsys.readouterr().out


# ── The real registry ────────────────────────────────────────────────────────


def test_the_shipped_registry_still_has_the_finding_this_tool_is_for():
    """If someone repairs it, this test says so rather than silently passing.

    It also pins the reassuring half: the version serving inference is the one
    whose recorded accuracy matches its artifact.
    """
    from ml.model_registry import get_registry

    audit = get_registry().audit_manifest()
    if audit["ok"]:
        pytest.skip("registry already repaired")

    stale_names = {item["version"] for item in audit["stale_metrics"]}
    assert audit["active_version"] not in stale_names, (
        f"the active version {audit['active_version']!r} now carries metrics that disagree with its "
        "artifact — inference is serving a mislabelled model"
    )

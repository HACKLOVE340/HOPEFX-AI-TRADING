# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# AGPL-3.0 — Share all modifications
"""
Unit tests for ml/model_registry.py.

Targets the promotion gate branches, symlink swap, bootstrap_from_meta,
retire, verify, and singleton — the areas with incomplete branch coverage.
"""

from __future__ import annotations

import json
import os
import pickle
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture()
def registry(tmp_path):
    """Return a ModelRegistry backed by a temp directory."""
    from ml.model_registry import ModelRegistry
    reg = ModelRegistry(registry_path=tmp_path / "registry.json")
    return reg


@pytest.fixture()
def artifact(tmp_path):
    """Write a tiny pickle artifact and return its path."""
    p = tmp_path / "model.pkl"
    p.write_bytes(pickle.dumps({"weights": [1, 2, 3]}))
    return p


# ── _gate_check branches ──────────────────────────────────────────────────────

class TestGateCheck:
    def test_passes_when_all_thresholds_met(self, registry):
        entry = {
            "oos_accuracy": 0.70,
            "oos_p_value": 0.001,
            "sharpe_gate_passed": True,
        }
        passed, reason = registry._gate_check(entry)
        assert passed is True
        assert "Gate passed" in reason

    def test_fails_on_low_accuracy(self, registry):
        entry = {
            "oos_accuracy": 0.50,  # below 0.60 default
            "oos_p_value": 0.001,
            "sharpe_gate_passed": True,
        }
        passed, reason = registry._gate_check(entry)
        assert passed is False
        assert "accuracy" in reason.lower()

    def test_fails_on_high_p_value(self, registry):
        entry = {
            "oos_accuracy": 0.70,
            "oos_p_value": 0.10,  # above 0.05 default
            "sharpe_gate_passed": True,
        }
        passed, reason = registry._gate_check(entry)
        assert passed is False
        assert "p-value" in reason.lower()

    def test_fails_when_sharpe_gate_not_passed(self, registry):
        import ml.model_registry as mr
        entry = {
            "oos_accuracy": 0.70,
            "oos_p_value": 0.001,
            "sharpe_gate_passed": False,
        }
        with patch.object(mr, "_REQUIRE_SHARPE_GATE", True):
            passed, reason = registry._gate_check(entry)
        assert passed is False
        assert "Sharpe" in reason

    def test_sharpe_gate_skipped_when_not_required(self, registry):
        import ml.model_registry as mr
        entry = {
            "oos_accuracy": 0.70,
            "oos_p_value": 0.001,
            "sharpe_gate_passed": False,
        }
        with patch.object(mr, "_REQUIRE_SHARPE_GATE", False):
            passed, reason = registry._gate_check(entry)
        assert passed is True


# ── register ──────────────────────────────────────────────────────────────────

class TestRegister:
    def test_register_creates_entry(self, registry, artifact):
        entry = registry.register(
            name="v1",
            file_path=artifact,
            oos_accuracy=0.65,
            oos_auc=0.72,
            oos_p_value=0.01,
            sharpe_gate_passed=True,
            n_trades=800,
            feature_count=50,
        )
        assert entry["name"] == "v1"
        assert entry["state"] == "staging"
        assert len(entry["sha256"]) == 64

    def test_register_raises_for_missing_artifact(self, registry, tmp_path):
        with pytest.raises(FileNotFoundError):
            registry.register(name="v1", file_path=tmp_path / "missing.pkl")

    def test_register_raises_for_empty_name(self, registry, artifact):
        with pytest.raises(ValueError, match="non-empty"):
            registry.register(name="", file_path=artifact)

    def test_register_raises_for_invalid_state(self, registry, artifact):
        with pytest.raises(ValueError, match="state"):
            registry.register(name="v1", file_path=artifact, state="production")

    def test_register_persists_to_manifest(self, registry, artifact):
        registry.register(name="v1", file_path=artifact)
        versions = registry.list_versions()
        assert "v1" in versions


# ── promote ───────────────────────────────────────────────────────────────────

class TestPromote:
    def _register_good(self, registry, artifact, name="v1"):
        return registry.register(
            name=name,
            file_path=artifact,
            oos_accuracy=0.70,
            oos_auc=0.72,
            oos_p_value=0.001,
            sharpe_gate_passed=True,
        )

    def test_promote_raises_for_unknown_version(self, registry):
        with pytest.raises(KeyError):
            registry.promote("nonexistent")

    def test_promote_raises_when_gate_fails(self, registry, artifact):
        registry.register(
            name="v1",
            file_path=artifact,
            oos_accuracy=0.50,  # below threshold
            oos_p_value=0.001,
            sharpe_gate_passed=True,
        )
        with pytest.raises(RuntimeError, match="BLOCKED"):
            registry.promote("v1")

    def test_promote_sets_state_production(self, registry, artifact):
        self._register_good(registry, artifact)
        with patch.object(registry, "_update_symlink"):
            entry = registry.promote("v1")
        assert entry["state"] == "production"
        assert entry["promoted_at"] is not None

    def test_promote_retires_previous_production(self, registry, artifact, tmp_path):
        # Register and promote v1
        a1 = tmp_path / "m1.pkl"
        a1.write_bytes(pickle.dumps({}))
        a2 = tmp_path / "m2.pkl"
        a2.write_bytes(pickle.dumps({}))

        registry.register(
            name="v1", file_path=a1,
            oos_accuracy=0.70, oos_p_value=0.001, sharpe_gate_passed=True,
        )
        with patch.object(registry, "_update_symlink"):
            registry.promote("v1")

        # Register and promote v2
        registry.register(
            name="v2", file_path=a2,
            oos_accuracy=0.72, oos_p_value=0.001, sharpe_gate_passed=True,
        )
        with patch.object(registry, "_update_symlink"):
            registry.promote("v2")

        versions = registry.list_versions()
        assert versions["v1"]["state"] == "retired"
        assert versions["v2"]["state"] == "production"

    def test_promote_notifies_performance_monitor(self, registry, artifact):
        self._register_good(registry, artifact)
        mock_monitor = MagicMock()
        mock_get_monitor = MagicMock(return_value=mock_monitor)

        with patch.object(registry, "_update_symlink"), \
             patch.dict("sys.modules", {"ml.performance_monitor": MagicMock(get_monitor=mock_get_monitor)}):
            registry.promote("v1")

        mock_monitor.on_model_promoted.assert_called_once()

    def test_promote_handles_monitor_exception(self, registry, artifact):
        self._register_good(registry, artifact)
        mock_get_monitor = MagicMock(side_effect=RuntimeError("monitor down"))

        with patch.object(registry, "_update_symlink"), \
             patch.dict("sys.modules", {"ml.performance_monitor": MagicMock(get_monitor=mock_get_monitor)}):
            entry = registry.promote("v1")  # must not raise

        assert entry["state"] == "production"


# ── _update_symlink ───────────────────────────────────────────────────────────

class TestUpdateSymlink:
    def test_symlink_created(self, registry, artifact):
        registry._update_symlink(artifact)
        symlink = registry._path.parent / "current.pkl"
        assert symlink.exists() or symlink.is_symlink()

    def test_symlink_handles_os_error(self, registry, artifact):
        with patch("pathlib.Path.symlink_to", side_effect=OSError("no symlinks")):
            registry._update_symlink(artifact)  # must not raise

    def test_symlink_replaces_existing(self, registry, artifact, tmp_path):
        # Create a second artifact
        a2 = tmp_path / "model2.pkl"
        a2.write_bytes(pickle.dumps({"v": 2}))

        registry._update_symlink(artifact)
        registry._update_symlink(a2)

        symlink = registry._path.parent / "current.pkl"
        assert symlink.is_symlink()


# ── verify / verify_active ────────────────────────────────────────────────────

class TestVerify:
    def test_verify_returns_false_for_unknown_version(self, registry):
        ok, msg = registry.verify("nonexistent")
        assert ok is False
        assert "not found" in msg

    def test_verify_returns_false_when_artifact_missing(self, registry, artifact):
        registry.register(name="v1", file_path=artifact)
        # Delete the artifact
        artifact.unlink()
        ok, msg = registry.verify("v1")
        assert ok is False
        assert "missing" in msg.lower()

    def test_verify_returns_true_for_intact_artifact(self, registry, artifact):
        registry.register(name="v1", file_path=artifact)
        ok, msg = registry.verify("v1")
        assert ok is True
        assert "OK" in msg

    def test_verify_returns_false_on_sha256_mismatch(self, registry, artifact):
        registry.register(name="v1", file_path=artifact)
        # Tamper with the stored hash
        manifest = registry._load()
        manifest["versions"]["v1"]["sha256"] = "deadbeef" * 8
        registry._save(manifest)

        ok, msg = registry.verify("v1")
        assert ok is False
        assert "MISMATCH" in msg

    def test_verify_returns_false_when_no_sha256_stored(self, registry, artifact):
        registry.register(name="v1", file_path=artifact)
        manifest = registry._load()
        manifest["versions"]["v1"]["sha256"] = ""
        registry._save(manifest)

        ok, msg = registry.verify("v1")
        assert ok is False

    def test_verify_active_returns_false_when_no_active(self, registry):
        ok, msg = registry.verify_active()
        assert ok is False
        assert "No active" in msg

    def test_verify_active_delegates_to_verify(self, registry, artifact):
        registry.register(name="v1", file_path=artifact)
        manifest = registry._load()
        manifest["active_version"] = "v1"
        registry._save(manifest)

        ok, msg = registry.verify_active()
        assert ok is True


# ── retire ────────────────────────────────────────────────────────────────────

class TestRetire:
    def test_retire_sets_state(self, registry, artifact):
        registry.register(name="v1", file_path=artifact)
        registry.retire("v1")
        assert registry.get_version("v1")["state"] == "retired"

    def test_retire_raises_for_unknown_version(self, registry):
        with pytest.raises(KeyError):
            registry.retire("nonexistent")


# ── active_version / active_path ──────────────────────────────────────────────

class TestActiveVersion:
    def test_active_version_returns_none_when_empty(self, registry):
        assert registry.active_version() is None

    def test_active_path_returns_none_when_empty(self, registry):
        assert registry.active_path() is None

    def test_active_version_returns_entry_after_promote(self, registry, artifact):
        registry.register(
            name="v1", file_path=artifact,
            oos_accuracy=0.70, oos_p_value=0.001, sharpe_gate_passed=True,
        )
        with patch.object(registry, "_update_symlink"):
            registry.promote("v1")

        entry = registry.active_version()
        assert entry is not None
        assert entry["name"] == "v1"

    def test_active_path_returns_path_after_promote(self, registry, artifact):
        registry.register(
            name="v1", file_path=artifact,
            oos_accuracy=0.70, oos_p_value=0.001, sharpe_gate_passed=True,
        )
        with patch.object(registry, "_update_symlink"):
            registry.promote("v1")

        path = registry.active_path()
        assert path is not None
        assert isinstance(path, Path)


# ── _load / _save edge cases ──────────────────────────────────────────────────

class TestManifestIO:
    def test_load_returns_skeleton_when_file_absent(self, registry):
        manifest = registry._load()
        assert manifest["schema_version"] == 1
        assert manifest["active_version"] is None
        assert manifest["versions"] == {}

    def test_load_handles_corrupt_json(self, registry):
        registry._path.write_text("not valid json {{{{")
        manifest = registry._load()
        assert manifest["versions"] == {}

    def test_save_is_atomic(self, registry, artifact):
        registry.register(name="v1", file_path=artifact)
        # Verify the file exists and is valid JSON
        data = json.loads(registry._path.read_text())
        assert "v1" in data["versions"]

    def test_load_migrates_missing_schema_version(self, registry):
        registry._path.write_text(json.dumps({"versions": {}}))
        manifest = registry._load()
        assert manifest["schema_version"] == 1


# ── bootstrap_from_meta ───────────────────────────────────────────────────────

class TestBootstrapFromMeta:
    def test_bootstrap_returns_none_when_artifact_missing(self, registry, tmp_path):
        result = registry.bootstrap_from_meta(
            meta_path=tmp_path / "meta.json",
            model_path=tmp_path / "missing.pkl",
            name="v1",
        )
        assert result is None

    def test_bootstrap_registers_from_meta(self, registry, artifact, tmp_path):
        meta = {
            "oos_accuracy": 0.68,
            "oos_auc": 0.73,
            "oos_p_value": 0.002,
            "sharpe_gate": {"gate_passed": True, "n_trades": 700},
            "feature_count": 40,
        }
        meta_path = tmp_path / "meta.json"
        meta_path.write_text(json.dumps(meta))

        result = registry.bootstrap_from_meta(
            meta_path=meta_path,
            model_path=artifact,
            name="v1",
        )
        assert result is not None
        assert result["name"] == "v1"
        assert result["oos_accuracy"] == pytest.approx(0.68)

    def test_bootstrap_is_noop_when_already_registered(self, registry, artifact, tmp_path):
        registry.register(name="v1", file_path=artifact)
        result = registry.bootstrap_from_meta(
            meta_path=tmp_path / "meta.json",
            model_path=artifact,
            name="v1",
        )
        # Returns existing entry without re-registering
        assert result is not None
        assert result["name"] == "v1"

    def test_bootstrap_handles_corrupt_meta(self, registry, artifact, tmp_path):
        meta_path = tmp_path / "meta.json"
        meta_path.write_text("not json {{")

        result = registry.bootstrap_from_meta(
            meta_path=meta_path,
            model_path=artifact,
            name="v1",
        )
        # Should still register with zero defaults
        assert result is not None

    def test_bootstrap_with_promote_true(self, registry, artifact, tmp_path):
        meta = {
            "oos_accuracy": 0.70,
            "oos_auc": 0.73,
            "oos_p_value": 0.001,
            "sharpe_gate": {"gate_passed": True, "n_trades": 700},
            "feature_count": 40,
        }
        meta_path = tmp_path / "meta.json"
        meta_path.write_text(json.dumps(meta))

        with patch.object(registry, "_update_symlink"), \
             patch.dict("sys.modules", {"ml.performance_monitor": MagicMock(get_monitor=MagicMock(return_value=MagicMock()))}):
            result = registry.bootstrap_from_meta(
                meta_path=meta_path,
                model_path=artifact,
                name="v1",
                promote=True,
            )

        assert result is not None
        assert result["state"] == "production"


# ── sha256_file ───────────────────────────────────────────────────────────────

class TestSha256File:
    def test_sha256_file_returns_hex_string(self, tmp_path):
        from ml.model_registry import sha256_file
        p = tmp_path / "data.bin"
        p.write_bytes(b"hello world")
        digest = sha256_file(p)
        assert len(digest) == 64
        assert all(c in "0123456789abcdef" for c in digest)

    def test_sha256_file_is_deterministic(self, tmp_path):
        from ml.model_registry import sha256_file
        p = tmp_path / "data.bin"
        p.write_bytes(b"deterministic content")
        assert sha256_file(p) == sha256_file(p)


# ── Singleton ─────────────────────────────────────────────────────────────────

class TestSingleton:
    def test_get_registry_returns_same_instance(self):
        import ml.model_registry as mr
        mr._registry = None
        from ml.model_registry import get_registry, ModelRegistry
        a = get_registry()
        b = get_registry()
        assert a is b
        assert isinstance(a, ModelRegistry)

    def test_get_registry_creates_on_first_call(self):
        import ml.model_registry as mr
        mr._registry = None
        from ml.model_registry import get_registry, ModelRegistry
        reg = get_registry()
        assert isinstance(reg, ModelRegistry)

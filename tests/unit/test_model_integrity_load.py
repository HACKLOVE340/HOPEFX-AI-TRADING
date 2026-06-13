# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
tests/unit/test_model_integrity_load.py
=======================================
Regression: AdvancedModelPredictor verifies a registry-tracked model's SHA-256
before joblib.load (pickle = arbitrary code execution). A tracked artifact whose
checksum does not match must be refused (fail closed); untracked paths are
allowed with a warning so dev/test workflows are not broken.
"""

from __future__ import annotations

from ml.live_inference import AdvancedModelPredictor


def test_tracked_model_with_matching_checksum_allowed():
    # Default path is advanced_oos.pkl, which matches its registry entry.
    p = AdvancedModelPredictor()
    assert p._verify_model_integrity() is True


def test_untracked_model_allowed_with_warning(tmp_path):
    rogue = tmp_path / "rogue.pkl"
    rogue.write_bytes(b"not a real model")
    p = AdvancedModelPredictor(model_path=rogue)
    # Not in the registry → cannot verify, but must not block dev workflows.
    assert p._verify_model_integrity() is True


def test_tracked_model_checksum_mismatch_rejected(monkeypatch):
    p = AdvancedModelPredictor()  # tracked path
    # Simulate the on-disk file differing from the registry checksum.
    monkeypatch.setattr("ml.verify_model._sha256", lambda path: "0" * 64)
    assert p._verify_model_integrity() is False

# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
tests/unit/test_ml_package_loading.py
=====================================
`ml/__init__.py` was 443 statements at 46.63 %.

It is the package's model-loading surface: where an artifact directory is
resolved, where a `.pkl` is integrity-checked before it is unpickled, and where
the stacking ensemble is wrapped in an sklearn-shaped interface for the signal
engine. The parts that had no tests are the parts that decide whether the
system serves a model at all, and *which* one.

**The checksum check is a security control, not bookkeeping.** `_try_load`
unpickles whatever `_verify_checksum` approves, so its four outcomes each need
to be right for a different reason: no baseline yet (record and allow — a first
run must not be a hard failure), a new filename (record and allow), an
unreadable baseline (warn and allow — a corrupt sidecar must not take
production offline), and a genuine mismatch (log CRITICAL and **refuse**). Only
the last one may block, and it must block.

**Checksums are per directory.** They were once a single file covering the
packaged models, which held only while the packaged directory was the sole read
location. Once `ML_MODEL_DIR` became real, a retrained `advanced_oos.pkl` there
had the same *name* and different bytes, so it was rejected as tampering — a
path change reported as a security incident. That is pinned here.

**`_saved` is a seam.** Tests and callers reassign it to point the package at a
specific directory; an earlier version delegated to a resolver that never
consulted it, so redirection silently stopped working and isolated fixtures
read the committed models instead.
"""

from __future__ import annotations

import hashlib
import json
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

import ml as ml_pkg
from ml import StackingEnsemblePredictor

pytestmark = pytest.mark.unit


@pytest.fixture
def model_dir(tmp_path, monkeypatch):
    """An isolated artifact directory wired into the package's seams."""
    d = tmp_path / "models"
    d.mkdir()
    monkeypatch.setattr(ml_pkg, "_SAVED", d)
    monkeypatch.setattr(ml_pkg, "_ENV_RESOLVED", d)
    monkeypatch.setattr(ml_pkg, "_PACKAGED", d)
    return d


def _write(directory, name="advanced_oos.pkl", data=b"model-bytes"):
    path = directory / name
    path.write_bytes(data)
    return path


def _baseline(directory, **entries):
    (directory / "model_checksums.json").write_text(json.dumps(entries, indent=2))


# ── directory resolution ──────────────────────────────────────────────────────


class TestChecksumFileLocation:
    def test_the_baseline_lives_beside_the_models_it_describes(self, tmp_path):
        assert ml_pkg._checksum_file_for(tmp_path) == tmp_path / "model_checksums.json"

    def test_two_directories_get_two_baselines(self, tmp_path):
        """One shared baseline made a retrained model look like tampering."""
        a, b = tmp_path / "packaged", tmp_path / "configured"

        assert ml_pkg._checksum_file_for(a) != ml_pkg._checksum_file_for(b)


class TestSavedSeam:
    def test_it_resolves_under_the_reassigned_directory(self, model_dir):
        _write(model_dir, "thing.pkl")

        assert ml_pkg._saved("thing.pkl") == model_dir / "thing.pkl"

    def test_a_missing_artifact_still_resolves_to_the_seam_directory(self, model_dir):
        """Callers get a path to probe, not a silent redirect elsewhere."""
        assert ml_pkg._saved("absent.pkl").parent == model_dir

    def test_a_configured_directory_falls_back_to_the_packaged_copy(self, tmp_path, monkeypatch):
        """A pod whose ML_MODEL_DIR is empty must not end up with no model."""
        configured, packaged = tmp_path / "configured", tmp_path / "packaged"
        configured.mkdir()
        packaged.mkdir()
        _write(packaged, "advanced_oos.pkl")
        monkeypatch.setattr(ml_pkg, "_SAVED", configured)
        monkeypatch.setattr(ml_pkg, "_ENV_RESOLVED", configured)
        monkeypatch.setattr(ml_pkg, "_PACKAGED", packaged)

        assert ml_pkg._saved("advanced_oos.pkl") == packaged / "advanced_oos.pkl"

    def test_a_deliberately_reassigned_seam_does_not_fall_back(self, tmp_path, monkeypatch):
        """Reassigning _SAVED means 'read here and nowhere else'."""
        isolated, packaged = tmp_path / "isolated", tmp_path / "packaged"
        isolated.mkdir()
        packaged.mkdir()
        _write(packaged, "advanced_oos.pkl")
        monkeypatch.setattr(ml_pkg, "_SAVED", isolated)
        monkeypatch.setattr(ml_pkg, "_ENV_RESOLVED", tmp_path / "configured")
        monkeypatch.setattr(ml_pkg, "_PACKAGED", packaged)

        assert ml_pkg._saved("advanced_oos.pkl") == isolated / "advanced_oos.pkl"


# ── hashing ───────────────────────────────────────────────────────────────────


class TestSha256:
    def test_it_matches_hashlib(self, tmp_path):
        path = tmp_path / "f.bin"
        path.write_bytes(b"hello world")

        assert ml_pkg._sha256(path) == hashlib.sha256(b"hello world").hexdigest()

    def test_it_is_stable_across_calls(self, tmp_path):
        path = tmp_path / "f.bin"
        path.write_bytes(b"abc")

        assert ml_pkg._sha256(path) == ml_pkg._sha256(path)

    def test_different_bytes_hash_differently(self, tmp_path):
        a, b = tmp_path / "a", tmp_path / "b"
        a.write_bytes(b"one")
        b.write_bytes(b"two")

        assert ml_pkg._sha256(a) != ml_pkg._sha256(b)

    def test_a_file_larger_than_the_read_buffer_hashes_correctly(self, tmp_path):
        """It reads in 64 KiB chunks; a single-shot hash must agree."""
        blob = b"x" * (65536 * 3 + 17)
        path = tmp_path / "big.bin"
        path.write_bytes(blob)

        assert ml_pkg._sha256(path) == hashlib.sha256(blob).hexdigest()

    def test_an_empty_file_hashes_to_the_empty_digest(self, tmp_path):
        path = tmp_path / "empty"
        path.write_bytes(b"")

        assert ml_pkg._sha256(path) == hashlib.sha256(b"").hexdigest()


# ── the integrity gate ────────────────────────────────────────────────────────


class TestVerifyChecksum:
    def test_no_baseline_records_one_and_allows(self, model_dir):
        """A first run must not be a hard failure."""
        path = _write(model_dir)

        assert ml_pkg._verify_checksum(path) is True
        assert (model_dir / "model_checksums.json").exists()

    def test_the_recorded_baseline_matches_the_file(self, model_dir):
        path = _write(model_dir)
        ml_pkg._verify_checksum(path)

        stored = json.loads((model_dir / "model_checksums.json").read_text())

        assert stored[path.name] == ml_pkg._sha256(path)

    def test_a_matching_file_passes(self, model_dir):
        path = _write(model_dir)
        _baseline(model_dir, **{path.name: ml_pkg._sha256(path)})

        assert ml_pkg._verify_checksum(path) is True

    def test_a_tampered_file_is_refused(self, model_dir):
        """The one outcome that must block."""
        path = _write(model_dir, data=b"original")
        _baseline(model_dir, **{path.name: ml_pkg._sha256(path)})
        path.write_bytes(b"tampered")

        assert ml_pkg._verify_checksum(path) is False

    def test_a_tampered_file_is_reported_at_critical(self, model_dir, caplog):
        import logging

        path = _write(model_dir, data=b"original")
        _baseline(model_dir, **{path.name: ml_pkg._sha256(path)})
        path.write_bytes(b"tampered")

        with caplog.at_level(logging.CRITICAL):
            ml_pkg._verify_checksum(path)

        assert any("MODEL INTEGRITY FAILURE" in r.message for r in caplog.records)

    def test_a_filename_absent_from_the_baseline_is_recorded_and_allowed(self, model_dir):
        _baseline(model_dir, **{"other.pkl": "deadbeef"})
        path = _write(model_dir, "brand_new.pkl")

        assert ml_pkg._verify_checksum(path) is True

    def test_an_unreadable_baseline_warns_and_allows(self, model_dir):
        """A corrupt sidecar must not take model serving offline."""
        path = _write(model_dir)
        (model_dir / "model_checksums.json").write_text("{ not json")

        assert ml_pkg._verify_checksum(path) is True

    def test_two_directories_do_not_share_a_baseline(self, tmp_path):
        """Same filename, different bytes, different directories — both valid."""
        packaged, configured = tmp_path / "packaged", tmp_path / "configured"
        packaged.mkdir()
        configured.mkdir()
        p1 = _write(packaged, "advanced_oos.pkl", b"packaged-bytes")
        p2 = _write(configured, "advanced_oos.pkl", b"retrained-bytes")

        assert ml_pkg._verify_checksum(p1) is True
        assert ml_pkg._verify_checksum(p2) is True

    def test_a_retrained_model_is_not_reported_as_tampering(self, tmp_path):
        packaged, configured = tmp_path / "packaged", tmp_path / "configured"
        packaged.mkdir()
        configured.mkdir()
        _write(packaged, "advanced_oos.pkl", b"packaged-bytes")
        ml_pkg._verify_checksum(packaged / "advanced_oos.pkl")
        retrained = _write(configured, "advanced_oos.pkl", b"retrained-bytes")

        assert ml_pkg._verify_checksum(retrained) is True


class TestRecordChecksums:
    def test_it_records_every_pkl_in_the_directory(self, model_dir):
        _write(model_dir, "a.pkl")
        _write(model_dir, "b.pkl")

        ml_pkg._record_checksums(model_dir)

        stored = json.loads((model_dir / "model_checksums.json").read_text())
        assert set(stored) == {"a.pkl", "b.pkl"}

    def test_it_ignores_non_pkl_files(self, model_dir):
        _write(model_dir, "a.pkl")
        (model_dir / "notes.txt").write_text("hello")
        (model_dir / "model.zip").write_bytes(b"zip")

        ml_pkg._record_checksums(model_dir)

        assert set(json.loads((model_dir / "model_checksums.json").read_text())) == {"a.pkl"}

    def test_an_empty_directory_records_an_empty_baseline(self, model_dir):
        ml_pkg._record_checksums(model_dir)

        assert json.loads((model_dir / "model_checksums.json").read_text()) == {}

    def test_an_unwritable_directory_is_survivable(self, tmp_path):
        """Read-only model volumes are a normal container arrangement."""
        ml_pkg._record_checksums(tmp_path / "does-not-exist")

    def test_the_baseline_is_valid_json(self, model_dir):
        _write(model_dir, "a.pkl")
        ml_pkg._record_checksums(model_dir)

        json.loads((model_dir / "model_checksums.json").read_text())


class TestTryLoad:
    def test_a_missing_file_yields_nothing(self, model_dir):
        assert ml_pkg._try_load(model_dir / "absent.pkl") is None

    def test_a_tampered_file_is_never_unpickled(self, model_dir):
        """The integrity gate has to run before deserialisation, not after."""
        import joblib

        path = model_dir / "m.pkl"
        joblib.dump({"a": 1}, path)
        _baseline(model_dir, **{"m.pkl": "0" * 64})

        assert ml_pkg._try_load(path) is None

    def test_a_valid_artifact_loads(self, model_dir):
        import joblib

        path = model_dir / "m.pkl"
        joblib.dump({"marker": "value"}, path)

        assert ml_pkg._try_load(path) == {"marker": "value"}

    def test_an_unreadable_artifact_yields_nothing_rather_than_raising(self, model_dir):
        path = model_dir / "m.pkl"
        path.write_bytes(b"not a pickle or a joblib file")

        assert ml_pkg._try_load(path) is None


# ── the stacking ensemble wrapper ─────────────────────────────────────────────


class _Base:
    """A base learner returning a fixed P(up)."""

    def __init__(self, p=0.7):
        self.p = p

    def predict_proba(self, X):
        n = X.shape[0] if hasattr(X, "shape") else len(X)
        return np.column_stack([np.full(n, 1 - self.p), np.full(n, self.p)])


class _Meta:
    """A meta-learner echoing the mean of its inputs as P(up)."""

    def predict_proba(self, X):
        p = np.asarray(X).mean(axis=1)
        return np.column_stack([1 - p, p])


def _payload(**over):
    base = {
        "base_learners": [_Base(0.7), _Base(0.9)],
        "meta_model": _Meta(),
        "feature_cols": ["rsi", "atr"],
        "scaler": None,
        "horizon": 5,
        "abstain_threshold": 0.55,
    }
    base.update(over)
    return base


class TestStackingEnsemblePredictor:
    def test_predict_proba_returns_the_sklearn_shape(self):
        predictor = StackingEnsemblePredictor(_payload())

        proba = predictor.predict_proba(pd.DataFrame({"rsi": [50.0], "atr": [1.0]}))

        assert proba.shape == (1, 2)

    def test_the_columns_sum_to_one(self):
        predictor = StackingEnsemblePredictor(_payload())

        proba = predictor.predict_proba(pd.DataFrame({"rsi": [50.0], "atr": [1.0]}))

        assert proba.sum(axis=1)[0] == pytest.approx(1.0)

    def test_a_missing_feature_column_is_filled_rather_than_raising(self):
        """Feature sets drift between training and serving; 0.0 is the scaled default."""
        predictor = StackingEnsemblePredictor(_payload())

        proba = predictor.predict_proba(pd.DataFrame({"rsi": [50.0]}))

        assert proba.shape == (1, 2)

    def test_the_caller_s_frame_is_not_mutated(self):
        predictor = StackingEnsemblePredictor(_payload())
        frame = pd.DataFrame({"rsi": [50.0]})

        predictor.predict_proba(frame)

        assert list(frame.columns) == ["rsi"]

    def test_extra_columns_are_dropped_to_the_training_order(self):
        predictor = StackingEnsemblePredictor(_payload())

        proba = predictor.predict_proba(pd.DataFrame({"atr": [1.0], "unexpected": [9.0], "rsi": [50.0]}))

        assert proba.shape == (1, 2)

    def test_infinities_and_nans_are_neutralised(self):
        predictor = StackingEnsemblePredictor(_payload())

        proba = predictor.predict_proba(pd.DataFrame({"rsi": [np.inf], "atr": [np.nan]}))

        assert np.all(np.isfinite(proba))

    def test_a_raw_array_input_is_accepted(self):
        predictor = StackingEnsemblePredictor(_payload())

        assert predictor.predict_proba(np.zeros((3, 2))).shape == (3, 2)

    def test_a_failing_base_learner_is_replaced_with_a_neutral_vote(self):
        """One broken learner must not silence the ensemble."""
        broken = SimpleNamespace(predict_proba=lambda X: (_ for _ in ()).throw(RuntimeError("boom")))
        predictor = StackingEnsemblePredictor(_payload(base_learners=[broken, _Base(1.0)]))

        proba = predictor.predict_proba(np.zeros((2, 2)))

        assert proba[:, 1] == pytest.approx([0.75, 0.75])

    def test_a_failing_scaler_does_not_stop_the_prediction(self):
        scaler = SimpleNamespace(transform=lambda X: (_ for _ in ()).throw(RuntimeError("scaler mismatch")))
        predictor = StackingEnsemblePredictor(_payload(scaler=scaler))

        assert predictor.predict_proba(np.zeros((1, 2))).shape == (1, 2)

    def test_a_working_scaler_is_applied(self):
        seen = {}

        def _transform(X):
            seen["called"] = True
            return np.asarray(X)

        predictor = StackingEnsemblePredictor(_payload(scaler=SimpleNamespace(transform=_transform)))
        predictor.predict_proba(np.zeros((1, 2)))

        assert seen.get("called") is True

    def test_predict_thresholds_at_a_half(self):
        up = StackingEnsemblePredictor(_payload(base_learners=[_Base(0.9)]))
        down = StackingEnsemblePredictor(_payload(base_learners=[_Base(0.1)]))

        assert up.predict(np.zeros((1, 2)))[0] == 1
        assert down.predict(np.zeros((1, 2)))[0] == 0

    def test_predict_returns_one_label_per_row(self):
        predictor = StackingEnsemblePredictor(_payload())

        assert predictor.predict(np.zeros((4, 2))).shape == (4,)

    def test_the_horizon_and_threshold_are_exposed(self):
        predictor = StackingEnsemblePredictor(_payload(horizon=12, abstain_threshold=0.62))

        assert predictor.horizon == 12
        assert predictor.abstain_threshold == pytest.approx(0.62)

    def test_they_fall_back_to_documented_defaults(self):
        predictor = StackingEnsemblePredictor({"base_learners": [_Base()], "meta_model": _Meta()})

        assert predictor.horizon == 5
        assert predictor.abstain_threshold == pytest.approx(0.55)

    def test_the_repr_summarises_the_ensemble(self):
        text = repr(StackingEnsemblePredictor(_payload()))

        assert "n_base=2" in text
        assert "features=2" in text
        assert "horizon=5" in text

    def test_a_payload_without_base_learners_is_rejected_at_construction(self):
        with pytest.raises(KeyError):
            StackingEnsemblePredictor({"meta_model": _Meta()})


# ── the public accessors ──────────────────────────────────────────────────────


class TestPublicAccessors:
    def test_the_active_model_accessor_is_callable(self):
        ml_pkg.get_active_model()

    def test_the_version_accessor_returns_a_string(self):
        assert isinstance(ml_pkg.get_model_version(), str)

    def test_the_version_is_never_empty(self):
        assert ml_pkg.get_model_version() != ""

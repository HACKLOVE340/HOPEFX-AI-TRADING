# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""Every ML loader here must refuse an artifact whose bytes changed under it.

`ml/__init__.py::_verify_checksum` reads the per-directory
``model_checksums.json`` on every load and is fail-closed in production. Twelve
modules under `ml/` called `joblib.load` / `PPO.load` straight past it
(`python scripts/model_provenance_report.py`), so for those the manifest was a
record nobody consulted — and `joblib.load` on a pickle is arbitrary code
execution, not merely a wrong prediction.

Every test below does the same thing, and the shape matters:

1. write a REAL artifact and a manifest recording its real sha256 — the
   positive control, so a loader that refuses everything cannot pass;
2. append one byte to the artifact and assert the load is REFUSED;
3. assert the corrupted artifact is still perfectly loadable by `joblib.load`.

Step 3 is what makes step 2 mean anything. A pickle ignores trailing bytes, so
the corrupted file unpickles to the same object — the only thing that can refuse
it is the checksum gate. Without step 3 this suite would pass against a loader
that merely crashed on a malformed file.

The mismatch branch of `_verify_checksum` has no bootstrap escape, so these
assertions hold in every APP_ENV, which is why the tests do not set one.
"""

from __future__ import annotations

import json
from pathlib import Path

import joblib
import pytest

pytestmark = pytest.mark.unit


# ── harness ───────────────────────────────────────────────────────────────────


def _sha256(path: Path) -> str:
    import hashlib

    return hashlib.sha256(path.read_bytes()).hexdigest()


def _artifact(directory: Path, name: str, payload: object) -> Path:
    """A real artifact in *directory*, recorded in that directory's manifest."""
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    joblib.dump(payload, path)
    manifest = directory / "model_checksums.json"
    stored = json.loads(manifest.read_text()) if manifest.exists() else {}
    stored[name] = _sha256(path)
    manifest.write_text(json.dumps(stored, indent=2))
    return path


def _corrupt(path: Path) -> None:
    """Change the bytes without breaking the pickle.

    A pickle stops at its STOP opcode, so a trailing byte leaves the file
    loadable and only the recorded digest disagrees. That is the whole point:
    the refusal must come from the gate, not from a load that would have failed
    anyway.
    """
    path.write_bytes(path.read_bytes() + b"\x00")


def test_the_harness_corrupts_without_breaking_the_pickle(tmp_path: Path):
    """The assumption every test below rests on, asserted rather than assumed."""
    path = _artifact(tmp_path, "m.pkl", {"hello": "world"})
    _corrupt(path)

    assert joblib.load(path) == {"hello": "world"}
    assert _sha256(path) != json.loads((tmp_path / "model_checksums.json").read_text())["m.pkl"]


def test_verify_checksum_refuses_the_corrupted_file(tmp_path: Path):
    """The gate itself, so a failure below localises to the wiring, not the gate."""
    import ml

    path = _artifact(tmp_path, "m.pkl", {"hello": "world"})
    assert ml._verify_checksum(path) is True

    _corrupt(path)
    assert ml._verify_checksum(path) is False


# ── ml/models/base.py ─────────────────────────────────────────────────────────


def _concrete_model():
    from ml.models.base import BaseMLModel

    class _Model(BaseMLModel):
        def build(self) -> None:
            self.model = {"weights": [1, 2, 3]}

        def train(self, *a, **k):
            return {}

        def predict(self, *a, **k):
            return []

    return _Model("probe")


def test_base_model_load_refuses_a_corrupted_artifact(tmp_path: Path):
    path = _artifact(
        tmp_path,
        "m.pkl",
        {"model": {"w": 1}, "config": {}, "is_trained": True, "training_history": []},
    )

    ok = _concrete_model()
    ok.load(str(path))
    assert ok.model == {"w": 1}

    _corrupt(path)
    refused = _concrete_model()
    with pytest.raises(ValueError, match="integrity"):
        refused.load(str(path))
    assert refused.model is None


# ── ml/pipeline.py ────────────────────────────────────────────────────────────


def test_xgboost_predictor_load_refuses_a_corrupted_artifact(tmp_path: Path):
    from ml.pipeline import XGBoostPredictor

    path = _artifact(tmp_path, "xgb.pkl", {"model": "M", "scaler": "S", "features": ["a"]})

    ok = XGBoostPredictor()
    ok.load(str(path))
    assert ok._model == "M"

    _corrupt(path)
    refused = XGBoostPredictor()
    with pytest.raises(ValueError, match="integrity"):
        refused.load(str(path))
    assert refused._model is None


# ── ml/regime_conditional.py ──────────────────────────────────────────────────


def _regime_conditional_payload() -> dict:
    return {
        "regime_models": {},
        "global_model": None,
        "regime_counts": {},
        "feature_names": ["a"],
        "hurst_col": "hurst",
        "adx_col": "adx",
    }


def test_regime_conditional_load_refuses_a_corrupted_artifact(tmp_path: Path):
    from ml.regime_conditional import RegimeConditionalModel

    path = _artifact(tmp_path, "rc.pkl", _regime_conditional_payload())

    assert RegimeConditionalModel.load(str(path))._feature_names == ["a"]

    _corrupt(path)
    with pytest.raises(ValueError, match="integrity"):
        RegimeConditionalModel.load(str(path))


# ── ml/regime.py ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_regime_detector_load_refuses_a_corrupted_artifact(tmp_path: Path):
    pytest.importorskip("hmmlearn")
    from ml.regime import RegimeDetector

    path = _artifact(tmp_path, "regime_hmm.pkl", {"hmm": "H", "vol_gmm": "G", "regime_map": {}})

    ok = RegimeDetector(model_path=path)
    await ok.load()
    assert ok._is_fitted is True

    _corrupt(path)
    refused = RegimeDetector(model_path=path)
    await refused.load()
    assert refused._is_fitted is False, "a refused artifact must not leave the detector claiming it is fitted"
    assert refused.hmm != "H"


# ── ml/robust_predictor.py ────────────────────────────────────────────────────


def test_robust_predictor_load_refuses_a_corrupted_manifest(tmp_path: Path):
    from ml.robust_predictor import RobustPredictor

    state = {
        "config": RobustPredictor().config,
        "selected_features": ["a"],
        "feature_importance_history": [],
        "last_retrain": None,
        "saved_members": {},
        "meta_model_path": None,
        "thresholds": {},
        "thresholds_calibrated": False,
    }
    path = _artifact(tmp_path, "state.joblib", state)

    ok = RobustPredictor()
    ok.load(str(tmp_path))
    assert ok.selected_features == ["a"]

    _corrupt(path)
    refused = RobustPredictor()
    with pytest.raises(ValueError, match="integrity"):
        refused.load(str(tmp_path))


def test_robust_predictor_drops_an_ensemble_member_that_fails_integrity(tmp_path: Path):
    """A refused member must not silently become a smaller ensemble that claims to be whole."""
    from ml.robust_predictor import RobustPredictor

    member = _artifact(tmp_path, "member_rf.joblib", {"kind": "rf"})
    state = {
        "config": RobustPredictor().config,
        "selected_features": ["a"],
        "feature_importance_history": [],
        "last_retrain": None,
        "saved_members": {"rf": str(member)},
        "meta_model_path": None,
        "thresholds": {},
        "thresholds_calibrated": False,
    }
    _artifact(tmp_path, "state.joblib", state)

    ok = RobustPredictor()
    ok.load(str(tmp_path))
    assert ok.models["rf"] == {"kind": "rf"}

    _corrupt(member)
    refused = RobustPredictor()
    refused.load(str(tmp_path))
    assert "rf" not in refused.models


# ── ml/inference_engine.py ────────────────────────────────────────────────────


def test_inference_engine_calibrator_refuses_a_corrupted_artifact(tmp_path: Path, monkeypatch):
    import ml
    import ml.inference_engine as ie

    path = _artifact(tmp_path, "isotonic_calibrator.pkl", {"kind": "isotonic"})
    monkeypatch.setattr(ml, "_SAVED", tmp_path, raising=False)
    monkeypatch.setattr(ie, "_saved", lambda name: tmp_path / name, raising=False)

    engine = ie.InferenceEngine.__new__(ie.InferenceEngine)
    engine._calibrator = None
    assert engine._load_calibrator() == {"kind": "isotonic"}

    _corrupt(path)
    refused = ie.InferenceEngine.__new__(ie.InferenceEngine)
    refused._calibrator = None
    assert refused._load_calibrator() is None


# ── ml/live_inference.py ──────────────────────────────────────────────────────


def test_live_inference_load_refuses_a_corrupted_artifact(tmp_path: Path):
    from ml.live_inference import AdvancedModelPredictor

    path = _artifact(tmp_path, "advanced_oos.pkl", {"kind": "pipeline"})

    ok = AdvancedModelPredictor(model_path=path)
    assert ok._load() is True

    _corrupt(path)
    refused = AdvancedModelPredictor(model_path=path)
    assert refused._load() is False
    assert refused._model is None


# ── ml/explainability.py ──────────────────────────────────────────────────────


def test_explainability_load_refuses_a_corrupted_artifact(tmp_path: Path, monkeypatch):
    import ml.explainability as ex

    path = _artifact(tmp_path, "probe_model.pkl", {"kind": "rf"})
    monkeypatch.setattr(ex, "_MODEL_DIR", tmp_path, raising=False)

    assert ex._load_model("probe_model") == {"kind": "rf"}

    _corrupt(path)
    assert ex._load_model("probe_model") is None


# ── ml/rl_agent.py ────────────────────────────────────────────────────────────


def test_rl_agent_load_refuses_a_corrupted_policy(tmp_path: Path, caplog):
    """The PPO zip is not a pickle, so the gate must run BEFORE stable-baselines3.

    This one cannot assert on the return value. `RLAgent.load` already returns
    False when stable-baselines3 is absent, so `is False` would be satisfied by
    a module with no gate at all — the false green this suite exists to avoid.
    What distinguishes them is WHICH refusal was logged, so that is what is
    asserted, in both directions: an intact policy must NOT produce an integrity
    refusal, a corrupted one must.
    """
    import logging

    from ml.rl_agent import RLAgent

    path = _artifact(tmp_path, "hopefx_ppo.zip", {"policy": "weights"})

    agent = RLAgent()
    agent.model_path = path
    with caplog.at_level(logging.ERROR, logger="ml.rl_agent"):
        agent.load()
    assert "integrity" not in caplog.text.lower(), "the intact policy must not be refused"

    caplog.clear()
    _corrupt(path)
    with caplog.at_level(logging.ERROR, logger="ml.rl_agent"):
        assert agent.load() is False
    assert "integrity" in caplog.text.lower()
    assert agent._model is None


# ── ml/__init__.py::_record_checksums ─────────────────────────────────────────


def test_bootstrapping_a_directory_records_every_artifact_kind(tmp_path: Path):
    """A `.zip` policy must be baselined too, or the gate can never latch on it.

    `_record_checksums` globbed `*.pkl` only. In a bootstrap-allowed directory
    the sequence for a `.zip` was: not listed -> record (which writes no `.zip`
    entry) -> allow. On the next load, still not listed -> record -> allow.
    The refusal branch was unreachable for every artifact this repository does
    not name `.pkl`, for the life of the module.

    The evidence is committed: `ml/saved_models/rl/model_checksums.json` is `{}`
    beside a 189 KB `hopefx_ppo.zip`, which is what that loop writes.
    """
    import ml

    policy = tmp_path / "policy.zip"
    policy.write_bytes(b"PK\x03\x04 pretend this is a stable-baselines3 policy")
    assert not (tmp_path / "model_checksums.json").exists()

    # First load bootstraps the baseline from what is on disk, and allows.
    assert ml._verify_checksum(policy) is True
    recorded = json.loads((tmp_path / "model_checksums.json").read_text())
    assert "policy.zip" in recorded, "a baseline that skips the artifact cannot ever refuse it"

    # Which means the SECOND load, after the bytes change, must refuse.
    _corrupt(policy)
    assert ml._verify_checksum(policy) is False


# ── ml/advanced_ai.py ─────────────────────────────────────────────────────────


def test_ppo_rl_agent_load_refuses_a_corrupted_policy(tmp_path: Path):
    """`PPO.load` unpickles the policy out of the zip, so the gate runs first.

    stable-baselines3 is not installed here, which is what makes this provable:
    with no gate the call reaches `PPO.load` on a `None` and raises TypeError,
    and with the gate it raises ValueError naming the integrity check. Asserting
    the exception TYPE is what keeps the two apart.

    The intact policy is the positive control: it must get past the gate and
    fail on stable-baselines3 instead.
    """
    import ml.advanced_ai as aa

    path = _artifact(tmp_path, "ppo_hopefx.zip", {"policy": "weights"})
    agent = aa.PPORLAgent.__new__(aa.PPORLAgent)

    try:
        agent.load(str(path))
    except ValueError as exc:  # pragma: no cover - only reached if the gate is wrong
        pytest.fail(f"the intact policy must get past the gate, not be refused: {exc}")
    except Exception:
        pass  # stable-baselines3 is absent; getting this far means the gate allowed it

    _corrupt(path)
    with pytest.raises(ValueError, match="integrity"):
        agent.load(str(path))


def test_ppo_rl_agent_gates_the_extensionless_path_sb3_actually_saves(tmp_path: Path):
    """`save()` hands stable-baselines3 a path with no suffix and it appends `.zip`.

    A gate that hashed the literal argument would find no file, bootstrap a
    baseline and allow — checking a file that is not the one being loaded.
    """
    import ml.advanced_ai as aa

    path = _artifact(tmp_path, "ppo_hopefx.zip", {"policy": "weights"})
    _corrupt(path)

    agent = aa.PPORLAgent.__new__(aa.PPORLAgent)
    with pytest.raises(ValueError, match="integrity"):
        agent.load(str(tmp_path / "ppo_hopefx"))


def test_rag_metadata_load_refuses_a_corrupted_artifact(tmp_path: Path):
    import ml.advanced_ai as aa

    path = _artifact(tmp_path, "metadata.pkl", {"headlines": ["a"], "scores": [1.0]})
    rag = aa.VectorRAGNewsSentiment.__new__(aa.VectorRAGNewsSentiment)
    rag._stored_headlines = []
    rag._stored_scores = []

    rag.load(str(tmp_path))
    assert rag._stored_headlines == ["a"]

    _corrupt(path)
    refused = aa.VectorRAGNewsSentiment.__new__(aa.VectorRAGNewsSentiment)
    refused._stored_headlines = []
    refused._stored_scores = []
    refused.load(str(tmp_path))
    assert refused._stored_headlines == [], "refused metadata must not reach the store"

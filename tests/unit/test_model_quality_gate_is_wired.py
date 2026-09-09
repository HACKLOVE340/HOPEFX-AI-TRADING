# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""`ml/model_quality_gate.py` had no caller. Now it has the right one.

The module is well built: `ModelQualityGate.require_pass()` raises rather than
returning a falsy result, `evaluate()` treats a missing score as a FAILURE
rather than a zero, and every refusal carries a reason code. It was invoked by
nothing — only its own tests. A fail-closed gate nobody calls is the shape this
repository keeps finding, and it is worse than no gate, because it reads to a
reviewer as though model quality is checked.

## It was pointed at the wrong place first

The obvious guess is `ml/model_registry.py::promote()` — model quality, model
promotion. That is wrong, and the module's own docstring says so: it exists to
be consulted *"before a candidate reaches paper or live execution"*. That is
the inference path, not the promotion path. Registry promotion already has its
own gate (OOS accuracy, p-value, Sharpe, PnL reconciliation); this one is about
whether a *prediction* can be trusted right now.

## The three signals already existed, judged ad hoc

`ml/inference_engine.py::predict()` was already making all three judgements
inline, as strings in an evidence blob, with a bare `0.3` for the threshold:

    "calibration_state":  "isotonic" if self._calibrator is not None else "raw",
    "drift_state":        "detected" if drift else "clear_or_unavailable",
    "data_quality_state": "valid" if data_quality >= 0.3 else "degraded",

and `data_quality` itself is computed under a comment reading "for downstream
gating" — then used only to set a Prometheus gauge. Nothing gated on it.

So the wiring replaces three hand-rolled judgements with the component built to
make them, and every threshold is taken from a value this file was already
using (`_DRIFT_Z_THRESHOLD`, and the `0.3` now named rather than inline). None
is invented, which matters: a gate configured with numbers nobody chose is a
gate that fails at a boundary nobody agreed to.

## What is deliberately NOT changed here

Whether a failing snapshot stops a trade. It is recorded and exposed by
default, and refuses only under `MODEL_QUALITY_BLOCK=true` — the same shape as
the existing `DRIFT_BLOCK`. Silently changing when this system declines to
trade is not a side effect a wiring commit gets to have; that is the owner's
call, and it is tracked separately alongside the `DRIFT_BLOCK` default.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit


def _engine():
    """An engine instance without loading models — only the gate path is under test."""
    from ml.inference_engine import InferenceEngine

    return InferenceEngine.__new__(InferenceEngine)


class TestTheGateHasAProductionCaller:
    def test_something_outside_its_own_module_and_tests_imports_it(self) -> None:
        # Parsed, not grepped: a substring search for "ModelQualityGate" would
        # also match this docstring and the module's own definition.
        import ast
        import pathlib

        repo = pathlib.Path(__file__).resolve().parents[2]
        callers = []
        for path in repo.rglob("*.py"):
            rel = path.relative_to(repo).as_posix()
            if rel.startswith(("tests/", ".venv/")) or "__pycache__" in rel:
                continue
            if rel == "ml/model_quality_gate.py":
                continue
            try:
                tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and (node.module or "").endswith("model_quality_gate"):
                    callers.append(rel)
                    break

        assert callers, "nothing in production imports ml.model_quality_gate — the gate is still dead"


class TestPredictActuallyRunsIt:
    """Methods existing is not the gate running.

    The first version of this file proved `_evaluate_model_quality` and
    `_enforce_model_quality` behaved correctly and that something imported the
    module — all of which was true while `predict()` still called neither. That
    is the same "registration is not execution" gap the agent sweep hit one
    commit earlier, so it is asserted here directly.
    """

    def test_predict_calls_both_the_evaluation_and_the_enforcement(self) -> None:
        import ast
        import inspect
        import textwrap

        from ml.inference_engine import InferenceEngine

        source = textwrap.dedent(inspect.getsource(InferenceEngine.predict))
        called = {
            node.func.attr
            for node in ast.walk(ast.parse(source))
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        }
        assert "_evaluate_model_quality" in called, "predict() never evaluates model quality"
        assert "_enforce_model_quality" in called, "predict() evaluates quality and never acts on it"

    def test_the_evidence_payload_carries_the_gates_verdict(self) -> None:
        import inspect

        from ml.inference_engine import InferenceEngine

        source = inspect.getsource(InferenceEngine.predict)
        assert "model_quality_passed" in source
        assert "model_quality_reasons" in source


class TestTheScoresComeFromRealSignals:
    def test_a_missing_calibrator_scores_zero_not_one(self) -> None:
        # isotonic_calibrator.pkl does not exist in this tree, so every
        # prediction today is served from a raw, uncalibrated probability and
        # nothing says so. The gate is what says so.
        engine = _engine()
        engine._calibrator = None
        snapshot = engine._evaluate_model_quality(drift_z=0.0, data_quality=1.0)
        assert snapshot is not None
        assert snapshot.calibration_score == 0.0

    def test_a_loaded_calibrator_scores_one(self) -> None:
        engine = _engine()
        engine._calibrator = object()
        snapshot = engine._evaluate_model_quality(drift_z=0.0, data_quality=1.0)
        assert snapshot is not None
        assert snapshot.calibration_score == 1.0

    def test_drift_above_the_engines_own_threshold_fails(self) -> None:
        from ml.inference_engine import _DRIFT_Z_THRESHOLD

        engine = _engine()
        engine._calibrator = object()
        snapshot = engine._evaluate_model_quality(drift_z=_DRIFT_Z_THRESHOLD + 1.0, data_quality=1.0)
        assert snapshot is not None
        assert snapshot.drift_ok is False
        assert not snapshot.passed

    def test_drift_below_the_threshold_passes(self) -> None:
        from ml.inference_engine import _DRIFT_Z_THRESHOLD

        engine = _engine()
        engine._calibrator = object()
        snapshot = engine._evaluate_model_quality(drift_z=_DRIFT_Z_THRESHOLD - 1.0, data_quality=1.0)
        assert snapshot is not None
        assert snapshot.drift_ok is True

    def test_degraded_data_quality_fails(self) -> None:
        engine = _engine()
        engine._calibrator = object()
        snapshot = engine._evaluate_model_quality(drift_z=0.0, data_quality=0.1)
        assert snapshot is not None
        assert snapshot.data_quality_ok is False
        assert "DATA_QUALITY_UNAVAILABLE_OR_BELOW_THRESHOLD" in snapshot.reason_codes

    def test_an_unmeasured_drift_score_is_absent_not_zero(self) -> None:
        # Rule 2. `None` must not be read as "no drift" — the gate's own
        # evaluate() already treats a missing score as a failure, and the
        # wiring must pass the absence through rather than substituting 0.0.
        engine = _engine()
        engine._calibrator = object()
        snapshot = engine._evaluate_model_quality(drift_z=None, data_quality=1.0)
        assert snapshot is not None
        assert snapshot.drift_ok is False


class TestBlockingIsOptOutAndFailsClosed:
    def test_by_default_a_failing_snapshot_does_not_raise(self, monkeypatch) -> None:
        # Today's behaviour: degraded quality is recorded, not refused.
        # Changing that is the owner's decision, not a side effect of wiring.
        import ml.inference_engine as ie

        monkeypatch.setattr(ie, "_MODEL_QUALITY_BLOCK", False)
        engine = _engine()
        engine._calibrator = None
        snapshot = engine._evaluate_model_quality(drift_z=999.0, data_quality=0.0)
        assert snapshot is not None
        assert not snapshot.passed
        # No exception: the caller decides.
        engine._enforce_model_quality(snapshot)

    def test_with_blocking_enabled_a_failing_snapshot_raises(self, monkeypatch) -> None:
        import ml.inference_engine as ie

        monkeypatch.setattr(ie, "_MODEL_QUALITY_BLOCK", True)
        engine = _engine()
        engine._calibrator = None
        snapshot = engine._evaluate_model_quality(drift_z=999.0, data_quality=0.0)
        with pytest.raises(RuntimeError) as excinfo:
            engine._enforce_model_quality(snapshot)
        # RuntimeError specifically: HOPEFXDecisionEngine._phase2_ml treats that
        # type as a hard ML filter rather than falling back to base confidence.
        assert "quality" in str(excinfo.value).lower()

    def test_with_blocking_enabled_an_unevaluable_snapshot_also_raises(self, monkeypatch) -> None:
        # A gate that could not be evaluated is not a gate that passed.
        import ml.inference_engine as ie

        monkeypatch.setattr(ie, "_MODEL_QUALITY_BLOCK", True)
        with pytest.raises(RuntimeError):
            _engine()._enforce_model_quality(None)

    def test_with_blocking_disabled_an_unevaluable_snapshot_does_not_raise(self, monkeypatch) -> None:
        import ml.inference_engine as ie

        monkeypatch.setattr(ie, "_MODEL_QUALITY_BLOCK", False)
        _engine()._enforce_model_quality(None)

    def test_a_passing_snapshot_never_raises_even_when_blocking(self, monkeypatch) -> None:
        # A gate that refuses everything is indistinguishable from a working
        # one until somebody tries to use it.
        import ml.inference_engine as ie

        monkeypatch.setattr(ie, "_MODEL_QUALITY_BLOCK", True)
        engine = _engine()
        engine._calibrator = object()
        snapshot = engine._evaluate_model_quality(drift_z=0.0, data_quality=1.0)
        assert snapshot is not None and snapshot.passed
        engine._enforce_model_quality(snapshot)


class TestThresholdsAreTheOnesTheFileAlreadyUsed:
    def test_the_drift_ceiling_is_the_engines_existing_constant(self) -> None:
        import ml.inference_engine as ie

        engine = _engine()
        engine._calibrator = object()
        gate = engine._model_quality_gate()
        assert gate.maximum_drift == ie._DRIFT_Z_THRESHOLD

    def test_the_data_quality_floor_is_the_previously_inline_value(self) -> None:
        # predict() used a bare `0.3` for "valid" vs "degraded". It is now a
        # named constant feeding the gate, so the boundary has one definition.
        import ml.inference_engine as ie

        assert ie._MIN_DATA_QUALITY == 0.3
        assert _engine()._model_quality_gate().minimum_data_quality == 0.3

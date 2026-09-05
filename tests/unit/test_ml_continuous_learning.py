# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
tests/unit/test_ml_continuous_learning.py
=========================================
`ml/continuous_learning.py` was 430 statements at 35.33 %.

This is the pipeline that is supposed to notice a model has drifted, retrain,
run the challenger in shadow, and promote it when it genuinely wins. Writing
tests for it found that **it could never promote anything**.

`_test_significance` called `scipy.stats.binom_test`. SciPy **removed** that
function in 1.12 — and `requirements.txt` pins `scipy>=1.12.0`, so 1.12 is the
*floor* of the supported range. On every supported install the call raised
`AttributeError`, the method's bare `except Exception` swallowed it, and the
gate returned `False`. Reproduced directly: a challenger with **70 % accuracy
over 1000 predictions** — overwhelmingly significant by any test — was rejected
as "not statistically significant yet". The `except ImportError` fallback never
helped either, because SciPy *is* installed; the AttributeError took the other
branch.

A second, smaller defect of the same family as the one fixed in
`ml/drift_detector.py`: `check_prediction_drift` set
`is_drifted = ks_stat > threshold` on a SciPy `numpy.float64`, producing a
`numpy.bool_` that `json.dumps` cannot serialise — in a dataclass whose
`to_dict()` exists precisely to build a JSON payload. The `score` beside it had
already been coerced with `float()` for that exact reason.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import numpy as np
import pytest

import ml.continuous_learning as cl
from ml.continuous_learning import (
    _CHAMPION_MIN_IMPROVEMENT,
    _DRIFT_PSI_THRESHOLD,
    _SHADOW_MIN_PREDICTIONS,
    ChampionChallenger,
    ContinuousLearningPipeline,
    DriftDetector,
    DriftReport,
    DriftType,
    RetrainingState,
    ShadowDeployment,
    ShadowResult,
    ShadowState,
    get_continuous_learning_pipeline,
)

pytestmark = pytest.mark.unit

UTC = timezone.utc


def _shadow_result(predictions=1000, correct=700, pnl=120.0, champion_pnl=100.0, version="v2"):
    return ShadowResult(
        model_version=version,
        predictions=predictions,
        correct_predictions=correct,
        total_pnl=pnl,
        champion_pnl=champion_pnl,
    )


class _Model:
    """A stand-in challenger exposing predict()."""

    def __init__(self, value=0.8):
        self.value = value

    def predict(self, X):
        return np.array([self.value])


class _ProbaModel:
    def __init__(self, value=0.8):
        self.value = value

    def predict_proba(self, X):
        return np.array([[1 - self.value, self.value]])


# ── the promotion gate that could never open ──────────────────────────────────


class TestSignificanceGate:
    """The defect this file was written to find."""

    def test_a_clearly_winning_challenger_is_significant(self):
        """70 % over 1000 predictions. Any binomial test says yes."""
        assert ChampionChallenger()._test_significance(_shadow_result(1000, 700)) is True

    def test_a_coin_flip_challenger_is_not_significant(self):
        assert ChampionChallenger()._test_significance(_shadow_result(1000, 505)) is False

    def test_a_worse_than_chance_challenger_is_not_significant(self):
        assert ChampionChallenger()._test_significance(_shadow_result(1000, 400)) is False

    def test_a_small_sample_is_not_significant_even_at_high_accuracy(self):
        """Ten flips landing 7 heads proves nothing."""
        assert ChampionChallenger()._test_significance(_shadow_result(10, 7)) is False

    def test_a_large_sample_makes_a_small_edge_significant(self):
        assert ChampionChallenger()._test_significance(_shadow_result(10_000, 5300)) is True

    def test_the_verdict_is_a_python_bool(self):
        verdict = ChampionChallenger()._test_significance(_shadow_result(1000, 700))

        assert type(verdict) is bool

    def test_the_modern_scipy_api_is_the_one_used(self):
        """binom_test is gone from every SciPy this project supports."""
        from scipy import stats

        assert hasattr(stats, "binomtest"), "the API this module now depends on"

    def test_without_scipy_it_falls_back_to_a_threshold(self, monkeypatch):
        import builtins

        real_import = builtins.__import__

        def _no_scipy(name, *args, **kwargs):
            if name == "scipy" or name.startswith("scipy."):
                raise ImportError("no scipy")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", _no_scipy)

        good = _shadow_result(_SHADOW_MIN_PREDICTIONS, int(_SHADOW_MIN_PREDICTIONS * 0.7))
        weak = _shadow_result(_SHADOW_MIN_PREDICTIONS, int(_SHADOW_MIN_PREDICTIONS * 0.5))

        assert ChampionChallenger()._test_significance(good) is True
        assert ChampionChallenger()._test_significance(weak) is False

    def test_zero_predictions_does_not_raise(self):
        assert ChampionChallenger()._test_significance(_shadow_result(0, 0)) is False


# ── drift reports ─────────────────────────────────────────────────────────────


class TestDriftReport:
    def _report(self, **kw):
        base = {
            "timestamp": datetime.now(UTC),
            "drift_type": DriftType.FEATURE_DRIFT,
            "score": 0.31,
            "threshold": 0.2,
            "is_drifted": True,
        }
        base.update(kw)
        return DriftReport(**base)

    def test_to_dict_flattens_the_enum_and_timestamp(self):
        payload = self._report().to_dict()

        assert payload["drift_type"] == "feature_drift"
        assert datetime.fromisoformat(payload["timestamp"])

    def test_the_collections_default_to_empty(self):
        payload = self._report().to_dict()

        assert payload["details"] == {}
        assert payload["affected_features"] == []

    def test_it_is_json_serialisable(self):
        json.dumps(self._report().to_dict())


class TestPredictionDriftPayload:
    """The numpy.bool_ that json.dumps cannot serialise."""

    def _report(self, shifted=True):
        rng = np.random.default_rng(0)
        reference = rng.normal(0, 1, 300)
        recent = rng.normal(4, 1, 300) if shifted else rng.normal(0, 1, 300)
        return DriftDetector().check_prediction_drift(recent, reference)

    def test_the_drift_flag_is_a_python_bool(self):
        assert type(self._report().is_drifted) is bool

    def test_a_drifted_report_serialises(self):
        json.dumps(self._report(shifted=True).to_dict())

    def test_a_stable_report_serialises(self):
        json.dumps(self._report(shifted=False).to_dict())

    def test_a_shifted_distribution_is_detected(self):
        assert self._report(shifted=True).is_drifted is True

    def test_a_matching_distribution_is_not(self):
        assert self._report(shifted=False).is_drifted is False

    def test_it_reports_the_ks_statistic_and_p_value(self):
        details = self._report().details

        assert 0.0 <= details["ks_statistic"] <= 1.0
        assert 0.0 <= details["p_value"] <= 1.0

    def test_the_report_is_labelled_prediction_drift(self):
        assert self._report().drift_type is DriftType.PREDICTION_DRIFT


# ── the shadow result record ──────────────────────────────────────────────────


class TestShadowResult:
    def test_accuracy_with_no_predictions_is_zero_not_a_division_error(self):
        assert ShadowResult(model_version="v").accuracy == 0.0

    def test_accuracy_is_the_hit_rate(self):
        assert _shadow_result(200, 150).accuracy == pytest.approx(0.75)

    def test_pnl_improvement_against_a_flat_champion_is_zero(self):
        assert _shadow_result(pnl=50.0, champion_pnl=0.0).pnl_improvement == 0.0

    def test_pnl_improvement_is_relative_to_the_champion(self):
        assert _shadow_result(pnl=120.0, champion_pnl=100.0).pnl_improvement == pytest.approx(0.2)

    def test_a_losing_champion_still_yields_a_signed_improvement(self):
        """abs() in the denominator keeps the sign meaningful when the champion lost."""
        assert _shadow_result(pnl=-50.0, champion_pnl=-100.0).pnl_improvement == pytest.approx(0.5)

    def test_it_starts_running(self):
        assert ShadowResult(model_version="v").state is ShadowState.RUNNING

    def test_to_dict_is_serialisable_and_complete(self):
        payload = _shadow_result().to_dict()

        json.dumps(payload)
        assert set(payload) == {
            "model_version",
            "predictions",
            "correct_predictions",
            "accuracy",
            "total_pnl",
            "champion_pnl",
            "pnl_improvement",
            "started_at",
            "state",
        }


# ── feature drift (PSI) ───────────────────────────────────────────────────────


class TestDriftDetectorPsi:
    def test_a_fresh_detector_reports_no_drift(self):
        report = DriftDetector().check_drift()

        assert report.is_drifted is False
        assert report.score == 0.0
        assert report.affected_features == []

    def test_the_window_is_bounded(self):
        detector = DriftDetector()
        for i in range(2500):
            detector.add_observation("rsi", float(i))

        assert len(detector._current_window["rsi"]) == detector._window_size

    def test_the_window_keeps_the_most_recent_values(self):
        detector = DriftDetector()
        detector._window_size = 3
        for v in (1.0, 2.0, 3.0, 4.0):
            detector.add_observation("rsi", v)

        assert detector._current_window["rsi"] == [2.0, 3.0, 4.0]

    def test_too_few_observations_are_skipped_rather_than_scored(self):
        """Under 100 samples PSI is noise; reporting it would be a false alarm."""
        detector = DriftDetector()
        detector.set_reference("rsi", np.random.default_rng(0).normal(50, 10, 500))
        for v in np.random.default_rng(1).normal(90, 1, 50):
            detector.add_observation("rsi", float(v))

        assert detector.check_drift().is_drifted is False

    def test_a_matching_distribution_is_not_drifted(self):
        rng = np.random.default_rng(0)
        detector = DriftDetector()
        detector.set_reference("rsi", rng.normal(50, 10, 1000))
        for v in rng.normal(50, 10, 500):
            detector.add_observation("rsi", float(v))

        report = detector.check_drift()

        assert report.is_drifted is False
        assert report.score < _DRIFT_PSI_THRESHOLD

    def test_a_shifted_distribution_is_drifted_and_names_the_feature(self):
        rng = np.random.default_rng(0)
        detector = DriftDetector()
        detector.set_reference("rsi", rng.normal(50, 5, 1000))
        for v in rng.normal(90, 5, 500):
            detector.add_observation("rsi", float(v))

        report = detector.check_drift()

        assert report.is_drifted is True
        assert "rsi" in report.affected_features
        assert report.details["psi_scores"]["rsi"] > _DRIFT_PSI_THRESHOLD

    def test_the_overall_score_is_the_worst_feature(self):
        rng = np.random.default_rng(0)
        detector = DriftDetector()
        detector.set_reference("calm", rng.normal(50, 5, 1000))
        detector.set_reference("wild", rng.normal(50, 5, 1000))
        for v in rng.normal(50, 5, 500):
            detector.add_observation("calm", float(v))
        for v in rng.normal(95, 5, 500):
            detector.add_observation("wild", float(v))

        report = detector.check_drift()

        assert report.score == pytest.approx(max(report.details["psi_scores"].values()))
        assert report.affected_features == ["wild"]

    def test_psi_of_a_distribution_against_itself_is_about_zero(self):
        data = np.random.default_rng(0).normal(0, 1, 1000)

        assert DriftDetector()._calculate_psi(data, data) == pytest.approx(0.0, abs=1e-9)

    def test_psi_is_never_negative(self):
        rng = np.random.default_rng(0)

        for shift in (0, 1, 5, 20):
            psi = DriftDetector()._calculate_psi(rng.normal(0, 1, 500), rng.normal(shift, 1, 500))
            assert psi >= 0.0

    def test_psi_grows_with_the_shift(self):
        rng = np.random.default_rng(0)
        reference = rng.normal(0, 1, 2000)
        near = DriftDetector()._calculate_psi(reference, rng.normal(0.5, 1, 2000))
        far = DriftDetector()._calculate_psi(reference, rng.normal(6, 1, 2000))

        assert far > near

    def test_psi_is_finite_for_disjoint_ranges(self):
        """Empty bins would make log(0) infinite; the clip is what prevents it."""
        import math

        psi = DriftDetector()._calculate_psi(np.zeros(500), np.ones(500) * 100)

        assert math.isfinite(psi)

    def test_a_check_stamps_the_time(self):
        detector = DriftDetector()
        detector.check_drift()

        assert detector._last_check is not None

    def test_the_report_is_serialisable(self):
        json.dumps(DriftDetector().check_drift().to_dict())


# ── shadow deployment ─────────────────────────────────────────────────────────


class TestShadowDeployment:
    def test_deploying_registers_a_result_slot(self):
        shadow = ShadowDeployment()
        shadow.deploy_shadow("v2", _Model())

        assert "v2" in shadow.get_shadow_results()
        assert shadow.get_shadow_results()["v2"].predictions == 0

    def test_removing_clears_both_the_model_and_its_results(self):
        shadow = ShadowDeployment()
        shadow.deploy_shadow("v2", _Model())
        shadow.remove_shadow("v2")

        assert shadow.get_shadow_results() == {}
        assert shadow._shadow_models == {}

    def test_removing_an_unknown_version_is_not_an_error(self):
        ShadowDeployment().remove_shadow("never-deployed")

    def test_the_results_view_is_a_copy(self):
        shadow = ShadowDeployment()
        shadow.deploy_shadow("v2", _Model())
        shadow.get_shadow_results().clear()

        assert "v2" in shadow.get_shadow_results()

    @pytest.mark.asyncio
    async def test_a_predict_model_is_run(self):
        shadow = ShadowDeployment()
        shadow.deploy_shadow("v2", _Model(0.9))

        preds = await shadow.run_shadow_prediction(np.zeros(5), champion_prediction=0.5)

        assert preds == {"v2": pytest.approx(0.9)}

    @pytest.mark.asyncio
    async def test_a_predict_proba_model_uses_the_positive_class(self):
        shadow = ShadowDeployment()
        shadow.deploy_shadow("v2", _ProbaModel(0.7))

        preds = await shadow.run_shadow_prediction(np.zeros(5), champion_prediction=0.5)

        assert preds["v2"] == pytest.approx(0.7)

    @pytest.mark.asyncio
    async def test_a_model_with_neither_method_is_skipped(self):
        shadow = ShadowDeployment()
        shadow.deploy_shadow("v2", object())

        assert await shadow.run_shadow_prediction(np.zeros(5), 0.5) == {}

    @pytest.mark.asyncio
    async def test_a_failing_shadow_never_affects_the_others(self):
        """Shadow predictions must not be able to disturb live trading."""
        shadow = ShadowDeployment()
        broken = MagicMock()
        broken.predict.side_effect = RuntimeError("challenger exploded")
        shadow.deploy_shadow("broken", broken)
        shadow.deploy_shadow("good", _Model(0.6))

        preds = await shadow.run_shadow_prediction(np.zeros(5), 0.5)

        assert set(preds) == {"good"}

    @pytest.mark.asyncio
    async def test_a_correct_prediction_is_counted(self):
        shadow = ShadowDeployment()
        shadow.deploy_shadow("v2", _Model(0.9))  # predicts up

        await shadow.run_shadow_prediction(np.zeros(5), 0.5, actual_outcome=1.0)

        result = shadow.get_shadow_results()["v2"]
        assert result.predictions == 1
        assert result.correct_predictions == 1

    @pytest.mark.asyncio
    async def test_a_wrong_prediction_is_not_counted_correct(self):
        shadow = ShadowDeployment()
        shadow.deploy_shadow("v2", _Model(0.9))  # predicts up

        await shadow.run_shadow_prediction(np.zeros(5), 0.5, actual_outcome=-1.0)

        assert shadow.get_shadow_results()["v2"].correct_predictions == 0

    @pytest.mark.asyncio
    async def test_without_an_outcome_only_the_count_advances(self):
        shadow = ShadowDeployment()
        shadow.deploy_shadow("v2", _Model(0.9))

        await shadow.run_shadow_prediction(np.zeros(5), 0.5)

        result = shadow.get_shadow_results()["v2"]
        assert (result.predictions, result.correct_predictions) == (1, 0)

    def test_pnl_accumulates(self):
        shadow = ShadowDeployment()
        shadow.deploy_shadow("v2", _Model())
        shadow.record_pnl("v2", 10.0, 8.0)
        shadow.record_pnl("v2", 5.0, 2.0)

        result = shadow.get_shadow_results()["v2"]
        assert result.total_pnl == pytest.approx(15.0)
        assert result.champion_pnl == pytest.approx(10.0)

    def test_recording_pnl_for_an_unknown_version_is_ignored(self):
        ShadowDeployment().record_pnl("nope", 1.0, 1.0)


class TestPromotionEligibility:
    def _shadow_with(self, **kw):
        shadow = ShadowDeployment()
        shadow.deploy_shadow("v2", _Model())
        shadow._shadows["v2"] = _shadow_result(**kw)
        return shadow

    def test_an_unknown_version_is_not_eligible(self):
        assert ShadowDeployment().evaluate_for_promotion("nope") is False

    def test_too_few_predictions_is_not_eligible(self):
        shadow = self._shadow_with(predictions=_SHADOW_MIN_PREDICTIONS - 1, correct=100)

        assert shadow.evaluate_for_promotion("v2") is False

    def test_accuracy_below_the_floor_is_not_eligible(self):
        n = _SHADOW_MIN_PREDICTIONS + 100
        shadow = self._shadow_with(predictions=n, correct=int(n * 0.51))

        assert shadow.evaluate_for_promotion("v2") is False

    def test_insufficient_pnl_improvement_is_not_eligible(self):
        n = _SHADOW_MIN_PREDICTIONS + 100
        shadow = self._shadow_with(predictions=n, correct=int(n * 0.7), pnl=100.0, champion_pnl=100.0)

        assert shadow.evaluate_for_promotion("v2") is False

    def test_clearing_every_gate_is_eligible(self):
        n = _SHADOW_MIN_PREDICTIONS + 100
        shadow = self._shadow_with(
            predictions=n,
            correct=int(n * 0.7),
            pnl=100.0 * (1 + _CHAMPION_MIN_IMPROVEMENT * 2),
            champion_pnl=100.0,
        )

        assert shadow.evaluate_for_promotion("v2") is True


# ── champion / challenger ─────────────────────────────────────────────────────


class TestPromoteIfReady:
    def _ready_shadow(self):
        n = _SHADOW_MIN_PREDICTIONS + 100
        shadow = ShadowDeployment()
        shadow.deploy_shadow("v2", _Model())
        shadow._shadows["v2"] = _shadow_result(
            predictions=n,
            correct=int(n * 0.7),
            pnl=100.0 * (1 + _CHAMPION_MIN_IMPROVEMENT * 2),
            champion_pnl=100.0,
        )
        return shadow

    @pytest.mark.asyncio
    async def test_an_ineligible_challenger_is_not_promoted(self):
        shadow = ShadowDeployment()
        shadow.deploy_shadow("v2", _Model())

        assert await ChampionChallenger().promote_if_ready(shadow, "v2") is False

    @pytest.mark.asyncio
    async def test_a_winning_challenger_is_promoted(self):
        """Before the scipy fix this returned False no matter how good the model."""
        registry = MagicMock()
        cc = ChampionChallenger(model_registry=registry)
        shadow = self._ready_shadow()

        assert await cc.promote_if_ready(shadow, "v2") is True
        registry.promote.assert_called_once_with("v2")

    @pytest.mark.asyncio
    async def test_promotion_is_recorded_in_the_history(self):
        cc = ChampionChallenger()
        await cc.promote_if_ready(self._ready_shadow(), "v2")

        assert cc.promotion_history[-1]["version_id"] == "v2"
        assert "promoted_at" in cc.promotion_history[-1]

    @pytest.mark.asyncio
    async def test_a_promoted_shadow_is_retired(self):
        shadow = self._ready_shadow()
        await ChampionChallenger().promote_if_ready(shadow, "v2")

        assert "v2" not in shadow.get_shadow_results()

    @pytest.mark.asyncio
    async def test_a_failing_registry_aborts_the_promotion(self):
        """Never record a promotion the registry refused."""
        registry = MagicMock()
        registry.promote.side_effect = RuntimeError("registry down")
        cc = ChampionChallenger(model_registry=registry)

        assert await cc.promote_if_ready(self._ready_shadow(), "v2") is False
        assert cc.promotion_history == []

    @pytest.mark.asyncio
    async def test_without_a_registry_it_still_promotes_locally(self):
        cc = ChampionChallenger(model_registry=None)

        assert await cc.promote_if_ready(self._ready_shadow(), "v2") is True

    @pytest.mark.asyncio
    async def test_a_registry_without_a_promote_method_is_tolerated(self):
        cc = ChampionChallenger(model_registry=SimpleNamespace())

        assert await cc.promote_if_ready(self._ready_shadow(), "v2") is True

    @pytest.mark.asyncio
    async def test_the_history_is_json_serialisable(self):
        cc = ChampionChallenger()
        await cc.promote_if_ready(self._ready_shadow(), "v2")

        json.dumps(cc.promotion_history)


# ── the pipeline surface ──────────────────────────────────────────────────────


class TestPipeline:
    def test_a_fresh_pipeline_is_idle(self):
        health = ContinuousLearningPipeline().health()

        assert health["running"] is False
        assert health["retraining_state"] == RetrainingState.IDLE.value
        assert health["drift_history_count"] == 0
        assert health["latest_drift"] is None

    def test_health_is_json_serialisable(self):
        json.dumps(ContinuousLearningPipeline().health())

    def test_health_reports_shadow_models(self):
        pipeline = ContinuousLearningPipeline()
        pipeline._shadow.deploy_shadow("v2", _Model())

        assert "v2" in pipeline.health()["shadow_models"]

    def test_health_surfaces_the_latest_drift_report(self):
        pipeline = ContinuousLearningPipeline()
        pipeline._drift_history.append(pipeline._drift_detector.check_drift())

        health = pipeline.health()

        assert health["drift_history_count"] == 1
        assert health["latest_drift"]["drift_type"] == "feature_drift"
        json.dumps(health)

    def test_feature_observations_reach_the_detector(self):
        pipeline = ContinuousLearningPipeline()
        pipeline.add_feature_observation("rsi", 42.0)

        assert pipeline._drift_detector._current_window["rsi"] == [42.0]

    def test_promotion_history_is_empty_without_a_challenger(self):
        assert ContinuousLearningPipeline().health()["promotion_history"] == []

    @pytest.mark.asyncio
    async def test_shadow_predictions_are_delegated(self):
        pipeline = ContinuousLearningPipeline()
        pipeline._shadow.deploy_shadow("v2", _Model(0.6))

        preds = await pipeline.run_shadow_predictions(np.zeros(3), 0.5)

        assert preds["v2"] == pytest.approx(0.6)

    def test_a_fresh_orchestrator_may_retrain(self):
        assert ContinuousLearningPipeline()._retraining.can_retrain is True


class TestSingleton:
    def test_it_is_shared(self, monkeypatch):
        monkeypatch.setattr(cl, "_pipeline", None, raising=False)

        assert get_continuous_learning_pipeline() is get_continuous_learning_pipeline()

    def test_it_is_a_pipeline(self, monkeypatch):
        monkeypatch.setattr(cl, "_pipeline", None, raising=False)

        assert isinstance(get_continuous_learning_pipeline(), ContinuousLearningPipeline)

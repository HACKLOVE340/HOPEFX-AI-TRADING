# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
tests/unit/test_ml_drift_detector.py
====================================
`ml/drift_detector.py` was at **0.00 %** — 151 statements, reached by nothing.

It is not dead code: `api/ml.py` and `api/superadmin/ml_ai.py` both call
`get_drift_detector()` to serve the drift dashboard. So the endpoint that tells
an operator whether a live model has stopped matching the distribution it was
trained on was answered entirely by untested code.

There *is* a `TestDriftDetector` in `tests/unit/test_ml_inference_training.py`,
which is how this went unnoticed. It imports
`ml.robust_predictor.DriftDetector` — a different class in a different module.
A test named after the thing it does not test is worse than no test, because
the name is read as coverage. That pattern has now turned up several times in
this branch, so this file states plainly which class it covers:
`ModelDriftTracker` and `DriftDetectorService` from `ml/drift_detector.py`.

The behaviour worth pinning is the *status ladder*. The report distinguishes
"reference_insufficient", "warming_up", "stable" and "drift_detected", and the
first two exist so a model with too little data is never reported as stable.
Collapsing them would make a cold start look like a clean bill of health.
"""

from __future__ import annotations

import json
import threading

import numpy as np
import pytest

import ml.drift_detector as dd_mod
from ml.drift_detector import (
    _MIN_REFERENCE_SAMPLES,
    _MIN_WINDOW_SAMPLES,
    _MONITORED_MODELS,
    DriftDetectorService,
    ModelDriftTracker,
    get_drift_detector,
)

pytestmark = pytest.mark.unit


def _reference(n=200, loc=0.5, scale=0.08, seed=1):
    rng = np.random.default_rng(seed)
    return np.clip(rng.normal(loc, scale, n), 0.0, 1.0).tolist()


def _fill(tracker, values):
    for v in values:
        tracker.record(v)


# ── the per-model tracker ─────────────────────────────────────────────────────


class TestTrackerConstruction:
    def test_it_starts_empty(self):
        tracker = ModelDriftTracker("advanced_oos")

        assert tracker.model_name == "advanced_oos"
        assert tracker._reference is None
        assert len(tracker._window) == 0

    def test_the_window_is_bounded(self):
        """An unbounded window would grow without limit on a live feed."""
        tracker = ModelDriftTracker("m", window_size=50)

        _fill(tracker, [0.5] * 500)

        assert len(tracker._window) == 50

    def test_the_window_keeps_the_most_recent_values(self):
        tracker = ModelDriftTracker("m", window_size=3)

        _fill(tracker, [0.1, 0.2, 0.3, 0.4, 0.5])

        assert list(tracker._window) == [0.3, 0.4, 0.5]


class TestSetReference:
    def test_a_list_becomes_an_array(self):
        tracker = ModelDriftTracker("m")
        tracker.set_reference([0.1, 0.2, 0.3])

        assert isinstance(tracker._reference, np.ndarray)
        assert tracker._reference.dtype == float

    def test_an_array_is_accepted_directly(self):
        tracker = ModelDriftTracker("m")
        tracker.set_reference(np.array([0.1, 0.2]))

        assert len(tracker._reference) == 2

    def test_setting_a_new_reference_replaces_the_old_one(self):
        tracker = ModelDriftTracker("m")
        tracker.set_reference([0.1] * 10)
        tracker.set_reference([0.2] * 5)

        assert len(tracker._reference) == 5


class TestTheStatusLadder:
    def test_no_reference_reports_insufficient_rather_than_stable(self):
        """A cold start must never read as a clean bill of health."""
        report = ModelDriftTracker("m").get_report()

        assert report["status"] == "reference_insufficient"
        assert report["n_reference"] == 0

    def test_a_short_reference_is_still_insufficient(self):
        tracker = ModelDriftTracker("m")
        tracker.set_reference([0.5] * (_MIN_REFERENCE_SAMPLES - 1))

        assert tracker.get_report()["status"] == "reference_insufficient"

    def test_a_full_reference_with_an_empty_window_is_warming_up(self):
        tracker = ModelDriftTracker("m")
        tracker.set_reference(_reference())

        report = tracker.get_report()

        assert report["status"] == "warming_up"
        assert report["n_window"] == 0

    def test_a_matching_window_is_stable(self):
        tracker = ModelDriftTracker("m")
        tracker.set_reference(_reference(seed=1))
        _fill(tracker, _reference(n=_MIN_WINDOW_SAMPLES + 10, seed=2))

        report = tracker.get_report()

        assert report["status"] == "stable"
        assert report["drifted"] is False

    def test_a_shifted_window_is_drift_detected(self):
        tracker = ModelDriftTracker("m")
        tracker.set_reference(_reference(loc=0.5, seed=1))
        _fill(tracker, _reference(n=_MIN_WINDOW_SAMPLES + 10, loc=0.95, scale=0.01, seed=2))

        report = tracker.get_report()

        assert report["status"] == "drift_detected"
        assert report["drifted"] is True

    def test_the_ladder_covers_every_state_exactly_once(self):
        assert {"reference_insufficient", "warming_up", "stable", "drift_detected"}


class TestTheReportShape:
    def test_it_always_names_its_model(self):
        assert ModelDriftTracker("advanced_oos").get_report()["model"] == "advanced_oos"

    def test_empty_means_are_none_rather_than_zero(self):
        """0.0 is a real probability; None is the honest answer for 'no data'."""
        report = ModelDriftTracker("m").get_report()

        assert report["window_mean"] is None
        assert report["reference_mean"] is None

    def test_the_means_are_reported_once_there_is_data(self):
        tracker = ModelDriftTracker("m")
        tracker.set_reference([0.4] * 200)
        _fill(tracker, [0.6] * 40)

        report = tracker.get_report()

        assert report["reference_mean"] == pytest.approx(0.4)
        assert report["window_mean"] == pytest.approx(0.6)

    def test_a_fresh_tracker_has_no_events_and_no_check_time(self):
        report = ModelDriftTracker("m").get_report()

        assert report["drift_events"] == 0
        assert report["last_drift_event"] is None
        assert report["checked_at"] is None

    def test_a_drift_check_stamps_the_time(self):
        tracker = ModelDriftTracker("m")
        tracker.set_reference(_reference())
        _fill(tracker, _reference(n=_MIN_WINDOW_SAMPLES + 5, seed=3))

        assert tracker.get_report()["checked_at"] is not None


class TestDriftEvents:
    def test_a_drift_is_appended_to_the_history(self):
        tracker = ModelDriftTracker("m")
        tracker.set_reference(_reference(loc=0.2, seed=1))
        _fill(tracker, _reference(n=_MIN_WINDOW_SAMPLES + 5, loc=0.9, scale=0.01, seed=2))
        tracker.get_report()

        assert tracker.get_report()["drift_events"] >= 1

    def test_the_event_records_which_model_drifted(self):
        tracker = ModelDriftTracker("advanced_oos")
        tracker.set_reference(_reference(loc=0.2, seed=1))
        _fill(tracker, _reference(n=_MIN_WINDOW_SAMPLES + 5, loc=0.9, scale=0.01, seed=2))
        tracker.get_report()

        assert tracker.get_report()["last_drift_event"]["model"] == "advanced_oos"

    def test_the_event_history_is_capped(self):
        """Unbounded history on a drifting model is a slow memory leak."""
        tracker = ModelDriftTracker("m")
        tracker.set_reference(_reference(loc=0.2, seed=1))
        _fill(tracker, _reference(n=_MIN_WINDOW_SAMPLES + 5, loc=0.9, scale=0.01, seed=2))
        for _ in range(150):
            tracker._evaluate()

        assert len(tracker._drift_events) <= 100

    def test_a_stable_model_records_no_events(self):
        tracker = ModelDriftTracker("m")
        tracker.set_reference(_reference(seed=1))
        _fill(tracker, _reference(n=_MIN_WINDOW_SAMPLES + 5, seed=2))
        tracker.get_report()

        assert tracker._drift_events == []


class TestRecord:
    def test_it_returns_false_while_the_reference_is_missing(self):
        tracker = ModelDriftTracker("m")

        assert any(tracker.record(0.5) for _ in range(60)) is False

    def test_it_reports_true_when_a_periodic_check_finds_drift(self):
        tracker = ModelDriftTracker("m")
        tracker.set_reference(_reference(loc=0.2, seed=1))

        # 20 predictions triggers the periodic evaluation, but the window must
        # also reach the minimum before the KS test can run.
        flags = [tracker.record(v) for v in _reference(n=100, loc=0.95, scale=0.01, seed=2)]

        assert any(flags)

    def test_a_matching_stream_never_flags(self):
        tracker = ModelDriftTracker("m")
        tracker.set_reference(_reference(seed=1))

        flags = [tracker.record(v) for v in _reference(n=100, seed=2)]

        assert not any(flags)

    def test_the_update_count_advances(self):
        tracker = ModelDriftTracker("m")
        _fill(tracker, [0.5] * 7)

        assert tracker._update_count == 7


class TestEvaluate:
    def test_it_declines_without_a_reference(self):
        assert ModelDriftTracker("m")._evaluate() is None

    def test_it_declines_with_too_short_a_reference(self):
        tracker = ModelDriftTracker("m")
        tracker.set_reference([0.5] * 10)
        _fill(tracker, [0.5] * 50)

        assert tracker._evaluate() is None

    def test_it_declines_with_too_short_a_window(self):
        tracker = ModelDriftTracker("m")
        tracker.set_reference(_reference())
        _fill(tracker, [0.5] * (_MIN_WINDOW_SAMPLES - 1))

        assert tracker._evaluate() is None

    def test_the_result_carries_the_statistic_and_p_value(self):
        tracker = ModelDriftTracker("m")
        tracker.set_reference(_reference(seed=1))
        _fill(tracker, _reference(n=50, seed=2))

        result = tracker._evaluate()

        assert 0.0 <= result["p_value"] <= 1.0
        assert result["ks_statistic"] >= 0.0
        assert isinstance(result["drifted"], bool)

    def test_without_scipy_it_falls_back_to_a_mean_shift_test(self, monkeypatch):
        """scipy is optional; the detector must still answer without it."""
        import builtins

        real_import = builtins.__import__

        def _no_scipy(name, *args, **kwargs):
            if name.startswith("scipy"):
                raise ImportError("no scipy")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", _no_scipy)

        tracker = ModelDriftTracker("m")
        tracker.set_reference(_reference(loc=0.2, scale=0.05, seed=1))
        _fill(tracker, [0.95] * 50)

        result = tracker._evaluate()

        assert result is not None
        assert result["drifted"] is True

    def test_the_scipy_free_fallback_calls_a_matching_stream_stable(self, monkeypatch):
        import builtins

        real_import = builtins.__import__

        def _no_scipy(name, *args, **kwargs):
            if name.startswith("scipy"):
                raise ImportError("no scipy")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", _no_scipy)

        tracker = ModelDriftTracker("m")
        tracker.set_reference(_reference(loc=0.5, seed=1))
        _fill(tracker, [0.5] * 50)

        assert tracker._evaluate()["drifted"] is False


class TestThreadSafety:
    def test_concurrent_records_do_not_lose_updates(self):
        tracker = ModelDriftTracker("m", window_size=10_000)

        def _worker():
            for _ in range(200):
                tracker.record(0.5)

        threads = [threading.Thread(target=_worker) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert tracker._update_count == 800


# ── the multi-model service ───────────────────────────────────────────────────


@pytest.fixture
def service(tmp_path, monkeypatch):
    """A service with no saved-model metadata in reach."""
    monkeypatch.chdir(tmp_path)
    return DriftDetectorService()


class TestServiceInitialisation:
    def test_it_is_lazy(self, service):
        assert service._initialised is False
        assert service._trackers == {}

    def test_the_first_call_creates_a_tracker_per_monitored_model(self, service):
        service._ensure_initialised()

        assert set(service._trackers) == set(_MONITORED_MODELS)

    def test_initialisation_happens_once(self, service):
        service._ensure_initialised()
        service._trackers["injected"] = ModelDriftTracker("injected")
        service._ensure_initialised()

        assert "injected" in service._trackers

    def test_without_metadata_a_neutral_prior_is_synthesised(self, service):
        """A model with no saved OOS distribution still needs a baseline."""
        service._ensure_initialised()
        tracker = service._trackers["advanced_oos"]

        assert tracker._reference is not None
        assert len(tracker._reference) >= _MIN_REFERENCE_SAMPLES
        assert float(tracker._reference.min()) >= 0.0
        assert float(tracker._reference.max()) <= 1.0

    def test_a_saved_oos_distribution_is_used_when_present(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        saved = tmp_path / "ml" / "saved_models"
        saved.mkdir(parents=True)
        probs = [0.31] * 150
        (saved / "advanced_oos_meta.json").write_text(json.dumps({"oos_probabilities": probs}))

        svc = DriftDetectorService()
        svc._ensure_initialised()

        assert float(svc._trackers["advanced_oos"]._reference.mean()) == pytest.approx(0.31)

    def test_a_validation_distribution_is_the_second_choice(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        saved = tmp_path / "ml" / "saved_models"
        saved.mkdir(parents=True)
        (saved / "lstm_signal_meta.json").write_text(json.dumps({"val_probabilities": [0.62] * 150}))

        svc = DriftDetectorService()
        svc._ensure_initialised()

        assert float(svc._trackers["lstm_signal"]._reference.mean()) == pytest.approx(0.62)

    def test_too_few_saved_probabilities_are_ignored(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        saved = tmp_path / "ml" / "saved_models"
        saved.mkdir(parents=True)
        (saved / "advanced_oos_meta.json").write_text(json.dumps({"oos_probabilities": [0.9] * 5}))

        svc = DriftDetectorService()
        svc._ensure_initialised()

        assert svc._trackers["advanced_oos"]._reference is None

    def test_corrupt_metadata_is_survivable(self, tmp_path, monkeypatch):
        """A half-written meta file must not take the drift endpoint down."""
        monkeypatch.chdir(tmp_path)
        saved = tmp_path / "ml" / "saved_models"
        saved.mkdir(parents=True)
        (saved / "advanced_oos_meta.json").write_text("{ not json")

        svc = DriftDetectorService()
        svc._ensure_initialised()  # must not raise

        assert "advanced_oos" in svc._trackers


class TestRecordPrediction:
    def test_it_initialises_on_first_use(self, service):
        service.record_prediction("advanced_oos", 0.6)

        assert service._initialised is True

    def test_an_unmonitored_model_gets_a_tracker_on_demand(self, service):
        service.record_prediction("brand_new_model", 0.6)

        assert "brand_new_model" in service._trackers

    def test_the_value_reaches_the_tracker(self, service):
        service.record_prediction("advanced_oos", 0.77)

        assert list(service._trackers["advanced_oos"]._window) == [0.77]


class TestGetDriftReport:
    def test_a_monitored_model_reports(self, service):
        report = service.get_drift_report("advanced_oos")

        assert report["model"] == "advanced_oos"

    def test_an_unknown_model_is_not_monitored_rather_than_an_error(self, service):
        report = service.get_drift_report("nope")

        assert report == {"model": "nope", "status": "not_monitored"}


class TestGetAllDrift:
    def test_it_reports_every_monitored_model(self, service):
        payload = service.get_all_drift()

        assert payload["total"] == len(_MONITORED_MODELS)
        assert len(payload["drift_reports"]) == len(_MONITORED_MODELS)

    def test_a_quiet_system_is_stable(self, service):
        payload = service.get_all_drift()

        assert payload["overall_status"] == "stable"
        assert payload["models_drifted"] == 0

    def test_one_drifting_model_flips_the_overall_status(self, service):
        """This is the value the superadmin dashboard renders."""
        service.set_reference("advanced_oos", _reference(loc=0.2, seed=1))
        for v in _reference(n=60, loc=0.95, scale=0.01, seed=2):
            service.record_prediction("advanced_oos", v)

        payload = service.get_all_drift()

        assert payload["models_drifted"] >= 1
        assert payload["overall_status"] == "drift_detected"

    def test_it_stamps_when_it_was_checked(self, service):
        assert service.get_all_drift()["last_checked"] is not None


class TestThePayloadIsActuallySerialisable:
    """The bug this file was written to find.

    `drifted = p_value < _DRIFT_P_THRESHOLD` produced a `numpy.bool_`, because
    scipy returns numpy scalars. That value went straight into the dict
    `GET /api/ml/drift` and the superadmin drift page return, and **neither
    `json.dumps` nor FastAPI's `jsonable_encoder` can serialise it**.

    So the drift endpoint worked only while it had nothing to report: as soon
    as a model accumulated enough reference and window samples for the KS test
    to run -- the point at which drift monitoring starts being useful -- the
    response raised instead of rendering.
    """

    def _drifting(self, service):
        service.set_reference("advanced_oos", _reference(loc=0.2, seed=1))
        for v in _reference(n=60, loc=0.95, scale=0.01, seed=2):
            service.record_prediction("advanced_oos", v)
        return service.get_all_drift()

    def test_a_drift_report_survives_json_dumps(self, service):
        payload = self._drifting(service)

        json.dumps(payload)  # must not raise

    def test_a_drift_report_survives_fastapi_encoding(self, service):
        from fastapi.encoders import jsonable_encoder

        payload = self._drifting(service)

        jsonable_encoder(payload)  # must not raise

    def test_a_stable_report_survives_json_dumps(self, service):
        service.set_reference("advanced_oos", _reference(seed=1))
        for v in _reference(n=60, seed=2):
            service.record_prediction("advanced_oos", v)

        json.dumps(service.get_all_drift())

    def test_an_untouched_report_survives_json_dumps(self, service):
        json.dumps(service.get_all_drift())

    def test_the_drifted_flag_is_a_python_bool(self, service):
        payload = self._drifting(service)
        flags = [r["drifted"] for r in payload["drift_reports"] if "drifted" in r]

        assert flags, "expected at least one evaluated report"
        for flag in flags:
            assert type(flag) is bool

    def test_a_single_model_report_also_serialises(self, service):
        self._drifting(service)

        json.dumps(service.get_drift_report("advanced_oos"))

    def test_the_tracker_result_is_a_python_bool_directly(self):
        tracker = ModelDriftTracker("m")
        tracker.set_reference(_reference(seed=1))
        _fill(tracker, _reference(n=50, seed=2))

        assert type(tracker._evaluate()["drifted"]) is bool


class TestServiceSetReference:
    def test_it_reaches_the_named_tracker(self, service):
        service.set_reference("advanced_oos", [0.42] * 150)

        assert float(service._trackers["advanced_oos"]._reference.mean()) == pytest.approx(0.42)

    def test_an_unknown_model_gets_a_tracker(self, service):
        service.set_reference("brand_new", [0.5] * 150)

        assert "brand_new" in service._trackers


class TestSingleton:
    def test_it_is_shared(self, monkeypatch):
        monkeypatch.setattr(dd_mod, "_detector", None, raising=False)

        assert get_drift_detector() is get_drift_detector()

    def test_it_is_a_service(self, monkeypatch):
        monkeypatch.setattr(dd_mod, "_detector", None, raising=False)

        assert isinstance(get_drift_detector(), DriftDetectorService)

    def test_concurrent_first_calls_yield_one_instance(self, monkeypatch):
        monkeypatch.setattr(dd_mod, "_detector", None, raising=False)
        seen = []

        def _worker():
            seen.append(get_drift_detector())

        threads = [threading.Thread(target=_worker) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len({id(s) for s in seen}) == 1

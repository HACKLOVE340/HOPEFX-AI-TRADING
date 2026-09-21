# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
tests/unit/test_ml_evaluation_reports.py
========================================
`ml/evaluation/__init__.py` was at **0.00 %** — 62 statements, nothing reached.

It is the loader for the JSON evaluation reports the training pipeline writes:
the accuracy, F1, precision and recall a human reads to decide whether a
retrained model is fit to serve. Every accessor, every parse, and every one of
its three "return None / skip / carry on" degradation paths was unverified.

The ordering contract is the part worth pinning. `list_evaluations` sorts on
the `YYYYMMDD_HHMMSS` string lifted out of the filename, which is
lexicographically ordered *because* of that format, and
`load_latest_evaluation` then takes the last entry. Anything that changes the
filename format — a different separator, a locale date, a bare epoch — silently
reorders the list and starts returning an older report as "latest", which is
the one failure mode of this module that would not look like an error.
"""

from __future__ import annotations

import json

import pytest

import ml.evaluation as eval_mod
from ml.evaluation import (
    EvaluationReport,
    list_evaluations,
    load_all_evaluations,
    load_latest_evaluation,
)

pytestmark = pytest.mark.unit


@pytest.fixture
def eval_dir(tmp_path, monkeypatch):
    """Point the module at an empty directory we control."""
    monkeypatch.setattr(eval_mod, "_EVAL_DIR", tmp_path)
    return tmp_path


def _write(directory, model, ts, **payload):
    body = {
        "model_name": model,
        "timestamp": ts,
        "metrics": {"accuracy": 0.7, "f1": 0.65, "precision": 0.68, "recall": 0.62},
        "predictions_sample": {"y_true": [1, 0], "y_pred": [1, 0]},
    }
    body.update(payload)
    path = directory / f"{model}_evaluation_{ts}.json"
    path.write_text(json.dumps(body))
    return path


# ── the report record ─────────────────────────────────────────────────────────


class TestEvaluationReport:
    def test_the_metric_accessors_read_the_metrics_dict(self):
        report = EvaluationReport(
            model_name="XGBoost",
            timestamp="20260101_120000",
            metrics={"accuracy": 0.81, "f1": 0.77, "precision": 0.79, "recall": 0.75},
        )

        assert report.accuracy == pytest.approx(0.81)
        assert report.f1 == pytest.approx(0.77)
        assert report.precision == pytest.approx(0.79)
        assert report.recall == pytest.approx(0.75)

    def test_a_missing_metric_reads_as_zero_rather_than_raising(self):
        """A partial report must still render on the dashboard."""
        report = EvaluationReport(model_name="m", timestamp="t", metrics={})

        assert report.accuracy == 0.0
        assert report.f1 == 0.0
        assert report.precision == 0.0
        assert report.recall == 0.0

    def test_a_string_metric_is_coerced_to_float(self):
        report = EvaluationReport(model_name="m", timestamp="t", metrics={"accuracy": "0.5"})

        assert report.accuracy == pytest.approx(0.5)

    def test_the_collections_default_to_empty_rather_than_shared(self):
        first = EvaluationReport(model_name="a", timestamp="t")
        second = EvaluationReport(model_name="b", timestamp="t")
        first.metrics["accuracy"] = 1.0

        assert second.metrics == {}

    def test_to_dict_round_trips_through_json(self):
        report = EvaluationReport(
            model_name="XGBoost",
            timestamp="20260101_120000",
            metrics={"accuracy": 0.81},
            predictions_sample={"y_true": [1]},
            source_file="/tmp/x.json",
        )

        payload = report.to_dict()

        assert json.loads(json.dumps(payload)) == payload
        assert payload["source_file"] == "/tmp/x.json"

    def test_the_source_file_defaults_to_empty(self):
        assert EvaluationReport(model_name="m", timestamp="t").source_file == ""


# ── listing ───────────────────────────────────────────────────────────────────


class TestListEvaluations:
    def test_an_empty_directory_lists_nothing(self, eval_dir):
        assert list_evaluations("XGBoost") == []

    def test_it_finds_a_matching_report(self, eval_dir):
        _write(eval_dir, "XGBoost", "20260101_120000")

        found = list_evaluations("XGBoost")

        assert len(found) == 1
        assert found[0][0] == "20260101_120000"

    def test_it_ignores_other_models(self, eval_dir):
        _write(eval_dir, "XGBoost", "20260101_120000")
        _write(eval_dir, "LSTM", "20260101_120000")

        assert len(list_evaluations("XGBoost")) == 1

    def test_it_ignores_unrelated_files(self, eval_dir):
        _write(eval_dir, "XGBoost", "20260101_120000")
        (eval_dir / "XGBoost_predictions.csv").write_text("a,b\n")
        (eval_dir / "feature_importance.png").write_bytes(b"\x89PNG")

        assert len(list_evaluations("XGBoost")) == 1

    def test_results_are_ordered_oldest_first(self, eval_dir):
        _write(eval_dir, "XGBoost", "20260301_090000")
        _write(eval_dir, "XGBoost", "20260101_120000")
        _write(eval_dir, "XGBoost", "20260201_235959")

        stamps = [ts for ts, _p in list_evaluations("XGBoost")]

        assert stamps == ["20260101_120000", "20260201_235959", "20260301_090000"]

    def test_same_day_reports_order_by_time(self, eval_dir):
        _write(eval_dir, "XGBoost", "20260101_235959")
        _write(eval_dir, "XGBoost", "20260101_000001")

        stamps = [ts for ts, _p in list_evaluations("XGBoost")]

        assert stamps == ["20260101_000001", "20260101_235959"]

    def test_a_filename_without_a_timestamp_sorts_oldest(self, eval_dir):
        """It gets a zero stamp, so it can never masquerade as the latest."""
        (eval_dir / "XGBoost_evaluation_.json").write_text("{}")
        _write(eval_dir, "XGBoost", "20260101_120000")

        stamps = [ts for ts, _p in list_evaluations("XGBoost")]

        assert stamps[-1] == "20260101_120000"

    def test_each_entry_carries_a_real_path(self, eval_dir):
        _write(eval_dir, "XGBoost", "20260101_120000")

        _ts, path = list_evaluations("XGBoost")[0]

        assert path.exists()


# ── loading the latest ────────────────────────────────────────────────────────


class TestLoadLatestEvaluation:
    def test_nothing_on_disk_is_none_rather_than_an_error(self, eval_dir):
        assert load_latest_evaluation("XGBoost") is None

    def test_it_loads_the_single_report(self, eval_dir):
        _write(eval_dir, "XGBoost", "20260101_120000")

        report = load_latest_evaluation("XGBoost")

        assert report.model_name == "XGBoost"
        assert report.accuracy == pytest.approx(0.7)

    def test_it_returns_the_newest_of_several(self, eval_dir):
        _write(eval_dir, "XGBoost", "20260101_120000", metrics={"accuracy": 0.5})
        _write(eval_dir, "XGBoost", "20260301_090000", metrics={"accuracy": 0.9})
        _write(eval_dir, "XGBoost", "20260201_090000", metrics={"accuracy": 0.7})

        assert load_latest_evaluation("XGBoost").accuracy == pytest.approx(0.9)

    def test_the_source_file_is_recorded(self, eval_dir):
        path = _write(eval_dir, "XGBoost", "20260101_120000")

        assert load_latest_evaluation("XGBoost").source_file == str(path)

    def test_a_missing_model_name_falls_back_to_the_requested_one(self, eval_dir):
        (eval_dir / "XGBoost_evaluation_20260101_120000.json").write_text(json.dumps({"metrics": {}}))

        assert load_latest_evaluation("XGBoost").model_name == "XGBoost"

    def test_a_missing_timestamp_falls_back_to_the_filename_stamp(self, eval_dir):
        (eval_dir / "XGBoost_evaluation_20260101_120000.json").write_text(json.dumps({"metrics": {}}))

        assert load_latest_evaluation("XGBoost").timestamp == "20260101_120000"

    def test_missing_sections_default_to_empty(self, eval_dir):
        (eval_dir / "XGBoost_evaluation_20260101_120000.json").write_text(json.dumps({}))

        report = load_latest_evaluation("XGBoost")

        assert report.metrics == {}
        assert report.predictions_sample == {}

    def test_corrupt_json_is_none_rather_than_a_traceback(self, eval_dir):
        """A half-written report from an interrupted training run."""
        (eval_dir / "XGBoost_evaluation_20260101_120000.json").write_text("{ not json")

        assert load_latest_evaluation("XGBoost") is None

    def test_a_corrupt_newest_report_does_not_silently_serve_an_older_one(self, eval_dir):
        """Returning stale metrics as current is worse than returning nothing."""
        _write(eval_dir, "XGBoost", "20260101_120000", metrics={"accuracy": 0.9})
        (eval_dir / "XGBoost_evaluation_20260301_090000.json").write_text("{ broken")

        assert load_latest_evaluation("XGBoost") is None


# ── loading the history ───────────────────────────────────────────────────────


class TestLoadAllEvaluations:
    def test_nothing_on_disk_is_an_empty_list(self, eval_dir):
        assert load_all_evaluations("XGBoost") == []

    def test_it_returns_every_report_oldest_first(self, eval_dir):
        _write(eval_dir, "XGBoost", "20260301_090000", metrics={"accuracy": 0.9})
        _write(eval_dir, "XGBoost", "20260101_120000", metrics={"accuracy": 0.5})

        accuracies = [r.accuracy for r in load_all_evaluations("XGBoost")]

        assert accuracies == [pytest.approx(0.5), pytest.approx(0.9)]

    def test_a_corrupt_report_is_skipped_not_fatal(self, eval_dir):
        """One bad file must not hide the rest of the training history."""
        _write(eval_dir, "XGBoost", "20260101_120000")
        (eval_dir / "XGBoost_evaluation_20260201_090000.json").write_text("{ broken")
        _write(eval_dir, "XGBoost", "20260301_090000")

        assert len(load_all_evaluations("XGBoost")) == 2

    def test_every_entry_is_a_report(self, eval_dir):
        _write(eval_dir, "XGBoost", "20260101_120000")

        assert all(isinstance(r, EvaluationReport) for r in load_all_evaluations("XGBoost"))

    def test_the_history_is_json_serialisable(self, eval_dir):
        _write(eval_dir, "XGBoost", "20260101_120000")

        json.dumps([r.to_dict() for r in load_all_evaluations("XGBoost")])


class TestThePublicSurface:
    def test_everything_named_in_all_is_importable(self):
        for name in eval_mod.__all__:
            assert hasattr(eval_mod, name), name

    def test_the_default_directory_is_the_package_itself(self):
        assert eval_mod._EVAL_DIR.name == "evaluation"

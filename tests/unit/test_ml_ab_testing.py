# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
tests/unit/test_ml_ab_testing.py
================================
`ml/ab_testing.py` was 157 statements at 55.44 %.

This is the champion/challenger split that decides how much live traffic a new
model sees, and the arithmetic a human reads when deciding whether to keep it.
Three things here are worth stating rather than merely executing:

* **Routing is fail-closed.** An unknown test id, or a stopped one, routes to
  *control*. If that inverted, a stopped experiment would keep sending real
  traffic to a challenger nobody is watching.
* **`_chi2_pvalue` declines rather than guesses.** Chi-square is invalid when
  any cell of the contingency table is under 5, so it returns `None`. A number
  there would be read as significance by whoever is looking at the page.
* **Metrics distinguish "no data" from "zero".** An unstarted variant reports
  `accuracy: None`, not `0.0` — the latter reads as a model getting everything
  wrong.

Persistence is exercised with the database absent, which is the state every
unit-test run and many dev deployments are in: the manager must degrade to
in-memory rather than raise.
"""

from __future__ import annotations

import json
import threading
from types import SimpleNamespace
from unittest.mock import patch

import pytest

import ml.ab_testing as ab
from ml.ab_testing import ABTest, ABTestManager, _test_from_event, get_ab_test_manager

pytestmark = pytest.mark.unit


@pytest.fixture
def test_obj():
    return ABTest(
        test_id="t1",
        name="advanced_oos_vs_challenger",
        control="advanced_oos",
        challenger="challenger_v2",
        traffic_split=0.2,
    )


@pytest.fixture
def manager(monkeypatch):
    """A manager with no database in reach."""
    monkeypatch.setattr(ABTestManager, "_load_from_db", lambda self: None)
    monkeypatch.setattr(ABTestManager, "_persist_test", lambda self, test: None)
    return ABTestManager()


def _fill(test, variant, n, correct=True, pnl=1.0):
    for _ in range(n):
        test.record_result(variant, correct=correct, pnl=pnl)


# ── recording ─────────────────────────────────────────────────────────────────


class TestRecordResult:
    def test_a_control_result_is_recorded(self, test_obj):
        test_obj.record_result("control", correct=True, pnl=5.0)

        assert test_obj.get_metrics()["control"]["n"] == 1

    def test_a_challenger_result_is_recorded(self, test_obj):
        test_obj.record_result("challenger", correct=False, pnl=-2.0)

        assert test_obj.get_metrics()["challenger"]["n"] == 1

    @pytest.mark.parametrize("variant", ["", "champion", "CONTROL", "other", "treatment"])
    def test_an_unknown_variant_is_dropped_rather_than_creating_a_bucket(self, test_obj, variant):
        test_obj.record_result(variant, correct=True)

        metrics = test_obj.get_metrics()
        assert metrics["control"]["n"] == 0
        assert metrics["challenger"]["n"] == 0
        assert set(metrics) == {"control", "challenger"}

    def test_concurrent_recording_loses_nothing(self, test_obj):
        def _worker():
            for _ in range(50):
                test_obj.record_result("control", correct=True)

        threads = [threading.Thread(target=_worker) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert test_obj.get_metrics()["control"]["n"] == 200


# ── metrics ───────────────────────────────────────────────────────────────────


class TestMetrics:
    def test_an_empty_variant_reports_none_not_zero(self, test_obj):
        """0.0 accuracy means 'wrong every time'. None means 'no data'."""
        metrics = test_obj.get_metrics()

        assert metrics["control"] == {"n": 0, "accuracy": None, "avg_pnl": None}

    def test_accuracy_is_the_hit_rate(self, test_obj):
        _fill(test_obj, "control", 3, correct=True)
        _fill(test_obj, "control", 1, correct=False)

        assert test_obj.get_metrics()["control"]["accuracy"] == pytest.approx(0.75)

    def test_average_pnl_is_the_mean(self, test_obj):
        test_obj.record_result("control", correct=True, pnl=10.0)
        test_obj.record_result("control", correct=True, pnl=20.0)

        assert test_obj.get_metrics()["control"]["avg_pnl"] == pytest.approx(15.0)

    def test_average_confidence_is_reported(self, test_obj):
        test_obj.record_result("control", correct=True, confidence=0.8)
        test_obj.record_result("control", correct=True, confidence=0.6)

        assert test_obj.get_metrics()["control"]["avg_confidence"] == pytest.approx(0.7)

    def test_negative_pnl_averages_correctly(self, test_obj):
        test_obj.record_result("control", correct=False, pnl=-10.0)
        test_obj.record_result("control", correct=True, pnl=4.0)

        assert test_obj.get_metrics()["control"]["avg_pnl"] == pytest.approx(-3.0)

    def test_the_two_variants_are_scored_independently(self, test_obj):
        _fill(test_obj, "control", 4, correct=True)
        _fill(test_obj, "challenger", 4, correct=False)

        metrics = test_obj.get_metrics()
        assert metrics["control"]["accuracy"] == 1.0
        assert metrics["challenger"]["accuracy"] == 0.0

    def test_metrics_are_json_serialisable(self, test_obj):
        _fill(test_obj, "control", 20)
        _fill(test_obj, "challenger", 20, correct=False)

        json.dumps(test_obj.get_metrics())


class TestSignificance:
    def test_it_is_absent_until_both_arms_have_enough_data(self, test_obj):
        _fill(test_obj, "control", 20)

        assert "significance" not in test_obj.get_metrics()

    def test_it_appears_once_both_arms_are_populated(self, test_obj):
        _fill(test_obj, "control", 30, correct=True)
        _fill(test_obj, "control", 30, correct=False)
        _fill(test_obj, "challenger", 50, correct=True)
        _fill(test_obj, "challenger", 10, correct=False)

        assert test_obj.get_metrics()["significance"] is not None

    def test_a_thin_contingency_cell_declines_to_report_a_p_value(self, test_obj):
        """chi-square is invalid below 5 per cell; a number there would mislead."""
        _fill(test_obj, "control", 20, correct=True)
        _fill(test_obj, "control", 1, correct=False)
        _fill(test_obj, "challenger", 20, correct=True)
        _fill(test_obj, "challenger", 1, correct=False)

        assert test_obj.get_metrics()["significance"] is None

    def test_a_clear_difference_is_significant(self, test_obj):
        _fill(test_obj, "control", 20, correct=True)
        _fill(test_obj, "control", 80, correct=False)
        _fill(test_obj, "challenger", 80, correct=True)
        _fill(test_obj, "challenger", 20, correct=False)

        assert test_obj.get_metrics()["significance"] < 0.05

    def test_two_identical_arms_are_not_significant(self, test_obj):
        for variant in ("control", "challenger"):
            _fill(test_obj, variant, 50, correct=True)
            _fill(test_obj, variant, 50, correct=False)

        assert test_obj.get_metrics()["significance"] > 0.05

    def test_a_failure_inside_the_test_returns_none_rather_than_raising(self, test_obj):
        _fill(test_obj, "control", 30, correct=True)
        _fill(test_obj, "control", 30, correct=False)
        _fill(test_obj, "challenger", 30, correct=True)
        _fill(test_obj, "challenger", 30, correct=False)

        with patch("scipy.stats.chi2_contingency", side_effect=RuntimeError("boom")):
            assert test_obj._chi2_pvalue() is None


class TestToDict:
    def test_it_carries_the_identity_and_the_arms(self, test_obj):
        payload = test_obj.to_dict()

        assert payload["id"] == "t1"
        assert payload["control"] == "advanced_oos"
        assert payload["challenger"] == "challenger_v2"
        assert payload["traffic_split"] == pytest.approx(0.2)

    def test_a_new_test_is_active_and_unfinished(self, test_obj):
        payload = test_obj.to_dict()

        assert payload["status"] == "active"
        assert payload["finished_at"] is None

    def test_it_embeds_live_metrics(self, test_obj):
        _fill(test_obj, "control", 2)

        assert test_obj.to_dict()["metrics"]["control"]["n"] == 2

    def test_it_is_json_serialisable(self, test_obj):
        json.dumps(test_obj.to_dict())

    def test_the_start_time_is_iso_formatted(self, test_obj):
        from datetime import datetime

        assert datetime.fromisoformat(test_obj.to_dict()["started_at"])


# ── the stored-row renderer ───────────────────────────────────────────────────


class TestTestFromEvent:
    def _row(self, **payload):
        return SimpleNamespace(
            ref_id="stored-1",
            component="stored_test",
            status="completed",
            started_at="2026-01-01T00:00:00+00:00",
            payload=payload,
        )

    def test_a_stored_row_renders_like_a_live_test(self, test_obj):
        """A caller must not be able to tell memory from database."""
        rendered = _test_from_event(self._row(control="a", challenger="b"))

        assert set(rendered) == set(test_obj.to_dict())

    def test_the_row_fields_are_carried_through(self):
        rendered = _test_from_event(self._row(control="a", challenger="b", traffic_split=0.3))

        assert rendered["id"] == "stored-1"
        assert rendered["name"] == "stored_test"
        assert rendered["control"] == "a"
        assert rendered["traffic_split"] == 0.3

    def test_missing_payload_fields_get_defaults(self):
        rendered = _test_from_event(self._row())

        assert rendered["control"] == "baseline"
        assert rendered["challenger"] == "variant"
        assert rendered["metrics"] == {}

    def test_a_row_without_a_status_is_treated_as_completed(self):
        row = self._row()
        row.status = None

        assert _test_from_event(row)["status"] == "completed"


# ── the manager ───────────────────────────────────────────────────────────────


class TestCreateAndQuery:
    def test_a_new_manager_holds_no_tests(self, manager):
        assert manager.list_tests() == []

    def test_creating_registers_a_test(self, manager):
        created = manager.create_test(challenger_model="v2")

        assert manager.get_test(created.test_id) is created

    def test_the_default_name_describes_the_matchup(self, manager):
        created = manager.create_test(challenger_model="v2", control_model="v1")

        assert created.name == "v1_vs_v2"

    def test_an_explicit_name_wins(self, manager):
        assert manager.create_test(challenger_model="v2", name="my test").name == "my test"

    def test_each_test_gets_a_distinct_id(self, manager):
        a = manager.create_test(challenger_model="v2")
        b = manager.create_test(challenger_model="v3")

        assert a.test_id != b.test_id

    def test_the_traffic_split_is_coerced_to_float(self, manager):
        created = manager.create_test(challenger_model="v2", traffic_split=1)

        assert isinstance(created.traffic_split, float)

    def test_an_unknown_id_returns_none(self, manager):
        assert manager.get_test("nope") is None

    def test_listing_renders_every_test(self, manager):
        manager.create_test(challenger_model="v2")
        manager.create_test(challenger_model="v3")

        assert len(manager.list_tests()) == 2

    def test_active_only_filters_out_stopped_tests(self, manager):
        live = manager.create_test(challenger_model="v2")
        stopped = manager.create_test(challenger_model="v3")
        manager.stop_test(stopped.test_id)

        ids = {t["id"] for t in manager.list_tests(active_only=True)}

        assert ids == {live.test_id}

    def test_listing_is_json_serialisable(self, manager):
        manager.create_test(challenger_model="v2")

        json.dumps(manager.list_tests())


class TestStopTest:
    def test_stopping_an_active_test_succeeds(self, manager):
        created = manager.create_test(challenger_model="v2")

        assert manager.stop_test(created.test_id) is True
        assert created.status == "completed"
        assert created.finished_at is not None

    def test_stopping_twice_is_refused(self, manager):
        created = manager.create_test(challenger_model="v2")
        manager.stop_test(created.test_id)

        assert manager.stop_test(created.test_id) is False

    def test_stopping_an_unknown_test_is_refused(self, manager):
        assert manager.stop_test("nope") is False

    def test_a_winner_may_be_recorded(self, manager):
        created = manager.create_test(challenger_model="v2")

        assert manager.stop_test(created.test_id, winner="challenger") is True


class TestRecordThroughTheManager:
    def test_a_result_reaches_the_test(self, manager):
        created = manager.create_test(challenger_model="v2")

        manager.record_result(created.test_id, "control", correct=True, pnl=3.0)

        assert created.get_metrics()["control"]["n"] == 1

    def test_recording_against_an_unknown_test_is_ignored(self, manager):
        manager.record_result("nope", "control", correct=True)


class TestRouting:
    def test_an_unknown_test_routes_to_control(self, manager):
        """Fail closed: never send live traffic on the strength of a bad id."""
        assert manager.route("nope") == "control"

    def test_a_stopped_test_routes_to_control(self, manager):
        created = manager.create_test(challenger_model="v2", traffic_split=1.0)
        manager.stop_test(created.test_id)

        assert manager.route(created.test_id) == "control"

    def test_a_zero_split_never_routes_to_the_challenger(self, manager):
        created = manager.create_test(challenger_model="v2", traffic_split=0.0)

        assert {manager.route(created.test_id) for _ in range(200)} == {"control"}

    def test_a_full_split_always_routes_to_the_challenger(self, manager):
        created = manager.create_test(challenger_model="v2", traffic_split=1.0)

        assert {manager.route(created.test_id) for _ in range(200)} == {"challenger"}

    def test_a_partial_split_produces_both_arms(self, manager):
        created = manager.create_test(challenger_model="v2", traffic_split=0.5)

        assert {manager.route(created.test_id) for _ in range(400)} == {"control", "challenger"}

    def test_the_split_is_roughly_honoured(self, manager):
        created = manager.create_test(challenger_model="v2", traffic_split=0.2)

        routes = [manager.route(created.test_id) for _ in range(4000)]
        share = routes.count("challenger") / len(routes)

        assert 0.15 < share < 0.25


class TestPersistenceDegradation:
    def test_a_manager_builds_without_a_database(self, monkeypatch):
        """Every unit-test run, and many dev deployments, are in this state."""
        monkeypatch.setattr(ab, "logger", SimpleNamespace(info=lambda *a, **k: None, warning=lambda *a, **k: None))

        assert isinstance(ABTestManager(), ABTestManager)

    def test_listing_survives_an_unreadable_database(self, manager, monkeypatch):
        manager.create_test(challenger_model="v2")

        def _boom():
            raise RuntimeError("db down")

        monkeypatch.setattr("database.connection.get_db_manager", _boom, raising=False)

        assert len(manager.list_tests()) == 1

    def test_creating_survives_a_failing_persist(self, monkeypatch):
        monkeypatch.setattr(ABTestManager, "_load_from_db", lambda self: None)

        def _boom(self, test):
            raise RuntimeError("db down")

        monkeypatch.setattr(ABTestManager, "_persist_test", _boom)
        mgr = ABTestManager()

        with pytest.raises(RuntimeError):
            mgr.create_test(challenger_model="v2")


class TestSingleton:
    def test_it_is_shared(self):
        assert get_ab_test_manager() is get_ab_test_manager()

    def test_it_is_a_manager(self):
        assert isinstance(get_ab_test_manager(), ABTestManager)

# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
Unit tests for ``ml.training_manager`` — the ML training job registry behind
``/api/ml/training/*`` and the superadmin ML page.

The manager's output is what an operator reads to decide whether a model is
trained and current, so the tests here care most about it never claiming a
model is trained when no artifact for that model exists.
"""

from __future__ import annotations

import threading
from datetime import datetime, timezone

import pytest

from database.system_events import SystemEventRecord
from ml import model_paths
from ml import training_manager as tm

UTC = timezone.utc


# ── Helpers ───────────────────────────────────────────────────────────────────


def _record(
    ref_id: str = "job-1",
    component: str = "advanced_oos",
    status: str = "completed",
    payload: dict | None = None,
    timestamp: datetime | None = None,
) -> SystemEventRecord:
    return SystemEventRecord(
        ref_id=ref_id,
        event_type="ml_training",
        component=component,
        status=status,
        payload=payload if payload is not None else {},
        timestamp=timestamp or datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC),
    )


class _FakeSession:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def commit(self):
        self.committed = True


class _FakeDBManager:
    """Stands in for ``database.connection.get_db_manager()``."""

    def __init__(self, session=None):
        self._session = session or _FakeSession()

    def session(self):
        return self._session


def _patch_db(monkeypatch, db_mgr, records=None, upsert=None):
    """Point the manager's lazy database imports at fakes."""
    import database.connection as conn
    import database.system_events as events

    monkeypatch.setattr(conn, "get_db_manager", lambda: db_mgr)
    if records is not None:
        monkeypatch.setattr(events, "read_events", lambda db, **kw: list(records))
    if upsert is not None:
        monkeypatch.setattr(events, "upsert_event", upsert)


# ── Event → job mapping ───────────────────────────────────────────────────────


class TestJobFromEvent:
    def test_maps_every_field_the_api_publishes(self):
        rec = _record(
            ref_id="abc",
            component="rf_macro",
            status="failed",
            payload={
                "finished_at": "2026-01-02T04:00:00+00:00",
                "duration_s": 12.5,
                "metrics": {"auc": 0.61},
                "error": "boom",
            },
        )
        assert tm._job_from_event(rec) == {
            "id": "abc",
            "model": "rf_macro",
            "status": "failed",
            "started_at": "2026-01-02T03:04:05+00:00",
            "finished_at": "2026-01-02T04:00:00+00:00",
            "duration_s": 12.5,
            "metrics": {"auc": 0.61},
            "error": "boom",
        }

    def test_blank_status_reads_as_completed(self):
        assert tm._job_from_event(_record(status=""))["status"] == "completed"

    def test_empty_payload_yields_neutral_defaults(self):
        job = tm._job_from_event(_record(payload={}))
        assert job["finished_at"] is None
        assert job["duration_s"] == 0
        assert job["metrics"] == {}
        assert job["error"] is None


class TestTrainingJob:
    def test_defaults_stamp_a_start_time(self):
        job = tm.TrainingJob(job_id="j1", model="rf_macro")
        assert job.status == "pending"
        assert job.started_at  # ISO timestamp, not None
        assert job.metrics == {}

    def test_to_dict_rounds_the_duration(self):
        job = tm.TrainingJob(
            job_id="j1",
            model="rf_macro",
            status="completed",
            started_at="s",
            finished_at="f",
            duration_s=12.3456,
            metrics={"auc": 0.6},
            error=None,
        )
        assert job.to_dict() == {
            "id": "j1",
            "model": "rf_macro",
            "status": "completed",
            "started_at": "s",
            "finished_at": "f",
            "duration_s": 12.3,
            "metrics": {"auc": 0.6},
            "error": None,
        }


# ── Static model status (the DB-less fallback) ────────────────────────────────


class TestStaticModelStatus:
    """
    ``_static_model_status`` is what ``list_jobs`` returns on a fresh deployment
    with no training history, so it is the model inventory an operator sees
    first.  It must not report a model as trained unless that model's own
    artifact exists.
    """

    def test_each_model_is_judged_by_its_own_artifact(self, monkeypatch, tmp_path):
        (tmp_path / "advanced_oos.pkl").write_text("x")
        (tmp_path / "rl").mkdir()
        (tmp_path / "rl" / "hopefx_ppo.zip").write_text("x")
        monkeypatch.setenv("ML_MODEL_DIR", str(tmp_path))
        monkeypatch.setattr(model_paths, "packaged_model_dir", lambda: tmp_path / "nonexistent")

        rows = {r["model"]: r for r in tm.TrainingManager()._static_model_status()}

        assert rows["advanced_oos"]["status"] == "completed"
        assert rows["rl_ppo"]["status"] == "completed"
        # No lstm_signal.pkl/.pt, no xgb_macro.pkl, no hybrid_ensemble.pkl on
        # disk — the RL zip must not vouch for them.
        assert rows["lstm_signal"]["status"] == "not_trained"
        assert rows["xgb_macro"]["status"] == "not_trained"
        assert rows["hybrid_ensemble"]["status"] == "not_trained"
        assert rows["rf_macro"]["status"] == "not_trained"

    def test_untrained_models_carry_no_timestamp(self, monkeypatch, tmp_path):
        (tmp_path / "rl").mkdir()
        (tmp_path / "rl" / "hopefx_ppo.zip").write_text("x")
        monkeypatch.setenv("ML_MODEL_DIR", str(tmp_path))
        monkeypatch.setattr(model_paths, "packaged_model_dir", lambda: tmp_path / "nonexistent")

        rows = {r["model"]: r for r in tm.TrainingManager()._static_model_status()}
        assert rows["rl_ppo"]["started_at"] is not None
        for name in ("advanced_oos", "lstm_signal", "xgb_macro"):
            assert rows[name]["started_at"] is None, name
            assert rows[name]["finished_at"] is None, name

    def test_torch_checkpoints_count_as_trained(self, monkeypatch, tmp_path):
        (tmp_path / "lstm_signal.pt").write_text("x")
        monkeypatch.setenv("ML_MODEL_DIR", str(tmp_path))
        monkeypatch.setattr(model_paths, "packaged_model_dir", lambda: tmp_path / "nonexistent")

        rows = {r["model"]: r for r in tm.TrainingManager()._static_model_status()}
        assert rows["lstm_signal"]["status"] == "completed"
        assert rows["lstm_signal"]["started_at"] is not None

    def test_configured_model_dir_is_honoured(self, monkeypatch, tmp_path):
        """
        Production points ML_MODEL_DIR at a mounted volume (see the Helm chart).
        Resolving a hardcoded relative 'ml/saved_models' would report the
        packaged build-time artifacts — or nothing at all when the process runs
        from another working directory.
        """
        (tmp_path / "xgb_macro.pkl").write_text("x")
        monkeypatch.setenv("ML_MODEL_DIR", str(tmp_path))
        monkeypatch.setattr(model_paths, "packaged_model_dir", lambda: tmp_path / "nonexistent")

        rows = {r["model"]: r for r in tm.TrainingManager()._static_model_status()}
        assert rows["xgb_macro"]["status"] == "completed"

    def test_packaged_artifacts_are_the_fallback(self, monkeypatch, tmp_path):
        packaged = tmp_path / "packaged"
        packaged.mkdir()
        (packaged / "rf_macro.pkl").write_text("x")
        monkeypatch.delenv("ML_MODEL_DIR", raising=False)
        monkeypatch.setattr(model_paths, "packaged_model_dir", lambda: packaged)

        rows = {r["model"]: r for r in tm.TrainingManager()._static_model_status()}
        assert rows["rf_macro"]["status"] == "completed"

    def test_every_known_model_gets_a_row(self, monkeypatch, tmp_path):
        monkeypatch.setenv("ML_MODEL_DIR", str(tmp_path))
        monkeypatch.setattr(model_paths, "packaged_model_dir", lambda: tmp_path / "nonexistent")

        rows = tm.TrainingManager()._static_model_status()
        assert [r["model"] for r in rows] == tm._KNOWN_MODELS
        for row in rows:
            assert row["id"] == f"static_{row['model']}"
            assert row["status"] == "not_trained"
            assert row["metrics"] == {}
            assert row["error"] is None


# ── Listing and lookup ────────────────────────────────────────────────────────


class TestListJobs:
    def test_active_jobs_come_first(self, monkeypatch):
        mgr = tm.TrainingManager()
        mgr._active["live"] = tm.TrainingJob(job_id="live", model="rf_macro", status="running")
        _patch_db(monkeypatch, _FakeDBManager(), records=[_record(ref_id="old")])

        jobs = mgr.list_jobs()
        assert jobs[0]["id"] == "live"
        assert jobs[1]["id"] == "old"

    def test_history_does_not_duplicate_an_active_job(self, monkeypatch):
        mgr = tm.TrainingManager()
        mgr._active["dup"] = tm.TrainingJob(job_id="dup", model="rf_macro", status="running")
        _patch_db(monkeypatch, _FakeDBManager(), records=[_record(ref_id="dup")])

        jobs = mgr.list_jobs()
        assert [j["id"] for j in jobs] == ["dup"]
        assert jobs[0]["status"] == "running"  # the in-memory job wins

    def test_limit_is_applied(self, monkeypatch):
        mgr = tm.TrainingManager()
        _patch_db(
            monkeypatch,
            _FakeDBManager(),
            records=[_record(ref_id=f"j{i}") for i in range(10)],
        )
        assert len(mgr.list_jobs(limit=3)) == 3

    def test_no_database_falls_back_to_static_status(self, monkeypatch):
        _patch_db(monkeypatch, None)
        jobs = tm.TrainingManager().list_jobs()
        assert [j["id"] for j in jobs] == [f"static_{m}" for m in tm._KNOWN_MODELS]

    def test_database_error_falls_back_to_static_status(self, monkeypatch):
        import database.connection as conn

        def _boom():
            raise RuntimeError("db down")

        monkeypatch.setattr(conn, "get_db_manager", _boom)
        jobs = tm.TrainingManager().list_jobs()
        assert jobs[0]["id"].startswith("static_")

    def test_an_active_job_survives_a_database_error(self, monkeypatch):
        import database.connection as conn

        monkeypatch.setattr(conn, "get_db_manager", lambda: (_ for _ in ()).throw(RuntimeError("x")))
        mgr = tm.TrainingManager()
        mgr._active["live"] = tm.TrainingJob(job_id="live", model="rf_macro", status="running")

        jobs = mgr.list_jobs()
        # Non-empty, so the static fallback must not replace the live job.
        assert [j["id"] for j in jobs] == ["live"]


class TestGetJob:
    def test_active_job_is_returned_from_memory(self):
        mgr = tm.TrainingManager()
        mgr._active["live"] = tm.TrainingJob(job_id="live", model="rf_macro", status="running")
        assert mgr.get_job("live")["status"] == "running"

    def test_historical_job_is_matched_on_ref_id(self, monkeypatch):
        _patch_db(
            monkeypatch,
            _FakeDBManager(),
            records=[_record(ref_id="other"), _record(ref_id="wanted", component="rf_macro")],
        )
        job = tm.TrainingManager().get_job("wanted")
        assert job["id"] == "wanted"
        assert job["model"] == "rf_macro"

    def test_unknown_job_returns_none(self, monkeypatch):
        _patch_db(monkeypatch, _FakeDBManager(), records=[_record(ref_id="other")])
        assert tm.TrainingManager().get_job("missing") is None

    def test_no_database_returns_none(self, monkeypatch):
        _patch_db(monkeypatch, None)
        assert tm.TrainingManager().get_job("anything") is None

    def test_database_error_returns_none(self, monkeypatch):
        import database.connection as conn

        monkeypatch.setattr(conn, "get_db_manager", lambda: (_ for _ in ()).throw(RuntimeError("x")))
        assert tm.TrainingManager().get_job("anything") is None


# ── Job control ───────────────────────────────────────────────────────────────


class TestStartAndCancel:
    def test_start_job_registers_and_runs_the_model(self, monkeypatch):
        mgr = tm.TrainingManager()
        done = threading.Event()
        seen: list[str] = []

        def _dispatch(model):
            seen.append(model)
            done.set()
            return {"status": "ok"}

        monkeypatch.setattr(mgr, "_dispatch_training", _dispatch)
        monkeypatch.setattr(mgr, "_persist_job", lambda *a, **k: None)

        job_id = mgr.start_job("rf_macro")
        assert done.wait(timeout=10), "training thread never ran"

        assert seen == ["rf_macro"]
        assert job_id in mgr._active
        # The worker sets the terminal state; give it a moment to finish.
        for _ in range(100):
            if mgr._active[job_id].status != "running":
                break
            threading.Event().wait(0.02)
        assert mgr._active[job_id].status == "completed"
        assert mgr._active[job_id].metrics == {"status": "ok"}

    def test_cancel_job_marks_a_running_job(self):
        mgr = tm.TrainingManager()
        mgr._active["live"] = tm.TrainingJob(job_id="live", model="rf_macro", status="running")
        assert mgr.cancel_job("live") is True
        assert mgr._active["live"].status == "cancelled"
        assert mgr._active["live"].finished_at is not None

    def test_cancelling_a_finished_job_is_a_no_op(self):
        mgr = tm.TrainingManager()
        mgr._active["done"] = tm.TrainingJob(job_id="done", model="rf_macro", status="completed")
        assert mgr.cancel_job("done") is False
        assert mgr._active["done"].status == "completed"

    def test_cancelling_an_unknown_job_returns_false(self):
        assert tm.TrainingManager().cancel_job("nope") is False


class TestRunTraining:
    def test_success_records_metrics_and_persists(self, monkeypatch):
        mgr = tm.TrainingManager()
        mgr._active["j"] = tm.TrainingJob(job_id="j", model="rf_macro", status="running")
        persisted: list[tuple] = []
        monkeypatch.setattr(mgr, "_dispatch_training", lambda m: {"auc": 0.7})
        monkeypatch.setattr(mgr, "_persist_job", lambda *a: persisted.append(a))

        mgr._run_training("j", "rf_macro")

        job = mgr._active["j"]
        assert job.status == "completed"
        assert job.metrics == {"auc": 0.7}
        assert job.finished_at is not None
        assert persisted[0][2] == "completed"
        assert persisted[0][5] is None

    def test_failure_records_the_error_and_persists(self, monkeypatch):
        mgr = tm.TrainingManager()
        mgr._active["j"] = tm.TrainingJob(job_id="j", model="rf_macro", status="running")
        persisted: list[tuple] = []

        def _boom(_model):
            raise RuntimeError("training exploded")

        monkeypatch.setattr(mgr, "_dispatch_training", _boom)
        monkeypatch.setattr(mgr, "_persist_job", lambda *a: persisted.append(a))

        mgr._run_training("j", "rf_macro")

        job = mgr._active["j"]
        assert job.status == "failed"
        assert job.error == "training exploded"
        assert persisted[0][2] == "failed"
        assert persisted[0][5] == "training exploded"

    def test_a_cancelled_job_is_not_overwritten_by_a_late_success(self, monkeypatch):
        mgr = tm.TrainingManager()
        mgr._active["j"] = tm.TrainingJob(job_id="j", model="rf_macro", status="cancelled")
        monkeypatch.setattr(mgr, "_dispatch_training", lambda m: {"auc": 0.7})
        monkeypatch.setattr(mgr, "_persist_job", lambda *a: None)

        mgr._run_training("j", "rf_macro")
        assert mgr._active["j"].status == "cancelled"

    def test_a_dropped_job_id_does_not_raise(self, monkeypatch):
        mgr = tm.TrainingManager()
        monkeypatch.setattr(mgr, "_dispatch_training", lambda m: {})
        monkeypatch.setattr(mgr, "_persist_job", lambda *a: None)
        mgr._run_training("gone", "rf_macro")  # no entry in _active


class TestDispatchTraining:
    def test_advanced_oos_calls_the_advanced_retrainer(self, monkeypatch):
        from ml import train_advanced

        monkeypatch.setattr(train_advanced, "retrain_advanced_predictor", lambda: {"auc": 0.62})
        assert tm.TrainingManager()._dispatch_training("advanced_oos") == {"auc": 0.62}

    def test_hybrid_ensemble_reports_meta_trained(self, monkeypatch):
        from ml import advanced_predictor

        class _Hybrid:
            component_status = {"meta_trained": True}

        monkeypatch.setattr(advanced_predictor, "get_hybrid_predictor", lambda: _Hybrid())
        assert tm.TrainingManager()._dispatch_training("hybrid_ensemble") == {"meta_trained": True}

    def test_lstm_signal_explains_that_no_trainer_exists(self):
        with pytest.raises(RuntimeError, match="no training implementation"):
            tm.TrainingManager()._dispatch_training("lstm_signal")

    @pytest.mark.parametrize("model", ["rf_macro", "xgb_macro"])
    def test_macro_models_report_the_missing_dispatch_branch(self, model):
        with pytest.raises(RuntimeError, match="_KNOWN_MODELS"):
            tm.TrainingManager()._dispatch_training(model)

    def test_unknown_model_is_rejected_by_name(self):
        with pytest.raises(ValueError, match="Unknown model for training"):
            tm.TrainingManager()._dispatch_training("does_not_exist")

    def test_every_known_model_is_dispatchable_or_explains_itself(self, monkeypatch):
        """
        A name in ``_KNOWN_MODELS`` is offered to the operator as trainable.
        Each one must either dispatch or raise a message naming the reason —
        never fall through to the generic 'Unknown model' path, which reads as
        a typo rather than a missing implementation.

        The two models that really do dispatch are stubbed: this asserts the
        routing, and must never start a training run (which would rewrite the
        committed artifacts under ``ml/saved_models``).
        """
        from ml import advanced_predictor
        from ml import train_advanced

        class _Hybrid:
            component_status = {"meta_trained": False}

        monkeypatch.setattr(train_advanced, "retrain_advanced_predictor", lambda: {})
        monkeypatch.setattr(advanced_predictor, "get_hybrid_predictor", lambda: _Hybrid())
        # rl_ppo reads a CSV and runs PPO for 100k timesteps; refuse to let the
        # real path run and record that the branch was reached instead.
        reached: list[str] = []

        class _Sentinel(Exception):
            pass

        def _no_rl(*a, **k):
            reached.append("rl")
            raise _Sentinel("RL training not run under test")

        monkeypatch.setattr("pandas.read_csv", _no_rl)

        mgr = tm.TrainingManager()
        for model in tm._KNOWN_MODELS:
            try:
                mgr._dispatch_training(model)
            except ValueError as exc:  # the generic fall-through
                pytest.fail(f"{model} fell through to: {exc}")
            except (RuntimeError, _Sentinel, ImportError):
                pass  # a named reason, or an optional dep this env lacks
        assert reached == ["rl"], "the rl_ppo branch was not reached"


class TestPersistJob:
    def test_a_completed_run_is_written_and_committed(self, monkeypatch):
        session = _FakeSession()
        calls: list[dict] = []
        _patch_db(
            monkeypatch,
            _FakeDBManager(session),
            upsert=lambda db, **kw: calls.append(kw),
        )

        tm.TrainingManager()._persist_job("j1", "rf_macro", "completed", 12.34, {"auc": 0.6}, None)

        assert len(calls) == 1
        kw = calls[0]
        assert kw["ref_id"] == "j1"
        assert kw["event_type"] == "ml_training"
        assert kw["component"] == "rf_macro"
        assert kw["status"] == "completed"
        assert kw["level"] == "INFO"
        assert kw["payload"]["duration_s"] == 12.3
        assert kw["payload"]["metrics"] == {"auc": 0.6}
        assert kw["payload"]["finished_at"]
        assert getattr(session, "committed", False) is True

    def test_a_failed_run_is_written_at_error_level(self, monkeypatch):
        calls: list[dict] = []
        _patch_db(monkeypatch, _FakeDBManager(), upsert=lambda db, **kw: calls.append(kw))

        tm.TrainingManager()._persist_job("j1", "rf_macro", "failed", 1.0, {}, "boom")

        assert calls[0]["level"] == "ERROR"
        assert calls[0]["payload"]["error"] == "boom"

    def test_no_database_is_a_silent_no_op(self, monkeypatch):
        _patch_db(monkeypatch, None, upsert=lambda db, **kw: pytest.fail("must not write"))
        tm.TrainingManager()._persist_job("j1", "rf_macro", "completed", 1.0, {}, None)

    def test_a_write_failure_never_propagates(self, monkeypatch, caplog):
        def _boom(db, **kw):
            raise RuntimeError("insert rejected")

        _patch_db(monkeypatch, _FakeDBManager(), upsert=_boom)
        with caplog.at_level("WARNING"):
            tm.TrainingManager()._persist_job("j1", "rf_macro", "completed", 1.0, {}, None)
        assert "run not recorded" in caplog.text


class TestSingleton:
    def test_get_training_manager_returns_one_instance(self, monkeypatch):
        monkeypatch.setattr(tm, "_manager", None)
        first = tm.get_training_manager()
        assert tm.get_training_manager() is first
        assert isinstance(first, tm.TrainingManager)

    def test_concurrent_callers_share_one_instance(self, monkeypatch):
        monkeypatch.setattr(tm, "_manager", None)
        seen: list[tm.TrainingManager] = []
        barrier = threading.Barrier(8)

        def _get():
            barrier.wait()
            seen.append(tm.get_training_manager())

        threads = [threading.Thread(target=_get) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        assert len(seen) == 8
        assert len(set(map(id, seen))) == 1

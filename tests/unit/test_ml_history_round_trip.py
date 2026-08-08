# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
tests/unit/test_ml_history_round_trip.py
=========================================
The end-to-end version of the ``system_events`` fix: write a training run and an
A/B test through the real managers, then read them back through the real
managers.

``tests/unit/test_system_event_persistence.py`` covers the storage helper. This
covers the wiring, which is where the bug actually lived — both managers were
writing columns that do not exist and reading a column that does not exist, and
both swallowed the resulting exceptions.

The A/B test case is the one with teeth. ``ABTestManager._load_from_db`` is how a
running experiment survives a process restart; because the query raised while
being built, every restart silently dropped every running test, and traffic that
was being split between champion and challenger went back to the champion with
no record that an experiment had been in flight.
"""

from __future__ import annotations

from contextlib import contextmanager

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database.models import Base, SystemEvent

pytestmark = pytest.mark.unit


class _FakeDbManager:
    """Stands in for ``database.connection.get_db_manager()`` with SQLite."""

    def __init__(self):
        self.engine = create_engine("sqlite://")
        Base.metadata.create_all(self.engine, tables=[SystemEvent.__table__])
        self._Session = sessionmaker(bind=self.engine)

    @contextmanager
    def session(self):
        s = self._Session()
        try:
            yield s
        finally:
            s.close()


@pytest.fixture
def db_manager(monkeypatch):
    mgr = _FakeDbManager()
    import database.connection as conn

    monkeypatch.setattr(conn, "get_db_manager", lambda: mgr)
    try:
        yield mgr
    finally:
        mgr.engine.dispose()


def test_a_finished_training_run_appears_in_the_history(db_manager):
    from ml.training_manager import TrainingManager

    mgr = TrainingManager()
    mgr._persist_job(
        job_id="job-77",
        model="advanced_oos",
        status="completed",
        duration_s=41.2,
        metrics={"auc": 0.63},
        error=None,
    )

    jobs = mgr.list_jobs()
    stored = [j for j in jobs if j["id"] == "job-77"]
    assert stored, (
        "the finished run is not in the history. The write raised TypeError on "
        "status= and the read raised AttributeError on SystemEvent.created_at; "
        "both were logged at debug and the page fell back to a static list of "
        f"models scraped off disk. Got: {[j['id'] for j in jobs]}"
    )
    job = stored[0]
    assert job["model"] == "advanced_oos"
    assert job["status"] == "completed"
    assert job["metrics"] == {"auc": 0.63}
    assert job["duration_s"] == 41.2


def test_a_failed_run_keeps_its_error(db_manager):
    from ml.training_manager import TrainingManager

    mgr = TrainingManager()
    mgr._persist_job(
        job_id="job-bad",
        model="lstm_signal",
        status="failed",
        duration_s=3.0,
        metrics={},
        error="ran out of memory",
    )

    job = mgr.get_job("job-bad")
    assert job is not None, "get_job compared a UUID string against the BigInteger primary key"
    assert job["status"] == "failed"
    assert job["error"] == "ran out of memory"


def test_a_running_ab_test_survives_a_restart(db_manager):
    """The restart path. A second manager instance is what a process restart
    looks like from the database's point of view."""
    from ml.ab_testing import ABTest, ABTestManager

    first = ABTestManager()
    test = ABTest(
        test_id="exp-1",
        name="ppo-vs-baseline",
        control="baseline",
        challenger="ppo_v2",
        traffic_split=0.25,
        status="active",
    )
    first._persist_test(test)

    second = ABTestManager()
    second._load_from_db()

    restored = second.get_test("exp-1")
    assert restored is not None, (
        "the running experiment did not survive the restart — traffic silently "
        "reverted to the champion with no record that a test was in flight"
    )
    assert restored.challenger == "ppo_v2"
    assert restored.traffic_split == 0.25


def test_a_finished_test_is_not_restored_as_running(db_manager):
    from ml.ab_testing import ABTest, ABTestManager

    mgr = ABTestManager()
    mgr._persist_test(
        ABTest(
            test_id="exp-done",
            name="old",
            control="a",
            challenger="b",
            traffic_split=0.5,
            status="finished",
        )
    )

    fresh = ABTestManager()
    fresh._load_from_db()
    assert fresh.get_test("exp-done") is None


def test_active_only_is_honoured_for_stored_tests(db_manager):
    """``list_tests(active_only=True)`` filtered the in-memory tests but not the
    rows it appended from the database, so a finished experiment could come back
    labelled as part of the active set."""
    from ml.ab_testing import ABTest, ABTestManager

    mgr = ABTestManager()
    for tid, status in (("live", "active"), ("done", "finished")):
        mgr._persist_test(ABTest(test_id=tid, name=tid, control="a", challenger="b", traffic_split=0.5, status=status))

    ids = {t["id"] for t in ABTestManager().list_tests(active_only=True)}
    assert "done" not in ids, f"a finished test came back in the active listing: {ids}"


def test_re_persisting_a_test_does_not_duplicate_it(db_manager):
    """A test is written again on each status change."""
    from ml.ab_testing import ABTest, ABTestManager

    mgr = ABTestManager()
    test = ABTest(test_id="e", name="e", control="a", challenger="b", traffic_split=0.5, status="active")
    mgr._persist_test(test)
    test.status = "finished"
    mgr._persist_test(test)

    with db_manager.session() as db:
        assert db.query(SystemEvent).count() == 1

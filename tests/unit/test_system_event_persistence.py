# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
tests/unit/test_system_event_persistence.py
============================================
ML training history and A/B test state were never persisted, and never read.

``ml/training_manager.py`` and ``ml/ab_testing.py`` both write run records to
the ``system_events`` table and both read them back. Neither had ever worked.
The model's columns are ``timestamp``, ``level``, ``component``, ``event_type``,
``message``, ``details_json``, ``trace_id`` — the callers used ``created_at``,
``status`` and ``metadata``, passed a UUID string into a BigInteger primary key,
and left the two NOT NULL columns unset.

Every failure was swallowed by an ``except Exception`` logging at ``debug``:

* writes died on ``TypeError: 'status' is an invalid keyword argument``,
* reads died on ``AttributeError`` while *building* the query, at
  ``SystemEvent.created_at``,
* and ``row.metadata`` on a declarative model is the SQLAlchemy ``MetaData``
  object, which is truthy — so the ``meta = r.metadata or {}`` guard handed
  back a ``MetaData`` and the next ``.get()`` raised as well.

What an operator saw: an A/B test page that was always empty, an A/B manager
that silently forgot every running experiment across a restart, and a training
history page that fell back to ``_static_model_status()`` and therefore showed a
believable list of models scraped off disk while no run had ever been recorded.

These tests use a real SQLite session against the real metadata, so a future
schema change that breaks the mapping fails here rather than in a log nobody
reads.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database.models import Base, SystemEvent
from database.system_events import read_events, upsert_event

pytestmark = pytest.mark.unit


@pytest.fixture
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine, tables=[SystemEvent.__table__])
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()


# ── The premise: the columns the old code used do not exist ──────────────────


def test_the_model_has_no_status_created_at_or_metadata_columns():
    """If these ever become real columns, the mapping below should be revisited
    rather than left as a translation layer over nothing."""
    cols = set(SystemEvent.__table__.columns.keys())
    assert "status" not in cols
    assert "created_at" not in cols
    assert "metadata" not in cols
    assert {"timestamp", "level", "message", "details_json", "trace_id"} <= cols


def test_metadata_on_an_instance_is_truthy_and_not_a_dict():
    """The specific trap: ``meta = r.metadata or {}`` does not fall back."""
    row = SystemEvent()
    assert row.metadata  # truthy — the guard never fires
    assert not hasattr(row.metadata, "get")


# ── Writing ──────────────────────────────────────────────────────────────────


def test_a_training_run_is_actually_stored(db):
    upsert_event(
        db,
        ref_id="job-abc",
        event_type="ml_training",
        component="xgboost",
        status="completed",
        payload={"duration_s": 12.5, "metrics": {"auc": 0.71}},
    )
    db.commit()

    assert db.query(SystemEvent).count() == 1, (
        "nothing was written — this is the TypeError on status= that the caller's except-block turned into a debug line"
    )


def test_the_not_null_columns_are_populated(db):
    """``level`` and ``message`` are NOT NULL and were never set, so the insert
    would have failed even with the invalid kwargs removed."""
    upsert_event(db, ref_id="j1", event_type="ml_training", component="lgbm", status="running", payload={})
    db.commit()

    row = db.query(SystemEvent).one()
    assert row.level
    assert row.message
    assert row.component == "lgbm"


def test_a_string_id_does_not_go_into_the_bigint_primary_key(db):
    upsert_event(db, ref_id="uuid-shaped-id", event_type="ab_test", component="t", status="active", payload={})
    db.commit()

    row = db.query(SystemEvent).one()
    assert row.trace_id == "uuid-shaped-id"
    assert isinstance(row.id, int)


def test_writing_the_same_ref_twice_updates_rather_than_duplicates(db):
    """A/B tests are re-persisted on every status change; the old code used
    ``db.merge`` on the primary key to get this."""
    upsert_event(db, ref_id="t1", event_type="ab_test", component="exp", status="active", payload={"traffic": 0.2})
    db.commit()
    upsert_event(db, ref_id="t1", event_type="ab_test", component="exp", status="finished", payload={"traffic": 0.2})
    db.commit()

    assert db.query(SystemEvent).count() == 1
    assert read_events(db, event_type="ab_test")[0].status == "finished"


# ── Reading ──────────────────────────────────────────────────────────────────


def test_a_written_run_reads_back_with_its_payload(db):
    upsert_event(
        db,
        ref_id="job-1",
        event_type="ml_training",
        component="xgboost",
        status="completed",
        payload={"duration_s": 12.5, "metrics": {"auc": 0.71}},
    )
    db.commit()

    got = read_events(db, event_type="ml_training")
    assert len(got) == 1, "the read query raised on SystemEvent.created_at and returned nothing"
    rec = got[0]
    assert rec.ref_id == "job-1"
    assert rec.component == "xgboost"
    assert rec.status == "completed"
    assert rec.payload["metrics"]["auc"] == 0.71
    assert rec.started_at is not None


def test_reads_are_scoped_to_their_event_type(db):
    upsert_event(db, ref_id="a", event_type="ml_training", component="m", status="done", payload={})
    upsert_event(db, ref_id="b", event_type="ab_test", component="e", status="active", payload={})
    db.commit()

    assert [r.ref_id for r in read_events(db, event_type="ab_test")] == ["b"]


def test_a_row_written_by_something_else_does_not_break_the_listing(db):
    """``system_events`` is a general log table; other components write to it.
    A row whose details_json is not our envelope must be skipped over, not
    fatal — losing one row is better than losing the page."""
    db.add(
        SystemEvent(
            level="ERROR",
            component="somewhere-else",
            event_type="ml_training",
            message="unrelated",
            details_json="not json at all",
        )
    )
    upsert_event(db, ref_id="mine", event_type="ml_training", component="m", status="done", payload={"x": 1})
    db.commit()

    got = read_events(db, event_type="ml_training")
    assert len(got) == 2
    assert {r.status for r in got} == {"", "done"}


def test_limit_is_honoured(db):
    for i in range(5):
        upsert_event(db, ref_id=f"j{i}", event_type="ml_training", component="m", status="done", payload={})
    db.commit()

    assert len(read_events(db, event_type="ml_training", limit=3)) == 3

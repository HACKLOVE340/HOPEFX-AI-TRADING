# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""`core/outbox.py`'s relay, driven against a real database.

The outbox exists so a compliance event — a kill-switch activation, an AML
block, an order fill — survives Redis being down. Its guarantee is at-least-once
delivery, and the machinery that upholds it is a SQL filter and a retry counter.

The existing suite drives the relay with `MagicMock` sessions, so the filter it
depends on never executes: a mock `.query(...).filter(...).all()` returns
whatever it was told to, regardless of what the filter says. These tests use an
in-memory SQLite database and the real `OutboxEvent` model, so the query is the
thing under test.

That is what exposed the defect below.
"""

from __future__ import annotations

import asyncio
import json
import sys
import types
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core import outbox
from database.models import Base, OutboxEvent

pytestmark = pytest.mark.unit

UTC = timezone.utc

#: The row column's own default, from `database/models.py`.
COLUMN_MAX_ATTEMPTS = 5


class _RedisThatRefuses:
    def __init__(self) -> None:
        self.attempts = 0

    def publish(self, _channel, _payload):
        self.attempts += 1
        raise RuntimeError("redis refused")


class _RedisThatAccepts:
    def __init__(self) -> None:
        self.published: list[tuple[str, str]] = []

    def publish(self, channel, payload):
        self.published.append((channel, payload))


@pytest.fixture
def db(monkeypatch: pytest.MonkeyPatch):
    """A real session factory, wired where `_get_db_session` looks for it."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)

    app_state = types.ModuleType("core.app_state")
    app_state.app_state = types.SimpleNamespace(db_session_factory=factory)
    monkeypatch.setitem(sys.modules, "core.app_state", app_state)
    return factory


def _event(session, **overrides) -> int:
    defaults = {
        "event_type": "KILL_SWITCH",
        "channel": "hopefx:breach",
        "payload": json.dumps({"reason": "drawdown exceeded"}),
        "status": "pending",
        "attempts": 0,
        "created_at": datetime.now(UTC),
    }
    row = OutboxEvent(**{**defaults, **overrides})
    session.add(row)
    session.commit()
    return row.id


def _tick(redis_client) -> None:
    outbox._get_redis = lambda: redis_client
    asyncio.run(outbox.OutboxRelay()._relay_batch())


@pytest.fixture(autouse=True)
def _restore_get_redis():
    original = outbox._get_redis
    yield
    outbox._get_redis = original


class TestDelivery:
    def test_a_pending_event_reaches_redis_and_is_marked_published(self, db) -> None:
        session = db()
        row_id = _event(session)
        session.close()

        redis_client = _RedisThatAccepts()
        _tick(redis_client)

        session = db()
        row = session.get(OutboxEvent, row_id)
        assert redis_client.published == [("hopefx:breach", json.dumps({"reason": "drawdown exceeded"}))]
        assert row.published_at is not None
        assert row.status == "published"

    def test_a_published_event_is_not_sent_twice(self, db) -> None:
        session = db()
        _event(session, published_at=datetime.now(UTC), status="published")
        session.close()

        redis_client = _RedisThatAccepts()
        _tick(redis_client)

        assert redis_client.published == []

    def test_oldest_first(self, db) -> None:
        session = db()
        now = datetime.now(UTC)
        _event(session, channel="second", created_at=now)
        _event(session, channel="first", created_at=now - timedelta(minutes=5))
        session.close()

        redis_client = _RedisThatAccepts()
        _tick(redis_client)

        assert [channel for channel, _payload in redis_client.published] == ["first", "second"]


class TestTheRetryCounterAndTheDeadLetterThresholdAgree:
    """The defect this file was written to find.

    The fetch filter used the module-level `MAX_ATTEMPTS` (env default 10):

        OutboxEvent.attempts < max_attempts

    while dead-lettering used the row's own column (schema default 5):

        row_max = getattr(row, "max_attempts", None) or max_attempts
        if row.attempts >= row_max: row.status = "dead_letter"

    Two different numbers for one decision. Measured, one event that cannot
    publish, one relay tick per line:

        tick  5: attempts=5   status=dead_letter   still fetched next tick: True
        tick  6: attempts=6   status=dead_letter   still fetched next tick: True
        ...
        tick 10: attempts=10  status=dead_letter   still fetched next tick: False

    So an event was declared dead at 5 and retried five more times, logging
    `outbox: dead-lettered` at ERROR on each of them — six identical alerts for
    one event, and five publish attempts made after the system said it had
    stopped.
    """

    def test_a_dead_lettered_row_is_not_fetched_again(self, db) -> None:
        session = db()
        row_id = _event(session)
        session.close()

        redis_client = _RedisThatRefuses()
        for _ in range(COLUMN_MAX_ATTEMPTS + 3):
            _tick(redis_client)

        session = db()
        row = session.get(OutboxEvent, row_id)
        assert row.status == "dead_letter"
        assert row.attempts == COLUMN_MAX_ATTEMPTS, (
            f"attempted {row.attempts} times against a limit of {COLUMN_MAX_ATTEMPTS}"
        )
        assert redis_client.attempts == COLUMN_MAX_ATTEMPTS

    def test_it_is_dead_lettered_exactly_once(self, db, caplog: pytest.LogCaptureFixture) -> None:
        """Six ERROR alerts for one undeliverable event is how an on-call
        engineer learns to filter out the channel."""
        session = db()
        _event(session)
        session.close()

        redis_client = _RedisThatRefuses()
        with caplog.at_level("ERROR"):
            for _ in range(COLUMN_MAX_ATTEMPTS + 3):
                _tick(redis_client)

        dead_letters = [r for r in caplog.records if "dead-lettered" in r.getMessage()]
        assert len(dead_letters) == 1

    def test_a_row_with_its_own_higher_limit_gets_the_attempts_it_asked_for(self, db) -> None:
        """The column is per-row for a reason. A row asking for 8 must not be
        cut off at the global default, and must not be dead-lettered early."""
        session = db()
        row_id = _event(session, max_attempts=8)
        session.close()

        redis_client = _RedisThatRefuses()
        for _ in range(12):
            _tick(redis_client)

        session = db()
        row = session.get(OutboxEvent, row_id)
        assert row.attempts == 8
        assert row.status == "dead_letter"

    def test_a_row_with_a_lower_limit_stops_early(self, db) -> None:
        session = db()
        row_id = _event(session, max_attempts=2)
        session.close()

        redis_client = _RedisThatRefuses()
        for _ in range(6):
            _tick(redis_client)

        session = db()
        assert session.get(OutboxEvent, row_id).attempts == 2

    def test_a_recovered_redis_still_delivers_before_the_limit(self, db) -> None:
        """At-least-once is the whole point: failing twice must not lose the
        event."""
        session = db()
        row_id = _event(session)
        session.close()

        _tick(_RedisThatRefuses())
        _tick(_RedisThatRefuses())
        accepting = _RedisThatAccepts()
        _tick(accepting)

        session = db()
        row = session.get(OutboxEvent, row_id)
        assert len(accepting.published) == 1
        assert row.status == "published"
        assert row.published_at is not None


class TestIdempotency:
    """The duplicate-skip branch, and the schema question of whether it can run.

    `database/models.py:1263` declares `idempotency_key` with `unique=True`. The
    migration that adds the column to an existing `outbox_events` table —
    `alembic/versions/n1o2p3q4r5s6_...py:237` — adds it as
    `sa.Column("idempotency_key", sa.String(128), nullable=True)`, with no
    unique constraint.

    So the table has two shapes depending on how the database was built. Under
    `Base.metadata.create_all` (tests, a fresh deployment) the key is UNIQUE and
    the relay's

        already = ... .filter(OutboxEvent.idempotency_key == row.idempotency_key,
                              OutboxEvent.id != row.id).first()

    can never find anything — the branch is unreachable by construction. Under a
    migrated database it can. See MASTER_OUTSTANDING A11.

    The first version of this test simply inserted two rows with the same key
    and died on an IntegrityError, which is how the divergence was found.
    """

    def test_the_create_all_schema_makes_a_duplicate_key_impossible(self, db) -> None:
        """The constraint itself, asserted rather than assumed — it is what
        decides whether the branch below is live."""
        import sqlalchemy.exc

        session = db()
        _event(session, idempotency_key="fill-42")
        with pytest.raises(sqlalchemy.exc.IntegrityError):
            _event(session, idempotency_key="fill-42", channel="hopefx:dup")
        session.rollback()
        session.close()

    def test_a_migrated_schema_skips_the_duplicate_without_resending(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The production shape: the column exists without the unique index."""
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        with engine.begin() as connection:
            connection.exec_driver_sql("DROP TABLE outbox_events")
            connection.exec_driver_sql(
                """
                CREATE TABLE outbox_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_type VARCHAR(100) NOT NULL,
                    channel VARCHAR(100) NOT NULL,
                    payload TEXT NOT NULL,
                    status VARCHAR(20) NOT NULL DEFAULT 'pending',
                    created_at DATETIME,
                    published_at DATETIME,
                    attempts INTEGER DEFAULT 0,
                    max_attempts INTEGER NOT NULL DEFAULT 5,
                    last_error TEXT,
                    idempotency_key VARCHAR(128)
                )
                """
            )
        factory = sessionmaker(bind=engine)
        app_state = types.ModuleType("core.app_state")
        app_state.app_state = types.SimpleNamespace(db_session_factory=factory)
        monkeypatch.setitem(sys.modules, "core.app_state", app_state)

        session = factory()
        _event(session, idempotency_key="fill-42", published_at=datetime.now(UTC), status="published")
        duplicate_id = _event(session, idempotency_key="fill-42", channel="hopefx:dup")
        session.close()

        redis_client = _RedisThatAccepts()
        _tick(redis_client)

        session = factory()
        duplicate = session.get(OutboxEvent, duplicate_id)
        assert redis_client.published == [], "the duplicate was re-sent"
        assert duplicate.status == "published"
        assert duplicate.published_at is not None

    def test_a_distinct_key_is_sent(self, db) -> None:
        session = db()
        _event(session, idempotency_key="fill-1", published_at=datetime.now(UTC), status="published")
        _event(session, idempotency_key="fill-2", channel="hopefx:other")
        session.close()

        redis_client = _RedisThatAccepts()
        _tick(redis_client)

        assert [channel for channel, _p in redis_client.published] == ["hopefx:other"]


class TestBatchLimit:
    def test_no_more_than_the_batch_size_is_taken_per_tick(self, db, monkeypatch) -> None:
        monkeypatch.setenv("OUTBOX_BATCH_SIZE", "3")
        session = db()
        for index in range(7):
            _event(session, channel=f"c{index}")
        session.close()

        redis_client = _RedisThatAccepts()
        _tick(redis_client)

        assert len(redis_client.published) == 3


class TestNothingToDo:
    def test_an_empty_outbox_does_not_reach_for_redis(self, db) -> None:
        called: list[int] = []

        def _redis():
            called.append(1)
            return _RedisThatAccepts()

        outbox._get_redis = _redis
        asyncio.run(outbox.OutboxRelay()._relay_batch())

        assert called == []

    def test_no_session_factory_is_a_quiet_no_op(self, monkeypatch) -> None:
        app_state = types.ModuleType("core.app_state")
        app_state.app_state = types.SimpleNamespace(db_session_factory=None)
        monkeypatch.setitem(sys.modules, "core.app_state", app_state)

        asyncio.run(outbox.OutboxRelay()._relay_batch())  # must not raise

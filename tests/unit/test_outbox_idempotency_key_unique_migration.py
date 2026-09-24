# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""`outbox_events.idempotency_key` must be UNIQUE on a migrated database.

`database/models.py::OutboxEvent.idempotency_key` declares `unique=True`, but
`alembic/versions/n1o2p3q4r5s6_...py` added the column without a unique
constraint. So the guarantee the ORM model claims holds only under
`Base.metadata.create_all()` (tests, a from-scratch deploy) and not on any
database actually built by `alembic upgrade head` — which is every
long-running deployment. See MASTER_OUTSTANDING A11 /
CORRECTION_REGISTER A11.

This builds the database the way a deployment does — `alembic upgrade head`
against an empty database, no `create_all()` — and proves the constraint is
enforced there.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone

import pytest
import sqlalchemy.exc
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database.models import OutboxEvent

pytestmark = [pytest.mark.unit, pytest.mark.slow]

UTC = timezone.utc


@pytest.fixture()
def migrated_engine(tmp_path):
    """A real engine bound to a database built only by the migrations."""
    db = tmp_path / "schema.db"
    url = f"sqlite:///{db}"
    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", url)
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("DATABASE_URL", url)
        command.upgrade(cfg, "head")
    engine = create_engine(url)
    yield engine
    engine.dispose()


_next_id = iter(range(1, 10_000))


def _row(**overrides):
    # `outbox_events.id` does not autoincrement on a migrated SQLite database
    # (a separate, pre-existing gap — `r1s2t3u4v5w6` covers other bigint PKs
    # but not this table); assign an id explicitly rather than rely on it.
    defaults = {
        "id": next(_next_id),
        "event_type": "KILL_SWITCH",
        "channel": "hopefx:breach",
        "payload": json.dumps({"reason": "drawdown exceeded"}),
        "status": "pending",
        "attempts": 0,
        "created_at": datetime.now(UTC),
    }
    return OutboxEvent(**{**defaults, **overrides})


def test_the_migrated_schema_rejects_a_duplicate_idempotency_key(migrated_engine):
    """The property the ORM model claims — proven on the schema the migrations
    actually build, not on `create_all()`."""
    session = sessionmaker(bind=migrated_engine)()
    session.add(_row(idempotency_key="fill-42"))
    session.commit()

    session.add(_row(idempotency_key="fill-42", channel="hopefx:dup"))
    with pytest.raises(sqlalchemy.exc.IntegrityError):
        session.commit()
    session.rollback()
    session.close()


def test_a_null_idempotency_key_is_unconstrained(migrated_engine):
    """Most outbox events carry no idempotency key at all; NULL != NULL under
    a unique index/constraint in both SQLite and PostgreSQL, so this must not
    regress alongside the fix above."""
    session = sessionmaker(bind=migrated_engine)()
    session.add(_row())
    session.add(_row(channel="hopefx:second"))
    session.commit()  # must not raise
    session.close()


def test_the_migration_refuses_to_run_over_existing_duplicates(tmp_path):
    """The owner's decision: fail loudly and name the count, never silently
    delete real outbox rows to make room for the constraint."""
    db = tmp_path / "schema.db"
    url = f"sqlite:///{db}"
    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", url)
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("DATABASE_URL", url)
        # Stop one migration short of the one under test, seed a duplicate
        # directly, then attempt to advance onto it.
        command.upgrade(cfg, "z5a6b7c8d9e0")

        con = sqlite3.connect(db)
        con.execute(
            "INSERT INTO outbox_events (id, event_type, channel, payload, status, "
            "attempts, idempotency_key) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (1, "A", "c1", "{}", "pending", 0, "dupe-key"),
        )
        con.execute(
            "INSERT INTO outbox_events (id, event_type, channel, payload, status, "
            "attempts, idempotency_key) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (2, "A", "c2", "{}", "pending", 0, "dupe-key"),
        )
        con.commit()
        con.close()

        with pytest.raises(RuntimeError, match=r"(?i)duplicate"):
            command.upgrade(cfg, "head")

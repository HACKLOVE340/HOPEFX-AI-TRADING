# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""``outbox_events.id`` and ``crypto_payments.id`` do not autoincrement on a
SQLite database built by ``alembic upgrade head``.

MASTER_OUTSTANDING §A11's "found on the way, still open" note: migration
``r1s2t3u4v5w6`` ("bigint primary keys must autoincrement on sqlite") retyped
thirteen tables' primary keys from ``BIGINT`` to ``INTEGER`` on SQLite, but it
was written 2026-08-08 against the fixed list of tables that existed at the
time. ``b2c3d4e5f6a7`` ("idempotency_and_new_tables", 2026-06-01, so already
merged before ``r1s2t3u4v5w6`` ran) created ``outbox_events`` and
``crypto_payments`` with ``sa.Column("id", sa.BigInteger(), autoincrement=True,
nullable=False)`` plus a separate ``sa.PrimaryKeyConstraint("id")`` — the exact
pre-fix shape ``r1s2t3u4v5w6`` corrects elsewhere — but neither table is in its
``_TABLES`` list, so the gap was never closed for them.

Both models (``database/models.py::OutboxEvent`` and ``::CryptoPayment``)
declare their ``id`` as plain ``Integer``, which is why ``create_all()`` (tests,
a from-scratch deploy) never shows this: SQLite's rowid-alias rule needs the
literal type word ``INTEGER``, and that is what ``create_all()`` emits. Only a
database built by the migrations has the mismatched ``BIGINT`` column — every
long-running deployment.

The production callers omit the id on every insert:
``core/outbox.py::write_outbox_event`` /
``write_outbox_event_standalone`` and ``api/payments.py::_save_payment``. Both
catch the resulting ``IntegrityError`` and log it rather than raising — the
same "action still executed" shape as the audit-log writer in
``test_bigint_primary_keys_autoincrement.py`` — so a kill-switch/AML/fill event
or a crypto payment record silently fails to persist.

PostgreSQL is unaffected: the identical column definition compiles to
``BIGSERIAL`` there (proven below), so this is a SQLite-only gap, same as
``r1s2t3u4v5w6``.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import sqlalchemy as sa
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import sessionmaker
from sqlalchemy.schema import CreateTable

from database.models import CryptoPayment, OutboxEvent

pytestmark = [pytest.mark.unit, pytest.mark.slow]

UTC = timezone.utc


@pytest.fixture()
def migrated_engine(tmp_path):
    """A real engine bound to a database built only by the migrations — no
    ``create_all()`` anywhere, exactly as a deployment is built."""
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


def _outbox_row(**overrides):
    defaults = dict(
        event_type="KILL_SWITCH",
        channel="hopefx:breach",
        payload=json.dumps({"reason": "drawdown exceeded"}),
        status="pending",
        attempts=0,
        created_at=datetime.now(UTC),
    )
    return OutboxEvent(**{**defaults, **overrides})


def _crypto_payment_row(**overrides):
    defaults = dict(
        payment_id=f"pay-{id(overrides)}",
        user_id="user-1",
        plan_id="pro",
        currency="BTC",
        network="BTC",
        address="bc1qexampleaddress",
        amount_usd="100.00",
        amount_crypto="0.00250000",
        rate_usd="40000.00000000",
        status="pending",
        confirmations=0,
        confirmations_required=2,
        expires_at=datetime.now(UTC),
    )
    return CryptoPayment(**{**defaults, **overrides})


def test_outbox_events_id_autoincrements_on_a_migrated_sqlite_db(migrated_engine):
    """The exact write path production uses: no explicit id, two inserts,
    expecting the database to assign sequential ids — the way
    ``core/outbox.py::write_outbox_event`` calls it."""
    session = sessionmaker(bind=migrated_engine)()
    try:
        first = _outbox_row(idempotency_key="fill-1")
        session.add(first)
        session.commit()
        assert first.id is not None, "outbox_events.id was not assigned by the database"

        second = _outbox_row(idempotency_key="fill-2")
        session.add(second)
        session.commit()
        assert second.id == first.id + 1, "outbox_events.id did not autoincrement sequentially"
    finally:
        session.close()


def test_crypto_payments_id_autoincrements_on_a_migrated_sqlite_db(migrated_engine):
    """The exact write path production uses: ``api/payments.py::_save_payment``
    never sets an id."""
    session = sessionmaker(bind=migrated_engine)()
    try:
        first = _crypto_payment_row(payment_id="pay-a")
        session.add(first)
        session.commit()
        assert first.id is not None, "crypto_payments.id was not assigned by the database"

        second = _crypto_payment_row(payment_id="pay-b")
        session.add(second)
        session.commit()
        assert second.id == first.id + 1, "crypto_payments.id did not autoincrement sequentially"
    finally:
        session.close()


@pytest.mark.parametrize("table_name", ["outbox_events", "crypto_payments"])
def test_still_bigserial_on_postgres(table_name):
    """Confirms the fix must be SQLite-only, mirroring ``r1s2t3u4v5w6``.

    This mirrors ``alembic/versions/b2c3d4e5f6a7_idempotency_and_new_tables.py``'s
    own ``id`` column definition — ``sa.BigInteger()`` with ``autoincrement=True``
    plus a separate ``sa.PrimaryKeyConstraint("id")`` — which is what is actually
    deployed on PostgreSQL (migrations, not ``create_all()``). It already
    compiles to BIGSERIAL there, so retyping it on PostgreSQL would be
    redundant, not a fix.

    (The ORM models declare this column as plain ``Integer``, which would
    compile to 32-bit ``SERIAL`` under ``create_all()`` on PostgreSQL — a
    separate, pre-existing model/migration divergence this test does not
    address; the migration's own column type, proven here, is what a real
    deployment gets.)
    """
    metadata = sa.MetaData()
    table = sa.Table(
        table_name,
        metadata,
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("placeholder", sa.String(length=1), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    ddl = str(CreateTable(table).compile(dialect=postgresql.dialect()))
    id_line = next(line for line in ddl.splitlines() if line.strip().startswith("id "))
    assert "BIGSERIAL" in id_line, f"{table_name}.id is {id_line.strip()!r} on PostgreSQL, expected BIGSERIAL"

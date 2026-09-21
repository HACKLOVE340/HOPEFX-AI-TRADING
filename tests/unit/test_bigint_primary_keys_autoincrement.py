# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
tests/unit/test_bigint_primary_keys_autoincrement.py
=====================================================
Thirteen tables could not be inserted into on SQLite, including the audit log.

SQLite only auto-populates a primary key declared *exactly* ``INTEGER PRIMARY
KEY`` — that spelling, and only that spelling, is an alias for the implicit
``rowid``. ``BIGINT PRIMARY KEY`` is an ordinary NOT NULL column. Thirteen
models were declared ``Column(BigInteger, primary_key=True)``, so on SQLite —
the dev default, and what CI boots — every insert that let the database assign
the id failed with::

    sqlite3.IntegrityError: NOT NULL constraint failed: audit_log.id

On PostgreSQL the same declaration is fine (BIGSERIAL), which is why this
survived: it is invisible on the deployment target and fatal everywhere else.

The tables include ``audit_log`` and ``wallet_transactions``. Every writer
found doing this caught the IntegrityError and continued — the superadmin audit
writer logs "action still executed" and moves on — so an append-only compliance
log silently stopped appending and no operator was told.

``PKBigInt`` is ``BigInteger().with_variant(Integer, "sqlite")``: BIGSERIAL on
PostgreSQL, rowid-aliasing INTEGER on SQLite. ``audit_log`` had been patched to
plain ``Integer`` to work around this, with a comment claiming ``sa.Integer``
maps to BIGINT on PostgreSQL. It does not — that narrowed an append-only audit
log to 2^31 rows on the one backend that runs in production.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, inspect
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.orm import sessionmaker
from sqlalchemy.schema import CreateTable

from database.models import AuditLogEntry, Base

pytestmark = pytest.mark.unit


def _autoincrement_pk_tables():
    """Every table whose single-column integer PK has no default — i.e. the
    ones relying on the database to assign the id."""
    out = []
    for table in Base.metadata.tables.values():
        pks = list(table.primary_key.columns)
        if len(pks) != 1:
            continue
        col = pks[0]
        if col.default is not None or col.server_default is not None:
            continue
        if "INT" in str(col.type).upper():
            out.append((table, col))
    return out


@pytest.mark.parametrize(
    "table_name",
    sorted(t.name for t, _ in _autoincrement_pk_tables()),
)
def test_every_autoincrement_pk_is_a_rowid_alias_on_sqlite(table_name):
    """The actual rule: SQLite needs the literal type word ``INTEGER``."""
    table = Base.metadata.tables[table_name]
    ddl = str(CreateTable(table).compile(dialect=sqlite.dialect()))
    pk_col = list(table.primary_key.columns)[0]

    for line in ddl.splitlines():
        stripped = line.strip()
        if stripped.startswith(f"{pk_col.name} "):
            declared = stripped.split()[1].rstrip(",")
            assert declared == "INTEGER", (
                f"{table_name}.{pk_col.name} is declared {declared} on SQLite. "
                "Only 'INTEGER PRIMARY KEY' aliases rowid, so inserts that omit "
                "the id fail with NOT NULL constraint failed. Use PKBigInt."
            )
            return
    pytest.fail(f"could not find the {pk_col.name} column in the generated DDL for {table_name}")


def test_the_audit_log_is_still_64_bit_on_postgres():
    """The workaround this replaces narrowed an append-only log to 2^31 rows on
    the production backend."""
    ddl = str(CreateTable(AuditLogEntry.__table__).compile(dialect=postgresql.dialect()))
    id_line = next(line for line in ddl.splitlines() if line.strip().startswith("id "))
    assert "BIGSERIAL" in id_line, f"audit_log.id is {id_line.strip()!r} on PostgreSQL, not BIGSERIAL"


def test_an_audit_row_can_actually_be_written_on_sqlite():
    """The end-to-end version. This is the insert that was failing, and it is
    the compliance audit trail."""
    from datetime import datetime, timezone

    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine, tables=[AuditLogEntry.__table__])
    session = sessionmaker(bind=engine)()
    try:
        now = datetime.now(timezone.utc)
        session.add(
            AuditLogEntry(
                sequence_number=1,
                timestamp=now,
                created_at=now,
                level="COMPLIANCE",
                category="SUPERADMIN",
                actor="admin-1",
                action="kill_switch",
                hash_chain="0" * 64,
            )
        )
        session.commit()

        row = session.query(AuditLogEntry).one()
        assert row.id is not None, "the audit row was written with no id"
    finally:
        session.close()
        engine.dispose()


def test_the_sqlite_schema_matches_what_the_models_declare():
    """Guards the whole set: create_all must succeed and produce the tables."""
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    try:
        present = set(inspect(engine).get_table_names())
        assert "audit_log" in present
        assert "system_events" in present
    finally:
        engine.dispose()

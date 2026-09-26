# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""tick_data.timestamp becomes TIMESTAMPTZ, storing UTC

Revision ID: f2a3b4c5d6e7
Revises: d9e0f1a2b3c4
Create Date: 2026-09-25

`database/models.py::TickData.timestamp` has declared `DateTime(timezone=True)`
since it was written; every migration, from the initial schema through
`v1w2x3y4z5a6`, created it as plain `DateTime()` — `TIMESTAMP WITHOUT TIME
ZONE` on PostgreSQL. `tests/unit/test_migrated_schema_matches_models.py`
carried it in `KNOWN_COLUMN_TYPE_DRIFT` rather than widen it, because widening
a timestamp needs an assumed source zone for every already-stored row — an
owner decision this migration has now: the owner approved storing it as UTC,
timezone-aware.

**Verified before writing this, not assumed.** Both live writers of this
column construct an aware UTC `datetime` before the value ever reaches
SQLAlchemy:

* `database/repositories/tick_data_repository.py::insert_tick` /
  `bulk_insert_ticks` — `datetime.fromtimestamp(ts_ns / 1e9, tz=UTC)`.
* `data/real_time_price_engine.py::_persist_tick_batch` —
  `datetime.fromtimestamp(tick.timestamp, tz=UTC)`.

(`database/models.py::TickData.from_gold_tick` also passes one through, but
has no caller anywhere in this repository — dead code, not a live writer.)

Neither writer ever constructs a naive or non-UTC datetime, so the "STOP
before migrating" condition in the owner's instruction does not apply.

**What was actually landing in PostgreSQL, measured against a real server
(not assumed).** Both drivers this codebase uses were exercised end to end —
`TickDataRepository.insert_tick` through a real asyncpg connection, and the
equivalent sync write through psycopg2 — against the pre-fix `TIMESTAMP
WITHOUT TIME ZONE` column:

* **asyncpg (async path; nothing in production currently calls
  `TickDataRepository`, but this is the driver it would use).** SQLAlchemy's
  asyncpg dialect renders an explicit bind cast from the model's declared
  type (`AsyncpgDateTime.render_bind_cast`), so the insert does not fail —
  it sends `$1::TIMESTAMP WITH TIME ZONE`, and PostgreSQL then *implicitly*
  downcasts that to the real `TIMESTAMP WITHOUT TIME ZONE` column using the
  session's `TimeZone` GUC. Reading the row back hands the caller a **naive**
  `datetime` — the ORM column claims `timezone=True` and the value it
  produces does not carry one. (A raw, uncast asyncpg bind against the same
  column — no ORM in the way — does fail outright with
  `asyncpg.exceptions.DataError: ... can't subtract offset-naive and
  offset-aware datetimes`, which is what a caller hits the moment it stops
  going through a column whose declared type triggers the cast.)
* **psycopg2 (sync path; what `real_time_price_engine`'s
  `db_session_factory` actually uses in production).** Silently drops the
  tzinfo and writes the wall-clock value — the UTC instant only because this
  server's `TimeZone` GUC is `Etc/UTC` and nothing in `database/connection.py`
  overrides it per-session.

Both are session-GUC-dependent for correctness today, and the async path
additionally hands every caller a datetime that lies about being
timezone-aware — exactly the naive/aware comparison bug this fix exists to
close, not merely the schema label. `USING timestamp AT TIME ZONE 'UTC'`
makes the stored instant explicit rather than GUC-dependent, and a real
`timestamptz` column is what both drivers' codecs actually want for an aware
datetime, so the value that comes back is honestly aware from here on.

**The ALTER.** `timestamp AT TIME ZONE 'UTC'` — not a bare cast — because
PostgreSQL's implicit `timestamp -> timestamptz` cast interprets the naive
value in the *session's* timezone at ALTER time, which is correct only by the
same GUC-dependent accident described above. The explicit form pins the
interpretation to UTC regardless of who runs the migration or when.

**SQLite.** SQLite has no native timezone-aware storage; SQLAlchemy's sqlite
dialect stores `DateTime(timezone=True)` the same way it stores `DateTime()`
(an ISO string) and returns a naive `datetime` on read regardless of the
declared type (verified — see the round-trip test). `batch_alter_table` is a
pure type-label change there: no data touches disk differently.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "f2a3b4c5d6e7"  # pragma: allowlist secret
down_revision = "d9e0f1a2b3c4"  # pragma: allowlist secret
branch_labels = None
depends_on = None

_TABLE = "tick_data"
_COLUMN = "timestamp"


def _has_column() -> bool:
    """True only when there is something here to alter.

    Same guard every other tick_data migration in this chain uses: a database
    built by an older `create_all()` snapshot may not have this column, or
    even this table, and an ALTER against something absent aborts the whole
    migration run.
    """
    inspector = sa.inspect(op.get_bind())
    if _TABLE not in set(inspector.get_table_names()):
        return False
    return _COLUMN in {c["name"] for c in inspector.get_columns(_TABLE)}


def upgrade() -> None:
    if not _has_column():
        return

    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        with op.batch_alter_table(_TABLE) as batch:
            batch.alter_column(
                _COLUMN,
                type_=sa.DateTime(timezone=True),
                existing_nullable=False,
                postgresql_using=f"{_COLUMN} AT TIME ZONE 'UTC'",
            )
    else:
        # SQLite (and any other dialect without a distinct tz-aware storage
        # format): no data transformation is possible or needed — see the
        # module docstring. `batch_alter_table` rebuilds the table, which is
        # SQLite's only way to change a declared column type at all.
        with op.batch_alter_table(_TABLE) as batch:
            batch.alter_column(_COLUMN, type_=sa.DateTime(timezone=True), existing_nullable=False)


def downgrade() -> None:
    if not _has_column():
        return

    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        with op.batch_alter_table(_TABLE) as batch:
            batch.alter_column(
                _COLUMN,
                type_=sa.DateTime(timezone=False),
                existing_nullable=False,
                postgresql_using=f"{_COLUMN} AT TIME ZONE 'UTC'",
            )
    else:
        with op.batch_alter_table(_TABLE) as batch:
            batch.alter_column(_COLUMN, type_=sa.DateTime(timezone=False), existing_nullable=False)

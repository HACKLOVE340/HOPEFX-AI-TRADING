# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""columns the models declare that no migration ever created

Revision ID: v1w2x3y4z5a6
Revises: u1v2w3x4y5z6
Create Date: 2026-09-06

F218 measured migration coverage per **table** and reported 14 tables with no
migration. Re-measured by execution — `alembic upgrade head` against an empty
database, then a diff against `Base.metadata` — that count is closed: all 44
model tables are created by migrations today.

What was never measured is the granularity that actually crashes. A table can
be covered while its columns are not, and `create_all()` hides it perfectly:
it creates a missing table and **never alters an existing one**, so on every
deployment built by Alembic these columns simply are not there.

    sqlite3.OperationalError: no such column: tick_data.quality
    sqlite3.OperationalError: no such column: accounts.account_name
    sqlite3.OperationalError: no such column: orders.account_id

Eight columns across three tables. The consequential one is `tick_data.ts_ns`:
`database/repositories/tick_data_repository.py` writes it on every insert and
orders every range query by it, so on a migrated database that repository could
not write or read a single row. `quality`, `confidence` and `lineage_id` are
the three columns the previous migration (u1v2w3x4y5z6) was written to adjust —
it correctly no-oped because they were absent, which is how this was found.

That earlier migration's docstring said `tick_data` "exists only via
create_all()". That was wrong, and it is worth stating rather than quietly
fixing: the table is created by `1b0666c43575`, in an eight-column shape from
before the nanosecond schema. Its guard was right for the wrong reason.

`orders.status` is the same drift pointing the other way — the column exists in
the schema (added and indexed by `o1p2q3r4s5t6`) and the model never declared
it, so nothing can read it and it is always its server default. The model gains
it in this change rather than the schema losing it: dropping a column on a
production database is destructive and irreversible, and additive is the
standing rule here.

`tests/unit/test_migrated_schema_matches_models.py` compares the migrated
schema to the models column by column so a ninth cannot appear unnoticed. Eight
of its nine cases fail on the pre-fix tree.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "v1w2x3y4z5a6"
down_revision = "u1v2w3x4y5z6"
branch_labels = None
depends_on = None


def _inspector() -> sa.Inspector:
    return sa.inspect(op.get_bind())


def _columns(table: str) -> set[str]:
    """Column names, or an empty set when the table itself is absent.

    Every operation below is guarded on this. These migrations run against
    databases built by `create_all()` as well as by Alembic, and on those the
    columns are already present — an unguarded `add_column` would abort the run
    and block every later migration.
    """
    inspector = _inspector()
    if table not in set(inspector.get_table_names()):
        return set()
    return {column["name"] for column in inspector.get_columns(table)}


def _indexes(table: str) -> set[str]:
    inspector = _inspector()
    if table not in set(inspector.get_table_names()):
        return set()
    return {index["name"] for index in inspector.get_indexes(table)}


def _add_index_if_missing(name: str, table: str, columns: list[str], **kw) -> None:
    if table in set(_inspector().get_table_names()) and name not in _indexes(table):
        op.create_index(name, table, columns, **kw)


def _drop_index_if_present(name: str, table: str) -> None:
    if name in _indexes(table):
        op.drop_index(name, table_name=table)


def _drop_indexes_referencing(table: str, columns: set[str]) -> None:
    """Drop every index that mentions any of `columns`, before they are dropped.

    SQLite has no DROP COLUMN, so `batch_alter_table` rebuilds the table and
    replays its indexes — including ones that name a column the rebuild just
    removed, which fails. A database built by `create_all()` carries indexes
    this migration never created (`idx_orders_account_symbol_created` spans
    account_id, symbol and created_at), so dropping only the indexes created
    here is not enough. Measured, not assumed: the downgrade failed exactly
    this way on a create_all() database before this helper existed.
    """
    inspector = _inspector()
    if table not in set(inspector.get_table_names()):
        return
    for index in inspector.get_indexes(table):
        if columns & {c for c in index.get("column_names") or [] if c}:
            op.drop_index(index["name"], table_name=table)


def upgrade() -> None:
    bind = op.get_bind()
    is_sqlite = bind.dialect.name == "sqlite"

    # ── accounts.account_name ────────────────────────────────────────────────
    if "accounts" in set(_inspector().get_table_names()) and "account_name" not in _columns("accounts"):
        op.add_column("accounts", sa.Column("account_name", sa.String(100), nullable=True))

    # ── orders.account_id ────────────────────────────────────────────────────
    # The model declares a ForeignKey with ondelete="SET NULL". SQLite cannot
    # ADD COLUMN with a constraint and cannot ADD CONSTRAINT at all, so there
    # the column arrives bare — the same compromise o1p2q3r4s5t6 made for
    # orders.user_id, and the reason that column's model comment says a
    # constraint the database does not have is how model and schema drift.
    # PostgreSQL, which is what production runs, gets the real constraint.
    if "orders" in set(_inspector().get_table_names()) and "account_id" not in _columns("orders"):
        op.add_column("orders", sa.Column("account_id", sa.Integer(), nullable=True))
        if not is_sqlite:
            op.create_foreign_key(
                "fk_orders_account_id_accounts",
                "orders",
                "accounts",
                ["account_id"],
                ["id"],
                ondelete="SET NULL",
            )
    _add_index_if_missing("ix_orders_account_id", "orders", ["account_id"])

    # ── tick_data: six columns from the nanosecond schema ────────────────────
    tick_columns = _columns("tick_data")
    if tick_columns:
        # ts_ns is NOT NULL in the model. Adding a NOT NULL column to a table
        # that may already hold rows needs a value for them, so it arrives with
        # a server default, is backfilled from the legacy `timestamp` column
        # (itself NOT NULL, so the backfill is total), and then loses the
        # default. The default must not survive: ordering is by ts_ns, and a
        # writer that forgot it would get epoch 0 and sort first forever —
        # a silent wrong answer, which is the failure mode this audit is about.
        if "ts_ns" not in tick_columns:
            op.add_column(
                "tick_data",
                sa.Column("ts_ns", sa.BigInteger(), nullable=False, server_default="0"),
            )
            if is_sqlite:
                backfill = (
                    "UPDATE tick_data SET ts_ns = "
                    "CAST(strftime('%s', timestamp) AS INTEGER) * 1000000000 "
                    "WHERE ts_ns = 0"
                )
            else:
                backfill = (
                    "UPDATE tick_data SET ts_ns = "
                    "CAST(EXTRACT(EPOCH FROM timestamp) * 1000000000 AS BIGINT) "
                    "WHERE ts_ns = 0"
                )
            op.execute(sa.text(backfill))
            if is_sqlite:
                with op.batch_alter_table("tick_data") as batch:
                    batch.alter_column("ts_ns", server_default=None)
            else:
                op.alter_column("tick_data", "ts_ns", server_default=None)

        for name, column_type in (
            ("mid", sa.Float()),
            ("spread", sa.Float()),
            ("quality", sa.String(20)),
            ("confidence", sa.Float()),
            ("lineage_id", sa.String(36)),
        ):
            if name not in _columns("tick_data"):
                op.add_column("tick_data", sa.Column(name, column_type, nullable=True))

        # The indexes the model declares on these columns. Without them every
        # range query over ts_ns is a full scan of a table designed to hold one
        # row per tick.
        _add_index_if_missing("ix_tick_data_ts_ns", "tick_data", ["ts_ns"])
        _add_index_if_missing("idx_tick_data_ts_ns", "tick_data", ["ts_ns"])
        _add_index_if_missing("ix_tick_data_lineage_id", "tick_data", ["lineage_id"])
        _add_index_if_missing("idx_tick_data_source_ts_ns", "tick_data", ["source", "ts_ns"])
        _add_index_if_missing(
            "idx_tick_data_symbol_ts_ns",
            "tick_data",
            ["symbol", "ts_ns"],
            **({} if is_sqlite else {"postgresql_using": "brin"}),
        )


def downgrade() -> None:
    tick_dropped = {"lineage_id", "confidence", "quality", "spread", "mid", "ts_ns"}
    _drop_indexes_referencing("tick_data", tick_dropped)
    if _columns("tick_data"):
        with op.batch_alter_table("tick_data") as batch:
            for name in ("lineage_id", "confidence", "quality", "spread", "mid", "ts_ns"):
                batch.drop_column(name)

    _drop_indexes_referencing("orders", {"account_id"})
    if "account_id" in _columns("orders"):
        with op.batch_alter_table("orders") as batch:
            if op.get_bind().dialect.name != "sqlite":
                batch.drop_constraint("fk_orders_account_id_accounts", type_="foreignkey")
            batch.drop_column("account_id")

    if "account_name" in _columns("accounts"):
        with op.batch_alter_table("accounts") as batch:
            batch.drop_column("account_name")

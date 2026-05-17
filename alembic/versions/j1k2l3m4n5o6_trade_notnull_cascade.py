"""trade: NOT NULL on side/entry_price/entry_quantity, CASCADE on account_id FK

Revision ID: j1k2l3m4n5o6
Revises: i1j2k3l4m5n6
Create Date: 2026-04-22 00:00:00.000000

Changes
-------
1. trades.side          — backfill NULL → 'buy', then set NOT NULL
2. trades.entry_price   — backfill NULL → 0.0,   then set NOT NULL
3. trades.entry_quantity— backfill NULL → 0.0,   then set NOT NULL
4. trades.account_id FK — add ON DELETE CASCADE so orphan trade rows are
                          automatically removed when the parent Account is deleted.

The backfill uses safe defaults that preserve existing rows without data loss.
'BUY' is chosen for trades.side because it matches the uppercase label used
when the ``orderside`` PostgreSQL enum type was first created in migration
1b0666c43575_initial_schema.py (``sa.Enum("BUY", "SELL", name="orderside")``).
Lowercase 'buy' would also be rejected by Postgres as an invalid enum value.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "j1k2l3m4n5o6"
down_revision = "i1j2k3l4m5n6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    dialect = conn.dialect.name  # "postgresql" | "sqlite" | "mysql"

    # ── 1. Backfill NULLs before tightening constraints ───────────────────────
    # Use 'BUY' — a valid value in the orderside enum — for the side backfill.
    # The PostgreSQL enum type `orderside` was created with uppercase labels
    # ('BUY', 'SELL') in migration 1b0666c43575_initial_schema.py so the
    # backfill value must match that case exactly.
    # 'unknown' is not a member of the enum (causes invalid-input-value error)
    # and lowercase 'buy' is also rejected.  'BUY' is the safest neutral default
    # for legacy rows where the direction was not recorded.
    op.execute("UPDATE trades SET side = 'BUY' WHERE side IS NULL")
    op.execute("UPDATE trades SET entry_price = 0.0 WHERE entry_price IS NULL")
    op.execute("UPDATE trades SET entry_quantity = 0.0 WHERE entry_quantity IS NULL")

    # ── 2. Apply NOT NULL constraints ─────────────────────────────────────────
    if dialect == "sqlite":
        # SQLite does not support ALTER COLUMN — the standard workaround is a
        # table rebuild.  We use batch_alter_table which Alembic implements as
        # CREATE TABLE + INSERT + DROP + RENAME under the hood.
        with op.batch_alter_table("trades") as batch_op:
            batch_op.alter_column("side",           existing_type=sa.String(20),  nullable=False)
            batch_op.alter_column("entry_price",    existing_type=sa.Float(),     nullable=False)
            batch_op.alter_column("entry_quantity", existing_type=sa.Float(),     nullable=False)
    else:
        # PostgreSQL / MySQL support ALTER COLUMN directly
        op.alter_column("trades", "side",           existing_type=sa.String(20),  nullable=False)
        op.alter_column("trades", "entry_price",    existing_type=sa.Float(),     nullable=False)
        op.alter_column("trades", "entry_quantity", existing_type=sa.Float(),     nullable=False)

    # ── 3. Add ON DELETE CASCADE to trades.account_id FK ─────────────────────
    # account_id is currently a plain integer column with no FK constraint in
    # the DB (only a SQLAlchemy relationship).  We create the FK constraint
    # explicitly here with ON DELETE CASCADE.
    #
    # SQLite does not support adding a FK constraint to an existing table via
    # ALTER TABLE.  The batch_alter_table rebuild handles this correctly.
    if dialect == "sqlite":
        with op.batch_alter_table("trades") as batch_op:
            batch_op.create_foreign_key(
                "fk_trades_account_id",
                "accounts",
                ["account_id"],
                ["id"],
                ondelete="CASCADE",
            )
    else:
        # Drop any existing FK(s) on account_id first.
        # For PostgreSQL this avoids aborting the transaction when the expected
        # name is absent, and it handles auto-generated constraint names.
        inspector = sa.inspect(conn)
        for fk in inspector.get_foreign_keys("trades"):
            constrained = fk.get("constrained_columns") or []
            fk_name = fk.get("name")
            if fk_name and constrained == ["account_id"]:
                op.drop_constraint(fk_name, "trades", type_="foreignkey")
        op.create_foreign_key(
            "fk_trades_account_id",
            "trades",
            "accounts",
            ["account_id"],
            ["id"],
            ondelete="CASCADE",
        )


def downgrade() -> None:
    conn = op.get_bind()
    dialect = conn.dialect.name

    # Remove FK constraint
    if dialect == "sqlite":
        with op.batch_alter_table("trades") as batch_op:
            batch_op.drop_constraint("fk_trades_account_id", type_="foreignkey")
            batch_op.alter_column("side",           existing_type=sa.String(20),  nullable=True)
            batch_op.alter_column("entry_price",    existing_type=sa.Float(),     nullable=True)
            batch_op.alter_column("entry_quantity", existing_type=sa.Float(),     nullable=True)
    else:
        op.drop_constraint("fk_trades_account_id", "trades", type_="foreignkey")
        op.alter_column("trades", "side",           existing_type=sa.String(20),  nullable=True)
        op.alter_column("trades", "entry_price",    existing_type=sa.Float(),     nullable=True)
        op.alter_column("trades", "entry_quantity", existing_type=sa.Float(),     nullable=True)

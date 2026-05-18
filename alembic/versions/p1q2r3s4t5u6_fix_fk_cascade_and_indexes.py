"""fix FK cascade rules and add missing indexes

Revision ID: p1q2r3s4t5u6
Revises: o1p2q3r4s5t6
Create Date: 2026-05-11

Changes
-------
FK fixes (referential integrity):
  - orders.account_id: add FK to accounts.id ON DELETE SET NULL
  - orders.trade_id: add ON DELETE SET NULL (was missing)
  - signals.trade_id: add ON DELETE SET NULL (was missing)
  - accounts.user_id: add ON DELETE CASCADE (was missing)
  - positions.account_id: add FK to accounts.id ON DELETE SET NULL
  - positions.user_id: add FK to users.id ON DELETE SET NULL; widen to VARCHAR(36)

New indexes (hot query paths):
  - idx_trades_exit_time
  - idx_trades_user_exit_time
  - idx_orders_filled_at
  - idx_orders_broker
  - idx_positions_status
  - idx_positions_symbol_status
  - idx_signals_confidence
  - idx_wallet_reference
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "p1q2r3s4t5u6"
down_revision = "o1p2q3r4s5t6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    dialect = bind.dialect.name

    def _matching_fk_names(
        table: str,
        constrained_columns: list[str],
        referred_table: str,
    ) -> set[str]:
        return {
            fk["name"]
            for fk in sa.inspect(bind).get_foreign_keys(table)
            if fk.get("name")
            and fk.get("constrained_columns") == constrained_columns
            and fk.get("referred_table") == referred_table
        }

    # ── orders.account_id — add column + FK ──────────────────────────────────
    # SQLite does not support ADD CONSTRAINT; skip FK DDL on SQLite.
    if dialect != "sqlite":
        existing_order_columns = {col["name"] for col in inspector.get_columns("orders")}
        if "account_id" not in existing_order_columns:
            op.add_column("orders", sa.Column("account_id", sa.Integer(), nullable=True))

        # Drop any pre-existing FK on (orders.account_id → accounts) so we
        # can (re)create it with the correct ondelete rule.
        for fk_name in _matching_fk_names("orders", ["account_id"], "accounts"):
            op.drop_constraint(fk_name, "orders", type_="foreignkey")

        # Use op.create_foreign_key directly (not batch_alter_table) so that
        # the just-added column is guaranteed to be visible to the DDL.
        current_order_fks = {
            fk["name"] for fk in sa.inspect(bind).get_foreign_keys("orders")
        }
        if "fk_orders_account_id" not in current_order_fks:
            op.create_foreign_key(
                "fk_orders_account_id",
                "orders",
                "accounts",
                ["account_id"],
                ["id"],
                ondelete="SET NULL",
            )

        # orders.trade_id — recreate FK with ondelete
        with op.batch_alter_table("orders") as batch_op:
            for fk_name in _matching_fk_names("orders", ["trade_id"], "trades"):
                batch_op.drop_constraint(fk_name, type_="foreignkey")
            batch_op.create_foreign_key(
                "fk_orders_trade_id",
                "trades",
                ["trade_id"],
                ["trade_id"],
                ondelete="SET NULL",
            )

        # signals.trade_id — recreate FK with ondelete
        with op.batch_alter_table("signals") as batch_op:
            for fk_name in _matching_fk_names("signals", ["trade_id"], "trades"):
                batch_op.drop_constraint(fk_name, type_="foreignkey")
            batch_op.create_foreign_key(
                "fk_signals_trade_id",
                "trades",
                ["trade_id"],
                ["trade_id"],
                ondelete="SET NULL",
            )

        # accounts.user_id — recreate FK with CASCADE
        with op.batch_alter_table("accounts") as batch_op:
            for fk_name in _matching_fk_names("accounts", ["user_id"], "users"):
                batch_op.drop_constraint(fk_name, type_="foreignkey")
            batch_op.create_foreign_key(
                "fk_accounts_user_id",
                "users",
                ["user_id"],
                ["id"],
                ondelete="CASCADE",
            )

        # positions.account_id — add FK
        with op.batch_alter_table("positions") as batch_op:
            for fk_name in _matching_fk_names("positions", ["account_id"], "accounts"):
                batch_op.drop_constraint(fk_name, type_="foreignkey")
            batch_op.create_foreign_key(
                "fk_positions_account_id",
                "accounts",
                ["account_id"],
                ["id"],
                ondelete="SET NULL",
            )

        # positions.user_id — widen column + add FK
        with op.batch_alter_table("positions") as batch_op:
            batch_op.alter_column(
                "user_id",
                existing_type=sa.String(50),
                type_=sa.String(36),
                existing_nullable=True,
            )
            for fk_name in _matching_fk_names("positions", ["user_id"], "users"):
                batch_op.drop_constraint(fk_name, type_="foreignkey")
            batch_op.create_foreign_key(
                "fk_positions_user_id",
                "users",
                ["user_id"],
                ["id"],
                ondelete="SET NULL",
            )

    # ── New indexes (all dialects) ────────────────────────────────────────────
    _create_index_if_not_exists("idx_trades_exit_time", "trades", ["exit_time"])
    _create_index_if_not_exists("idx_trades_user_exit_time", "trades", ["user_id", "exit_time"])
    _create_index_if_not_exists("idx_orders_filled_at", "orders", ["filled_at"])
    _create_index_if_not_exists("idx_orders_broker", "orders", ["broker"])
    _create_index_if_not_exists("idx_positions_status", "positions", ["status"])
    _create_index_if_not_exists("idx_positions_symbol_status", "positions", ["symbol", "status"])
    _create_index_if_not_exists("idx_signals_confidence", "signals", ["confidence"])
    _create_index_if_not_exists("idx_wallet_reference", "wallet_transactions", ["reference"])


def downgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name

    # Drop new indexes
    for idx_name, table in [
        ("idx_trades_exit_time", "trades"),
        ("idx_trades_user_exit_time", "trades"),
        ("idx_orders_filled_at", "orders"),
        ("idx_orders_broker", "orders"),
        ("idx_positions_status", "positions"),
        ("idx_positions_symbol_status", "positions"),
        ("idx_signals_confidence", "signals"),
        ("idx_wallet_reference", "wallet_transactions"),
    ]:
        try:
            op.drop_index(idx_name, table_name=table)
        except Exception:  # nosec B110 — constraint may not exist yet
            pass

    if dialect != "sqlite":
        # Restore FKs without ondelete (original state)
        for constraint, table in [
            ("fk_orders_account_id", "orders"),
            ("fk_orders_trade_id", "orders"),
            ("fk_signals_trade_id", "signals"),
            ("fk_accounts_user_id", "accounts"),
            ("fk_positions_account_id", "positions"),
            ("fk_positions_user_id", "positions"),
        ]:
            try:
                with op.batch_alter_table(table) as batch_op:
                    batch_op.drop_constraint(constraint, type_="foreignkey")
            except Exception:  # nosec B110 — constraint may not exist yet
                pass


def _create_index_if_not_exists(name: str, table: str, columns: list[str]) -> None:
    """Create an index only if it does not already exist (idempotent)."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = {idx["name"] for idx in inspector.get_indexes(table)}
    if name not in existing:
        op.create_index(name, table, columns)

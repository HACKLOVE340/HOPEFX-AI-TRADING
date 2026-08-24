# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""creator ledger: balances, sales and payouts

Revision ID: s1t2u3v4w5x6
Revises: r1s2t3u4v5w6
Create Date: 2026-08-23

Creator balances, sales and payouts had no tables at all. All three lived in
``RevenueSplitEngine``'s dictionaries, so a restart forgot every sale, every
balance and every payout, and a Stripe transfer had nothing to reconcile
against (F208).

Three design decisions are carried by the DDL rather than by application code:

**Money is ``NUMERIC(18, 2)``.** These are the first exact-decimal money columns
in this schema; the other 104 are ``Float``. That is why ``payments/wallet.py``
has to refuse sub-cent amounts to keep its balances round-trippable (F235).
New tables have nothing to migrate, so this is the cheapest possible place to
stop inheriting the problem.

**The split identity is a CHECK.** ``platform_fee + creator_amount =
gross_amount`` makes the fee-truncation bug unrepresentable rather than merely
fixed: no row can exist where the parts do not sum to the whole (F206).

**Settlement is a foreign key.** ``creator_sales.settled_by_payout_id``
references ``creator_payouts.payout_id``, so a sale can be claimed by at most
one payout. In Python that was a filter that was simply absent, and every payout
claimed every historical transaction (F207).

``creator_balances`` is a cache, not the truth: it is always re-derivable from
the two append-only tables. It carries a ``version`` column because
``RevenueSplitEngine``'s RLock only serialises threads within one process, and
production runs several workers where an in-process lock protects nothing.
"""

from alembic import op
import sqlalchemy as sa

revision = "s1t2u3v4w5x6"
down_revision = "r1s2t3u4v5w6"
branch_labels = None
depends_on = None

# BIGINT on PostgreSQL; INTEGER on SQLite so the column aliases rowid and
# autoincrements. Same reasoning as PKBigInt in database/models.py (r1s2t3u4v5w6).
_PK = sa.BigInteger().with_variant(sa.Integer, "sqlite")
_MONEY = sa.Numeric(18, 2)


def upgrade() -> None:
    # creator_payouts first: creator_sales has a foreign key into it.
    op.create_table(
        "creator_payouts",
        sa.Column("id", _PK, primary_key=True, autoincrement=True),
        sa.Column("payout_id", sa.String(64), nullable=False, unique=True),
        sa.Column("creator_id", sa.String(64), nullable=False),
        sa.Column("amount_usd", _MONEY, nullable=False),
        sa.Column("currency", sa.String(3), nullable=False, server_default="USD"),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False, unique=True),
        sa.Column("stripe_transfer_id", sa.String(128), nullable=True, unique=True),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("amount_usd >= 0", name="ck_creator_payouts_amount_non_negative"),
        sa.CheckConstraint(
            "status IN ('pending','processing','paid','failed','simulated')",
            name="ck_creator_payouts_status",
        ),
    )
    op.create_index("ix_creator_payouts_payout_id", "creator_payouts", ["payout_id"])
    op.create_index("ix_creator_payouts_creator_id", "creator_payouts", ["creator_id"])
    op.create_index("ix_creator_payouts_status", "creator_payouts", ["status"])
    op.create_index("ix_creator_payouts_created_at", "creator_payouts", ["created_at"])
    op.create_index("idx_creator_payouts_creator_created", "creator_payouts", ["creator_id", "created_at"])

    op.create_table(
        "creator_sales",
        sa.Column("id", _PK, primary_key=True, autoincrement=True),
        sa.Column("transaction_id", sa.String(64), nullable=False, unique=True),
        sa.Column("strategy_id", sa.String(64), nullable=False),
        sa.Column("creator_id", sa.String(64), nullable=False),
        sa.Column("buyer_id", sa.String(64), nullable=False),
        sa.Column("gross_amount", _MONEY, nullable=False),
        sa.Column("platform_fee", _MONEY, nullable=False),
        sa.Column("creator_amount", _MONEY, nullable=False),
        sa.Column("currency", sa.String(3), nullable=False, server_default="USD"),
        sa.Column("transaction_type", sa.String(20), nullable=False),
        sa.Column("stripe_payment_intent_id", sa.String(128), nullable=True, unique=True),
        sa.Column("settled_by_payout_id", sa.String(64), nullable=True),
        sa.Column("refund_policy_applied", sa.String(32), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["settled_by_payout_id"],
            ["creator_payouts.payout_id"],
            name="fk_creator_sales_settled_by_payout",
            ondelete="SET NULL",
        ),
        # Integer cents, not the column type: SQLite stores NUMERIC as REAL, so
        # the plain form is evaluated in binary floating point there and refuses
        # a correct 1c + 6c = 7c split. Exact on both backends.
        sa.CheckConstraint(
            "CAST(ROUND(platform_fee * 100) AS INTEGER) "
            "+ CAST(ROUND(creator_amount * 100) AS INTEGER) "
            "= CAST(ROUND(gross_amount * 100) AS INTEGER)",
            name="ck_creator_sales_split_sums_to_gross",
        ),
        sa.CheckConstraint(
            "transaction_type IN ('purchase','subscription','refund')",
            name="ck_creator_sales_type",
        ),
    )
    op.create_index("ix_creator_sales_transaction_id", "creator_sales", ["transaction_id"])
    op.create_index("ix_creator_sales_strategy_id", "creator_sales", ["strategy_id"])
    op.create_index("ix_creator_sales_creator_id", "creator_sales", ["creator_id"])
    op.create_index("ix_creator_sales_buyer_id", "creator_sales", ["buyer_id"])
    op.create_index("ix_creator_sales_transaction_type", "creator_sales", ["transaction_type"])
    op.create_index("ix_creator_sales_created_at", "creator_sales", ["created_at"])
    # PostgreSQL does not index a foreign key column for you. This one is read
    # on every payout cycle ("which sales are still unsettled").
    op.create_index("ix_creator_sales_settled_by_payout_id", "creator_sales", ["settled_by_payout_id"])
    op.create_index("idx_creator_sales_creator_settled", "creator_sales", ["creator_id", "settled_by_payout_id"])
    op.create_index("idx_creator_sales_creator_created", "creator_sales", ["creator_id", "created_at"])

    op.create_table(
        "creator_balances",
        sa.Column("creator_id", sa.String(64), primary_key=True),
        sa.Column("pending_usd", _MONEY, nullable=False, server_default="0"),
        sa.Column("total_earned_usd", _MONEY, nullable=False, server_default="0"),
        sa.Column("total_paid_usd", _MONEY, nullable=False, server_default="0"),
        sa.Column("recoverable_usd", _MONEY, nullable=False, server_default="0"),
        sa.Column("stripe_account_id", sa.String(128), nullable=True),
        sa.Column("last_payout_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        # pending_usd is deliberately NOT constrained non-negative: the
        # allow_negative_balance refund policy exists to let it go below zero.
        # The other three are totals, and a negative total is meaningless.
        sa.CheckConstraint("total_earned_usd >= 0", name="ck_creator_balances_earned_non_negative"),
        sa.CheckConstraint("total_paid_usd >= 0", name="ck_creator_balances_paid_non_negative"),
        sa.CheckConstraint("recoverable_usd >= 0", name="ck_creator_balances_recoverable_non_negative"),
    )


def downgrade() -> None:
    # creator_sales first: it holds the foreign key into creator_payouts.
    op.drop_table("creator_balances")
    op.drop_table("creator_sales")
    op.drop_table("creator_payouts")

"""affiliates / affiliate_referrals / affiliate_payouts — the ledger was RAM

`AffiliateManager` kept every affiliate, referral and payout in module
dictionaries with nothing behind them. A restart erased what every affiliate
was owed, and each worker in a multi-worker deployment held its own disjoint
copy — two workers could each approve a withdrawal the other could not see
(F31/F32, second half).

Money is `Numeric(18, 2)`, following the creator ledger tables rather than the
104 Float money columns that preceded them: a commission that cannot round-trip
drifts against what was actually paid.

`commission_paid` is an amount, not a flag. It was a flag, and a withdrawal
therefore marked the referral that crossed the requested total as fully paid —
two 60.00 commissions against a 100.00 withdrawal destroyed 20.00.

`referred_user_id` is UNIQUE. `create_referral` enforces one referral per user
by scanning its own working set, which protects nothing across workers; the
database is what actually enforces it.

Revision ID: y4z5a6b7c8d9
Revises: x3y4z5a6b7c8
Create Date: 2026-09-13
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "y4z5a6b7c8d9"
down_revision = "x3y4z5a6b7c8"
branch_labels = None
depends_on = None

_AFFILIATES = "affiliates"
_REFERRALS = "affiliate_referrals"
_PAYOUTS = "affiliate_payouts"


def _has_table(name: str) -> bool:
    """Idempotent guard, matching the convention in the preceding migrations."""
    bind = op.get_bind()
    return sa.inspect(bind).has_table(name)


def _pk() -> sa.types.TypeEngine:
    """BigInteger on PostgreSQL, Integer on SQLite so it aliases rowid."""
    return sa.BigInteger().with_variant(sa.Integer, "sqlite")


def upgrade() -> None:
    if not _has_table(_AFFILIATES):
        op.create_table(
            _AFFILIATES,
            sa.Column("id", _pk(), primary_key=True, autoincrement=True),
            sa.Column("affiliate_id", sa.String(length=64), nullable=False, unique=True),
            sa.Column("user_id", sa.String(length=64), nullable=False, unique=True),
            sa.Column("code", sa.String(length=32), nullable=False, unique=True),
            sa.Column("level", sa.String(length=20), nullable=False),
            sa.Column("status", sa.String(length=20), nullable=False),
            sa.Column("payment_details_json", sa.Text(), nullable=True),
            sa.Column("total_referrals", sa.Integer(), nullable=False, server_default=sa.text("0")),
            sa.Column("total_revenue", sa.Numeric(18, 2), nullable=False, server_default=sa.text("0")),
            sa.Column("total_commissions", sa.Numeric(18, 2), nullable=False, server_default=sa.text("0")),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
            sa.CheckConstraint("total_revenue >= 0", name="ck_affiliates_revenue_non_negative"),
            sa.CheckConstraint("total_commissions >= 0", name="ck_affiliates_commissions_non_negative"),
            sa.CheckConstraint("total_referrals >= 0", name="ck_affiliates_referrals_non_negative"),
        )
        op.create_index(f"ix_{_AFFILIATES}_affiliate_id", _AFFILIATES, ["affiliate_id"], unique=True)
        op.create_index(f"ix_{_AFFILIATES}_user_id", _AFFILIATES, ["user_id"], unique=True)
        op.create_index(f"ix_{_AFFILIATES}_code", _AFFILIATES, ["code"], unique=True)
        op.create_index(f"ix_{_AFFILIATES}_status", _AFFILIATES, ["status"])
        op.create_index(f"ix_{_AFFILIATES}_created_at", _AFFILIATES, ["created_at"])

    if not _has_table(_REFERRALS):
        op.create_table(
            _REFERRALS,
            sa.Column("id", _pk(), primary_key=True, autoincrement=True),
            sa.Column("referral_id", sa.String(length=64), nullable=False, unique=True),
            sa.Column("affiliate_id", sa.String(length=64), nullable=False),
            sa.Column("referred_user_id", sa.String(length=64), nullable=False, unique=True),
            sa.Column("status", sa.String(length=20), nullable=False),
            sa.Column("tier", sa.String(length=20), nullable=True),
            sa.Column("subscription_amount", sa.Numeric(18, 2), nullable=True),
            sa.Column("commission_amount", sa.Numeric(18, 2), nullable=True),
            sa.Column("commission_paid", sa.Numeric(18, 2), nullable=False, server_default=sa.text("0")),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("converted_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
            sa.CheckConstraint("commission_paid >= 0", name="ck_affiliate_referrals_paid_non_negative"),
        )
        op.create_index(f"ix_{_REFERRALS}_referral_id", _REFERRALS, ["referral_id"], unique=True)
        op.create_index(f"ix_{_REFERRALS}_affiliate_id", _REFERRALS, ["affiliate_id"])
        op.create_index(f"ix_{_REFERRALS}_referred_user_id", _REFERRALS, ["referred_user_id"], unique=True)
        op.create_index(f"ix_{_REFERRALS}_status", _REFERRALS, ["status"])
        op.create_index(f"ix_{_REFERRALS}_created_at", _REFERRALS, ["created_at"])
        # The outstanding-commission read: one affiliate, by referral state.
        op.create_index("idx_affiliate_referrals_affiliate_status", _REFERRALS, ["affiliate_id", "status"])

    if not _has_table(_PAYOUTS):
        op.create_table(
            _PAYOUTS,
            sa.Column("id", _pk(), primary_key=True, autoincrement=True),
            sa.Column("payout_id", sa.String(length=64), nullable=False, unique=True),
            sa.Column("affiliate_id", sa.String(length=64), nullable=False),
            sa.Column("amount", sa.Numeric(18, 2), nullable=False),
            sa.Column("payment_method", sa.String(length=40), nullable=False),
            sa.Column("status", sa.String(length=20), nullable=False),
            sa.Column("transaction_id", sa.String(length=128), nullable=True),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column("settlements_json", sa.Text(), nullable=True),
            # sa.false(), not sa.text("0"): see x3y4z5a6b7c8 — PostgreSQL refuses
            # an integer default on a boolean. Unreachable on PostgreSQL until
            # 2026-09-25 (the chain stopped one revision earlier); SQLite still
            # renders DEFAULT 0, byte-identical.
            sa.Column("reversed", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
            sa.CheckConstraint("amount >= 0", name="ck_affiliate_payouts_amount_non_negative"),
        )
        op.create_index(f"ix_{_PAYOUTS}_payout_id", _PAYOUTS, ["payout_id"], unique=True)
        op.create_index(f"ix_{_PAYOUTS}_affiliate_id", _PAYOUTS, ["affiliate_id"])
        op.create_index(f"ix_{_PAYOUTS}_status", _PAYOUTS, ["status"])
        op.create_index(f"ix_{_PAYOUTS}_created_at", _PAYOUTS, ["created_at"])
        op.create_index("idx_affiliate_payouts_affiliate_created", _PAYOUTS, ["affiliate_id", "created_at"])


def downgrade() -> None:
    if _has_table(_PAYOUTS):
        op.drop_index("idx_affiliate_payouts_affiliate_created", table_name=_PAYOUTS)
        op.drop_index(f"ix_{_PAYOUTS}_created_at", table_name=_PAYOUTS)
        op.drop_index(f"ix_{_PAYOUTS}_status", table_name=_PAYOUTS)
        op.drop_index(f"ix_{_PAYOUTS}_affiliate_id", table_name=_PAYOUTS)
        op.drop_index(f"ix_{_PAYOUTS}_payout_id", table_name=_PAYOUTS)
        op.drop_table(_PAYOUTS)

    if _has_table(_REFERRALS):
        op.drop_index("idx_affiliate_referrals_affiliate_status", table_name=_REFERRALS)
        op.drop_index(f"ix_{_REFERRALS}_created_at", table_name=_REFERRALS)
        op.drop_index(f"ix_{_REFERRALS}_status", table_name=_REFERRALS)
        op.drop_index(f"ix_{_REFERRALS}_referred_user_id", table_name=_REFERRALS)
        op.drop_index(f"ix_{_REFERRALS}_affiliate_id", table_name=_REFERRALS)
        op.drop_index(f"ix_{_REFERRALS}_referral_id", table_name=_REFERRALS)
        op.drop_table(_REFERRALS)

    if _has_table(_AFFILIATES):
        op.drop_index(f"ix_{_AFFILIATES}_created_at", table_name=_AFFILIATES)
        op.drop_index(f"ix_{_AFFILIATES}_status", table_name=_AFFILIATES)
        op.drop_index(f"ix_{_AFFILIATES}_code", table_name=_AFFILIATES)
        op.drop_index(f"ix_{_AFFILIATES}_user_id", table_name=_AFFILIATES)
        op.drop_index(f"ix_{_AFFILIATES}_affiliate_id", table_name=_AFFILIATES)
        op.drop_table(_AFFILIATES)

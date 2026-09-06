# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""money on the paying path becomes NUMERIC

Revision ID: t1u2v3w4x5y6
Revises: s1t2u3v4w5x6
Create Date: 2026-09-06

`Float` is IEEE-754 binary and cannot represent 0.07, or 0.10, or any tenth. A
balance that is written, read and re-summed drifts, and a drift in a balance
column is money. The schema carried 61 money-ish `Float` columns against 8
`Numeric` -- the 8 being the creator-ledger tables added in s1t2u3v4w5x6, which
stopped inheriting the problem only because they were new (audit TODO item 4).

This converts the columns on the path that **pays or holds user money**. Ordered
by exposure, as the audit called for: the wallet ledger first, then payments,
then the figures a regulator or a tax authority reads.

| Table | Columns | Why it is on this list |
|---|---|---|
| `wallet_transactions` | amount, balance_after | The ledger. Every credit and debit, and the balance each one produced. |
| `crypto_payments` | amount_usd, amount_crypto, rate_usd | Money in, on a chain. |
| `chargebacks` | amount | Money going back out, under dispute. |
| `billing_history` | amount | What a customer was charged. |
| `reconciliation_records` | expected_amount, actual_amount, discrepancy | The check that DETECTS drift. In `Float` it was drifting itself. |
| `tax_reports` | total_revenue, taxable_amount, tax_rate_pct, tax_owed | A filing figure that drifts is a filing error. |
| `aml_alerts` | amount | Compared against a regulatory threshold. |
| `whitelabel_tenants` | revenue_usd | What a tenant is owed. |
| `sub_accounts` | initial_balance, current_balance, daily_loss_limit | Held money, and a risk-gate threshold. |

**Scales.** `NUMERIC(18, 2)` for fiat. `NUMERIC(28, 8)` for `amount_crypto` and
`rate_usd`, because a satoshi is 1e-8 and two decimal places would round it away
entirely. `tax_rate_pct` is `NUMERIC(9, 6)`: a rate rather than an amount, but it
multiplies one.

**Not converted, deliberately.** The trading-side tables -- `trades`, `orders`,
`positions`, `accounts`, `account_snapshots`, `signals`, `ai_signals`,
`predictions`, `tick_data`, `order_book_snapshots` -- stay `Float`. Their
runtime does too: `execution/position_tracker.py` holds every live position as
`float` across 35 importers. Converting the columns without the runtime produces
`Decimal` in the schema and `float` arithmetic above it, which is the boundary
bug rather than a fix for it. That is a separate change and it needs the runtime
moved first. `tests/unit/test_money_columns_are_exact.py` lists them, so the
remainder is a decision on the record rather than an oversight.

**SQLite.** SQLite has no native decimal type; SQLAlchemy stores these as REAL
and quantizes back to the declared scale on read, which round-trips exactly
across the whole realistic range (verified for both 2 and 8 decimal places).
PostgreSQL, which production runs, stores NUMERIC exactly. `batch_alter_table`
is used throughout because SQLite cannot `ALTER COLUMN` at all -- it rebuilds
the table instead.

**Existing rows.** Values already stored as floats are converted by the database
during the ALTER, so a balance that had already drifted keeps its drifted value.
This migration stops the drift; it does not retroactively correct one. Any
correction is a reconciliation against `wallet_transactions`, which is
append-only, and belongs in its own change with its own evidence.
"""

import sqlalchemy as sa
from alembic import op

revision = "t1u2v3w4x5y6"
down_revision = "s1t2u3v4w5x6"
branch_labels = None
depends_on = None

_MONEY = sa.Numeric(18, 2)
_CRYPTO = sa.Numeric(28, 8)
_RATE = sa.Numeric(9, 6)

#: (table, column, new type, old type, nullable)
_COLUMNS: tuple[tuple[str, str, sa.types.TypeEngine, sa.types.TypeEngine, bool], ...] = (
    ("wallet_transactions", "amount", _MONEY, sa.Float(), False),
    ("wallet_transactions", "balance_after", _MONEY, sa.Float(), False),
    ("crypto_payments", "amount_usd", _MONEY, sa.Float(), False),
    ("crypto_payments", "amount_crypto", _CRYPTO, sa.Float(), False),
    ("crypto_payments", "rate_usd", _CRYPTO, sa.Float(), False),
    ("chargebacks", "amount", _MONEY, sa.Float(), False),
    ("billing_history", "amount", _MONEY, sa.Float(), True),
    ("reconciliation_records", "expected_amount", _MONEY, sa.Float(), False),
    ("reconciliation_records", "actual_amount", _MONEY, sa.Float(), False),
    ("reconciliation_records", "discrepancy", _MONEY, sa.Float(), False),
    ("tax_reports", "total_revenue", _MONEY, sa.Float(), False),
    ("tax_reports", "taxable_amount", _MONEY, sa.Float(), False),
    ("tax_reports", "tax_rate_pct", _RATE, sa.Float(), False),
    ("tax_reports", "tax_owed", _MONEY, sa.Float(), False),
    ("aml_alerts", "amount", _MONEY, sa.Float(), False),
    ("whitelabel_tenants", "revenue_usd", _MONEY, sa.Float(), False),
    ("sub_accounts", "initial_balance", _MONEY, sa.Float(), True),
    ("sub_accounts", "current_balance", _MONEY, sa.Float(), True),
    ("sub_accounts", "daily_loss_limit", _MONEY, sa.Float(), True),
)


def _existing_tables() -> set[str]:
    """Only alter what is actually there.

    Several of these tables are declared behind a feature guard in
    database/models.py and may be absent from a given deployment. Altering a
    missing table aborts the whole migration, which would leave the wallet
    ledger -- the row that matters most -- unconverted because of a table
    nobody uses.
    """
    return set(sa.inspect(op.get_bind()).get_table_names())


def upgrade() -> None:
    present = _existing_tables()
    for table, column, new_type, _old_type, nullable in _COLUMNS:
        if table not in present:
            continue
        with op.batch_alter_table(table) as batch:
            batch.alter_column(column, type_=new_type, existing_nullable=nullable)


def downgrade() -> None:
    present = _existing_tables()
    for table, column, _new_type, old_type, nullable in _COLUMNS:
        if table not in present:
            continue
        with op.batch_alter_table(table) as batch:
            batch.alter_column(column, type_=old_type, existing_nullable=nullable)

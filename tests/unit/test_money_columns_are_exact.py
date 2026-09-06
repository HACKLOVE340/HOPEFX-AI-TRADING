"""TODO item 4 — money columns on the paying path must be exact, not `Float`.

`Float` is IEEE-754 binary: it cannot represent 0.07, or 0.10, or any tenth.
A balance that is written, read and re-summed drifts, and a drift in a balance
column is money. The schema had 61 money-ish `Float` columns against 8
`Numeric` — the 8 being the creator-ledger tables, the only exact ones.

This converts the columns on the path that **pays or holds user money**, and
asserts the property rather than the type: a repeated-addition case that `Float`
fails and `Numeric` passes, driven through the real ORM.

**Not converted here, with the reason for each** (asserted below so the list
cannot quietly shrink): the trading-side tables. `trades`, `orders`,
`positions`, `accounts`, `account_snapshots`, `signals`, `ai_signals`,
`predictions`, `tick_data` and `order_book_snapshots` carry prices and P&L that
`execution/position_tracker.py` holds as `float` across 35 importers. Converting
the columns without the runtime is how you get `Decimal` in the schema and
`float` arithmetic above it -- the boundary bug the money-precision skill is
about. They are a separate change, and they need the runtime moved first.
"""

from __future__ import annotations

import warnings
from decimal import Decimal

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session

from database import models as m

#: The columns this change makes exact: everything that pays or holds user money.
EXACT_COLUMNS: dict[str, tuple[str, ...]] = {
    "wallet_transactions": ("amount", "balance_after"),
    "crypto_payments": ("amount_usd", "amount_crypto", "rate_usd"),
    "chargebacks": ("amount",),
    "billing_history": ("amount",),
    "reconciliation_records": ("expected_amount", "actual_amount"),
    "tax_reports": ("total_revenue", "taxable_amount"),
    "aml_alerts": ("amount",),
    "whitelabel_tenants": ("revenue_usd",),
    "sub_accounts": ("initial_balance", "current_balance", "daily_loss_limit"),
}

#: Still `Float`, deliberately. Each needs its runtime moved off float first.
STILL_FLOAT_TABLES = frozenset(
    {
        "trades",
        "orders",
        "positions",
        "accounts",
        "account_snapshots",
        "signals",
        "ai_signals",
        "predictions",
        "tick_data",
        "order_book_snapshots",
        "performance_metrics",
        "performance_metric_samples",
    }
)


def _table(name: str):
    for mapper in m.Base.registry.mappers:
        table = mapper.local_table
        if table is not None and table.name == name:
            return table
    pytest.skip(f"{name} is not mapped in this build")
    return None


@pytest.mark.parametrize(("table_name", "columns"), sorted(EXACT_COLUMNS.items()))
def test_the_paying_path_is_numeric(table_name: str, columns: tuple[str, ...]) -> None:
    """The type, asserted per column so a revert is visible."""
    table = _table(table_name)
    for column in columns:
        assert column in table.c, f"{table_name}.{column} is missing"
        kind = table.c[column].type
        assert isinstance(kind, sa.Numeric) and not isinstance(kind, sa.Float), (
            f"{table_name}.{column} is {kind!r}; money that is paid or held must be Numeric"
        )
        assert kind.scale and kind.scale >= 2, f"{table_name}.{column} has scale {kind.scale}"


def test_crypto_amounts_keep_eight_decimals() -> None:
    """A satoshi is 1e-8. Two decimal places would round it away entirely."""
    table = _table("crypto_payments")
    assert table.c["amount_crypto"].type.scale >= 8
    assert table.c["rate_usd"].type.scale >= 8


def test_repeated_addition_is_exact_where_float_drifts() -> None:
    """The property, not the type. This is the case `Float` fails.

    Ten increments of 0.07 sum to 0.7000000000000002 in binary floating point.
    A balance column that does this is losing money in the last bits on every
    read-modify-write cycle.
    """
    engine = sa.create_engine("sqlite://")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        m.Base.metadata.create_all(engine, tables=[_table("wallet_transactions")])

        with Session(engine) as session:
            running = Decimal("0")
            for index in range(10):
                running += Decimal("0.07")
                session.add(
                    m.WalletTransaction(
                        transaction_id=f"txn-{index}",
                        user_id="u-1",
                        transaction_type="credit",
                        amount=Decimal("0.07"),
                        balance_after=running,
                        currency="USD",
                    )
                )
            session.commit()

            rows = session.query(m.WalletTransaction).order_by(m.WalletTransaction.id).all()
            total = sum((row.amount for row in rows), Decimal("0"))

            assert total == Decimal("0.70"), f"ten credits of 0.07 summed to {total}"
            assert rows[-1].balance_after == Decimal("0.70")
            # The same arithmetic in binary floating point, for contrast.
            assert sum(0.07 for _ in range(10)) != 0.70


def test_a_value_survives_the_round_trip_unchanged() -> None:
    """Written, read back, identical — including a tenth, which `Float` cannot hold."""
    engine = sa.create_engine("sqlite://")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        m.Base.metadata.create_all(engine, tables=[_table("wallet_transactions")])

        with Session(engine) as session:
            for index, value in enumerate(("0.10", "0.07", "1234567.89", "0.01")):
                session.add(
                    m.WalletTransaction(
                        transaction_id=f"txn-rt-{index}",
                        user_id="u-2",
                        transaction_type="credit",
                        amount=Decimal(value),
                        balance_after=Decimal(value),
                        currency="USD",
                    )
                )
            session.commit()

            stored = [row.amount for row in session.query(m.WalletTransaction).order_by(m.WalletTransaction.id)]
            assert stored == [Decimal("0.10"), Decimal("0.07"), Decimal("1234567.89"), Decimal("0.01")]


def test_the_unconverted_tables_are_listed_rather_than_forgotten() -> None:
    """The remainder is a decision on the record, not an oversight.

    If a table here becomes Numeric, delete its row from STILL_FLOAT_TABLES in
    the same commit. If a NEW money table appears as Float, it belongs in one of
    the two lists with a reason — not in neither.
    """
    money = ("balance", "amount", "equity", "pnl", "price", "revenue", "margin", "payout", "fee", "commission")
    unlisted: list[str] = []
    for mapper in m.Base.registry.mappers:
        table = mapper.local_table
        if table is None or table.name in STILL_FLOAT_TABLES or table.name in EXACT_COLUMNS:
            continue
        for column in table.c:
            if isinstance(column.type, sa.Float) and any(token in column.name.lower() for token in money):
                unlisted.append(f"{table.name}.{column.name}")
    assert not unlisted, (
        "these money columns are Float and appear in neither list. Convert them, "
        f"or add the table to STILL_FLOAT_TABLES with a reason: {sorted(set(unlisted))}"
    )

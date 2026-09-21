# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
The creator ledger tables, against a real database.

A model class that imports proves nothing. What these tests check is that the
constraints actually refuse bad rows when a database enforces them — because the
whole argument for putting these rules in the schema is that they hold even when
the Python that was supposed to check them is wrong or absent.

SQLite is used here because it is what the test suite runs on; the same DDL is
emitted for PostgreSQL, with BIGINT identity via PKBigInt.
"""

from __future__ import annotations

from datetime import timezone
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, event, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from database.models import CreatorBalanceRow, CreatorPayoutRow, CreatorSale

UTC = timezone.utc
pytestmark = pytest.mark.unit


@pytest.fixture
def session():
    engine = create_engine("sqlite://")

    # SQLite ignores foreign keys unless asked. Without this the FK test would
    # pass for the wrong reason.
    @event.listens_for(engine, "connect")
    def _fk_on(dbapi_conn, _rec):
        dbapi_conn.execute("PRAGMA foreign_keys=ON")

    for table in (CreatorPayoutRow.__table__, CreatorSale.__table__, CreatorBalanceRow.__table__):
        table.create(engine)
    with sessionmaker(bind=engine)() as s:
        yield s


def a_payout(session, payout_id="po-1", **kw):
    row = CreatorPayoutRow(
        payout_id=payout_id,
        creator_id=kw.get("creator_id", "c1"),
        amount_usd=kw.get("amount_usd", Decimal("80.00")),
        status=kw.get("status", "paid"),
        idempotency_key=kw.get("idempotency_key", f"idem-{payout_id}"),
    )
    session.add(row)
    session.commit()
    return row


def a_sale(session, **kw):
    row = CreatorSale(
        transaction_id=kw.get("transaction_id", "txn-1"),
        strategy_id="s1",
        creator_id="c1",
        buyer_id="b1",
        gross_amount=kw.get("gross_amount", Decimal("100.00")),
        platform_fee=kw.get("platform_fee", Decimal("20.00")),
        creator_amount=kw.get("creator_amount", Decimal("80.00")),
        transaction_type=kw.get("transaction_type", "purchase"),
        settled_by_payout_id=kw.get("settled_by_payout_id"),
        refund_policy_applied=kw.get("refund_policy_applied"),
    )
    session.add(row)
    session.commit()
    return row


# --------------------------------------------------------------------------
# The split identity
# --------------------------------------------------------------------------


def test_a_split_that_does_not_sum_to_the_gross_is_refused(session):
    """
    The constraint that makes the to_cents truncation bug unrepresentable: no
    row can exist where the parts do not add up to the whole.
    """
    with pytest.raises(IntegrityError):
        a_sale(session, gross_amount=Decimal("100.00"), platform_fee=Decimal("20.00"), creator_amount=Decimal("79.99"))


def test_a_correct_split_is_accepted(session):
    row = a_sale(session)
    assert row.platform_fee + row.creator_amount == row.gross_amount


def test_a_refund_is_the_negative_mirror_and_still_satisfies_the_identity(session):
    row = a_sale(
        session,
        transaction_id="txn-refund",
        gross_amount=Decimal("-100.00"),
        platform_fee=Decimal("-20.00"),
        creator_amount=Decimal("-80.00"),
        transaction_type="refund",
        refund_policy_applied="deduct_next_payout",
    )
    assert row.gross_amount == Decimal("-100.00")


def test_an_unknown_transaction_type_is_refused(session):
    with pytest.raises(IntegrityError):
        a_sale(session, transaction_id="txn-bad", transaction_type="chargeback")


# --------------------------------------------------------------------------
# Money precision
# --------------------------------------------------------------------------


def test_money_round_trips_as_exact_decimal(session):
    """
    Numeric(18, 2), not Float. A balance written as Decimal must read back as the
    same Decimal — the property payments/wallet.py has to defend with a sub-cent
    guard precisely because its column is Float (F235).
    """
    session.add(
        CreatorBalanceRow(
            creator_id="c1",
            pending_usd=Decimal("1234.56"),
            total_earned_usd=Decimal("0.07"),
            total_paid_usd=Decimal("0.03"),
            recoverable_usd=Decimal("0.01"),
        )
    )
    session.commit()
    session.expire_all()

    row = session.get(CreatorBalanceRow, "c1")
    assert row.pending_usd == Decimal("1234.56")
    assert isinstance(row.pending_usd, Decimal), "money came back as a float"
    assert row.total_earned_usd == Decimal("0.07")
    assert row.recoverable_usd == Decimal("0.01")


def test_a_negative_recoverable_amount_is_refused(session):
    """A debt is owed or it is not. A negative one would mean the platform owes
    the creator through a field that is netted off their earnings."""
    with pytest.raises(IntegrityError):
        session.add(CreatorBalanceRow(creator_id="c2", recoverable_usd=Decimal("-1.00")))
        session.commit()


# --------------------------------------------------------------------------
# Idempotency and settlement
# --------------------------------------------------------------------------


def test_two_payouts_cannot_share_an_idempotency_key(session):
    """The guard against a retried transfer paying twice."""
    a_payout(session, "po-1", idempotency_key="same-key")
    with pytest.raises(IntegrityError):
        a_payout(session, "po-2", idempotency_key="same-key")


def test_two_payouts_cannot_share_a_stripe_transfer_id(session):
    a_payout(session, "po-1")
    session.query(CreatorPayoutRow).filter_by(payout_id="po-1").update({"stripe_transfer_id": "tr_1"})
    session.commit()
    with pytest.raises(IntegrityError):
        p2 = CreatorPayoutRow(
            payout_id="po-2",
            creator_id="c1",
            amount_usd=Decimal("1.00"),
            status="paid",
            idempotency_key="idem-2",
            stripe_transfer_id="tr_1",
        )
        session.add(p2)
        session.commit()


def test_transaction_ids_are_unique(session):
    a_sale(session, transaction_id="txn-dup")
    with pytest.raises(IntegrityError):
        a_sale(session, transaction_id="txn-dup")


def test_a_sale_cannot_be_settled_by_a_payout_that_does_not_exist(session):
    """
    The foreign key is what keeps F207 fixed at the storage layer rather than in
    a filter someone can forget to write again.
    """
    with pytest.raises(IntegrityError):
        a_sale(session, transaction_id="txn-orphan", settled_by_payout_id="po-does-not-exist")


def test_a_sale_settled_by_a_real_payout_is_accepted(session):
    a_payout(session, "po-1")
    row = a_sale(session, transaction_id="txn-settled", settled_by_payout_id="po-1")
    assert row.settled_by_payout_id == "po-1"


def test_an_unknown_payout_status_is_refused(session):
    with pytest.raises(IntegrityError):
        a_payout(session, "po-bad", status="probably_fine")


@pytest.mark.parametrize("status", ["pending", "processing", "paid", "failed", "simulated"])
def test_every_status_the_engine_emits_is_permitted(session, status):
    """The CHECK and monetization.revenue_split.PayoutStatus must not drift
    apart — a status the engine writes and the table rejects loses a payout."""
    a_payout(session, f"po-{status}", status=status)


def test_the_check_covers_exactly_the_engines_statuses():
    from sqlalchemy import CheckConstraint

    from monetization.revenue_split import PayoutStatus

    clause = next(
        str(c.sqltext)
        for c in CreatorPayoutRow.__table__.constraints
        if isinstance(c, CheckConstraint) and c.name == "ck_creator_payouts_status"
    )
    for status in PayoutStatus:
        assert f"'{status.value}'" in clause, f"PayoutStatus.{status.name} is not permitted by the table"


# --------------------------------------------------------------------------
# The balance is derivable from the events
# --------------------------------------------------------------------------


def test_the_pending_balance_can_be_rederived_from_unsettled_sales(session):
    """
    The reason the balance is a cache rather than the truth: it must always be
    reconstructible from the append-only rows. If this ever stops holding, the
    stored number is wrong, not the sum.
    """
    a_payout(session, "po-1")
    a_sale(session, transaction_id="t1", settled_by_payout_id="po-1")  # paid out
    a_sale(session, transaction_id="t2")  # still pending
    a_sale(session, transaction_id="t3")  # still pending

    derived = session.execute(
        text(
            "SELECT COALESCE(SUM(creator_amount), 0) FROM creator_sales "
            "WHERE creator_id = :c AND settled_by_payout_id IS NULL"
        ),
        {"c": "c1"},
    ).scalar_one()

    assert Decimal(str(derived)) == Decimal("160.00")


# --------------------------------------------------------------------------
# The split CHECK must be exact for small amounts on every backend
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("gross", "fee", "creator"),
    [
        ("0.07", "0.01", "0.06"),  # the case that exposed it
        ("0.03", "0.01", "0.02"),
        ("0.01", "0.00", "0.01"),
        ("19.99", "4.00", "15.99"),
        ("100.00", "20.00", "80.00"),
        ("1234.56", "246.91", "987.65"),
        ("-0.07", "-0.01", "-0.06"),  # the refund mirror
    ],
)
def test_a_correct_split_is_accepted_at_every_scale(session, gross, fee, creator):
    """
    SQLite has no exact decimal — it stores NUMERIC as REAL. Written as
    ``platform_fee + creator_amount = gross_amount`` this CHECK evaluates in
    binary floating point there and refuses a correct 1c + 6c = 7c split, since
    0.01 + 0.06 is 0.06999999999999999. PostgreSQL, where NUMERIC is exact,
    would have accepted it: the constraint was right in production and silently
    wrong on every SQLite deployment, rejecting legitimate small sales.

    Comparing in integer cents is exact on both.
    """
    row = a_sale(
        session,
        transaction_id=f"txn-{gross}",
        gross_amount=Decimal(gross),
        platform_fee=Decimal(fee),
        creator_amount=Decimal(creator),
        transaction_type="refund" if Decimal(gross) < 0 else "purchase",
    )
    assert row.platform_fee + row.creator_amount == row.gross_amount


@pytest.mark.parametrize(
    ("gross", "fee", "creator"),
    [
        ("0.07", "0.01", "0.07"),  # one cent too much
        ("100.00", "20.00", "79.99"),
        ("100.00", "20.01", "80.00"),
    ],
)
def test_a_wrong_split_is_still_refused_at_every_scale(session, gross, fee, creator):
    """The looser comparison must not have loosened what it catches."""
    with pytest.raises(IntegrityError):
        a_sale(
            session,
            transaction_id=f"bad-{gross}-{creator}",
            gross_amount=Decimal(gross),
            platform_fee=Decimal(fee),
            creator_amount=Decimal(creator),
        )

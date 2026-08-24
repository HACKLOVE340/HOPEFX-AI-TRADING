# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
RevenueSplitEngine writing to the creator ledger tables.

The tables existing is not the fix; the engine using them is. What is pinned
here is survival across a restart, which is the whole point of F208: a new engine
built against the same database must see the same sales, the same balances and
the same settled/unsettled split as the one that recorded them.

The other half is honesty about failure. A sale the ledger could not record has
not happened, and reporting it as recorded leaves the creator's balance moved in
memory and absent from the durable record — the divergence a reconciliation can
never close, and the same rule already applied to payments/wallet.py.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from monetization.refund_policy import RefundPolicy
from monetization.revenue_split import PayoutStatus, RevenueSplitEngine

pytestmark = pytest.mark.unit


class Store:
    def __init__(self, policy: RefundPolicy | None = None):
        self._policy = policy

    def get(self, key, default=None):
        return self._policy.value if self._policy is not None else default


@pytest.fixture
def session_factory(tmp_path):
    """A real file-backed database, so a second engine can reopen it."""
    from database.models import CreatorBalanceRow, CreatorPayoutRow, CreatorSale

    url = f"sqlite:///{tmp_path / 'ledger.db'}"
    eng = create_engine(url)

    @event.listens_for(eng, "connect")
    def _fk_on(dbapi_conn, _rec):
        dbapi_conn.execute("PRAGMA foreign_keys=ON")

    for t in (CreatorPayoutRow.__table__, CreatorSale.__table__, CreatorBalanceRow.__table__):
        t.create(eng)
    return sessionmaker(bind=eng)


def new_engine(session_factory, policy: RefundPolicy | None = None) -> RevenueSplitEngine:
    e = RevenueSplitEngine(session_factory=session_factory)
    e.config_store = Store(policy)
    return e


def sell(eng, gross="100.00", creator="c1"):
    return eng.record_sale(strategy_id="s1", creator_id=creator, buyer_id="b1", gross_amount=float(Decimal(gross)))


# --------------------------------------------------------------------------
# Survival across a restart — the point of F208
# --------------------------------------------------------------------------


def test_a_sale_survives_a_restart(session_factory):
    eng = new_engine(session_factory)
    sale = sell(eng, "100.00")

    reopened = new_engine(session_factory)

    restored = reopened.get_creator_transactions("c1")
    assert len(restored) == 1
    assert restored[0].transaction_id == sale.transaction_id
    assert restored[0].gross_amount == sale.gross_amount
    assert restored[0].creator_amount == sale.creator_amount


def test_a_balance_survives_a_restart(session_factory):
    eng = new_engine(session_factory)
    sale = sell(eng, "100.00")

    reopened = new_engine(session_factory)

    bal = reopened.get_creator_balance("c1")
    assert bal.pending_usd == sale.creator_amount
    assert bal.total_earned_usd == sale.creator_amount
    assert bal.total_paid_usd == Decimal("0.00")


def test_money_survives_the_round_trip_as_exact_decimal(session_factory):
    """Numeric(18, 2), so no cent is lost to a float representation."""
    eng = new_engine(session_factory)
    for amount in ("0.01", "0.07", "19.99", "1234.56"):
        sell(eng, amount)
    expected = eng.get_creator_balance("c1").pending_usd

    reopened = new_engine(session_factory)

    assert reopened.get_creator_balance("c1").pending_usd == expected
    assert isinstance(reopened.get_creator_balance("c1").pending_usd, Decimal)


def test_a_stripe_account_survives_a_restart(session_factory):
    """Without it, a restart makes every creator ineligible for payout and the
    next cycle silently pays nobody."""
    eng = new_engine(session_factory)
    sell(eng, "100.00")
    eng.register_stripe_account("c1", "acct_live")

    reopened = new_engine(session_factory)
    assert reopened.get_creator_balance("c1").stripe_account_id == "acct_live"


def test_the_settled_unsettled_split_survives_a_restart(session_factory, monkeypatch):
    """
    The one that prevents paying twice. If a restart forgets which sales a payout
    already settled, the next cycle re-claims them and the creator is paid again
    for the same work (F207).
    """
    import monetization.revenue_split as rs

    eng = new_engine(session_factory)
    sale = sell(eng, "100.00")
    eng.register_stripe_account("c1", "acct_live")

    def _paid(payout, bal):
        payout.status = PayoutStatus.PAID
        payout.stripe_transfer_id = "tr_1"
        return payout

    eng._execute_stripe_transfer = _paid
    monkeypatch.setattr(rs, "_STRIPE_AVAILABLE", True)
    payouts = eng.process_weekly_payouts()
    assert payouts[0].status is PayoutStatus.PAID

    reopened = new_engine(session_factory)

    restored = {t.transaction_id: t for t in reopened.get_creator_transactions("c1")}
    assert restored[sale.transaction_id].settled_by_payout_id == payouts[0].payout_id
    assert reopened.get_creator_balance("c1").pending_usd == Decimal("0.00")
    assert reopened.get_creator_balance("c1").total_paid_usd == sale.creator_amount

    # And the next cycle must find nothing left to pay.
    reopened._execute_stripe_transfer = _paid
    assert reopened.process_weekly_payouts() == []


def test_a_carried_refund_debt_survives_a_restart(session_factory, monkeypatch):
    """recoverable_usd is money the platform is owed. Forgetting it on restart
    writes the debt off silently."""
    import monetization.revenue_split as rs

    eng = new_engine(session_factory, RefundPolicy.DEDUCT_NEXT_PAYOUT)
    sale = sell(eng, "100.00")
    eng.register_stripe_account("c1", "acct_live")
    eng._execute_stripe_transfer = lambda p, b: (setattr(p, "status", PayoutStatus.PAID), p)[1]
    monkeypatch.setattr(rs, "_STRIPE_AVAILABLE", True)
    eng.process_weekly_payouts()
    eng.record_refund(sale.transaction_id)
    assert eng.get_creator_balance("c1").recoverable_usd == sale.creator_amount

    reopened = new_engine(session_factory, RefundPolicy.DEDUCT_NEXT_PAYOUT)
    assert reopened.get_creator_balance("c1").recoverable_usd == sale.creator_amount


def test_the_applied_refund_policy_survives_a_restart(session_factory):
    """The stamp is worthless if it is not durable."""
    eng = new_engine(session_factory, RefundPolicy.PLATFORM_ABSORBS)
    sale = sell(eng, "100.00")
    refund = eng.record_refund(sale.transaction_id)

    reopened = new_engine(session_factory, RefundPolicy.ALLOW_NEGATIVE_BALANCE)

    restored = {t.transaction_id: t for t in reopened.get_creator_transactions("c1")}
    assert restored[refund.transaction_id].refund_policy_applied == RefundPolicy.PLATFORM_ABSORBS.value


# --------------------------------------------------------------------------
# The balance is a cache the events can re-derive
# --------------------------------------------------------------------------


def test_the_restored_balance_agrees_with_the_sum_of_unsettled_sales(session_factory):
    """The design's central claim, checked rather than asserted."""
    eng = new_engine(session_factory)
    for amount in ("10.00", "25.50", "3.33"):
        sell(eng, amount)

    reopened = new_engine(session_factory)
    bal = reopened.get_creator_balance("c1")
    derived = sum(
        (t.creator_amount for t in reopened.get_creator_transactions("c1") if t.settled_by_payout_id is None),
        Decimal("0.00"),
    )
    assert bal.pending_usd == derived


# --------------------------------------------------------------------------
# Honesty about failure
# --------------------------------------------------------------------------


def test_no_session_factory_still_works_in_memory(session_factory):
    """Paper trading and tests run without a database. That is not a failure."""
    eng = RevenueSplitEngine()
    eng.config_store = Store()
    sale = sell(eng, "100.00")
    assert sale is not None
    assert eng.get_creator_balance("c1").pending_usd == sale.creator_amount


def test_a_sale_the_ledger_rejected_is_not_reported_as_recorded(session_factory):
    """
    A sale that could not be written has not happened. Reporting it moves the
    creator's balance in memory while the durable record has no trace of it.
    """

    class Exploding:
        def __call__(self):
            return self

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def add(self, _row):
            raise RuntimeError("disk full")

        def commit(self):  # pragma: no cover
            raise AssertionError("unreachable")

        def rollback(self):
            return None

        def close(self):
            return None

        def query(self, *_a, **_k):
            raise RuntimeError("disk full")

    eng = RevenueSplitEngine(session_factory=Exploding())
    eng.config_store = Store()

    with pytest.raises(RuntimeError):
        sell(eng, "100.00")

    assert eng.get_creator_balance("c1").pending_usd == Decimal("0.00"), (
        "the balance moved for a sale the ledger never recorded"
    )

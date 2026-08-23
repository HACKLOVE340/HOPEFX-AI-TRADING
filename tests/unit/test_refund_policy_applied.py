# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
Refunding a sale, under each of the three policies.

The case that matters is a sale that has **already been settled by a payout**:
the creator's share has left the platform, so refunding the buyer means the money
has to come back from somewhere. Which of the three answers applies is the
operator's setting (monetization/refund_policy.py).

Before this, ``record_refund`` did none of that. It clamped the creator balance
with ``max(Decimal("0.00"), ...)`` and never looked at whether the sale had been
paid out, so the shortfall on a settled refund was neither deferred nor debited —
it was silently forgotten, and the platform's books and the creator's books
disagreed with nothing to reconcile them.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

UTC = timezone.utc

import pytest

from monetization.refund_policy import RefundPolicy
from monetization.revenue_split import PayoutStatus, RevenueSplitEngine, TransactionType

pytestmark = pytest.mark.unit


class Store:
    """A config_store stand-in holding one policy."""

    def __init__(self, policy: RefundPolicy | None = None):
        self._policy = policy

    def get(self, key, default=None):
        return self._policy.value if self._policy is not None else default


def engine(policy: RefundPolicy | None = None) -> RevenueSplitEngine:
    eng = RevenueSplitEngine()
    eng.config_store = Store(policy)
    return eng


def sell(eng, gross="100.00", creator="c1"):
    return eng.record_sale(strategy_id="s1", creator_id=creator, buyer_id="b1", gross_amount=float(Decimal(gross)))


def pay_out(eng, monkeypatch=None, creator="c1"):
    """Run a payout that genuinely settles.

    Without a transfer backend a payout is SIMULATED, which deliberately does
    *not* claim the creator was paid and leaves the balance pending (F204). That
    is correct, and it means the "already settled" case these tests are about
    only exists when a transfer actually succeeded — so the transfer is stubbed
    rather than skipped.
    """
    eng.register_stripe_account(creator, "acct_test")

    def _paid(payout, bal):
        payout.status = PayoutStatus.PAID
        payout.stripe_transfer_id = "tr_test"
        payout.completed_at = datetime.now(UTC)
        return payout

    eng._execute_stripe_transfer = _paid
    import monetization.revenue_split as rs

    original = rs._STRIPE_AVAILABLE
    rs._STRIPE_AVAILABLE = True
    try:
        payouts = eng.process_weekly_payouts()
    finally:
        rs._STRIPE_AVAILABLE = original
    return [p for p in payouts if p.creator_id == creator]


# --------------------------------------------------------------------------
# An unsettled sale: the money never left, so there is nothing to recover
# --------------------------------------------------------------------------


@pytest.mark.parametrize("policy", list(RefundPolicy))
def test_refunding_an_unsettled_sale_just_reverses_it(policy):
    """No payout has happened, so the creator's share is still pending. Every
    policy behaves identically here — the policy only governs money that has
    already left."""
    eng = engine(policy)
    sale = sell(eng, "100.00")
    # Derived, not assumed: the platform fee percentage is a business setting
    # and hardcoding it here would make these tests fail for the wrong reason.
    share = sale.creator_amount
    assert eng.get_creator_balance("c1").pending_usd == share

    refund = eng.record_refund(sale.transaction_id)

    assert refund is not None
    bal = eng.get_creator_balance("c1")
    assert bal.pending_usd == Decimal("0.00")
    assert bal.total_earned_usd == Decimal("0.00")
    assert bal.recoverable_usd == Decimal("0.00"), "nothing should be owed — the money never left"


# --------------------------------------------------------------------------
# A settled sale: the three policies diverge
# --------------------------------------------------------------------------


def test_deduct_next_payout_carries_the_shortfall_forward():
    """
    The default. The creator has already been paid, so there is nothing pending
    to debit. The amount becomes recoverable and is netted off the next payout —
    it is not forgotten, and the balance never goes negative.
    """
    eng = engine(RefundPolicy.DEDUCT_NEXT_PAYOUT)
    sale = sell(eng, "100.00")
    paid = pay_out(eng)
    assert paid and paid[0].status is PayoutStatus.PAID
    assert eng._transactions[sale.transaction_id].settled_by_payout_id is not None

    eng.record_refund(sale.transaction_id)

    bal = eng.get_creator_balance("c1")
    assert bal.pending_usd == Decimal("0.00")
    assert bal.recoverable_usd == sale.creator_amount, "the shortfall was forgotten instead of carried"


def test_deduct_next_payout_nets_the_debt_off_the_next_sale():
    """The recoverable amount has to actually reduce what is paid next, or
    'deduct from next payout' is a label on nothing."""
    eng = engine(RefundPolicy.DEDUCT_NEXT_PAYOUT)
    sale = sell(eng, "100.00")
    pay_out(eng)
    eng.record_refund(sale.transaction_id)
    assert eng.get_creator_balance("c1").recoverable_usd == sale.creator_amount

    # An identical sale earns the creator exactly the debt, clearing it.
    sell(eng, "100.00")
    bal = eng.get_creator_balance("c1")
    assert bal.recoverable_usd == Decimal("0.00")
    assert bal.pending_usd == Decimal("0.00"), "the new earnings should have cleared the debt first"

    # A further sale is theirs to keep.
    third = sell(eng, "100.00")
    assert eng.get_creator_balance("c1").pending_usd == third.creator_amount


def test_allow_negative_balance_debits_past_zero():
    eng = engine(RefundPolicy.ALLOW_NEGATIVE_BALANCE)
    sale = sell(eng, "100.00")
    pay_out(eng)

    eng.record_refund(sale.transaction_id)

    bal = eng.get_creator_balance("c1")
    assert bal.pending_usd == -sale.creator_amount, "the policy is to show the true position"
    assert bal.recoverable_usd == Decimal("0.00"), "the debt is in the balance, not carried separately"


def test_platform_absorbs_leaves_the_creator_untouched():
    eng = engine(RefundPolicy.PLATFORM_ABSORBS)
    sale = sell(eng, "100.00")
    pay_out(eng)
    earned_before = eng.get_creator_balance("c1").total_earned_usd

    eng.record_refund(sale.transaction_id)

    bal = eng.get_creator_balance("c1")
    assert bal.pending_usd == Decimal("0.00")
    assert bal.recoverable_usd == Decimal("0.00")
    assert bal.total_earned_usd == earned_before, "the creator's earnings were clawed back anyway"


# --------------------------------------------------------------------------
# The policy that was applied must be recorded, not re-derived
# --------------------------------------------------------------------------


@pytest.mark.parametrize("policy", list(RefundPolicy))
def test_the_refund_records_which_policy_it_used(policy):
    eng = engine(policy)
    sale = sell(eng, "100.00")
    pay_out(eng)

    refund = eng.record_refund(sale.transaction_id)

    assert refund.refund_policy_applied == policy.value


def test_changing_the_setting_does_not_rewrite_an_existing_refund():
    """
    The whole reason the policy is stamped rather than re-read. Flipping the
    setting must change new refunds only; a historical refund keeps explaining
    itself with the rule that was actually applied to it.
    """
    eng = engine(RefundPolicy.PLATFORM_ABSORBS)
    first_sale = sell(eng, "100.00")
    pay_out(eng)
    first_refund = eng.record_refund(first_sale.transaction_id)
    assert first_refund.refund_policy_applied == RefundPolicy.PLATFORM_ABSORBS.value

    eng.config_store = Store(RefundPolicy.ALLOW_NEGATIVE_BALANCE)

    second_sale = sell(eng, "50.00")
    pay_out(eng)
    second_refund = eng.record_refund(second_sale.transaction_id)

    assert second_refund.refund_policy_applied == RefundPolicy.ALLOW_NEGATIVE_BALANCE.value
    assert first_refund.refund_policy_applied == RefundPolicy.PLATFORM_ABSORBS.value


# --------------------------------------------------------------------------
# Shape guarantees that hold under every policy
# --------------------------------------------------------------------------


@pytest.mark.parametrize("policy", list(RefundPolicy))
def test_the_refund_row_is_a_negative_mirror_of_the_sale(policy):
    eng = engine(policy)
    sale = sell(eng, "100.00")

    refund = eng.record_refund(sale.transaction_id)

    assert refund.transaction_type is TransactionType.REFUND
    assert refund.gross_amount == -sale.gross_amount
    assert refund.platform_fee == -sale.platform_fee
    assert refund.creator_amount == -sale.creator_amount
    # The split identity must survive the sign flip.
    assert refund.platform_fee + refund.creator_amount == refund.gross_amount


@pytest.mark.parametrize("policy", list(RefundPolicy))
def test_refunding_an_unknown_transaction_returns_none(policy):
    eng = engine(policy)
    assert eng.record_refund("no-such-transaction") is None


def test_an_unreadable_policy_setting_falls_back_to_the_default_not_a_crash():
    """A broken config store must not take down a refund."""

    class Broken:
        def get(self, key, default=None):
            raise RuntimeError("redis down")

    eng = RevenueSplitEngine()
    eng.config_store = Broken()
    sale = sell(eng, "100.00")
    pay_out(eng)

    refund = eng.record_refund(sale.transaction_id)

    assert refund.refund_policy_applied == RefundPolicy.DEDUCT_NEXT_PAYOUT.value
    assert eng.get_creator_balance("c1").recoverable_usd == sale.creator_amount

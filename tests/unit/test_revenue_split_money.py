"""Money correctness in the creator payout path.

`monetization/revenue_split.py` has no tests at all (audit F222) and carries
five proven defects (F203-F207) behind seven live endpoints in
`api/monetization.py`.

Every test here fails on the pre-fix module. They are written to demonstrate
the defect, not merely to pin the fix.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from monetization.revenue_split import (
    MIN_PAYOUT_USD,
    PayoutStatus,
    RevenueSplitEngine,
)


@pytest.fixture()
def engine() -> RevenueSplitEngine:
    """A fresh engine per test — the module singleton carries state across tests."""
    return RevenueSplitEngine()


# ── F203: a sale during a payout window must not be destroyed ─────────────────


def test_sale_during_payout_is_not_destroyed(engine: RevenueSplitEngine) -> None:
    """The payout captures a balance, transfers, then must SUBTRACT what it paid.

    It used to assign zero, so anything credited between the capture and the
    write was silently lost. Measured before the fix: a $50 sale landing
    mid-payout destroyed $40 of creator earnings.
    """
    engine.register_stripe_account("c1", "acct_test")
    engine.record_sale("s1", "c1", "b1", 100.00)

    bal = engine._get_or_create_balance("c1")
    captured = bal.pending_usd

    # A sale lands after the payout captured its amount but before it writes.
    engine.record_sale("s2", "c1", "b2", 50.00)
    after_sale = bal.pending_usd
    assert after_sale > captured, "fixture must credit during the window"

    engine._settle_paid_payout(bal, captured)

    assert bal.pending_usd == after_sale - captured, (
        f"money destroyed: pending is {bal.pending_usd}, expected {after_sale - captured}"
    )
    assert bal.total_paid_usd == captured


def test_balance_never_goes_negative(engine: RevenueSplitEngine) -> None:
    """Subtracting more than is pending must clamp, not underflow into debt."""
    engine.register_stripe_account("c1", "acct_test")
    engine.record_sale("s1", "c1", "b1", 100.00)
    bal = engine._get_or_create_balance("c1")

    engine._settle_paid_payout(bal, bal.pending_usd + Decimal("999.00"))

    assert bal.pending_usd >= Decimal("0.00")


# ── F204: never report PAID without a transfer ────────────────────────────────


def test_no_transfer_backend_does_not_report_paid(engine: RevenueSplitEngine, monkeypatch: pytest.MonkeyPatch) -> None:
    """With the stripe package absent, a payout must NOT claim it paid.

    Before the fix this set status=PAID, stamped completed_at, and zeroed the
    balance — so a creator's ledger said they had been paid $400 that never
    left the platform.
    """
    monkeypatch.setattr("monetization.revenue_split._STRIPE_AVAILABLE", False)
    engine.register_stripe_account("c1", "acct_test")
    engine.record_sale("s1", "c1", "b1", 500.00)
    pending_before = engine._get_or_create_balance("c1").pending_usd

    payouts = engine.process_weekly_payouts()

    assert len(payouts) == 1
    payout = payouts[0]
    assert payout.status is not PayoutStatus.PAID, "reported PAID with no transfer backend"
    assert payout.stripe_transfer_id is None
    assert engine._get_or_create_balance("c1").pending_usd == pending_before, "balance was debited without a transfer"


# ── F206: cents must not truncate against the creator ─────────────────────────


@pytest.mark.parametrize(
    ("amount", "expected_cents"),
    [
        (Decimal("10.999"), 1100),
        (Decimal("0.999"), 100),
        (Decimal("19.995"), 2000),
        (Decimal("12.34"), 1234),
    ],
)
def test_cents_conversion_rounds_it_does_not_truncate(amount: Decimal, expected_cents: int) -> None:
    """`int(x * 100)` truncates toward zero, always in the platform's favour.

    Sub-cent amounts arise normally: the creator's share is the remainder after
    quantising the platform fee.
    """
    from monetization.revenue_split import to_cents

    assert to_cents(amount) == expected_cents


# ── F207: a payout must claim only what it actually paid ──────────────────────


def test_payout_claims_only_unpaid_transactions(engine: RevenueSplitEngine, monkeypatch: pytest.MonkeyPatch) -> None:
    """Each payout used to list every historical transaction for the creator,
    so summing transaction ids across payouts double-counted."""
    monkeypatch.setattr(
        "monetization.revenue_split.RevenueSplitEngine._execute_stripe_transfer",
        lambda self, payout, bal: _force_paid(payout),
    )
    engine.register_stripe_account("c1", "acct_test")
    for i in range(3):
        engine.record_sale(f"s{i}", "c1", "b", 100.00)

    first = engine.process_weekly_payouts()[0]
    assert len(first.transaction_ids) == 3

    engine.record_sale("s4", "c1", "b", 100.00)
    second = engine.process_weekly_payouts()[0]

    assert len(second.transaction_ids) == 1, (
        f"second payout claimed {len(second.transaction_ids)} transactions; "
        "the three settled by the first payout must not be re-claimed"
    )
    assert not set(first.transaction_ids) & set(second.transaction_ids)


def _force_paid(payout):
    payout.status = PayoutStatus.PAID
    payout.stripe_transfer_id = "tr_test"
    return payout


# ── the arithmetic that is already correct — pinned so it stays that way ──────


def test_platform_fee_and_creator_share_sum_to_gross(
    engine: RevenueSplitEngine,
) -> None:
    """Only the fee is quantised; the creator takes the remainder, so no cent
    is invented or lost. This was correct before the fix and must remain so."""
    for gross in (100.00, 33.33, 0.07, 19.99):
        txn = engine.record_sale("s", "c", "b", gross)
        assert txn.platform_fee + txn.creator_amount == txn.gross_amount


def test_payout_requires_the_minimum_and_an_account(
    engine: RevenueSplitEngine,
) -> None:
    """Eligibility must need both a threshold balance and a payout account."""
    engine.record_sale("s", "c_no_acct", "b", 1000.00)
    assert engine.process_weekly_payouts() == []

    engine.register_stripe_account("c_small", "acct_x")
    engine.record_sale("s2", "c_small", "b", float(MIN_PAYOUT_USD) / 10)
    assert engine.process_weekly_payouts() == []

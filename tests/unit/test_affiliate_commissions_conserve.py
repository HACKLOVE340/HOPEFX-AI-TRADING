# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""Affiliate commissions must be conserved: paid out, or still owed. Never neither.

F31/F32. `monetization/affiliate.py` carries the two defects that were fixed in
`monetization/revenue_split.py` as F203 and F208, one module over and 750 lines
long. It is not dormant code: `api/billing.py` imports the module-level
`affiliate_manager` singleton and `celery_app.py` constructs its own.

Three ways money leaves the ledger without being paid.

**1. `request_withdrawal` over-marks, with no concurrency required.** It walks
converted referrals marking them PAID until the running total covers the
request, but it tests the total *before* adding each one, so the referral that
crosses the line is marked in full:

    requested = 100.00, referrals of 60.00 and 60.00
      ref1: covered 0 < 100  -> covered = 60,  mark_paid
      ref2: covered 60 < 100 -> covered = 120, mark_paid
      payout amount = 100.00, commissions marked paid = 120.00

Reproduced against the real manager before this test was written: pending
120.00, withdrawn 100.00, pending afterwards 0.00 — **20.00 destroyed**.

**2. A conversion landing mid-payout is marked paid without being paid.**
`request_payout` sums the converted referrals, then re-reads them to mark them
paid. A conversion between the two sees the mark and not the sum. This is
F203's shape exactly: the sale was recorded, and then erased.

**3. Two concurrent payout requests pay the same referrals twice.** Both read
the same converted set, both clear the threshold, both create a full-value
payout. Nothing serialises the read-modify-write — there is no lock anywhere in
the module.

Each test states the invariant rather than the mechanism: **what was owed
before equals what was paid plus what is still owed.**
"""

from __future__ import annotations

import threading
from decimal import Decimal

import pytest

from monetization.affiliate import Affiliate, AffiliateLevel, AffiliateManager, ReferralStatus
from monetization.subscription import SubscriptionTier

pytestmark = pytest.mark.unit


def _manager_with_commissions(*amounts: str) -> tuple[AffiliateManager, str]:
    """An approved affiliate holding one converted referral per amount."""
    m = AffiliateManager()
    aff = m.create_affiliate(user_id="affiliate-user")
    m.approve_affiliate(aff.affiliate_id)
    rate = aff.get_commission_rate()
    for i, amount in enumerate(amounts):
        uid = f"referred-{i}"
        m.create_referral(aff.code, uid)
        # Work backwards from the commission we want, so the arithmetic in the
        # test states the commission rather than a subscription price.
        m.convert_referral(uid, SubscriptionTier.PROFESSIONAL, Decimal(amount) / rate)
    return m, aff.affiliate_id


def _owed(m: AffiliateManager, affiliate_id: str) -> Decimal:
    return m._calculate_pending_commission(affiliate_id)


def _paid_out(m: AffiliateManager, affiliate_id: str) -> Decimal:
    return sum(
        (p.amount for p in m.get_affiliate_payouts(affiliate_id)),
        Decimal("0.00"),
    )


def test_a_withdrawal_does_not_destroy_the_remainder():
    """The referral that crosses the requested amount must not be fully consumed.

    Deterministic — this needs no threads and no unusual input. Two ordinary
    60.00 commissions and a 100.00 withdrawal lose 20.00.
    """
    m, aff_id = _manager_with_commissions("60.00", "60.00")
    owed_before = _owed(m, aff_id)
    assert owed_before == Decimal("120.00")

    payout = m.request_withdrawal(aff_id, 100.0)

    assert payout.amount == Decimal("100.00")
    assert _owed(m, aff_id) + payout.amount == owed_before, (
        f"commission destroyed: {owed_before} owed, {payout.amount} withdrawn, {_owed(m, aff_id)} still owed"
    )


def test_a_withdrawal_that_exactly_covers_leaves_nothing_owed():
    """The boundary the fix must not overshoot in the other direction.

    A fix that stops one referral short would leave the affiliate owed money it
    has already been paid, which is the same defect with the sign flipped.
    """
    m, aff_id = _manager_with_commissions("60.00", "40.00")
    payout = m.request_withdrawal(aff_id, 100.0)

    assert payout.amount == Decimal("100.00")
    assert _owed(m, aff_id) == Decimal("0.00")


def test_a_conversion_during_a_payout_is_not_marked_paid_without_being_paid():
    """F203's shape: a sale recorded while a payout is running, then erased.

    `request_payout` totalled the converted referrals and then re-read the
    ledger to mark them paid. A conversion landing between the two passes was
    marked PAID and had never been in the total, so the affiliate lost it
    permanently.

    The conversion is driven from another thread at the moment the payout is
    inside its read-modify-write, joined only after the payout returns — the
    same shape as the concurrent-request test, and for the same reason: joining
    inside the critical section would deadlock once a lock exists rather than
    exercise it.
    """
    m, aff_id = _manager_with_commissions("150.00")
    aff = m.get_affiliate(aff_id)
    rate = aff.get_commission_rate()

    # A referral standing ready to convert the instant the payout starts.
    m.create_referral(aff.code, "late-referral")

    fired: list[object] = []
    late: list[threading.Thread] = []
    errors: list[BaseException] = []
    original = m.get_affiliate_referrals

    def _reading_the_ledger(*args, **kwargs):
        result = original(*args, **kwargs)
        if not fired:
            fired.append(None)

            def _convert() -> None:
                try:
                    m.convert_referral(
                        "late-referral",
                        SubscriptionTier.PROFESSIONAL,
                        Decimal("70.00") / rate,
                    )
                except BaseException as exc:  # reported below, never swallowed
                    errors.append(exc)

            t = threading.Thread(target=_convert)
            late.append(t)
            t.start()
            t.join(timeout=0.5)
        return result

    m.get_affiliate_referrals = _reading_the_ledger
    try:
        payout = m.request_payout(aff_id, "bank_transfer")
    finally:
        m.get_affiliate_referrals = original

    for t in late:
        t.join(timeout=10)
        assert not t.is_alive(), "the competing conversion never completed"
    assert not errors, errors
    assert payout is not None

    earned = sum((r.commission_amount or Decimal("0.00")) for r in m.get_affiliate_referrals(aff_id))
    assert _paid_out(m, aff_id) + _owed(m, aff_id) == earned, (
        f"a conversion was settled without being paid: {_paid_out(m, aff_id)} paid, "
        f"{_owed(m, aff_id)} still owed, {earned} earned"
    )


def test_concurrent_payout_requests_do_not_pay_the_same_commissions_twice():
    """Two callers must not both be paid for the same referrals.

    Deterministic by construction. Two plain threads racing this passed, because
    the GIL happens to switch outside the window — and a concurrency test that
    has never failed proves nothing about the lock it is supposed to be
    guarding. So the second request is driven from inside the first one's
    read-modify-write, at the exact moment the sum has been taken and the
    referrals have not yet been marked: the interleaving the missing lock
    permits, rather than the one the scheduler happened to produce.

    With a lock the re-entrant call blocks or observes a consistent ledger; the
    invariant asserted is the same either way.
    """
    m, aff_id = _manager_with_commissions("150.00")
    owed_before = _owed(m, aff_id)

    second: list[object] = []
    competitor: list[threading.Thread] = []
    errors: list[BaseException] = []
    original_sum = m._calculate_pending_commission

    def _sum_then_race(affiliate_id: str) -> Decimal:
        total = original_sum(affiliate_id)
        if not second:
            second.append(None)  # re-entrancy guard: only race once

            def _competitor() -> None:
                try:
                    m.request_payout(aff_id, "bank_transfer")
                except BaseException as exc:  # reported below, never swallowed
                    errors.append(exc)

            t = threading.Thread(target=_competitor)
            competitor.append(t)
            t.start()
            # Give it long enough to get in if nothing is stopping it. Joined
            # after the outer request returns, NOT here: once a lock exists the
            # competitor blocks until then, and joining inside the critical
            # section would deadlock this test rather than exercise the fix.
            t.join(timeout=0.5)
        return total

    m._calculate_pending_commission = _sum_then_race
    try:
        m.request_payout(aff_id, "bank_transfer")
    finally:
        m._calculate_pending_commission = original_sum

    for t in competitor:
        t.join(timeout=10)
        assert not t.is_alive(), "the competing request never completed"

    assert not errors, errors
    assert _paid_out(m, aff_id) + _owed(m, aff_id) == owed_before, (
        f"the same commissions were paid more than once: {_paid_out(m, aff_id)} paid "
        f"and {_owed(m, aff_id)} still owed against {owed_before} earned"
    )


def test_a_payout_request_below_the_minimum_changes_nothing():
    """A refusal must not consume the referrals it refused to pay for."""
    m, aff_id = _manager_with_commissions("10.00")

    assert m.request_payout(aff_id, "bank_transfer") is None
    assert _owed(m, aff_id) == Decimal("10.00")
    assert all(r.status is ReferralStatus.CONVERTED for r in m.get_affiliate_referrals(aff_id))


# ── The payout lifecycle ──────────────────────────────────────────────────────
#
# Found while raising this module past the 80% coverage gate: the whole payout
# lifecycle — process, complete, fail — was uncovered, and the failure path
# destroys the commission outright.


def test_a_failed_payout_returns_the_commission():
    """A bank rejection must not erase what the affiliate earned.

    `request_payout` settles the referrals when the payout is *requested*.
    `fail_payout` then set `status = FAILED` and stopped, so the money was
    neither paid nor owed. Reproduced before the fix: 150.00 earned, payout
    failed, 0.00 still owed — **150.00 destroyed by a bank rejection**.

    This is F204's shape in the other direction. There, a status said money had
    moved when it had not; here, a status says the attempt failed while the
    ledger still records it as paid.
    """
    m, aff_id = _manager_with_commissions("150.00")
    owed_before = _owed(m, aff_id)

    payout = m.request_payout(aff_id, "bank_transfer")
    assert payout is not None
    m.process_payout(payout.payout_id, "txn-1")
    m.fail_payout(payout.payout_id, "bank rejected the transfer")

    assert _owed(m, aff_id) == owed_before, (
        f"a failed payout destroyed the commission: {owed_before} earned, {_owed(m, aff_id)} still owed"
    )


def test_a_failed_withdrawal_returns_only_what_it_had_taken():
    """A partial withdrawal that fails must restore exactly its own share.

    The reversal has to know what this payout settled, not re-settle whatever
    happens to be outstanding now — otherwise a failure credits back more than
    was taken and creates money.
    """
    m, aff_id = _manager_with_commissions("60.00", "60.00")
    withdrawal = m.request_withdrawal(aff_id, 100.0)
    assert _owed(m, aff_id) == Decimal("20.00")

    m.fail_payout(withdrawal.payout_id, "card declined")

    assert _owed(m, aff_id) == Decimal("120.00")


def test_failing_a_payout_twice_does_not_credit_it_twice():
    """Reversal must be idempotent; a retried failure notice is not new money."""
    m, aff_id = _manager_with_commissions("150.00")
    payout = m.request_payout(aff_id, "bank_transfer")

    m.fail_payout(payout.payout_id, "bank rejected")
    m.fail_payout(payout.payout_id, "bank rejected (duplicate webhook)")

    assert _owed(m, aff_id) == Decimal("150.00")


def test_a_completed_payout_keeps_the_commission_settled():
    """The other side of the same coin: success must not give the money back."""
    m, aff_id = _manager_with_commissions("150.00")
    payout = m.request_payout(aff_id, "bank_transfer")

    m.process_payout(payout.payout_id, "txn-1")
    assert m.complete_payout(payout.payout_id) is True

    assert _owed(m, aff_id) == Decimal("0.00")
    assert _paid_out(m, aff_id) == Decimal("150.00")


def test_the_lifecycle_refuses_an_unknown_payout():
    """Fail closed on an id nobody issued, rather than reporting success."""
    m, _aff_id = _manager_with_commissions("150.00")

    assert m.process_payout("PAY-DOES-NOT-EXIST", "txn-1") is False
    assert m.complete_payout("PAY-DOES-NOT-EXIST") is False
    assert m.fail_payout("PAY-DOES-NOT-EXIST", "reason") is False


# ── The reporting surfaces ────────────────────────────────────────────────────
#
# `api/billing.py` and `api/monetization.py` serve these to affiliates as
# statements of what they are owed. They were entirely uncovered.


def test_metrics_report_what_was_paid_not_what_reached_a_status():
    """`paid_commissions` must total money, not count referrals by status.

    Once a withdrawal can settle part of a referral, "paid" stops being a flag.
    Totalling the full commission of every referral whose status reached PAID
    under-reports a part-settled one as zero and over-reports a fully-settled
    one that had been part-paid earlier.
    """
    m, aff_id = _manager_with_commissions("60.00", "60.00")
    m.request_withdrawal(aff_id, 100.0)

    metrics = m.get_affiliate_metrics(aff_id)

    assert metrics is not None
    assert metrics.paid_commissions == Decimal("100.00")
    assert metrics.pending_commissions == Decimal("20.00")
    assert metrics.paid_commissions + metrics.pending_commissions == Decimal("120.00")
    assert metrics.converted_referrals == 2


def test_metrics_are_absent_for_an_unknown_affiliate():
    m, _ = _manager_with_commissions("60.00")
    assert m.get_affiliate_metrics("AFF-NOT-A-REAL-ID") is None


def test_the_commission_listing_shows_paid_and_outstanding_separately():
    """An affiliate reading a statement must be able to see what is still owed."""
    m, aff_id = _manager_with_commissions("60.00", "60.00")
    m.request_withdrawal(aff_id, 100.0)

    rows = m.get_commissions(aff_id)

    assert len(rows) == 2
    assert sum(r["commission_paid"] for r in rows) == pytest.approx(100.00, abs=0.001)
    assert sum(r["commission_outstanding"] for r in rows) == pytest.approx(20.00, abs=0.001)


def test_a_level_upgrade_raises_the_commission_rate():
    """Tier thresholds are a business rule; this pins the mechanism around them."""
    m, aff_id = _manager_with_commissions()
    aff = m.get_affiliate(aff_id)
    assert aff.get_commission_rate() == Decimal("0.10")

    aff.total_referrals = 10
    aff.total_revenue = Decimal("18000")
    upgraded = aff.check_level_upgrade()

    assert upgraded is not None
    assert aff.upgrade_level(upgraded) is True
    assert aff.get_commission_rate() > Decimal("0.10")


def test_a_level_is_never_downgraded_by_upgrade_level():
    """`upgrade_level` must refuse to move backwards, whatever it is handed."""
    from monetization.affiliate import AffiliateLevel

    m, aff_id = _manager_with_commissions()
    aff = m.get_affiliate(aff_id)
    aff.level = AffiliateLevel.GOLD

    assert aff.upgrade_level(AffiliateLevel.BRONZE) is False
    assert aff.level is AffiliateLevel.GOLD


def test_check_level_upgrade_advances_one_tier_per_call():
    """Documenting real behaviour, not endorsing it.

    `check_level_upgrade` returns the FIRST qualifying level above the current
    one, so an affiliate whose numbers already clear a higher tier is granted
    the next one up and stays under-levelled — and therefore under-paid — until
    the following conversion triggers another check. Whether tiers should skip
    is a commercial decision, so this test records the behaviour rather than
    changing it. If the policy changes, this test should fail and be rewritten.
    """
    from monetization.affiliate import AffiliateLevel, LEVEL_REQUIREMENTS

    m, aff_id = _manager_with_commissions()
    aff = m.get_affiliate(aff_id)
    top = list(AffiliateLevel)[-1]
    aff.total_referrals = LEVEL_REQUIREMENTS[top]["referrals"]
    aff.total_revenue = LEVEL_REQUIREMENTS[top]["revenue"]

    granted = aff.check_level_upgrade()

    assert granted is list(AffiliateLevel)[1], (
        "the affiliate qualifies for the top tier and was granted the next one up"
    )


def test_a_suspended_affiliate_cannot_be_paid_out():
    """Suspension must reach the money path, not only the status field."""
    m, aff_id = _manager_with_commissions("150.00")
    assert m.suspend_affiliate(aff_id) is True

    assert m.request_payout(aff_id, "bank_transfer") is None
    with pytest.raises(ValueError, match="not active"):
        m.request_withdrawal(aff_id, 100.0)

    assert _owed(m, aff_id) == Decimal("150.00")


def test_a_withdrawal_beyond_the_balance_is_refused_and_changes_nothing():
    m, aff_id = _manager_with_commissions("150.00")

    with pytest.raises(ValueError, match="exceeds pending commissions"):
        m.request_withdrawal(aff_id, 500.0)

    assert _owed(m, aff_id) == Decimal("150.00")
    assert m.get_affiliate_payouts(aff_id) == []


def test_the_monthly_breakdown_covers_the_requested_span():
    m, aff_id = _manager_with_commissions("150.00")

    rows = m.get_monthly_breakdown(aff_id, months=3)

    assert len(rows) == 3
    assert sum(r["referrals"] for r in rows) >= 1
    assert {"month", "commissions", "referrals"} <= set(rows[0])


def test_programme_stats_count_what_exists():
    m, aff_id = _manager_with_commissions("150.00")
    m.request_payout(aff_id, "bank_transfer")

    stats = m.get_stats()

    assert stats["total_affiliates"] >= 1
    assert stats["total_referrals"] >= 1


# ── AFF-TIER: the tier an affiliate has, versus the one they have earned ──────


def test_a_bronze_affiliate_clearing_platinum_is_offered_only_silver():
    """Today's behaviour, pinned because it costs the affiliate money.

    `check_level_upgrade` walks the levels above the current one and returns the
    FIRST that qualifies. Requirements ascend, so "first qualifying" is the
    LOWEST tier they clear, not the highest: an affiliate whose numbers already
    clear platinum (50 referrals, $100k) is granted silver and paid the 15%
    rate instead of 25% — a 10-point spread on every commission until the next
    conversion triggers another check, which grants gold, and so on.

    Whether tiers should be skippable is a commercial decision and is not made
    here. What this pins is that the decision is visible: if the policy changes,
    this test fails and should be rewritten.
    """
    affiliate = Affiliate(affiliate_id="a1", user_id="u1", code="C1")
    affiliate.total_referrals = 80
    affiliate.total_revenue = Decimal("250000")

    assert affiliate.level is AffiliateLevel.BRONZE
    assert affiliate.check_level_upgrade() is AffiliateLevel.SILVER, (
        "the one-tier-per-call policy changed — revisit AFF-TIER and this test"
    )


def test_the_tier_they_have_earned_is_reported_alongside_the_one_they_get():
    """The half that is not a commercial decision: say what was earned.

    A caller reading `check_level_upgrade` reasonably assumes it returns the
    level the affiliate qualifies for. It returns the next step toward it, and
    nothing in the method's name, signature or return value says so. That is a
    silent under-payment rather than a policy — the policy only becomes a policy
    once both numbers are visible.
    """
    affiliate = Affiliate(affiliate_id="a1", user_id="u1", code="C1")
    affiliate.total_referrals = 80
    affiliate.total_revenue = Decimal("250000")

    assert affiliate.highest_qualifying_level() is AffiliateLevel.PLATINUM
    assert affiliate.check_level_upgrade() is AffiliateLevel.SILVER
    # bronze -> silver -> gold -> platinum: three steps, not the two a first draft
    # expected. The index arithmetic was mine to get wrong, not the module's.
    assert affiliate.tiers_behind() == 3, "bronze to platinum is three tiers of lag"


def test_an_affiliate_at_the_tier_they_earned_is_not_behind():
    """The control. A gap detector that always reports a gap is not one."""
    affiliate = Affiliate(affiliate_id="a2", user_id="u2", code="C2")
    affiliate.total_referrals = 30
    affiliate.total_revenue = Decimal("60000")
    affiliate.level = AffiliateLevel.GOLD

    assert affiliate.highest_qualifying_level() is AffiliateLevel.GOLD
    assert affiliate.tiers_behind() == 0
    assert affiliate.check_level_upgrade() is None


def test_both_requirements_must_be_met_not_either():
    """Revenue without referrals, or referrals without revenue, is not a tier.

    Asserted because `and` becoming `or` here is a one-character change that
    raises every commission rate and would pass every other test in this file.
    """
    revenue_only = Affiliate(affiliate_id="a3", user_id="u3", code="C3")
    revenue_only.total_referrals = 1
    revenue_only.total_revenue = Decimal("999999")
    assert revenue_only.highest_qualifying_level() is AffiliateLevel.BRONZE
    assert revenue_only.check_level_upgrade() is None

    referrals_only = Affiliate(affiliate_id="a4", user_id="u4", code="C4")
    referrals_only.total_referrals = 999
    referrals_only.total_revenue = Decimal("0")
    assert referrals_only.highest_qualifying_level() is AffiliateLevel.BRONZE
    assert referrals_only.check_level_upgrade() is None


def test_a_tier_is_earned_exactly_at_its_threshold_not_above_it():
    """`>=`, asserted at the boundary. Off-by-one here is a tier of commission."""
    at_silver = Affiliate(affiliate_id="a5", user_id="u5", code="C5")
    at_silver.total_referrals = 10
    at_silver.total_revenue = Decimal("18000")
    assert at_silver.highest_qualifying_level() is AffiliateLevel.SILVER

    just_under = Affiliate(affiliate_id="a6", user_id="u6", code="C6")
    just_under.total_referrals = 10
    just_under.total_revenue = Decimal("17999.99")
    assert just_under.highest_qualifying_level() is AffiliateLevel.BRONZE

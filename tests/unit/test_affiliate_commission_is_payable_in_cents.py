"""A commission an affiliate is owed must be an amount that can be paid.

`Referral.convert` computed `subscription_amount * commission_rate` and stored
the raw product. Decimal multiplication keeps every digit, so a 10% commission
on 3,333.33 is 333.3330 — a third of a cent that no bank transfer can move.

Reproduced before the fix, with no concurrency and no database involved::

    commission owed   : 333.3330
    paid              : 333.33      # every cent that *can* be paid
    still outstanding : 0.0030      status: converted
    pending           : 0.0030

That remainder is permanent. It is below `MIN_PAYOUT` (100.00) so no withdrawal
can ever take it, and `outstanding_commission` stays above zero so the referral
never reaches PAID — it sits in the CONVERTED working set for the life of the
account, and every affiliate's dashboard shows a pending balance they cannot
withdraw.

The affiliate ledger tables made the same defect visible from the other side:
the columns are `Numeric(18, 2)`, so storage truncated 333.3330 to 333.33 and
the database disagreed with memory about what was owed.

`monetization/revenue_split.py` already quantizes with ROUND_HALF_UP at the
point money becomes authoritative. This does the same, one module over.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

pytestmark = pytest.mark.unit


def _earned(amount: str) -> tuple:
    from monetization.affiliate import AffiliateManager, SubscriptionTier

    manager = AffiliateManager()
    affiliate = manager.create_affiliate(user_id="aff-cents")
    manager.approve_affiliate(affiliate.affiliate_id)
    manager.create_referral(affiliate.code, "buyer-cents")
    commission = manager.convert_referral("buyer-cents", SubscriptionTier.PROFESSIONAL, Decimal(amount))
    return manager, affiliate, commission


class TestCommissionIsWholeCents:
    @pytest.mark.parametrize(
        "subscription",
        ["3333.33", "333.33", "99.99", "0.01", "1234.56", "19.95"],
    )
    def test_a_commission_never_carries_a_sub_cent_remainder(self, subscription):
        _, _, commission = _earned(subscription)
        assert commission == commission.quantize(Decimal("0.01")), (
            f"commission {commission} on {subscription} carries a fraction of a cent that cannot be paid"
        )

    def test_the_stored_commission_is_whole_cents_too(self):
        """The amount the affiliate is *owed*, not merely the amount returned."""
        manager, affiliate, _ = _earned("3333.33")
        referral = next(iter(manager._referrals.values()))
        assert referral.commission_amount == referral.commission_amount.quantize(Decimal("0.01"))
        assert manager._calculate_pending_commission(affiliate.affiliate_id) == Decimal("333.33")

    def test_rounding_is_half_up_not_bankers(self):
        """`round()` would round 0.005 to the even cent; money rounds half up.

        2.50% of 100.10 is 2.5025 → 2.50; of 100.30 is 2.5075 → 2.51. The case
        that separates the two modes is an exact half, so it is asserted
        directly on the quantization the fix uses.
        """
        from decimal import ROUND_HALF_UP

        assert Decimal("2.505").quantize(Decimal("0.01"), rounding=ROUND_HALF_UP) == Decimal("2.51")
        assert Decimal("2.515").quantize(Decimal("0.01"), rounding=ROUND_HALF_UP) == Decimal("2.52")


class TestNothingIsLeftStranded:
    def test_withdrawing_the_whole_commission_leaves_nothing_outstanding(self):
        """The reproduction above, asserted.

        Before the fix this left 0.0030 outstanding: unwithdrawable, because it
        is below MIN_PAYOUT, and permanent, because the referral never reaches
        PAID while anything is outstanding.
        """
        from monetization.affiliate import ReferralStatus

        manager, affiliate, commission = _earned("3333.33")
        # What a payment processor can actually send: whole cents. Withdrawing
        # the raw 333.3330 would settle the fraction too and hide the defect.
        payable = float(commission.quantize(Decimal("0.01")))
        manager.request_withdrawal(affiliate.affiliate_id, payable)

        referral = next(iter(manager._referrals.values()))
        assert referral.outstanding_commission == Decimal("0.00"), (
            f"{referral.outstanding_commission} left stranded — it can never be withdrawn "
            f"(below MIN_PAYOUT {manager.MIN_PAYOUT}) and blocks the referral from ever being PAID"
        )
        assert referral.status == ReferralStatus.PAID
        assert manager._calculate_pending_commission(affiliate.affiliate_id) == Decimal("0.00")

    def test_the_affiliate_totals_agree_with_the_referrals(self):
        """A summary that cannot be re-derived from the facts is the defect."""
        manager, affiliate, commission = _earned("3333.33")
        from_referrals = sum(
            (r.commission_amount or Decimal("0.00") for r in manager._referrals.values()),
            Decimal("0.00"),
        )
        assert manager.get_affiliate(affiliate.affiliate_id).total_commissions == from_referrals == commission

# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
Affiliate and Referral Program

This module handles:
- Affiliate code generation and management
- Referral tracking
- Commission calculation for affiliates
- Payout management
- Affiliate dashboard data
"""

import logging
import secrets
import string
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

try:
    from enum import StrEnum
except ImportError:
    from enum import Enum

    class StrEnum(str, Enum):  # Python 3.10 compat
        pass


UTC = timezone.utc
from decimal import Decimal
from typing import Any

from .pricing import SubscriptionTier

logger = logging.getLogger(__name__)


class AffiliateStatus(StrEnum):
    """Affiliate status enumeration"""

    PENDING = "pending"
    ACTIVE = "active"
    SUSPENDED = "suspended"
    TERMINATED = "terminated"


class AffiliateLevel(StrEnum):
    """Affiliate tier levels"""

    BRONZE = "bronze"  # 10% commission
    SILVER = "silver"  # 15% commission
    GOLD = "gold"  # 20% commission
    PLATINUM = "platinum"  # 25% commission


class ReferralStatus(StrEnum):
    """Referral status enumeration"""

    PENDING = "pending"
    CONVERTED = "converted"
    PAID = "paid"
    EXPIRED = "expired"


class PayoutStatus(StrEnum):
    """Payout status enumeration"""

    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


# Commission rates by affiliate level
AFFILIATE_COMMISSION_RATES = {
    AffiliateLevel.BRONZE: Decimal("0.10"),  # 10%
    AffiliateLevel.SILVER: Decimal("0.15"),  # 15%
    AffiliateLevel.GOLD: Decimal("0.20"),  # 20%
    AffiliateLevel.PLATINUM: Decimal("0.25"),  # 25%
}

# Requirements to upgrade affiliate level
LEVEL_REQUIREMENTS = {
    AffiliateLevel.BRONZE: {"referrals": 0, "revenue": Decimal(0)},
    AffiliateLevel.SILVER: {"referrals": 10, "revenue": Decimal(18000)},
    AffiliateLevel.GOLD: {"referrals": 25, "revenue": Decimal(50000)},
    AffiliateLevel.PLATINUM: {"referrals": 50, "revenue": Decimal(100000)},
}


@dataclass
class AffiliateMetrics:
    """Affiliate performance metrics"""

    total_referrals: int
    converted_referrals: int
    total_revenue: Decimal
    total_commissions: Decimal
    pending_commissions: Decimal
    paid_commissions: Decimal
    conversion_rate: float
    avg_commission: Decimal


class Affiliate:
    """Affiliate account model"""

    def __init__(
        self,
        affiliate_id: str,
        user_id: str,
        code: str,
        level: AffiliateLevel = AffiliateLevel.BRONZE,
        status: AffiliateStatus = AffiliateStatus.PENDING,
        payment_details: dict[str, Any] | None = None,
    ):
        self.affiliate_id = affiliate_id
        self.user_id = user_id
        self.code = code
        self.level = level
        self.status = status
        self.payment_details = payment_details or {}
        self.created_at = datetime.now(UTC)
        self.approved_at: datetime | None = None
        self.total_referrals = 0
        self.total_revenue = Decimal("0.00")
        self.total_commissions = Decimal("0.00")

    def get_commission_rate(self) -> Decimal:
        """Get commission rate based on level"""
        return AFFILIATE_COMMISSION_RATES.get(self.level, Decimal("0.10"))

    def is_active(self) -> bool:
        """Check if affiliate is active"""
        return self.status == AffiliateStatus.ACTIVE

    def approve(self) -> None:
        """Approve affiliate application"""
        self.status = AffiliateStatus.ACTIVE
        self.approved_at = datetime.now(UTC)
        logger.info("Affiliate %s approved", self.affiliate_id)

    def suspend(self) -> None:
        """Suspend affiliate account"""
        self.status = AffiliateStatus.SUSPENDED
        logger.info("Affiliate %s suspended", self.affiliate_id)

    def highest_qualifying_level(self) -> AffiliateLevel:
        """The best tier this affiliate's numbers actually earn, today.

        Distinct from :meth:`check_level_upgrade`, which grants one step at a
        time — see that method for why both exist. Both thresholds must be met:
        revenue without referrals, or referrals without revenue, earns nothing.
        """
        earned = AffiliateLevel.BRONZE
        for level in AffiliateLevel:
            req = LEVEL_REQUIREMENTS[level]
            if self.total_referrals >= req["referrals"] and self.total_revenue >= req["revenue"]:
                earned = level
        return earned

    def tiers_behind(self) -> int:
        """How many tiers below their earned level this affiliate is being paid.

        Zero is the normal state. A positive number is money the affiliate has
        earned and is not receiving, and it is reported rather than inferred so
        the one-step policy below is a visible choice instead of a silent one.
        """
        levels = list(AffiliateLevel)
        return max(0, levels.index(self.highest_qualifying_level()) - levels.index(self.level))

    def check_level_upgrade(self) -> AffiliateLevel | None:
        """The next tier to grant — **one step**, not the tier they have earned.

        Returns the FIRST level above the current one whose requirements are
        met. Requirements ascend, so "first qualifying" is the LOWEST tier the
        affiliate clears, not the highest: someone whose numbers already clear
        platinum is granted silver and paid 15% instead of 25% until the next
        conversion triggers another check, which grants gold, and so on. A
        ten-point spread on every commission in between.

        **Whether tiers should be skippable is a commercial decision, and this
        method does not make it.** What changed is that it no longer makes it
        silently: the name and signature gave a caller no way to tell this from
        "the level they qualify for", so under-payment read as policy without
        anyone choosing it. :meth:`highest_qualifying_level` and
        :meth:`tiers_behind` make the gap legible, and
        `tests/unit/test_affiliate_commissions_conserve.py` pins today's
        behaviour so a change to it has to be deliberate (AFF-TIER).
        """
        current_level_idx = list(AffiliateLevel).index(self.level)

        for level in list(AffiliateLevel)[current_level_idx + 1 :]:
            req = LEVEL_REQUIREMENTS[level]
            if self.total_referrals >= req["referrals"] and self.total_revenue >= req["revenue"]:
                return level
        return None

    def upgrade_level(self, new_level: AffiliateLevel) -> bool:
        """Upgrade affiliate level"""
        if list(AffiliateLevel).index(new_level) > list(AffiliateLevel).index(self.level):
            old_level = self.level
            self.level = new_level
            logger.info("Affiliate %s upgraded from %s to %s", self.affiliate_id, old_level.value, new_level.value)

            return True
        return False

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary"""
        return {
            "affiliate_id": self.affiliate_id,
            "user_id": self.user_id,
            "code": self.code,
            "level": self.level.value,
            "status": self.status.value,
            "commission_rate": float(self.get_commission_rate()),
            "total_referrals": self.total_referrals,
            "total_revenue": float(self.total_revenue),
            "total_commissions": float(self.total_commissions),
            "created_at": self.created_at.isoformat(),
            "approved_at": self.approved_at.isoformat() if self.approved_at else None,
        }


class Referral:
    """Referral tracking model"""

    def __init__(
        self,
        referral_id: str,
        affiliate_id: str,
        referred_user_id: str,
        status: ReferralStatus = ReferralStatus.PENDING,
        tier: SubscriptionTier | None = None,
    ):
        self.referral_id = referral_id
        self.affiliate_id = affiliate_id
        self.referred_user_id = referred_user_id
        self.status = status
        self.tier = tier
        self.created_at = datetime.now(UTC)
        self.converted_at: datetime | None = None
        self.expires_at = datetime.now(UTC) + timedelta(days=90)  # 90-day cookie
        self.subscription_amount: Decimal | None = None
        self.commission_amount: Decimal | None = None
        #: How much of ``commission_amount`` has actually been paid out. A
        #: withdrawal may cover part of a referral, so "paid" is an amount, not
        #: a flag. It was a flag, and ``request_withdrawal`` therefore marked the
        #: referral that crossed the requested total as fully paid: two 60.00
        #: commissions against a 100.00 withdrawal settled 120.00 and paid 100.00
        #: (F31/F32, reproduced at 20.00 destroyed).
        self.commission_paid: Decimal = Decimal("0.00")

    def is_expired(self) -> bool:
        """Check if referral tracking has expired"""
        return datetime.now(UTC) > self.expires_at

    def convert(
        self,
        tier: SubscriptionTier,
        subscription_amount: Decimal,
        commission_rate: Decimal,
    ) -> Decimal:
        """Mark referral as converted and calculate commission"""
        self.status = ReferralStatus.CONVERTED
        self.converted_at = datetime.now(UTC)
        self.tier = tier
        self.subscription_amount = subscription_amount
        self.commission_amount = subscription_amount * commission_rate

        logger.info(
            "Referral %s converted: $%s -> $%s commission",
            self.referral_id,
            subscription_amount,
            self.commission_amount,
        )
        return self.commission_amount

    @property
    def outstanding_commission(self) -> Decimal:
        """Commission earned and not yet paid out."""
        return (self.commission_amount or Decimal("0.00")) - self.commission_paid

    def settle(self, amount: Decimal) -> Decimal:
        """Record *amount* as paid against this referral; return what was taken.

        Never settles more than is outstanding, so a caller that over-asks gets
        a short answer rather than the ledger absorbing the difference.
        """
        taken = min(amount, self.outstanding_commission)
        if taken <= Decimal("0.00"):
            return Decimal("0.00")
        self.commission_paid += taken
        if self.outstanding_commission <= Decimal("0.00"):
            self.status = ReferralStatus.PAID
        return taken

    def unsettle(self, amount: Decimal) -> Decimal:
        """Give *amount* back to the outstanding balance; return what was returned.

        Never returns more than was settled, so a duplicated failure notice
        cannot credit the affiliate twice.
        """
        given_back = min(amount, self.commission_paid)
        if given_back <= Decimal("0.00"):
            return Decimal("0.00")
        self.commission_paid -= given_back
        if self.outstanding_commission > Decimal("0.00"):
            self.status = ReferralStatus.CONVERTED
        return given_back

    def mark_paid(self) -> None:
        """Settle the whole outstanding commission and mark the referral paid."""
        self.settle(self.outstanding_commission)
        self.status = ReferralStatus.PAID

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary"""
        return {
            "referral_id": self.referral_id,
            "affiliate_id": self.affiliate_id,
            "referred_user_id": self.referred_user_id,
            "status": self.status.value,
            "tier": self.tier.value if self.tier else None,
            "subscription_amount": float(self.subscription_amount) if self.subscription_amount else None,
            "commission_amount": float(self.commission_amount) if self.commission_amount else None,
            "commission_paid": float(self.commission_paid),
            "commission_outstanding": float(self.outstanding_commission),
            "created_at": self.created_at.isoformat(),
            "converted_at": self.converted_at.isoformat() if self.converted_at else None,
            "expires_at": self.expires_at.isoformat(),
        }


class Payout:
    """Affiliate payout model"""

    def __init__(
        self,
        payout_id: str,
        affiliate_id: str,
        amount: Decimal,
        payment_method: str,
        status: PayoutStatus = PayoutStatus.PENDING,
    ):
        self.payout_id = payout_id
        self.affiliate_id = affiliate_id
        self.amount = amount
        self.payment_method = payment_method
        self.status = status
        self.created_at = datetime.now(UTC)
        self.processed_at: datetime | None = None
        self.transaction_id: str | None = None
        self.notes: str = ""
        #: (referral_id, amount) for every commission this payout consumed.
        #: Recorded so a failure can return exactly what it took — reversing by
        #: re-reading the ledger would credit back whatever happens to be
        #: outstanding at failure time, which is a different number.
        self.settlements: list[tuple[str, Decimal]] = []
        #: Set once the settlements have been returned, so a duplicated failure
        #: notice is not a second credit.
        self.reversed: bool = False

    def process(self, transaction_id: str) -> None:
        """Process payout"""
        self.status = PayoutStatus.PROCESSING
        self.transaction_id = transaction_id
        logger.info("Payout %s processing: %s", self.payout_id, transaction_id)

    def complete(self) -> None:
        """Mark payout as completed"""
        self.status = PayoutStatus.COMPLETED
        self.processed_at = datetime.now(UTC)
        logger.info("Payout %s completed", self.payout_id)

    def fail(self, reason: str) -> None:
        """Mark payout as failed"""
        self.status = PayoutStatus.FAILED
        self.notes = reason
        logger.error("Payout %s failed: %s", self.payout_id, reason)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary"""
        return {
            "payout_id": self.payout_id,
            "affiliate_id": self.affiliate_id,
            "amount": float(self.amount),
            "payment_method": self.payment_method,
            "status": self.status.value,
            "created_at": self.created_at.isoformat(),
            "processed_at": self.processed_at.isoformat() if self.processed_at else None,
            "transaction_id": self.transaction_id,
            "notes": self.notes,
        }


class AffiliateManager:
    """Manage affiliates, referrals, and payouts"""

    # Minimum payout threshold
    MIN_PAYOUT = Decimal("100.00")

    def __init__(self):
        self._affiliates: dict[str, Affiliate] = {}
        self._referrals: dict[str, Referral] = {}
        self._payouts: dict[str, Payout] = {}
        self._affiliate_codes: dict[str, str] = {}  # code -> affiliate_id
        self._user_affiliates: dict[str, str] = {}  # user_id -> affiliate_id
        # Both payout paths total the outstanding commissions, then walk the
        # referrals settling them. There was no lock anywhere in this module, so
        # that read-modify-write raced two ways: two concurrent requests each
        # saw the full balance and paid it (measured: 300.00 paid against 150.00
        # earned), and a conversion landing between the total and the settlement
        # was marked paid without being in the total — F203's shape, one module
        # over. Re-entrant because request_withdrawal reads through
        # _calculate_pending_commission while already holding it.
        self._lock = threading.RLock()

    def _generate_affiliate_code(self, length: int = 8) -> str:
        """Generate unique affiliate code"""
        chars = string.ascii_uppercase + string.digits
        while True:
            code = "".join(secrets.choice(chars) for _ in range(length))
            if code not in self._affiliate_codes:
                return code

    def create_affiliate(
        self,
        user_id: str,
        payment_details: dict[str, Any] | None = None,
        custom_code: str | None = None,
    ) -> Affiliate:
        """Create a new affiliate account"""
        import uuid

        # Check if user already has affiliate account
        if user_id in self._user_affiliates:
            existing_id = self._user_affiliates[user_id]
            return self._affiliates[existing_id]

        affiliate_id = f"AFF-{uuid.uuid4().hex[:12].upper()}"
        code = custom_code or self._generate_affiliate_code()

        # Validate custom code is unique
        if custom_code and custom_code in self._affiliate_codes:
            raise ValueError(f"Affiliate code '{custom_code}' already exists")

        affiliate = Affiliate(
            affiliate_id=affiliate_id,
            user_id=user_id,
            code=code,
            level=AffiliateLevel.BRONZE,
            status=AffiliateStatus.PENDING,
            payment_details=payment_details,
        )

        self._affiliates[affiliate_id] = affiliate
        self._affiliate_codes[code] = affiliate_id
        self._user_affiliates[user_id] = affiliate_id

        logger.info("Created affiliate %s with code %s", affiliate_id, code)

        return affiliate

    def get_affiliate(self, affiliate_id: str) -> Affiliate | None:
        """Get affiliate by ID"""
        return self._affiliates.get(affiliate_id)

    def get_affiliate_by_code(self, code: str) -> Affiliate | None:
        """Get affiliate by referral code"""
        affiliate_id = self._affiliate_codes.get(code.upper())
        return self._affiliates.get(affiliate_id) if affiliate_id else None

    def get_user_affiliate(self, user_id: str) -> Affiliate | None:
        """Get affiliate account for a user"""
        affiliate_id = self._user_affiliates.get(user_id)
        return self._affiliates.get(affiliate_id) if affiliate_id else None

    def approve_affiliate(self, affiliate_id: str) -> bool:
        """Approve affiliate application"""
        affiliate = self.get_affiliate(affiliate_id)
        if not affiliate:
            return False

        affiliate.approve()
        return True

    def suspend_affiliate(self, affiliate_id: str) -> bool:
        """Suspend affiliate account"""
        affiliate = self.get_affiliate(affiliate_id)
        if not affiliate:
            return False

        affiliate.suspend()
        return True

    def create_referral(self, affiliate_code: str, referred_user_id: str) -> Referral | None:
        """Create a referral tracking record"""
        import uuid

        affiliate = self.get_affiliate_by_code(affiliate_code)
        if not affiliate or not affiliate.is_active():
            logger.warning("Invalid or inactive affiliate code: %s", affiliate_code)

            return None

        # Reject self-referral — an affiliate must not earn commission on their
        # own subscription.
        if affiliate.user_id == referred_user_id:
            logger.warning("Self-referral rejected: affiliate %s == referred user", affiliate.affiliate_id)
            return None

        # Check if user was already referred
        for referral in self._referrals.values():
            if referral.referred_user_id == referred_user_id:
                logger.info("User %s already has referral tracking", referred_user_id)

                return referral

        referral_id = f"REF-{uuid.uuid4().hex[:12].upper()}"
        referral = Referral(
            referral_id=referral_id,
            affiliate_id=affiliate.affiliate_id,
            referred_user_id=referred_user_id,
            status=ReferralStatus.PENDING,
        )

        self._referrals[referral_id] = referral
        logger.info("Created referral %s for affiliate %s", referral_id, affiliate.affiliate_id)

        return referral

    def convert_referral(
        self,
        referred_user_id: str,
        tier: SubscriptionTier,
        subscription_amount: Decimal,
    ) -> Decimal | None:
        """Convert a referral when user subscribes.

        Holds the manager lock: this credits a commission that a payout running
        concurrently is in the middle of totalling and settling. Without it, a
        conversion could be settled by that payout without ever being in its
        total — the sale recorded and then erased.
        """
        with self._lock:
            return self._convert_referral_locked(referred_user_id, tier, subscription_amount)

    def _convert_referral_locked(
        self,
        referred_user_id: str,
        tier: SubscriptionTier,
        subscription_amount: Decimal,
    ) -> Decimal | None:
        # Find active referral for user
        referral = None
        for ref in self._referrals.values():
            if (
                ref.referred_user_id == referred_user_id
                and ref.status == ReferralStatus.PENDING
                and not ref.is_expired()
            ):
                referral = ref
                break

        if not referral:
            logger.info("No active referral found for user %s", referred_user_id)

            return None

        affiliate = self.get_affiliate(referral.affiliate_id)
        if not affiliate or not affiliate.is_active():
            logger.warning("Affiliate %s not active", referral.affiliate_id)

            return None

        # Calculate and apply commission
        commission = referral.convert(
            tier=tier,
            subscription_amount=subscription_amount,
            commission_rate=affiliate.get_commission_rate(),
        )

        # Update affiliate stats
        affiliate.total_referrals += 1
        affiliate.total_revenue += subscription_amount
        affiliate.total_commissions += commission

        # Check for level upgrade
        new_level = affiliate.check_level_upgrade()
        if new_level:
            affiliate.upgrade_level(new_level)

        return commission

    def get_referral(self, referral_id: str) -> Referral | None:
        """Get referral by ID"""
        return self._referrals.get(referral_id)

    def get_affiliate_referrals(self, affiliate_id: str, status: ReferralStatus | None = None) -> list[Referral]:
        """Get all referrals for an affiliate"""
        referrals = [ref for ref in self._referrals.values() if ref.affiliate_id == affiliate_id]
        if status:
            referrals = [ref for ref in referrals if ref.status == status]
        return referrals

    def request_payout(self, affiliate_id: str, payment_method: str) -> Payout | None:
        """Request affiliate payout"""
        import uuid

        # The whole read-modify-write is one critical section. Totalling the
        # commissions and settling them used to be two separate passes over the
        # ledger, so a conversion landing between them was settled without ever
        # being in the total.
        with self._lock:
            affiliate = self.get_affiliate(affiliate_id)
            if not affiliate or not affiliate.is_active():
                return None

            # Snapshot the referrals this payout covers, and total THAT list.
            # Re-reading the ledger to settle is what lost the conversion.
            covered = [
                ref
                for ref in self.get_affiliate_referrals(affiliate_id, ReferralStatus.CONVERTED)
                if ref.outstanding_commission > Decimal("0.00")
            ]
            pending = sum((ref.outstanding_commission for ref in covered), Decimal("0.00"))

            if pending < self.MIN_PAYOUT:
                logger.warning("Payout below minimum: $%s < $%s", pending, self.MIN_PAYOUT)

                return None

            payout_id = f"PAY-{uuid.uuid4().hex[:12].upper()}"
            payout = Payout(
                payout_id=payout_id,
                affiliate_id=affiliate_id,
                amount=pending,
                payment_method=payment_method,
                status=PayoutStatus.PENDING,
            )

            self._payouts[payout_id] = payout

            settled = Decimal("0.00")
            for ref in covered:
                taken = ref.settle(ref.outstanding_commission)
                if taken > Decimal("0.00"):
                    payout.settlements.append((ref.referral_id, taken))
                    settled += taken
            if settled != pending:
                # Cannot happen while the lock is held; asserted rather than
                # assumed, because the failure mode is silent money loss.
                logger.error(
                    "Payout %s settled $%s against a total of $%s — ledger not conserved",
                    payout_id,
                    settled,
                    pending,
                )

            logger.info("Created payout request %s for $%s", payout_id, pending)

            return payout

    def _calculate_pending_commission(self, affiliate_id: str) -> Decimal:
        """Total commission earned by this affiliate and not yet paid out.

        Sums what is *outstanding* rather than the full commission of every
        CONVERTED referral, so a referral that a withdrawal covered part of
        contributes only its remainder.
        """
        with self._lock:
            total = Decimal("0.00")
            for ref in self.get_affiliate_referrals(affiliate_id, ReferralStatus.CONVERTED):
                total += ref.outstanding_commission
            return total

    def process_payout(self, payout_id: str, transaction_id: str) -> bool:
        """Process a payout request"""
        payout = self._payouts.get(payout_id)
        if not payout:
            return False

        payout.process(transaction_id)
        return True

    def complete_payout(self, payout_id: str) -> bool:
        """Mark payout as completed"""
        payout = self._payouts.get(payout_id)
        if not payout:
            return False

        payout.complete()
        return True

    def fail_payout(self, payout_id: str, reason: str) -> bool:
        """Mark a payout failed and return the commissions it had consumed.

        The referrals are settled when the payout is *requested*, so marking it
        failed and stopping left the money neither paid nor owed. Measured
        before this returned anything: 150.00 earned, the payout failed, 0.00
        still owed — a bank rejection erased the affiliate's whole commission.

        Reversal uses the amounts this payout recorded, not whatever is
        outstanding now, and runs once: a duplicated failure notice is not a
        second credit.
        """
        with self._lock:
            payout = self._payouts.get(payout_id)
            if not payout:
                return False

            payout.fail(reason)

            if payout.reversed:
                return True
            payout.reversed = True

            returned = Decimal("0.00")
            for referral_id, amount in payout.settlements:
                ref = self._referrals.get(referral_id)
                if ref is None:
                    logger.error(
                        "Payout %s settled referral %s, which no longer exists — $%s cannot be returned",
                        payout_id,
                        referral_id,
                        amount,
                    )
                    continue
                returned += ref.unsettle(amount)

            if returned:
                logger.info(
                    "Payout %s failed (%s) — returned $%s to outstanding commissions",
                    payout_id,
                    reason,
                    returned,
                )
            return True

    def get_affiliate_metrics(self, affiliate_id: str) -> AffiliateMetrics | None:
        """Get comprehensive affiliate metrics"""
        affiliate = self.get_affiliate(affiliate_id)
        if not affiliate:
            return None

        referrals = self.get_affiliate_referrals(affiliate_id)
        converted = [r for r in referrals if r.status in [ReferralStatus.CONVERTED, ReferralStatus.PAID]]

        pending_commission = self._calculate_pending_commission(affiliate_id)
        # Sum what was actually paid, not the full commission of every referral
        # whose status reached PAID. Since a withdrawal may settle part of a
        # referral, "paid" is an amount and the status is a consequence of it —
        # totalling by status under-reported a part-settled referral as zero and
        # over-reported a fully-settled one that had been part-paid earlier.
        paid_commission = sum((ref.commission_paid for ref in referrals), Decimal("0.00"))

        conversion_rate = len(converted) / len(referrals) * 100 if referrals else 0.0

        avg_commission = affiliate.total_commissions / len(converted) if converted else Decimal(0)

        return AffiliateMetrics(
            total_referrals=len(referrals),
            converted_referrals=len(converted),
            total_revenue=affiliate.total_revenue,
            total_commissions=affiliate.total_commissions,
            pending_commissions=pending_commission,
            paid_commissions=paid_commission,
            conversion_rate=conversion_rate,
            avg_commission=avg_commission,
        )

    def get_affiliate_payouts(self, affiliate_id: str, status: PayoutStatus | None = None) -> list[Payout]:
        """Get all payouts for an affiliate"""
        payouts = [p for p in self._payouts.values() if p.affiliate_id == affiliate_id]
        if status:
            payouts = [p for p in payouts if p.status == status]
        return payouts

    def get_all_affiliates(self, status: AffiliateStatus | None = None) -> list[Affiliate]:
        """Get all affiliates"""
        affiliates = list(self._affiliates.values())
        if status:
            affiliates = [a for a in affiliates if a.status == status]
        return affiliates

    def get_commissions(self, affiliate_id: str) -> list[dict[str, Any]]:
        """Return all commission records (converted + paid referrals) for an affiliate."""
        referrals = self.get_affiliate_referrals(affiliate_id)
        result = []
        for ref in referrals:
            if ref.status in (ReferralStatus.CONVERTED, ReferralStatus.PAID) and ref.commission_amount is not None:
                result.append(
                    {
                        "referral_id": ref.referral_id,
                        "affiliate_id": ref.affiliate_id,
                        "referred_user_id": ref.referred_user_id,
                        "commission_amount": float(ref.commission_amount),
                        "commission_paid": float(ref.commission_paid),
                        "commission_outstanding": float(ref.outstanding_commission),
                        "subscription_amount": float(ref.subscription_amount) if ref.subscription_amount else None,
                        "tier": ref.tier.value if ref.tier else None,
                        "status": ref.status.value,
                        "converted_at": ref.converted_at.isoformat() if ref.converted_at else None,
                    }
                )
        return result

    def request_withdrawal(self, affiliate_id: str, amount: float) -> Payout:
        """Request a commission withdrawal for a specific amount.

        Raises ValueError if the affiliate is not found/active or the amount
        exceeds available pending commissions.
        """
        import uuid

        with self._lock:
            affiliate = self.get_affiliate(affiliate_id)
            if not affiliate:
                raise ValueError(f"Affiliate {affiliate_id} not found")
            if not affiliate.is_active():
                raise ValueError(f"Affiliate {affiliate_id} is not active")

            # `amount` arrives as a float from api/monetization.py. Decimal(str(x))
            # rather than Decimal(x), which would inherit the binary error verbatim.
            requested = Decimal(str(amount))
            pending = self._calculate_pending_commission(affiliate_id)
            if requested > pending:
                raise ValueError(f"Requested withdrawal ${requested} exceeds pending commissions ${pending}")
            if requested < self.MIN_PAYOUT:
                raise ValueError(f"Withdrawal amount ${requested} is below minimum ${self.MIN_PAYOUT}")

            payment_method = affiliate.payment_details.get("method", "bank_transfer")
            payout_id = f"WD-{uuid.uuid4().hex[:12].upper()}"
            payout = Payout(
                payout_id=payout_id,
                affiliate_id=affiliate_id,
                amount=requested,
                payment_method=payment_method,
                status=PayoutStatus.PENDING,
            )
            payout.withdrawal_id = payout_id  # type: ignore[attr-defined]
            self._payouts[payout_id] = payout

            # Settle exactly the requested amount. This walked the referrals
            # marking each one PAID in full until the running total reached the
            # request, testing the total BEFORE adding the current referral — so
            # the one that crossed the line was consumed whole and its remainder
            # ceased to exist. Two 60.00 commissions against a 100.00 withdrawal
            # destroyed 20.00, with no concurrency involved.
            remaining = requested
            for ref in self.get_affiliate_referrals(affiliate_id, ReferralStatus.CONVERTED):
                if remaining <= Decimal("0.00"):
                    break
                taken = ref.settle(remaining)
                if taken > Decimal("0.00"):
                    payout.settlements.append((ref.referral_id, taken))
                    remaining -= taken

            if remaining > Decimal("0.00"):
                logger.error(
                    "Withdrawal %s could only settle $%s of $%s — ledger not conserved",
                    payout_id,
                    requested - remaining,
                    requested,
                )

            logger.info("Withdrawal %s created for affiliate %s: $%s", payout_id, affiliate_id, requested)
            return payout

    def update_payment_method(self, affiliate_id: str, payment_details: dict[str, Any]) -> bool:
        """Update payment/payout details for an affiliate."""
        affiliate = self.get_affiliate(affiliate_id)
        if not affiliate:
            raise ValueError(f"Affiliate {affiliate_id} not found")
        affiliate.payment_details.update(payment_details)
        logger.info("Payment method updated for affiliate %s", affiliate_id)
        return True

    def get_leaderboard(self, limit: int = 10) -> list[dict[str, Any]]:
        """Get top affiliates leaderboard"""
        active = self.get_all_affiliates(AffiliateStatus.ACTIVE)
        sorted_affiliates = sorted(active, key=lambda a: (a.total_revenue, a.total_referrals), reverse=True)

        return [
            {
                "rank": idx + 1,
                "affiliate_id": a.affiliate_id,
                "code": a.code,
                "level": a.level.value,
                "total_referrals": a.total_referrals,
                "total_revenue": float(a.total_revenue),
                "total_commissions": float(a.total_commissions),
            }
            for idx, a in enumerate(sorted_affiliates[:limit])
        ]

    def get_monthly_breakdown(self, affiliate_id: str, months: int = 12) -> list[dict[str, Any]]:
        """Return month-by-month commission and referral counts for the last N months."""
        from collections import defaultdict

        referrals = self.get_affiliate_referrals(affiliate_id)
        buckets: dict[str, dict[str, Any]] = defaultdict(lambda: {"commissions": 0.0, "referrals": 0})
        for ref in referrals:
            month_key = ref.created_at.strftime("%Y-%m")
            buckets[month_key]["referrals"] += 1
            if ref.commission_amount:
                buckets[month_key]["commissions"] += float(ref.commission_amount)
        # Build sorted list for the last N months
        now = datetime.now(UTC)
        result: list[dict[str, Any]] = []
        for i in range(months - 1, -1, -1):
            d = now.replace(day=1) - timedelta(days=i * 30)
            key = d.strftime("%Y-%m")
            label = d.strftime("%b %Y")
            bucket = buckets.get(key, {"commissions": 0.0, "referrals": 0})
            result.append({"month": label, "commissions": bucket["commissions"], "referrals": bucket["referrals"]})
        return result

    def get_stats(self) -> dict[str, Any]:
        """Get overall affiliate program statistics"""
        affiliates = list(self._affiliates.values())
        referrals = list(self._referrals.values())
        payouts = list(self._payouts.values())

        total_revenue = sum(a.total_revenue for a in affiliates)
        total_commissions = sum(a.total_commissions for a in affiliates)
        total_payouts = sum(p.amount for p in payouts if p.status == PayoutStatus.COMPLETED)

        return {
            "total_affiliates": len(affiliates),
            "active_affiliates": len([a for a in affiliates if a.is_active()]),
            "pending_affiliates": len([a for a in affiliates if a.status == AffiliateStatus.PENDING]),
            "total_referrals": len(referrals),
            "converted_referrals": len(
                [r for r in referrals if r.status in [ReferralStatus.CONVERTED, ReferralStatus.PAID]]
            ),
            "total_revenue_generated": float(total_revenue),
            "total_commissions_earned": float(total_commissions),
            "total_payouts_processed": float(total_payouts),
            "level_breakdown": {
                level.value: len([a for a in affiliates if a.level == level]) for level in AffiliateLevel
            },
        }


# Global affiliate manager instance
affiliate_manager = AffiliateManager()

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
import hashlib
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Optional, Dict, List, Any
from enum import Enum
from dataclasses import dataclass

from .pricing import SubscriptionTier, pricing_manager

logger = logging.getLogger(__name__)


class AffiliateStatus(str, Enum):
    """Affiliate status enumeration"""
    PENDING = "pending"
    ACTIVE = "active"
    SUSPENDED = "suspended"
    TERMINATED = "terminated"


class AffiliateLevel(str, Enum):
    """Affiliate tier levels"""
    BRONZE = "bronze"      # 10% commission
    SILVER = "silver"      # 15% commission
    GOLD = "gold"          # 20% commission
    PLATINUM = "platinum"  # 25% commission


class ReferralStatus(str, Enum):
    """Referral status enumeration"""
    PENDING = "pending"
    CONVERTED = "converted"
    PAID = "paid"
    EXPIRED = "expired"


class PayoutStatus(str, Enum):
    """Payout status enumeration"""
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


# Commission rates by affiliate level
AFFILIATE_COMMISSION_RATES = {
    AffiliateLevel.BRONZE: Decimal("0.10"),    # 10%
    AffiliateLevel.SILVER: Decimal("0.15"),    # 15%
    AffiliateLevel.GOLD: Decimal("0.20"),      # 20%
    AffiliateLevel.PLATINUM: Decimal("0.25"),  # 25%
}

# Requirements to upgrade affiliate level
LEVEL_REQUIREMENTS = {
    AffiliateLevel.BRONZE: {'referrals': 0, 'revenue': Decimal("0")},
    AffiliateLevel.SILVER: {'referrals': 10, 'revenue': Decimal("18000")},
    AffiliateLevel.GOLD: {'referrals': 25, 'revenue': Decimal("50000")},
    AffiliateLevel.PLATINUM: {'referrals': 50, 'revenue': Decimal("100000")},
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
        payment_details: Optional[Dict[str, Any]] = None
    ):
        self.affiliate_id = affiliate_id
        self.user_id = user_id
        self.code = code
        self.level = level
        self.status = status
        self.payment_details = payment_details or {}
        self.created_at = datetime.utcnow()
        self.approved_at: Optional[datetime] = None
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
        self.approved_at = datetime.utcnow()
        logger.info(f"Affiliate {self.affiliate_id} approved")

    def suspend(self) -> None:
        """Suspend affiliate account"""
        self.status = AffiliateStatus.SUSPENDED
        logger.info(f"Affiliate {self.affiliate_id} suspended")

    def check_level_upgrade(self) -> Optional[AffiliateLevel]:
        """Check if affiliate qualifies for level upgrade"""
        current_level_idx = list(AffiliateLevel).index(self.level)
        
        for level in list(AffiliateLevel)[current_level_idx + 1:]:
            req = LEVEL_REQUIREMENTS[level]
            if (self.total_referrals >= req['referrals'] and 
                self.total_revenue >= req['revenue']):
                return level
        return None

    def upgrade_level(self, new_level: AffiliateLevel) -> bool:
        """Upgrade affiliate level"""
        if list(AffiliateLevel).index(new_level) > list(AffiliateLevel).index(self.level):
            old_level = self.level
            self.level = new_level
            logger.info(
                f"Affiliate {self.affiliate_id} upgraded from {old_level.value} "
                f"to {new_level.value}"
            )
            return True
        return False

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            'affiliate_id': self.affiliate_id,
            'user_id': self.user_id,
            'code': self.code,
            'level': self.level.value,
            'status': self.status.value,
            'commission_rate': float(self.get_commission_rate()),
            'total_referrals': self.total_referrals,
            'total_revenue': float(self.total_revenue),
            'total_commissions': float(self.total_commissions),
            'created_at': self.created_at.isoformat(),
            'approved_at': self.approved_at.isoformat() if self.approved_at else None
        }


class Referral:
    """Referral tracking model"""

    def __init__(
        self,
        referral_id: str,
        affiliate_id: str,
        referred_user_id: str,
        status: ReferralStatus = ReferralStatus.PENDING,
        tier: Optional[SubscriptionTier] = None
    ):
        self.referral_id = referral_id
        self.affiliate_id = affiliate_id
        self.referred_user_id = referred_user_id
        self.status = status
        self.tier = tier
        self.created_at = datetime.utcnow()
        self.converted_at: Optional[datetime] = None
        self.expires_at = datetime.utcnow() + timedelta(days=90)  # 90-day cookie
        self.subscription_amount: Optional[Decimal] = None
        self.commission_amount: Optional[Decimal] = None

    def is_expired(self) -> bool:
        """Check if referral tracking has expired"""
        return datetime.utcnow() > self.expires_at

    def convert(
        self,
        tier: SubscriptionTier,
        subscription_amount: Decimal,
        commission_rate: Decimal
    ) -> Decimal:
        """Mark referral as converted and calculate commission"""
        self.status = ReferralStatus.CONVERTED
        self.converted_at = datetime.utcnow()
        self.tier = tier
        self.subscription_amount = subscription_amount
        self.commission_amount = subscription_amount * commission_rate
        
        logger.info(
            f"Referral {self.referral_id} converted: ${subscription_amount} -> "
            f"${self.commission_amount} commission"
        )
        return self.commission_amount

    def mark_paid(self) -> None:
        """Mark referral commission as paid"""
        self.status = ReferralStatus.PAID

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            'referral_id': self.referral_id,
            'affiliate_id': self.affiliate_id,
            'referred_user_id': self.referred_user_id,
            'status': self.status.value,
            'tier': self.tier.value if self.tier else None,
            'subscription_amount': float(self.subscription_amount) if self.subscription_amount else None,
            'commission_amount': float(self.commission_amount) if self.commission_amount else None,
            'created_at': self.created_at.isoformat(),
            'converted_at': self.converted_at.isoformat() if self.converted_at else None,
            'expires_at': self.expires_at.isoformat()
        }


class Payout:
    """Affiliate payout model"""

    def __init__(
        self,
        payout_id: str,
        affiliate_id: str,
        amount: Decimal,
        payment_method: str,
        status: PayoutStatus = PayoutStatus.PENDING
    ):
        self.payout_id = payout_id
        self.affiliate_id = affiliate_id
        self.amount = amount
        self.payment_method = payment_method
        self.status = status
        self.created_at = datetime.utcnow()
        self.processed_at: Optional[datetime] = None
        self.transaction_id: Optional[str] = None
        self.notes: str = ""

    def process(self, transaction_id: str) -> None:
        """Process payout"""
        self.status = PayoutStatus.PROCESSING
        self.transaction_id = transaction_id
        logger.info(f"Payout {self.payout_id} processing: {transaction_id}")

    def complete(self) -> None:
        """Mark payout as completed"""
        self.status = PayoutStatus.COMPLETED
        self.processed_at = datetime.utcnow()
        logger.info(f"Payout {self.payout_id} completed")

    def fail(self, reason: str) -> None:
        """Mark payout as failed"""
        self.status = PayoutStatus.FAILED
        self.notes = reason
        logger.error(f"Payout {self.payout_id} failed: {reason}")

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            'payout_id': self.payout_id,
            'affiliate_id': self.affiliate_id,
            'amount': float(self.amount),
            'payment_method': self.payment_method,
            'status': self.status.value,
            'created_at': self.created_at.isoformat(),
            'processed_at': self.processed_at.isoformat() if self.processed_at else None,
            'transaction_id': self.transaction_id,
            'notes': self.notes
        }


class AffiliateManager:
    """Manage affiliates, referrals, and payouts"""

    # Minimum payout threshold
    MIN_PAYOUT = Decimal("100.00")

    def __init__(self):
        self._affiliates: Dict[str, Affiliate] = {}
        self._referrals: Dict[str, Referral] = {}
        self._payouts: Dict[str, Payout] = {}
        self._affiliate_codes: Dict[str, str] = {}  # code -> affiliate_id
        self._user_affiliates: Dict[str, str] = {}  # user_id -> affiliate_id

    def _generate_affiliate_code(self, length: int = 8) -> str:
        """Generate unique affiliate code"""
        chars = string.ascii_uppercase + string.digits
        while True:
            code = ''.join(secrets.choice(chars) for _ in range(length))
            if code not in self._affiliate_codes:
                return code

    def create_affiliate(
        self,
        user_id: str,
        payment_details: Optional[Dict[str, Any]] = None,
        custom_code: Optional[str] = None
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
            payment_details=payment_details
        )

        self._affiliates[affiliate_id] = affiliate
        self._affiliate_codes[code] = affiliate_id
        self._user_affiliates[user_id] = affiliate_id

        logger.info(f"Created affiliate {affiliate_id} with code {code}")
        return affiliate

    def get_affiliate(self, affiliate_id: str) -> Optional[Affiliate]:
        """Get affiliate by ID"""
        return self._affiliates.get(affiliate_id)

    def get_affiliate_by_code(self, code: str) -> Optional[Affiliate]:
        """Get affiliate by referral code"""
        affiliate_id = self._affiliate_codes.get(code.upper())
        return self._affiliates.get(affiliate_id) if affiliate_id else None

    def get_user_affiliate(self, user_id: str) -> Optional[Affiliate]:
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

    def create_referral(
        self,
        affiliate_code: str,
        referred_user_id: str
    ) -> Optional[Referral]:
        """Create a referral tracking record"""
        import uuid

        affiliate = self.get_affiliate_by_code(affiliate_code)
        if not affiliate or not affiliate.is_active():
            logger.warning(f"Invalid or inactive affiliate code: {affiliate_code}")
            return None

        # Check if user was already referred
        for referral in self._referrals.values():
            if referral.referred_user_id == referred_user_id:
                logger.info(f"User {referred_user_id} already has referral tracking")
                return referral

        referral_id = f"REF-{uuid.uuid4().hex[:12].upper()}"
        referral = Referral(
            referral_id=referral_id,
            affiliate_id=affiliate.affiliate_id,
            referred_user_id=referred_user_id,
            status=ReferralStatus.PENDING
        )

        self._referrals[referral_id] = referral
        logger.info(f"Created referral {referral_id} for affiliate {affiliate.affiliate_id}")
        
        return referral

    def convert_referral(
        self,
        referred_user_id: str,
        tier: SubscriptionTier,
        subscription_amount: Decimal
    ) -> Optional[Decimal]:
        """Convert a referral when user subscribes"""
        # Find active referral for user
        referral = None
        for ref in self._referrals.values():
            if (ref.referred_user_id == referred_user_id and 
                ref.status == ReferralStatus.PENDING and
                not ref.is_expired()):
                referral = ref
                break

        if not referral:
            logger.info(f"No active referral found for user {referred_user_id}")
            return None

        affiliate = self.get_affiliate(referral.affiliate_id)
        if not affiliate or not affiliate.is_active():
            logger.warning(f"Affiliate {referral.affiliate_id} not active")
            return None

        # Calculate and apply commission
        commission = referral.convert(
            tier=tier,
            subscription_amount=subscription_amount,
            commission_rate=affiliate.get_commission_rate()
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

    def get_referral(self, referral_id: str) -> Optional[Referral]:
        """Get referral by ID"""
        return self._referrals.get(referral_id)

    def get_affiliate_referrals(
        self,
        affiliate_id: str,
        status: Optional[ReferralStatus] = None
    ) -> List[Referral]:
        """Get all referrals for an affiliate"""
        referrals = [
            ref for ref in self._referrals.values()
            if ref.affiliate_id == affiliate_id
        ]
        if status:
            referrals = [ref for ref in referrals if ref.status == status]
        return referrals

    def request_payout(
        self,
        affiliate_id: str,
        payment_method: str
    ) -> Optional[Payout]:
        """Request affiliate payout"""
        import uuid

        affiliate = self.get_affiliate(affiliate_id)
        if not affiliate or not affiliate.is_active():
            return None

        # Calculate pending commissions
        pending = self._calculate_pending_commission(affiliate_id)
        
        if pending < self.MIN_PAYOUT:
            logger.warning(
                f"Payout below minimum: ${pending} < ${self.MIN_PAYOUT}"
            )
            return None

        payout_id = f"PAY-{uuid.uuid4().hex[:12].upper()}"
        payout = Payout(
            payout_id=payout_id,
            affiliate_id=affiliate_id,
            amount=pending,
            payment_method=payment_method,
            status=PayoutStatus.PENDING
        )

        self._payouts[payout_id] = payout
        
        # Mark referrals as paid
        for ref in self.get_affiliate_referrals(affiliate_id, ReferralStatus.CONVERTED):
            ref.mark_paid()

        logger.info(f"Created payout request {payout_id} for ${pending}")
        return payout

    def _calculate_pending_commission(self, affiliate_id: str) -> Decimal:
        """Calculate total pending commission for affiliate"""
        total = Decimal("0.00")
        for ref in self.get_affiliate_referrals(affiliate_id, ReferralStatus.CONVERTED):
            if ref.commission_amount:
                total += ref.commission_amount
        return total

    def process_payout(
        self,
        payout_id: str,
        transaction_id: str
    ) -> bool:
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
        """Mark payout as failed"""
        payout = self._payouts.get(payout_id)
        if not payout:
            return False

        payout.fail(reason)
        return True

    def get_affiliate_metrics(self, affiliate_id: str) -> Optional[AffiliateMetrics]:
        """Get comprehensive affiliate metrics"""
        affiliate = self.get_affiliate(affiliate_id)
        if not affiliate:
            return None

        referrals = self.get_affiliate_referrals(affiliate_id)
        converted = [r for r in referrals if r.status in [ReferralStatus.CONVERTED, ReferralStatus.PAID]]
        
        pending_commission = self._calculate_pending_commission(affiliate_id)
        paid_commission = sum(
            ref.commission_amount or Decimal("0")
            for ref in referrals
            if ref.status == ReferralStatus.PAID
        )
        
        conversion_rate = (
            len(converted) / len(referrals) * 100 
            if referrals else 0.0
        )
        
        avg_commission = (
            affiliate.total_commissions / len(converted) 
            if converted else Decimal("0")
        )

        return AffiliateMetrics(
            total_referrals=len(referrals),
            converted_referrals=len(converted),
            total_revenue=affiliate.total_revenue,
            total_commissions=affiliate.total_commissions,
            pending_commissions=pending_commission,
            paid_commissions=paid_commission,
            conversion_rate=conversion_rate,
            avg_commission=avg_commission
        )

    def get_affiliate_payouts(
        self,
        affiliate_id: str,
        status: Optional[PayoutStatus] = None
    ) -> List[Payout]:
        """Get all payouts for an affiliate"""
        payouts = [
            p for p in self._payouts.values()
            if p.affiliate_id == affiliate_id
        ]
        if status:
            payouts = [p for p in payouts if p.status == status]
        return payouts

    def get_all_affiliates(
        self,
        status: Optional[AffiliateStatus] = None
    ) -> List[Affiliate]:
        """Get all affiliates"""
        affiliates = list(self._affiliates.values())
        if status:
            affiliates = [a for a in affiliates if a.status == status]
        return affiliates

    def get_leaderboard(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get top affiliates leaderboard"""
        active = self.get_all_affiliates(AffiliateStatus.ACTIVE)
        sorted_affiliates = sorted(
            active,
            key=lambda a: (a.total_revenue, a.total_referrals),
            reverse=True
        )
        
        return [
            {
                'rank': idx + 1,
                'affiliate_id': a.affiliate_id,
                'code': a.code,
                'level': a.level.value,
                'total_referrals': a.total_referrals,
                'total_revenue': float(a.total_revenue),
                'total_commissions': float(a.total_commissions)
            }
            for idx, a in enumerate(sorted_affiliates[:limit])
        ]

    def get_stats(self) -> Dict[str, Any]:
        """Get overall affiliate program statistics"""
        affiliates = list(self._affiliates.values())
        referrals = list(self._referrals.values())
        payouts = list(self._payouts.values())

        total_revenue = sum(a.total_revenue for a in affiliates)
        total_commissions = sum(a.total_commissions for a in affiliates)
        total_payouts = sum(
            p.amount for p in payouts 
            if p.status == PayoutStatus.COMPLETED
        )

        return {
            'total_affiliates': len(affiliates),
            'active_affiliates': len([a for a in affiliates if a.is_active()]),
            'pending_affiliates': len([a for a in affiliates if a.status == AffiliateStatus.PENDING]),
            'total_referrals': len(referrals),
            'converted_referrals': len([r for r in referrals if r.status in [ReferralStatus.CONVERTED, ReferralStatus.PAID]]),
            'total_revenue_generated': float(total_revenue),
            'total_commissions_earned': float(total_commissions),
            'total_payouts_processed': float(total_payouts),
            'level_breakdown': {
                level.value: len([a for a in affiliates if a.level == level])
                for level in AffiliateLevel
            }
        }


# Global affiliate manager instance
affiliate_manager = AffiliateManager()

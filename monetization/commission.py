"""
Commission Tracking System

This module handles commission calculation, tracking, and reporting for trades.
Commissions are charged based on subscription tier (0.1% - 0.5% per trade).
"""

import logging
from datetime import datetime
from typing import Optional, Dict, List
from decimal import Decimal
from enum import Enum

from .pricing import SubscriptionTier, pricing_manager


logger = logging.getLogger(__name__)


class CommissionStatus(str, Enum):
    """Commission status enumeration"""
    PENDING = "pending"
    COLLECTED = "collected"
    FAILED = "failed"
    REFUNDED = "refunded"


class Commission:
    """Commission record model"""

    def __init__(
        self,
        commission_id: str,
        user_id: str,
        subscription_id: str,
        tier: SubscriptionTier,
        trade_id: str,
        trade_amount: Decimal,
        commission_rate: Decimal,
        commission_amount: Decimal,
        currency: str = "USD",
        status: CommissionStatus = CommissionStatus.PENDING
    ):
        self.commission_id = commission_id
        self.user_id = user_id
        self.subscription_id = subscription_id
        self.tier = tier
        self.trade_id = trade_id
        self.trade_amount = trade_amount
        self.commission_rate = commission_rate
        self.commission_amount = commission_amount
        self.currency = currency
        self.status = status
        self.created_at = datetime.utcnow()
        self.collected_at: Optional[datetime] = None

    def mark_collected(self) -> None:
        """Mark commission as collected"""
        self.status = CommissionStatus.COLLECTED
        self.collected_at = datetime.utcnow()
        logger.info(f"Commission {self.commission_id} marked as collected")

    def mark_failed(self) -> None:
        """Mark commission as failed"""
        self.status = CommissionStatus.FAILED
        logger.warning(f"Commission {self.commission_id} marked as failed")

    def refund(self) -> None:
        """Refund commission"""
        self.status = CommissionStatus.REFUNDED
        logger.info(f"Commission {self.commission_id} refunded")

    def to_dict(self) -> Dict:
        """Convert to dictionary"""
        return {
            'commission_id': self.commission_id,
            'user_id': self.user_id,
            'subscription_id': self.subscription_id,
            'tier': self.tier.value,
            'trade_id': self.trade_id,
            'trade_amount': float(self.trade_amount),
            'commission_rate': float(self.commission_rate),
            'commission_amount': float(self.commission_amount),
            'currency': self.currency,
            'status': self.status.value,
            'created_at': self.created_at.isoformat(),
            'collected_at': self.collected_at.isoformat() if self.collected_at else None
        }


class CommissionTracker:
    """Track and manage commissions"""

    def __init__(self):
        self._commissions: Dict[str, Commission] = {}
        self._user_commissions: Dict[str, List[str]] = {}  # user_id -> [commission_ids]

    def calculate_commission(
        self,
        user_id: str,
        subscription_id: str,
        tier: SubscriptionTier,
        trade_id: str,
        trade_amount: Decimal,
        currency: str = "USD"
    ) -> Commission:
        """Calculate commission for a trade"""
        import uuid

        commission_id = f"COM-{uuid.uuid4().hex[:12].upper()}"
        commission_rate = pricing_manager.get_commission_rate(tier)
        commission_amount = trade_amount * commission_rate

        commission = Commission(
            commission_id=commission_id,
            user_id=user_id,
            subscription_id=subscription_id,
            tier=tier,
            trade_id=trade_id,
            trade_amount=trade_amount,
            commission_rate=commission_rate,
            commission_amount=commission_amount,
            currency=currency,
            status=CommissionStatus.PENDING
        )

        self._commissions[commission_id] = commission

        if user_id not in self._user_commissions:
            self._user_commissions[user_id] = []
        self._user_commissions[user_id].append(commission_id)

        logger.info(
            f"Calculated commission {commission_id}: "
            f"${commission_amount:.2f} ({commission_rate:.2%}) "
            f"for trade {trade_id}"
        )

        return commission

    def collect_commission(self, commission_id: str) -> bool:
        """Collect a commission"""
        commission = self._commissions.get(commission_id)
        if not commission:
            logger.error(f"Commission {commission_id} not found")
            return False

        if commission.status != CommissionStatus.PENDING:
            logger.warning(f"Commission {commission_id} already processed")
            return False

        commission.mark_collected()
        return True

    def get_commission(self, commission_id: str) -> Optional[Commission]:
        """Get commission by ID"""
        return self._commissions.get(commission_id)

    def get_user_commissions(self, user_id: str) -> List[Commission]:
        """Get all commissions for a user"""
        commission_ids = self._user_commissions.get(user_id, [])
        return [self._commissions[cid] for cid in commission_ids if cid in self._commissions]

    def get_user_total_commissions(
        self,
        user_id: str,
        status: Optional[CommissionStatus] = None
    ) -> Decimal:
        """Get total commissions for a user"""
        commissions = self.get_user_commissions(user_id)

        if status:
            commissions = [c for c in commissions if c.status == status]

        total = sum(c.commission_amount for c in commissions)
        return Decimal(str(total))

    def get_pending_commissions(self, user_id: Optional[str] = None) -> List[Commission]:
        """Get pending commissions"""
        if user_id:
            commissions = self.get_user_commissions(user_id)
            return [c for c in commissions if c.status == CommissionStatus.PENDING]

        return [c for c in self._commissions.values() if c.status == CommissionStatus.PENDING]

    def get_collected_commissions(self, user_id: Optional[str] = None) -> List[Commission]:
        """Get collected commissions"""
        if user_id:
            commissions = self.get_user_commissions(user_id)
            return [c for c in commissions if c.status == CommissionStatus.COLLECTED]

        return [c for c in self._commissions.values() if c.status == CommissionStatus.COLLECTED]

    def get_commission_stats(self, user_id: Optional[str] = None) -> Dict:
        """Get commission statistics"""
        if user_id:
            commissions = self.get_user_commissions(user_id)
        else:
            commissions = list(self._commissions.values())

        total_commissions = len(commissions)
        pending = sum(1 for c in commissions if c.status == CommissionStatus.PENDING)
        collected = sum(1 for c in commissions if c.status == CommissionStatus.COLLECTED)
        failed = sum(1 for c in commissions if c.status == CommissionStatus.FAILED)

        total_amount = sum(c.commission_amount for c in commissions)
        collected_amount = sum(
            c.commission_amount for c in commissions
            if c.status == CommissionStatus.COLLECTED
        )
        pending_amount = sum(
            c.commission_amount for c in commissions
            if c.status == CommissionStatus.PENDING
        )

        return {
            'total_commissions': total_commissions,
            'pending_count': pending,
            'collected_count': collected,
            'failed_count': failed,
            'total_amount': float(total_amount),
            'collected_amount': float(collected_amount),
            'pending_amount': float(pending_amount),
            'average_commission': float(total_amount / total_commissions) if total_commissions > 0 else 0.0
        }

    def get_monthly_commissions(
        self,
        user_id: Optional[str] = None,
        year: Optional[int] = None,
        month: Optional[int] = None
    ) -> Dict:
        """Get monthly commission report"""
        now = datetime.utcnow()
        year = year or now.year
        month = month or now.month

        if user_id:
            commissions = self.get_user_commissions(user_id)
        else:
            commissions = list(self._commissions.values())

        monthly_commissions = [
            c for c in commissions
            if c.created_at.year == year and c.created_at.month == month
        ]

        total = sum(c.commission_amount for c in monthly_commissions)
        collected = sum(
            c.commission_amount for c in monthly_commissions
            if c.status == CommissionStatus.COLLECTED
        )

        return {
            'year': year,
            'month': month,
            'total_count': len(monthly_commissions),
            'total_amount': float(total),
            'collected_amount': float(collected),
            'average_commission': float(total / len(monthly_commissions)) if monthly_commissions else 0.0
        }

    def get_tier_breakdown(self) -> Dict:
        """Get commission breakdown by tier"""
        breakdown = {}

        for tier in SubscriptionTier:
            tier_commissions = [
                c for c in self._commissions.values()
                if c.tier == tier
            ]

            total = sum(c.commission_amount for c in tier_commissions)
            collected = sum(
                c.commission_amount for c in tier_commissions
                if c.status == CommissionStatus.COLLECTED
            )

            breakdown[tier.value] = {
                'count': len(tier_commissions),
                'total_amount': float(total),
                'collected_amount': float(collected),
                'commission_rate': float(pricing_manager.get_commission_rate(tier))
            }

        return breakdown


# Global commission tracker instance
commission_tracker = CommissionTracker()

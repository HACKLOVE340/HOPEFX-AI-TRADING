"""
Subscription Management

This module handles user subscriptions, including creation, updates,
cancellations, and feature access control.
"""

import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, List
from enum import Enum
from decimal import Decimal

from .pricing import SubscriptionTier, pricing_manager


logger = logging.getLogger(__name__)


class SubscriptionStatus(str, Enum):
    """Subscription status enumeration"""
    ACTIVE = "active"
    CANCELLED = "cancelled"
    EXPIRED = "expired"
    SUSPENDED = "suspended"
    PENDING = "pending"
    TRIAL = "trial"


class Subscription:
    """User subscription model"""
    
    def __init__(
        self,
        subscription_id: str,
        user_id: str,
        tier: SubscriptionTier,
        status: SubscriptionStatus = SubscriptionStatus.PENDING,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        access_code: Optional[str] = None,
        auto_renew: bool = True
    ):
        self.subscription_id = subscription_id
        self.user_id = user_id
        self.tier = tier
        self.status = status
        self.start_date = start_date or datetime.utcnow()
        self.end_date = end_date or (self.start_date + timedelta(days=30))
        self.access_code = access_code
        self.auto_renew = auto_renew
        self.created_at = datetime.utcnow()
        self.updated_at = datetime.utcnow()
    
    def is_active(self) -> bool:
        """Check if subscription is active"""
        if self.status != SubscriptionStatus.ACTIVE:
            return False
        
        now = datetime.utcnow()
        return self.start_date <= now <= self.end_date
    
    def is_expired(self) -> bool:
        """Check if subscription is expired"""
        return datetime.utcnow() > self.end_date
    
    def days_remaining(self) -> int:
        """Get days remaining in subscription"""
        if self.is_expired():
            return 0
        return (self.end_date - datetime.utcnow()).days
    
    def renew(self, duration_days: int = 30) -> None:
        """Renew subscription"""
        if self.is_expired():
            self.start_date = datetime.utcnow()
        self.end_date = datetime.utcnow() + timedelta(days=duration_days)
        self.status = SubscriptionStatus.ACTIVE
        self.updated_at = datetime.utcnow()
        logger.info(f"Subscription {self.subscription_id} renewed until {self.end_date}")
    
    def cancel(self) -> None:
        """Cancel subscription"""
        self.status = SubscriptionStatus.CANCELLED
        self.auto_renew = False
        self.updated_at = datetime.utcnow()
        logger.info(f"Subscription {self.subscription_id} cancelled")
    
    def suspend(self) -> None:
        """Suspend subscription"""
        self.status = SubscriptionStatus.SUSPENDED
        self.updated_at = datetime.utcnow()
        logger.info(f"Subscription {self.subscription_id} suspended")
    
    def reactivate(self) -> None:
        """Reactivate subscription"""
        if self.is_expired():
            self.renew()
        else:
            self.status = SubscriptionStatus.ACTIVE
        self.updated_at = datetime.utcnow()
        logger.info(f"Subscription {self.subscription_id} reactivated")
    
    def to_dict(self) -> Dict:
        """Convert to dictionary"""
        return {
            'subscription_id': self.subscription_id,
            'user_id': self.user_id,
            'tier': self.tier.value,
            'status': self.status.value,
            'start_date': self.start_date.isoformat(),
            'end_date': self.end_date.isoformat(),
            'access_code': self.access_code,
            'auto_renew': self.auto_renew,
            'is_active': self.is_active(),
            'days_remaining': self.days_remaining(),
            'created_at': self.created_at.isoformat(),
            'updated_at': self.updated_at.isoformat()
        }


class SubscriptionManager:
    """Manage user subscriptions"""
    
    def __init__(self):
        self._subscriptions: Dict[str, Subscription] = {}
        self._user_subscriptions: Dict[str, str] = {}  # user_id -> subscription_id
    
    def create_subscription(
        self,
        user_id: str,
        tier: SubscriptionTier,
        duration_days: int = 30,
        access_code: Optional[str] = None,
        auto_renew: bool = True
    ) -> Subscription:
        """Create a new subscription"""
        import uuid
        
        subscription_id = f"SUB-{uuid.uuid4().hex[:12].upper()}"
        start_date = datetime.utcnow()
        end_date = start_date + timedelta(days=duration_days)
        
        subscription = Subscription(
            subscription_id=subscription_id,
            user_id=user_id,
            tier=tier,
            status=SubscriptionStatus.PENDING,
            start_date=start_date,
            end_date=end_date,
            access_code=access_code,
            auto_renew=auto_renew
        )
        
        self._subscriptions[subscription_id] = subscription
        self._user_subscriptions[user_id] = subscription_id
        
        logger.info(f"Created subscription {subscription_id} for user {user_id}")
        return subscription
    
    def get_subscription(self, subscription_id: str) -> Optional[Subscription]:
        """Get subscription by ID"""
        return self._subscriptions.get(subscription_id)
    
    def get_user_subscription(self, user_id: str) -> Optional[Subscription]:
        """Get active subscription for a user"""
        subscription_id = self._user_subscriptions.get(user_id)
        if subscription_id:
            return self._subscriptions.get(subscription_id)
        return None
    
    def activate_subscription(self, subscription_id: str, access_code: str) -> bool:
        """Activate a subscription with access code"""
        subscription = self.get_subscription(subscription_id)
        if not subscription:
            logger.error(f"Subscription {subscription_id} not found")
            return False
        
        if subscription.access_code != access_code:
            logger.error(f"Invalid access code for subscription {subscription_id}")
            return False
        
        subscription.status = SubscriptionStatus.ACTIVE
        subscription.updated_at = datetime.utcnow()
        
        logger.info(f"Activated subscription {subscription_id}")
        return True
    
    def upgrade_subscription(
        self,
        subscription_id: str,
        new_tier: SubscriptionTier
    ) -> bool:
        """Upgrade subscription to a higher tier"""
        subscription = self.get_subscription(subscription_id)
        if not subscription:
            return False
        
        # Check if upgrade is valid
        upgrade_path = pricing_manager.get_upgrade_path(subscription.tier)
        if new_tier not in upgrade_path:
            logger.error(f"Invalid upgrade from {subscription.tier} to {new_tier}")
            return False
        
        subscription.tier = new_tier
        subscription.updated_at = datetime.utcnow()
        
        logger.info(f"Upgraded subscription {subscription_id} to {new_tier}")
        return True
    
    def downgrade_subscription(
        self,
        subscription_id: str,
        new_tier: SubscriptionTier
    ) -> bool:
        """Downgrade subscription to a lower tier"""
        subscription = self.get_subscription(subscription_id)
        if not subscription:
            return False
        
        # Check if downgrade is valid
        downgrade_path = pricing_manager.get_downgrade_path(subscription.tier)
        if new_tier not in downgrade_path:
            logger.error(f"Invalid downgrade from {subscription.tier} to {new_tier}")
            return False
        
        subscription.tier = new_tier
        subscription.updated_at = datetime.utcnow()
        
        logger.info(f"Downgraded subscription {subscription_id} to {new_tier}")
        return True
    
    def renew_subscription(self, subscription_id: str, duration_days: int = 30) -> bool:
        """Renew a subscription"""
        subscription = self.get_subscription(subscription_id)
        if not subscription:
            return False
        
        subscription.renew(duration_days)
        return True
    
    def cancel_subscription(self, subscription_id: str) -> bool:
        """Cancel a subscription"""
        subscription = self.get_subscription(subscription_id)
        if not subscription:
            return False
        
        subscription.cancel()
        return True
    
    def check_feature_access(self, user_id: str, feature_name: str) -> bool:
        """Check if user has access to a feature"""
        subscription = self.get_user_subscription(user_id)
        if not subscription or not subscription.is_active():
            return False
        
        return pricing_manager.has_feature(subscription.tier, feature_name)
    
    def get_user_limits(self, user_id: str) -> Dict:
        """Get usage limits for a user"""
        subscription = self.get_user_subscription(user_id)
        if not subscription or not subscription.is_active():
            return {
                'max_strategies': 0,
                'max_brokers': 0,
                'ml_features': False,
                'api_access': False
            }
        
        tier = pricing_manager.get_tier(subscription.tier)
        if not tier:
            return {}
        
        return {
            'max_strategies': tier.features.max_strategies,
            'max_brokers': tier.features.max_brokers,
            'ml_features': tier.features.ml_features,
            'priority_support': tier.features.priority_support,
            'api_access': tier.features.api_access,
            'custom_development': tier.features.custom_development,
            'dedicated_support': tier.features.dedicated_support,
            'backtesting_unlimited': tier.features.backtesting_unlimited,
            'pattern_recognition': tier.features.pattern_recognition,
            'news_integration': tier.features.news_integration
        }
    
    def get_all_subscriptions(self) -> List[Subscription]:
        """Get all subscriptions"""
        return list(self._subscriptions.values())
    
    def get_active_subscriptions(self) -> List[Subscription]:
        """Get all active subscriptions"""
        return [sub for sub in self._subscriptions.values() if sub.is_active()]
    
    def get_expired_subscriptions(self) -> List[Subscription]:
        """Get all expired subscriptions"""
        return [sub for sub in self._subscriptions.values() if sub.is_expired()]


# Global subscription manager instance
subscription_manager = SubscriptionManager()

"""
License Validation System

This module handles license validation, feature gating, and access control
based on user subscriptions and access codes.
"""

import logging
from datetime import datetime
from typing import Optional, Dict, List
from enum import Enum

from .pricing import SubscriptionTier, pricing_manager
from .subscription import subscription_manager, SubscriptionStatus
from .access_codes import access_code_generator


logger = logging.getLogger(__name__)


class ValidationResult(str, Enum):
    """Validation result enumeration"""
    VALID = "valid"
    EXPIRED = "expired"
    INVALID = "invalid"
    NO_SUBSCRIPTION = "no_subscription"
    SUSPENDED = "suspended"
    FEATURE_NOT_AVAILABLE = "feature_not_available"


class LicenseValidator:
    """Validate licenses and control feature access"""
    
    def __init__(self):
        self._validation_cache: Dict[str, Dict] = {}
        self._cache_duration = 300  # 5 minutes
    
    def validate_access_code(self, code: str) -> tuple:
        """Validate an access code"""
        # Validate format
        if not access_code_generator.validate_code(code):
            return ValidationResult.INVALID, "Invalid code format"
        
        # Get code object
        access_code = access_code_generator.get_code(code)
        if not access_code:
            return ValidationResult.INVALID, "Code not found"
        
        # Check if valid
        if not access_code.is_valid():
            if access_code.is_expired():
                return ValidationResult.EXPIRED, "Code has expired"
            return ValidationResult.INVALID, "Code is not active"
        
        return ValidationResult.VALID, "Code is valid"
    
    def validate_subscription(self, user_id: str) -> tuple:
        """Validate user subscription"""
        subscription = subscription_manager.get_user_subscription(user_id)
        
        if not subscription:
            return ValidationResult.NO_SUBSCRIPTION, "No active subscription"
        
        if subscription.status == SubscriptionStatus.SUSPENDED:
            return ValidationResult.SUSPENDED, "Subscription is suspended"
        
        if subscription.status == SubscriptionStatus.CANCELLED:
            return ValidationResult.INVALID, "Subscription is cancelled"
        
        if subscription.is_expired():
            return ValidationResult.EXPIRED, "Subscription has expired"
        
        if not subscription.is_active():
            return ValidationResult.INVALID, "Subscription is not active"
        
        return ValidationResult.VALID, "Subscription is active"
    
    def has_feature_access(self, user_id: str, feature_name: str) -> bool:
        """Check if user has access to a feature"""
        # Check cache first
        cache_key = f"{user_id}:{feature_name}"
        if cache_key in self._validation_cache:
            cache_entry = self._validation_cache[cache_key]
            if (datetime.utcnow() - cache_entry['timestamp']).seconds < self._cache_duration:
                return cache_entry['has_access']
        
        # Validate subscription
        result, message = self.validate_subscription(user_id)
        if result != ValidationResult.VALID:
            self._update_cache(cache_key, False)
            return False
        
        # Check feature access
        has_access = subscription_manager.check_feature_access(user_id, feature_name)
        
        # Update cache
        self._update_cache(cache_key, has_access)
        
        return has_access
    
    def _update_cache(self, cache_key: str, has_access: bool) -> None:
        """Update validation cache"""
        self._validation_cache[cache_key] = {
            'has_access': has_access,
            'timestamp': datetime.utcnow()
        }
    
    def get_user_tier(self, user_id: str) -> Optional[SubscriptionTier]:
        """Get user's subscription tier"""
        subscription = subscription_manager.get_user_subscription(user_id)
        return subscription.tier if subscription else None
    
    def get_user_limits(self, user_id: str) -> Dict:
        """Get user's usage limits"""
        return subscription_manager.get_user_limits(user_id)
    
    def check_strategy_limit(self, user_id: str, current_strategies: int) -> bool:
        """Check if user can create more strategies"""
        limits = self.get_user_limits(user_id)
        max_strategies = limits.get('max_strategies', 0)
        return current_strategies < max_strategies
    
    def check_broker_limit(self, user_id: str, current_brokers: int) -> bool:
        """Check if user can connect more brokers"""
        limits = self.get_user_limits(user_id)
        max_brokers = limits.get('max_brokers', 0)
        return current_brokers < max_brokers
    
    def get_feature_list(self, user_id: str) -> List[str]:
        """Get list of available features for user"""
        limits = self.get_user_limits(user_id)
        features = []
        
        if limits.get('ml_features'):
            features.append('ml_features')
        if limits.get('priority_support'):
            features.append('priority_support')
        if limits.get('api_access'):
            features.append('api_access')
        if limits.get('custom_development'):
            features.append('custom_development')
        if limits.get('dedicated_support'):
            features.append('dedicated_support')
        if limits.get('backtesting_unlimited'):
            features.append('backtesting_unlimited')
        if limits.get('pattern_recognition'):
            features.append('pattern_recognition')
        if limits.get('news_integration'):
            features.append('news_integration')
        
        return features
    
    def validate_api_access(self, user_id: str, api_key: str) -> bool:
        """Validate API access"""
        # Check subscription validity
        result, _ = self.validate_subscription(user_id)
        if result != ValidationResult.VALID:
            return False
        
        # Check API access feature
        if not self.has_feature_access(user_id, 'api_access'):
            return False
        
        # Validate API key (would check against stored keys in production)
        return True
    
    def generate_license_info(self, user_id: str) -> Dict:
        """Generate comprehensive license information"""
        subscription = subscription_manager.get_user_subscription(user_id)
        
        if not subscription:
            return {
                'valid': False,
                'reason': 'No active subscription',
                'tier': None,
                'features': [],
                'limits': {}
            }
        
        result, message = self.validate_subscription(user_id)
        limits = self.get_user_limits(user_id)
        features = self.get_feature_list(user_id)
        
        return {
            'valid': result == ValidationResult.VALID,
            'reason': message,
            'user_id': user_id,
            'subscription_id': subscription.subscription_id,
            'tier': subscription.tier.value,
            'tier_name': pricing_manager.get_tier(subscription.tier).name,
            'status': subscription.status.value,
            'expires_at': subscription.end_date.isoformat(),
            'days_remaining': subscription.days_remaining(),
            'features': features,
            'limits': limits,
            'commission_rate': float(pricing_manager.get_commission_rate(subscription.tier))
        }
    
    def can_upgrade_tier(self, user_id: str, new_tier: SubscriptionTier) -> bool:
        """Check if user can upgrade to new tier"""
        current_tier = self.get_user_tier(user_id)
        if not current_tier:
            return True  # New subscription
        
        upgrade_path = pricing_manager.get_upgrade_path(current_tier)
        return new_tier in upgrade_path
    
    def can_downgrade_tier(self, user_id: str, new_tier: SubscriptionTier) -> bool:
        """Check if user can downgrade to new tier"""
        current_tier = self.get_user_tier(user_id)
        if not current_tier:
            return False
        
        downgrade_path = pricing_manager.get_downgrade_path(current_tier)
        return new_tier in downgrade_path
    
    def clear_cache(self, user_id: Optional[str] = None) -> None:
        """Clear validation cache"""
        if user_id:
            # Clear only user's cache
            keys_to_remove = [k for k in self._validation_cache.keys() if k.startswith(f"{user_id}:")]
            for key in keys_to_remove:
                del self._validation_cache[key]
        else:
            # Clear entire cache
            self._validation_cache.clear()
        
        logger.info(f"Cleared validation cache for user: {user_id or 'all'}")


# Global license validator instance
license_validator = LicenseValidator()

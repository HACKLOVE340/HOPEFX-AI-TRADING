"""
Access Code Generation and Validation

This module handles generation and validation of access codes for subscriptions.
Format: HOPEFX-{TIER}-{RANDOM}-{CHECKSUM}
Example: HOPEFX-PRO-A7B9C2D4-X8Y2
"""

import logging
import hashlib
import secrets
import string
from datetime import datetime, timedelta
from typing import Optional, Dict
from enum import Enum

from .pricing import SubscriptionTier


logger = logging.getLogger(__name__)


class AccessCodeStatus(str, Enum):
    """Access code status enumeration"""
    ACTIVE = "active"
    USED = "used"
    EXPIRED = "expired"
    REVOKED = "revoked"


class AccessCode:
    """Access code model"""

    def __init__(
        self,
        code: str,
        tier: SubscriptionTier,
        duration_days: int = 30,
        user_id: Optional[str] = None,
        subscription_id: Optional[str] = None,
        status: AccessCodeStatus = AccessCodeStatus.ACTIVE
    ):
        self.code = code
        self.tier = tier
        self.duration_days = duration_days
        self.user_id = user_id
        self.subscription_id = subscription_id
        self.status = status
        self.created_at = datetime.utcnow()
        self.expires_at = self.created_at + timedelta(days=duration_days)
        self.activated_at: Optional[datetime] = None
        self.used_at: Optional[datetime] = None

    def is_valid(self) -> bool:
        """Check if access code is valid"""
        if self.status != AccessCodeStatus.ACTIVE:
            return False

        if datetime.utcnow() > self.expires_at:
            self.status = AccessCodeStatus.EXPIRED
            return False

        return True

    def activate(self, user_id: str, subscription_id: str) -> bool:
        """Activate access code"""
        if not self.is_valid():
            logger.error(f"Cannot activate invalid code {self.code}")
            return False

        self.user_id = user_id
        self.subscription_id = subscription_id
        self.status = AccessCodeStatus.USED
        self.activated_at = datetime.utcnow()
        self.used_at = datetime.utcnow()

        logger.info(f"Access code {self.code} activated for user {user_id}")
        return True

    def revoke(self) -> None:
        """Revoke access code"""
        self.status = AccessCodeStatus.REVOKED
        logger.info(f"Access code {self.code} revoked")

    def to_dict(self) -> Dict:
        """Convert to dictionary"""
        return {
            'code': self.code,
            'tier': self.tier.value,
            'duration_days': self.duration_days,
            'user_id': self.user_id,
            'subscription_id': self.subscription_id,
            'status': self.status.value,
            'is_valid': self.is_valid(),
            'created_at': self.created_at.isoformat(),
            'expires_at': self.expires_at.isoformat(),
            'activated_at': self.activated_at.isoformat() if self.activated_at else None,
            'used_at': self.used_at.isoformat() if self.used_at else None
        }


class AccessCodeGenerator:
    """Generate and manage access codes"""

    def __init__(self):
        self._codes: Dict[str, AccessCode] = {}
        self._tier_prefixes = {
            SubscriptionTier.FREE: "FRE",
            SubscriptionTier.STARTER: "STR",
            SubscriptionTier.PROFESSIONAL: "PRO",
            SubscriptionTier.ENTERPRISE: "ENT",
            SubscriptionTier.ELITE: "ELT"
        }

    def _generate_random_string(self, length: int = 8) -> str:
        """Generate random alphanumeric string"""
        chars = string.ascii_uppercase + string.digits
        return ''.join(secrets.choice(chars) for _ in range(length))

    def _calculate_checksum(self, tier_prefix: str, random_part: str) -> str:
        """Calculate checksum for verification"""
        data = f"{tier_prefix}{random_part}".encode()
        hash_obj = hashlib.sha256(data)
        return hash_obj.hexdigest()[:4].upper()

    def generate_code(
        self,
        tier: SubscriptionTier,
        duration_days: int = 30
    ) -> AccessCode:
        """Generate a new access code"""
        tier_prefix = self._tier_prefixes.get(tier, "UNK")
        random_part = self._generate_random_string(8)
        checksum = self._calculate_checksum(tier_prefix, random_part)

        code = f"HOPEFX-{tier_prefix}-{random_part}-{checksum}"

        access_code = AccessCode(
            code=code,
            tier=tier,
            duration_days=duration_days,
            status=AccessCodeStatus.ACTIVE
        )

        self._codes[code] = access_code

        logger.info(f"Generated access code: {code} for tier {tier.value}")
        return access_code

    def validate_code(self, code: str) -> bool:
        """Validate access code format and checksum"""
        try:
            parts = code.split('-')
            if len(parts) != 4:
                return False

            if parts[0] != "HOPEFX":
                return False

            tier_prefix = parts[1]
            random_part = parts[2]
            provided_checksum = parts[3]

            calculated_checksum = self._calculate_checksum(tier_prefix, random_part)

            return provided_checksum == calculated_checksum
        except Exception as e:
            logger.error(f"Error validating code {code}: {e}")
            return False

    def get_code(self, code: str) -> Optional[AccessCode]:
        """Get access code by code string"""
        return self._codes.get(code)

    def activate_code(
        self,
        code: str,
        user_id: str,
        subscription_id: str
    ) -> bool:
        """Activate an access code"""
        if not self.validate_code(code):
            logger.error(f"Invalid code format: {code}")
            return False

        access_code = self.get_code(code)
        if not access_code:
            logger.error(f"Access code not found: {code}")
            return False

        return access_code.activate(user_id, subscription_id)

    def revoke_code(self, code: str) -> bool:
        """Revoke an access code"""
        access_code = self.get_code(code)
        if not access_code:
            return False

        access_code.revoke()
        return True

    def get_active_codes(self) -> list:
        """Get all active access codes"""
        return [
            code for code in self._codes.values()
            if code.status == AccessCodeStatus.ACTIVE and code.is_valid()
        ]

    def get_used_codes(self) -> list:
        """Get all used access codes"""
        return [
            code for code in self._codes.values()
            if code.status == AccessCodeStatus.USED
        ]

    def get_expired_codes(self) -> list:
        """Get all expired access codes"""
        return [
            code for code in self._codes.values()
            if code.status == AccessCodeStatus.EXPIRED or not code.is_valid()
        ]

    def get_tier_from_code(self, code: str) -> Optional[SubscriptionTier]:
        """Extract tier from code"""
        try:
            parts = code.split('-')
            if len(parts) != 4:
                return None

            tier_prefix = parts[1]

            prefix_to_tier = {v: k for k, v in self._tier_prefixes.items()}
            return prefix_to_tier.get(tier_prefix)
        except Exception as e:
            logger.error(f"Error extracting tier from code {code}: {e}")
            return None

    def generate_batch_codes(
        self,
        tier: SubscriptionTier,
        count: int,
        duration_days: int = 30
    ) -> list:
        """Generate multiple access codes"""
        codes = []
        for _ in range(count):
            code = self.generate_code(tier, duration_days)
            codes.append(code)

        logger.info(f"Generated {count} access codes for tier {tier.value}")
        return codes

    def get_code_stats(self) -> Dict:
        """Get access code statistics"""
        total = len(self._codes)
        active = len(self.get_active_codes())
        used = len(self.get_used_codes())
        expired = len(self.get_expired_codes())

        tier_breakdown = {}
        for tier in SubscriptionTier:
            tier_codes = [c for c in self._codes.values() if c.tier == tier]
            tier_breakdown[tier.value] = {
                'total': len(tier_codes),
                'active': len([c for c in tier_codes if c.status == AccessCodeStatus.ACTIVE]),
                'used': len([c for c in tier_codes if c.status == AccessCodeStatus.USED])
            }

        return {
            'total_codes': total,
            'active_codes': active,
            'used_codes': used,
            'expired_codes': expired,
            'tier_breakdown': tier_breakdown
        }


# Global access code generator instance
access_code_generator = AccessCodeGenerator()

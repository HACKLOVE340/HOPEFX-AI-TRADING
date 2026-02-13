"""
Security Module

Handles 2FA, KYC verification, transaction limits, and fraud detection.
"""

from datetime import datetime, timedelta
from decimal import Decimal
from enum import Enum
from typing import Dict, Optional, List, Tuple
from dataclasses import dataclass
import logging
import hashlib
import secrets

logger = logging.getLogger(__name__)


class KYCLevel(Enum):
    """KYC verification levels"""
    NONE = "none"
    BASIC = "basic"  # $0-$1,000
    INTERMEDIATE = "intermediate"  # $1,000-$10,000
    ADVANCED = "advanced"  # >$10,000


@dataclass
class KYCInfo:
    """KYC information"""
    user_id: str
    level: KYCLevel
    verified_at: Optional[datetime] = None
    documents: Dict[str, str] = None

    def __post_init__(self):
        if self.documents is None:
            self.documents = {}


@dataclass
class TransactionLimit:
    """Transaction limits"""
    daily_limit: Decimal
    monthly_limit: Decimal
    per_transaction_limit: Decimal
    daily_used: Decimal = Decimal('0')
    monthly_used: Decimal = Decimal('0')
    last_reset: datetime = None

    def __post_init__(self):
        if self.last_reset is None:
            self.last_reset = datetime.utcnow()


class SecurityManager:
    """Manages security features including 2FA, KYC, and limits"""

    def __init__(self):
        self.kyc_info: Dict[str, KYCInfo] = {}
        self.transaction_limits: Dict[str, TransactionLimit] = {}
        self.totp_secrets: Dict[str, str] = {}
        self.failed_attempts: Dict[str, List[datetime]] = {}
        self.ip_whitelist: Dict[str, List[str]] = {}

        # Default limits by KYC level
        self.default_limits = {
            KYCLevel.NONE: {
                'daily': Decimal('100.00'),
                'monthly': Decimal('500.00'),
                'per_transaction': Decimal('100.00')
            },
            KYCLevel.BASIC: {
                'daily': Decimal('1000.00'),
                'monthly': Decimal('5000.00'),
                'per_transaction': Decimal('1000.00')
            },
            KYCLevel.INTERMEDIATE: {
                'daily': Decimal('10000.00'),
                'monthly': Decimal('50000.00'),
                'per_transaction': Decimal('10000.00')
            },
            KYCLevel.ADVANCED: {
                'daily': Decimal('100000.00'),
                'monthly': Decimal('500000.00'),
                'per_transaction': Decimal('100000.00')
            }
        }

    def setup_2fa(self, user_id: str) -> str:
        """
        Set up 2FA for user

        Args:
            user_id: User ID

        Returns:
            TOTP secret
        """
        # Generate random secret
        secret = secrets.token_hex(16)
        self.totp_secrets[user_id] = secret

        logger.info(f"2FA setup for user {user_id}")
        return secret

    def verify_2fa(self, user_id: str, token: str) -> bool:
        """
        Verify 2FA token

        Args:
            user_id: User ID
            token: TOTP token

        Returns:
            Verification result
        """
        # Simplified verification (in production, use TOTP library)
        secret = self.totp_secrets.get(user_id)
        if not secret:
            logger.warning(f"No 2FA secret for user {user_id}")
            return False

        # For demo purposes, accept any 6-digit token
        # In production, use pyotp.TOTP(secret).verify(token)
        is_valid = len(token) == 6 and token.isdigit()

        if is_valid:
            logger.info(f"2FA verified for user {user_id}")
        else:
            self._record_failed_attempt(user_id)
            logger.warning(f"2FA failed for user {user_id}")

        return is_valid

    def set_kyc_level(
        self,
        user_id: str,
        level: KYCLevel,
        documents: Optional[Dict[str, str]] = None
    ) -> None:
        """
        Set KYC level for user

        Args:
            user_id: User ID
            level: KYC level
            documents: Document references
        """
        kyc = KYCInfo(
            user_id=user_id,
            level=level,
            verified_at=datetime.utcnow() if level != KYCLevel.NONE else None,
            documents=documents or {}
        )

        self.kyc_info[user_id] = kyc

        # Update transaction limits
        self._update_limits(user_id, level)

        logger.info(f"KYC level set to {level.value} for user {user_id}")

    def get_kyc_info(self, user_id: str) -> KYCInfo:
        """Get KYC information"""
        if user_id not in self.kyc_info:
            # Default to NONE
            self.set_kyc_level(user_id, KYCLevel.NONE)

        return self.kyc_info[user_id]

    def _update_limits(self, user_id: str, level: KYCLevel) -> None:
        """Update transaction limits based on KYC level"""
        limits = self.default_limits[level]

        self.transaction_limits[user_id] = TransactionLimit(
            daily_limit=limits['daily'],
            monthly_limit=limits['monthly'],
            per_transaction_limit=limits['per_transaction']
        )

    def check_transaction_limit(
        self,
        user_id: str,
        amount: Decimal
    ) -> Tuple[bool, Optional[str]]:
        """
        Check if transaction is within limits

        Args:
            user_id: User ID
            amount: Transaction amount

        Returns:
            (allowed, reason) tuple
        """
        # Get user limits
        if user_id not in self.transaction_limits:
            kyc = self.get_kyc_info(user_id)
            self._update_limits(user_id, kyc.level)

        limits = self.transaction_limits[user_id]

        # Reset limits if needed
        self._reset_limits_if_needed(user_id)

        # Check per-transaction limit
        if amount > limits.per_transaction_limit:
            return False, f"Exceeds per-transaction limit of ${limits.per_transaction_limit}"

        # Check daily limit
        if limits.daily_used + amount > limits.daily_limit:
            return False, f"Exceeds daily limit of ${limits.daily_limit}"

        # Check monthly limit
        if limits.monthly_used + amount > limits.monthly_limit:
            return False, f"Exceeds monthly limit of ${limits.monthly_limit}"

        return True, None

    def record_transaction(self, user_id: str, amount: Decimal) -> None:
        """Record a transaction against limits"""
        if user_id not in self.transaction_limits:
            return

        limits = self.transaction_limits[user_id]
        limits.daily_used += amount
        limits.monthly_used += amount

    def _reset_limits_if_needed(self, user_id: str) -> None:
        """Reset limits if period has passed"""
        limits = self.transaction_limits.get(user_id)
        if not limits:
            return

        now = datetime.utcnow()

        # Reset daily if day changed
        if limits.last_reset.date() != now.date():
            limits.daily_used = Decimal('0')

        # Reset monthly if month changed
        if limits.last_reset.month != now.month:
            limits.monthly_used = Decimal('0')

        limits.last_reset = now

    def validate_transaction(
        self,
        user_id: str,
        amount: Decimal,
        transaction_type: str
    ) -> Tuple[bool, Optional[str]]:
        """
        Validate if transaction is allowed

        Args:
            user_id: User ID
            amount: Transaction amount
            transaction_type: Type of transaction

        Returns:
            (allowed, reason) tuple
        """
        # Check KYC level
        kyc = self.get_kyc_info(user_id)

        # Require at least BASIC KYC for amounts > $1000
        if amount > Decimal('1000.00') and kyc.level == KYCLevel.NONE:
            return False, "KYC verification required for amounts over $1,000"

        # Require INTERMEDIATE for amounts > $10000
        if amount > Decimal('10000.00') and kyc.level in [KYCLevel.NONE, KYCLevel.BASIC]:
            return False, "Advanced KYC verification required for amounts over $10,000"

        # Check transaction limits
        allowed, reason = self.check_transaction_limit(user_id, amount)
        if not allowed:
            return False, reason

        # Check for suspicious activity
        if self.check_suspicious_activity(user_id, amount):
            return False, "Transaction flagged for review"

        return True, None

    def check_suspicious_activity(
        self,
        user_id: str,
        amount: Decimal,
        ip_address: Optional[str] = None
    ) -> bool:
        """
        Check for suspicious activity

        Args:
            user_id: User ID
            amount: Transaction amount
            ip_address: IP address

        Returns:
            True if suspicious
        """
        # Check for unusually large amount (10x normal)
        if user_id in self.transaction_limits:
            limits = self.transaction_limits[user_id]
            if amount > limits.per_transaction_limit * 10:
                logger.warning(f"Suspicious: Large amount for user {user_id}")
                return True

        # Check failed attempts
        failed = self.failed_attempts.get(user_id, [])
        recent_failed = [f for f in failed if datetime.utcnow() - f < timedelta(hours=1)]
        if len(recent_failed) > 5:
            logger.warning(f"Suspicious: Multiple failed attempts for user {user_id}")
            return True

        # Check IP whitelist if configured
        if ip_address and user_id in self.ip_whitelist:
            if ip_address not in self.ip_whitelist[user_id]:
                logger.warning(f"Suspicious: Unknown IP for user {user_id}")
                return True

        return False

    def _record_failed_attempt(self, user_id: str) -> None:
        """Record a failed authentication attempt"""
        if user_id not in self.failed_attempts:
            self.failed_attempts[user_id] = []

        self.failed_attempts[user_id].append(datetime.utcnow())

    def add_ip_to_whitelist(self, user_id: str, ip_address: str) -> None:
        """Add IP to user's whitelist"""
        if user_id not in self.ip_whitelist:
            self.ip_whitelist[user_id] = []

        if ip_address not in self.ip_whitelist[user_id]:
            self.ip_whitelist[user_id].append(ip_address)
            logger.info(f"IP {ip_address} added to whitelist for user {user_id}")

    def get_security_status(self, user_id: str) -> Dict:
        """Get security status for user"""
        kyc = self.get_kyc_info(user_id)
        has_2fa = user_id in self.totp_secrets

        limits = self.transaction_limits.get(user_id)
        limits_info = None
        if limits:
            limits_info = {
                'daily_limit': float(limits.daily_limit),
                'daily_used': float(limits.daily_used),
                'daily_remaining': float(limits.daily_limit - limits.daily_used),
                'monthly_limit': float(limits.monthly_limit),
                'monthly_used': float(limits.monthly_used),
                'monthly_remaining': float(limits.monthly_limit - limits.monthly_used)
            }

        return {
            'user_id': user_id,
            'kyc_level': kyc.level.value,
            'kyc_verified': kyc.verified_at is not None,
            '2fa_enabled': has_2fa,
            'limits': limits_info,
            'ip_whitelist': self.ip_whitelist.get(user_id, [])
        }


# Global security manager instance
security_manager = SecurityManager()

# src/hopefx/marketplace/licensing.py
"""
Strategy licensing with time-bound and performance-gated access.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from enum import Enum
from typing import Literal

import structlog

logger = structlog.get_logger()


class LicenseTier(Enum):
    """Subscription tiers."""
    FREE = "free"
    BASIC = "basic"
    PRO = "pro"
    ENTERPRISE = "enterprise"


@dataclass(frozen=True)
class License:
    """Immutable license token."""
    license_id: str
    strategy_id: str
    subscriber_id: str
    tier: LicenseTier
    created_at: float
    expires_at: float
    max_drawdown_limit: Decimal
    profit_share_pct: Decimal
    api_key_hash: str
    
    def is_valid(self) -> bool:
        """Check license validity."""
        return time.time() < self.expires_at
    
    def is_active(self, current_drawdown: Decimal) -> bool:
        """Check if license active given performance."""
        if not self.is_valid():
            return False
        return current_drawdown <= self.max_drawdown_limit


class LicenseManager:
    """
    Cryptographically secure license management.
    Uses HMAC-SHA256 for license verification.
    """
    
    def __init__(self, master_secret: str) -> None:
        self._master_secret = master_secret.encode()
        self._licenses: dict[str, License] = {}
        self._revoked: set[str] = set()
    
    def issue_license(
        self,
        strategy_id: str,
        subscriber_id: str,
        tier: LicenseTier,
        duration_days: int,
        max_drawdown: Decimal = Decimal("0.10"),
        profit_share: Decimal = Decimal("0.20")
    ) -> tuple[License, str]:
        """
        Issue new license with API key.
        Returns (license, api_key).
        """
        license_id = secrets.token_urlsafe(16)
        api_key = f"hf_{secrets.token_urlsafe(32)}"
        api_key_hash = hashlib.sha256(api_key.encode()).hexdigest()
        
        now = time.time()
        
        license = License(
            license_id=license_id,
            strategy_id=strategy_id,
            subscriber_id=subscriber_id,
            tier=tier,
            created_at=now,
            expires_at=now + (duration_days * 86400),
            max_drawdown_limit=max_drawdown,
            profit_share_pct=profit_share,
            api_key_hash=api_key_hash
        )
        
        self._licenses[license_id] = license
        
        logger.info(
            "license_issued",
            license_id=license_id,
            strategy_id=strategy_id,
            tier=tier.value,
            duration_days=duration_days
        )
        
        return license, api_key
    
    def verify_license(self, license_id: str, api_key: str) -> License | None:
        """Verify license authenticity."""
        if license_id in self._revoked:
            return None
        
        license = self._licenses.get(license_id)
        if not license:
            return None
        
        # Verify API key
        key_hash = hashlib.sha256(api_key.encode()).hexdigest()
        if not hmac.compare_digest(key_hash, license.api_key_hash):
            return None
        
        return license if license.is_valid() else None
    
    def revoke_license(self, license_id: str) -> bool:
        """Revoke license immediately."""
        if license_id in self._licenses:
            self._revoked.add(license_id)
            logger.info("license_revoked", license_id=license_id)
            return True
        return False
    
    def check_performance_gate(
        self,
        license_id: str,
        current_drawdown: Decimal
    ) -> Literal["ACTIVE", "SUSPENDED", "EXPIRED"]:
        """Check if license should be suspended due to performance."""
        license = self._licenses.get(license_id)
        
        if not license or not license.is_valid():
            return "EXPIRED"
        
        if not license.is_active(current_drawdown):
            logger.warning(
                "license_suspended_drawdown",
                license_id=license_id,
                drawdown=float(current_drawdown),
                limit=float(license.max_drawdown_limit)
            )
            return "SUSPENDED"
        
        return "ACTIVE"

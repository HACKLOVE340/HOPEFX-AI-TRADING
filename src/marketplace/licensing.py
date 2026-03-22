"""
Strategy licensing and intellectual property protection.
"""

import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum

import jwt


class LicenseType(Enum):
    TRIAL = "trial"
    BASIC = "basic"
    PRO = "pro"
    ENTERPRISE = "enterprise"


@dataclass
class License:
    license_id: str
    strategy_id: str
    user_id: str
    license_type: LicenseType
    created_at: datetime
    expires_at: datetime
    max_accounts: int
    features: list[str]
    signature: str


class LicenseManager:
    """
    Cryptographic license management for strategy protection.
    """
    
    def __init__(self, secret_key: str | None = None):
        self.secret_key = secret_key or secrets.token_hex(32)
    
    def issue_license(
        self,
        strategy_id: str,
        user_id: str,
        license_type: LicenseType,
        duration_days: int = 30,
        max_accounts: int = 1
    ) -> License:
        """Issue new license."""
        license_id = secrets.token_urlsafe(16)
        
        now = datetime.now(timezone.utc)
        expires = now + timedelta(days=duration_days)
        
        # Determine features by tier
        features = self._get_features(license_type)
        
        # Create license payload
        payload = {
            "lid": license_id,
            "sid": strategy_id,
            "uid": user_id,
            "typ": license_type.value,
            "iat": now.isoformat(),
            "exp": expires.isoformat(),
            "mac": max_accounts,
            "ftr": features
        }
        
        # Sign license
        signature = jwt.encode(payload, self.secret_key, algorithm="HS256")
        
        return License(
            license_id=license_id,
            strategy_id=strategy_id,
            user_id=user_id,
            license_type=license_type,
            created_at=now,
            expires_at=expires,
            max_accounts=max_accounts,
            features=features,
            signature=signature
        )
    
    def verify_license(self, license: License) -> bool:
        """Verify license signature and expiration."""
        try:
            payload = jwt.decode(
                license.signature,
                self.secret_key,
                algorithms=["HS256"]
            )
            
            # Check expiration
            exp = datetime.fromisoformat(payload["exp"])
            if exp < datetime.now(timezone.utc):
                return False
            
            return True
            
        except jwt.ExpiredSignatureError:
            return False
        except jwt.InvalidTokenError:
            return False
    
    def _get_features(self, license_type: LicenseType) -> list[str]:
        """Get features for license tier."""
        features = {
            LicenseType.TRIAL: ["backtest", "paper_trade"],
            LicenseType.BASIC: ["backtest", "paper_trade", "live_trade"],
            LicenseType.PRO: ["backtest", "paper_trade", "live_trade", "advanced_ml", "api_access"],
            LicenseType.ENTERPRISE: ["all_features", "white_label", "custom_development"]
        }
        return features.get(license_type, [])

# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
Trader Profiles Management
- Profile creation and updates
- Performance statistics
- Verification system
"""

from dataclasses import dataclass
from datetime import datetime, timezone
UTC = timezone.utc


@dataclass
class TraderProfile:
    """Complete trader profile"""

    trader_id: str
    username: str
    email: str
    bio: str = ""
    avatar_url: str | None = None
    website: str | None = None
    verified: bool = False
    verification_date: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    # Statistics
    total_followers: int = 0
    total_following: int = 0
    total_trades: int = 0
    win_rate: float = 0.0
    total_pnl: float = 0.0
    avg_win: float = 0.0
    avg_loss: float = 0.0
    sharpe_ratio: float = 0.0

    def to_dict(self) -> dict:
        """Convert to dictionary"""
        return {
            "trader_id": self.trader_id,
            "username": self.username,
            "email": self.email,
            "bio": self.bio,
            "avatar_url": self.avatar_url,
            "website": self.website,
            "verified": self.verified,
            "verification_date": self.verification_date.isoformat() if self.verification_date else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "total_followers": self.total_followers,
            "total_following": self.total_following,
            "total_trades": self.total_trades,
            "win_rate": self.win_rate,
            "total_pnl": self.total_pnl,
            "avg_win": self.avg_win,
            "avg_loss": self.avg_loss,
            "sharpe_ratio": self.sharpe_ratio,
        }


class TraderProfileManager:
    """Manage trader profiles"""

    def __init__(self):
        self.profiles: dict[str, TraderProfile] = {}

    def create_profile(self, trader_id: str, username: str, email: str) -> TraderProfile:
        """Create new trader profile"""
        profile = TraderProfile(
            trader_id=trader_id,
            username=username,
            email=email,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        self.profiles[trader_id] = profile
        return profile

    def update_profile(self, trader_id: str, **kwargs) -> TraderProfile | None:
        """Update trader profile"""
        if trader_id not in self.profiles:
            return None

        profile = self.profiles[trader_id]
        for key, value in kwargs.items():
            if hasattr(profile, key):
                setattr(profile, key, value)

        profile.updated_at = datetime.now(UTC)
        return profile

    def get_profile(self, trader_id: str) -> TraderProfile | None:
        """Get trader profile"""
        return self.profiles.get(trader_id)

    def list_profiles(self, public_only: bool = False) -> list:
        """Return all profiles, optionally filtered to public/opted-in traders."""
        profiles = list(self.profiles.values())
        if public_only:
            profiles = [p for p in profiles if getattr(p, "is_public", True)]
        return profiles

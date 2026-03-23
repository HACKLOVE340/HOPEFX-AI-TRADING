from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import List, Optional

import structlog

from hopefx.database.models import User, LeaderboardEntry, Trade

logger = structlog.get_logger()


class LeaderboardEngine:
    """Real-time leaderboard with multiple ranking algorithms."""

    def __init__(self) -> None:
        self._cache: dict = {}
        self._last_update: Optional[datetime] = None
        self._update_interval = timedelta(minutes=5)

    async def calculate_rankings(
        self, period: str = "monthly"
    ) -> List[LeaderboardEntry]:
        """Calculate trader rankings for period."""
        # Complex scoring algorithm combining multiple factors

        # Query all active strategies with performance data
        # Calculate composite score
        # Rank and store

        return []

    def _calculate_social_score(
        self, followers: int, copiers: int, copied_volume: Decimal
    ) -> Decimal:
        """Calculate social influence score."""
        # Log-scaled social metrics
        follower_score = (
            Decimal(str(min(followers, 10000))).ln() if followers > 0 else Decimal("0")
        )
        copier_score = (
            Decimal(str(min(copiers, 1000))).ln() if copiers > 0 else Decimal("0")
        )
        volume_score = (
            (copied_volume / Decimal("1000000")).ln()
            if copied_volume > 0
            else Decimal("0")
        )

        return (follower_score + copier_score + volume_score) / Decimal("3")

    async def get_leaderboard(
        self,
        period: str = "monthly",
        limit: int = 100,
        strategy_type: Optional[str] = None,
    ) -> List[dict]:
        """Get cached or fresh leaderboard."""

        if self._should_refresh():
            await self.calculate_rankings(period)

        # Return from cache or database
        return []

    def _should_refresh(self) -> bool:
        """Check if cache needs refresh."""
        if not self._last_update:
            return True
        return datetime.now(timezone.utc) - self._last_update > self._update_interval

    async def get_trader_profile(self, user_id: str) -> Optional[dict]:
        """Get public trader profile with stats."""
        # Combine user profile, strategy performance, and social metrics
        pass

    async def follow_trader(self, follower_id: str, leader_id: str) -> bool:
        """Follow a trader (social, not copy trading)."""
        # Add to followers list
        # Update social metrics
        pass

    async def unfollow_trader(self, follower_id: str, leader_id: str) -> bool:
        """Unfollow a trader."""
        pass


class SocialFeed:
    """Real-time social feed for trading activity."""

    def __init__(self) -> None:
        self._subscribers: dict = {}

    async def publish_trade(self, trade: Trade, user: User) -> None:
        """Publish trade to followers' feeds."""
        # Only if user has public trading enabled
        # Broadcast to WebSocket subscribers
        pass

    async def publish_milestone(self, user_id: str, milestone: str) -> None:
        """Publish achievement milestone."""
        # e.g., "Passed FTMO Challenge", "100th Winning Trade"
        pass


# Global instances
leaderboard = LeaderboardEngine()
social_feed = SocialFeed()

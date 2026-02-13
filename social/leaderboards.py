"""
Leaderboard System

Ranks users based on performance metrics.
"""

from typing import List, Dict
from decimal import Decimal


class LeaderboardEntry:
    """Entry in a leaderboard"""
    def __init__(self, user_id: str, score: Decimal, rank: int = 0):
        self.user_id = user_id
        self.score = score
        self.rank = rank


class LeaderboardManager:
    """Manages performance leaderboards"""

    def __init__(self):
        self.leaderboards: Dict[str, List[LeaderboardEntry]] = {}

    def update_leaderboard(
        self,
        category: str,
        user_id: str,
        score: Decimal
    ) -> None:
        """Update leaderboard for a category"""
        if category not in self.leaderboards:
            self.leaderboards[category] = []

        # Find or create entry
        entry = None
        for e in self.leaderboards[category]:
            if e.user_id == user_id:
                entry = e
                break

        if entry is None:
            entry = LeaderboardEntry(user_id, score)
            self.leaderboards[category].append(entry)
        else:
            entry.score = score

        # Sort and update ranks
        self.leaderboards[category].sort(key=lambda x: x.score, reverse=True)
        for rank, e in enumerate(self.leaderboards[category], start=1):
            e.rank = rank

    def get_leaderboard(
        self,
        category: str,
        limit: int = 50
    ) -> List[LeaderboardEntry]:
        """Get top entries from a leaderboard"""
        return self.leaderboards.get(category, [])[:limit]

    def get_user_rank(self, category: str, user_id: str) -> int:
        """Get user's rank in a category"""
        leaderboard = self.leaderboards.get(category, [])
        for entry in leaderboard:
            if entry.user_id == user_id:
                return entry.rank
        return 0

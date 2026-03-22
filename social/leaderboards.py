"""Leaderboard management."""

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Dict, List, Optional


@dataclass
class LeaderboardEntry:
    user_id: str
    score: Decimal
    rank: int = 0


class LeaderboardManager:
    """Manages ranked leaderboards by category."""

    def __init__(self):
        # category -> {user_id -> LeaderboardEntry}
        self._data: Dict[str, Dict[str, LeaderboardEntry]] = {}

    @property
    def leaderboards(self) -> Dict[str, List[LeaderboardEntry]]:
        """Return sorted leaderboard lists keyed by category."""
        return {cat: self._sorted(cat) for cat in self._data}

    def _sorted(self, category: str) -> List[LeaderboardEntry]:
        entries = sorted(self._data[category].values(), key=lambda e: e.score, reverse=True)
        for i, e in enumerate(entries, 1):
            e.rank = i
        return entries

    def update_leaderboard(self, category: str, user_id: str, score: Decimal) -> None:
        if category not in self._data:
            self._data[category] = {}
        entry = self._data[category].get(user_id)
        if entry:
            entry.score = score
        else:
            self._data[category][user_id] = LeaderboardEntry(user_id=user_id, score=score)

    def get_leaderboard(self, category: str, limit: Optional[int] = None) -> List[LeaderboardEntry]:
        if category not in self._data:
            return []
        entries = self._sorted(category)
        return entries[:limit] if limit else entries

    def get_user_rank(self, category: str, user_id: str) -> int:
        entries = self.get_leaderboard(category)
        for e in entries:
            if e.user_id == user_id:
                return e.rank
        return 0


# Alias
PerformanceLeaderboard = LeaderboardManager

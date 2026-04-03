# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""Leaderboard management."""

from dataclasses import dataclass
from decimal import Decimal


@dataclass
class LeaderboardEntry:
    user_id: str
    score: Decimal
    rank: int = 0


class LeaderboardManager:
    """Manages ranked leaderboards by category."""

    def __init__(self):
        # category -> {user_id -> LeaderboardEntry}
        self._data: dict[str, dict[str, LeaderboardEntry]] = {}

    @property
    def leaderboards(self) -> dict[str, list[LeaderboardEntry]]:
        """Return sorted leaderboard lists keyed by category."""
        return {cat: self._sorted(cat) for cat in self._data}

    def _sorted(self, category: str) -> list[LeaderboardEntry]:
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

    def get_leaderboard(self, category: str, limit: int | None = None) -> list[LeaderboardEntry]:
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

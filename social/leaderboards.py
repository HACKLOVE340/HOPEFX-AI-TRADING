# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""Leaderboard management — Redis sorted sets with in-process fallback."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal

logger = logging.getLogger(__name__)


@dataclass
class LeaderboardEntry:
    user_id: str
    score: Decimal
    rank: int = 0


def _get_sync_redis():
    try:
        from cache.redis_pool import get_sync_client

        return get_sync_client()
    except Exception:
        return None


class LeaderboardManager:
    """
    Manages ranked leaderboards by category.

    Scores are stored in Redis sorted sets (key: leaderboard:{category})
    so rankings are shared across replicas and survive restarts.
    Falls back to an in-process dict when Redis is unavailable.
    """

    _REDIS_KEY_PREFIX = "leaderboard"

    def __init__(self):
        # In-process fallback: category -> {user_id -> LeaderboardEntry}
        self._data: dict[str, dict[str, LeaderboardEntry]] = {}

    def _redis_key(self, category: str) -> str:
        return f"{self._REDIS_KEY_PREFIX}:{category}"

    @property
    def leaderboards(self) -> dict[str, list[LeaderboardEntry]]:
        """Return sorted leaderboard lists keyed by category."""
        r = _get_sync_redis()
        if r:
            try:
                # Discover all leaderboard keys
                keys = r.keys(f"{self._REDIS_KEY_PREFIX}:*")
                result = {}
                for k in keys:
                    cat = k.decode().split(":", 1)[1] if isinstance(k, bytes) else k.split(":", 1)[1]
                    result[cat] = self.get_leaderboard(cat)
                return result
            except Exception as _e:
                logger.debug("Redis leaderboards scan failed: %s", _e)
        return {cat: self._sorted_fallback(cat) for cat in self._data}

    def _sorted_fallback(self, category: str) -> list[LeaderboardEntry]:
        entries = sorted(self._data.get(category, {}).values(), key=lambda e: e.score, reverse=True)
        for i, e in enumerate(entries, 1):
            e.rank = i
        return entries

    def clear(self, category: str | None = None) -> None:
        """Clear one category, or every category when *category* is None.

        Clears **both** backends. Constructing a new ``LeaderboardManager`` only
        resets the in-process fallback dict; the Redis sorted set behind
        ``leaderboard:{category}`` outlives the instance, the process and the
        test run. That is what made the smoke tests for this class pass on a
        machine with no Redis and fail on one with it — backwards, since Redis is
        the path production takes.

        Scoped to this class's own key prefix, never ``FLUSHDB``: this instance
        may share Redis with the rate limiter, the kill-switch latch and the
        idempotency store.

        Useful beyond tests — resetting a leaderboard season is a real operation.
        """
        if category is None:
            self._data.clear()
        else:
            self._data.pop(category, None)

        r = _get_sync_redis()
        if not r:
            return
        try:
            if category is None:
                for key in r.scan_iter(match=f"{self._REDIS_KEY_PREFIX}:*", count=500):
                    r.delete(key)
            else:
                r.delete(self._redis_key(category))
        except Exception as exc:
            logger.debug("Redis leaderboard clear failed: %s", exc)

    def update_leaderboard(self, category: str, user_id: str, score: Decimal) -> None:
        r = _get_sync_redis()
        if r:
            try:
                r.zadd(self._redis_key(category), {user_id: float(score)})
                return
            except Exception as _e:
                logger.debug("Redis leaderboard zadd failed: %s", _e)
        # Fallback
        if category not in self._data:
            self._data[category] = {}
        entry = self._data[category].get(user_id)
        if entry:
            entry.score = score
        else:
            self._data[category][user_id] = LeaderboardEntry(user_id=user_id, score=score)

    def get_leaderboard(self, category: str, limit: int | None = None) -> list[LeaderboardEntry]:
        r = _get_sync_redis()
        if r:
            try:
                # zrevrange returns members highest-score first
                count = limit or -1
                members = r.zrevrange(self._redis_key(category), 0, count - 1 if count != -1 else -1, withscores=True)
                entries = []
                for rank, (member, score) in enumerate(members, 1):
                    uid = member.decode() if isinstance(member, bytes) else member
                    entries.append(LeaderboardEntry(user_id=uid, score=Decimal(str(score)), rank=rank))
                return entries
            except Exception as _e:
                logger.debug("Redis leaderboard zrevrange failed: %s", _e)
        entries = self._sorted_fallback(category)
        return entries[:limit] if limit else entries

    def get_user_rank(self, category: str, user_id: str) -> int:
        r = _get_sync_redis()
        if r:
            try:
                # zrevrank returns 0-based rank (highest score = rank 0)
                rank = r.zrevrank(self._redis_key(category), user_id)
                return (rank + 1) if rank is not None else 0
            except Exception as _e:
                logger.debug("Redis leaderboard zrevrank failed: %s", _e)
        entries = self.get_leaderboard(category)
        for e in entries:
            if e.user_id == user_id:
                return e.rank
        return 0


# Alias
PerformanceLeaderboard = LeaderboardManager

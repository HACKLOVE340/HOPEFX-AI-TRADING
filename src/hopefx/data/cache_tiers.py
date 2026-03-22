"""Multi-tier caching strategy."""

from __future__ import annotations

import asyncio
from typing import Optional, Any
from dataclasses import dataclass

import aioredis


@dataclass
class CacheItem:
    value: Any
    tier: int  # 0=memory, 1=redis, 2=disk
    expires_at: float


class MultiTierCache:
    """L1 (memory) -> L2 (Redis) -> L3 (Disk) cache."""

    def __init__(self) -> None:
        self._l1: dict = {}  # In-memory
        self._l2: Optional[aioredis.Redis] = None  # Redis
        self._l3_path = "/tmp/hopefx_cache"  # Disk
        self._hit_stats = {"l1": 0, "l2": 0, "l3": 0, "miss": 0}

    async def get(self, key: str) -> Optional[Any]:
        """Get with tier promotion."""
        # L1 check
        if key in self._l1:
            self._hit_stats["l1"] += 1
            return self._l1[key].value

        # L2 check
        if self._l2:
            value = await self._l2.get(key)
            if value:
                self._hit_stats["l2"] += 1
                self._promote_to_l1(key, value)
                return value

        # L3 check
        value = await self._get_from_disk(key)
        if value:
            self._hit_stats["l3"] += 1
            await self._promote_to_l2(key, value)
            return value

        self._hit_stats["miss"] += 1
        return None

    async def set(
        self,
        key: str,
        value: Any,
        ttl_l1: int = 60,
        ttl_l2: int = 300,
        ttl_l3: int = 3600
    ) -> None:
        """Set across all tiers."""
        now = asyncio.get_event_loop().time()
        
        # L1
        self._l1[key] = CacheItem(value, 0, now + ttl_l1)
        
        # L2
        if self._l2:
            await self._l2.setex(key, ttl_l2, value)
        
        # L3
        await self._set_to_disk(key, value, ttl_l3)

    def _promote_to_l1(self, key: str, value: Any) -> None:
        """Promote from lower tier to L1."""
        self._l1[key] = CacheItem(value, 0, asyncio.get_event_loop().time() + 60)

    async def _promote_to_l2(self, key: str, value: Any) -> None:
        """Promote from L3 to L2."""
        if self._l2:
            await self._l2.setex(key, 300, value)

    def get_stats(self) -> dict:
        """Return cache statistics."""
        total = sum(self._hit_stats.values())
        if total == 0:
            return self._hit_stats
        
        return {
            **self._hit_stats,
            "hit_rate": (total - self._hit_stats["miss"]) / total,
            "tier_distribution": {
                k: v / total for k, v in self._hit_stats.items() if k != "miss"
            }
        }

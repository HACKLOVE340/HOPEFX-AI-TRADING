"""
Redis cache with connection pooling and circuit breaker.
"""

import asyncio
from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator

try:
    import aioredis
    from aioredis import Redis
    _AIOREDIS_OK = True
except Exception:
    aioredis = None  # type: ignore
    Redis = object   # type: ignore
    _AIOREDIS_OK = False

try:
    from circuitbreaker import circuit
except ImportError:
    def circuit(*a, **kw):  # type: ignore
        def decorator(fn): return fn
        return decorator

from src.core.config import settings
from src.core.exceptions import CacheError
from src.core.logging_config import get_logger

logger = get_logger(__name__)


class RedisCache:
    """Production Redis cache with health checks."""
    
    def __init__(self) -> None:
        self._pool: Redis | None = None
        self._lock = asyncio.Lock()
    
    async def connect(self) -> None:
        """Initialize Redis connection."""
        async with self._lock:
            if self._pool is not None:
                return
            
            try:
                self._pool = aioredis.from_url(
                    settings.redis.url,
                    socket_connect_timeout=settings.redis.socket_connect_timeout,
                    socket_keepalive=settings.redis.socket_keepalive,
                    health_check_interval=settings.redis.health_check_interval,
                    retry_on_timeout=settings.redis.retry_on_timeout,
                    decode_responses=True,
                )
                await self._pool.ping()
                logger.info("Redis connected")
            except Exception as e:
                raise CacheError(f"Redis connection failed: {e}")
    
    async def disconnect(self) -> None:
        """Close Redis connection."""
        if self._pool:
            await self._pool.close()
            self._pool = None
            logger.info("Redis disconnected")
    
    @property
    def client(self) -> Redis:
        """Get Redis client."""
        if self._pool is None:
            raise CacheError("Redis not connected")
        return self._pool
    
    @circuit(failure_threshold=5, recovery_timeout=60)
    async def get(self, key: str) -> Any:
        """Get value from cache."""
        try:
            value = await self.client.get(key)
            return value
        except Exception as e:
            logger.error(f"Cache get error: {e}")
            raise CacheError(f"Failed to get {key}: {e}")
    
    @circuit(failure_threshold=5, recovery_timeout=60)
    async def set(
        self,
        key: str,
        value: Any,
        ttl: int | None = None,
        nx: bool = False
    ) -> bool:
        """Set value in cache."""
        try:
            return await self.client.set(key, value, ex=ttl, nx=nx)
        except Exception as e:
            logger.error(f"Cache set error: {e}")
            raise CacheError(f"Failed to set {key}: {e}")
    
    @circuit(failure_threshold=5, recovery_timeout=60)
    async def delete(self, key: str) -> int:
        """Delete key from cache."""
        try:
            return await self.client.delete(key)
        except Exception as e:
            logger.error(f"Cache delete error: {e}")
            raise CacheError(f"Failed to delete {key}: {e}")
    
    async def health_check(self) -> bool:
        """Check Redis health."""
        try:
            await self.client.ping()
            return True
        except Exception:
            return False


# Global cache instance
_cache: RedisCache | None = None


async def get_cache() -> RedisCache:
    """Get or initialize cache."""
    global _cache
    if _cache is None:
        _cache = RedisCache()
        await _cache.connect()
    return _cache


async def close_cache() -> None:
    """Close global cache."""
    global _cache
    if _cache:
        await _cache.disconnect()
        _cache = None

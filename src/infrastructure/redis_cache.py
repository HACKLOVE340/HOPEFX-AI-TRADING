"""
Async Redis cache with circuit breaker.

Serialization uses JSON (not pickle) to prevent remote code execution
if Redis is compromised.
"""
import json
from typing import Optional, Any, Union
import asyncio

import aioredis
import structlog

from src.config.settings import get_settings
from src.core.circuit_breaker import CircuitBreaker

logger = structlog.get_logger()
settings = get_settings()


class RedisCache:
    """
    Production Redis cache with serialization and circuit breaker.
    """
    
    def __init__(self):
        self._redis: Optional[aioredis.Redis] = None
        self._circuit_breaker = CircuitBreaker(
            failure_threshold=3,
            recovery_timeout=30,
            name="redis_cache"
        )
        self._default_ttl = 3600  # 1 hour
        
    async def connect(self) -> None:
        """Establish Redis connection."""
        try:
            redis_url = f"redis://{settings.redis.host}:{settings.redis.port}/{settings.redis.db}"
            if settings.redis.password:
                redis_url = f"redis://:{settings.redis.password.get_secret_value()}@{settings.redis.host}:{settings.redis.port}/{settings.redis.db}"
            
            self._redis = aioredis.from_url(
                redis_url,
                encoding="utf-8",
                decode_responses=False
            )
            await self._redis.ping()
            self._circuit_breaker.record_success()
            logger.info("redis_connected", host=settings.redis.host)
        except Exception as e:
            self._circuit_breaker.record_failure()
            logger.error("redis_connection_failed", error=str(e))
            raise
    
    async def disconnect(self) -> None:
        """Close Redis connection."""
        if self._redis:
            await self._redis.close()
            logger.info("redis_disconnected")
    
    async def get(self, key: str) -> Optional[Any]:
        """Get value from cache."""
        if not await self._circuit_breaker.can_execute():
            return None
        
        try:
            data = await self._redis.get(key)
            if data is None:
                return None
            
            self._circuit_breaker.record_success()
            return json.loads(data)
        except Exception as e:
            self._circuit_breaker.record_failure()
            logger.error("redis_get_failed", key=key, error=str(e))
            return None

    async def set(self,
                  key: str,
                  value: Any,
                  ttl: Optional[int] = None,
                  nx: bool = False) -> bool:
        """Set value in cache."""
        if not await self._circuit_breaker.can_execute():
            return False

        try:
            serialized = json.dumps(value, default=str)
            result = await self._redis.set(
                key,
                serialized,
                ex=ttl or self._default_ttl,
                nx=nx,
            )
            self._circuit_breaker.record_success()
            return bool(result)
        except Exception as e:
            self._circuit_breaker.record_failure()
            logger.error("redis_set_failed", key=key, error=str(e))
            return False
    
    async def delete(self, key: str) -> bool:
        """Delete key from cache."""
        if not await self._circuit_breaker.can_execute():
            return False
        
        try:
            result = await self._redis.delete(key)
            self._circuit_breaker.record_success()
            return result > 0
        except Exception as e:
            self._circuit_breaker.record_failure()
            logger.error("redis_delete_failed", key=key, error=str(e))
            return False
    
    async def exists(self, key: str) -> bool:
        """Check if key exists."""
        if not await self._circuit_breaker.can_execute():
            return False
        
        try:
            result = await self._redis.exists(key)
            self._circuit_breaker.record_success()
            return result > 0
        except Exception as e:
            self._circuit_breaker.record_failure()
            return False
    
    async def get_or_set(self, 
                         key: str, 
                         factory: callable, 
                         ttl: Optional[int] = None) -> Any:
        """Get from cache or compute and store."""
        cached = await self.get(key)
        if cached is not None:
            return cached
        
        value = await factory()
        await self.set(key, value, ttl)
        return value
    
    async def increment(self, key: str, amount: int = 1) -> Optional[int]:
        """Atomic increment."""
        if not await self._circuit_breaker.can_execute():
            return None
        
        try:
            result = await self._redis.incrby(key, amount)
            self._circuit_breaker.record_success()
            return result
        except Exception as e:
            self._circuit_breaker.record_failure()
            logger.error("redis_increment_failed", key=key, error=str(e))
            return None
    
    async def expire(self, key: str, seconds: int) -> bool:
        """Set expiration on key."""
        if not await self._circuit_breaker.can_execute():
            return False
        
        try:
            await self._redis.expire(key, seconds)
            self._circuit_breaker.record_success()
            return True
        except Exception as e:
            self._circuit_breaker.record_failure()
            return False

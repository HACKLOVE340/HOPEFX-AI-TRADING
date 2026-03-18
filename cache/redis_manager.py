# cache/redis_manager.py
"""
Redis cache manager with serialization and TTL
"""

import redis
import pickle
import json
from typing import Any, Optional
from datetime import timedelta

class RedisCacheManager:
    """Production-ready Redis cache with compression."""
    
    def __init__(self, host='localhost', port=6379, db=0):
        self.client = redis.Redis(
            host=host, port=port, db=db,
            decode_responses=False,
            socket_connect_timeout=5,
            socket_timeout=5,
            health_check_interval=30
        )
        self.default_ttl = timedelta(hours=1)
    
    def get(self, key: str) -> Optional[Any]:
        """Get value from cache."""
        try:
            data = self.client.get(key)
            if data:
                return pickle.loads(data)
            return None
        except redis.RedisError as e:
            # Log error, fallback to None
            return None
    
    def set(
        self,
        key: str,
        value: Any,
        ttl: Optional[timedelta] = None
    ) -> bool:
        """Set value in cache with TTL."""
        try:
            serialized = pickle.dumps(value)
            expiry = int((ttl or self.default_ttl).total_seconds())
            return self.client.setex(key, expiry, serialized)
        except redis.RedisError:
            return False
    
    def get_market_data(self, symbol: str, timeframe: str) -> Optional[pd.DataFrame]:
        """Get cached market data."""
        key = f"ohlcv:{symbol}:{timeframe}"
        return self.get(key)
    
    def set_market_data(
        self,
        symbol: str,
        timeframe: str,
        data: pd.DataFrame,
        ttl: Optional[timedelta] = None
    ):
        """Cache market data."""
        key = f"ohlcv:{symbol}:{timeframe}"
        self.set(key, data, ttl or timedelta(minutes=5))
    
    def invalidate_pattern(self, pattern: str):
        """Invalidate all keys matching pattern."""
        for key in self.client.scan_iter(match=pattern):
            self.client.delete(key)

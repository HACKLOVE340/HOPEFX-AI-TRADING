# cache/redis_manager.py
"""
Redis cache manager with JSON serialization and TTL.

Serialization uses JSON (not pickle) to prevent remote code execution
if Redis is compromised. pandas DataFrames are serialized via
DataFrame.to_json / pd.read_json.
"""

import json
import logging
from typing import Any, Optional
from datetime import timedelta

logger = logging.getLogger(__name__)

try:
    import redis
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False

try:
    import pandas as pd
    PANDAS_AVAILABLE = True
except ImportError:
    PANDAS_AVAILABLE = False


def _serialize(value: Any) -> bytes:
    """Serialize value to JSON bytes. DataFrames use orient='split'."""
    if PANDAS_AVAILABLE and isinstance(value, pd.DataFrame):
        payload = {"__type__": "dataframe", "data": value.to_json(orient="split")}
    elif PANDAS_AVAILABLE and isinstance(value, pd.Series):
        payload = {"__type__": "series", "data": value.to_json(orient="split")}
    else:
        payload = {"__type__": "json", "data": value}
    return json.dumps(payload, default=str).encode()


def _deserialize(raw: bytes) -> Any:
    """Deserialize JSON bytes back to Python object."""
    payload = json.loads(raw.decode())
    t = payload.get("__type__")
    if t == "dataframe" and PANDAS_AVAILABLE:
        return pd.read_json(payload["data"], orient="split")
    if t == "series" and PANDAS_AVAILABLE:
        return pd.read_json(payload["data"], orient="split", typ="series")
    return payload.get("data")


class RedisCacheManager:
    """Production-ready Redis cache with JSON serialization."""

    def __init__(self, host='localhost', port=6379, db=0):
        if not REDIS_AVAILABLE:
            raise ImportError("redis package required: pip install redis")
        self.client = redis.Redis(
            host=host, port=port, db=db,
            decode_responses=False,
            socket_connect_timeout=5,
            socket_timeout=5,
            health_check_interval=30,
        )
        self.default_ttl = timedelta(hours=1)

    def get(self, key: str) -> Optional[Any]:
        """Get value from cache."""
        try:
            data = self.client.get(key)
            if data:
                return _deserialize(data)
            return None
        except Exception as e:
            logger.warning("Redis get failed for key=%s: %s", key, e)
            return None

    def set(self, key: str, value: Any, ttl: Optional[timedelta] = None) -> bool:
        """Set value in cache with TTL."""
        try:
            serialized = _serialize(value)
            expiry = int((ttl or self.default_ttl).total_seconds())
            return bool(self.client.setex(key, expiry, serialized))
        except Exception as e:
            logger.warning("Redis set failed for key=%s: %s", key, e)
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

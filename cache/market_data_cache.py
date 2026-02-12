"""
Market Data Cache Module with Redis Integration

This module provides a robust caching system for market data including:
- OHLCV (Open, High, Low, Close, Volume) data
- Tick-level data
- Multi-timeframe support
- TTL (Time-To-Live) management
- Cache statistics and monitoring
"""

import json
import logging
import time
import threading
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, asdict
from enum import Enum

import redis
from redis import Redis
from redis.exceptions import ConnectionError, TimeoutError as RedisTimeoutError


# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class Timeframe(Enum):
    """Supported timeframes for market data"""
    ONE_MINUTE = "1m"
    FIVE_MINUTES = "5m"
    FIFTEEN_MINUTES = "15m"
    THIRTY_MINUTES = "30m"
    ONE_HOUR = "1h"
    FOUR_HOURS = "4h"
    ONE_DAY = "1d"
    ONE_WEEK = "1w"
    ONE_MONTH = "1M"


@dataclass
class OHLCVData:
    """OHLCV (Open, High, Low, Close, Volume) data structure"""
    timestamp: int
    open_price: float
    high_price: float
    low_price: float
    close_price: float
    volume: float
    
    def to_dict(self) -> Dict:
        """Convert OHLCV data to dictionary"""
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'OHLCVData':
        """Create OHLCV data from dictionary"""
        return cls(**data)


@dataclass
class CachedTickData:
    """Tick-level market data structure for caching"""
    timestamp: int
    price: float
    volume: float
    bid: float
    ask: float
    bid_volume: float
    ask_volume: float
    
    def to_dict(self) -> Dict:
        """Convert tick data to dictionary"""
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'CachedTickData':
        """Create tick data from dictionary"""
        return cls(**data)


@dataclass
class CacheStatistics:
    """Cache statistics data structure"""
    total_hits: int = 0
    total_misses: int = 0
    total_evictions: int = 0
    total_keys: int = 0
    memory_usage_bytes: int = 0
    
    @property
    def hit_rate(self) -> float:
        """Calculate cache hit rate"""
        total_requests = self.total_hits + self.total_misses
        if total_requests == 0:
            return 0.0
        return (self.total_hits / total_requests) * 100
    
    def to_dict(self) -> Dict:
        """Convert statistics to dictionary"""
        return {
            'total_hits': self.total_hits,
            'total_misses': self.total_misses,
            'total_evictions': self.total_evictions,
            'total_keys': self.total_keys,
            'memory_usage_bytes': self.memory_usage_bytes,
            'hit_rate_percent': round(self.hit_rate, 2)
        }


class MarketDataCache:
    """
    Redis-based cache for market data with multi-timeframe support
    """
    
    # Default TTL values (in seconds)
    DEFAULT_TTL = {
        Timeframe.ONE_MINUTE: 3600,  # 1 hour
        Timeframe.FIVE_MINUTES: 7200,  # 2 hours
        Timeframe.FIFTEEN_MINUTES: 14400,  # 4 hours
        Timeframe.THIRTY_MINUTES: 28800,  # 8 hours
        Timeframe.ONE_HOUR: 86400,  # 1 day
        Timeframe.FOUR_HOURS: 172800,  # 2 days
        Timeframe.ONE_DAY: 604800,  # 1 week
        Timeframe.ONE_WEEK: 1209600,  # 2 weeks
        Timeframe.ONE_MONTH: 2592000,  # 30 days
    }
    
    def __init__(
        self,
        host: str = 'localhost',
        port: int = 6379,
        db: int = 0,
        password: Optional[str] = None,
        socket_timeout: int = 5,
        socket_connect_timeout: int = 5,
        decode_responses: bool = True,
        max_retries: int = 3,
        retry_delay: float = 1.0
    ):
        """
        Initialize Redis cache connection
        
        Args:
            host: Redis server hostname
            port: Redis server port
            db: Redis database number
            password: Redis password (if required)
            socket_timeout: Socket timeout in seconds
            socket_connect_timeout: Connection timeout in seconds
            decode_responses: Decode responses as strings
            max_retries: Maximum number of connection retries
            retry_delay: Delay between retries in seconds
        """
        self.host = host
        self.port = port
        self.db = db
        self.decode_responses = decode_responses
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        
        # Try to connect with retries
        self.redis_client = self._connect_with_retry(
            host=host,
            port=port,
            db=db,
            password=password,
            socket_timeout=socket_timeout,
            socket_connect_timeout=socket_connect_timeout,
            decode_responses=decode_responses
        )
        
        # Statistics tracking with thread safety
        self.stats = CacheStatistics()
        self._stats_lock = threading.Lock()
    
    def _connect_with_retry(
        self,
        host: str,
        port: int,
        db: int,
        password: Optional[str],
        socket_timeout: int,
        socket_connect_timeout: int,
        decode_responses: bool
    ) -> Redis:
        """
        Connect to Redis with retry logic
        
        Returns:
            Connected Redis client
            
        Raises:
            ConnectionError: If all connection attempts fail
        """
        last_error = None
        
        for attempt in range(1, self.max_retries + 1):
            try:
                client = redis.Redis(
                    host=host,
                    port=port,
                    db=db,
                    password=password,
                    socket_timeout=socket_timeout,
                    socket_connect_timeout=socket_connect_timeout,
                    decode_responses=decode_responses
                )
                # Test connection
                client.ping()
                logger.info(f"Connected to Redis at {host}:{port} (attempt {attempt})")
                return client
            except (ConnectionError, RedisTimeoutError) as e:
                last_error = e
                if attempt < self.max_retries:
                    logger.warning(
                        f"Redis connection attempt {attempt}/{self.max_retries} failed: {e}. "
                        f"Retrying in {self.retry_delay}s..."
                    )
                    time.sleep(self.retry_delay)
                else:
                    logger.error(
                        f"Failed to connect to Redis after {self.max_retries} attempts: {e}"
                    )
        
        raise ConnectionError(f"Could not connect to Redis: {last_error}")
    def _build_key(
        self,
        symbol: str,
        timeframe: Timeframe,
        data_type: str
    ) -> str:
        """Build cache key"""
        return f"market_data:{symbol}:{timeframe.value}:{data_type}"
    
    def _build_tick_key(self, symbol: str) -> str:
        """Build tick data cache key"""
        return f"tick_data:{symbol}"
    
    # OHLCV Operations
    def cache_ohlcv(
        self,
        symbol: str,
        timeframe: Timeframe,
        ohlcv_data: List[OHLCVData],
        ttl: Optional[int] = None
    ) -> bool:
        """
        Cache OHLCV data
        
        Args:
            symbol: Trading symbol
            timeframe: Timeframe for the data
            ohlcv_data: List of OHLCV data points
            ttl: Time-to-live in seconds (uses default if None)
        
        Returns:
            True if caching succeeded, False otherwise
        """
        try:
            key = self._build_key(symbol, timeframe, "ohlcv")
            ttl = ttl or self.DEFAULT_TTL.get(timeframe, 3600)
            
            # Serialize data
            data_list = [asdict(candle) for candle in ohlcv_data]
            cached_data = {
                'data': data_list,
                'cached_at': datetime.utcnow().isoformat(),
                'expiry': (datetime.utcnow() + timedelta(seconds=ttl)).isoformat()
            }
            
            # Store in Redis with TTL
            self.redis_client.setex(
                key,
                ttl,
                json.dumps(cached_data)
            )
            
            logger.debug(f"Cached OHLCV data for {symbol} ({timeframe.value})")
            return True
            
        except Exception as e:
            logger.error(f"Error caching OHLCV data: {e}")
            return False
    
    def get_ohlcv(
        self,
        symbol: str,
        timeframe: Timeframe
    ) -> Optional[List[OHLCVData]]:
        """
        Retrieve OHLCV data from cache
        
        Args:
            symbol: Trading symbol
            timeframe: Timeframe for the data
        
        Returns:
            List of OHLCV data or None if not found
        """
        try:
            key = self._build_key(symbol, timeframe, "ohlcv")
            cached = self.redis_client.get(key)
            
            if cached:
                with self._stats_lock:
                    self.stats.total_hits += 1
                data = json.loads(cached)
                return [OHLCVData.from_dict(item) for item in data['data']]
            else:
                with self._stats_lock:
                    self.stats.total_misses += 1
                return None
                
        except Exception as e:
            logger.error(f"Error retrieving OHLCV data: {e}")
            with self._stats_lock:
                self.stats.total_misses += 1
            return None
    
    def append_ohlcv(
        self,
        symbol: str,
        timeframe: Timeframe,
        ohlcv_data: OHLCVData,
        max_size: int = 1000,
        ttl: Optional[int] = None
    ) -> bool:
        """
        Append OHLCV data to existing cache
        
        Args:
            symbol: Trading symbol
            timeframe: Timeframe for the data
            ohlcv_data: Single OHLCV data point
            max_size: Maximum number of candles to keep
            ttl: Time-to-live in seconds
        
        Returns:
            True if append succeeded, False otherwise
        """
        try:
            key = self._build_key(symbol, timeframe, "ohlcv")
            ttl = ttl or self.DEFAULT_TTL.get(timeframe, 3600)
            
            # Get existing data
            existing = self.redis_client.get(key)
            if existing:
                data = json.loads(existing)
                data_list = data['data']
            else:
                data_list = []
            
            # Append new data
            data_list.append(asdict(ohlcv_data))
            
            # Keep only recent data
            if len(data_list) > max_size:
                data_list = data_list[-max_size:]
            
            # Update cache
            cached_data = {
                'data': data_list,
                'cached_at': datetime.utcnow().isoformat(),
                'expiry': (datetime.utcnow() + timedelta(seconds=ttl)).isoformat()
            }
            
            self.redis_client.setex(key, ttl, json.dumps(cached_data))
            logger.debug(f"Appended OHLCV data for {symbol} ({timeframe.value})")
            return True
            
        except Exception as e:
            logger.error(f"Error appending OHLCV data: {e}")
            return False
    
    # Tick Data Operations
    def cache_tick(
        self,
        symbol: str,
        tick_data: CachedTickData,
        ttl: int = 300
    ) -> bool:
        """
        Cache tick-level data
        
        Args:
            symbol: Trading symbol
            tick_data: Tick data point
            ttl: Time-to-live in seconds
        
        Returns:
            True if caching succeeded, False otherwise
        """
        try:
            key = self._build_tick_key(symbol)
            
            cached_data = {
                'data': asdict(tick_data),
                'cached_at': datetime.utcnow().isoformat()
            }
            
            self.redis_client.setex(key, ttl, json.dumps(cached_data))
            logger.debug(f"Cached tick data for {symbol}")
            return True
            
        except Exception as e:
            logger.error(f"Error caching tick data: {e}")
            return False
    
    def get_tick(self, symbol: str) -> Optional[CachedTickData]:
        """
        Retrieve latest tick data from cache
        
        Args:
            symbol: Trading symbol
        
        Returns:
            CachedTickData or None if not found
        """
        try:
            key = self._build_tick_key(symbol)
            cached = self.redis_client.get(key)
            
            if cached:
                with self._stats_lock:
                    self.stats.total_hits += 1
                data = json.loads(cached)
                return CachedTickData.from_dict(data['data'])
            else:
                with self._stats_lock:
                    self.stats.total_misses += 1
                return None
                
        except Exception as e:
            logger.error(f"Error retrieving tick data: {e}")
            with self._stats_lock:
                self.stats.total_misses += 1
            return None
    
    def cache_ticks(
        self,
        symbol: str,
        tick_data_list: List[CachedTickData],
        ttl: int = 300,
        max_size: int = 100
    ) -> bool:
        """
        Cache multiple tick data points
        
        Args:
            symbol: Trading symbol
            tick_data_list: List of tick data points
            ttl: Time-to-live in seconds
            max_size: Maximum number of ticks to keep
        
        Returns:
            True if caching succeeded, False otherwise
        """
        try:
            key = self._build_tick_key(symbol)
            
            # Limit to max_size most recent ticks
            ticks_to_cache = tick_data_list[-max_size:] if len(tick_data_list) > max_size else tick_data_list
            
            cached_data = {
                'data': [asdict(tick) for tick in ticks_to_cache],
                'cached_at': datetime.utcnow().isoformat(),
                'count': len(ticks_to_cache)
            }
            
            self.redis_client.setex(key, ttl, json.dumps(cached_data))
            logger.debug(f"Cached {len(ticks_to_cache)} tick data points for {symbol}")
            return True
            
        except Exception as e:
            logger.error(f"Error caching tick data: {e}")
            return False
    
    def get_ticks(self, symbol: str) -> Optional[List[CachedTickData]]:
        """
        Retrieve cached tick data
        
        Args:
            symbol: Trading symbol
        
        Returns:
            List of CachedTickData or None if not found
        """
        try:
            key = self._build_tick_key(symbol)
            cached = self.redis_client.get(key)
            
            if cached:
                with self._stats_lock:
                    self.stats.total_hits += 1
                data = json.loads(cached)
                return [CachedTickData.from_dict(item) for item in data['data']]
            else:
                with self._stats_lock:
                    self.stats.total_misses += 1
                return None
                
        except Exception as e:
            logger.error(f"Error retrieving tick data: {e}")
            with self._stats_lock:
                self.stats.total_misses += 1
            return None
    
    # Multi-Timeframe Operations
    def cache_multi_timeframe(
        self,
        symbol: str,
        timeframes_data: Dict[Timeframe, List[OHLCVData]],
        ttl: Optional[Dict[Timeframe, int]] = None
    ) -> bool:
        """
        Cache OHLCV data for multiple timeframes
        
        Args:
            symbol: Trading symbol
            timeframes_data: Dictionary mapping timeframes to OHLCV data lists
            ttl: Custom TTL values per timeframe
        
        Returns:
            True if all timeframes cached successfully
        """
        try:
            success = True
            for timeframe, data in timeframes_data.items():
                custom_ttl = ttl.get(timeframe) if ttl else None
                if not self.cache_ohlcv(symbol, timeframe, data, custom_ttl):
                    success = False
            return success
        except Exception as e:
            logger.error(f"Error caching multi-timeframe data: {e}")
            return False
    
    def get_multi_timeframe(
        self,
        symbol: str,
        timeframes: List[Timeframe]
    ) -> Dict[Timeframe, Optional[List[OHLCVData]]]:
        """
        Retrieve OHLCV data for multiple timeframes
        
        Args:
            symbol: Trading symbol
            timeframes: List of timeframes to retrieve
        
        Returns:
            Dictionary mapping timeframes to OHLCV data lists
        """
        result = {}
        for timeframe in timeframes:
            result[timeframe] = self.get_ohlcv(symbol, timeframe)
        return result
    
    # Cache Management Operations
    def invalidate_ohlcv(self, symbol: str, timeframe: Timeframe) -> bool:
        """
        Invalidate OHLCV cache for a symbol and timeframe
        
        Args:
            symbol: Trading symbol
            timeframe: Timeframe to invalidate
        
        Returns:
            True if invalidation succeeded
        """
        try:
            key = self._build_key(symbol, timeframe, "ohlcv")
            self.redis_client.delete(key)
            with self._stats_lock:
                self.stats.total_evictions += 1
            logger.debug(f"Invalidated OHLCV cache for {symbol} ({timeframe.value})")
            return True
        except Exception as e:
            logger.error(f"Error invalidating cache: {e}")
            return False
    
    def invalidate_tick(self, symbol: str) -> bool:
        """
        Invalidate tick cache for a symbol
        
        Args:
            symbol: Trading symbol
        
        Returns:
            True if invalidation succeeded
        """
        try:
            key = self._build_tick_key(symbol)
            self.redis_client.delete(key)
            with self._stats_lock:
                self.stats.total_evictions += 1
            logger.debug(f"Invalidated tick cache for {symbol}")
            return True
        except Exception as e:
            logger.error(f"Error invalidating tick cache: {e}")
            return False
    
    def invalidate_symbol(self, symbol: str) -> bool:
        """
        Invalidate all cache for a symbol (all timeframes and tick data)
        
        Args:
            symbol: Trading symbol
        
        Returns:
            True if invalidation succeeded
        """
        try:
            pattern = f"market_data:{symbol}:*"
            # Use SCAN instead of KEYS for non-blocking iteration
            keys = []
            cursor = 0
            while True:
                cursor, partial_keys = self.redis_client.scan(
                    cursor=cursor,
                    match=pattern,
                    count=100
                )
                keys.extend(partial_keys)
                if cursor == 0:
                    break
            
            if keys:
                self.redis_client.delete(*keys)
                with self._stats_lock:
                    self.stats.total_evictions += len(keys)
            
            # Also invalidate tick data
            self.invalidate_tick(symbol)
            
            logger.debug(f"Invalidated all cache for {symbol}")
            return True
        except Exception as e:
            logger.error(f"Error invalidating symbol cache: {e}")
            return False
    
    def clear_all(self) -> bool:
        """
        Clear all market data cache
        
        Returns:
            True if clear succeeded
        """
        try:
            # Use SCAN instead of KEYS for non-blocking iteration
            all_keys = []
            
            # Scan for market_data keys
            cursor = 0
            while True:
                cursor, partial_keys = self.redis_client.scan(
                    cursor=cursor,
                    match="market_data:*",
                    count=100
                )
                all_keys.extend(partial_keys)
                if cursor == 0:
                    break
            
            # Scan for tick_data keys
            cursor = 0
            while True:
                cursor, partial_keys = self.redis_client.scan(
                    cursor=cursor,
                    match="tick_data:*",
                    count=100
                )
                all_keys.extend(partial_keys)
                if cursor == 0:
                    break
            
            if all_keys:
                # Delete in batches to avoid blocking
                batch_size = 1000
                for i in range(0, len(all_keys), batch_size):
                    batch = all_keys[i:i + batch_size]
                    self.redis_client.delete(*batch)
                
                with self._stats_lock:
                    self.stats.total_evictions += len(all_keys)
            
            logger.info(f"Cleared all cache ({len(all_keys)} keys)")
            return True
        except Exception as e:
            logger.error(f"Error clearing cache: {e}")
            return False
    
    # Statistics Operations
    def get_statistics(self) -> CacheStatistics:
        """
        Get cache statistics
        
        Returns:
            CacheStatistics object
        """
        try:
            # Use SCAN to count keys instead of KEYS
            key_count = 0
            
            # Count market_data keys
            cursor = 0
            while True:
                cursor, partial_keys = self.redis_client.scan(
                    cursor=cursor,
                    match="market_data:*",
                    count=100
                )
                key_count += len(partial_keys)
                if cursor == 0:
                    break
            
            # Count tick_data keys
            cursor = 0
            while True:
                cursor, partial_keys = self.redis_client.scan(
                    cursor=cursor,
                    match="tick_data:*",
                    count=100
                )
                key_count += len(partial_keys)
                if cursor == 0:
                    break
            
            with self._stats_lock:
                stats = CacheStatistics(
                    total_hits=self.stats.total_hits,
                    total_misses=self.stats.total_misses,
                    total_evictions=self.stats.total_evictions,
                    total_keys=key_count,
                    memory_usage_bytes=int(self.redis_client.info('memory')['used_memory'])
                )
            return stats
        except Exception as e:
            logger.error(f"Error getting statistics: {e}")
            return CacheStatistics()
    
    def print_statistics(self) -> None:
        """Print cache statistics to logger"""
        stats = self.get_statistics()
        logger.info("Cache Statistics:")
        logger.info(f"  Total Hits: {stats.total_hits}")
        logger.info(f"  Total Misses: {stats.total_misses}")
        logger.info(f"  Hit Rate: {stats.hit_rate:.2f}%")
        logger.info(f"  Total Evictions: {stats.total_evictions}")
        logger.info(f"  Total Keys: {stats.total_keys}")
        logger.info(f"  Memory Usage: {stats.memory_usage_bytes / 1024 / 1024:.2f} MB")
    
    def reset_statistics(self) -> None:
        """Reset cache statistics"""
        with self._stats_lock:
            self.stats = CacheStatistics()
        logger.info("Cache statistics reset")
    
    # Connection Management
    def health_check(self) -> bool:
        """
        Check Redis connection health
        
        Returns:
            True if Redis is healthy
        """
        try:
            self.redis_client.ping()
            return True
        except Exception as e:
            logger.error(f"Redis health check failed: {e}")
            return False
    
    def close(self) -> None:
        """Close Redis connection"""
        try:
            self.redis_client.close()
            logger.info("Redis connection closed")
        except Exception as e:
            logger.error(f"Error closing Redis connection: {e}")
    
    def __enter__(self):
        """Context manager entry"""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit"""
        self.close()

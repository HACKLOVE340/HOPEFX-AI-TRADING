"""
Tests for the cache module.
"""

import pytest
import time
from datetime import datetime
from unittest.mock import Mock, patch, MagicMock

from cache.market_data_cache import (
    Timeframe,
    OHLCVData,
    CachedTickData,
    CacheStatistics,
    MarketDataCache,
)


class TestTimeframe:
    """Tests for Timeframe Enum."""
    
    def test_timeframe_values(self):
        """Test timeframe enum values."""
        assert Timeframe.ONE_MINUTE.value == "1m"
        assert Timeframe.FIVE_MINUTES.value == "5m"
        assert Timeframe.FIFTEEN_MINUTES.value == "15m"
        assert Timeframe.THIRTY_MINUTES.value == "30m"
        assert Timeframe.ONE_HOUR.value == "1h"
        assert Timeframe.FOUR_HOURS.value == "4h"
        assert Timeframe.ONE_DAY.value == "1d"
        assert Timeframe.ONE_WEEK.value == "1w"
        assert Timeframe.ONE_MONTH.value == "1M"
    
    def test_timeframe_count(self):
        """Test that all expected timeframes exist."""
        timeframes = list(Timeframe)
        assert len(timeframes) == 9


class TestOHLCVData:
    """Tests for OHLCVData dataclass."""
    
    def test_ohlcv_creation(self):
        """Test OHLCV data creation."""
        ohlcv = OHLCVData(
            timestamp=1704067200,
            open_price=1.0850,
            high_price=1.0880,
            low_price=1.0820,
            close_price=1.0860,
            volume=10000.0
        )
        
        assert ohlcv.timestamp == 1704067200
        assert ohlcv.open_price == 1.0850
        assert ohlcv.high_price == 1.0880
        assert ohlcv.low_price == 1.0820
        assert ohlcv.close_price == 1.0860
        assert ohlcv.volume == 10000.0
    
    def test_ohlcv_to_dict(self):
        """Test OHLCV data conversion to dictionary."""
        ohlcv = OHLCVData(
            timestamp=1704067200,
            open_price=1.0850,
            high_price=1.0880,
            low_price=1.0820,
            close_price=1.0860,
            volume=10000.0
        )
        
        data = ohlcv.to_dict()
        
        assert isinstance(data, dict)
        assert data['timestamp'] == 1704067200
        assert data['open_price'] == 1.0850
        assert data['close_price'] == 1.0860
    
    def test_ohlcv_from_dict(self):
        """Test OHLCV data creation from dictionary."""
        data = {
            'timestamp': 1704067200,
            'open_price': 1.0850,
            'high_price': 1.0880,
            'low_price': 1.0820,
            'close_price': 1.0860,
            'volume': 10000.0
        }
        
        ohlcv = OHLCVData.from_dict(data)
        
        assert ohlcv.timestamp == 1704067200
        assert ohlcv.open_price == 1.0850
    
    def test_ohlcv_roundtrip(self):
        """Test OHLCV data serialization and deserialization roundtrip."""
        original = OHLCVData(
            timestamp=1704067200,
            open_price=1.0850,
            high_price=1.0880,
            low_price=1.0820,
            close_price=1.0860,
            volume=10000.0
        )
        
        restored = OHLCVData.from_dict(original.to_dict())
        
        assert original.timestamp == restored.timestamp
        assert original.open_price == restored.open_price
        assert original.close_price == restored.close_price


class TestCachedTickData:
    """Tests for CachedTickData dataclass."""
    
    def test_tick_data_creation(self):
        """Test tick data creation."""
        tick = CachedTickData(
            timestamp=1704067200000,
            price=1.0855,
            volume=100.0,
            bid=1.0854,
            ask=1.0856,
            bid_volume=50.0,
            ask_volume=50.0
        )
        
        assert tick.timestamp == 1704067200000
        assert tick.price == 1.0855
        assert tick.bid == 1.0854
        assert tick.ask == 1.0856
    
    def test_tick_data_to_dict(self):
        """Test tick data conversion to dictionary."""
        tick = CachedTickData(
            timestamp=1704067200000,
            price=1.0855,
            volume=100.0,
            bid=1.0854,
            ask=1.0856,
            bid_volume=50.0,
            ask_volume=50.0
        )
        
        data = tick.to_dict()
        
        assert isinstance(data, dict)
        assert data['price'] == 1.0855
        assert data['bid'] == 1.0854
    
    def test_tick_data_from_dict(self):
        """Test tick data creation from dictionary."""
        data = {
            'timestamp': 1704067200000,
            'price': 1.0855,
            'volume': 100.0,
            'bid': 1.0854,
            'ask': 1.0856,
            'bid_volume': 50.0,
            'ask_volume': 50.0
        }
        
        tick = CachedTickData.from_dict(data)
        
        assert tick.price == 1.0855
        assert tick.bid == 1.0854


class TestCacheStatistics:
    """Tests for CacheStatistics dataclass."""
    
    def test_statistics_defaults(self):
        """Test statistics default values."""
        stats = CacheStatistics()
        
        assert stats.total_hits == 0
        assert stats.total_misses == 0
        assert stats.total_evictions == 0
        assert stats.total_keys == 0
        assert stats.memory_usage_bytes == 0
    
    def test_hit_rate_zero_requests(self):
        """Test hit rate with zero requests."""
        stats = CacheStatistics()
        
        assert stats.hit_rate == 0.0
    
    def test_hit_rate_calculation(self):
        """Test hit rate calculation."""
        stats = CacheStatistics(total_hits=80, total_misses=20)
        
        assert stats.hit_rate == 80.0  # 80%
    
    def test_hit_rate_all_hits(self):
        """Test hit rate with all hits."""
        stats = CacheStatistics(total_hits=100, total_misses=0)
        
        assert stats.hit_rate == 100.0
    
    def test_hit_rate_all_misses(self):
        """Test hit rate with all misses."""
        stats = CacheStatistics(total_hits=0, total_misses=100)
        
        assert stats.hit_rate == 0.0
    
    def test_statistics_to_dict(self):
        """Test statistics conversion to dictionary."""
        stats = CacheStatistics(
            total_hits=80,
            total_misses=20,
            total_evictions=5,
            total_keys=100,
            memory_usage_bytes=1024
        )
        
        data = stats.to_dict()
        
        assert isinstance(data, dict)
        assert data['total_hits'] == 80
        assert data['total_misses'] == 20
        assert data['hit_rate_percent'] == 80.0
        assert data['memory_usage_bytes'] == 1024


class TestMarketDataCacheBasics:
    """Tests for MarketDataCache basic functionality (mocked Redis)."""
    
    def test_default_ttl_values(self):
        """Test that default TTL values are set correctly."""
        default_ttl = MarketDataCache.DEFAULT_TTL
        
        assert Timeframe.ONE_MINUTE in default_ttl
        assert Timeframe.ONE_DAY in default_ttl
        assert default_ttl[Timeframe.ONE_MINUTE] == 3600  # 1 hour
        assert default_ttl[Timeframe.ONE_DAY] == 604800  # 1 week
    
    @patch.object(MarketDataCache, '_connect_with_retry')
    def test_cache_initialization_with_mock(self, mock_connect):
        """Test cache initialization with mocked Redis connection."""
        # Setup mock
        mock_redis = MagicMock()
        mock_connect.return_value = mock_redis
        
        # Create cache
        cache = MarketDataCache(
            host='localhost',
            port=6379,
            db=0
        )
        
        # Verify
        assert cache.host == 'localhost'
        assert cache.port == 6379
        assert cache.db == 0
        assert cache.stats.total_hits == 0
        assert cache.stats.total_misses == 0
    
    @patch.object(MarketDataCache, '_connect_with_retry')
    def test_cache_with_password(self, mock_connect):
        """Test cache initialization with password."""
        mock_redis = MagicMock()
        mock_connect.return_value = mock_redis
        
        cache = MarketDataCache(
            host='redis.example.com',
            port=6380,
            password='secret'
        )
        
        assert cache.host == 'redis.example.com'
        assert cache.port == 6380

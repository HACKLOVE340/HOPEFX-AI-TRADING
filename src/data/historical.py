"""
Historical data loader with caching and validation.
"""

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal

import aiohttp
import pandas as pd

from src.core.config import settings
from src.core.exceptions import DataError
from src.core.logging_config import get_logger
from src.domain.models import OHLCV
from src.infrastructure.cache import get_cache

logger = get_logger(__name__)


class HistoricalDataLoader:
    """
    Production historical data loader with multi-source support.
    """
    
    def __init__(
        self,
        cache_dir: Path | None = None,
        default_source: Literal["polygon", "oanda", "file"] = "polygon"
    ):
        self.cache_dir = cache_dir or settings.data_dir / "historical"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.default_source = default_source
        self._session: aiohttp.ClientSession | None = None
    
    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create HTTP session."""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session
    
    async def load(
        self,
        symbol: str,
        start: datetime,
        end: datetime,
        timeframe: str = "1min",
        source: Literal["polygon", "oanda", "file", "cache"] | None = None,
        use_cache: bool = True
    ) -> pd.DataFrame:
        """
        Load historical data with caching.
        
        Args:
            symbol: Trading pair (e.g., "XAUUSD")
            start: Start datetime
            end: End datetime
            timeframe: Bar frequency
            source: Data source
            use_cache: Whether to use cache
        
        Returns:
            DataFrame with OHLCV columns
        """
        source = source or self.default_source
        
        # Check cache first
        if use_cache:
            cached = await self._load_from_cache(symbol, start, end, timeframe)
            if cached is not None:
                logger.info(f"Loaded {symbol} from cache")
                return cached
        
        # Load from source
        if source == "polygon":
            data = await self._load_from_polygon(symbol, start, end, timeframe)
        elif source == "oanda":
            data = await self._load_from_oanda(symbol, start, end, timeframe)
        elif source == "file":
            data = await self._load_from_file(symbol, start, end)
        else:
            raise DataError(f"Unknown source: {source}")
        
        # Save to cache
        if use_cache and data is not None:
            await self._save_to_cache(symbol, start, end, timeframe, data)
        
        return data
    
    async def _load_from_cache(
        self,
        symbol: str,
        start: datetime,
        end: datetime,
        timeframe: str
    ) -> pd.DataFrame | None:
        """Load from Redis cache."""
        try:
            cache = await get_cache()
            cache_key = f"hist:{symbol}:{timeframe}:{start.strftime('%Y%m%d')}:{end.strftime('%Y%m%d')}"
            
            data = await cache.get(cache_key)
            if data:
                return pd.read_json(data)
        except Exception as e:
            logger.warning(f"Cache load failed: {e}")
        
        return None
    
    async def _save_to_cache(
        self,
        symbol: str,
        start: datetime,
        end: datetime,
        timeframe: str,
        data: pd.DataFrame
    ) -> None:
        """Save to Redis cache."""
        try:
            cache = await get_cache()
            cache_key = f"hist:{symbol}:{timeframe}:{start.strftime('%Y%m%d')}:{end.strftime('%Y%m%d')}"
            
            await cache.set(
                cache_key,
                data.to_json(),
                ttl=86400  # 24 hours
            )
        except Exception as e:
            logger.warning(f"Cache save failed: {e}")
    
    async def _load_from_polygon(
        self,
        symbol: str,
        start: datetime,
        end: datetime,
        timeframe: str
    ) -> pd.DataFrame:
        """Load from Polygon.io."""
        from src.data.feeds.polygon import PolygonDataFeed
        
        feed = PolygonDataFeed(symbols=[symbol])
        bars = await feed.get_historical(symbol, start, end, timeframe)
        
        if not bars:
            raise DataError(f"No data returned from Polygon for {symbol}")
        
        # Convert to DataFrame
        data = {
            "open": [float(b.open) for b in bars],
            "high": [float(b.high) for b in bars],
            "low": [float(b.low) for b in bars],
            "close": [float(b.close) for b in bars],
            "volume": [b.volume for b in bars],
        }
        index = [b.timestamp for b in bars]
        
        return pd.DataFrame(data, index=index)
    
    async def _load_from_oanda(
        self,
        symbol: str,
        start: datetime,
        end: datetime,
        timeframe: str
    ) -> pd.DataFrame:
        """Load from OANDA."""
        # Implementation for OANDA historical data
        raise NotImplementedError("OANDA historical data not yet implemented")
    
    async def _load_from_file(
        self,
        symbol: str,
        start: datetime,
        end: datetime
    ) -> pd.DataFrame:
        """Load from local CSV/Parquet file."""
        file_path = self.cache_dir / f"{symbol}.parquet"
        
        if not file_path.exists():
            raise DataError(f"Local file not found: {file_path}")
        
        df = pd.read_parquet(file_path)
        
        # Filter by date
        mask = (df.index >= start) & (df.index <= end)
        return df.loc[mask]
    
    async def save_to_file(
        self,
        symbol: str,
        data: pd.DataFrame,
        format: Literal["parquet", "csv"] = "parquet"
    ) -> None:
        """Save data to local file."""
        if format == "parquet":
            file_path = self.cache_dir / f"{symbol}.parquet"
            data.to_parquet(file_path)
        else:
            file_path = self.cache_dir / f"{symbol}.csv"
            data.to_csv(file_path)
        
        logger.info(f"Saved {symbol} to {file_path}")
    
    async def close(self) -> None:
        """Close resources."""
        if self._session and not self._session.closed:
            await self._session.close()

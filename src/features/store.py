"""Feature store with versioning."""
from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path
from typing import Any

import aiofiles
import pandas as pd
import structlog

from configs.settings import get_settings

logger = structlog.get_logger()


class FeatureStore:
    """Versioned feature storage."""
    
    def __init__(self) -> None:
        self.base_path = get_settings().ml.feature_store_path
        self._cache: dict[str, pd.DataFrame] = {}
        self._lock = asyncio.Lock()
    
    async def store(self, symbol: str, features: dict[str, float], timestamp: datetime) -> None:
        """Store feature vector."""
        async with self._lock:
            key = f"{symbol}_{timestamp.strftime('%Y%m%d')}"
            
            if key not in self._cache:
                self._cache[key] = pd.DataFrame()
            
            # Append to DataFrame
            new_row = pd.DataFrame([{**features, "timestamp": timestamp}])
            self._cache[key] = pd.concat([self._cache[key], new_row], ignore_index=True)
            
            # Persist every 100 rows
            if len(self._cache[key]) % 100 == 0:
                await self._persist(key)
    
    async def _persist(self, key: str) -> None:
        """Persist to Parquet."""
        df = self._cache[key]
        path = self.base_path / f"{key}.parquet"
        
        # Write atomically
        temp_path = path.with_suffix(".tmp")
        df.to_parquet(temp_path, index=False, compression="zstd")
        temp_path.replace(path)
        
        logger.debug(f"Persisted features to {path}")
    
    async def get_features(
        self, 
        symbol: str, 
        start: datetime, 
        end: datetime
    ) -> pd.DataFrame:
        """Retrieve features for date range."""
        dates = pd.date_range(start, end, freq="D")
        frames = []
        
        for date in dates:
            key = f"{symbol}_{date.strftime('%Y%m%d')}"
            path = self.base_path / f"{key}.parquet"
            
            if path.exists():
                df = pd.read_parquet(path)
                frames.append(df)
            elif key in self._cache:
                frames.append(self._cache[key])
        
        if not frames:
            return pd.DataFrame()
        
        return pd.concat(frames, ignore_index=True)
    
    async def get_latest(self, symbol: str, n: int = 100) -> pd.DataFrame:
        """Get latest n feature vectors."""
        # Get from cache first
        today = datetime.utcnow().strftime("%Y%m%d")
        key = f"{symbol}_{today}"
        
        if key in self._cache:
            return self._cache[key].tail(n)
        
        # Fallback to disk
        path = self.base_path / f"{key}.parquet"
        if path.exists():
            df = pd.read_parquet(path)
            return df.tail(n)
        
        return pd.DataFrame()

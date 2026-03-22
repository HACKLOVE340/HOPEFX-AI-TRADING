"""
Institutional Data Management
Unified interface for: Database, Cache, File Storage, Message Queue
"""

import asyncio
import json
import pickle
import zlib
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Union, Callable
import hashlib

import aiofiles
import pandas as pd
import redis.asyncio as redis
from sqlalchemy import create_engine, select, insert, update, delete
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

# ============================================================================
# CONFIGURATION
# ============================================================================

@dataclass
class DataConfig:
    db_url: str = "postgresql+asyncpg://localhost/hopefx"
    redis_url: str = "redis://localhost:6379"
    storage_path: str = "outputs"
    cache_ttl: int = 300  # seconds

# ============================================================================
# UNIFIED DATA MANAGER
# ============================================================================

class UnifiedDataManager:
    """
    Single interface for ALL data operations.
    
    Tiers:
    1. L1: In-memory cache (fastest, smallest)
    2. L2: Redis (distributed, fast)
    3. L3: Database (persistent, relational)
    4. L4: File storage (blobs, large objects)
    """
    
    def __init__(self, config: DataConfig):
        self.config = config
        self._engine = None
        self._session_maker = None
        self._redis: Optional[redis.Redis] = None
        self._local_cache: Dict[str, tuple] = {}  # key -> (value, expiry)
        self._subscribers: List[Callable] = []
        
        # Ensure directories
        Path(self.config.storage_path).mkdir(parents=True, exist_ok=True)
        for subdir in ['trades', 'models', 'reports', 'logs', 'audit']:
            Path(self.config.storage_path) / subdir.mkdir(exist_ok=True)
    
    async def initialize(self):
        """Initialize all connections."""
        # Database
        self._engine = create_async_engine(
            self.config.db_url,
            pool_size=20,
            max_overflow=0,
            echo=False
        )
        self._session_maker = sessionmaker(
            self._engine, 
            class_=AsyncSession,
            expire_on_commit=False
        )
        
        # Redis
        self._redis = await redis.from_url(
            self.config.redis_url,
            decode_responses=False
        )
        
        # Start maintenance tasks
        asyncio.create_task(self._cache_maintenance())
    
    async def shutdown(self):
        """Graceful shutdown."""
        if self._redis:
            await self._redis.close()
        if self._engine:
            await self._engine.dispose()
    
    # =====================================================================
    # TIER 1: Local Cache (sub-millisecond)
    # =====================================================================
    
    def local_get(self, key: str) -> Optional[Any]:
        """Get from local memory cache."""
        if key in self._local_cache:
            value, expiry = self._local_cache[key]
            if expiry > datetime.utcnow().timestamp():
                return value
            del self._local_cache[key]
        return None
    
    def local_set(self, key: str, value: Any, ttl_seconds: int = 60):
        """Set in local cache."""
        expiry = datetime.utcnow().timestamp() + ttl_seconds
        self._local_cache[key] = (value, expiry)
    
    # =====================================================================
    # TIER 2: Redis Cache (milliseconds)
    # =====================================================================
    
    async def redis_get(self, key: str) -> Optional[Any]:
        """Get from Redis."""
        try:
            data = await self._redis.get(key)
            if data:
                return self._deserialize(data)
        except redis.RedisError:
            pass
        return None
    
    async def redis_set(
        self, 
        key: str, 
        value: Any, 
        ttl: int = 300,
        nx: bool = False
    ) -> bool:
        """Set in Redis."""
        try:
            serialized = self._serialize(value)
            if nx:
                return await self._redis.setnx(key, serialized) and \
                       await self._redis.expire(key, ttl)
            return await self._redis.setex(key, ttl, serialized)
        except redis.RedisError:
            return False
    
    async def redis_delete(self, pattern: str):
        """Delete keys matching pattern."""
        try:
            keys = await self._redis.keys(f"*{pattern}*")
            if keys:
                await self._redis.delete(*keys)
        except redis.RedisError:
            pass
    
    # =====================================================================
    # TIER 3: Database (persistent)
    # =====================================================================
    
    async def db_execute(self, statement):
        """Execute database statement."""
        async with self._session_maker() as session:
            async with session.begin():
                result = await session.execute(statement)
                return result
    
    async def db_fetch_one(self, statement):
        """Fetch single result."""
        result = await self.db_execute(statement)
        return result.scalar_one_or_none()
    
    async def db_fetch_many(self, statement):
        """Fetch multiple results."""
        result = await self.db_execute(statement)
        return result.scalars().all()
    
    async def db_insert(self, table, values: Dict) -> str:
        """Insert record."""
        stmt = insert(table).values(**values).returning(table.id)
        result = await self.db_execute(stmt)
        return result.scalar_one()
    
    async def db_update(self, table, id: str, values: Dict):
        """Update record."""
        stmt = update(table).where(table.id == id).values(**values)
        await self.db_execute(stmt)
    
    # =====================================================================
    # TIER 4: File Storage (large objects)
    # =====================================================================
    
    def file_save(
        self,
        category: str,
        name: str,
        data: Any,
        metadata: Optional[Dict] = None,
        format: str = "auto"
    ) -> Path:
        """
        Save to organized file storage.
        
        Categories: trades, models, reports, logs, audit
        """
        base_path = Path(self.config.storage_path) / category
        base_path.mkdir(exist_ok=True)
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        filename = f"{name}_{timestamp}"
        
        # Determine format
        if format == "auto":
            if isinstance(data, pd.DataFrame):
                format = "parquet"
            elif isinstance(data, (dict, list)):
                format = "json"
            elif isinstance(data, bytes):
                format = "bin"
            else:
                format = "pkl"
        
        # Save
        path = base_path / f"{filename}.{format}"
        
        if format == "parquet":
            data.to_parquet(path, compression="zstd", engine="pyarrow")
        elif format == "json":
            with open(path, "w") as f:
                json.dump(data, f, indent=2, default=str)
        elif format == "bin":
            path.write_bytes(data)
        else:
            with open(path, "wb") as f:
                pickle.dump(data, f, protocol=pickle.HIGHEST_PROTOCOL)
        
        # Metadata
        if metadata:
            meta_path = base_path / f"{filename}.meta.json"
            with open(meta_path, "w") as f:
                json.dump(metadata, f, indent=2, default=str)
        
        return path
    
    def file_load(self, path: Path) -> Any:
        """Load from file storage."""
        suffix = path.suffix.lstrip(".")
        
        if suffix == "parquet":
            return pd.read_parquet(path)
        elif suffix == "json":
            with open(path) as f:
                return json.load(f)
        elif suffix == "pkl":
            with open(path, "rb") as f:
                return pickle.load(f)
        elif suffix == "bin":
            return path.read_bytes()
        
        raise ValueError(f"Unknown format: {suffix}")
    
    def file_list(
        self,
        category: str,
        pattern: Optional[str] = None,
        since: Optional[datetime] = None
    ) -> List[Path]:
        """List files in category."""
        base_path = Path(self.config.storage_path) / category
        
        if not base_path.exists():
            return []
        
        files = list(base_path.glob(f"*{pattern or '*'}*"))
        
        if since:
            files = [f for f in files if datetime.fromtimestamp(f.stat().st_mtime) > since]
        
        return sorted(files, key=lambda p: p.stat().st_mtime, reverse=True)
    
    # =====================================================================
    # UNIFIED INTERFACE (Auto-tier selection)
    # =====================================================================
    
    async def get(
        self,
        key: str,
        source: str = "auto"
    ) -> Optional[Any]:
        """
        Get with automatic tier selection.
        
        Order: L1 -> L2 -> L3 -> miss
        """
        # L1
        if source in ("auto", "l1"):
            val = self.local_get(key)
            if val is not None:
                return val
        
        # L2
        if source in ("auto", "l2"):
            val = await self.redis_get(key)
            if val is not None:
                # Promote to L1
                self.local_set(key, val, 60)
                return val
        
        return None
    
    async def set(
        self,
        key: str,
        value: Any,
        l1_ttl: int = 60,
        l2_ttl: int = 300
    ):
        """Set in all tiers."""
        self.local_set(key, value, l1_ttl)
        await self.redis_set(key, value, l2_ttl)
    
    async def invalidate(self, pattern: str):
        """Invalidate across all caches."""
        # L1
        for k in list(self._local_cache.keys()):
            if pattern in k:
                del self._local_cache[k]
        
        # L2
        await self.redis_delete(pattern)
    
    # =====================================================================
    # SPECIALIZED METHODS
    # =====================================================================
    
    async def cache_market_data(
        self,
        symbol: str,
        timeframe: str,
        data: pd.DataFrame
    ):
        """Cache OHLCV data."""
        key = f"md:{symbol}:{timeframe}"
        await self.set(key, data, l1_ttl=30, l2_ttl=300)
    
    async def get_market_data(
        self,
        symbol: str,
        timeframe: str
    ) -> Optional[pd.DataFrame]:
        """Get cached market data."""
        key = f"md:{symbol}:{timeframe}"
        return await self.get(key)
    
    def save_model(
        self,
        name: str,
        model: Any,
        metrics: Dict,
        features: List[str]
    ) -> Path:
        """Save ML model with metadata."""
        metadata = {
            "saved_at": datetime.utcnow().isoformat(),
            "metrics": metrics,
            "features": features,
            "model_type": type(model).__name__
        }
        
        return self.file_save("models", name, model, metadata)
    
    def save_equity_curve(
        self,
        strategy_name: str,
        equity_curve: pd.DataFrame,
        trades: List[Dict],
        metrics: Dict
    ) -> Path:
        """Save backtest results."""
        data = {
            "equity_curve": equity_curve.to_dict(),
            "trades": trades,
            "metrics": metrics
        }
        
        return self.file_save(
            "trades",
            f"backtest_{strategy_name}",
            data,
            metadata={
                "strategy": strategy_name,
                "trade_count": len(trades),
                "final_equity": equity_curve['equity'].iloc[-1] if len(equity_curve) > 0 else 0
            }
        )
    
    # =====================================================================
    # INTERNAL
    # =====================================================================
    
    def _serialize(self, obj: Any) -> bytes:
        """Serialize with compression."""
        pickled = pickle.dumps(obj, protocol=pickle.HIGHEST_PROTOCOL)
        if len(pickled) > 1024:
            return b"z" + zlib.compress(pickled)
        return b"r" + pickled
    
    def _deserialize(self, data: bytes) -> Any:
        """Deserialize."""
        if data[0:1] == b"z":
            return pickle.loads(zlib.decompress(data[1:]))
        return pickle.loads(data[1:])
    
    async def _cache_maintenance(self):
        """Periodic cache cleanup."""
        while True:
            await asyncio.sleep(60)
            
            # Clean expired L1 entries
            now = datetime.utcnow().timestamp()
            expired = [
                k for k, (_, exp) in self._local_cache.items() 
                if exp < now
            ]
            for k in expired:
                del self._local_cache[k]

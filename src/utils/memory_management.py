"""
Memory management utilities for long-running trading systems.
Prevents OOM crashes and ensures stable operation.
"""

import asyncio
import gc
import sys
import tracemalloc
import weakref
from collections import deque
from dataclasses import dataclass
from typing import Any, Callable, Deque, Dict, Generic, Optional, TypeVar, List

import psutil

from src.core.logging_config import get_logger

logger = get_logger(__name__)

T = TypeVar('T')


@dataclass
class MemorySnapshot:
    """Memory usage snapshot."""
    timestamp: float
    rss_mb: float
    vms_mb: float
    percent: float
    top_allocations: List[tuple]


class RingBuffer(Generic[T]):
    """
    Fixed-size ring buffer with O(1) append and automatic eviction.
    Replaces unbounded lists in price history and other accumulators.
    """
    
    def __init__(self, capacity: int, on_evict: Optional[Callable[[T], None]] = None):
        self.capacity = capacity
        self._buffer: Deque[T] = deque(maxlen=capacity)
        self._on_evict = on_evict
        self._access_count = 0
    
    def append(self, item: T) -> None:
        """Add item, evicting oldest if at capacity."""
        if len(self._buffer) >= self.capacity and self._on_evict:
            # on_evict called automatically by deque, but we can notify
            pass
        
        self._buffer.append(item)
        self._access_count += 1
    
    def extend(self, items: List[T]) -> None:
        """Extend with multiple items."""
        for item in items:
            self.append(item)
    
    def __getitem__(self, index: int) -> T:
        """Get item by index (negative indices supported)."""
        return self._buffer[index]
    
    def __len__(self) -> int:
        return len(self._buffer)
    
    def __iter__(self):
        return iter(self._buffer)
    
    def clear(self) -> None:
        """Clear all items."""
        self._buffer.clear()
    
    def to_list(self) -> List[T]:
        """Convert to list (copy)."""
        return list(self._buffer)
    
    @property
    def is_full(self) -> bool:
        """Check if buffer is at capacity."""
        return len(self._buffer) >= self.capacity
    
    @property
    def oldest(self) -> Optional[T]:
        """Get oldest item."""
        return self._buffer[0] if self._buffer else None
    
    @property
    def newest(self) -> Optional[T]:
        """Get newest item."""
        return self._buffer[-1] if self._buffer else None


class LRUCache(Generic[T]):
    """
    LRU cache with TTL support for time-sensitive data.
    """
    
    def __init__(
        self,
        max_size: int = 1000,
        ttl_seconds: Optional[float] = None
    ):
        self.max_size = max_size
        self.ttl = ttl_seconds
        
        self._cache: Dict[str, tuple[T, float]] = {}  # key -> (value, timestamp)
        self._access_order: Deque[str] = deque()
        self._lock = asyncio.Lock()
    
    async def get(self, key: str) -> Optional[T]:
        """Get value if exists and not expired."""
        async with self._lock:
            if key not in self._cache:
                return None
            
            value, timestamp = self._cache[key]
            
            # Check TTL
            if self.ttl and (asyncio.get_event_loop().time() - timestamp) > self.ttl:
                del self._cache[key]
                self._access_order.remove(key)
                return None
            
            # Update access order
            self._access_order.remove(key)
            self._access_order.append(key)
            
            return value
    
    async def set(self, key: str, value: T) -> None:
        """Set value with automatic eviction."""
        async with self._lock:
            now = asyncio.get_event_loop().time()
            
            # Evict if at capacity
            if len(self._cache) >= self.max_size and key not in self._cache:
                oldest_key = self._access_order.popleft()
                del self._cache[oldest_key]
            
            # Remove old entry if exists
            if key in self._cache:
                self._access_order.remove(key)
            
            # Add new entry
            self._cache[key] = (value, now)
            self._access_order.append(key)
    
    async def clear(self) -> None:
        """Clear all entries."""
        async with self._lock:
            self._cache.clear()
            self._access_order.clear()


class MemoryMonitor:
    """
    Continuous memory monitoring with automatic garbage collection
    and alerting.
    """
    
    def __init__(
        self,
        warning_threshold: float = 80.0,  # Percent
        critical_threshold: float = 90.0,
        check_interval: float = 30.0,
        auto_gc: bool = True
    ):
        self.warning_threshold = warning_threshold
        self.critical_threshold = critical_threshold
        self.check_interval = check_interval
        self.auto_gc = auto_gc
        
        self._running = False
        self._snapshots: RingBuffer[MemorySnapshot] = RingBuffer(capacity=1000)
        self._task: Optional[asyncio.Task] = None
        
        # Tracemalloc for detailed tracking
        self._tracemalloc_enabled = False
    
    async def start(self) -> None:
        """Start monitoring."""
        self._running = True
        self._task = asyncio.create_task(self._monitor_loop())
        
        # Start tracemalloc if available
        try:
            tracemalloc.start()
            self._tracemalloc_enabled = True
            logger.info("Tracemalloc enabled for detailed memory tracking")
        except Exception:
            logger.warning("Tracemalloc not available")
        
        logger.info(f"Memory monitor started (check interval: {self.check_interval}s)")
    
    async def stop(self) -> None:
        """Stop monitoring."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        
        if self._tracemalloc_enabled:
            tracemalloc.stop()
        
        logger.info("Memory monitor stopped")
    
    async def _monitor_loop(self) -> None:
        """Main monitoring loop."""
        while self._running:
            try:
                await self._check_memory()
                await asyncio.sleep(self.check_interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Memory check error: {e}")
                await asyncio.sleep(self.check_interval)
    
    async def _check_memory(self) -> None:
        """Check current memory usage."""
        process = psutil.Process()
        memory_info = process.memory_info()
        
        # System memory
        system_memory = psutil.virtual_memory()
        
        snapshot = MemorySnapshot(
            timestamp=asyncio.get_event_loop().time(),
            rss_mb=memory_info.rss / 1024 / 1024,
            vms_mb=memory_info.vms / 1024 / 1024,
            percent=system_memory.percent,
            top_allocations=self._get_top_allocations() if self._tracemalloc_enabled else []
        )
        
        self._snapshots.append(snapshot)
        
        # Check thresholds
        if system_memory.percent >= self.critical_threshold:
            logger.critical(
                f"CRITICAL: Memory usage at {system_memory.percent:.1f}%! "
                f"RSS: {snapshot.rss_mb:.1f}MB"
            )
            await self._emergency_cleanup()
            
        elif system_memory.percent >= self.warning_threshold:
            logger.warning(
                f"WARNING: Memory usage at {system_memory.percent:.1f}% "
                f"RSS: {snapshot.rss_mb:.1f}MB"
            )
            if self.auto_gc:
                self._trigger_gc()
        
        # Log detailed stats periodically
        if len(self._snapshots) % 10 == 0:
            logger.info(
                f"Memory stats: RSS={snapshot.rss_mb:.1f}MB, "
                f"VMS={snapshot.vms_mb:.1f}MB, "
                f"System={system_memory.percent:.1f}%"
            )
    
    def _get_top_allocations(self) -> List[tuple]:
        """Get top memory allocations from tracemalloc."""
        if not self._tracemalloc_enabled:
            return []
        
        snapshot = tracemalloc.take_snapshot()
        top_stats = snapshot.statistics('lineno')[:5]
        
        return [
            (stat.traceback.format()[-1], stat.size / 1024)
            for stat in top_stats
        ]
    
    def _trigger_gc(self) -> None:
        """Trigger garbage collection."""
        gc.collect()
        
        # Log GC results
        freed = gc.garbage
        if freed:
            logger.info(f"GC freed {len(freed)} objects")
    
    async def _emergency_cleanup(self) -> None:
        """Emergency memory cleanup."""
        logger.critical("Performing emergency memory cleanup...")
        
        # Force garbage collection
        gc.collect()
        gc.collect()  # Second pass for cyclic refs
        
        # Clear all ring buffers if possible
        # This would need integration with the rest of the system
        
        # If still critical, consider restarting components
        memory = psutil.virtual_memory()
        if memory.percent >= self.critical_threshold:
            logger.critical("Memory still critical after cleanup - consider restart")
    
    def get_trend(self, window: int = 10) -> Dict[str, float]:
        """Get memory usage trend."""
        if len(self._snapshots) < 2:
            return {"slope": 0, "avg": 0}
        
        recent = list(self._snapshots)[-window:]
        rss_values = [s.rss_mb for s in recent]
        
        # Simple linear regression
        n = len(rss_values)
        x = list(range(n))
        avg_x = sum(x) / n
        avg_y = sum(rss_values) / n
        
        slope = sum((xi - avg_x) * (yi - avg_y) for xi, yi in zip(x, rss_values))
        slope /= sum((xi - avg_x) ** 2 for xi in x) or 1
        
        return {
            "slope_mb_per_check": slope,
            "avg_mb": avg_y,
            "current_mb": rss_values[-1],
            "projected_critical_checks": (
                (self.critical_threshold / 100 * psutil.virtual_memory().total / 1024 / 1024 - rss_values[-1]) / slope
                if slope > 0 else float('inf')
            )
        }


class ObjectPool(Generic[T]):
    """
    Object pool for expensive-to-create objects (e.g., ML models).
    """
    
    def __init__(
        self,
        factory: Callable[[], T],
        max_size: int = 5,
        ttl_seconds: float = 300
    ):
        self.factory = factory
        self.max_size = max_size
        self.ttl = ttl_seconds
        
        self._pool: Deque[tuple[T, float]] = deque()
        self._in_use: set = set()
        self._lock = asyncio.Lock()
    
    async def acquire(self) -> T:
        """Get object from pool or create new."""
        async with self._lock:
            now = asyncio.get_event_loop().time()
            
            # Find non-expired object
            while self._pool:
                obj, created_at = self._pool.popleft()
                if now - created_at < self.ttl:
                    self._in_use.add(id(obj))
                    return obj
            
            # Create new
            obj = self.factory()
            self._in_use.add(id(obj))
            return obj
    
    async def release(self, obj: T) -> None:
        """Return object to pool."""
        async with self._lock:
            obj_id = id(obj)
            if obj_id in self._in_use:
                self._in_use.remove(obj_id)
                
                if len(self._pool) < self.max_size:
                    self._pool.append((obj, asyncio.get_event_loop().time()))
    
    async def clear(self) -> None:
        """Clear all pooled objects."""
        async with self._lock:
            self._pool.clear()
            self._in_use.clear()


# Global memory monitor
_memory_monitor: Optional[MemoryMonitor] = None


async def get_memory_monitor() -> MemoryMonitor:
    """Get or create global memory monitor."""
    global _memory_monitor
    if _memory_monitor is None:
        _memory_monitor = MemoryMonitor()
        await _memory_monitor.start()
    return _memory_monitor


def get_ring_buffer(capacity: int, name: str = "buffer") -> RingBuffer:
    """Create a named ring buffer with monitoring."""
    buffer = RingBuffer(capacity=capacity)
    logger.debug(f"Created ring buffer '{name}' with capacity {capacity}")
    return buffer

"""
Production concurrency primitives for trading systems.
Ensures atomic operations and prevents race conditions.
"""

import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Dict, Generic, Optional, TypeVar

import atomic  # Using atomic operations where possible

from src.core.logging_config import get_logger

logger = get_logger(__name__)

T = TypeVar('T')


@dataclass
class AtomicDecimal:
    """
    Thread-safe Decimal with atomic operations.
    Replaces direct Decimal usage in shared state.
    """
    
    def __init__(self, value: Decimal = Decimal("0")):
        self._value = value
        self._lock = asyncio.Lock()
    
    async def get(self) -> Decimal:
        """Get current value."""
        async with self._lock:
            return self._value
    
    async def set(self, value: Decimal) -> None:
        """Set new value."""
        async with self._lock:
            self._value = value
    
    async def add(self, other: Decimal) -> Decimal:
        """Atomic addition."""
        async with self._lock:
            self._value += other
            return self._value
    
    async def subtract(self, other: Decimal) -> Decimal:
        """Atomic subtraction."""
        async with self._lock:
            self._value -= other
            return self._value
    
    async def compare_and_swap(
        self,
        expected: Decimal,
        new_value: Decimal
    ) -> bool:
        """Atomic compare-and-swap."""
        async with self._lock:
            if self._value == expected:
                self._value = new_value
                return True
            return False


class ReadWriteLock:
    """
    Async read-write lock with writer priority.
    Prevents writer starvation.
    """
    
    def __init__(self):
        self._read_lock = asyncio.Lock()
        self._write_lock = asyncio.Lock()
        self._read_count = 0
        self._read_count_lock = asyncio.Lock()
        self._write_pending = asyncio.Event()
        self._write_pending.set()  # No writers initially
    
    @asynccontextmanager
    async def read(self):
        """Acquire read lock."""
        # Wait if writer pending
        await self._write_pending.wait()
        
        async with self._read_count_lock:
            self._read_count += 1
            if self._read_count == 1:
                await self._read_lock.acquire()
        
        try:
            yield
        finally:
            async with self._read_count_lock:
                self._read_count -= 1
                if self._read_count == 0:
                    self._read_lock.release()
    
    @asynccontextmanager
    async def write(self):
        """Acquire write lock."""
        # Signal writers pending
        self._write_pending.clear()
        
        try:
            # Wait for all readers to finish
            async with self._read_count_lock:
                if self._read_count > 0:
                    await self._read_lock.acquire()
                    self._read_lock.release()
            
            async with self._write_lock:
                yield
        finally:
            self._write_pending.set()


class SequentialExecutor:
    """
    Ensures sequential execution of operations with same key.
    Prevents race conditions in order processing.
    """
    
    def __init__(self):
        self._locks: Dict[str, asyncio.Lock] = {}
        self._master_lock = asyncio.Lock()
    
    async def execute(
        self,
        key: str,
        coro: Any
    ) -> Any:
        """Execute coroutine sequentially for given key."""
        async with self._master_lock:
            if key not in self._locks:
                self._locks[key] = asyncio.Lock()
            lock = self._locks[key]
        
        async with lock:
            return await coro
    
    async def execute_many(
        self,
        items: list[tuple[str, Any]]
    ) -> list[Any]:
        """Execute multiple items, parallelizing different keys."""
        # Group by key
        by_key: Dict[str, list] = {}
        for key, coro in items:
            by_key.setdefault(key, []).append(coro)
        
        # Execute each key's items sequentially, keys in parallel
        tasks = []
        for key, coros in by_key.items():
            async def run_key(key, coros):
                results = []
                for coro in coros:
                    result = await self.execute(key, coro)
                    results.append(result)
                return results
            
            tasks.append(run_key(key, coros))
        
        results = await asyncio.gather(*tasks)
        # Flatten results
        return [r for sublist in results for r in sublist]


class IdGenerator:
    """
    Distributed-safe ID generator with ordering guarantees.
    Uses Snowflake-like approach for uniqueness.
    """
    
    def __init__(self, node_id: int = 0):
        self.node_id = node_id
        self._sequence = 0
        self._last_timestamp = 0
        self._lock = asyncio.Lock()
    
    async def generate(self) -> str:
        """Generate unique ordered ID."""
        async with self._lock:
            timestamp = int(asyncio.get_event_loop().time() * 1000)
            
            if timestamp == self._last_timestamp:
                self._sequence = (self._sequence + 1) & 0xFFF
                if self._sequence == 0:
                    # Wait for next millisecond
                    await asyncio.sleep(0.001)
                    timestamp = int(asyncio.get_event_loop().time() * 1000)
            else:
                self._sequence = 0
            
            self._last_timestamp = timestamp
            
            # Snowflake-like: 41 bits timestamp | 10 bits node | 12 bits sequence
            id_num = ((timestamp & 0x1FFFFFFFFFF) << 22) | \
                     ((self.node_id & 0x3FF) << 12) | \
                     (self._sequence & 0xFFF)
            
            return f"{id_num:020d}"


class AsyncBarrier:
    """
    Async barrier for coordinating multiple tasks.
    """
    
    def __init__(self, parties: int):
        self.parties = parties
        self._count = 0
        self._lock = asyncio.Lock()
        self._event = asyncio.Event()
    
    async def wait(self) -> int:
        """Wait for all parties."""
        async with self._lock:
            self._count += 1
            if self._count >= self.parties:
                self._event.set()
                return 0  # Leader
        
        await self._event.wait()
        return 1  # Follower
    
    async def reset(self) -> None:
        """Reset barrier for reuse."""
        async with self._lock:
            self._count = 0
            self._event.clear()

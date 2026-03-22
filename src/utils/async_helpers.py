"""
Async utility functions.
"""

import asyncio
from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator, Callable, TypeVar

T = TypeVar("T")


async def retry_with_backoff(
    func: Callable[..., T],
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 60.0,
    exceptions: tuple[type[Exception], ...] = (Exception,),
    **kwargs
) -> T:
    """
    Retry function with exponential backoff.
    """
    for attempt in range(max_retries):
        try:
            return await func(**kwargs) if asyncio.iscoroutinefunction(func) else func(**kwargs)
        except exceptions as e:
            if attempt == max_retries - 1:
                raise
            
            delay = min(base_delay * (2 ** attempt), max_delay)
            jitter = delay * 0.1 * (asyncio.random() - 0.5) if hasattr(asyncio, 'random') else 0
            await asyncio.sleep(delay + jitter)
    
    raise RuntimeError("Max retries exceeded")


@asynccontextmanager
async def timeout_context(seconds: float) -> AsyncGenerator[None, None]:
    """Context manager with timeout."""
    try:
        yield
    except asyncio.TimeoutError:
        raise TimeoutError(f"Operation timed out after {seconds}s")


async def gather_with_concurrency(
    coroutines: list[Callable[[], Any]],
    max_concurrent: int = 10
) -> list[Any]:
    """
    Gather coroutines with limited concurrency.
    """
    semaphore = asyncio.Semaphore(max_concurrent)
    
    async def bounded_coro(coro):
        async with semaphore:
            return await coro()
    
    return await asyncio.gather(*[bounded_coro(c) for c in coroutines])


class CircuitBreaker:
    """
    Circuit breaker pattern implementation.
    """
    
    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout: float = 60.0,
        expected_exception: type[Exception] = Exception
    ):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.expected_exception = expected_exception
        
        self._failures = 0
        self._last_failure_time: float | None = None
        self._state = "CLOSED"  # CLOSED, OPEN, HALF_OPEN
    
    @property
    def is_open(self) -> bool:
        """Check if circuit is open."""
        if self._state == "OPEN":
            if self._last_failure_time:
                elapsed = asyncio.get_event_loop().time() - self._last_failure_time
                if elapsed > self.recovery_timeout:
                    self._state = "HALF_OPEN"
                    return False
            return True
        return False
    
    async def call(self, func: Callable[..., T], *args, **kwargs) -> T:
        """Execute function with circuit breaker."""
        if self.is_open:
            raise RuntimeError("Circuit breaker is OPEN")
        
        try:
            result = await func(*args, **kwargs) if asyncio.iscoroutinefunction(func) else func(*args, **kwargs)
            self._on_success()
            return result
        except self.expected_exception as e:
            self._on_failure()
            raise
    
    def _on_success(self) -> None:
        """Handle successful call."""
        self._failures = 0
        self._state = "CLOSED"
    
    def _on_failure(self) -> None:
        """Handle failed call."""
        self._failures += 1
        self._last_failure_time = asyncio.get_event_loop().time()
        
        if self._failures >= self.failure_threshold:
            self._state = "OPEN"

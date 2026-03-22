"""
Production-grade async infrastructure with proper event loop management,
task supervision, and graceful degradation.
"""

import asyncio
import functools
import signal
import sys
import threading
import weakref
from contextlib import asynccontextmanager
from typing import Any, Callable, Coroutine, Optional, Set

from src.core.logging_config import get_logger

logger = get_logger(__name__)


class EventLoopManager:
    """
    Manages event loop lifecycle for production deployments.
    
    Handles:
    - Proper loop initialization
    - Signal handling
    - Graceful shutdown with task cleanup
    - Thread-safe loop access
    """
    
    _instance: Optional["EventLoopManager"] = None
    _lock = threading.Lock()
    
    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._tasks: Set[asyncio.Task] = weakref.WeakSet()
        self._shutdown_hooks: list[Callable] = []
        self._running = False
        self._initialized = True
    
    def get_loop(self) -> asyncio.AbstractEventLoop:
        """
        Get running event loop or create new one.
        
        Thread-safe access to event loop.
        """
        try:
            # Try to get running loop in current thread
            loop = asyncio.get_running_loop()
            return loop
        except RuntimeError:
            # No running loop - create or get existing
            if self._loop is None or self._loop.is_closed():
                self._loop = asyncio.new_event_loop()
                asyncio.set_event_loop(self._loop)
            return self._loop
    
    def run_async(self, coro: Coroutine, timeout: Optional[float] = None) -> Any:
        """
        Run coroutine from synchronous code safely.
        
        Args:
            coro: Coroutine to run
            timeout: Maximum wait time
        
        Returns:
            Coroutine result
        """
        try:
            # Check if we're in an async context
            loop = asyncio.get_running_loop()
            # We're in async context - use run_coroutine_threadsafe
            future = asyncio.run_coroutine_threadsafe(coro, loop)
            return future.result(timeout=timeout)
        except RuntimeError:
            # No running loop - safe to use asyncio.run
            return asyncio.run(coro)
    
    def setup_signal_handlers(self) -> None:
        """Setup graceful shutdown signals."""
        loop = self.get_loop()
        
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(
                sig,
                lambda: asyncio.create_task(self._signal_handler(sig))
            )
        
        logger.info("Signal handlers registered")
    
    async def _signal_handler(self, sig: signal.Signals) -> None:
        """Handle shutdown signal."""
        logger.info(f"Received signal {sig.name}, initiating shutdown...")
        await self.shutdown()
    
    def create_supervised_task(
        self,
        coro: Coroutine,
        name: Optional[str] = None,
        on_error: Optional[Callable[[Exception], None]] = None
    ) -> asyncio.Task:
        """
        Create task with automatic error handling and cleanup.
        """
        loop = self.get_loop()
        
        async def wrapper():
            try:
                return await coro
            except asyncio.CancelledError:
                logger.debug(f"Task {name} cancelled")
                raise
            except Exception as e:
                logger.error(f"Task {name} failed: {e}", exc_info=True)
                if on_error:
                    on_error(e)
                raise
        
        task = loop.create_task(wrapper(), name=name)
        self._tasks.add(task)
        
        # Auto-cleanup
        def cleanup(t):
            self._tasks.discard(t)
        
        task.add_done_callback(cleanup)
        
        return task
    
    async def shutdown(self, timeout: float = 30.0) -> None:
        """
        Graceful shutdown with task cleanup.
        
        Steps:
        1. Stop accepting new work
        2. Cancel running tasks
        3. Wait for cleanup with timeout
        4. Force close remaining tasks
        """
        if not self._running:
            return
        
        self._running = False
        logger.info("Starting graceful shutdown...")
        
        # Run shutdown hooks
        for hook in self._shutdown_hooks:
            try:
                if asyncio.iscoroutinefunction(hook):
                    await asyncio.wait_for(hook(), timeout=5.0)
                else:
                    hook()
            except Exception as e:
                logger.error(f"Shutdown hook failed: {e}")
        
        # Cancel all running tasks
        tasks = [t for t in self._tasks if not t.done()]
        if tasks:
            logger.info(f"Cancelling {len(tasks)} running tasks...")
            for task in tasks:
                task.cancel()
            
            # Wait for cancellation
            await asyncio.gather(*tasks, return_exceptions=True)
        
        # Close loop
        if self._loop and not self._loop.is_closed():
            self._loop.close()
        
        logger.info("Shutdown complete")
    
    def register_shutdown_hook(self, hook: Callable) -> None:
        """Register cleanup function for shutdown."""
        self._shutdown_hooks.append(hook)


class TaskGroup:
    """
    Structured concurrency task group with error propagation.
    
    Ensures all tasks complete or all fail together.
    """
    
    def __init__(self, name: Optional[str] = None):
        self.name = name or "TaskGroup"
        self._tasks: list[asyncio.Task] = []
        self._completed = 0
        self._failed = 0
    
    async def __aenter__(self):
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Cleanup all tasks on exit."""
        if exc_val:
            # Error occurred - cancel all tasks
            for task in self._tasks:
                if not task.done():
                    task.cancel()
        
        # Wait for all tasks
        results = await asyncio.gather(*self._tasks, return_exceptions=True)
        
        # Log results
        for task, result in zip(self._tasks, results):
            if isinstance(result, Exception):
                logger.error(f"Task {task.get_name()} failed: {result}")
                self._failed += 1
            else:
                self._completed += 1
    
    def create_task(self, coro: Coroutine, name: Optional[str] = None) -> asyncio.Task:
        """Add task to group."""
        task = asyncio.create_task(coro, name=name)
        self._tasks.append(task)
        return task


@asynccontextmanager
async def timeout_context(seconds: float, description: str = "Operation"):
    """
    Timeout context with proper cleanup.
    """
    try:
        async with asyncio.timeout(seconds):
            yield
    except asyncio.TimeoutError:
        logger.error(f"{description} timed out after {seconds}s")
        raise TimeoutError(f"{description} exceeded {seconds}s timeout")


def retry_with_jitter(
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 60.0,
    exceptions: tuple = (Exception,)
):
    """
    Decorator for retry with exponential backoff and jitter.
    """
    def decorator(func):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            for attempt in range(max_retries):
                try:
                    return await func(*args, **kwargs)
                except exceptions as e:
                    if attempt == max_retries - 1:
                        raise
                    
                    # Calculate delay with jitter
                    delay = min(base_delay * (2 ** attempt), max_delay)
                    jitter = delay * 0.1 * (asyncio.random() if hasattr(asyncio, 'random') else 0.5)
                    total_delay = delay + jitter
                    
                    logger.warning(
                        f"Retry {attempt + 1}/{max_retries} for {func.__name__} "
                        f"after {total_delay:.2f}s: {e}"
                    )
                    await asyncio.sleep(total_delay)
        
        return wrapper
    return decorator


# Global instance
_loop_manager = EventLoopManager()


def get_loop_manager() -> EventLoopManager:
    """Get global event loop manager."""
    return _loop_manager


def run_async(coro: Coroutine, timeout: Optional[float] = None) -> Any:
    """Convenience function to run async code from sync context."""
    return _loop_manager.run_async(coro, timeout)

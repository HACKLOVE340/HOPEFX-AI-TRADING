"""
Application lifecycle management.
"""

import asyncio
from enum import Enum, auto


class LifecycleState(Enum):
    UNINITIALIZED = auto()
    INITIALIZING = auto()
    INITIALIZED = auto()
    RUNNING = auto()
    STOPPING = auto()
    STOPPED = auto()


class LifecycleManager:
    """
    Manages application lifecycle state transitions.
    """
    
    def __init__(self):
        self._state = LifecycleState.UNINITIALIZED
        self._lock = asyncio.Lock()
        self._shutdown_hooks: list[callable] = []
    
    async def initialize(self) -> None:
        """Mark as initialized."""
        async with self._lock:
            if self._state != LifecycleState.UNINITIALIZED:
                raise RuntimeError(f"Cannot initialize from {self._state}")
            self._state = LifecycleState.INITIALIZING
            
            # Perform initialization
            await self._do_initialize()
            
            self._state = LifecycleState.INITIALIZED
    
    async def _do_initialize(self) -> None:
        """Override for custom initialization."""
        pass
    
    def mark_initialized(self) -> None:
        """Manual initialization marker."""
        self._state = LifecycleState.INITIALIZED
    
    async def start(self) -> None:
        """Start operations."""
        async with self._lock:
            if self._state != LifecycleState.INITIALIZED:
                raise RuntimeError(f"Cannot start from {self._state}")
            self._state = LifecycleState.RUNNING
    
    async def shutdown(self) -> None:
        """Execute shutdown sequence."""
        async with self._lock:
            if self._state in (LifecycleState.STOPPING, LifecycleState.STOPPED):
                return
            
            self._state = LifecycleState.STOPPING
            
            # Execute shutdown hooks
            for hook in self._shutdown_hooks:
                try:
                    await hook() if asyncio.iscoroutinefunction(hook) else hook()
                except Exception as e:
                    print(f"Shutdown hook error: {e}")
            
            self._state = LifecycleState.STOPPED
    
    def register_shutdown_hook(self, hook: callable) -> None:
        """Register cleanup function."""
        self._shutdown_hooks.append(hook)
    
    @property
    def is_initialized(self) -> bool:
        return self._state in (LifecycleState.INITIALIZED, LifecycleState.RUNNING)
    
    @property
    def is_running(self) -> bool:
        return self._state == LifecycleState.RUNNING
    
    @property
    def state(self) -> LifecycleState:
        return self._state

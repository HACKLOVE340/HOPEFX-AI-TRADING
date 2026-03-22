"""
Production circuit breaker implementation with half-open state,
adaptive thresholds, and comprehensive metrics.
"""

import asyncio
import time
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Callable, Dict, List, Optional, Type, Union

from src.core.logging_config import get_logger
from src.infrastructure.monitoring import CIRCUIT_BREAKER_STATE

logger = get_logger(__name__)


class CircuitState(Enum):
    CLOSED = auto()      # Normal operation
    OPEN = auto()        # Failing, reject fast
    HALF_OPEN = auto()   # Testing recovery


@dataclass
class CircuitBreakerConfig:
    """Configuration for circuit breaker."""
    failure_threshold: int = 5
    success_threshold: int = 3
    timeout_duration: float = 60.0
    half_open_max_calls: int = 3
    error_types: tuple = (Exception,)
    excluded_types: tuple = ()  # Don't count these as failures
    
    # Adaptive settings
    adaptive: bool = True
    slow_call_threshold: float = 2.0  # Seconds
    slow_call_rate_threshold: float = 0.5  # 50% slow calls triggers open


@dataclass
class CallMetrics:
    """Metrics for a single call."""
    start_time: float
    end_time: Optional[float] = None
    success: Optional[bool] = None
    error: Optional[Exception] = None


class CircuitBreaker:
    """
    Production-grade circuit breaker with:
    - Half-open state for gradual recovery
    - Adaptive thresholds based on performance
    - Per-exception-type handling
    - Sliding window for failure counting
    """
    
    def __init__(
        self,
        name: str,
        config: Optional[CircuitBreakerConfig] = None
    ):
        self.name = name
        self.config = config or CircuitBreakerConfig()
        
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._last_failure_time: Optional[float] = None
        self._half_open_calls = 0
        
        # Sliding window of recent calls
        self._recent_calls: List[CallMetrics] = []
        self._window_size = 100
        
        # Metrics
        self._total_calls = 0
        self._total_failures = 0
        self._total_successes = 0
        self._total_slow_calls = 0
        
        self._lock = asyncio.Lock()
        
        # Update Prometheus metric
        CIRCUIT_BREAKER_STATE.labels(name=name).set(0)
    
    @property
    def state(self) -> CircuitState:
        """Get current state with automatic transition."""
        if self._state == CircuitState.OPEN:
            if self._should_attempt_reset():
                return CircuitState.HALF_OPEN
        return self._state
    
    def _should_attempt_reset(self) -> bool:
        """Check if we should try half-open state."""
        if self._last_failure_time is None:
            return True
        
        elapsed = time.monotonic() - self._last_failure_time
        return elapsed >= self.config.timeout_duration
    
    async def call(
        self,
        func: Callable[..., Any],
        *args,
        fallback: Optional[Callable] = None,
        **kwargs
    ) -> Any:
        """
        Execute function with circuit breaker protection.
        
        Args:
            func: Function to protect
            fallback: Fallback function if circuit open
            *args, **kwargs: Arguments to func
        
        Returns:
            Function result or fallback result
        """
        current_state = self.state
        
        if current_state == CircuitState.OPEN:
            if fallback:
                logger.info(f"[{self.name}] Circuit open, using fallback")
                return await self._execute_fallback(fallback, *args, **kwargs)
            raise CircuitBreakerOpenError(f"Circuit {self.name} is OPEN")
        
        if current_state == CircuitState.HALF_OPEN:
            async with self._lock:
                if self._half_open_calls >= self.config.half_open_max_calls:
                    if fallback:
                        return await self._execute_fallback(fallback, *args, **kwargs)
                    raise CircuitBreakerOpenError(f"Circuit {self.name} half-open limit reached")
                self._half_open_calls += 1
        
        # Execute the call
        metrics = CallMetrics(start_time=time.monotonic())
        
        try:
            result = await func(*args, **kwargs)
            
            metrics.end_time = time.monotonic()
            metrics.success = True
            
            # Check for slow call
            duration = metrics.end_time - metrics.start_time
            is_slow = duration > self.config.slow_call_threshold
            
            await self._record_success(is_slow)
            
            return result
            
        except Exception as e:
            metrics.end_time = time.monotonic()
            metrics.success = False
            metrics.error = e
            
            # Check if we should count this error
            if not isinstance(e, self.config.error_types):
                raise  # Don't handle this error type
            
            if isinstance(e, self.config.excluded_types):
                raise  # Don't count excluded types
            
            await self._record_failure()
            
            if fallback:
                return await self._execute_fallback(fallback, *args, **kwargs)
            raise
    
    async def _execute_fallback(
        self,
        fallback: Callable,
        *args,
        **kwargs
    ) -> Any:
        """Execute fallback function."""
        try:
            if asyncio.iscoroutinefunction(fallback):
                return await fallback(*args, **kwargs)
            return fallback(*args, **kwargs)
        except Exception as e:
            logger.error(f"[{self.name}] Fallback failed: {e}")
            raise
    
    async def _record_success(self, is_slow: bool = False) -> None:
        """Record successful call."""
        async with self._lock:
            self._success_count += 1
            self._total_successes += 1
            self._total_calls += 1
            
            if is_slow:
                self._total_slow_calls += 1
            
            # Update sliding window
            self._update_window(True, is_slow)
            
            # Check for state transition
            if self._state == CircuitState.HALF_OPEN:
                if self._success_count >= self.config.success_threshold:
                    self._transition_to(CircuitState.CLOSED)
            else:
                # In closed state, reset failure count on success
                self._failure_count = max(0, self._failure_count - 1)
    
    async def _record_failure(self) -> None:
        """Record failed call."""
        async with self._lock:
            self._failure_count += 1
            self._total_failures += 1
            self._total_calls += 1
            self._last_failure_time = time.monotonic()
            
            self._update_window(False, False)
            
            # Check thresholds
            if self._state == CircuitState.HALF_OPEN:
                # Any failure in half-open goes back to open
                self._transition_to(CircuitState.OPEN)
            elif self._failure_count >= self.config.failure_threshold:
                self._transition_to(CircuitState.OPEN)
            elif self.config.adaptive and self._is_slow_call_rate_high():
                self._transition_to(CircuitState.OPEN)
    
    def _update_window(self, success: bool, is_slow: bool) -> None:
        """Update sliding window of recent calls."""
        self._recent_calls.append(CallMetrics(
            start_time=time.monotonic(),
            success=success
        ))
        
        # Trim window
        if len(self._recent_calls) > self._window_size:
            self._recent_calls = self._recent_calls[-self._window_size:]
    
    def _is_slow_call_rate_high(self) -> bool:
        """Check if slow call rate exceeds threshold."""
        if not self._recent_calls:
            return False
        
        slow_count = sum(
            1 for call in self._recent_calls
            if call.end_time and (call.end_time - call.start_time) > self.config.slow_call_threshold
        )
        
        slow_rate = slow_count / len(self._recent_calls)
        return slow_rate > self.config.slow_call_rate_threshold
    
    def _transition_to(self, new_state: CircuitState) -> None:
        """Transition to new state."""
        old_state = self._state
        self._state = new_state
        
        # Reset counters
        if new_state == CircuitState.CLOSED:
            self._failure_count = 0
            self._success_count = 0
            self._half_open_calls = 0
        elif new_state == CircuitState.HALF_OPEN:
            self._half_open_calls = 0
            self._success_count = 0
        
        # Update metrics
        state_value = 0 if new_state == CircuitState.CLOSED else 1 if new_state == CircuitState.OPEN else 2
        CIRCUIT_BREAKER_STATE.labels(name=self.name).set(state_value)
        
        logger.warning(
            f"[{self.name}] Circuit breaker: {old_state.name} -> {new_state.name}"
        )
    
    def get_metrics(self) -> Dict[str, Any]:
        """Get circuit breaker metrics."""
        return {
            "state": self._state.name,
            "failure_count": self._failure_count,
            "success_count": self._success_count,
            "total_calls": self._total_calls,
            "total_failures": self._total_failures,
            "total_successes": self._total_successes,
            "failure_rate": self._total_failures / max(self._total_calls, 1),
            "slow_call_rate": self._total_slow_calls / max(self._total_calls, 1),
            "last_failure_time": self._last_failure_time
        }


class CircuitBreakerOpenError(Exception):
    """Raised when circuit breaker is open."""
    pass


class CircuitBreakerRegistry:
    """
    Registry for managing multiple circuit breakers.
    """
    
    def __init__(self):
        self._breakers: Dict[str, CircuitBreaker] = {}
    
    def get_or_create(
        self,
        name: str,
        config: Optional[CircuitBreakerConfig] = None
    ) -> CircuitBreaker:
        """Get existing or create new circuit breaker."""
        if name not in self._breakers:
            self._breakers[name] = CircuitBreaker(name, config)
        return self._breakers[name]
    
    def get(self, name: str) -> Optional[CircuitBreaker]:
        """Get circuit breaker by name."""
        return self._breakers.get(name)
    
    def get_all_metrics(self) -> Dict[str, Dict]:
        """Get metrics for all circuit breakers."""
        return {
            name: breaker.get_metrics()
            for name, breaker in self._breakers.items()
        }


# Global registry
_circuit_registry = CircuitBreakerRegistry()


def get_circuit_breaker(
    name: str,
    config: Optional[CircuitBreakerConfig] = None
) -> CircuitBreaker:
    """Get or create circuit breaker."""
    return _circuit_registry.get_or_create(name, config)


def circuit_breaker(
    name: Optional[str] = None,
    failure_threshold: int = 5,
    timeout_duration: float = 60.0,
    excluded_exceptions: tuple = ()
):
    """
    Decorator for adding circuit breaker to function.
    """
    def decorator(func):
        breaker_name = name or func.__name__
        config = CircuitBreakerConfig(
            failure_threshold=failure_threshold,
            timeout_duration=timeout_duration,
            excluded_types=excluded_exceptions
        )
        breaker = get_circuit_breaker(breaker_name, config)
        
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            return await breaker.call(func, *args, **kwargs)
        
        return wrapper
    return decorator

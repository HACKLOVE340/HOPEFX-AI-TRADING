# resilience/circuit_breaker.py
"""
HOPEFX Circuit Breaker & Fault Tolerance
Prevents cascade failures and ensures system stability
"""

import asyncio
from typing import Dict, Callable, Optional
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum, auto


class CircuitState(Enum):
    CLOSED = auto()      # Normal operation
    OPEN = auto()        # Failing, reject requests
    HALF_OPEN = auto()   # Testing if recovered


@dataclass
class CircuitBreakerConfig:
    failure_threshold: int = 5        # Failures before opening
    success_threshold: int = 3       # Successes to close
    timeout_seconds: float = 60.0    # Time before half-open
    half_open_max_calls: int = 3     # Test calls in half-open


class CircuitBreaker:
    """
    Circuit breaker pattern for external service calls.
    """
    
    def __init__(self, name: str, config: CircuitBreakerConfig = None):
        self.name = name
        self.config = config or CircuitBreakerConfig()
        self.state = CircuitState.CLOSED
        self.failures = 0
        self.successes = 0
        self.last_failure_time: Optional[datetime] = None
        self.half_open_calls = 0
        self.total_calls = 0
        self.total_failures = 0
    
    async def call(self, func: Callable, *args, **kwargs):
        """Execute function with circuit breaker protection"""
        
        if self.state == CircuitState.OPEN:
            # Check if we should try half-open
            if self.last_failure_time:
                elapsed = (datetime.utcnow() - self.last_failure_time).total_seconds()
                if elapsed > self.config.timeout_seconds:
                    self.state = CircuitState.HALF_OPEN
                    self.half_open_calls = 0
                    print(f"🔌 Circuit {self.name}: HALF_OPEN (testing recovery)")
                else:
                    raise CircuitBreakerOpen(f"Circuit {self.name} is OPEN")
        
        if self.state == CircuitState.HALF_OPEN:
            if self.half_open_calls >= self.config.half_open_max_calls:
                raise CircuitBreakerOpen(f"Circuit {self.name} half-open limit reached")
            self.half_open_calls += 1
        
        # Execute
        try:
            result = await func(*args, **kwargs)
            self._on_success()
            return result
            
        except Exception as e:
            self._on_failure()
            raise
    
    def _on_success(self):
        """Handle successful call"""
        self.total_calls += 1
        
        if self.state == CircuitState.HALF_OPEN:
            self.successes += 1
            if self.successes >= self.config.success_threshold:
                print(f"✅ Circuit {self.name}: CLOSED (recovered)")
                self.state = CircuitState.CLOSED
                self.failures = 0
                self.successes = 0
        
        elif self.state == CircuitState.CLOSED:
            self.failures = max(0, self.failures - 1)  # Decay failures
    
    def _on_failure(self):
        """Handle failed call"""
        self.total_calls += 1
        self.total_failures += 1
        self.failures += 1
        self.last_failure_time = datetime.utcnow()
        
        if self.state == CircuitState.HALF_OPEN:
            print(f"❌ Circuit {self.name}: OPEN (recovery failed)")
            self.state = CircuitState.OPEN
        
        elif self.state == CircuitState.CLOSED:
            if self.failures >= self.config.failure_threshold:
                print(f"🚫 Circuit {self.name}: OPEN ({self.failures} failures)")
                self.state = CircuitState.OPEN
    
    def get_stats(self) -> Dict:
        return {
            'name': self.name,
            'state': self.state.name,
            'failures': self.failures,
            'successes': self.successes,
            'total_calls': self.total_calls,
            'failure_rate': self.total_failures / max(self.total_calls, 1),
            'last_failure': self.last_failure_time.isoformat() if self.last_failure_time else None
        }


class CircuitBreakerOpen(Exception):
    """Exception when circuit is open"""
    pass


class Bulkhead:
    """
    Bulkhead pattern: Isolate different parts of system.
    Prevents one failure from consuming all resources.
    """
    
    def __init__(self, name: str, max_concurrent: int, max_queue: int):
        self.name = name
        self.semaphore = asyncio.Semaphore(max_concurrent)
        self.queue_size = asyncio.Semaphore(max_queue)
        self.active_count = 0
        self.queue_count = 0
    
    async def execute(self, func: Callable, *args, **kwargs):
        """Execute with bulkhead constraints"""
        if self.queue_size.locked():
            raise BulkheadFull(f"Bulkhead {self.name} queue full")
        
        async with self.queue_size:
            self.queue_count += 1
            
            async with self.semaphore:
                self.queue_count -= 1
                self.active_count += 1
                
                try:
                    return await func(*args, **kwargs)
                finally:
                    self.active_count -= 1
    
    def get_stats(self) -> Dict:
        return {
            'name': self.name,
            'active': self.active_count,
            'queued': self.queue_count
        }


class BulkheadFull(Exception):
    pass


class TimeoutManager:
    """
    Hierarchical timeouts with cancellation.
    """
    
    def __init__(self, default_timeout: float = 30.0):
        self.default_timeout = default_timeout
        self.timeouts: Dict[str, float] = {
            'market_data': 1.0,      # 1 second for price updates
            'order_entry': 5.0,      # 5 seconds for order submission
            'risk_calculation': 10.0,  # 10 seconds for risk
            'ml_inference': 0.1,     # 100ms for ML
            'database_query': 2.0,   # 2 seconds for DB
        }
    
    async def with_timeout(self, operation: str, func: Callable, *args, **kwargs):
        """Execute with operation-specific timeout"""
        timeout = self.timeouts.get(operation, self.default_timeout)
        
        try:
            return await asyncio.wait_for(
                func(*args, **kwargs),
                timeout=timeout
            )
        except asyncio.TimeoutError:
            raise TimeoutError(f"Operation '{operation}' timed out after {timeout}s")

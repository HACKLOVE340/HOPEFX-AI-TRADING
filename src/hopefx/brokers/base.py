# src/hopefx/brokers/base.py
"""
Abstract broker with circuit breaker protection.
"""
from abc import ABC, abstractmethod
from typing import Any

from circuitbreaker import circuit
import tenacity
from tenacity import retry, stop_after_attempt, wait_exponential

from hopefx.data.feeds.base import TickData


class BaseBroker(ABC):
    """Abstract base for all brokers with resilience patterns."""
    
    def __init__(self, name: str):
        self.name = name
        self._connected = False
    
    @abstractmethod
    @circuit(failure_threshold=5, recovery_timeout=60, expected_exception=Exception)
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        reraise=True
    )
    async def connect(self) -> bool:
        """Connect with circuit breaker and retry."""
        pass
    
    @abstractmethod
    @circuit(failure_threshold=3, recovery_timeout=30)
    async def get_tick(self, symbol: str) -> TickData | None:
        """Get current tick with protection."""
        pass
    
    @property
    def is_connected(self) -> bool:
        return self._connected

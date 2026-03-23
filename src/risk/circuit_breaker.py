"""Circuit breaker for risk management."""
from __future__ import annotations

import asyncio
import enum
from typing import Any, Awaitable


class _State(enum.Enum):
    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"


class CircuitBreaker:
    """Async circuit breaker.

    Opens after *failure_threshold* consecutive failures and rejects calls
    until manually reset or a half-open probe succeeds.
    """

    def __init__(self, name: str, failure_threshold: int = 5) -> None:
        self.name = name
        self.failure_threshold = failure_threshold
        self._failures = 0
        self.state = _State.CLOSED

    async def _on_failure(self) -> None:
        self._failures += 1
        if self._failures >= self.failure_threshold:
            self.state = _State.OPEN

    async def _on_success(self) -> None:
        self._failures = 0
        self.state = _State.CLOSED

    async def call(self, coro: Awaitable[Any]) -> Any:
        if self.state == _State.OPEN:
            raise RuntimeError(f"Circuit breaker '{self.name}' is OPEN — call rejected")
        try:
            result = await coro
            await self._on_success()
            return result
        except Exception:
            await self._on_failure()
            raise

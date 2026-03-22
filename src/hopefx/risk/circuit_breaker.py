from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Callable

import structlog

from hopefx.config.settings import settings
from hopefx.events.bus import event_bus
from hopefx.events.schemas import CircuitBreakerEvent, Event, EventType

logger = structlog.get_logger()


class BreakerState(Enum):
    CLOSED = auto()  # Normal operation
    OPEN = auto()    # Rejecting requests
    HALF_OPEN = auto()  # Testing if recovered


@dataclass
class BreakerMetrics:
    failures: int = 0
    successes: int = 0
    last_failure_time: float = 0.0
    consecutive_successes: int = 0


class CircuitBreaker:
    """Multi-threshold circuit breaker for trading."""

    def __init__(
        self,
        name: str,
        failure_threshold: int = 3,
        recovery_timeout: int = 300,
        half_open_max_calls: int = 5,
    ) -> None:
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.half_open_max_calls = half_open_max_calls

        self._state = BreakerState.CLOSED
        self._metrics = BreakerMetrics()
        self._half_open_calls = 0
        self._callbacks: list[Callable[[BreakerState, BreakerState], None]] = []
        self._lock = asyncio.Lock()

    def register_transition_callback(
        self,
        callback: Callable[[BreakerState, BreakerState], None],
    ) -> None:
        """Register state transition callback."""
        self._callbacks.append(callback)

    async def call(self, coro: asyncio.Coroutine) -> any:
        """Execute coroutine with circuit breaker protection."""
        async with self._lock:
            if self._state == BreakerState.OPEN:
                if time.time() - self._metrics.last_failure_time > self.recovery_timeout:
                    self._transition_to(BreakerState.HALF_OPEN)
                    self._half_open_calls = 0
                else:
                    raise CircuitBreakerOpen(f"Circuit {self.name} is OPEN")

            if self._state == BreakerState.HALF_OPEN:
                if self._half_open_calls >= self.half_open_max_calls:
                    raise CircuitBreakerOpen(f"Circuit {self.name} HALF_OPEN limit reached")
                self._half_open_calls += 1

        try:
            result = await coro
            await self._on_success()
            return result
        except Exception as e:
            await self._on_failure()
            raise
        async def _on_success(self) -> None:
        """Handle successful call."""
        async with self._lock:
            self._metrics.successes += 1

            if self._state == BreakerState.HALF_OPEN:
                self._metrics.consecutive_successes += 1
                if self._metrics.consecutive_successes >= self.half_open_max_calls:
                    self._transition_to(BreakerState.CLOSED)
                    self._metrics = BreakerMetrics()  # Reset

    async def _on_failure(self) -> None:
        """Handle failed call."""
        async with self._lock:
            self._metrics.failures += 1
            self._metrics.last_failure_time = time.time()
            self._metrics.consecutive_successes = 0

            if self._state == BreakerState.HALF_OPEN:
                self._transition_to(BreakerState.OPEN)
            elif self._metrics.failures >= self.failure_threshold:
                self._transition_to(BreakerState.OPEN)

                # Publish circuit breaker event
                asyncio.create_task(event_bus.publish(
                    Event(
                        type=EventType.CIRCUIT_BREAKER,
                        payload=CircuitBreakerEvent(
                            breaker_name=self.name,
                            state="open",
                            metrics=self._metrics,
                        ),
                        source="circuit_breaker",
                    )
                ))

    def _transition_to(self, new_state: BreakerState) -> None:
        """Transition to new state."""
        old_state = self._state
        self._state = new_state

        logger.warning(
            "circuit_breaker.transition",
            name=self.name,
            old=old_state.name,
            new=new_state.name,
        )

        for callback in self._callbacks:
            try:
                callback(old_state, new_state)
            except Exception as e:
                logger.exception("circuit_breaker.callback_error", error=str(e))

    @property
    def state(self) -> BreakerState:
        """Current breaker state."""
        return self._state

    @property
    def metrics(self) -> BreakerMetrics:
        """Current metrics."""
        return self._metrics


class CircuitBreakerOpen(Exception):
    """Circuit breaker is open."""
    pass


class MultiCircuitBreaker:
    """Coordinated circuit breakers for different risk dimensions."""

    def __init__(self) -> None:
        self.breakers: dict[str, CircuitBreaker] = {
            "pnl": CircuitBreaker("pnl", failure_threshold=1),  # Immediate on large loss
            "latency": CircuitBreaker("latency", failure_threshold=5, recovery_timeout=60),
            "slippage": CircuitBreaker("slippage", failure_threshold=3),
            "disconnect": CircuitBreaker("disconnect", failure_threshold=2),
        }
        self._global_open = False

    async def check_all(self) -> bool:
        """Check if any breaker is open."""
        for name, breaker in self.breakers.items():
            if breaker.state == BreakerState.OPEN:
                logger.error("multi_breaker.open", breaker=name)
                return False
        return True

    def record_pnl(self, pnl: float) -> None:
        """Record P&L for breaker monitoring."""
        if pnl < -settings.max_daily_loss_pct * float(settings.max_position_risk_pct):
            # Trigger P&L breaker on large loss
            asyncio.create_task(self.breakers["pnl"]._on_failure())

    def record_latency(self, latency_ms: float) -> None:
        """Record latency for monitoring."""
        if latency_ms > 1000:  # 1 second threshold
            asyncio.create_task(self.breakers["latency"]._on_failure())
        else:
            asyncio.create_task(self.breakers["latency"]._on_success())

    def record_slippage(self, slippage: float) -> None:
        """Record execution slippage."""
        if abs(slippage) > settings.xauusd_max_slippage:
            asyncio.create_task(self.breakers["slippage"]._on_failure())
        else:
            asyncio.create_task(self.breakers["slippage"]._on_success())


# Global circuit breakers
multi_breaker = MultiCircuitBreaker()

  
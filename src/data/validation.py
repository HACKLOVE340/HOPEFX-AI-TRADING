"""Tick validation with circuit breaker pattern."""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

import structlog

from src.core.exceptions import DataValidationError, CircuitBreakerError
from src.core.types import Tick

logger = structlog.get_logger()


@dataclass
class ValidationRule:
    """Validation rule configuration."""
    name: str
    check: callable
    critical: bool = True


@dataclass
class CircuitBreaker:
    """Circuit breaker for data feed."""
    failure_threshold: int = 5
    recovery_timeout: float = 30.0
    half_open_max_calls: int = 3
    
    _failures: int = field(default=0, repr=False)
    _last_failure_time: float = field(default=0.0, repr=False)
    _state: str = field(default="CLOSED", repr=False)  # CLOSED, OPEN, HALF_OPEN
    _half_open_calls: int = field(default=0, repr=False)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    
    async def call(self, func, *args, **kwargs):
        """Execute function with circuit breaker."""
        async with self._lock:
            if self._state == "OPEN":
                if time.time() - self._last_failure_time > self.recovery_timeout:
                    self._state = "HALF_OPEN"
                    self._half_open_calls = 0
                    logger.info("Circuit breaker entering HALF_OPEN")
                else:
                    raise CircuitBreakerError("Circuit breaker is OPEN")
            
            if self._state == "HALF_OPEN" and self._half_open_calls >= self.half_open_max_calls:
                raise CircuitBreakerError("Circuit breaker HALF_OPEN limit reached")
            
            if self._state == "HALF_OPEN":
                self._half_open_calls += 1
        
        try:
            result = await func(*args, **kwargs)
            await self._on_success()
            return result
        except Exception as e:
            await self._on_failure()
            raise
    
    async def _on_success(self) -> None:
        async with self._lock:
            if self._state == "HALF_OPEN":
                self._state = "CLOSED"
                self._failures = 0
                logger.info("Circuit breaker CLOSED")
    
    async def _on_failure(self) -> None:
        async with self._lock:
            self._failures += 1
            self._last_failure_time = time.time()
            
            if self._failures >= self.failure_threshold:
                self._state = "OPEN"
                logger.error(f"Circuit breaker OPENED after {self._failures} failures")


class TickValidator:
    """Multi-layer tick validation."""
    
    def __init__(self) -> None:
        self.rules: list[ValidationRule] = [
            ValidationRule("price_positive", self._check_positive_prices),
            ValidationRule("spread_sane", self._check_spread),
            ValidationRule("timestamp_fresh", self._check_timestamp),
            ValidationRule("no_stale", self._check_not_stale, critical=True),
        ]
        self.circuit_breaker = CircuitBreaker()
        self._last_tick: Tick | None = None
        self._last_timestamp: float = time.time()
        self._stale_threshold_sec = 60.0
    
    def _check_positive_prices(self, tick: Tick) -> bool:
        """Ensure bid/ask/mid are positive."""
        return tick.bid > 0 and tick.ask > 0 and tick.mid > 0
    
    def _check_spread(self, tick: Tick) -> bool:
        """Ensure spread is reasonable (< 5% of mid)."""
        spread_pct = (tick.ask - tick.bid) / tick.mid
        return spread_pct < Decimal("0.05")
    
    def _check_timestamp(self, tick: Tick) -> bool:
        """Ensure timestamp is not in future."""
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        return tick.timestamp <= now
    
    def _check_not_stale(self, tick: Tick) -> bool:
        """Ensure feed is not stale."""
        current_time = time.time()
        is_fresh = (current_time - self._last_timestamp) < self._stale_threshold_sec
        self._last_timestamp = current_time
        return is_fresh
    
    async def validate(self, tick: Tick) -> Tick:
        """Validate tick through all rules."""
        async def _do_validate():
            errors = []
            
            for rule in self.rules:
                try:
                    if not rule.check(tick):
                        msg = f"Validation failed: {rule.name}"
                        if rule.critical:
                            errors.append(msg)
                        else:
                            logger.warning(msg, tick=tick.symbol)
                except Exception as e:
                    msg = f"Validation error in {rule.name}: {e}"
                    errors.append(msg)
            
            if errors:
                raise DataValidationError(
                    f"Tick validation failed: {'; '.join(errors)}",
                    context={"tick": tick.model_dump(), "errors": errors}
                )
            
            self._last_tick = tick
            return tick
        
        return await self.circuit_breaker.call(_do_validate)
    
    def get_stats(self) -> dict[str, Any]:
        """Get validation statistics."""
        return {
            "circuit_state": self.circuit_breaker._state,
            "failures": self.circuit_breaker._failures,
            "last_tick": self._last_tick.model_dump() if self._last_tick else None,
        }

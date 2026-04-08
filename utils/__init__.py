# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
HOPEFX Utilities
Common utility functions and helpers
"""

import asyncio
import functools
import hashlib
import inspect
import json  # noqa: F401
import logging
import secrets
import time
from collections import deque
from collections.abc import Callable
from datetime import datetime, timezone

UTC = timezone.utc
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


class RateLimiter:
    """Token bucket rate limiter"""

    def __init__(self, rate: float, burst: int = 1):
        self.rate = rate  # tokens per second
        self.burst = burst  # max tokens
        self.tokens = burst
        self.last_update = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self):
        """Acquire a token"""
        async with self._lock:
            now = time.monotonic()
            elapsed = now - self.last_update
            self.tokens = min(self.burst, self.tokens + elapsed * self.rate)
            self.last_update = now

            if self.tokens < 1:
                sleep_time = (1 - self.tokens) / self.rate
                await asyncio.sleep(sleep_time)
                self.tokens = 0
            else:
                self.tokens -= 1


class RetryWithExponentialBackoff:
    """Decorator for retry with exponential backoff"""

    def __init__(
        self,
        max_retries: int = 3,
        base_delay: float = 1.0,
        exceptions: tuple = (Exception,),
        on_retry: Callable | None = None,
    ):
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.exceptions = exceptions
        self.on_retry = on_retry

    def __call__(self, func):
        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs):
            for attempt in range(self.max_retries):
                try:
                    return await func(*args, **kwargs)
                except self.exceptions as e:
                    if attempt == self.max_retries - 1:
                        raise

                    delay = self.base_delay * (2**attempt)
                    logger.warning("%s failed (attempt %s), retrying in %ss: %s", func.__name__, attempt + 1, delay, e)

                    if self.on_retry:
                        self.on_retry(attempt, e)

                    await asyncio.sleep(delay)

            return None  # Should never reach here

        @functools.wraps(func)
        def sync_wrapper(*args, **kwargs):
            for attempt in range(self.max_retries):
                try:
                    return func(*args, **kwargs)
                except self.exceptions as e:
                    if attempt == self.max_retries - 1:
                        raise

                    delay = self.base_delay * (2**attempt)
                    logger.warning("%s failed (attempt %s), retrying in %ss: %s", func.__name__, attempt + 1, delay, e)

                    if self.on_retry:
                        self.on_retry(attempt, e)

                    time.sleep(delay)

            return None

        return async_wrapper if inspect.iscoroutinefunction(func) else sync_wrapper


class CircuitBreaker:
    """Circuit breaker pattern"""

    def __init__(self, failure_threshold: int = 5, recovery_timeout: float = 60.0):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.failure_count = 0
        self.last_failure_time: float | None = None
        self.is_open = False
        self._half_open = False

    def record_success(self):
        """Record successful call"""
        self.failure_count = max(0, self.failure_count - 1)
        if self._half_open:
            self.is_open = False
            self._half_open = False
            logger.info("Circuit breaker closed (recovered)")

    def record_failure(self) -> bool:
        """Record failed call, returns True if circuit opened"""
        self.failure_count += 1
        self.last_failure_time = time.monotonic()

        if self.failure_count >= self.failure_threshold:
            self.is_open = True
            logger.critical("Circuit breaker OPENED after %s failures", self.failure_count)

            return True
        return False

    def can_execute(self) -> bool:
        """Check if execution allowed"""
        if not self.is_open:
            return True

        # Check if recovery timeout passed
        if self.last_failure_time and (time.monotonic() - self.last_failure_time > self.recovery_timeout):
            self._half_open = True
            return True

        return False


def generate_id(prefix: str = "", length: int = 12) -> str:
    """Generate unique ID"""
    random_part = secrets.token_hex(length // 2)
    return f"{prefix}_{random_part}" if prefix else random_part


def hash_sensitive(data: str, salt: str | None = None) -> str:
    """Hash sensitive data"""
    if salt is None:
        salt = secrets.token_hex(16)
    return hashlib.sha256(f"{data}{salt}".encode()).hexdigest()[:32]


def format_currency(value: float, symbol: str = "$", decimals: int = 2) -> str:
    """Format currency value"""
    return f"{symbol}{value:,.{decimals}f}"


def format_percentage(value: float, decimals: int = 2) -> str:
    """Format percentage"""
    return f"{value * 100:.{decimals}f}%"


def round_decimal(value: float, precision: str = "0.01") -> Decimal:
    """Round to decimal precision"""
    d = Decimal(str(value))
    return d.quantize(Decimal(precision), rounding=ROUND_HALF_UP)


def safe_divide(numerator: float, denominator: float, default: float = 0.0) -> float:
    """Safe division with default"""
    return numerator / denominator if denominator != 0 else default


def chunk_list(lst: list[T], chunk_size: int) -> list[list[T]]:
    """Split list into chunks"""
    return [lst[i : i + chunk_size] for i in range(0, len(lst), chunk_size)]


def timeit(func: Callable) -> Callable:
    """Decorator to time function execution"""

    @functools.wraps(func)
    async def async_wrapper(*args, **kwargs):
        start = time.perf_counter()
        try:
            return await func(*args, **kwargs)
        finally:
            elapsed = time.perf_counter() - start
            logger.debug("%s took %sms", func.__name__, elapsed * 1000)

    @functools.wraps(func)
    def sync_wrapper(*args, **kwargs):
        start = time.perf_counter()
        try:
            return func(*args, **kwargs)
        finally:
            elapsed = time.perf_counter() - start
            logger.debug("%s took %sms", func.__name__, elapsed * 1000)

    return async_wrapper if inspect.iscoroutinefunction(func) else sync_wrapper


def get_timestamp_ms() -> int:
    """Get current timestamp in milliseconds"""
    return int(time.time() * 1000)


def parse_timestamp(timestamp: Any) -> datetime:
    """Parse various timestamp formats"""
    if isinstance(timestamp, datetime):
        return timestamp
    if isinstance(timestamp, int | float):
        # Assume milliseconds if large number
        if timestamp > 1e10:
            timestamp = timestamp / 1000
        return datetime.fromtimestamp(timestamp, tz=UTC)
    if isinstance(timestamp, str):
        return datetime.fromisoformat(timestamp)
    raise ValueError(f"Cannot parse timestamp: {timestamp}")


def deep_merge(base: dict, override: dict) -> dict:
    """Deep merge two dictionaries"""
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def truncate_string(s: str, max_length: int, suffix: str = "...") -> str:
    """Truncate string with suffix"""
    if len(s) <= max_length:
        return s
    return s[: max_length - len(suffix)] + suffix


def validate_symbol(symbol: str) -> bool:
    """Validate trading symbol format"""
    # Basic validation: 6 chars for forex (EURUSD), or contains /
    if len(symbol) == 6 and symbol.isalpha():
        return True
    if "/" in symbol and len(symbol) <= 10:
        return True
    # XAUUSD, etc.
    return len(symbol) <= 10 and symbol.replace("/", "").isalnum()


def calculate_correlation(x: list[float], y: list[float]) -> float:
    """Calculate Pearson correlation"""
    if len(x) != len(y) or len(x) < 2:
        return 0.0

    n = len(x)
    sum_x = sum(x)
    sum_y = sum(y)
    sum_x_sq = sum(xi**2 for xi in x)
    sum_y_sq = sum(yi**2 for yi in y)
    sum_xy = sum(xi * yi for xi, yi in zip(x, y, strict=False))

    numerator = sum_xy - (sum_x * sum_y / n)
    denominator = ((sum_x_sq - sum_x**2 / n) * (sum_y_sq - sum_y**2 / n)) ** 0.5

    return numerator / denominator if denominator != 0 else 0.0


class MovingAverage:
    """Efficient moving average calculation"""

    def __init__(self, window: int):
        self.window = window
        self.values: deque = deque(maxlen=window)
        self.sum = 0.0

    def update(self, value: float) -> float:
        """Add value and return new average"""
        if len(self.values) == self.window:
            self.sum -= self.values[0]

        self.values.append(value)
        self.sum += value

        return self.sum / len(self.values)

    @property
    def average(self) -> float:
        """Current average"""
        return self.sum / len(self.values) if self.values else 0.0


class ExponentialMovingAverage:
    """Exponential moving average"""

    def __init__(self, alpha: float):
        self.alpha = alpha
        self.value: float | None = None

    def update(self, new_value: float) -> float:
        """Update EMA"""
        if self.value is None:
            self.value = new_value
        else:
            self.value = self.alpha * new_value + (1 - self.alpha) * self.value

        return self.value


def get_framework_version() -> str:
    """Get HOPEFX version"""
    return "2.1.0"


def get_all_component_statuses(app=None) -> dict[str, Any]:
    """Get status of all components"""
    statuses = {
        "framework_version": get_framework_version(),
        "timestamp": datetime.now(UTC).isoformat(),
        "components": {},
    }

    if app:
        statuses["components"]["brain"] = app.brain.get_health() if app.brain else None
        statuses["components"]["broker"] = {"connected": app.broker.connected if app.broker else False}
        statuses["components"]["price_engine"] = app.price_engine.get_status() if app.price_engine else None

    return statuses


# Export all utilities
__all__ = [
    "CircuitBreaker",
    "ExponentialMovingAverage",
    "MovingAverage",
    "RateLimiter",
    "RetryWithExponentialBackoff",
    "calculate_correlation",
    "chunk_list",
    "deep_merge",
    "format_currency",
    "format_percentage",
    "generate_id",
    "get_all_component_statuses",
    "get_framework_version",
    "get_timestamp_ms",
    "hash_sensitive",
    "parse_timestamp",
    "round_decimal",
    "safe_divide",
    "timeit",
    "truncate_string",
    "validate_symbol",
]

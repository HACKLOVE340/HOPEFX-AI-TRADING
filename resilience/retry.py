# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# AGPL-3.0 — Share all modifications
"""
resilience/retry.py
====================
Production retry policies with exponential back-off, jitter, and
per-exception filtering.

Usage
-----
    from resilience.retry import retry, RetryPolicy

    # Decorator — retries up to 3 times with exponential back-off
    @retry(max_attempts=3, base_delay=0.5, exceptions=(aiohttp.ClientError,))
    async def fetch_data(url: str) -> dict:
        ...

    # Explicit policy object
    policy = RetryPolicy(max_attempts=5, base_delay=1.0, max_delay=30.0)
    result = await policy.execute(my_coroutine, arg1, kwarg=val)

    # Synchronous retry
    result = policy.execute_sync(my_function, arg1)

Design
------
- Full jitter (random delay in [0, computed_delay]) prevents thundering herd.
- Configurable exception filter — only retries on specified exception types.
- Callback hooks: on_retry, on_success, on_failure for observability.
- Thread-safe: RetryPolicy instances are stateless between calls.
"""

from __future__ import annotations

import asyncio
import contextlib
import functools
import logging
import random
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class RetryPolicy:
    """
    Configurable retry policy with exponential back-off and full jitter.

    Attributes
    ----------
    max_attempts:
        Total number of attempts (1 = no retry).
    base_delay:
        Initial delay in seconds before the first retry.
    max_delay:
        Upper bound on computed delay (before jitter).
    backoff_factor:
        Multiplier applied to delay after each failure (default 2.0 = exponential).
    jitter:
        When True (default), applies full jitter: delay = random(0, computed).
    exceptions:
        Tuple of exception types to retry on. Empty tuple = retry on any Exception.
    on_retry:
        Optional callback(attempt, exc, delay) called before each retry sleep.
    on_success:
        Optional callback(attempt, result) called on success.
    on_failure:
        Optional callback(attempt, exc) called when all attempts are exhausted.
    """

    max_attempts: int = 3
    base_delay: float = 0.5
    max_delay: float = 60.0
    backoff_factor: float = 2.0
    jitter: bool = True
    exceptions: tuple[type[Exception], ...] = field(default_factory=tuple)
    on_retry: Callable[[int, Exception, float], None] | None = None
    on_success: Callable[[int, Any], None] | None = None
    on_failure: Callable[[int, Exception], None] | None = None

    def _compute_delay(self, attempt: int) -> float:
        """Return the sleep duration for the given attempt number (1-based)."""
        raw = min(self.base_delay * (self.backoff_factor ** (attempt - 1)), self.max_delay)
        if self.jitter:
            return random.uniform(0, raw)  # nosec B311 — not cryptographic
        return raw

    def _should_retry(self, exc: Exception) -> bool:
        """Return True if exc matches the configured exception filter."""
        if not self.exceptions:
            return True
        return isinstance(exc, self.exceptions)

    async def execute(self, func: Callable, *args: Any, **kwargs: Any) -> Any:
        """
        Execute an async callable with retry logic.

        Raises the last exception when all attempts are exhausted.
        """
        last_exc: Exception | None = None
        for attempt in range(1, self.max_attempts + 1):
            try:
                if asyncio.iscoroutinefunction(func):
                    result = await func(*args, **kwargs)
                else:
                    loop = asyncio.get_running_loop()
                    result = await loop.run_in_executor(None, functools.partial(func, *args, **kwargs))
                if self.on_success:
                    with contextlib.suppress(Exception):  # nosec B110
                        self.on_success(attempt, result)
                return result
            except Exception as exc:
                last_exc = exc
                if not self._should_retry(exc) or attempt == self.max_attempts:
                    if self.on_failure:
                        with contextlib.suppress(Exception):  # nosec B110
                            self.on_failure(attempt, exc)
                    raise
                delay = self._compute_delay(attempt)
                logger.warning(
                    "retry: attempt %d/%d failed (%s: %s) — retrying in %.2fs",
                    attempt,
                    self.max_attempts,
                    type(exc).__name__,
                    exc,
                    delay,
                )
                if self.on_retry:
                    with contextlib.suppress(Exception):  # nosec B110
                        self.on_retry(attempt, exc, delay)
                await asyncio.sleep(delay)
        # Should never reach here, but satisfy type checker
        raise last_exc  # type: ignore[misc]

    def execute_sync(self, func: Callable, *args: Any, **kwargs: Any) -> Any:
        """
        Execute a synchronous callable with retry logic.

        Raises the last exception when all attempts are exhausted.
        """
        last_exc: Exception | None = None
        for attempt in range(1, self.max_attempts + 1):
            try:
                result = func(*args, **kwargs)
                if self.on_success:
                    with contextlib.suppress(Exception):  # nosec B110
                        self.on_success(attempt, result)
                return result
            except Exception as exc:
                last_exc = exc
                if not self._should_retry(exc) or attempt == self.max_attempts:
                    if self.on_failure:
                        with contextlib.suppress(Exception):  # nosec B110
                            self.on_failure(attempt, exc)
                    raise
                delay = self._compute_delay(attempt)
                logger.warning(
                    "retry_sync: attempt %d/%d failed (%s: %s) — retrying in %.2fs",
                    attempt,
                    self.max_attempts,
                    type(exc).__name__,
                    exc,
                    delay,
                )
                if self.on_retry:
                    with contextlib.suppress(Exception):  # nosec B110
                        self.on_retry(attempt, exc, delay)
                time.sleep(delay)
        raise last_exc  # type: ignore[misc]


def retry(
    max_attempts: int = 3,
    base_delay: float = 0.5,
    max_delay: float = 60.0,
    backoff_factor: float = 2.0,
    jitter: bool = True,
    exceptions: tuple[type[Exception], ...] = (),
) -> Callable:
    """
    Decorator factory that wraps an async or sync function with retry logic.

    Example
    -------
        @retry(max_attempts=3, base_delay=1.0, exceptions=(IOError, TimeoutError))
        async def fetch(url: str) -> bytes:
            ...
    """
    policy = RetryPolicy(
        max_attempts=max_attempts,
        base_delay=base_delay,
        max_delay=max_delay,
        backoff_factor=backoff_factor,
        jitter=jitter,
        exceptions=exceptions,
    )

    def decorator(func: Callable) -> Callable:
        if asyncio.iscoroutinefunction(func):

            @functools.wraps(func)
            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                return await policy.execute(func, *args, **kwargs)

            return async_wrapper
        else:

            @functools.wraps(func)
            def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
                return policy.execute_sync(func, *args, **kwargs)

            return sync_wrapper

    return decorator


# ── Pre-built policies for common use cases ───────────────────────────────────

#: Fast retry for Redis operations (3 attempts, 100 ms base, 2 s max)
redis_retry = RetryPolicy(
    max_attempts=3,
    base_delay=0.1,
    max_delay=2.0,
    backoff_factor=2.0,
    jitter=True,
)

#: Conservative retry for broker API calls (5 attempts, 1 s base, 30 s max)
broker_retry = RetryPolicy(
    max_attempts=5,
    base_delay=1.0,
    max_delay=30.0,
    backoff_factor=2.0,
    jitter=True,
)

#: Retry for HTTP/news API calls (3 attempts, 0.5 s base, 10 s max)
http_retry = RetryPolicy(
    max_attempts=3,
    base_delay=0.5,
    max_delay=10.0,
    backoff_factor=2.0,
    jitter=True,
)

#: Retry for database operations (3 attempts, 0.2 s base, 5 s max)
db_retry = RetryPolicy(
    max_attempts=3,
    base_delay=0.2,
    max_delay=5.0,
    backoff_factor=2.0,
    jitter=True,
)

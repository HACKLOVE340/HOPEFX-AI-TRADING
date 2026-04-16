# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
utils/production_guard.py
=========================
Centralized production environment guard.

Provides a single enforcement point for blocking mock/stub/synthetic
implementations from running in production or staging environments.

Usage
-----
    from utils.production_guard import assert_not_production

    class MockFoo:
        def __init__(self):
            assert_not_production("MockFoo", replacement="RealFoo")
            ...

    # Or as a decorator:
    @production_blocked("SyntheticDataGenerator")
    def generate_synthetic_data():
        ...
"""

from __future__ import annotations

import functools
import logging
import os
from typing import Callable, TypeVar

logger = logging.getLogger(__name__)

# Environments where mocks/stubs/synthetic data are forbidden
_BLOCKED_ENVS: frozenset[str] = frozenset({"production", "prod", "staging", "stage"})

F = TypeVar("F", bound=Callable)


def current_env() -> str:
    """Return the normalised APP_ENV value (lowercase)."""
    return os.getenv("APP_ENV", "production").lower()


def is_production() -> bool:
    """Return True when running in a production or staging environment."""
    return current_env() in _BLOCKED_ENVS


def assert_not_production(
    class_or_func_name: str,
    *,
    replacement: str = "a real implementation",
    extra: str = "",
) -> None:
    """
    Raise RuntimeError if the current environment is production or staging.

    Parameters
    ----------
    class_or_func_name : str
        Name of the mock/stub/synthetic class or function being guarded.
    replacement : str
        Name of the real implementation to use instead.
    extra : str
        Optional extra guidance appended to the error message.

    Raises
    ------
    RuntimeError
        When APP_ENV is 'production', 'prod', 'staging', or 'stage'.
    """
    env = current_env()
    if env in _BLOCKED_ENVS:
        msg = (
            f"{class_or_func_name} cannot be used in {env} (APP_ENV={env}). "
            f"Use {replacement} instead."
        )
        if extra:
            msg = f"{msg} {extra}"
        raise RuntimeError(msg)


def production_blocked(
    name: str,
    *,
    replacement: str = "a real implementation",
    extra: str = "",
) -> Callable[[F], F]:
    """
    Decorator that raises RuntimeError when the decorated function is called
    in a production or staging environment.

    Example
    -------
        @production_blocked("generate_synthetic_ohlcv", replacement="real market data feed")
        def generate_synthetic_ohlcv(n: int) -> pd.DataFrame:
            ...
    """
    def decorator(func: F) -> F:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            assert_not_production(name, replacement=replacement, extra=extra)
            return func(*args, **kwargs)
        return wrapper  # type: ignore[return-value]
    return decorator

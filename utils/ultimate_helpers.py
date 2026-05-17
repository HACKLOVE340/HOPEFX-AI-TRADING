# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
# utils/ultimate_helpers.py
"""
Helper functions for HOPEFX Ultimate
"""

import asyncio
import time
from collections.abc import Callable
from functools import wraps
from typing import Any

import logging

try:
    import psutil as _psutil

    _PSUTIL_OK = True
except ImportError:
    _psutil = None  # type: ignore[assignment]
    _PSUTIL_OK = False

logger = logging.getLogger(__name__)


try:
    import torch

    HAS_TORCH = True
except ImportError:
    torch = None  # type: ignore[assignment]
    HAS_TORCH = False


def async_retry(max_attempts: int = 3, delay: float = 1.0):
    """Decorator for async retry logic"""

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs) -> Any:
            for attempt in range(max_attempts):
                try:
                    return await func(*args, **kwargs)
                except Exception as e:
                    if attempt == max_attempts - 1:
                        raise
                    logger.info("Retry %s/%s: %s", attempt + 1, max_attempts, e)
                    await asyncio.sleep(delay * (2**attempt))
            return None

        return wrapper

    return decorator


def measure_latency(func: Callable) -> Callable:
    """Decorator to measure function latency"""

    @wraps(func)
    async def async_wrapper(*args, **kwargs):
        start = time.time_ns()
        result = await func(*args, **kwargs)
        latency_ms = (time.time_ns() - start) / 1e6
        return result, latency_ms

    @wraps(func)
    def sync_wrapper(*args, **kwargs):
        start = time.time_ns()
        result = func(*args, **kwargs)
        latency_ms = (time.time_ns() - start) / 1e6
        return result, latency_ms

    return async_wrapper if asyncio.iscoroutinefunction(func) else sync_wrapper


class PerformanceProfiler:
    """Profile system performance"""

    def __init__(self):
        self.metrics = {}

    def snapshot(self) -> dict:
        """Get current system performance"""
        if _PSUTIL_OK:
            cpu = _psutil.cpu_percent(interval=0)
            mem = _psutil.virtual_memory().percent
            dio = _psutil.disk_io_counters()
            disk_io = dio._asdict() if dio else {}
        else:
            cpu, mem, disk_io = 0.0, 0.0, {}
        return {
            "cpu_percent": cpu,
            "memory_percent": mem,
            "disk_io": disk_io,
            "gpu_memory": torch.cuda.memory_allocated() / 1e9 if HAS_TORCH and torch.cuda.is_available() else 0,
            "gpu_memory_cached": torch.cuda.memory_reserved() / 1e9 if HAS_TORCH and torch.cuda.is_available() else 0,
        }

    def log(self, component: str, metric: str, value: float):
        """Log a metric"""
        if component not in self.metrics:
            self.metrics[component] = {}
        if metric not in self.metrics[component]:
            self.metrics[component][metric] = []
        self.metrics[component][metric].append((time.time(), value))

    def get_stats(self, component: str, metric: str) -> dict:
        """Get statistics for a metric"""
        if component not in self.metrics or metric not in self.metrics[component]:
            return {}

        values = [v for _, v in self.metrics[component][metric][-1000:]]
        if not values:
            return {}

        import numpy as np

        return {
            "mean": np.mean(values),
            "std": np.std(values),
            "min": np.min(values),
            "max": np.max(values),
            "p50": np.percentile(values, 50),
            "p99": np.percentile(values, 99),
        }

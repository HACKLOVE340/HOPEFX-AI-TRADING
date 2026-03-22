# utils/ultimate_helpers.py
"""
Helper functions for HOPEFX Ultimate
"""

import asyncio
import time
from functools import wraps
from typing import Callable, Any
import psutil
import torch


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
                    print(f"Retry {attempt + 1}/{max_attempts}: {e}")
                    await asyncio.sleep(delay * (2 ** attempt))
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
        return {
            'cpu_percent': psutil.cpu_percent(interval=1),
            'memory_percent': psutil.virtual_memory().percent,
            'disk_io': psutil.disk_io_counters()._asdict() if psutil.disk_io_counters() else {},
            'gpu_memory': torch.cuda.memory_allocated() / 1e9 if torch.cuda.is_available() else 0,
            'gpu_memory_cached': torch.cuda.memory_reserved() / 1e9 if torch.cuda.is_available() else 0
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
            'mean': np.mean(values),
            'std': np.std(values),
            'min': np.min(values),
            'max': np.max(values),
            'p50': np.percentile(values, 50),
            'p99': np.percentile(values, 99)
        }

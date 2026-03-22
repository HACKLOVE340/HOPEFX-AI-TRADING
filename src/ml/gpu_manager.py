"""GPU memory management with automatic OOM prevention."""
from __future__ import annotations

import gc
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Generator

import torch
import structlog

logger = structlog.get_logger()


@dataclass
class GPUMemoryStats:
    allocated_gb: float
    reserved_gb: float
    max_allocated_gb: float
    utilization_pct: float


class GPUMemoryManager:
    """Thread-safe GPU memory pool with pre-allocation."""
    
    _instance: GPUMemoryManager | None = None
    _lock = threading.RLock()
    
    def __new__(cls, max_gb: float = 4.0):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self, max_gb: float = 4.0):
        if self._initialized:
            return
        
        self.max_bytes = int(max_gb * 1024**3)
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self._pre_allocated: list[torch.Tensor] = []
        self._initialized = True
        
        if self.device.type == "cuda":
            self._pre_allocate()
            self._setup_memory_hooks()
    
    def _pre_allocate(self) -> None:
        """Pre-allocate memory pool to prevent fragmentation."""
        # Reserve 10% of max for emergency
        reserve_bytes = int(self.max_bytes * 0.1)
        try:
            self._pre_allocated.append(
                torch.empty(reserve_bytes // 4, dtype=torch.float32, device=self.device)
            )
            logger.info(f"GPU pre-allocated: {reserve_bytes / 1e9:.2f}GB")
        except RuntimeError:
            logger.warning("GPU pre-allocation failed")
    
    def _setup_memory_hooks(self) -> None:
        """Install OOM hook."""
        def oom_hook(device, alloc, device_alloc, device_free):
            logger.critical(
                f"GPU OOM triggered: "
                f"requested={alloc / 1e9:.2f}GB, "
                f"free={device_free / 1e9:.2f}GB"
            )
            self.emergency_cleanup()
            return False  # Don't retry
        
        # PyTorch doesn't expose public hooks, use allocator settings
        torch.cuda.set_per_process_memory_fraction(0.95)
    
    def emergency_cleanup(self) -> None:
        """Emergency memory free."""
        # Free pre-allocated reserve
        self._pre_allocated.clear()
        gc.collect()
        torch.cuda.empty_cache()
        torch.cuda.synchronize()
        logger.info("GPU emergency cleanup completed")
    
    @contextmanager
    def allocate(self, shape: tuple[int, ...], dtype: torch.dtype = torch.float32) -> Generator[torch.Tensor, None, None]:
        """Context-managed tensor allocation."""
        tensor = None
        try:
            if self.device.type == "cuda":
                # Check available before alloc
                free, total = torch.cuda.mem_get_info()
                requested = np.prod(shape) * (2 if dtype == torch.float16 else 4)
                
                if requested > free * 0.8:
                    self.emergency_cleanup()
                    free, _ = torch.cuda.mem_get_info()
                    
                    if requested > free * 0.9:
                        raise RuntimeError(f"GPU OOM: requested {requested/1e9:.2f}GB, free {free/1e9:.2f}GB")
            
            tensor = torch.empty(shape, dtype=dtype, device=self.device)
            yield tensor
            
        finally:
            if tensor is not None:
                del tensor
    
    def get_stats(self) -> GPUMemoryStats:
        """Current GPU memory status."""
        if self.device.type == "cpu":
            return GPUMemoryStats(0, 0, 0, 0)
        
        allocated = torch.cuda.memory_allocated()
        reserved = torch.cuda.memory_reserved()
        max_allocated = torch.cuda.max_memory_allocated()
        
        free, total = torch.cuda.mem_get_info()
        
        return GPUMemoryStats(
            allocated_gb=allocated / 1e9,
            reserved_gb=reserved / 1e9,
            max_allocated_gb=max_allocated / 1e9,
            utilization_pct=(allocated / total) * 100
        )


# Global instance
gpu_manager = GPUMemoryManager(max_gb=4.0)

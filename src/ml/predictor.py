# In src/ml/predictor.py
try:
    import torch

    HAS_TORCH = True
except ImportError:
    torch = None  # type: ignore[assignment]
    HAS_TORCH = False
from contextlib import contextmanager


class GPUMemoryManager:
    """Context manager for GPU memory."""

    def __init__(self, max_gb: float = 4.0):
        if not HAS_TORCH:
            raise ImportError(
                "torch is required for this feature. Install with: pip install torch"
            )
        self.max_bytes = max_gb * 1024**3
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    @contextmanager
    def allocate(self, tensor_shape: tuple):
        """Allocate with automatic cleanup."""
        try:
            if self.device.type == "cuda":
                torch.cuda.reset_peak_memory_stats()

            yield self.device

            if self.device.type == "cuda":
                used = torch.cuda.max_memory_allocated()
                if used > self.max_bytes:
                    torch.cuda.empty_cache()
                    logger.warning(f"GPU memory cleared: {used / 1e9:.2f}GB")
        finally:
            if self.device.type == "cuda":
                torch.cuda.synchronize()

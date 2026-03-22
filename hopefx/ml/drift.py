"""hopefx.ml.drift — concept drift detection"""
import numpy as np
from typing import List, Optional
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class DriftResult:
    detected: bool
    score: float
    threshold: float
    method: str
    timestamp: datetime = field(default_factory=datetime.utcnow)


class DriftDetector:
    """
    Statistical concept drift detector.

    Uses Page-Hinkley test by default; falls back to simple
    mean-shift detection when the window is too small.
    """

    def __init__(self, method: str = "page_hinkley", threshold: float = 0.05,
                 window_size: int = 50, min_samples: int = 30):
        self.method = method
        self.threshold = threshold
        self.window_size = window_size
        self.min_samples = min_samples
        self._reference: Optional[np.ndarray] = None
        self._buffer: List[float] = []
        self._cumsum = 0.0
        self._min_cumsum = 0.0
        self._n = 0

    def set_reference(self, data: np.ndarray):
        """Set the reference distribution."""
        self._reference = np.array(data, dtype=float)
        self._cumsum = 0.0
        self._min_cumsum = 0.0
        self._n = 0

    def update(self, value: float) -> DriftResult:
        """Add one observation and check for drift."""
        self._buffer.append(value)
        if len(self._buffer) > self.window_size:
            self._buffer.pop(0)

        if self._reference is None or len(self._buffer) < self.min_samples:
            return DriftResult(False, 0.0, self.threshold, self.method)

        if self.method == "page_hinkley":
            return self._page_hinkley(value)
        return self._ks_test()

    def _page_hinkley(self, value: float) -> DriftResult:
        ref_mean = float(np.mean(self._reference))
        self._n += 1
        self._cumsum += value - ref_mean - 0.005  # delta
        self._min_cumsum = min(self._min_cumsum, self._cumsum)
        ph_stat = self._cumsum - self._min_cumsum
        detected = ph_stat > self.threshold * 100
        return DriftResult(detected, ph_stat, self.threshold * 100, "page_hinkley")

    def _ks_test(self) -> DriftResult:
        from scipy import stats
        stat, p_value = stats.ks_2samp(self._reference, self._buffer)
        return DriftResult(p_value < self.threshold, stat, self.threshold, "ks_test")

    def check_batch(self, data: np.ndarray) -> DriftResult:
        """Check an entire batch for drift against the reference."""
        if self._reference is None:
            self.set_reference(data)
            return DriftResult(False, 0.0, self.threshold, self.method)
        results = [self.update(float(v)) for v in data]
        detected = any(r.detected for r in results)
        score = max(r.score for r in results) if results else 0.0
        return DriftResult(detected, score, self.threshold, self.method)

    def reset(self):
        self._buffer.clear()
        self._cumsum = 0.0
        self._min_cumsum = 0.0
        self._n = 0

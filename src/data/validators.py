"""
Tick validation and outlier detection.
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from statistics import mean, stdev
from typing import Deque

from src.domain.models import TickData
from src.core.exceptions import ValidationFailed


class TickValidator:
    """
    Real-time tick validation with Z-score outlier detection.
    Maintains rolling window for statistical analysis.
    """
    
    def __init__(
        self,
        window_size: int = 1000,
        z_score_threshold: float = 4.0,
        max_spread_pct: float = 0.01,
        max_latency_ms: int = 5000
    ):
        self._window: Deque[Decimal] = Deque(maxlen=window_size)
        self._z_threshold = z_score_threshold
        self._max_spread_pct = Decimal(str(max_spread_pct))
        self._max_latency = timedelta(milliseconds=max_latency_ms)
        self._last_timestamp: datetime | None = None
    
    def validate(self, tick: TickData) -> tuple[bool, str | None]:
        """
        Validate tick data.
        Returns (is_valid, error_message).
        """
        now = datetime.now(timezone.utc)
        
        # 1. Timestamp sanity
        if tick.timestamp > now + timedelta(seconds=1):
            return False, "Future timestamp"
        
        if self._last_timestamp and tick.timestamp < self._last_timestamp:
            return False, "Out-of-order timestamp"
        
        latency = now - tick.timestamp
        if latency > self._max_latency:
            return False, f"Stale data: {latency.total_seconds()}s"
        
        # 2. Price sanity
        if tick.bid <= 0 or tick.ask <= 0:
            return False, "Non-positive price"
        
        spread = (tick.ask - tick.bid) / tick.mid
        if spread > self._max_spread_pct:
            return False, f"Excessive spread: {spread:.4%}"
        
        # 3. Statistical outlier detection
        if len(self._window) >= 30:
            prices = list(self._window)
            avg = mean(prices)
            std = stdev(prices)
            
            if std > 0:
                z_score = abs((tick.mid - avg) / std)
                if z_score > self._z_threshold:
                    return False, f"Outlier detected: Z={z_score:.2f}"
        
        # Update window
        self._window.append(tick.mid)
        self._last_timestamp = tick.timestamp
        
        return True, None
    
    def reset(self) -> None:
        """Clear validation state."""
        self._window.clear()
        self._last_timestamp = None

"""
Performance Tracking

Tracks and analyzes trader performance metrics.
"""

from typing import Dict, List
from decimal import Decimal
from datetime import datetime, timedelta


class PerformanceMetric:
    """Performance metric data"""
    def __init__(self, user_id: str, period: str):
        self.user_id = user_id
        self.period = period
        self.total_return = Decimal('0.0')
        self.win_rate = Decimal('0.0')
        self.profit_factor = Decimal('0.0')
        self.sharpe_ratio = Decimal('0.0')
        self.max_drawdown = Decimal('0.0')
        self.total_trades = 0
        self.updated_at = datetime.utcnow()


class PerformanceTracker:
    """Tracks user performance metrics"""

    def __init__(self):
        self.metrics: Dict[str, PerformanceMetric] = {}

    def record_trade(
        self,
        user_id: str,
        profit: Decimal,
        period: str = "all_time"
    ) -> None:
        """Record a trade result"""
        key = f"{user_id}_{period}"

        if key not in self.metrics:
            self.metrics[key] = PerformanceMetric(user_id, period)

        metric = self.metrics[key]
        metric.total_trades += 1
        metric.total_return += profit
        metric.updated_at = datetime.utcnow()

    def get_performance(
        self,
        user_id: str,
        period: str = "all_time"
    ) -> PerformanceMetric:
        """Get performance metrics for a user"""
        key = f"{user_id}_{period}"
        return self.metrics.get(key, PerformanceMetric(user_id, period))

    def calculate_win_rate(self, user_id: str, winning_trades: int, total_trades: int) -> Decimal:
        """Calculate win rate"""
        if total_trades == 0:
            return Decimal('0.0')
        return Decimal(winning_trades) / Decimal(total_trades) * Decimal('100.0')

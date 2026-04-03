# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""Performance tracking for social trading."""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal


@dataclass
class PerformanceMetric:
    user_id: str
    period: str = "all"
    total_return: Decimal = field(default_factory=lambda: Decimal("0.0"))
    total_trades: int = 0
    winning_trades: int = 0
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))


class PerformanceTracker:
    """Tracks per-user trading performance."""

    def __init__(self):
        # (user_id, period) -> PerformanceMetric
        self.metrics: dict[tuple, PerformanceMetric] = {}

    def _key(self, user_id: str, period: str) -> tuple:
        return (user_id, period)

    def record_trade(self, user_id: str, pnl: Decimal, period: str = "all") -> None:
        key = self._key(user_id, period)
        if key not in self.metrics:
            self.metrics[key] = PerformanceMetric(user_id=user_id, period=period)
        m = self.metrics[key]
        m.total_return += pnl
        m.total_trades += 1
        if pnl > 0:
            m.winning_trades += 1
        m.updated_at = datetime.now(UTC)

    def get_performance(self, user_id: str, period: str = "all") -> PerformanceMetric:
        key = self._key(user_id, period)
        if key not in self.metrics:
            return PerformanceMetric(user_id=user_id, period=period)
        return self.metrics[key]

    def calculate_win_rate(self, user_id: str, wins: int, total: int) -> Decimal:
        if total == 0:
            return Decimal("0.0")
        return Decimal(str(round(wins / total * 100, 1)))

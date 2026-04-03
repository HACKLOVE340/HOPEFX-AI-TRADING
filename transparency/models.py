# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""transparency/models.py — Data models for execution transparency."""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class ExecutionQuality(Enum):
    """Execution quality ratings"""

    EXCELLENT = "excellent"
    GOOD = "good"
    AVERAGE = "average"
    POOR = "poor"
    VERY_POOR = "very_poor"


@dataclass
class ExecutionRecord:
    """Record of a single trade execution"""

    execution_id: str
    order_id: str
    symbol: str
    side: str  # BUY or SELL
    requested_price: float
    executed_price: float
    requested_size: float
    executed_size: float
    slippage: float  # In pips/points
    slippage_cost: float  # In account currency
    latency_ms: float  # Execution latency in milliseconds
    fill_ratio: float  # Percentage filled
    timestamp: datetime
    broker: str
    market_conditions: dict[str, Any] = field(default_factory=dict)


@dataclass
class ExecutionReport:
    """Summary report of execution quality"""

    report_id: str
    period_start: datetime
    period_end: datetime
    total_executions: int
    avg_slippage: float
    max_slippage: float
    min_slippage: float
    positive_slippage_count: int  # Better than requested
    negative_slippage_count: int  # Worse than requested
    zero_slippage_count: int
    avg_latency_ms: float
    avg_fill_ratio: float
    total_slippage_cost: float
    execution_quality: ExecutionQuality
    broker_comparison: dict[str, dict[str, float]]

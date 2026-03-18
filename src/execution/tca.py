"""Institutional-grade transaction cost analysis."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any, Callable

import numpy as np
import structlog

from src.core.types import Fill, Order, Side, Tick

logger = structlog.get_logger()


class BenchmarkType(Enum):
    ARRIVAL = "arrival"  # Price at order creation
    VWAP = "vwap"        # Volume-weighted average price
    TWAP = "twap"        # Time-weighted average price
    CLOSE = "close"      # Previous close
    OPEN = "open"        # Opening price


@dataclass
class MarketImpactModel:
    """I-Star model implementation."""
    permanent_impact: Decimal = Decimal("0")
    temporary_impact: Decimal = Decimal("0")
    
    def calculate(
        self,
        order_size: Decimal,
        avg_daily_volume: Decimal,
   

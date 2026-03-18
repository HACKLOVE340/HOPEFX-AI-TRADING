"""Feature engineering: vol clustering, order flow, Hawkes, cycles."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd
import structlog
from scipy import stats

from src.core.types import Tick, OHLCV
from src.features.transforms import CyclicalEncoder, RobustFeatureScaler

logger = structlog.get_logger()


@dataclass
class FeatureVector:
    """Computed features."""
    timestamp: pd.Timestamp
    symbol: str
    
    # Price features
    returns: float
    log_returns: float
    volatility: float
    
    # Technical indicators
    rsi: float
    atr: float
    macd: float
    macd_signal: float
    obv: float
    vwap_dev

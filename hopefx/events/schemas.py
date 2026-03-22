"""hopefx.events.schemas — event schema re-exports"""
from src.core.events import (
    Event, TickEvent as TickData, SignalEvent, OrderEvent,
    FillEvent as OrderFill, PositionEvent, RiskEvent, HealthEvent,
)
from enum import Enum


class EventType(str, Enum):
    TICK = "TICK"
    SIGNAL = "SIGNAL"
    ORDER = "ORDER"
    FILL = "FILL"
    POSITION = "POSITION"
    RISK = "RISK"
    HEALTH = "HEALTH"


# Additional schemas used by integration tests
from dataclasses import dataclass, field
from typing import List, Optional
from datetime import datetime


@dataclass
class FeatureVector:
    symbol: str
    features: List[float] = field(default_factory=list)
    timestamp: datetime = field(default_factory=datetime.utcnow)


@dataclass
class Prediction:
    symbol: str
    direction: str
    confidence: float
    model: str = "ensemble"
    timestamp: datetime = field(default_factory=datetime.utcnow)

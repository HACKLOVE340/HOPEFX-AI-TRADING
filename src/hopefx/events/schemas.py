from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import Enum, auto
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, field_validator


class EventType(str, Enum):
    # Market Data
    TICK = "tick"
    BAR = "bar"
    ORDERBOOK = "orderbook"

    # ML
    FEATURE_VECTOR = "feature_vector"
    PREDICTION = "prediction"
    DRIFT_ALERT = "drift_alert"
    MODEL_DEPLOYMENT = "model_deployment"

    # Trading
    SIGNAL = "signal"
    ORDER_REQUEST = "order_request"
    ORDER_FILL = "order_fill"
    POSITION_UPDATE = "position_update"
    ORDER_CANCEL = "order_cancel"

    # Risk
    RISK_VIOLATION = "risk_violation"
    CIRCUIT_BREAKER = "circuit_breaker"
    MARGIN_CALL = "margin_call"

    # Compliance
    COMPLIANCE_BREACH = "compliance_breach"
    AUDIT_EVENT = "audit_event"

    # System
    HEARTBEAT = "heartbeat"
    ERROR = "error"
    SHUTDOWN = "shutdown"
    RECOVERY = "recovery"


class TickData(BaseModel):
    symbol: str
    timestamp: datetime
    bid: Decimal = Field(..., decimal_places=5)
    ask: Decimal = Field(..., decimal_places=5)
    volume: Decimal = Field(default=Decimal("0"), decimal_places=2)
    source: str = "unknown"

    @field_validator("bid", "ask", mode="before")
    @classmethod
    def validate_prices(cls, v: Any) -> Decimal:
        if isinstance(v, float):
            return Decimal(str(v))
        return Decimal(v)

    @property
    def spread(self) -> Decimal:
        return self.ask - self.bid

    @property
    def mid(self) -> Decimal:
        return (self.bid + self.ask) / 2


class FeatureVector(BaseModel):
    symbol: str
    timestamp: datetime
    features: dict[str, float]
    raw_data: Optional[TickData] = None
    version: str = "1.0"


class Prediction(BaseModel):
    symbol: str
    timestamp: datetime
    model_id: str
    model_version: str
    direction: Literal["long", "short", "neutral"]
    confidence: float = Field(..., ge=0.0, le=1.0)
    target_price: Optional[Decimal] = None
    stop_loss: Optional[Decimal] = None
    take_profit: Optional[Decimal] = None
    feature_vector: Optional[FeatureVector] = None
    regime: str = "unknown"  # trending, ranging, volatile


class Signal(BaseModel):
    symbol: str
    timestamp: datetime
    direction: Literal["buy", "sell", "close"]
    confidence: float
    size: Decimal
    order_type: Literal["market", "limit", "stop"] = "market"
    limit_price: Optional[Decimal] = None
    stop_price: Optional[Decimal] = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    strategy_id: Optional[str] = None


class OrderFill(BaseModel):
    order_id: str
    symbol: str
    timestamp: str
    side: Literal["buy", "sell"]
    filled_qty: Decimal
    filled_price: Decimal
    commission: Decimal = Decimal("0")
    slippage: Decimal = Decimal("0")
    execution_venue: str = "unknown"
    liquidity_type: str = "unknown"  # maker, taker


class RiskViolation(BaseModel):
    violation_type: Literal[
        "max_position_size",
        "daily_loss_limit",
        "leverage_limit",
        "concentration_limit",
        "margin_call",
        "prop_rule_breach"
    ]
    current_value: float
    limit_value: float
    symbol: Optional[str] = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    auto_action: Optional[str] = None


class ComplianceBreach(BaseModel):
    regulation: str  # MiFID2, EMIR, CFTC
    rule_id: str
    severity: Literal["warning", "violation", "critical"]
    details: dict[str, Any]
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class CircuitBreakerEvent(BaseModel):
    breaker_name: str
    state: str
    metrics: Any
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class Event(BaseModel):
    id: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    type: EventType
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    payload: Any
    priority: int = Field(default=5, ge=1, le=10)
    source: str = "system"
    trace_id: Optional[str] = None
    correlation_id: Optional[str] = None

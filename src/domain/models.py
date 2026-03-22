"""
Pydantic v2 domain models with strict validation.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.domain.enums import (
    BrokerType,
    DataFrequency,
    OrderStatus,
    OrderType,
    PositionStatus,
    PropFirm,
    TimeInForce,
    TradeDirection,
)


class TickData(BaseModel):
    """Validated tick data with nanosecond precision."""
    model_config = ConfigDict(frozen=True)
    
    symbol: str = Field(pattern=r"^[A-Z]{3,6}$")
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    bid: Decimal = Field(decimal_places=5, gt=0)
    ask: Decimal = Field(decimal_places=5, gt=0)
    mid: Decimal = Field(decimal_places=5, gt=0)
    volume: int = Field(ge=0)
    source: str = Field(default="unknown")
    
    @field_validator("ask")
    @classmethod
    def ask_above_bid(cls, v: Decimal, info) -> Decimal:
        if "bid" in info.data and v <= info.data["bid"]:
            raise ValueError("Ask must be greater than bid")
        return v
    
    @field_validator("mid")
    @classmethod
    def mid_is_midpoint(cls, v: Decimal, info) -> Decimal:
        if "bid" in info.data and "ask" in info.data:
            expected = (info.data["bid"] + info.data["ask"]) / 2
            if abs(v - expected) > Decimal("0.00001"):
                raise ValueError("Mid must be midpoint of bid/ask")
        return v


class OHLCV(BaseModel):
    """OHLCV bar with validation."""
    model_config = ConfigDict(frozen=True)
    
    symbol: str
    timestamp: datetime
    open: Decimal = Field(gt=0)
    high: Decimal = Field(gt=0)
    low: Decimal = Field(gt=0)
    close: Decimal = Field(gt=0)
    volume: int = Field(ge=0)
    frequency: DataFrequency
    
    @field_validator("high")
    @classmethod
    def high_is_highest(cls, v: Decimal, info) -> Decimal:
        o, l, c = info.data.get("open"), info.data.get("low"), info.data.get("close")
        if o and v < o:
            raise ValueError("High must be >= open")
        if l and v < l:
            raise ValueError("High must be >= low")
        if c and v < c:
            raise ValueError("High must be >= close")
        return v
    
    @field_validator("low")
    @classmethod
    def low_is_lowest(cls, v: Decimal, info) -> Decimal:
        o, h, c = info.data.get("open"), info.data.get("high"), info.data.get("close")
        if o and v > o:
            raise ValueError("Low must be <= open")
        if h and v > h:
            raise ValueError("Low must be <= high")
        if c and v > c:
            raise ValueError("Low must be <= close")
        return v


class Order(BaseModel):
    """Trading order with full lifecycle tracking."""
    model_config = ConfigDict(frozen=False)
    
    id: UUID = Field(default_factory=uuid4)
    symbol: str
    direction: TradeDirection
    order_type: OrderType
    quantity: Decimal = Field(gt=0)
    filled_quantity: Decimal = Field(default=Decimal("0"), ge=0)
    price: Decimal | None = Field(default=None, gt=0)
    stop_price: Decimal | None = Field(default=None, gt=0)
    time_in_force: TimeInForce = Field(default=TimeInForce.GTC)
    status: OrderStatus = Field(default=OrderStatus.PENDING)
    broker_id: str | None = Field(default=None)
    strategy_id: str | None = Field(default=None)
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    
    @property
    def is_filled(self) -> bool:
        return self.status == OrderStatus.FILLED
    
    @property
    def remaining(self) -> Decimal:
        return self.quantity - self.filled_quantity


class Position(BaseModel):
    """Open position with P&L tracking."""
    model_config = ConfigDict(frozen=False)
    
    id: UUID = Field(default_factory=uuid4)
    symbol: str
    direction: TradeDirection
    entry_price: Decimal = Field(gt=0)
    quantity: Decimal = Field(gt=0)
    status: PositionStatus = Field(default=PositionStatus.OPEN)
    unrealized_pnl: Decimal = Field(default=Decimal("0"))
    realized_pnl: Decimal = Field(default=Decimal("0"))
    open_orders: list[UUID] = Field(default_factory=list)
    opened_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    closed_at: datetime | None = Field(default=None)
    
    def calculate_unrealized_pnl(self, current_price: Decimal) -> Decimal:
        """Calculate unrealized P&L at current price."""
        if self.direction == TradeDirection.LONG:
            return (current_price - self.entry_price) * self.quantity
        else:
            return (self.entry_price - current_price) * self.quantity


class Signal(BaseModel):
    """Trading signal from strategy."""
    model_config = ConfigDict(frozen=True)
    
    strategy_id: str
    symbol: str
    direction: TradeDirection
    strength: float = Field(ge=0, le=1)
    confidence: float = Field(ge=0, le=1)
    features: dict[str, float] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict[str, Any] = Field(default_factory=dict)


class Account(BaseModel):
    """Trading account state."""
    model_config = ConfigDict(frozen=False)
    
    broker: BrokerType
    account_id: str
    balance: Decimal = Field(default=Decimal("0"))
    equity: Decimal = Field(default=Decimal("0"))
    margin_used: Decimal = Field(default=Decimal("0"))
    margin_available: Decimal = Field(default=Decimal("0"))
    open_positions: dict[str, Position] = Field(default_factory=dict)
    daily_pnl: Decimal = Field(default=Decimal("0"))
    total_pnl: Decimal = Field(default=Decimal("0"))
    max_drawdown: Decimal = Field(default=Decimal("0"))
    prop_firm: PropFirm = Field(default=PropFirm.NONE)
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

# Aliases expected by src.strategies.base and tests
MarketData = OHLCV

"""Strict type definitions for the trading system."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import Enum, StrEnum
from typing import Literal, NewType

from pydantic import BaseModel, Field, field_validator


# Domain types
Symbol = NewType("Symbol", str)
OrderId = NewType("OrderId", str)
PositionId = NewType("PositionId", str)


class Side(StrEnum):
    BUY = "BUY"
    SELL = "SELL"


class OrderType(StrEnum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    STOP = "STOP"
    STOP_LIMIT = "STOP_LIMIT"
    TRAILING_STOP = "TRAILING_STOP"


class OrderStatus(StrEnum):
    PENDING = "PENDING"
    OPEN = "OPEN"
    PARTIAL_FILL = "PARTIAL_FILL"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


class TimeInForce(StrEnum):
    GTC = "GTC"  # Good Till Cancelled
    IOC = "IOC"  # Immediate Or Cancel
    FOK = "FOK"  # Fill Or Kill
    GTD = "GTD"  # Good Till Date


class SignalType(StrEnum):
    ENTRY_LONG = "ENTRY_LONG"
    ENTRY_SHORT = "ENTRY_SHORT"
    EXIT_LONG = "EXIT_LONG"
    EXIT_SHORT = "EXIT_SHORT"
    HOLD = "HOLD"


class Venue(StrEnum):
    OANDA = "OANDA"
    MT5 = "MT5"
    IBKR = "IBKR"
    BINANCE = "BINANCE"
    PAPER = "PAPER"


class Tick(BaseModel):
    """Normalized tick data."""
    symbol: Symbol
    timestamp: datetime
    bid: Decimal = Field(..., decimal_places=5)
    ask: Decimal = Field(..., decimal_places=5)
    mid: Decimal = Field(..., decimal_places=5)
    volume: Decimal = Field(default=Decimal("0"), decimal_places=2)
    venue: Venue
    
    @field_validator("mid", mode="before")
    @classmethod
    def compute_mid(cls, v: Decimal | None, info) -> Decimal:
        if v is not None:
            return v
        data = info.data
        return (data.get("bid", Decimal("0")) + data.get("ask", Decimal("0"))) / 2


class OHLCV(BaseModel):
    """Candlestick data."""
    symbol: Symbol
    timestamp: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    timeframe: Literal["1m", "5m", "15m", "1h", "4h", "1d"]


class Position(BaseModel):
    """Open position state."""
    id: PositionId
    symbol: Symbol
    side: Side
    entry_price: Decimal
    quantity: Decimal
    unrealized_pnl: Decimal = Decimal("0")
    realized_pnl: Decimal = Decimal("0")
    open_time: datetime
    margin_used: Decimal
    stop_loss: Decimal | None = None
    take_profit: Decimal | None = None


class Order(BaseModel):
    """Order state."""
    id: OrderId
    symbol: Symbol
    side: Side
    order_type: OrderType
    quantity: Decimal
    price: Decimal | None = None
    stop_price: Decimal | None = None
    status: OrderStatus = OrderStatus.PENDING
    filled_qty: Decimal = Decimal("0")
    avg_fill_price: Decimal | None = None
    time_in_force: TimeInForce = TimeInForce.GTC
    created_at: datetime = Field(default_factory=datetime.utcnow)
    venue: Venue
    client_order_id: str | None = None


class Fill(BaseModel):
    """Fill/execution report."""
    order_id: OrderId
    fill_id: str
    symbol: Symbol
    side: Side
    quantity: Decimal
    price: Decimal
    timestamp: datetime
    venue: Venue
    commission: Decimal = Decimal("0")
    slippage: Decimal = Decimal("0")  # vs requested price

"""
Core domain models using SQLModel for type-safe ORM.
"""
from datetime import datetime, timedelta
from decimal import Decimal
from enum import Enum
from typing import Optional, List
from sqlmodel import SQLModel, Field, Relationship
import uuid


class TradeDirection(str, Enum):
    LONG = "LONG"
    SHORT = "SHORT"


class TradeStatus(str, Enum):
    PENDING = "PENDING"
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class OrderType(str, Enum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    STOP = "STOP"
    STOP_LIMIT = "STOP_LIMIT"


class TimeFrame(str, Enum):
    M1 = "1m"
    M5 = "5m"
    M15 = "15m"
    M30 = "30m"
    H1 = "1h"
    H4 = "4h"
    D1 = "1d"


class Account(SQLModel, table=True):
    """Trading account entity."""
    __tablename__ = "accounts"
    
    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    
    name: str
    broker: str
    account_type: str = "paper"  # paper, live, prop
    balance: Decimal = Field(default=Decimal("10000.00"), decimal_places=2)
    equity: Decimal = Field(default=Decimal("10000.00"), decimal_places=2)
    margin_used: Decimal = Field(default=Decimal("0.00"), decimal_places=2)
    currency: str = "USD"
    is_active: bool = True
    
    # Prop firm specific
    prop_firm: Optional[str] = None
    max_daily_loss: Optional[Decimal] = None
    max_total_loss: Optional[Decimal] = None
    profit_target: Optional[Decimal] = None
    
    trades: List["Trade"] = Relationship(back_populates="account")


class Trade(SQLModel, table=True):
    """Trade execution record."""
    __tablename__ = "trades"
    
    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    
    account_id: str = Field(foreign_key="accounts.id")
    account: Optional[Account] = Relationship(back_populates="trades")
    
    symbol: str = "XAUUSD"
    direction: TradeDirection
    status: TradeStatus = TradeStatus.PENDING
    
    # Entry
    entry_price: Optional[Decimal] = Field(default=None, decimal_places=5)
    entry_time: Optional[datetime] = None
    entry_order_type: OrderType = OrderType.MARKET
    
    # Exit
    exit_price: Optional[Decimal] = Field(default=None, decimal_places=5)
    exit_time: Optional[datetime] = None
    
    # Sizing
    quantity: Decimal = Field(decimal_places=2)
    stop_loss: Optional[Decimal] = Field(default=None, decimal_places=5)
    take_profit: Optional[Decimal] = Field(default=None, decimal_places=5)
    
    # P&L
    pnl: Optional[Decimal] = Field(default=None, decimal_places=2)
    pnl_pct: Optional[Decimal] = Field(default=None, decimal_places=4)
    commission: Decimal = Field(default=Decimal("0.00"), decimal_places=2)
    swap: Decimal = Field(default=Decimal("0.00"), decimal_places=2)
    
    # Metadata
    strategy: Optional[str] = None
    broker_trade_id: Optional[str] = None
    tags: Optional[str] = None  # JSON array


class MarketData(SQLModel, table=True):
    """OHLCV market data."""
    __tablename__ = "market_data"
    
    id: Optional[int] = Field(default=None, primary_key=True)
    symbol: str = Field(index=True)
    timeframe: TimeFrame = Field(index=True)
    timestamp: datetime = Field(index=True)
    
    open: Decimal = Field(decimal_places=5)
    high: Decimal = Field(decimal_places=5)
    low: Decimal = Field(decimal_places=5)
    close: Decimal = Field(decimal_places=5)
    volume: int
    
    # Technical indicators (stored for backtest performance)
    rsi_14: Optional[float] = None
    atr_14: Optional[Decimal] = Field(default=None, decimal_places=5)
    ema_20: Optional[Decimal] = Field(default=None, decimal_places=5)
    ema_50: Optional[Decimal] = Field(default=None, decimal_places=5)


class Strategy(SQLModel, table=True):
    """Trading strategy registry."""
    __tablename__ = "strategies"
    
    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    
    name: str = Field(index=True)
    description: Optional[str] = None
    owner_id: str
    is_public: bool = False
    price_monthly: Optional[Decimal] = Field(default=None, decimal_places=2)
    
    # Performance metrics
    total_return: Optional[float] = None
    sharpe_ratio: Optional[float] = None
    max_drawdown: Optional[float] = None
    win_rate: Optional[float] = None
    profit_factor: Optional[float] = None
    
    # Marketplace
    is_listed: bool = False
    stripe_product_id: Optional[str] = None


class Subscription(SQLModel, table=True):
    """Strategy subscription for copy trading."""
    __tablename__ = "subscriptions"
    
    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    
    strategy_id: str = Field(foreign_key="strategies.id")
    subscriber_id: str
    stripe_subscription_id: Optional[str] = None
    
    # Copy settings
    multiplier: float = Field(default=1.0, ge=0.1, le=10.0)
    max_risk_per_trade: float = Field(default=0.02, ge=0.001, le=0.1)
    is_active: bool = True

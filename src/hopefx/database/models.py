from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import List, Optional

from sqlalchemy import Column, String, Numeric, DateTime, ForeignKey, Index, JSON
from sqlmodel import Field, Relationship, SQLModel


# Enums
class UserRole(str, Enum):
    TRADER = "trader"
    FOLLOWER = "follower"
    ADMIN = "admin"
    PROP_MANAGER = "prop_manager"


class SubscriptionTier(str, Enum):
    FREE = "free"
    PRO = "pro"
    ELITE = "elite"
    PROP_CHALLENGE = "prop_challenge"


class TradeStatus(str, Enum):
    PENDING = "pending"
    FILLED = "filled"
    PARTIAL = "partial"
    REJECTED = "rejected"
    CANCELLED = "cancelled"


class CopyTradingStatus(str, Enum):
    ACTIVE = "active"
    PAUSED = "paused"
    STOPPED = "stopped"
    LIQUIDATED = "liquidated"


# User & Authentication
class User(SQLModel, table=True):
    __tablename__ = "users"
    
    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    email: str = Field(index=True, unique=True)
    username: str = Field(index=True, unique=True)
    hashed_password: str
    role: UserRole = Field(default=UserRole.TRADER)
    is_active: bool = Field(default=True)
    is_verified: bool = Field(default=False)
    two_factor_secret: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    last_login: Optional[datetime] = None
    
    # Relations
    profile: Optional["UserProfile"] = Relationship(back_populates="user")
    strategies: List["Strategy"] = Relationship(back_populates="user")
    subscriptions: List["Subscription"] = Relationship(back_populates="user")
    copy_relationships_as_leader: List["CopyTrading"] = Relationship(
        back_populates="leader", sa_relationship_kwargs={"foreign_keys": "CopyTrading.leader_id"}
    )
    copy_relationships_as_follower: List["CopyTrading"] = Relationship(
        back_populates="follower", sa_relationship_kwargs={"foreign_keys": "CopyTrading.follower_id"}
    )
    wallet: Optional["Wallet"] = Relationship(back_populates="user")
    
    # Indexes
    __table_args__ = (
        Index("idx_user_email", "email"),
        Index("idx_user_username", "username"),
        Index("idx_user_role", "role"),
    )


class UserProfile(SQLModel, table=True):
    __tablename__ = "user_profiles"
    
    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    user_id: str = Field(foreign_key="users.id")
    display_name: Optional[str] = None
    bio: Optional[str] = None
    avatar_url: Optional[str] = None
    country: Optional[str] = None
    timezone: str = Field(default="UTC")
    risk_tolerance: str = Field(default="moderate")  # conservative, moderate, aggressive
    max_drawdown_tolerance: Decimal = Field(default=Decimal("0.10"))
    preferred_leverage: Decimal = Field(default=Decimal("30"))
    
    # Social
    is_public_profile: bool = Field(default=True)
    allow_copying: bool = Field(default=False)
    min_copy_amount: Decimal = Field(default=Decimal("1000"))
    performance_fee_pct: Decimal = Field(default=Decimal("0.20"))  # 20% profit share
    
    user: User = Relationship(back_populates="profile")


# Wallet & Payments
class Wallet(SQLModel, table=True):
    __tablename__ = "wallets"
    
    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    user_id: str = Field(foreign_key="users.id", unique=True)
    balance: Decimal = Field(default=Decimal("0"), sa_column=Column(Numeric(19, 8)))
    frozen_balance: Decimal = Field(default=Decimal("0"), sa_column=Column(Numeric(19, 8)))
    currency: str = Field(default="USD")
    stripe_customer_id: Optional[str] = None
    
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    
    user: User = Relationship(back_populates="wallet")
    transactions: List["Transaction"] = Relationship(back_populates="wallet")


class Transaction(SQLModel, table=True):
    __tablename__ = "transactions"
    
    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    wallet_id: str = Field(foreign_key="wallets.id")
    type: str  # deposit, withdrawal, subscription, copy_fee, profit_share
    amount: Decimal = Field(sa_column=Column(Numeric(19, 8)))
    currency: str
    status: str = Field(default="pending")  # pending, completed, failed, refunded
    stripe_payment_intent_id: Optional[str] = None
    stripe_transfer_id: Optional[str] = None
    metadata: dict = Field(default_factory=dict, sa_column=Column(JSON))
    
    created_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = None
    
    wallet: Wallet = Relationship(back_populates="transactions")


class Subscription(SQLModel, table=True):
    __tablename__ = "subscriptions"
    
    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    user_id: str = Field(foreign_key="users.id")
    tier: SubscriptionTier
    status: str = Field(default="active")  # active, cancelled, expired
    current_period_start: datetime
    current_period_end: datetime
    stripe_subscription_id: Optional[str] = None
    cancel_at_period_end: bool = Field(default=False)
    
    user: User = Relationship(back_populates="subscriptions")


# Trading & Strategies
class Strategy(SQLModel, table=True):
    __tablename__ = "strategies"
    
    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    user_id: str = Field(foreign_key="users.id")
    name: str
    description: Optional[str] = None
    is_public: bool = Field(default=False)
    is_active: bool = Field(default=True)
    strategy_type: str  # ml, technical, hybrid
    config: dict = Field(default_factory=dict, sa_column=Column(JSON))
    
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    
    user: User = Relationship(back_populates="strategies")
    trades: List["Trade"] = Relationship(back_populates="strategy")
    performance: Optional["StrategyPerformance"] = Relationship(back_populates="strategy")


class StrategyPerformance(SQLModel, table=True):
    __tablename__ = "strategy_performance"
    
    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    strategy_id: str = Field(foreign_key="strategies.id", unique=True)
    
    # Metrics
    total_return_pct: Decimal = Field(default=Decimal("0"), sa_column=Column(Numeric(10, 4)))
    sharpe_ratio: Decimal = Field(default=Decimal("0"), sa_column=Column(Numeric(10, 4)))
    max_drawdown_pct: Decimal = Field(default=Decimal("0"), sa_column=Column(Numeric(10, 4)))
    win_rate: Decimal = Field(default=Decimal("0"), sa_column=Column(Numeric(5, 4)))
    profit_factor: Decimal = Field(default=Decimal("0"), sa_column=Column(Numeric(10, 4)))
    total_trades: int = Field(default=0)
    winning_trades: int = Field(default=0)
    losing_trades: int = Field(default=0)
    
    # Time series data for charts
    equity_curve: list = Field(default_factory=list, sa_column=Column(JSON))
    monthly_returns: dict = Field(default_factory=dict, sa_column=Column(JSON))
    
    last_updated: datetime = Field(default_factory=datetime.utcnow)
    
    strategy: Strategy = Relationship(back_populates="performance")


class Trade(SQLModel, table=True):
    __tablename__ = "trades"
    
    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    strategy_id: Optional[str] = Field(foreign_key="strategies.id", nullable=True)
    user_id: str = Field(foreign_key="users.id", index=True)
    symbol: str = Field(index=True)
    side: str  # buy, sell
    quantity: Decimal = Field(sa_column=Column(Numeric(19, 8)))
    entry_price: Decimal = Field(sa_column=Column(Numeric(19, 8)))
    exit_price: Optional[Decimal] = Field(default=None, sa_column=Column(Numeric(19, 8)))
    stop_loss: Optional[Decimal] = Field(default=None, sa_column=Column(Numeric(19, 8)))
    take_profit: Optional[Decimal] = Field(default=None, sa_column=Column(Numeric(19, 8)))
    status: TradeStatus
    pnl: Optional[Decimal] = Field(default=None, sa_column=Column(Numeric(19, 8)))
    commission: Decimal = Field(default=Decimal("0"), sa_column=Column(Numeric(19, 8)))
    swap: Decimal = Field(default=Decimal("0"), sa_column=Column(Numeric(19, 8)))
    
    entry_time: datetime = Field(default_factory=datetime.utcnow)
    exit_time: Optional[datetime] = None
    duration_seconds: Optional[int] = None
    
    broker: str
    broker_order_id: Optional[str] = None
    
    # ML metadata
    model_id: Optional[str] = None
    model_version: Optional[str] = None
    prediction_confidence: Optional[Decimal] = Field(default=None, sa_column=Column(Numeric(5, 4)))
    
    strategy: Optional[Strategy] = Relationship(back_populates="trades")
    
    __table_args__ = (
        Index("idx_trade_symbol_time", "symbol", "entry_time"),
        Index("idx_trade_user_status", "user_id", "status"),
    )


# Copy Trading
class CopyTrading(SQLModel, table=True):
    __tablename__ = "copy_trading"
    
    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    leader_id: str = Field(foreign_key="users.id", index=True)
    follower_id: str = Field(foreign_key="users.id", index=True)
    
    status: CopyTradingStatus = Field(default=CopyTradingStatus.ACTIVE)
    allocation_type: str = Field(default="fixed")  # fixed, proportional, mirror
    allocation_amount: Decimal = Field(sa_column=Column(Numeric(19, 8)))
    max_drawdown_stop: Decimal = Field(default=Decimal("0.10"))  # Stop copying at 10% DD
    
    # Fees
    performance_fee_pct: Decimal = Field(default=Decimal("0.20"))
    management_fee_pct: Decimal = Field(default=Decimal("0.0"))
    total_fees_paid: Decimal = Field(default=Decimal("0"), sa_column=Column(Numeric(19, 8)))
    
    # Performance tracking
    start_date: datetime = Field(default_factory=datetime.utcnow)
    end_date: Optional[datetime] = None
    initial_equity: Decimal = Field(sa_column=Column(Numeric(19, 8)))
    current_equity: Decimal = Field(sa_column=Column(Numeric(19, 8)))
    total_return_pct: Decimal = Field(default=Decimal("0"), sa_column=Column(Numeric(10, 4)))
    
    # Settings
    copy_stop_loss: bool = Field(default=True)
    copy_take_profit: bool = Field(default=True)
    max_slippage_pct: Decimal = Field(default=Decimal("0.001"))  # 0.1%
    min_trade_size: Decimal = Field(default=Decimal("0.01"))
    
    leader: User = Relationship(
        back_populates="copy_relationships_as_leader",
        sa_relationship_kwargs={"foreign_keys": "CopyTrading.leader_id"}
    )
    follower: User = Relationship(
        back_populates="copy_relationships_as_follower",
        sa_relationship_kwargs={"foreign_keys": "CopyTrading.follower_id"}
    )
    trades: List["CopyTrade"] = Relationship(back_populates="copy_relationship")


class CopyTrade(SQLModel, table=True):
    __tablename__ = "copy_trades"
    
    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    copy_relationship_id: str = Field(foreign_key="copy_trading.id")
    original_trade_id: str = Field(foreign_key="trades.id")
    
    # Copied trade details
    leader_quantity: Decimal = Field(sa_column=Column(Numeric(19, 8)))
    follower_quantity: Decimal = Field(sa_column=Column(Numeric(19, 8)))
    leader_entry: Decimal = Field(sa_column=Column(Numeric(19, 8)))
    follower_entry: Decimal = Field(sa_column=Column(Numeric(19, 8)))
    slippage_pct: Decimal = Field(sa_column=Column(Numeric(10, 6)))
    
    status: str = Field(default="open")  # open, closed, failed
    pnl: Optional[Decimal] = Field(default=None, sa_column=Column(Numeric(19, 8)))
    copy_fee: Decimal = Field(default=Decimal("0"), sa_column=Column(Numeric(19, 8)))
    
    executed_at: datetime = Field(default_factory=datetime.utcnow)
    closed_at: Optional[datetime] = None
    
    copy_relationship: CopyTrading = Relationship(back_populates="trades")


# Leaderboards & Rankings
class LeaderboardEntry(SQLModel, table=True):
    __tablename__ = "leaderboard_entries"
    
    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    user_id: str = Field(foreign_key="users.id", index=True)
    period: str  # daily, weekly, monthly, all_time
    rank: int
    score: Decimal = Field(sa_column=Column(Numeric(19, 8)))
    
    # Performance metrics for ranking
    return_pct: Decimal = Field(sa_column=Column(Numeric(10, 4)))
    sharpe_ratio: Decimal = Field(sa_column=Column(Numeric(10, 4)))
    max_drawdown_pct: Decimal = Field(sa_column=Column(Numeric(10, 4)))
    win_rate: Decimal = Field(sa_column=Column(Numeric(5, 4)))
    profit_factor: Decimal = Field(sa_column=Column(Numeric(10, 4)))
    
    # Social metrics
    followers_count: int = Field(default=0)
    copiers_count: int = Field(default=0)
    total_copied_volume: Decimal = Field(default=Decimal("0"), sa_column=Column(Numeric(19, 8)))
    
    calculated_at: datetime = Field(default_factory=datetime.utcnow)
    
    __table_args__ = (
        Index("idx_leaderboard_period_rank", "period", "rank"),
        Index("idx_leaderboard_user_period", "user_id", "period"),
    )


# Prop Firm Challenges
class PropChallenge(SQLModel, table=True):
    __tablename__ = "prop_challenges"
    
    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    user_id: str = Field(foreign_key="users.id")
    firm: str  # ftmo, mff, the5ers, etc.
    challenge_type: str  # evaluation, verification, funded
    account_size: Decimal = Field(sa_column=Column(Numeric(19, 8)))
    
    # Rules
    max_daily_loss_pct: Decimal = Field(default=Decimal("0.05"))
    max_total_loss_pct: Decimal = Field(default=Decimal("0.10"))
    profit_target_pct: Decimal = Field(default=Decimal("0.10"))
    min_trading_days: int = Field(default=4)
    max_trading_days: int = Field(default=30)
    
    # Status
    status: str = Field(default="active")  # active, passed, failed, violated
    start_date: datetime = Field(default_factory=datetime.utcnow)
    end_date: Optional[datetime] = None
    
    # Current metrics
    current_equity: Decimal = Field(sa_column=Column(Numeric(19, 8)))
    peak_equity: Decimal = Field(sa_column=Column(Numeric(19, 8)))
    daily_pnl: Decimal = Field(default=Decimal("0"), sa_column=Column(Numeric(19, 8)))
    total_pnl: Decimal = Field(default=Decimal("0"), sa_column=Column(Numeric(19, 8)))
    trading_days_count: int = Field(default=0)
    
    # Violations
    violations: list = Field(default_factory=list, sa_column=Column(JSON))
    
    # API integration
    firm_account_id: Optional[str] = None
    firm_api_key: Optional[str] = None  # Encrypted


# Audit & Compliance
class AuditLog(SQLModel, table=True):
    __tablename__ = "audit_logs"
    
    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    user_id: Optional[str] = Field(foreign_key="users.id")
    action: str  # login, trade, withdrawal, settings_change
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    details: dict = Field(default_factory=dict, sa_column=Column(JSON))
    risk_score: int = Field(default=0)  # 0-100 risk assessment
    created_at: datetime = Field(default_factory=datetime.utcnow)
    
    __table_args__ = (
        Index("idx_audit_user_time", "user_id", "created_at"),
        Index("idx_audit_action", "action"),
    )

"""
SQLAlchemy ORM Models for HOPEFX AI Trading System

This module defines all database models for the trading application including:
- Accounts and authentication
- Trades and orders
- Positions and portfolios
- Performance metrics
- AI predictions
- Market data
- Risk analysis
"""

from datetime import datetime
from decimal import Decimal
from enum import Enum
from sqlalchemy import (
    Column, Integer, String, Float, DateTime, Boolean, Text, Numeric,
    ForeignKey, Table, Index, UniqueConstraint, CheckConstraint,
    Enum as SQLEnum, Date, Time, JSON
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

Base = declarative_base()

# Foreign key reference constants
FK_USERS_ID = "users.id"
FK_ACCOUNTS_ID = "accounts.id"
ON_DELETE_SET_NULL = "SET NULL"
CASCADE_DELETE_ORPHAN = "all, delete-orphan"


# ============================================================================
# ENUMS
# ============================================================================

class AccountStatus(Enum):
    """Account status enumeration"""
    ACTIVE = "active"
    INACTIVE = "inactive"
    SUSPENDED = "suspended"
    CLOSED = "closed"


class TradeType(Enum):
    """Trade type enumeration"""
    LONG = "long"
    SHORT = "short"
    HEDGE = "hedge"


class OrderStatus(Enum):
    """Order status enumeration"""
    PENDING = "pending"
    OPEN = "open"
    PARTIALLY_FILLED = "partially_filled"
    FILLED = "filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"


class OrderType(Enum):
    """Order type enumeration"""
    MARKET = "market"
    LIMIT = "limit"
    STOP = "stop"
    STOP_LIMIT = "stop_limit"


class PositionStatus(Enum):
    """Position status enumeration"""
    OPEN = "open"
    CLOSING = "closing"
    CLOSED = "closed"


class PredictionType(Enum):
    """AI prediction type enumeration"""
    PRICE = "price"
    DIRECTION = "direction"
    VOLATILITY = "volatility"
    TREND = "trend"


class RiskLevel(Enum):
    """Risk level enumeration"""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class MarketDataType(Enum):
    """Market data type enumeration"""
    OHLCV = "ohlcv"
    TICK = "tick"
    DEPTH = "depth"
    NEWS = "news"


# ============================================================================
# ACCOUNTS & AUTHENTICATION
# ============================================================================

class User(Base):
    """User account model"""
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(255), unique=True, nullable=False, index=True)
    email = Column(String(255), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    full_name = Column(String(255))
    phone = Column(String(20))
    status = Column(SQLEnum(AccountStatus), default=AccountStatus.ACTIVE, nullable=False)
    kyc_verified = Column(Boolean, default=False, nullable=False)
    two_factor_enabled = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)
    last_login = Column(DateTime)

    # Relationships
    accounts = relationship("Account", back_populates="user", cascade=CASCADE_DELETE_ORPHAN)
    sessions = relationship("Session", back_populates="user", cascade=CASCADE_DELETE_ORPHAN)

    __table_args__ = (
        Index("idx_user_email_status", "email", "status"),
    )


class Session(Base):
    """User session model"""
    __tablename__ = "sessions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey(FK_USERS_ID, ondelete="CASCADE"), nullable=False)
    token = Column(String(512), unique=True, nullable=False, index=True)
    ip_address = Column(String(45))  # Supports IPv4 and IPv6
    user_agent = Column(Text)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    expires_at = Column(DateTime, nullable=False)

    # Relationships
    user = relationship("User", back_populates="sessions")

    __table_args__ = (
        Index("idx_session_user_id_expires", "user_id", "expires_at"),
    )


class Account(Base):
    """Trading account model"""
    __tablename__ = "accounts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey(FK_USERS_ID, ondelete="CASCADE"), nullable=False)
    account_name = Column(String(255), nullable=False)
    account_type = Column(String(50), nullable=False)  # e.g., LIVE, DEMO, PAPER
    broker = Column(String(100), nullable=False)  # e.g., OANDA, ALPACA, IB
    api_key = Column(String(512), nullable=False)
    api_secret = Column(String(512), nullable=False)
    balance = Column(Numeric(20, 2), nullable=False, default=0)
    equity = Column(Numeric(20, 2), nullable=False, default=0)
    used_margin = Column(Numeric(20, 2), nullable=False, default=0)
    available_margin = Column(Numeric(20, 2), nullable=False, default=0)
    leverage = Column(Float, nullable=False, default=1.0)
    status = Column(SQLEnum(AccountStatus), default=AccountStatus.ACTIVE, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)
    last_sync = Column(DateTime)

    # Relationships
    user = relationship("User", back_populates="accounts")
    trades = relationship("Trade", back_populates="account", cascade=CASCADE_DELETE_ORPHAN)
    orders = relationship("Order", back_populates="account", cascade=CASCADE_DELETE_ORPHAN)
    positions = relationship("Position", back_populates="account", cascade=CASCADE_DELETE_ORPHAN)
    performance_metrics = relationship("PerformanceMetrics", back_populates="account", cascade=CASCADE_DELETE_ORPHAN)
    risk_parameters = relationship("RiskParameters", back_populates="account", uselist=False, cascade=CASCADE_DELETE_ORPHAN)

    __table_args__ = (
        UniqueConstraint("user_id", "account_name", name="uq_user_account_name"),
        Index("idx_account_user_status", "user_id", "status"),
    )


# ============================================================================
# TRADES & ORDERS
# ============================================================================

class Trade(Base):
    """Trade model"""
    __tablename__ = "trades"

    id = Column(Integer, primary_key=True, autoincrement=True)
    account_id = Column(Integer, ForeignKey(FK_ACCOUNTS_ID, ondelete="CASCADE"), nullable=False)
    symbol = Column(String(20), nullable=False)  # e.g., EUR/USD
    trade_type = Column(SQLEnum(TradeType), nullable=False)
    entry_price = Column(Numeric(20, 8), nullable=False)
    entry_time = Column(DateTime, nullable=False)
    exit_price = Column(Numeric(20, 8))
    exit_time = Column(DateTime)
    quantity = Column(Numeric(18, 8), nullable=False)
    commission = Column(Numeric(15, 2), default=0)
    swap = Column(Numeric(15, 2), default=0)
    profit_loss = Column(Numeric(18, 2))
    profit_loss_percent = Column(Float)
    status = Column(String(50), nullable=False, default="open")  # open, closed, partial
    risk_reward_ratio = Column(Float)
    duration_seconds = Column(Integer)
    notes = Column(Text)
    ai_signal_used = Column(Boolean, default=False)
    prediction_id = Column(Integer, ForeignKey("predictions.id"))
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)

    # Relationships
    account = relationship("Account", back_populates="trades")
    orders = relationship("Order", back_populates="trade")
    prediction = relationship("Prediction", back_populates="trades")

    __table_args__ = (
        Index("idx_trade_account_symbol", "account_id", "symbol"),
        Index("idx_trade_status_time", "status", "entry_time"),
    )


class Order(Base):
    """Order model"""
    __tablename__ = "orders"

    id = Column(Integer, primary_key=True, autoincrement=True)
    account_id = Column(Integer, ForeignKey(FK_ACCOUNTS_ID, ondelete="CASCADE"), nullable=False)
    trade_id = Column(Integer, ForeignKey("trades.id", ondelete=ON_DELETE_SET_NULL))
    symbol = Column(String(20), nullable=False)
    order_type = Column(SQLEnum(OrderType), nullable=False)
    side = Column(String(10), nullable=False)  # BUY or SELL
    quantity = Column(Numeric(18, 8), nullable=False)
    price = Column(Numeric(20, 8))
    stop_price = Column(Numeric(20, 8))
    limit_price = Column(Numeric(20, 8))
    status = Column(SQLEnum(OrderStatus), default=OrderStatus.PENDING, nullable=False)
    filled_quantity = Column(Numeric(18, 8), default=0)
    average_filled_price = Column(Numeric(20, 8))
    commission = Column(Numeric(15, 2), default=0)
    time_in_force = Column(String(20), default="GTC")  # GTC, FOK, IOC, DAY
    external_order_id = Column(String(100), unique=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)
    expires_at = Column(DateTime)

    # Relationships
    account = relationship("Account", back_populates="orders")
    trade = relationship("Trade", back_populates="orders")

    __table_args__ = (
        Index("idx_order_account_status", "account_id", "status"),
        Index("idx_order_symbol_time", "symbol", "created_at"),
    )


# ============================================================================
# POSITIONS & PORTFOLIO
# ============================================================================

class Position(Base):
    """Open position model"""
    __tablename__ = "positions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    account_id = Column(Integer, ForeignKey(FK_ACCOUNTS_ID, ondelete="CASCADE"), nullable=False)
    symbol = Column(String(20), nullable=False)
    position_type = Column(SQLEnum(TradeType), nullable=False)
    quantity = Column(Numeric(18, 8), nullable=False)
    average_entry_price = Column(Numeric(20, 8), nullable=False)
    current_price = Column(Numeric(20, 8), nullable=False)
    unrealized_profit_loss = Column(Numeric(18, 2))
    unrealized_profit_loss_percent = Column(Float)
    realized_profit_loss = Column(Numeric(18, 2), default=0)
    status = Column(SQLEnum(PositionStatus), default=PositionStatus.OPEN, nullable=False)
    opened_at = Column(DateTime, nullable=False)
    closed_at = Column(DateTime)
    duration_seconds = Column(Integer)
    stop_loss = Column(Numeric(20, 8))
    take_profit = Column(Numeric(20, 8))
    trailing_stop = Column(Numeric(20, 8))
    risk_amount = Column(Numeric(18, 2))
    leverage_used = Column(Float)
    position_metadata = Column(JSON)  # Store additional data like tags, notes, etc.
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)

    # Relationships
    account = relationship("Account", back_populates="positions")

    __table_args__ = (
        UniqueConstraint("account_id", "symbol", "position_type",
                        name="uq_account_symbol_type"),
        Index("idx_position_account_status", "account_id", "status"),
    )


# ============================================================================
# PERFORMANCE METRICS
# ============================================================================

class PerformanceMetrics(Base):
    """Account performance metrics model"""
    __tablename__ = "performance_metrics"

    id = Column(Integer, primary_key=True, autoincrement=True)
    account_id = Column(Integer, ForeignKey(FK_ACCOUNTS_ID, ondelete="CASCADE"), nullable=False)
    metric_date = Column(Date, nullable=False)

    # Return metrics
    daily_return = Column(Float)
    weekly_return = Column(Float)
    monthly_return = Column(Float)
    yearly_return = Column(Float)
    total_return = Column(Float)

    # Risk metrics
    sharpe_ratio = Column(Float)
    sortino_ratio = Column(Float)
    max_drawdown = Column(Float)
    max_drawdown_percent = Column(Float)
    current_drawdown = Column(Float)

    # Trade statistics
    total_trades = Column(Integer)
    winning_trades = Column(Integer)
    losing_trades = Column(Integer)
    win_rate = Column(Float)
    average_win = Column(Numeric(18, 2))
    average_loss = Column(Numeric(18, 2))
    largest_win = Column(Numeric(18, 2))
    largest_loss = Column(Numeric(18, 2))
    profit_factor = Column(Float)

    # Position metrics
    open_positions = Column(Integer)
    closed_positions = Column(Integer)
    average_trade_duration = Column(Integer)  # seconds

    # Consistency metrics
    consecutive_wins = Column(Integer)
    consecutive_losses = Column(Integer)
    expectancy = Column(Float)  # Average profit per trade

    # Metadata
    calculated_at = Column(DateTime, server_default=func.now(), nullable=False)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)

    # Relationships
    account = relationship("Account", back_populates="performance_metrics")

    __table_args__ = (
        UniqueConstraint("account_id", "metric_date", name="uq_account_metric_date"),
        Index("idx_metrics_account_date", "account_id", "metric_date"),
    )


class DailySnapshot(Base):
    """Daily account snapshot for historical tracking"""
    __tablename__ = "daily_snapshots"

    id = Column(Integer, primary_key=True, autoincrement=True)
    account_id = Column(Integer, ForeignKey(FK_ACCOUNTS_ID, ondelete="CASCADE"), nullable=False)
    snapshot_date = Column(Date, nullable=False)

    # Account state
    balance = Column(Numeric(20, 2), nullable=False)
    equity = Column(Numeric(20, 2), nullable=False)
    used_margin = Column(Numeric(20, 2), nullable=False)
    available_margin = Column(Numeric(20, 2), nullable=False)

    # Daily performance
    daily_profit_loss = Column(Numeric(18, 2))
    daily_profit_loss_percent = Column(Float)
    open_position_count = Column(Integer)

    created_at = Column(DateTime, server_default=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("account_id", "snapshot_date", name="uq_account_snapshot_date"),
        Index("idx_snapshot_account_date", "account_id", "snapshot_date"),
    )


# ============================================================================
# AI PREDICTIONS & SIGNALS
# ============================================================================

class Prediction(Base):
    """AI prediction model"""
    __tablename__ = "predictions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String(20), nullable=False)
    prediction_type = Column(SQLEnum(PredictionType), nullable=False)
    model_version = Column(String(50), nullable=False)

    # Prediction data
    predicted_value = Column(Numeric(20, 8))
    predicted_direction = Column(String(10))  # UP, DOWN, NEUTRAL
    confidence = Column(Float, nullable=False)  # 0-1
    confidence_percent = Column(Float)

    # Price prediction specifics
    target_price = Column(Numeric(20, 8))
    price_target_percent = Column(Float)
    timeframe = Column(String(20))  # e.g., 1H, 4H, 1D

    # Volatility prediction
    predicted_volatility = Column(Float)
    volatility_change_percent = Column(Float)

    # Trend prediction
    trend = Column(String(50))  # STRONG_UP, UP, DOWN, STRONG_DOWN, SIDEWAYS
    trend_strength = Column(Float)  # 0-1

    # Supporting data
    supporting_factors = Column(JSON)  # Store important indicators/factors
    risk_level = Column(SQLEnum(RiskLevel))

    # Status
    is_active = Column(Boolean, default=True)
    prediction_time = Column(DateTime, nullable=False)
    expiry_time = Column(DateTime)

    # Validation after expiry
    actual_value = Column(Numeric(20, 8))
    actual_direction = Column(String(10))
    accuracy = Column(Float)  # 0-1
    is_accurate = Column(Boolean)

    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)

    # Relationships
    trades = relationship("Trade", back_populates="prediction")

    __table_args__ = (
        Index("idx_prediction_symbol_active", "symbol", "is_active"),
        Index("idx_prediction_model_time", "model_version", "prediction_time"),
    )


class AISignal(Base):
    """AI trading signal model"""
    __tablename__ = "ai_signals"

    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String(20), nullable=False)
    signal_type = Column(String(20), nullable=False)  # BUY, SELL, CLOSE
    confidence = Column(Float, nullable=False)  # 0-1
    strength = Column(Float)  # 0-1

    # Signal components
    technical_score = Column(Float)
    sentiment_score = Column(Float)
    fundamental_score = Column(Float)

    # Strategy info
    strategy_name = Column(String(100), nullable=False)
    strategy_version = Column(String(50))

    # Position recommendation
    suggested_entry = Column(Numeric(20, 8))
    suggested_stop_loss = Column(Numeric(20, 8))
    suggested_take_profit = Column(Numeric(20, 8))
    suggested_quantity = Column(Numeric(18, 8))
    risk_reward_ratio = Column(Float)

    # Metadata
    signal_reasons = Column(JSON)
    is_active = Column(Boolean, default=True)
    generated_at = Column(DateTime, nullable=False)
    expires_at = Column(DateTime)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)

    __table_args__ = (
        Index("idx_signal_symbol_active", "symbol", "is_active"),
        Index("idx_signal_type_confidence", "signal_type", "confidence"),
    )


class ModelPerformance(Base):
    """AI model performance tracking"""
    __tablename__ = "model_performance"

    id = Column(Integer, primary_key=True, autoincrement=True)
    model_name = Column(String(100), nullable=False)
    model_version = Column(String(50), nullable=False)
    symbol = Column(String(20), nullable=False)

    # Metrics
    accuracy = Column(Float)
    precision = Column(Float)
    recall = Column(Float)
    f1_score = Column(Float)
    auc_score = Column(Float)
    mape = Column(Float)  # Mean Absolute Percentage Error
    rmse = Column(Float)  # Root Mean Squared Error

    # Directional accuracy
    directional_accuracy = Column(Float)

    # Trading metrics
    win_rate = Column(Float)
    average_return = Column(Float)
    sharpe_ratio = Column(Float)
    max_drawdown = Column(Float)

    # Data
    total_predictions = Column(Integer)
    evaluation_period = Column(String(50))
    evaluation_start = Column(Date)
    evaluation_end = Column(Date)

    is_current = Column(Boolean, default=False)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)

    __table_args__ = (
        Index("idx_model_performance_model_symbol", "model_name", "model_version", "symbol"),
    )


# ============================================================================
# MARKET DATA
# ============================================================================

class MarketData(Base):
    """OHLCV market data model"""
    __tablename__ = "market_data"

    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String(20), nullable=False)
    timeframe = Column(String(20), nullable=False)  # 1m, 5m, 15m, 1h, 4h, 1d, 1w
    timestamp = Column(DateTime, nullable=False)

    # OHLCV
    open = Column(Numeric(20, 8), nullable=False)
    high = Column(Numeric(20, 8), nullable=False)
    low = Column(Numeric(20, 8), nullable=False)
    close = Column(Numeric(20, 8), nullable=False)
    volume = Column(Numeric(20, 8), nullable=False)

    # Additional metrics
    typical_price = Column(Numeric(20, 8))  # (H + L + C) / 3
    hlc3 = Column(Numeric(20, 8))  # (H + L + C) / 3

    # Technical indicators
    sma_20 = Column(Numeric(20, 8))
    sma_50 = Column(Numeric(20, 8))
    sma_200 = Column(Numeric(20, 8))
    ema_12 = Column(Numeric(20, 8))
    ema_26 = Column(Numeric(20, 8))

    # Momentum indicators
    rsi_14 = Column(Float)
    macd = Column(Float)
    macd_signal = Column(Float)
    macd_histogram = Column(Float)

    # Volatility
    atr_14 = Column(Float)
    bbands_upper = Column(Numeric(20, 8))
    bbands_middle = Column(Numeric(20, 8))
    bbands_lower = Column(Numeric(20, 8))

    created_at = Column(DateTime, server_default=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("symbol", "timeframe", "timestamp",
                        name="uq_symbol_timeframe_timestamp"),
        Index("idx_market_data_symbol_time", "symbol", "timeframe", "timestamp"),
    )


class TickData(Base):
    """Tick-level market data"""
    __tablename__ = "tick_data"

    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String(20), nullable=False)
    bid = Column(Numeric(20, 8), nullable=False)
    ask = Column(Numeric(20, 8), nullable=False)
    bid_volume = Column(Numeric(20, 8))
    ask_volume = Column(Numeric(20, 8))
    timestamp = Column(DateTime, nullable=False)

    created_at = Column(DateTime, server_default=func.now(), nullable=False)

    __table_args__ = (
        Index("idx_tick_symbol_time", "symbol", "timestamp"),
    )


class OrderBook(Base):
    """Order book depth data"""
    __tablename__ = "order_book"

    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String(20), nullable=False)
    timestamp = Column(DateTime, nullable=False)

    # Bid side (top 10) - stored as JSON for SQLite compatibility
    bid_prices = Column(JSON)
    bid_sizes = Column(JSON)

    # Ask side (top 10) - stored as JSON for SQLite compatibility
    ask_prices = Column(JSON)
    ask_sizes = Column(JSON)

    # Summary
    mid_price = Column(Numeric(20, 8))
    bid_ask_spread = Column(Float)

    created_at = Column(DateTime, server_default=func.now(), nullable=False)

    __table_args__ = (
        Index("idx_orderbook_symbol_time", "symbol", "timestamp"),
    )


class NewsData(Base):
    """Financial news and events"""
    __tablename__ = "news_data"

    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String(20))
    headline = Column(String(500), nullable=False)
    content = Column(Text)
    source = Column(String(100))

    # Classification
    sentiment = Column(String(20))  # POSITIVE, NEGATIVE, NEUTRAL
    impact = Column(String(20))  # HIGH, MEDIUM, LOW
    category = Column(String(50))  # EARNINGS, ECONOMIC, POLITICS, etc.

    # Relevance
    relevance_score = Column(Float)  # 0-1
    symbols_affected = Column(JSON)  # List of symbol strings

    published_at = Column(DateTime)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)

    __table_args__ = (
        Index("idx_news_symbol_sentiment", "symbol", "sentiment"),
        Index("idx_news_published", "published_at"),
    )


# ============================================================================
# RISK ANALYSIS & MANAGEMENT
# ============================================================================

class RiskParameters(Base):
    """Account risk management parameters"""
    __tablename__ = "risk_parameters"

    id = Column(Integer, primary_key=True, autoincrement=True)
    account_id = Column(Integer, ForeignKey(FK_ACCOUNTS_ID, ondelete="CASCADE"),
                       nullable=False, unique=True)

    # Risk limits
    max_daily_loss = Column(Numeric(18, 2))
    max_daily_loss_percent = Column(Float)
    max_monthly_loss = Column(Numeric(18, 2))
    max_monthly_loss_percent = Column(Float)

    # Position limits
    max_position_size = Column(Numeric(18, 8))
    max_positions = Column(Integer)
    max_correlation = Column(Float)  # Max correlated positions

    # Leverage limits
    max_leverage = Column(Float)
    max_margin_utilization = Column(Float)  # 0-1

    # Risk per trade
    risk_per_trade = Column(Float)  # As % of account
    max_risk_per_trade = Column(Numeric(18, 2))
    max_stop_loss_distance = Column(Float)  # In pips/points

    # Diversification
    max_concentration = Column(Float)  # Max % in single instrument
    min_diversification = Column(Integer)  # Min number of different instruments

    # Market conditions
    trading_allowed_outside_hours = Column(Boolean, default=False)
    trading_allowed_on_news = Column(Boolean, default=False)
    high_volatility_mode = Column(String(20))  # ALLOW, RESTRICT, STOP

    # Alerts
    alert_on_max_loss = Column(Boolean, default=True)
    alert_on_max_leverage = Column(Boolean, default=True)

    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)

    # Relationships
    account = relationship("Account", back_populates="risk_parameters")


class RiskMetrics(Base):
    """Real-time risk metrics for positions"""
    __tablename__ = "risk_metrics"

    id = Column(Integer, primary_key=True, autoincrement=True)
    account_id = Column(Integer, ForeignKey(FK_ACCOUNTS_ID, ondelete="CASCADE"), nullable=False)
    symbol = Column(String(20), nullable=False)

    # Current exposure
    exposure_percent = Column(Float)  # % of account equity
    notional_exposure = Column(Numeric(18, 2))

    # Risk measures
    var_95 = Column(Numeric(18, 2))  # Value at Risk 95%
    cvar_95 = Column(Numeric(18, 2))  # Conditional Value at Risk 95%
    max_loss = Column(Numeric(18, 2))  # Maximum possible loss

    # Greeks (for options)
    delta = Column(Float)
    gamma = Column(Float)
    vega = Column(Float)
    theta = Column(Float)
    rho = Column(Float)

    # Correlation metrics
    correlation_with_portfolio = Column(Float)  # -1 to 1
    beta = Column(Float)

    # Liquidity risk
    liquidity_score = Column(Float)  # 0-1, higher is more liquid
    spread_percent = Column(Float)

    # Updated metrics
    calculated_at = Column(DateTime, server_default=func.now(), nullable=False)

    __table_args__ = (
        Index("idx_risk_metrics_account_symbol", "account_id", "symbol"),
    )


class RiskEvent(Base):
    """Risk events and alerts"""
    __tablename__ = "risk_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    account_id = Column(Integer, ForeignKey(FK_ACCOUNTS_ID, ondelete="CASCADE"), nullable=False)

    # Event details
    event_type = Column(String(100), nullable=False)  # e.g., MAX_LOSS, HIGH_LEVERAGE, CONCENTRATION
    severity = Column(SQLEnum(RiskLevel), nullable=False)
    description = Column(Text, nullable=False)

    # Context
    symbol = Column(String(20))
    position_id = Column(Integer, ForeignKey("positions.id", ondelete=ON_DELETE_SET_NULL))

    # Metrics
    threshold = Column(Numeric(20, 8))
    actual_value = Column(Numeric(20, 8))

    # Action
    action_taken = Column(String(200))
    auto_remediated = Column(Boolean, default=False)

    # Timing
    event_time = Column(DateTime, nullable=False)
    acknowledged_at = Column(DateTime)
    acknowledged_by = Column(String(255))
    resolved_at = Column(DateTime)

    created_at = Column(DateTime, server_default=func.now(), nullable=False)

    __table_args__ = (
        Index("idx_risk_event_account_severity", "account_id", "severity"),
        Index("idx_risk_event_unresolved", "account_id", "resolved_at"),
    )


class StressTest(Base):
    """Stress test scenarios and results"""
    __tablename__ = "stress_tests"

    id = Column(Integer, primary_key=True, autoincrement=True)
    account_id = Column(Integer, ForeignKey(FK_ACCOUNTS_ID, ondelete="CASCADE"), nullable=False)
    test_name = Column(String(255), nullable=False)

    # Scenario
    scenario_type = Column(String(50))  # HISTORICAL, HYPOTHETICAL
    description = Column(Text)

    # Market conditions tested
    market_moves = Column(JSON)  # e.g., {"EUR/USD": -0.05, "GBP/USD": 0.03}
    volatility_increase = Column(Float)
    correlation_assumptions = Column(JSON)

    # Results
    portfolio_loss = Column(Numeric(18, 2))
    loss_percent = Column(Float)
    affected_positions = Column(Integer)
    recovery_time_days = Column(Integer)

    # Analysis
    key_risks = Column(JSON)
    recommendations = Column(JSON)

    executed_at = Column(DateTime, nullable=False)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)

    __table_args__ = (
        Index("idx_stress_test_account_date", "account_id", "executed_at"),
    )


# ============================================================================
# AUDIT & COMPLIANCE
# ============================================================================

class AuditLog(Base):
    """Audit log for all system actions"""
    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey(FK_USERS_ID, ondelete=ON_DELETE_SET_NULL))
    account_id = Column(Integer, ForeignKey(FK_ACCOUNTS_ID, ondelete=ON_DELETE_SET_NULL))

    # Action details
    action = Column(String(100), nullable=False)
    entity_type = Column(String(50))  # Trade, Order, Position, etc.
    entity_id = Column(Integer)

    # Changes
    old_values = Column(JSON)
    new_values = Column(JSON)
    description = Column(Text)

    # Source
    ip_address = Column(String(45))
    user_agent = Column(String(500))

    created_at = Column(DateTime, server_default=func.now(), nullable=False)

    __table_args__ = (
        Index("idx_audit_account_action", "account_id", "action"),
        Index("idx_audit_user_time", "user_id", "created_at"),
    )


# ============================================================================
# CONFIGURATION & SETTINGS
# ============================================================================

class SystemConfig(Base):
    """System configuration settings"""
    __tablename__ = "system_config"

    id = Column(Integer, primary_key=True, autoincrement=True)
    key = Column(String(255), unique=True, nullable=False)
    value = Column(Text, nullable=False)
    description = Column(Text)
    config_type = Column(String(50))  # STRING, INT, FLOAT, BOOLEAN, JSON
    is_encrypted = Column(Boolean, default=False)

    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)

    __table_args__ = (
        Index("idx_config_key", "key"),
    )


class BacktestResult(Base):
    """Backtest results and analysis"""
    __tablename__ = "backtest_results"

    id = Column(Integer, primary_key=True, autoincrement=True)
    test_name = Column(String(255), nullable=False)
    strategy_name = Column(String(100), nullable=False)
    strategy_version = Column(String(50))

    # Test parameters
    start_date = Column(Date, nullable=False)
    end_date = Column(Date, nullable=False)
    initial_balance = Column(Numeric(20, 2), nullable=False)
    symbols = Column(JSON)  # List of symbol strings

    # Results
    final_balance = Column(Numeric(20, 2), nullable=False)
    total_return = Column(Float)
    total_return_percent = Column(Float)

    # Risk metrics
    sharpe_ratio = Column(Float)
    sortino_ratio = Column(Float)
    max_drawdown = Column(Float)
    max_drawdown_percent = Column(Float)
    win_rate = Column(Float)
    profit_factor = Column(Float)

    # Trade statistics
    total_trades = Column(Integer)
    winning_trades = Column(Integer)
    losing_trades = Column(Integer)
    average_trade = Column(Numeric(18, 2))
    largest_win = Column(Numeric(18, 2))
    largest_loss = Column(Numeric(18, 2))

    # Additional metrics
    recovery_factor = Column(Float)
    monthly_return = Column(Float)
    calmar_ratio = Column(Float)

    created_at = Column(DateTime, server_default=func.now(), nullable=False)

    __table_args__ = (
        Index("idx_backtest_strategy", "strategy_name", "strategy_version"),
    )

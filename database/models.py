"""
HOPEFX Database Models
Complete SQLAlchemy models for all entities
"""

from datetime import datetime
from typing import Optional, List
import enum

try:
    from sqlalchemy import (
        Column, Integer, BigInteger, String, Float, Boolean,
        DateTime, ForeignKey, Enum, Text, Index, create_engine
    )
    from sqlalchemy.ext.declarative import declarative_base
    from sqlalchemy.orm import relationship, sessionmaker
    SQLALCHEMY_AVAILABLE = True
except ImportError:
    SQLALCHEMY_AVAILABLE = False
    # Stub everything so class bodies that reference Column etc. don't NameError
    class _Stub:
        def __init__(self, *a, **kw): pass
        def __call__(self, *a, **kw): return self
        def __getattr__(self, name): return self
    Column = BigInteger = Integer = String = Float = Boolean = _Stub()
    DateTime = ForeignKey = Enum = Text = Index = create_engine = _Stub()
    relationship = sessionmaker = _Stub()
    class _DummyBase:
        pass
    def declarative_base():
        return _DummyBase

Base = declarative_base()


class TradeStatus(enum.Enum):
    PENDING = "pending"
    OPEN = "open"
    CLOSED = "closed"
    CANCELLED = "cancelled"
    ERROR = "error"


class OrderSide(enum.Enum):
    BUY = "buy"
    SELL = "sell"


class OrderType(enum.Enum):
    MARKET = "market"
    LIMIT = "limit"
    STOP = "stop"
    STOP_LIMIT = "stop_limit"


class SignalSource(enum.Enum):
    TREND_FOLLOWING = "trend_following"
    MEAN_REVERSION = "mean_reversion"
    BREAKOUT = "breakout"
    MANUAL = "manual"
    STOP_LOSS = "stop_loss"
    TAKE_PROFIT = "take_profit"


class Trade(Base):
    """Trade record"""
    __tablename__ = 'trades'
    
    id = Column(Integer, primary_key=True)
    trade_id = Column(String(50), unique=True, nullable=False, index=True)
    symbol = Column(String(20), nullable=False, index=True)
    side = Column(Enum(OrderSide), nullable=False)
    
    # Entry
    entry_time = Column(DateTime, default=datetime.utcnow)
    entry_price = Column(Float, nullable=False)
    entry_quantity = Column(Float, nullable=False)
    
    # Exit
    exit_time = Column(DateTime, nullable=True)
    exit_price = Column(Float, nullable=True)
    exit_quantity = Column(Float, nullable=True)
    
    # P&L
    realized_pnl = Column(Float, default=0.0)
    unrealized_pnl = Column(Float, default=0.0)
    commission = Column(Float, default=0.0)
    swap = Column(Float, default=0.0)
    total_pnl = Column(Float, default=0.0)
    
    # Risk
    stop_loss = Column(Float, nullable=True)
    take_profit = Column(Float, nullable=True)
    risk_reward_ratio = Column(Float, nullable=True)
    
    # Strategy
    strategy = Column(String(50), nullable=True)
    signal_source = Column(Enum(SignalSource), nullable=True)
    signal_strength = Column(Float, nullable=True)
    
    # Status
    status = Column(Enum(TradeStatus), default=TradeStatus.PENDING)
    is_open = Column(Boolean, default=True)
    
    # Metadata
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    notes = Column(Text, nullable=True)
    
    # Relationships
    orders = relationship("Order", back_populates="trade", lazy="dynamic")
    signals = relationship("Signal", back_populates="trade", lazy="dynamic")
    
    def __repr__(self):
        return f"<Trade({self.trade_id}, {self.symbol}, {self.side.value}, PnL={self.total_pnl})>"
    
    def to_dict(self) -> dict:
        return {
            'id': self.id,
            'trade_id': self.trade_id,
            'symbol': self.symbol,
            'side': self.side.value,
            'entry_price': self.entry_price,
            'entry_quantity': self.entry_quantity,
            'exit_price': self.exit_price,
            'realized_pnl': self.realized_pnl,
            'status': self.status.value,
            'is_open': self.is_open
        }


class Order(Base):
    """Order record"""
    __tablename__ = 'orders'
    
    id = Column(Integer, primary_key=True)
    order_id = Column(String(50), unique=True, nullable=False, index=True)
    trade_id = Column(String(50), ForeignKey('trades.trade_id'), nullable=True)
    symbol = Column(String(20), nullable=False, index=True)
    
    # Order details
    side = Column(Enum(OrderSide), nullable=False)
    order_type = Column(Enum(OrderType), nullable=False)
    quantity = Column(Float, nullable=False)
    price = Column(Float, nullable=True)  # For limit orders
    stop_price = Column(Float, nullable=True)  # For stop orders
    
    # Execution
    filled_quantity = Column(Float, default=0.0)
    average_fill_price = Column(Float, nullable=True)
    commission = Column(Float, default=0.0)
    slippage = Column(Float, default=0.0)
    
    # Timing
    created_at = Column(DateTime, default=datetime.utcnow)
    submitted_at = Column(DateTime, nullable=True)
    filled_at = Column(DateTime, nullable=True)
    cancelled_at = Column(DateTime, nullable=True)
    
    # Status
    is_filled = Column(Boolean, default=False)
    is_cancelled = Column(Boolean, default=False)
    rejection_reason = Column(Text, nullable=True)
    
    # Broker info
    broker_order_id = Column(String(100), nullable=True)
    broker = Column(String(50), nullable=True)
    
    # Relationships
    trade = relationship("Trade", back_populates="orders")
    
    def to_dict(self) -> dict:
        return {
            'order_id': self.order_id,
            'symbol': self.symbol,
            'side': self.side.value,
            'type': self.order_type.value,
            'quantity': self.quantity,
            'filled_quantity': self.filled_quantity,
            'average_fill_price': self.average_fill_price,
            'is_filled': self.is_filled,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }


class Signal(Base):
    """Trading signal record"""
    __tablename__ = 'signals'
    
    id = Column(Integer, primary_key=True)
    signal_id = Column(String(50), unique=True, nullable=False)
    
    # Signal details
    symbol = Column(String(20), nullable=False, index=True)
    action = Column(String(10), nullable=False)  # buy, sell, close
    strategy = Column(String(50), nullable=False)
    source = Column(Enum(SignalSource), nullable=False)
    
    # Prices
    entry_price = Column(Float, nullable=True)
    stop_loss = Column(Float, nullable=True)
    take_profit = Column(Float, nullable=True)
    
    # Strength and metadata
    strength = Column(Float, nullable=True)
    confidence = Column(Float, nullable=True)
    metadata_json = Column(Text, nullable=True)  # JSON string
    
    # Execution
    executed = Column(Boolean, default=False)
    trade_id = Column(String(50), ForeignKey('trades.trade_id'), nullable=True)
    execution_time = Column(DateTime, nullable=True)
    
    # Timing
    generated_at = Column(DateTime, default=datetime.utcnow)
    expired_at = Column(DateTime, nullable=True)
    
    # Relationships
    trade = relationship("Trade", back_populates="signals")
    
    def to_dict(self) -> dict:
        return {
            'signal_id': self.signal_id,
            'symbol': self.symbol,
            'action': self.action,
            'strategy': self.strategy,
            'strength': self.strength,
            'executed': self.executed,
            'generated_at': self.generated_at.isoformat() if self.generated_at else None
        }


class AccountSnapshot(Base):
    """Periodic account snapshot"""
    __tablename__ = 'account_snapshots'
    
    id = Column(BigInteger, primary_key=True)
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)
    
    # Balance
    balance = Column(Float, nullable=False)
    equity = Column(Float, nullable=False)
    margin_used = Column(Float, default=0.0)
    free_margin = Column(Float, default=0.0)
    
    # P&L
    realized_pnl = Column(Float, default=0.0)
    unrealized_pnl = Column(Float, default=0.0)
    daily_pnl = Column(Float, default=0.0)
    
    # Exposure
    open_positions = Column(Integer, default=0)
    total_exposure = Column(Float, default=0.0)
    
    # Risk metrics
    current_drawdown = Column(Float, default=0.0)
    margin_level = Column(Float, nullable=True)
    
    def to_dict(self) -> dict:
        return {
            'timestamp': self.timestamp.isoformat() if self.timestamp else None,
            'balance': self.balance,
            'equity': self.equity,
            'open_positions': self.open_positions,
            'current_drawdown': self.current_drawdown
        }


class MarketData(Base):
    """Historical market data storage"""
    __tablename__ = 'market_data'
    
    id = Column(BigInteger, primary_key=True)
    symbol = Column(String(20), nullable=False, index=True)
    timeframe = Column(String(10), nullable=False, index=True)
    timestamp = Column(DateTime, nullable=False, index=True)
    
    # OHLCV
    open = Column(Float, nullable=False)
    high = Column(Float, nullable=False)
    low = Column(Float, nullable=False)
    close = Column(Float, nullable=False)
    volume = Column(Float, default=0.0)
    
    # Additional metrics
    spread = Column(Float, nullable=True)
    tick_count = Column(Integer, nullable=True)
    
    # Create composite index
    __table_args__ = (
        Index('idx_symbol_timeframe_timestamp', 'symbol', 'timeframe', 'timestamp'),
    )


class SystemEvent(Base):
    """System events and logs"""
    __tablename__ = 'system_events'
    
    id = Column(BigInteger, primary_key=True)
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)
    level = Column(String(20), nullable=False)  # DEBUG, INFO, WARNING, ERROR, CRITICAL
    component = Column(String(50), nullable=False, index=True)
    event_type = Column(String(50), nullable=False)
    
    # Content
    message = Column(Text, nullable=False)
    details_json = Column(Text, nullable=True)  # JSON string
    traceback = Column(Text, nullable=True)
    
    # Context
    trace_id = Column(String(50), nullable=True, index=True)
    session_id = Column(String(50), nullable=True)


class PerformanceMetric(Base):
    """Strategy and system performance metrics"""
    __tablename__ = 'performance_metrics'
    
    id = Column(BigInteger, primary_key=True)
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)
    metric_type = Column(String(50), nullable=False, index=True)  # strategy, system, risk
    
    # Metric details
    name = Column(String(100), nullable=False)
    value = Column(Float, nullable=False)
    unit = Column(String(20), nullable=True)
    labels_json = Column(Text, nullable=True)  # JSON string for tags
    
    # Context
    symbol = Column(String(20), nullable=True, index=True)
    strategy = Column(String(50), nullable=True, index=True)


class Configuration(Base):
    """Configuration history"""
    __tablename__ = 'configurations'
    
    id = Column(Integer, primary_key=True)
    timestamp = Column(DateTime, default=datetime.utcnow)
    environment = Column(String(20), nullable=False)
    
    config_key = Column(String(100), nullable=False)
    config_value = Column(Text, nullable=True)
    is_encrypted = Column(Boolean, default=False)
    
    changed_by = Column(String(100), nullable=True)
    change_reason = Column(Text, nullable=True)


class Account(Base):
    """Broker account snapshot."""
    __tablename__ = 'accounts'

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String(50), nullable=False, index=True)
    broker = Column(String(50), nullable=False)
    account_id = Column(String(100), nullable=True)
    balance = Column(Float, nullable=False, default=0.0)
    equity = Column(Float, nullable=True)
    margin_used = Column(Float, nullable=True)
    margin_free = Column(Float, nullable=True)
    currency = Column(String(10), default='USD')
    leverage = Column(Float, nullable=True)
    snapshot_at = Column(DateTime, default=datetime.utcnow, index=True)


class Position(Base):
    """Open trading position."""
    __tablename__ = 'positions'

    id = Column(String(50), primary_key=True)
    symbol = Column(String(20), nullable=False, index=True)
    side = Column(String(10), nullable=False)          # buy / sell
    quantity = Column(Float, nullable=False)
    entry_price = Column(Float, nullable=False)
    current_price = Column(Float, nullable=True)
    unrealized_pnl = Column(Float, nullable=True)
    realized_pnl = Column(Float, default=0.0)
    stop_loss = Column(Float, nullable=True)
    take_profit = Column(Float, nullable=True)
    broker = Column(String(50), nullable=True)
    user_id = Column(String(50), nullable=True, index=True)
    opened_at = Column(DateTime, default=datetime.utcnow)
    closed_at = Column(DateTime, nullable=True)
    status = Column(String(20), default='open')        # open, closed


class OrderBook(Base):
    """Snapshot of order book depth at a point in time."""
    __tablename__ = 'order_book_snapshots'

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    symbol = Column(String(20), nullable=False, index=True)
    bids_json = Column(Text, nullable=True)   # JSON [[price, size], ...]
    asks_json = Column(Text, nullable=True)
    spread = Column(Float, nullable=True)
    mid_price = Column(Float, nullable=True)
    timestamp = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)


class AISignal(Base):
    """AI-generated trading signal stored for audit and replay."""
    __tablename__ = 'ai_signals'

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    symbol = Column(String(20), nullable=False, index=True)
    signal_type = Column(String(10), nullable=False)   # buy, sell, hold
    confidence = Column(Float, nullable=False)
    entry_price = Column(Float, nullable=True)
    stop_loss = Column(Float, nullable=True)
    take_profit = Column(Float, nullable=True)
    source = Column(String(100), nullable=True)        # strategy name / brain
    executed = Column(Boolean, default=False)
    order_id = Column(String(50), nullable=True)
    generated_at = Column(DateTime, default=datetime.utcnow, index=True)
    expires_at = Column(DateTime, nullable=True)


class Prediction(Base):
    """ML model price prediction."""
    __tablename__ = 'predictions'

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    symbol = Column(String(20), nullable=False, index=True)
    model_name = Column(String(100), nullable=False)
    predicted_price = Column(Float, nullable=False)
    predicted_direction = Column(String(10), nullable=True)  # up, down, flat
    confidence = Column(Float, nullable=True)
    horizon_minutes = Column(Integer, nullable=True)
    actual_price = Column(Float, nullable=True)
    error_pct = Column(Float, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)


class NewsData(Base):
    """News article with sentiment score."""
    __tablename__ = 'news_data'

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    headline = Column(String(500), nullable=False)
    source = Column(String(100), nullable=True)
    url = Column(String(500), nullable=True)
    symbols = Column(String(200), nullable=True)       # comma-separated
    sentiment_score = Column(Float, nullable=True)     # -1.0 to 1.0
    sentiment_label = Column(String(20), nullable=True)  # positive, negative, neutral
    published_at = Column(DateTime, nullable=True, index=True)
    fetched_at = Column(DateTime, default=datetime.utcnow)


class PerformanceMetrics(Base):
    """Strategy / backtest performance metrics snapshot."""
    __tablename__ = 'performance_metrics'

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    strategy_name = Column(String(100), nullable=False, index=True)
    symbol = Column(String(20), nullable=True)
    timeframe = Column(String(20), nullable=True)
    total_trades = Column(Integer, default=0)
    winning_trades = Column(Integer, default=0)
    losing_trades = Column(Integer, default=0)
    win_rate = Column(Float, nullable=True)
    total_pnl = Column(Float, default=0.0)
    max_drawdown = Column(Float, nullable=True)
    sharpe_ratio = Column(Float, nullable=True)
    profit_factor = Column(Float, nullable=True)
    avg_trade_duration_minutes = Column(Float, nullable=True)
    recorded_at = Column(DateTime, default=datetime.utcnow, index=True)


class TickData(Base):
    """Real-time tick data storage."""
    __tablename__ = 'tick_data'

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    symbol = Column(String(20), nullable=False, index=True)
    bid = Column(Float, nullable=False)
    ask = Column(Float, nullable=False)
    last_price = Column(Float, nullable=True)
    volume = Column(Float, nullable=True)
    timestamp = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    source = Column(String(50), nullable=True)


class WalletTransaction(Base):
    """Persistent wallet transaction ledger — replaces in-memory dict."""
    __tablename__ = 'wallet_transactions'

    id = Column(BigInteger, primary_key=True)
    transaction_id = Column(String(50), unique=True, nullable=False, index=True)
    user_id = Column(String(50), nullable=False, index=True)
    transaction_type = Column(String(30), nullable=False)   # deposit, withdrawal, fee, commission
    amount = Column(Float, nullable=False)
    balance_after = Column(Float, nullable=False)
    currency = Column(String(10), default='USD')
    reference = Column(String(100), nullable=True)          # external payment ref
    status = Column(String(20), default='completed')        # pending, completed, failed
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)


class AuditLogEntry(Base):
    """Persistent, append-only audit log — replaces in-memory list."""
    __tablename__ = 'audit_log'

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    sequence_number = Column(BigInteger, nullable=False, index=True)
    timestamp = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    level = Column(String(20), nullable=False)              # INFO, COMPLIANCE, CRITICAL
    category = Column(String(30), nullable=False)           # ORDER, RISK, KYC, SYSTEM
    actor = Column(String(100), nullable=False)             # user_id or system component
    action = Column(String(200), nullable=False)
    data_json = Column(Text, nullable=True)                 # JSON payload
    hash_chain = Column(String(64), nullable=False)         # tamper-evident chain


class KYCRecord(Base):
    """Persistent KYC records — replaces in-memory dict."""
    __tablename__ = 'kyc_records'

    id = Column(Integer, primary_key=True)
    user_id = Column(String(50), unique=True, nullable=False, index=True)
    status = Column(String(20), nullable=False, default='unverified')  # unverified, pending, approved, rejected
    document_type = Column(String(50), nullable=True)
    verification_method = Column(String(50), nullable=True)
    submitted_at = Column(DateTime, nullable=True)
    verified_at = Column(DateTime, nullable=True)
    rejected_at = Column(DateTime, nullable=True)
    rejection_reason = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


# Create indexes for common queries
Index('idx_trades_symbol_status', Trade.symbol, Trade.status)
Index('idx_trades_entry_time', Trade.entry_time)
Index('idx_orders_symbol_created', Order.symbol, Order.created_at)
Index('idx_signals_generated_executed', Signal.generated_at, Signal.executed)
Index('idx_account_snapshots_timestamp', AccountSnapshot.timestamp)
Index('idx_wallet_user_created', WalletTransaction.user_id, WalletTransaction.created_at)
Index('idx_audit_timestamp', AuditLogEntry.timestamp)
Index('idx_kyc_user', KYCRecord.user_id)


def create_tables(engine):
    """Create all tables"""
    if SQLALCHEMY_AVAILABLE:
        Base.metadata.create_all(engine)
        logger.info("Database tables created")


def drop_tables(engine):
    """Drop all tables"""
    if SQLALCHEMY_AVAILABLE:
        Base.metadata.drop_all(engine)
        logger.info("Database tables dropped")

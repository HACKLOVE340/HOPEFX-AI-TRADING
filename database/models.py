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
    # Create dummy base for type hints
    class _DummyBase:
        pass
    declarative_base = lambda: _DummyBase

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


# Create indexes for common queries
Index('idx_trades_symbol_status', Trade.symbol, Trade.status)
Index('idx_trades_entry_time', Trade.entry_time)
Index('idx_orders_symbol_created', Order.symbol, Order.created_at)
Index('idx_signals_generated_executed', Signal.generated_at, Signal.executed)
Index('idx_account_snapshots_timestamp', AccountSnapshot.timestamp)


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

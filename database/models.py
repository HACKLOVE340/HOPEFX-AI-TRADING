# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
HOPEFX Database Models
Complete SQLAlchemy models for all entities
"""

import enum
import json
import logging
import uuid
from datetime import datetime, timezone

UTC = timezone.utc


def _utcnow() -> datetime:
    """Return current UTC time as timezone-aware datetime."""
    return datetime.now(UTC)


logger = logging.getLogger(__name__)

try:
    from sqlalchemy import (
        BigInteger,
        Boolean,
        Column,
        DateTime,
        Enum,
        Float,
        ForeignKey,
        Index,
        Integer,
        String,
        Text,
        UniqueConstraint,
    )
    from sqlalchemy.sql import func

    try:
        from sqlalchemy.orm import declarative_base
    except ImportError:
        from sqlalchemy.ext.declarative import declarative_base  # SQLAlchemy < 2.0
    from sqlalchemy.orm import relationship, sessionmaker  # noqa: F401  # pylint: disable=unused-import

    SQLALCHEMY_AVAILABLE = True
except ImportError:
    SQLALCHEMY_AVAILABLE = False
    _MISSING_MSG = (
        "CRITICAL DEPENDENCY MISSING: SQLAlchemy is not installed. "
        "All database persistence (trades, orders, audit trail, user accounts) "
        "is DISABLED. Fix with: pip install 'sqlalchemy>=2.0' "
        "or: pip install -r requirements.txt"
    )
    raise RuntimeError(_MISSING_MSG) from None


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

    __tablename__ = "trades"

    id = Column(Integer, primary_key=True)
    trade_id = Column(String(50), unique=True, nullable=True, index=True)
    # Idempotency key — set before broker submission; UNIQUE prevents duplicate fills
    # on network retry.  See Alembic migration b2c3d4e5f6a7.
    client_order_id = Column(String(100), unique=True, nullable=True, index=True)
    account_id = Column(Integer, ForeignKey("accounts.id", ondelete="CASCADE"), nullable=True, index=True)
    # user_id links trades directly to the auth user without requiring an Account row.
    # Populated on trade creation; used by _query_trades() for per-user history.
    user_id = Column(String(100), nullable=True, index=True)
    symbol = Column(String(20), nullable=False, index=True)
    side = Column(String(20), nullable=False, server_default="unknown")
    trade_type = Column(String(20), nullable=True)

    # Entry
    entry_time = Column(DateTime, default=_utcnow)
    entry_price = Column(Float, nullable=False, server_default="0.0")
    entry_quantity = Column(Float, nullable=False, server_default="0.0")
    size = Column(Float, nullable=True)  # alias for entry_quantity
    timestamp = Column(DateTime, nullable=True)

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
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)
    notes = Column(Text, nullable=True)

    # Relationships
    orders = relationship("Order", back_populates="trade", lazy="dynamic")
    signals = relationship("Signal", back_populates="trade", lazy="dynamic")
    account = relationship(
        "Account",
        back_populates="trades",
        primaryjoin="Trade.account_id == Account.id",
        foreign_keys="[Trade.account_id]",
    )

    def __repr__(self):
        return f"<Trade({self.trade_id}, {self.symbol}, {self.side.value}, PnL={self.total_pnl})>"

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "trade_id": self.trade_id,
            "symbol": self.symbol,
            "side": self.side.value,
            "entry_price": self.entry_price,
            "entry_quantity": self.entry_quantity,
            "exit_price": self.exit_price,
            "realized_pnl": self.realized_pnl,
            "status": self.status.value,
            "is_open": self.is_open,
        }


class Order(Base):
    """Order record"""

    __tablename__ = "orders"

    id = Column(Integer, primary_key=True)
    order_id = Column(String(50), unique=True, nullable=False, index=True)
    # Idempotency key — UNIQUE constraint prevents duplicate broker submissions.
    # Set by the trading engine before the first submission attempt.
    client_order_id = Column(String(100), unique=True, nullable=True, index=True)
    account_id = Column(Integer, nullable=True, index=True)
    trade_id = Column(String(50), ForeignKey("trades.trade_id"), nullable=True, index=True)
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
    created_at = Column(DateTime, default=_utcnow)
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
    trade = relationship(
        "Trade",
        back_populates="orders",
        foreign_keys="[Order.trade_id]",
    )
    account = relationship(
        "Account",
        back_populates="orders",
        primaryjoin="Order.account_id == Account.id",
        foreign_keys="[Order.account_id]",
    )

    def to_dict(self) -> dict:
        return {
            "order_id": self.order_id,
            "symbol": self.symbol,
            "side": self.side.value,
            "type": self.order_type.value,
            "quantity": self.quantity,
            "filled_quantity": self.filled_quantity,
            "average_fill_price": self.average_fill_price,
            "is_filled": self.is_filled,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class Signal(Base):
    """Trading signal record"""

    __tablename__ = "signals"

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
    trade_id = Column(String(50), ForeignKey("trades.trade_id"), nullable=True)
    execution_time = Column(DateTime, nullable=True)

    # Timing
    generated_at = Column(DateTime, default=_utcnow)
    expired_at = Column(DateTime, nullable=True)

    # Relationships
    trade = relationship("Trade", back_populates="signals")

    def to_dict(self) -> dict:
        return {
            "signal_id": self.signal_id,
            "symbol": self.symbol,
            "action": self.action,
            "strategy": self.strategy,
            "strength": self.strength,
            "executed": self.executed,
            "generated_at": self.generated_at.isoformat() if self.generated_at else None,
        }


class AccountSnapshot(Base):
    """Periodic account snapshot"""

    __tablename__ = "account_snapshots"

    id = Column(BigInteger, primary_key=True)
    timestamp = Column(DateTime, default=_utcnow, index=True)

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
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
            "balance": self.balance,
            "equity": self.equity,
            "open_positions": self.open_positions,
            "current_drawdown": self.current_drawdown,
        }


class MarketData(Base):
    """Historical market data storage"""

    __tablename__ = "market_data"

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
    __table_args__ = (Index("idx_symbol_timeframe_timestamp", "symbol", "timeframe", "timestamp"),)


class SystemEvent(Base):
    """System events and logs"""

    __tablename__ = "system_events"

    id = Column(BigInteger, primary_key=True)
    timestamp = Column(DateTime, default=_utcnow, index=True)
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
    """Time-series metric samples (strategy, system, risk)."""

    __tablename__ = "performance_metric_samples"

    id = Column(BigInteger, primary_key=True)
    timestamp = Column(DateTime, default=_utcnow, index=True)
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

    __tablename__ = "configurations"

    id = Column(Integer, primary_key=True)
    timestamp = Column(DateTime, default=_utcnow)
    environment = Column(String(20), nullable=False)

    config_key = Column(String(100), nullable=False, index=True, unique=True)
    config_value = Column(Text, nullable=True)
    is_encrypted = Column(Boolean, default=False)

    changed_by = Column(String(100), nullable=True)
    change_reason = Column(Text, nullable=True)


class Account(Base):
    """Broker account snapshot."""

    __tablename__ = "accounts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    account_name = Column(String(100), nullable=True)
    broker = Column(String(50), nullable=True)
    account_id = Column(String(100), nullable=True)
    balance = Column(Float, nullable=True, default=0.0)
    equity = Column(Float, nullable=True)
    margin_used = Column(Float, nullable=True)
    margin_free = Column(Float, nullable=True)
    currency = Column(String(10), default="USD")
    leverage = Column(Float, nullable=True)
    snapshot_at = Column(DateTime, default=_utcnow, index=True)

    user = relationship("User", back_populates="accounts")
    trades = relationship(
        "Trade",
        back_populates="account",
        lazy="dynamic",
        primaryjoin="Account.id == foreign(Trade.account_id)",
    )
    orders = relationship(
        "Order",
        back_populates="account",
        lazy="dynamic",
        primaryjoin="Account.id == foreign(Order.account_id)",
    )
    positions = relationship(
        "Position",
        back_populates="account",
        lazy="dynamic",
        primaryjoin="Account.id == foreign(Position.account_id)",
    )


class Position(Base):
    """Open trading position."""

    __tablename__ = "positions"

    id = Column(String(50), primary_key=True, default=lambda: str(uuid.uuid4()))
    account_id = Column(Integer, nullable=True, index=True)
    symbol = Column(String(20), nullable=False, index=True)
    side = Column(String(10), nullable=True)
    quantity = Column(Float, nullable=True)
    size = Column(Float, nullable=True)  # alias for quantity
    entry_price = Column(Float, nullable=True)
    current_price = Column(Float, nullable=True)
    market_value = Column(Float, nullable=True)  # current market value
    unrealized_pnl = Column(Float, nullable=True)
    realized_pnl = Column(Float, default=0.0)
    stop_loss = Column(Float, nullable=True)
    take_profit = Column(Float, nullable=True)
    broker = Column(String(50), nullable=True)
    user_id = Column(String(50), nullable=True, index=True)
    opened_at = Column(DateTime, default=_utcnow)
    closed_at = Column(DateTime, nullable=True)
    status = Column(String(20), default="open")

    account = relationship(
        "Account",
        back_populates="positions",
        primaryjoin="Position.account_id == Account.id",
        foreign_keys="[Position.account_id]",
    )


class OrderBook(Base):
    """Snapshot of order book depth at a point in time."""

    __tablename__ = "order_book_snapshots"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    symbol = Column(String(20), nullable=False, index=True)
    bids_json = Column(Text, nullable=True)  # JSON [[price, size], ...]
    asks_json = Column(Text, nullable=True)
    spread = Column(Float, nullable=True)
    mid_price = Column(Float, nullable=True)
    timestamp = Column(DateTime, default=_utcnow, nullable=False, index=True)


class AISignal(Base):
    """AI-generated trading signal stored for audit and replay."""

    __tablename__ = "ai_signals"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    symbol = Column(String(20), nullable=False, index=True)
    signal_type = Column(String(10), nullable=False)  # buy, sell, hold
    confidence = Column(Float, nullable=False)
    entry_price = Column(Float, nullable=True)
    stop_loss = Column(Float, nullable=True)
    take_profit = Column(Float, nullable=True)
    source = Column(String(100), nullable=True)  # strategy name / brain
    executed = Column(Boolean, default=False)
    order_id = Column(String(50), nullable=True)
    generated_at = Column(DateTime, default=_utcnow, index=True)
    expires_at = Column(DateTime, nullable=True)


class Prediction(Base):
    """ML model price prediction."""

    __tablename__ = "predictions"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    symbol = Column(String(20), nullable=False, index=True)
    model_name = Column(String(100), nullable=False)
    predicted_price = Column(Float, nullable=False)
    predicted_direction = Column(String(10), nullable=True)  # up, down, flat
    confidence = Column(Float, nullable=True)
    horizon_minutes = Column(Integer, nullable=True)
    actual_price = Column(Float, nullable=True)
    error_pct = Column(Float, nullable=True)
    created_at = Column(DateTime, default=_utcnow, index=True)


class NewsData(Base):
    """News article with sentiment score."""

    __tablename__ = "news_data"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    headline = Column(String(500), nullable=False)
    source = Column(String(100), nullable=True)
    url = Column(String(500), nullable=True)
    symbols = Column(String(200), nullable=True)  # comma-separated
    sentiment_score = Column(Float, nullable=True)  # -1.0 to 1.0
    sentiment_label = Column(String(20), nullable=True)  # positive, negative, neutral
    published_at = Column(DateTime, nullable=True, index=True)
    fetched_at = Column(DateTime, default=_utcnow)


class PerformanceMetrics(Base):
    """Strategy / backtest performance metrics snapshot."""

    __tablename__ = "performance_metrics"

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
    recorded_at = Column(DateTime, default=_utcnow, index=True)


class TimestampMixin:
    """
    Mixin that adds created_at / updated_at columns to any model.

    Works with both sync and async SQLAlchemy sessions because it uses
    server_default (database-side) rather than Python-side default callables,
    which avoids the "greenlet_spawn" error in async contexts.
    """

    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class SoftDeleteMixin:
    """
    Mixin that adds soft-delete support (deleted_at timestamp).

    Rows are never physically removed; set deleted_at to mark as deleted.
    Filter with ``Model.deleted_at.is_(None)`` in queries.
    """

    deleted_at = Column(DateTime(timezone=True), nullable=True, index=True)

    @property
    def is_deleted(self) -> bool:
        return self.deleted_at is not None


class TickData(Base):
    """
    Sub-millisecond tick data storage.

    Schema is designed for TimescaleDB hypertable partitioning on ts_ns.
    When TimescaleDB is not available the table works as a plain PostgreSQL
    or SQLite table with the composite index providing equivalent query
    performance for moderate data volumes.

    TimescaleDB setup (run once after CREATE TABLE):
        SELECT create_hypertable('tick_data', 'ts_ns',
            chunk_time_interval => 86400000000000,  -- 1 day in ns
            if_not_exists => TRUE);
        SELECT add_compression_policy('tick_data', INTERVAL '7 days');

    The ts_ns column stores nanosecond-epoch integers so that:
      - Ordering is exact (no floating-point rounding)
      - TimescaleDB can partition on it directly
      - Python time.time_ns() maps directly without conversion
    """

    __tablename__ = "tick_data"
    __table_args__ = (
        # Primary query pattern: latest N ticks for a symbol
        Index("idx_tick_data_symbol_ts_ns", "symbol", "ts_ns", postgresql_using="brin"),
        # Range queries: ticks between two timestamps
        Index("idx_tick_data_ts_ns", "ts_ns"),
        # Source-specific queries (feed health, per-source analytics)
        Index("idx_tick_data_source_ts_ns", "source", "ts_ns"),
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    # Nanosecond epoch — use time.time_ns() when inserting
    ts_ns = Column(BigInteger, nullable=False, index=True)
    symbol = Column(String(20), nullable=False, index=True)
    bid = Column(Float, nullable=False)
    ask = Column(Float, nullable=False)
    # mid and spread are computed columns in TimescaleDB; stored here for
    # compatibility with plain PostgreSQL / SQLite.
    mid = Column(Float, nullable=True)
    spread = Column(Float, nullable=True)
    last_price = Column(Float, nullable=True)
    volume = Column(Float, nullable=True, default=0.0)
    # Legacy datetime column — kept for backward compatibility with existing
    # queries that filter on timestamp.  New code should use ts_ns.
    timestamp = Column(DateTime(timezone=True), default=_utcnow, nullable=False, index=True)
    source = Column(String(50), nullable=True, index=True)
    # Quality flag: good | stale | suspect | rejected
    quality = Column(String(20), nullable=True, default="good")
    # Confidence score from multi-source consensus (0.0–1.0)
    confidence = Column(Float, nullable=True, default=1.0)
    # Lineage ID links back to DataLineageStore record
    lineage_id = Column(String(36), nullable=True, index=True)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "ts_ns": self.ts_ns,
            "symbol": self.symbol,
            "bid": self.bid,
            "ask": self.ask,
            "mid": self.mid if self.mid is not None else (self.bid + self.ask) / 2.0,
            "spread": self.spread if self.spread is not None else self.ask - self.bid,
            "volume": self.volume,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
            "source": self.source,
            "quality": self.quality,
            "confidence": self.confidence,
            "lineage_id": self.lineage_id,
        }

    @classmethod
    def from_gold_tick(cls, tick: "Any") -> "TickData":
        """Construct a TickData row from a data_layer.types.GoldTick."""
        import time as _time

        return cls(
            ts_ns=int(tick.timestamp.timestamp() * 1_000_000_000),
            symbol=tick.symbol,
            bid=tick.bid,
            ask=tick.ask,
            mid=tick.mid,
            spread=tick.spread,
            volume=0.0,
            timestamp=tick.timestamp,
            source=str(tick.source),
            quality=str(tick.quality),
            confidence=tick.confidence,
            lineage_id=tick.lineage_id,
        )


class WalletTransaction(Base):
    """Persistent wallet transaction ledger — replaces in-memory dict."""

    __tablename__ = "wallet_transactions"

    id = Column(BigInteger, primary_key=True)
    transaction_id = Column(String(50), unique=True, nullable=False, index=True)
    user_id = Column(String(50), nullable=False, index=True)
    transaction_type = Column(String(30), nullable=False)  # deposit, withdrawal, fee, commission
    amount = Column(Float, nullable=False)
    balance_after = Column(Float, nullable=False)
    currency = Column(String(10), default="USD")
    reference = Column(String(100), nullable=True)  # external payment ref
    status = Column(String(20), default="completed")  # pending, completed, failed
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=_utcnow, index=True)


class AuditLogEntry(Base):
    """Persistent, append-only audit log — replaces in-memory list."""

    __tablename__ = "audit_log"

    # Integer maps to INTEGER in SQLite (gets the implicit rowid alias / autoincrement)
    # and to BIGINT in PostgreSQL via dialect — both correct for an audit log.
    id = Column(Integer, primary_key=True, autoincrement=True)
    sequence_number = Column(BigInteger, nullable=False, index=True)
    timestamp = Column(DateTime, default=_utcnow, nullable=False, index=True)
    # created_at mirrors timestamp for query compatibility with the superadmin audit API.
    created_at = Column(DateTime, default=_utcnow, nullable=False, index=True)
    level = Column(String(20), nullable=False)  # INFO, COMPLIANCE, CRITICAL
    category = Column(String(30), nullable=False)  # ORDER, RISK, KYC, SYSTEM
    actor = Column(String(100), nullable=False)  # user_id or system component
    action = Column(String(200), nullable=False)
    data_json = Column(Text, nullable=True)  # JSON payload
    hash_chain = Column(String(64), nullable=False)  # tamper-evident chain
    # Fields required by the superadmin audit/security APIs.
    event_type = Column(String(100), nullable=True, index=True)
    user_id = Column(String(100), nullable=True, index=True)
    detail = Column(Text, nullable=True)
    ip_address = Column(String(45), nullable=True)


class KYCRecord(Base):
    """Persistent KYC records — replaces in-memory dict."""

    __tablename__ = "kyc_records"

    id = Column(Integer, primary_key=True)
    user_id = Column(String(50), unique=True, nullable=False, index=True)
    status = Column(String(20), nullable=False, default="unverified")  # unverified, pending, approved, rejected
    document_type = Column(String(50), nullable=True)
    verification_method = Column(String(50), nullable=True)
    submitted_at = Column(DateTime, nullable=True)
    verified_at = Column(DateTime, nullable=True)
    rejected_at = Column(DateTime, nullable=True)
    rejection_reason = Column(Text, nullable=True)
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)


# ---------------------------------------------------------------------------
# Composite indexes for common query patterns
# ---------------------------------------------------------------------------

# Trades
Index("idx_trades_symbol_status", Trade.symbol, Trade.status)
Index("idx_trades_entry_time", Trade.entry_time)
# Covering index for the most common trade list query: user + status + time
Index("idx_trades_user_status_entry", Trade.user_id, Trade.status, Trade.entry_time)
# Partial-style: open trades by symbol (status filter applied in WHERE)
Index("idx_trades_symbol_entry_time", Trade.symbol, Trade.entry_time)
# History-by-user without status filter (e.g. paginated trade history endpoint)
Index("idx_trades_user_entry_time", Trade.user_id, Trade.entry_time)

# Orders — Order has no user_id; use account_id + symbol as the covering key
Index("idx_orders_symbol_created", Order.symbol, Order.created_at)
Index("idx_orders_account_symbol_created", Order.account_id, Order.symbol, Order.created_at)
# Unfilled order lookups by symbol (polling for pending orders)
Index("idx_orders_symbol_filled", Order.symbol, Order.is_filled)

# Signals
Index("idx_signals_generated_executed", Signal.generated_at, Signal.executed)
Index("idx_signals_symbol_generated", Signal.symbol, Signal.generated_at)
Index("idx_signals_strategy", Signal.strategy)

# Account snapshots — no user_id column; timestamp is the only access key
Index("idx_account_snapshots_timestamp", AccountSnapshot.timestamp)

# Market data — symbol + timeframe + timestamp is the primary access pattern
Index("idx_market_data_symbol_tf_ts", MarketData.symbol, MarketData.timeframe, MarketData.timestamp)

# Wallet
Index("idx_wallet_user_created", WalletTransaction.user_id, WalletTransaction.created_at)
Index("idx_wallet_type_created", WalletTransaction.transaction_type, WalletTransaction.created_at)

# Audit log
Index("idx_audit_timestamp", AuditLogEntry.timestamp)
Index("idx_audit_category_ts", AuditLogEntry.category, AuditLogEntry.timestamp)
Index("idx_audit_actor_ts", AuditLogEntry.actor, AuditLogEntry.timestamp)
Index("idx_audit_user_ts", AuditLogEntry.user_id, AuditLogEntry.timestamp)

# KYC
Index("idx_kyc_user", KYCRecord.user_id)
Index("idx_kyc_status", KYCRecord.status)

# Positions — open positions by user is the hot path
Index("idx_positions_user_symbol", Position.user_id, Position.symbol)
Index("idx_positions_user_status", Position.user_id, Position.status)

# AI signals — generated_at is the existing indexed column
Index("idx_ai_signals_symbol_ts", AISignal.symbol, AISignal.generated_at)
Index("idx_ai_signals_executed_ts", AISignal.executed, AISignal.generated_at)

# News data — published_at is the existing indexed column; symbols is a text field
Index("idx_news_published_at", NewsData.published_at)
Index("idx_news_source_published", NewsData.source, NewsData.published_at)

# PerformanceMetric uses metric_type + name (not metric_name)
Index("idx_perf_metric_type_name_ts", PerformanceMetric.metric_type, PerformanceMetric.name, PerformanceMetric.timestamp)
Index("idx_perf_metric_symbol_ts", PerformanceMetric.symbol, PerformanceMetric.timestamp)


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


# ── Proper enums expected by tests ───────────────────────────────────────────


class AccountStatus(enum.Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    SUSPENDED = "suspended"
    CLOSED = "closed"


class TradeType(enum.Enum):
    LONG = "long"
    SHORT = "short"
    HEDGE = "hedge"


class OrderStatus(enum.Enum):
    PENDING = "pending"
    OPEN = "open"
    PARTIALLY_FILLED = "partially_filled"
    FILLED = "filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"


class PositionStatus(enum.Enum):
    OPEN = "open"
    CLOSING = "closing"
    CLOSED = "closed"


class PredictionType(enum.Enum):
    PRICE = "price"
    DIRECTION = "direction"
    VOLATILITY = "volatility"
    TREND = "trend"


class RiskLevel(enum.Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class MarketDataType(enum.Enum):
    OHLCV = "ohlcv"
    TICK = "tick"
    DEPTH = "depth"
    NEWS = "news"


# ── Re-export User from its canonical location ────────────────────────────────
# User is defined in database/user_models.py. Import it here so that code doing
# `from database.models import User` keeps working, and so SQLAlchemy resolves
# the "User" string reference in Account.user without a second class definition.
try:
    from database.user_models import User  # noqa: F401  # pylint: disable=unused-import
except ImportError as _user_models_err:
    raise ImportError(
        "CRITICAL: database/user_models.py could not be imported. "
        "Ensure all dependencies are installed: pip install -r requirements.txt"
    ) from _user_models_err
# ── Session model (used by master_control and other internal modules) ─────────

if SQLALCHEMY_AVAILABLE:

    class Session(Base):
        __tablename__ = "sessions"
        id = Column(Integer, primary_key=True)
        user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
        token = Column(String(512), unique=True, nullable=False)
        expires_at = Column(DateTime, nullable=False)
        created_at = Column(DateTime, default=_utcnow)

else:

    class Session:
        __tablename__ = "sessions"
        __table__ = type("T", (), {"columns": []})()

# ── Email suppression table ───────────────────────────────────────────────────
# Populated by the SendGrid webhook handler (POST /api/email/webhook).
# EmailChannel.send() checks this table before dispatching any message.

if SQLALCHEMY_AVAILABLE:

    class EmailSuppression(Base):
        __tablename__ = "email_suppressions"
        id = Column(Integer, primary_key=True)
        email = Column(String(320), unique=True, nullable=False, index=True)
        reason = Column(String(64), nullable=False)  # bounce | spam_report | unsubscribe
        created_at = Column(DateTime, default=_utcnow)
else:

    class EmailSuppression:  # type: ignore[no-redef]
        __tablename__ = "email_suppressions"
        __table__ = type("T", (), {"columns": []})()


# ── Dedicated watchlists table ────────────────────────────────────────────────
# Each row is one symbol in one user's watchlist.
# Replaces the JSON-column approach (configurations table keyed by
# "watchlist:{user_id}") with a proper relational table.
# Alembic migration: alembic/versions/f1a2b3c4d5e6_add_watchlists_table.py

if SQLALCHEMY_AVAILABLE:

    class WatchlistEntry(Base):
        __tablename__ = "watchlists"
        id = Column(BigInteger, primary_key=True, autoincrement=True)
        user_id = Column(String(128), nullable=False, index=True)
        symbol = Column(String(20), nullable=False)
        added_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
        sort_order = Column(Integer, nullable=False, server_default="0")

        __table_args__ = (UniqueConstraint("user_id", "symbol", name="uq_watchlist_user_symbol"),)

        def __repr__(self) -> str:
            return f"<WatchlistEntry user={self.user_id!r} symbol={self.symbol!r}>"
else:

    class WatchlistEntry:  # type: ignore[no-redef]
        __tablename__ = "watchlists"
        __table__ = type("T", (), {"columns": []})()


# ── Crypto payment table ──────────────────────────────────────────────────────
# Replaces the in-memory _pending dict in api/payments.py.
# Survives pod restarts; safe across replicas.

if SQLALCHEMY_AVAILABLE:

    class CryptoPayment(Base):
        """Persistent crypto payment record."""

        __tablename__ = "crypto_payments"

        # Use Integer for SQLite compatibility (BigInteger maps to INTEGER in SQLite anyway)
        id = Column(Integer, primary_key=True, autoincrement=True)
        payment_id = Column(String(100), unique=True, nullable=False, index=True)
        user_id = Column(String(128), nullable=False, index=True)
        plan_id = Column(String(100), nullable=False)
        currency = Column(String(10), nullable=False)  # BTC | ETH | USDT
        network = Column(String(20), nullable=False)  # BTC | ERC20 | TRC20 | BEP20
        address = Column(String(200), nullable=False)
        amount_usd = Column(Float, nullable=False)
        amount_crypto = Column(Float, nullable=False)
        rate_usd = Column(Float, nullable=False)  # USD price per coin at creation
        status = Column(
            String(20), nullable=False, default="pending", index=True
        )  # pending | confirming | complete | expired | failed
        confirmations = Column(Integer, default=0)
        confirmations_required = Column(Integer, nullable=False)
        # Webhook / on-chain data
        tx_hash = Column(String(200), nullable=True)
        webhook_payload = Column(Text, nullable=True)  # raw JSON from processor
        created_at = Column(DateTime(timezone=True), default=_utcnow, index=True)
        expires_at = Column(DateTime(timezone=True), nullable=False)
        confirmed_at = Column(DateTime(timezone=True), nullable=True)
        updated_at = Column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)

        def to_dict(self) -> dict:
            return {
                "payment_id": self.payment_id,
                "user_id": self.user_id,
                "plan_id": self.plan_id,
                "currency": self.currency,
                "network": self.network,
                "address": self.address,
                "amount_usd": self.amount_usd,
                "amount_crypto": self.amount_crypto,
                "rate_usd": self.rate_usd,
                "status": self.status,
                "confirmations": self.confirmations,
                "confirmations_required": self.confirmations_required,
                "tx_hash": self.tx_hash,
                "created_at": self.created_at.isoformat() if self.created_at else None,
                "expires_at": self.expires_at.isoformat() if self.expires_at else None,
                "confirmed_at": self.confirmed_at.isoformat() if self.confirmed_at else None,
            }

else:

    class CryptoPayment:  # type: ignore[no-redef]
        __tablename__ = "crypto_payments"
        __table__ = type("T", (), {"columns": []})()


# ── Transactional outbox table ────────────────────────────────────────────────
# Critical events (kill switch, AML block, order fill) are written here in the
# same DB transaction as the state change, then relayed to Redis pub/sub by the
# OutboxRelay background task.  Guarantees at-least-once delivery even when
# Redis is temporarily unavailable.

if SQLALCHEMY_AVAILABLE:

    class OutboxEvent(Base):
        """Transactional outbox for at-least-once event delivery."""

        __tablename__ = "outbox_events"

        id = Column(Integer, primary_key=True, autoincrement=True)
        event_type = Column(String(100), nullable=False, index=True)
        channel = Column(String(100), nullable=False)  # Redis pub/sub channel
        payload = Column(Text, nullable=False)  # JSON
        # status: "pending" | "published" | "dead_letter"
        status = Column(String(20), nullable=False, default="pending", index=True)
        created_at = Column(DateTime(timezone=True), default=_utcnow, index=True)
        published_at = Column(DateTime(timezone=True), nullable=True)
        attempts = Column(Integer, default=0)
        max_attempts = Column(Integer, default=5)
        last_error = Column(Text, nullable=True)
        idempotency_key = Column(String(128), nullable=True, unique=True)

        __table_args__ = (
            Index("idx_outbox_unpublished", "published_at", "created_at"),
            Index("idx_outbox_status_created", "status", "created_at"),
        )

else:

    class OutboxEvent:  # type: ignore[no-redef]
        __tablename__ = "outbox_events"
        __table__ = type("T", (), {"columns": []})()


# ── Key-value config store ────────────────────────────────────────────────────
# Replaces in-memory dicts for risk settings, auto-pause config, etc.
# Shared across all pods; reads are cheap (indexed by key).

if SQLALCHEMY_AVAILABLE:

    class ConfigStore(Base):
        """Generic key-value config store backed by the database."""

        __tablename__ = "config_store"

        id = Column(Integer, primary_key=True, autoincrement=True)
        key = Column(String(200), unique=True, nullable=False, index=True)
        value_json = Column(Text, nullable=False)
        changed_by = Column(String(128), nullable=True)
        updated_at = Column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)

else:

    class ConfigStore:  # type: ignore[no-redef]
        __tablename__ = "config_store"
        __table__ = type("T", (), {"columns": []})()


# ── Chargeback table ──────────────────────────────────────────────────────────
# Tracks payment disputes raised by cardholders via their bank.
# Populated by the Stripe webhook handler on charge.dispute.created events.

if SQLALCHEMY_AVAILABLE:

    class Chargeback(Base):
        """Payment chargeback / dispute record."""

        __tablename__ = "chargebacks"

        id = Column(Integer, primary_key=True, autoincrement=True)
        chargeback_id = Column(String(100), unique=True, nullable=False, index=True)
        payment_id = Column(String(100), nullable=False, index=True)
        user_id = Column(String(128), nullable=False, index=True)
        username = Column(String(255), nullable=True)
        amount = Column(Float, nullable=False)
        currency = Column(String(10), nullable=False, default="USD")
        reason = Column(String(255), nullable=False)
        # open | won | lost | pending_evidence
        status = Column(String(30), nullable=False, default="open", index=True)
        provider = Column(String(50), nullable=False, default="stripe")
        evidence_due_by = Column(DateTime(timezone=True), nullable=True)
        opened_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)
        resolved_at = Column(DateTime(timezone=True), nullable=True)
        raw_payload = Column(Text, nullable=True)  # raw JSON from payment provider

        def to_dict(self) -> dict:
            return {
                "chargeback_id": self.chargeback_id,
                "payment_id": self.payment_id,
                "user_id": self.user_id,
                "username": self.username or "",
                "amount": self.amount,
                "currency": self.currency,
                "reason": self.reason,
                "status": self.status,
                "provider": self.provider,
                "evidence_due_by": self.evidence_due_by.isoformat() if self.evidence_due_by else None,
                "opened_at": self.opened_at.isoformat() if self.opened_at else None,
                "resolved_at": self.resolved_at.isoformat() if self.resolved_at else None,
            }

else:

    class Chargeback:  # type: ignore[no-redef]
        __tablename__ = "chargebacks"
        __table__ = type("T", (), {"columns": []})()


# ── Tax report table ──────────────────────────────────────────────────────────
# One row per jurisdiction per period.  Populated by the tax-reporting job
# that runs on the 1st of each month.

if SQLALCHEMY_AVAILABLE:

    class TaxReport(Base):
        """Periodic tax report per jurisdiction."""

        __tablename__ = "tax_reports"

        id = Column(Integer, primary_key=True, autoincrement=True)
        report_id = Column(String(100), unique=True, nullable=False, index=True)
        period = Column(String(20), nullable=False)  # e.g. "2025-Q1" or "2025-01"
        jurisdiction = Column(String(100), nullable=False)  # e.g. "US-CA", "GB", "NG"
        total_revenue = Column(Float, nullable=False, default=0.0)
        taxable_amount = Column(Float, nullable=False, default=0.0)
        tax_rate_pct = Column(Float, nullable=False, default=0.0)
        tax_owed = Column(Float, nullable=False, default=0.0)
        currency = Column(String(10), nullable=False, default="USD")
        # draft | filed | paid | overdue
        status = Column(String(20), nullable=False, default="draft", index=True)
        due_date = Column(DateTime(timezone=True), nullable=True)
        filed_at = Column(DateTime(timezone=True), nullable=True)
        created_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)
        updated_at = Column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)

        __table_args__ = (UniqueConstraint("period", "jurisdiction", name="uq_tax_report_period_jurisdiction"),)

        def to_dict(self) -> dict:
            return {
                "report_id": self.report_id,
                "period": self.period,
                "jurisdiction": self.jurisdiction,
                "total_revenue": self.total_revenue,
                "taxable_amount": self.taxable_amount,
                "tax_rate_pct": self.tax_rate_pct,
                "tax_owed": self.tax_owed,
                "currency": self.currency,
                "status": self.status,
                "due_date": self.due_date.isoformat() if self.due_date else None,
                "filed_at": self.filed_at.isoformat() if self.filed_at else None,
                "created_at": self.created_at.isoformat() if self.created_at else None,
            }

else:

    class TaxReport:  # type: ignore[no-redef]
        __tablename__ = "tax_reports"
        __table__ = type("T", (), {"columns": []})()


# ── Reconciliation record table ───────────────────────────────────────────────
# Tracks expected vs actual amounts per payment provider per period.
# Discrepancies trigger an alert and require manual resolution.

if SQLALCHEMY_AVAILABLE:

    class ReconciliationRecord(Base):
        """Payment reconciliation record — expected vs actual per provider."""

        __tablename__ = "reconciliation_records"

        id = Column(Integer, primary_key=True, autoincrement=True)
        recon_id = Column(String(100), unique=True, nullable=False, index=True)
        period = Column(String(20), nullable=False)  # e.g. "2025-01"
        provider = Column(String(50), nullable=False)  # stripe | flutterwave | crypto
        expected_amount = Column(Float, nullable=False, default=0.0)
        actual_amount = Column(Float, nullable=False, default=0.0)
        discrepancy = Column(Float, nullable=False, default=0.0)
        currency = Column(String(10), nullable=False, default="USD")
        transaction_count = Column(Integer, nullable=False, default=0)
        # matched | discrepancy | pending | resolved
        status = Column(String(20), nullable=False, default="pending", index=True)
        notes = Column(Text, nullable=True)
        created_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)
        resolved_at = Column(DateTime(timezone=True), nullable=True)
        resolved_by = Column(String(128), nullable=True)

        __table_args__ = (UniqueConstraint("period", "provider", name="uq_recon_period_provider"),)

        def to_dict(self) -> dict:
            return {
                "recon_id": self.recon_id,
                "period": self.period,
                "provider": self.provider,
                "expected_amount": self.expected_amount,
                "actual_amount": self.actual_amount,
                "discrepancy": self.discrepancy,
                "currency": self.currency,
                "transaction_count": self.transaction_count,
                "status": self.status,
                "notes": self.notes,
                "created_at": self.created_at.isoformat() if self.created_at else None,
                "resolved_at": self.resolved_at.isoformat() if self.resolved_at else None,
            }

else:

    class ReconciliationRecord:  # type: ignore[no-redef]
        __tablename__ = "reconciliation_records"
        __table__ = type("T", (), {"columns": []})()


def _add_enum_value(enum_cls, name, value):
    """Add a new member to an existing Enum if it doesn't already exist."""
    if name in enum_cls._member_map_:
        return
    new_member = object.__new__(enum_cls)
    new_member._name_ = name
    new_member._value_ = value
    enum_cls._member_map_[name] = new_member
    enum_cls._value2member_map_[value] = new_member
    # Bypass enum's __setattr__ which rejects new members
    type.__setattr__(enum_cls, name, new_member)


_add_enum_value(SignalSource, "PRICE", "price")
_add_enum_value(SignalSource, "OHLCV", "ohlcv")
_add_enum_value(SignalSource, "LOW", "low")
_add_enum_value(TradeStatus, "ACTIVE", "active")
_add_enum_value(TradeStatus, "CLOSING", "closing")
_add_enum_value(TradeStatus, "PARTIALLY_FILLED", "partially_filled")
_add_enum_value(OrderSide, "LONG", "long")


# ── APIKey — per-user programmatic API keys ───────────────────────────────────
if SQLALCHEMY_AVAILABLE:

    class APIKey(Base):
        """Programmatic API key issued to a user for external integrations."""

        __tablename__ = "api_keys"

        id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
        user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
        name = Column(String(100), nullable=False)
        key_hash = Column(String(64), unique=True, nullable=False)  # SHA-256 of raw key
        key_prefix = Column(String(12), nullable=False)  # first 8 chars shown in UI
        scopes = Column(Text, nullable=True)  # JSON-encoded list of scopes
        is_active = Column(Boolean, default=True, nullable=False)
        created_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)
        last_used_at = Column(DateTime(timezone=True), nullable=True)
        expires_at = Column(DateTime(timezone=True), nullable=True)

        __table_args__ = (
            Index("idx_api_keys_user", "user_id"),
            Index("idx_api_keys_hash", "key_hash"),
        )

        def to_dict(self) -> dict:
            return {
                "key_id": self.id,
                "user_id": self.user_id,
                "name": self.name,
                "prefix": self.key_prefix,
                "scopes": json.loads(self.scopes) if self.scopes else [],
                "is_active": self.is_active,
                "created_at": self.created_at.isoformat() if self.created_at else None,
                "last_used_at": self.last_used_at.isoformat() if self.last_used_at else None,
            }

else:

    class APIKey:  # type: ignore[no-redef]
        __tablename__ = "api_keys"
        __table__ = type("T", (), {"columns": []})()


# ── AMLAlert — Anti-Money-Laundering compliance flags ────────────────────────
if SQLALCHEMY_AVAILABLE:

    class AMLAlert(Base):
        """AML compliance alert raised by the risk engine."""

        __tablename__ = "aml_alerts"

        id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
        user_id = Column(String(36), nullable=False, index=True)
        username = Column(String(100), nullable=True)
        alert_type = Column(String(50), nullable=False)
        severity = Column(String(20), nullable=False, default="medium")  # low/medium/high/critical
        amount = Column(Float, nullable=False, default=0.0)
        currency = Column(String(10), nullable=False, default="USD")
        description = Column(Text, nullable=True)
        status = Column(String(20), nullable=False, default="pending")  # pending/reviewed/escalated/dismissed
        notes = Column(Text, nullable=True)
        reviewed_by = Column(String(128), nullable=True)
        reviewed_at = Column(DateTime(timezone=True), nullable=True)
        created_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)

        __table_args__ = (
            Index("idx_aml_alerts_user", "user_id"),
            Index("idx_aml_alerts_status", "status"),
            Index("idx_aml_alerts_severity", "severity"),
        )

        def to_dict(self) -> dict:
            return {
                "alert_id": self.id,
                "user_id": self.user_id,
                "username": self.username or "",
                "alert_type": self.alert_type,
                "severity": self.severity,
                "amount": float(self.amount),
                "currency": self.currency,
                "description": self.description or "",
                "status": self.status,
                "notes": self.notes or "",
                "reviewed_by": self.reviewed_by,
                "reviewed_at": self.reviewed_at.isoformat() if self.reviewed_at else None,
                "created_at": self.created_at.isoformat() if self.created_at else None,
            }

else:

    class AMLAlert:  # type: ignore[no-redef]
        __tablename__ = "aml_alerts"
        __table__ = type("T", (), {"columns": []})()


# ── BrokerConnection — live broker integration records ───────────────────────
if SQLALCHEMY_AVAILABLE:

    class BrokerConnection(Base):
        """Tracks active broker connections and their real-time health metrics."""

        __tablename__ = "broker_connections"

        id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
        broker_name = Column(String(100), nullable=False, index=True)
        broker_type = Column(String(50), nullable=False, default="unknown")  # oanda/ibkr/bybit/etc.
        status = Column(String(20), nullable=False, default="disconnected")  # connected/disconnected/error
        latency_ms = Column(Integer, nullable=True, default=0)
        fill_rate_pct = Column(Float, nullable=True, default=0.0)
        slippage_avg_pips = Column(Float, nullable=True, default=0.0)
        orders_today = Column(Integer, nullable=True, default=0)
        uptime_pct = Column(Float, nullable=True, default=0.0)
        last_heartbeat = Column(DateTime(timezone=True), nullable=True)
        created_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)
        updated_at = Column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)

        __table_args__ = (Index("idx_broker_conn_name", "broker_name"),)

        def to_dict(self) -> dict:
            return {
                "broker_id": self.id,
                "name": self.broker_name,
                "type": self.broker_type,
                "status": self.status,
                "latency_ms": self.latency_ms or 0,
                "fill_rate_pct": float(self.fill_rate_pct or 0.0),
                "slippage_avg_pips": float(self.slippage_avg_pips or 0.0),
                "orders_today": self.orders_today or 0,
                "uptime_pct": float(self.uptime_pct or 0.0),
                "last_heartbeat": self.last_heartbeat.isoformat() if self.last_heartbeat else None,
            }

else:

    class BrokerConnection:  # type: ignore[no-redef]
        __tablename__ = "broker_connections"
        __table__ = type("T", (), {"columns": []})()


# ── WhitelabelTenant — durable white-label tenant records ────────────────────
if SQLALCHEMY_AVAILABLE:

    class WhitelabelTenant(Base):
        """Persistent white-label tenant record (replaces in-memory WhiteLabelManager store)."""

        __tablename__ = "whitelabel_tenants"

        id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
        name = Column(String(200), nullable=False)
        owner_email = Column(String(255), nullable=False, index=True)
        # status: active | suspended | trial | cancelled
        status = Column(String(20), nullable=False, default="trial", index=True)
        # reseller tier: starter | growth | enterprise
        tier = Column(String(30), nullable=False, default="starter")
        # JSON-encoded list of enabled FeatureFlag values
        features_json = Column(Text, nullable=False, default="[]")
        # Branding
        primary_color = Column(String(20), nullable=True, default="#3b82f6")
        logo_url = Column(Text, nullable=True)
        company_name = Column(String(200), nullable=True)
        custom_domain = Column(String(255), nullable=True, unique=True)
        # Hashed API key (shown once at creation, stored as SHA-256 hex)
        api_key_hash = Column(String(64), nullable=True)
        # Revenue tracking
        revenue_usd = Column(Float, nullable=False, default=0.0)
        user_count = Column(Integer, nullable=False, default=0)
        # Lifecycle
        trial_ends_at = Column(DateTime(timezone=True), nullable=True)
        expires_at = Column(DateTime(timezone=True), nullable=True)
        created_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)
        updated_at = Column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)

        __table_args__ = (
            Index("idx_wl_tenant_status", "status"),
            Index("idx_wl_tenant_owner", "owner_email"),
        )

        def to_dict(self) -> dict:
            import json as _json

            features: list = []
            try:
                features = _json.loads(self.features_json or "[]")
            except Exception:
                logger.debug("Suppressed non-fatal exception", exc_info=True)  # nosec B110
            return {
                "tenant_id": self.id,
                "name": self.name,
                "owner_email": self.owner_email,
                "status": self.status,
                "tier": self.tier,
                "features": features,
                "theme": {
                    "primary_color": self.primary_color or "#3b82f6",
                    "logo_url": self.logo_url or "",
                    "company_name": self.company_name or self.name,
                },
                "custom_domain": self.custom_domain,
                "revenue_usd": float(self.revenue_usd or 0.0),
                "user_count": int(self.user_count or 0),
                "trial_ends_at": self.trial_ends_at.isoformat() if self.trial_ends_at else None,
                "expires_at": self.expires_at.isoformat() if self.expires_at else None,
                "created_at": self.created_at.isoformat() if self.created_at else None,
                "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            }

else:

    class WhitelabelTenant:  # type: ignore[no-redef]
        __tablename__ = "whitelabel_tenants"
        __table__ = type("T", (), {"columns": []})()


# ── GDPRRequest — durable GDPR data-subject request records ──────────────────
if SQLALCHEMY_AVAILABLE:

    class GDPRRequest(Base):
        """
        Persistent GDPR data-subject request (Art. 15–22).

        Replaces the Redis-only store so requests survive restarts and are
        included in database backups / audit exports.
        """

        __tablename__ = "gdpr_requests"

        id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
        user_id = Column(String(36), nullable=False, index=True)
        user_email = Column(String(255), nullable=True)
        # request_type: access | erasure | portability | rectification | restriction | objection
        request_type = Column(String(30), nullable=False, index=True)
        # status: pending | in_progress | completed | rejected
        status = Column(String(20), nullable=False, default="pending", index=True)
        # Free-text description from the data subject
        description = Column(Text, nullable=True)
        # Admin notes added during processing
        notes = Column(Text, nullable=True)
        # Who processed this request
        processed_by = Column(String(128), nullable=True)
        # Timestamps
        submitted_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)
        completed_at = Column(DateTime(timezone=True), nullable=True)
        created_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)
        updated_at = Column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)

        __table_args__ = (
            Index("idx_gdpr_user", "user_id"),
            Index("idx_gdpr_status", "status"),
            Index("idx_gdpr_type", "request_type"),
        )

        def to_dict(self) -> dict:
            return {
                "request_id": self.id,
                "user_id": self.user_id,
                "user_email": self.user_email or "",
                "request_type": self.request_type,
                "status": self.status,
                "description": self.description or "",
                "notes": self.notes or "",
                "processed_by": self.processed_by,
                "submitted_at": self.submitted_at.isoformat() if self.submitted_at else None,
                "completed_at": self.completed_at.isoformat() if self.completed_at else None,
                "created_at": self.created_at.isoformat() if self.created_at else None,
            }

else:

    class GDPRRequest:  # type: ignore[no-redef]
        __tablename__ = "gdpr_requests"
        __table__ = type("T", (), {"columns": []})()


# ── TradeJournal — per-trade notes, tags, and emotion tracking ────────────────
if SQLALCHEMY_AVAILABLE:

    class TradeJournal(Base):
        """Per-trade journal entry: notes, tags, emotion, and self-assessment."""

        __tablename__ = "trade_journal"

        id = Column(Integer, primary_key=True, autoincrement=True)
        user_id = Column(
            String(36),
            ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        )
        trade_id = Column(
            String(50),
            ForeignKey("trades.trade_id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        )
        title = Column(String(200), nullable=True)
        notes = Column(Text, nullable=True)
        tags = Column(Text, nullable=True)           # JSON array of strings
        emotion = Column(String(50), nullable=True)  # "confident","fearful","neutral"
        rating = Column(Integer, nullable=True)      # 1-5 self-assessment
        setup_quality = Column(String(20), nullable=True)  # "A","B","C"
        lessons_learned = Column(Text, nullable=True)
        screenshot_url = Column(String(500), nullable=True)
        created_at = Column(
            DateTime(timezone=True),
            server_default=func.now(),
            nullable=False,
        )
        updated_at = Column(
            DateTime(timezone=True),
            server_default=func.now(),
            onupdate=func.now(),
            nullable=False,
        )

        __table_args__ = (
            Index("idx_journal_user_created", "user_id", "created_at"),
            Index("idx_journal_trade", "trade_id"),
        )

        def to_dict(self) -> dict:
            import json as _json
            tags_val: list = []
            try:
                tags_val = _json.loads(self.tags or "[]")
            except Exception:  # nosec B110
                pass
            return {
                "id": self.id,
                "user_id": self.user_id,
                "trade_id": self.trade_id,
                "title": self.title,
                "notes": self.notes or "",
                "tags": tags_val,
                "emotion": self.emotion,
                "rating": self.rating,
                "setup_quality": self.setup_quality,
                "lessons_learned": self.lessons_learned,
                "screenshot_url": self.screenshot_url,
                "created_at": self.created_at.isoformat() if self.created_at else None,
                "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            }

else:

    class TradeJournal:  # type: ignore[no-redef]
        __tablename__ = "trade_journal"
        __table__ = type("T", (), {"columns": []})()


# ── SubAccount — team/prop-firm sub-account management ───────────────────────
if SQLALCHEMY_AVAILABLE:

    class SubAccount(Base):
        """Sub-account for team or prop-firm trading."""

        __tablename__ = "sub_accounts"

        id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
        owner_id = Column(
            String(36),
            ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        )
        name = Column(String(100), nullable=False)
        description = Column(Text, nullable=True)
        # account_type: "personal" | "prop_firm" | "team" | "managed"
        account_type = Column(String(30), nullable=False, default="personal")
        currency = Column(String(10), nullable=False, default="USD")
        initial_balance = Column(Float, nullable=True)
        current_balance = Column(Float, nullable=True)
        max_drawdown_pct = Column(Float, nullable=True)
        daily_loss_limit = Column(Float, nullable=True)
        is_active = Column(Boolean, nullable=False, default=True)
        broker = Column(String(50), nullable=True)
        broker_account_id = Column(String(100), nullable=True)
        created_at = Column(
            DateTime(timezone=True),
            server_default=func.now(),
            nullable=False,
        )
        updated_at = Column(
            DateTime(timezone=True),
            server_default=func.now(),
            onupdate=func.now(),
            nullable=False,
        )

        __table_args__ = (
            Index("idx_sub_accounts_owner", "owner_id"),
            Index("idx_sub_accounts_active", "is_active"),
        )

        def to_dict(self) -> dict:
            return {
                "id": self.id,
                "owner_id": self.owner_id,
                "name": self.name,
                "description": self.description,
                "account_type": self.account_type,
                "currency": self.currency,
                "initial_balance": self.initial_balance,
                "current_balance": self.current_balance,
                "max_drawdown_pct": self.max_drawdown_pct,
                "daily_loss_limit": self.daily_loss_limit,
                "is_active": self.is_active,
                "broker": self.broker,
                "broker_account_id": self.broker_account_id,
                "created_at": self.created_at.isoformat() if self.created_at else None,
                "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            }

    class SubAccountMember(Base):
        """Many-to-many: users can be members of sub-accounts with a role."""

        __tablename__ = "sub_account_members"

        sub_account_id = Column(
            String(36),
            ForeignKey("sub_accounts.id", ondelete="CASCADE"),
            primary_key=True,
        )
        user_id = Column(
            String(36),
            ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        )
        # role: "owner" | "trader" | "viewer" | "risk_manager"
        role = Column(String(30), nullable=False, default="viewer")
        joined_at = Column(
            DateTime(timezone=True),
            server_default=func.now(),
            nullable=False,
        )

        __table_args__ = (
            Index("idx_sub_account_members_user", "user_id"),
        )

else:

    class SubAccount:  # type: ignore[no-redef]
        __tablename__ = "sub_accounts"
        __table__ = type("T", (), {"columns": []})()

    class SubAccountMember:  # type: ignore[no-redef]
        __tablename__ = "sub_account_members"
        __table__ = type("T", (), {"columns": []})()


# ── BillingHistory — Stripe/Flutterwave payment records ──────────────────────
if SQLALCHEMY_AVAILABLE:

    class BillingHistory(Base):
        """Immutable payment event record from Stripe or Flutterwave webhooks."""

        __tablename__ = "billing_history"

        id = Column(Integer, primary_key=True, autoincrement=True)
        user_id = Column(
            String(36),
            ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        )
        # provider: "stripe" | "flutterwave"
        provider = Column(String(30), nullable=False)
        provider_payment_id = Column(String(200), nullable=True, unique=True)
        provider_subscription_id = Column(String(200), nullable=True)
        # event_type: "payment_succeeded" | "payment_failed" | "subscription_created"
        #             | "subscription_cancelled" | "refund" | "chargeback"
        event_type = Column(String(50), nullable=False)
        amount = Column(Float, nullable=True)
        currency = Column(String(10), nullable=True, default="USD")
        plan = Column(String(30), nullable=True)
        # status: "pending" | "succeeded" | "failed" | "refunded"
        status = Column(String(30), nullable=False, default="pending")
        description = Column(Text, nullable=True)
        metadata_json = Column(Text, nullable=True)  # raw provider payload
        idempotency_key = Column(String(128), nullable=True, unique=True)
        created_at = Column(
            DateTime(timezone=True),
            server_default=func.now(),
            nullable=False,
        )

        __table_args__ = (
            Index("idx_billing_user_created", "user_id", "created_at"),
            Index("idx_billing_provider_id", "provider_payment_id"),
            Index("idx_billing_status", "status"),
        )

        def to_dict(self) -> dict:
            return {
                "id": self.id,
                "user_id": self.user_id,
                "provider": self.provider,
                "provider_payment_id": self.provider_payment_id,
                "provider_subscription_id": self.provider_subscription_id,
                "event_type": self.event_type,
                "amount": self.amount,
                "currency": self.currency or "USD",
                "plan": self.plan,
                "status": self.status,
                "description": self.description,
                "created_at": self.created_at.isoformat() if self.created_at else None,
            }

else:

    class BillingHistory:  # type: ignore[no-redef]
        __tablename__ = "billing_history"
        __table__ = type("T", (), {"columns": []})()


# ── UserProfile — extended user profile (bio, avatar, preferences) ────────────
if SQLALCHEMY_AVAILABLE:

    class UserProfile(Base):
        """Extended user profile — one row per user (1:1 with users table)."""

        __tablename__ = "user_profiles"

        user_id = Column(
            String(36),
            ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        )
        display_name = Column(String(100), nullable=True)
        bio = Column(Text, nullable=True)
        avatar_url = Column(String(500), nullable=True)
        timezone = Column(String(50), nullable=True, default="UTC")
        locale = Column(String(10), nullable=True, default="en")
        theme = Column(String(20), nullable=True, default="dark")
        notification_prefs = Column(Text, nullable=True)  # JSON
        # trading_experience: "beginner" | "intermediate" | "advanced" | "professional"
        trading_experience = Column(String(20), nullable=True)
        preferred_instruments = Column(Text, nullable=True)  # JSON array
        # risk_tolerance: "conservative" | "moderate" | "aggressive"
        risk_tolerance = Column(String(20), nullable=True)
        referral_code = Column(String(20), nullable=True, unique=True)
        referred_by = Column(String(36), nullable=True)
        created_at = Column(
            DateTime(timezone=True),
            server_default=func.now(),
            nullable=False,
        )
        updated_at = Column(
            DateTime(timezone=True),
            server_default=func.now(),
            onupdate=func.now(),
            nullable=False,
        )

        def to_dict(self) -> dict:
            import json as _json
            prefs: dict = {}
            instruments: list = []
            try:
                prefs = _json.loads(self.notification_prefs or "{}")
            except Exception:  # nosec B110
                pass
            try:
                instruments = _json.loads(self.preferred_instruments or "[]")
            except Exception:  # nosec B110
                pass
            return {
                "user_id": self.user_id,
                "display_name": self.display_name,
                "bio": self.bio,
                "avatar_url": self.avatar_url,
                "timezone": self.timezone or "UTC",
                "locale": self.locale or "en",
                "theme": self.theme or "dark",
                "notification_prefs": prefs,
                "trading_experience": self.trading_experience,
                "preferred_instruments": instruments,
                "risk_tolerance": self.risk_tolerance,
                "referral_code": self.referral_code,
                "referred_by": self.referred_by,
                "created_at": self.created_at.isoformat() if self.created_at else None,
                "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            }

else:

    class UserProfile:  # type: ignore[no-redef]
        __tablename__ = "user_profiles"
        __table__ = type("T", (), {"columns": []})()

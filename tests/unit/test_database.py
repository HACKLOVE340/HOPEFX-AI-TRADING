"""
Tests for the database models module.
"""

import pytest
from datetime import datetime
from decimal import Decimal

from database.models import (
    Base,
    # Enums
    AccountStatus,
    TradeType,
    OrderStatus,
    OrderType,
    PositionStatus,
    PredictionType,
    RiskLevel,
    MarketDataType,
    # Models
    User,
    Session,
    Account,
    Trade,
    Order,
    Position,
)


class TestDatabaseEnums:
    """Tests for database enumeration types."""
    
    def test_account_status_values(self):
        """Test AccountStatus enum values."""
        assert AccountStatus.ACTIVE.value == "active"
        assert AccountStatus.INACTIVE.value == "inactive"
        assert AccountStatus.SUSPENDED.value == "suspended"
        assert AccountStatus.CLOSED.value == "closed"
    
    def test_trade_type_values(self):
        """Test TradeType enum values."""
        assert TradeType.LONG.value == "long"
        assert TradeType.SHORT.value == "short"
        assert TradeType.HEDGE.value == "hedge"
    
    def test_order_status_values(self):
        """Test OrderStatus enum values."""
        assert OrderStatus.PENDING.value == "pending"
        assert OrderStatus.OPEN.value == "open"
        assert OrderStatus.PARTIALLY_FILLED.value == "partially_filled"
        assert OrderStatus.FILLED.value == "filled"
        assert OrderStatus.CANCELLED.value == "cancelled"
        assert OrderStatus.REJECTED.value == "rejected"
    
    def test_order_type_values(self):
        """Test OrderType enum values."""
        assert OrderType.MARKET.value == "market"
        assert OrderType.LIMIT.value == "limit"
        assert OrderType.STOP.value == "stop"
        assert OrderType.STOP_LIMIT.value == "stop_limit"
    
    def test_position_status_values(self):
        """Test PositionStatus enum values."""
        assert PositionStatus.OPEN.value == "open"
        assert PositionStatus.CLOSING.value == "closing"
        assert PositionStatus.CLOSED.value == "closed"
    
    def test_prediction_type_values(self):
        """Test PredictionType enum values."""
        assert PredictionType.PRICE.value == "price"
        assert PredictionType.DIRECTION.value == "direction"
        assert PredictionType.VOLATILITY.value == "volatility"
        assert PredictionType.TREND.value == "trend"
    
    def test_risk_level_values(self):
        """Test RiskLevel enum values."""
        assert RiskLevel.LOW.value == "low"
        assert RiskLevel.MEDIUM.value == "medium"
        assert RiskLevel.HIGH.value == "high"
        assert RiskLevel.CRITICAL.value == "critical"
    
    def test_market_data_type_values(self):
        """Test MarketDataType enum values."""
        assert MarketDataType.OHLCV.value == "ohlcv"
        assert MarketDataType.TICK.value == "tick"
        assert MarketDataType.DEPTH.value == "depth"
        assert MarketDataType.NEWS.value == "news"


class TestUserModel:
    """Tests for User model."""
    
    def test_user_model_table_name(self):
        """Test User model table name."""
        assert User.__tablename__ == "users"
    
    def test_user_model_columns(self):
        """Test User model has expected columns."""
        columns = [c.name for c in User.__table__.columns]
        
        assert 'id' in columns
        assert 'username' in columns
        assert 'email' in columns
        assert 'password_hash' in columns
        assert 'status' in columns
        assert 'created_at' in columns
    
    def test_user_model_relationships(self):
        """Test User model has relationships."""
        # Check that relationships are defined
        assert hasattr(User, 'accounts')
        assert hasattr(User, 'sessions')


class TestAccountModel:
    """Tests for Account model."""
    
    def test_account_model_table_name(self):
        """Test Account model table name."""
        assert Account.__tablename__ == "accounts"
    
    def test_account_model_columns(self):
        """Test Account model has expected columns."""
        columns = [c.name for c in Account.__table__.columns]
        
        assert 'id' in columns
        assert 'user_id' in columns
        assert 'account_name' in columns
        assert 'broker' in columns
        assert 'balance' in columns
        assert 'equity' in columns
        assert 'leverage' in columns
    
    def test_account_model_relationships(self):
        """Test Account model has relationships."""
        assert hasattr(Account, 'user')
        assert hasattr(Account, 'trades')
        assert hasattr(Account, 'orders')
        assert hasattr(Account, 'positions')


class TestTradeModel:
    """Tests for Trade model."""
    
    def test_trade_model_table_name(self):
        """Test Trade model table name."""
        assert Trade.__tablename__ == "trades"
    
    def test_trade_model_columns(self):
        """Test Trade model has expected columns."""
        columns = [c.name for c in Trade.__table__.columns]
        
        assert 'id' in columns
        assert 'account_id' in columns
        assert 'symbol' in columns
        assert 'trade_type' in columns


class TestOrderModel:
    """Tests for Order model."""
    
    def test_order_model_table_name(self):
        """Test Order model table name."""
        assert Order.__tablename__ == "orders"
    
    def test_order_model_columns(self):
        """Test Order model has expected columns."""
        columns = [c.name for c in Order.__table__.columns]
        
        assert 'id' in columns
        assert 'account_id' in columns
        assert 'symbol' in columns
        assert 'order_type' in columns


class TestPositionModel:
    """Tests for Position model."""
    
    def test_position_model_table_name(self):
        """Test Position model table name."""
        assert Position.__tablename__ == "positions"
    
    def test_position_model_columns(self):
        """Test Position model has expected columns."""
        columns = [c.name for c in Position.__table__.columns]
        
        assert 'id' in columns
        assert 'account_id' in columns
        assert 'symbol' in columns


class TestSessionModel:
    """Tests for Session model."""
    
    def test_session_model_table_name(self):
        """Test Session model table name."""
        assert Session.__tablename__ == "sessions"
    
    def test_session_model_columns(self):
        """Test Session model has expected columns."""
        columns = [c.name for c in Session.__table__.columns]
        
        assert 'id' in columns
        assert 'user_id' in columns
        assert 'token' in columns
        assert 'expires_at' in columns


class TestBase:
    """Tests for SQLAlchemy Base."""
    
    def test_base_exists(self):
        """Test Base exists and is usable."""
        assert Base is not None
        assert hasattr(Base, 'metadata')

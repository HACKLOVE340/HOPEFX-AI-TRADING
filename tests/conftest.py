"""
Pytest configuration and shared fixtures for HOPEFX tests.
"""

import pytest
import os
import tempfile
from pathlib import Path
from datetime import datetime, timedelta
import pandas as pd
import numpy as np

# Add project root to path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from config import ConfigManager
from database.models import Base, Trade, Position
from cache import MarketDataCache
from strategies import BaseStrategy, StrategyManager
from risk import RiskManager, RiskConfig
from brokers import PaperTradingBroker
from notifications import NotificationManager


@pytest.fixture(scope="session")
def test_config():
    """Create a test configuration."""
    with tempfile.TemporaryDirectory() as tmpdir:
        os.environ['CONFIG_ENCRYPTION_KEY'] = 'a' * 64
        os.environ['CONFIG_SALT'] = 'b' * 32
        os.environ['DATABASE_URL'] = f'sqlite:///{tmpdir}/test.db'
        os.environ['REDIS_URL'] = 'redis://localhost:6379/15'  # Test database
        os.environ['ENVIRONMENT'] = 'testing'

        config = ConfigManager()
        yield config


@pytest.fixture
def db_session(test_config):
    """Create a test database session."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    engine = create_engine(test_config.get('database.url'))
    Base.metadata.create_all(engine)

    Session = sessionmaker(bind=engine)
    session = Session()

    yield session

    session.close()
    Base.metadata.drop_all(engine)


@pytest.fixture
def market_cache(test_config):
    """Create a test market data cache."""
    cache = MarketDataCache(test_config)
    yield cache
    try:
        cache.clear_all()
    except:
        pass  # Ignore if Redis not available


@pytest.fixture
def risk_manager(test_config):
    """Create a test risk manager."""
    from risk.manager import RiskConfig
    risk_config = RiskConfig(
        max_position_size=10000,
        max_open_positions=5,
        max_daily_loss=1000,
        max_drawdown=0.10
    )
    return RiskManager(risk_config, initial_balance=100000)


@pytest.fixture
def paper_broker(test_config):
    """Create a test paper trading broker."""
    broker_config = {
        'initial_balance': 100000
    }
    return PaperTradingBroker(config=broker_config)


@pytest.fixture
def strategy_manager(test_config, risk_manager, paper_broker):
    """Create a test strategy manager."""
    return StrategyManager()


@pytest.fixture
def notification_manager(test_config):
    """Create a test notification manager."""
    return NotificationManager(config=test_config)


@pytest.fixture
def sample_market_data():
    """Generate sample market data for testing."""
    dates = pd.date_range(start='2023-01-01', periods=100, freq='h')

    # Generate realistic price data with trend and noise
    base_price = 1.1000
    trend = np.linspace(0, 0.01, 100)
    noise = np.random.normal(0, 0.0005, 100)
    prices = base_price + trend + noise

    data = pd.DataFrame({
        'timestamp': dates,
        'open': prices * (1 + np.random.normal(0, 0.0001, 100)),
        'high': prices * (1 + np.abs(np.random.normal(0, 0.0005, 100))),
        'low': prices * (1 - np.abs(np.random.normal(0, 0.0005, 100))),
        'close': prices,
        'volume': np.random.randint(1000, 10000, 100)
    })

    return data


@pytest.fixture
def sample_tick_data():
    """Generate sample tick data for testing."""
    return {
        'symbol': 'EUR_USD',
        'bid': 1.1000,
        'ask': 1.1002,
        'timestamp': datetime.now(),
        'volume': 1000
    }


@pytest.fixture
def mock_strategy(test_config):
    """Create a mock strategy for testing."""
    from strategies.base import StrategyConfig
    
    class MockStrategy(BaseStrategy):
        def __init__(self, name="MockStrategy", symbol="EUR_USD"):
            # Create StrategyConfig from parameters
            config = StrategyConfig(
                name=name,
                symbol=symbol,
                timeframe="1H"
            )
            super().__init__(config)
            self.generate_signal_called = False
            self.signal_to_return = None
            
            # Add backward compatibility properties
            self._name = name
            self._symbol = symbol
            self.performance = {
                'total_signals': 0,
                'winning_trades': 0,
                'losing_trades': 0,
                'total_pnl': 0,
                'win_rate': 0.0
            }

        @property
        def name(self):
            return self.config.name
        
        @property
        def symbol(self):
            return self.config.symbol
        
        @property
        def is_active(self):
            from strategies.base import StrategyStatus
            return self.status == StrategyStatus.RUNNING

        def analyze(self, data):
            """Implement required abstract method."""
            return {'analyzed': True, 'data': data}

        def generate_signal(self, analysis):
            """Override to match test expectations."""
            self.generate_signal_called = True
            return self.signal_to_return
        
        def update_performance(self, profit_loss, signal_type):
            """Update performance metrics (backward compatibility)."""
            self.performance['total_signals'] += 1
            self.performance['total_pnl'] += profit_loss
            
            if profit_loss > 0:
                self.performance['winning_trades'] += 1
            else:
                self.performance['losing_trades'] += 1
            
            # Calculate win rate
            if self.performance['total_signals'] > 0:
                self.performance['win_rate'] = (
                    self.performance['winning_trades'] / 
                    self.performance['total_signals'] * 100
                )

    return MockStrategy


# Pytest configuration
def pytest_configure(config):
    """Configure pytest."""
    config.addinivalue_line(
        "markers", "unit: Unit tests"
    )
    config.addinivalue_line(
        "markers", "integration: Integration tests"
    )
    config.addinivalue_line(
        "markers", "slow: Slow running tests"
    )
    config.addinivalue_line(
        "markers", "requires_redis: Tests that require Redis"
    )

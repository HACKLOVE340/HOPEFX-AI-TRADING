# tests/conftest.py
import pytest
import asyncio
from pathlib import Path
import tempfile
import shutil
from datetime import datetime, timedelta
import pandas as pd
import numpy as np

@pytest.fixture(scope='session')
def event_loop():
    """Create event loop for async tests."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()

@pytest.fixture
def temp_dir():
    """Create temporary directory for test outputs."""
    path = tempfile.mkdtemp()
    yield Path(path)
    shutil.rmtree(path)

@pytest.fixture
def sample_market_data():
    """Generate sample OHLCV data for testing."""
    dates = pd.date_range(start='2024-01-01', periods=100, freq='1H')
    np.random.seed(42)
    
    data = pd.DataFrame({
        'timestamp': dates,
        'open': 2000 + np.random.randn(100).cumsum(),
        'high': 2000 + np.random.randn(100).cumsum() + 5,
        'low': 2000 + np.random.randn(100).cumsum() - 5,
        'close': 2000 + np.random.randn(100).cumsum(),
        'volume': np.random.randint(1000, 10000, 100)
    })
    return data

@pytest.fixture
def mock_broker():
    """Mock broker for testing."""
    from unittest.mock import MagicMock
    
    broker = MagicMock()
    broker.connect.return_value = True
    broker.get_balance.return_value = {'USD': 100000}
    broker.place_order.return_value = {
        'id': 'test-order-123',
        'status': 'filled',
        'filled_price': 2000.50
    }
    return broker

@pytest.fixture
def test_config(temp_dir):
    """Test configuration."""
    return {
        'logging': {'level': 'DEBUG'},
        'database': {'url': f'sqlite:///{temp_dir}/test.db'},
        'cache': {'type': 'memory'},
        'risk': {
            'max_position_size': 0.1,
            'max_drawdown': 0.05,
            'daily_loss_limit': 1000
        }
    }

"""
pytest configuration and fixtures.
"""

import asyncio
from datetime import datetime, timezone
from decimal import Decimal

import pytest
import pytest_asyncio

from src.core.config import Settings, get_settings
from src.domain.enums import TradeDirection
from src.domain.models import Account, TickData


@pytest.fixture(scope="session")
def event_loop():
    """Create event loop for async tests."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
def test_settings():
    """Test configuration."""
    return Settings(
        environment="development",
        debug=True,
        database={"url": "sqlite+aiosqlite:///test.db"},
        redis={"url": "redis://localhost:6379/1"}
    )


@pytest_asyncio.fixture
async def test_account():
    """Create test account."""
    return Account(
        broker="PAPER",
        account_id="TEST_001",
        balance=Decimal("100000"),
        equity=Decimal("100000"),
        margin_used=Decimal("0"),
        margin_available=Decimal("100000"),
        open_positions={},
        daily_pnl=Decimal("0"),
        total_pnl=Decimal("0"),
        max_drawdown=Decimal("0")
    )


@pytest.fixture
def sample_tick():
    """Create sample tick data."""
    return TickData(
        symbol="XAUUSD",
        timestamp=datetime.now(timezone.utc),
        bid=Decimal("1800.50"),
        ask=Decimal("1800.60"),
        mid=Decimal("1800.55"),
        volume=100,
        source="TEST"
    )


@pytest.fixture
def sample_ohlcv():
    """Create sample OHLCV data."""
    import pandas as pd
    
    dates = pd.date_range(start="2024-01-01", periods=100, freq="1min")
    return pd.DataFrame({
        "open": [1800 + i * 0.01 for i in range(100)],
        "high": [1800 + i * 0.01 + 0.5 for i in range(100)],
        "low": [1800 + i * 0.01 - 0.5 for i in range(100)],
        "close": [1800 + i * 0.01 + 0.1 for i in range(100)],
        "volume": [1000] * 100,
    }, index=dates)

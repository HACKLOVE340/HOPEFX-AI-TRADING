"""
HOPEFX Test Configuration
Pytest fixtures and test utilities
"""

import os
import tempfile
import pytest
import asyncio
import numpy as np
from datetime import datetime, timedelta
from typing import Generator

# Import core components for testing
from brain.brain import HOPEFXBrain, BrainState, SystemState
from brokers import PaperTradingBroker
from risk.manager import RiskManager, RiskConfig
from strategies.manager import StrategyManager
from data.real_time_price_engine import Tick, OHLCV


@pytest.fixture
def event_loop():
    """Create event loop for async tests"""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
async def paper_broker():
    """Create paper trading broker for tests"""
    broker = PaperTradingBroker(
        initial_balance=100000.0,
        commission_per_lot=3.5
    )
    await broker.connect()
    yield broker
    await broker.disconnect()


@pytest.fixture
def risk_manager():
    """Create risk manager for tests"""
    return RiskManager(RiskConfig(
        max_position_size_pct=0.02,
        max_drawdown_pct=0.10
    ))


@pytest.fixture
def strategy_manager():
    """Create strategy manager for tests"""
    return StrategyManager()


@pytest.fixture
def sample_tick():
    """Create sample price tick"""
    return Tick(
        symbol="EURUSD",
        timestamp=datetime.now().timestamp(),
        bid=1.0850,
        ask=1.0852,
        mid=1.0851,
        volume=1000
    )


@pytest.fixture
def sample_ohlcv():
    """Create sample OHLCV data"""
    return [
        OHLCV(
            timestamp=datetime.now().timestamp() - i * 3600,
            open=1.0800 + i * 0.001,
            high=1.0810 + i * 0.001,
            low=1.0790 + i * 0.001,
            close=1.0805 + i * 0.001,
            volume=1000 + i * 100
        )
        for i in range(100, 0, -1)  # 100 hours of data, oldest first
    ]


@pytest.fixture
def mock_brain_config():
    """Brain configuration for testing"""
    return {
        'max_decision_history': 100,
        'regime_check_interval': 60,
        'circuit_breaker_threshold': 3
    }


class AsyncMock:
    """Helper for creating async mocks"""
    def __init__(self, return_value=None):
        self.return_value = return_value
        self.call_count = 0
        self.calls = []
    
    async def __call__(self, *args, **kwargs):
        self.call_count += 1
        self.calls.append((args, kwargs))
        return self.return_value


# Test data generators
def generate_price_series(start: float, volatility: float, n: int = 100) -> list:
    """Generate synthetic price series"""
    prices = [start]
    for _ in range(n - 1):
        change = np.random.normal(0, volatility)
        prices.append(prices[-1] * (1 + change))
    return prices


def generate_ohlcv_from_close(closes: list) -> list:
    """Generate OHLCV from close prices"""
    ohlcv = []
    for i, close in enumerate(closes):
        high = close * (1 + abs(np.random.normal(0, 0.001)))
        low = close * (1 - abs(np.random.normal(0, 0.001)))
        open_price = closes[i-1] if i > 0 else close

        ohlcv.append(OHLCV(
            timestamp=datetime.now().timestamp() - (len(closes) - i) * 3600,
            open=open_price,
            high=high,
            low=low,
            close=close,
            volume=np.random.randint(1000, 10000)
        ))

    return ohlcv


# ── Additional fixtures required by root-level tests ─────────────────────────

@pytest.fixture
def test_config():
    """Generic test configuration dict."""
    return {
        "initial_balance": 100_000.0,
        "commission_per_lot": 3.5,
        "max_position_size_pct": 0.02,
        "max_drawdown_pct": 0.10,
        "environment": "testing",
    }


@pytest.fixture
def mock_broker():
    """Lightweight synchronous mock broker for unit tests."""
    from unittest.mock import MagicMock, AsyncMock as _AsyncMock
    broker = MagicMock()
    broker.get_account_info = _AsyncMock(return_value={
        "balance": 100_000.0,
        "equity": 100_000.0,
        "margin_used": 0.0,
        "free_margin": 100_000.0,
    })
    broker.place_market_order = _AsyncMock(return_value=MagicMock(
        id="mock_order_1",
        status=MagicMock(value="filled"),
        filled_quantity=10_000,
        average_fill_price=1.0851,
    ))
    broker.get_positions = _AsyncMock(return_value=[])
    broker.close_position = _AsyncMock(return_value=True)
    return broker


@pytest.fixture
def temp_dir():
    """Temporary directory, cleaned up after the test."""
    with tempfile.TemporaryDirectory() as d:
        yield d


@pytest.fixture
def sample_market_data():
    """Multi-asset OHLCV dict for portfolio tests."""
    import pandas as pd
    import numpy as np
    rng = np.random.default_rng(42)
    dates = pd.date_range("2023-01-01", periods=252, freq="B")
    data = {}
    for sym, base in [("XAUUSD", 1900), ("EURUSD", 1.08), ("GBPUSD", 1.25), ("USDJPY", 130)]:
        closes = base * np.cumprod(1 + rng.normal(0.0002, 0.01, 252))
        data[sym] = pd.DataFrame({
            "open":   closes * (1 + rng.uniform(-0.002, 0.002, 252)),
            "high":   closes * (1 + rng.uniform(0, 0.005, 252)),
            "low":    closes * (1 - rng.uniform(0, 0.005, 252)),
            "close":  closes,
            "volume": rng.integers(5000, 50000, 252),
        }, index=dates)
    return data

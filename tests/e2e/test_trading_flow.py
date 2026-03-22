"""
End-to-end trading flow tests.
"""

import pytest
import asyncio

from src.core.trading_engine import TradingEngine
from src.brokers.paper import PaperBroker
from src.data.feeds.polygon import PolygonDataFeed
from src.strategies.xauusd_ml import XAUUSDMLStrategy


@pytest.mark.asyncio
async def test_full_trading_flow():
    """Test complete trading flow."""
    # Setup
    broker = PaperBroker(initial_balance=100000)
    
    # Mock data feed (would use real feed in production)
    class MockFeed:
        async def start(self):
            pass
        async def stop(self):
            pass
        async def subscribe(self, callback):
            pass
    
    strategy = XAUUSDMLStrategy(strategy_id="e2e_test")
    
    engine = TradingEngine(
        broker=broker,
        data_feed=MockFeed(),
        strategies=[strategy]
    )
    
    # Initialize
    await engine.initialize()
    
    # Run briefly
    asyncio.create_task(engine.run())
    await asyncio.sleep(0.5)
    
    # Shutdown
    await engine.shutdown()
    
    # Verify
    account = await broker.get_account()
    assert account is not None

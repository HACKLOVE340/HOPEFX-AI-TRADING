"""
Integration tests for broker connections.
"""

import pytest

from src.brokers.paper import PaperBroker
from src.domain.enums import TradeDirection
from src.domain.models import Order


@pytest.mark.asyncio
async def test_paper_broker_lifecycle():
    """Test paper broker connection and trading."""
    broker = PaperBroker(initial_balance=100000)
    
    # Connect
    connected = await broker.connect()
    assert connected is True
    
    # Get account
    account = await broker.get_account()
    assert account.balance == 100000
    
    # Submit order
    order = Order(
        symbol="XAUUSD",
        direction=TradeDirection.LONG,
        order_type="MARKET",
        quantity=1
    )
    
    filled = await broker.submit_order(order)
    assert filled.status.value == "FILLED"
    
    # Check positions
    positions = await broker.get_positions()
    assert len(positions) == 1
    
    # Disconnect
    await broker.disconnect()

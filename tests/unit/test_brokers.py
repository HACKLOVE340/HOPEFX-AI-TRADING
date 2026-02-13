"""
Unit tests for Broker connectors.
"""

import pytest
from datetime import datetime

from brokers import PaperTradingBroker
from brokers.base import OrderType, OrderSide


@pytest.mark.unit
class TestPaperTradingBroker:
    """Test the Paper Trading Broker."""
    
    def test_broker_initialization(self, paper_broker):
        """Test broker initialization."""
        assert paper_broker.balance == 100000
        assert len(paper_broker.positions) == 0
        assert len(paper_broker.orders) == 0
    
    def test_place_market_order_buy(self, paper_broker):
        """Test placing a market BUY order."""
        order = paper_broker.place_order(
            symbol="EUR_USD",
            order_type=OrderType.MARKET,
            side=OrderSide.BUY,
            quantity=10000,
            price=1.1000
        )
        
        assert order is not None
        assert order['symbol'] == "EUR_USD"
        assert order['side'] == OrderSide.BUY
        assert order['status'] == 'FILLED'
    
    def test_place_market_order_sell(self, paper_broker):
        """Test placing a market SELL order."""
        order = paper_broker.place_order(
            symbol="EUR_USD",
            order_type=OrderType.MARKET,
            side=OrderSide.SELL,
            quantity=10000,
            price=1.1000
        )
        
        assert order is not None
        assert order['side'] == OrderSide.SELL
        assert order['status'] == 'FILLED'
    
    def test_place_limit_order(self, paper_broker):
        """Test placing a limit order."""
        order = paper_broker.place_order(
            symbol="EUR_USD",
            order_type=OrderType.LIMIT,
            side=OrderSide.BUY,
            quantity=10000,
            price=1.0950
        )
        
        assert order is not None
        assert order['type'] == OrderType.LIMIT
        assert order['status'] == 'PENDING'
    
    def test_cancel_order(self, paper_broker):
        """Test canceling an order."""
        # Place a limit order
        order = paper_broker.place_order(
            symbol="EUR_USD",
            order_type=OrderType.LIMIT,
            side=OrderSide.BUY,
            quantity=10000,
            price=1.0950
        )
        
        order_id = order['id']
        
        # Cancel it
        result = paper_broker.cancel_order(order_id)
        
        assert result == True
        canceled_order = paper_broker.get_order(order_id)
        assert canceled_order['status'] == 'CANCELLED'
    
    def test_get_positions(self, paper_broker):
        """Test getting open positions."""
        # Open a position
        paper_broker.place_order(
            symbol="EUR_USD",
            order_type=OrderType.MARKET,
            side=OrderSide.BUY,
            quantity=10000,
            price=1.1000
        )
        
        positions = paper_broker.get_positions()
        
        assert len(positions) > 0
        assert positions[0]['symbol'] == "EUR_USD"
    
    def test_close_position(self, paper_broker):
        """Test closing a position."""
        # Open a position
        order = paper_broker.place_order(
            symbol="EUR_USD",
            order_type=OrderType.MARKET,
            side=OrderSide.BUY,
            quantity=10000,
            price=1.1000
        )
        
        position_id = f"EUR_USD_BUY"
        
        # Close it
        result = paper_broker.close_position(position_id, price=1.1010)
        
        assert result == True
    
    def test_calculate_pnl_profit(self, paper_broker):
        """Test P&L calculation for profitable trade."""
        # Buy at 1.1000
        paper_broker.place_order(
            symbol="EUR_USD",
            order_type=OrderType.MARKET,
            side=OrderSide.BUY,
            quantity=10000,
            price=1.1000
        )
        
        # Current price higher
        pnl = paper_broker._calculate_pnl("EUR_USD", OrderSide.BUY, 10000, 1.1000, 1.1010)
        
        assert pnl > 0  # Should be profitable
    
    def test_calculate_pnl_loss(self, paper_broker):
        """Test P&L calculation for losing trade."""
        # Buy at 1.1000
        paper_broker.place_order(
            symbol="EUR_USD",
            order_type=OrderType.MARKET,
            side=OrderSide.BUY,
            quantity=10000,
            price=1.1000
        )
        
        # Current price lower
        pnl = paper_broker._calculate_pnl("EUR_USD", OrderSide.BUY, 10000, 1.1000, 1.0990)
        
        assert pnl < 0  # Should be a loss
    
    def test_get_account_info(self, paper_broker):
        """Test getting account information."""
        info = paper_broker.get_account_info()
        
        assert 'balance' in info
        assert 'equity' in info
        assert 'margin_used' in info
        assert 'margin_available' in info
        assert info['balance'] == 100000
    
    def test_insufficient_balance(self, paper_broker):
        """Test placing order with insufficient balance."""
        # Try to place huge order
        with pytest.raises(Exception):
            paper_broker.place_order(
                symbol="EUR_USD",
                order_type=OrderType.MARKET,
                side=OrderSide.BUY,
                quantity=1000000,  # Way too large
                price=1.1000
            )
    
    def test_get_market_price(self, paper_broker):
        """Test getting current market price."""
        price = paper_broker.get_market_price("EUR_USD")
        
        assert price > 0
        assert isinstance(price, (int, float))

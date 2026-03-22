#!/usr/bin/env python3
"""
Tests for execution module.
"""

import pytest
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from execution import PaperExecutor, SmartOrderRouter, Order, OrderStatus


class TestPaperExecutor:
    """Test cases for PaperExecutor."""
    
    def setup_method(self):
        self.executor = PaperExecutor(initial_balance=10000.0)
    
    def test_initial_state(self):
        """Test initial executor state."""
        assert self.executor.balance == 10000.0
        assert self.executor.equity == 10000.0
        assert len(self.executor.positions) == 0
    
    def test_buy_order(self):
        """Test basic buy order execution."""
        order = Order(symbol='XAUUSD', side='buy', qty=0.01)
        result = self.executor.submit_order(order, current_price=2000.0, skip_validation=True)
        
        assert result.status == OrderStatus.FILLED
        assert result.filled_qty == 0.01
        assert result.avg_price > 0
        assert result.commission > 0
        assert self.executor.balance < 10000.0  # Balance reduced
    
    def test_sell_without_position(self):
        """Test sell order without position should fail."""
        order = Order(symbol='XAUUSD', side='sell', qty=0.01)
        result = self.executor.submit_order(order, current_price=2000.0, skip_validation=True)
        
        assert result.status == OrderStatus.REJECTED
        assert 'position' in result.message.lower()
    
    def test_buy_and_sell(self):
        """Test complete buy then sell cycle."""
        # Buy
        buy_order = Order(symbol='XAUUSD', side='buy', qty=0.01)
        buy_result = self.executor.submit_order(buy_order, current_price=2000.0, skip_validation=True)
        assert buy_result.status == OrderStatus.FILLED
        
        # Sell at higher price
        sell_order = Order(symbol='XAUUSD', side='sell', qty=0.01)
        sell_result = self.executor.submit_order(sell_order, current_price=2010.0, skip_validation=True)
        assert sell_result.status == OrderStatus.FILLED
        
        # Position should be closed
        assert 'XAUUSD' not in self.executor.positions
    
    def test_slippage_calculation(self):
        """Test slippage is applied correctly."""
        slippage = self.executor._calculate_slippage('XAUUSD', 'buy', 0.01, 2000.0, 0.0)
        assert slippage >= 0
        assert slippage <= 0.5  # Max slippage cap
        
        # Larger orders should have more slippage
        small_slip = self.executor._calculate_slippage('XAUUSD', 'buy', 0.01, 2000.0, 0.0)
        large_slip = self.executor._calculate_slippage('XAUUSD', 'buy', 1.0, 2000.0, 0.0)
        assert large_slip >= small_slip
    
    def test_commission_calculation(self):
        """Test commission calculation."""
        comm = self.executor._calculate_commission(0.01, 'XAUUSD')
        assert comm > 0
        assert comm == 3.5 * 0.01  # $3.50 per lot
    
    def test_insufficient_balance(self):
        """Test rejection of orders exceeding balance."""
        order = Order(symbol='XAUUSD', side='buy', qty=10.0)  # Way too big
        result = self.executor.submit_order(order, current_price=2000.0, skip_validation=True)
        
        assert result.status == OrderStatus.REJECTED
        assert 'balance' in result.message.lower()
    
    def test_position_tracking(self):
        """Test position tracking."""
        order = Order(symbol='XAUUSD', side='buy', qty=0.01)
        self.executor.submit_order(order, current_price=2000.0, skip_validation=True)
        
        pos = self.executor.get_position('XAUUSD')
        assert pos is not None
        assert pos['side'] == 'long'
        assert pos['qty'] == 0.01
        assert pos['entry_price'] > 0
    
    def test_unrealized_pnl(self):
        """Test unrealized P&L calculation."""
        order = Order(symbol='XAUUSD', side='buy', qty=0.01)
        self.executor.submit_order(order, current_price=2000.0, skip_validation=True)
        
        # Price up = positive P&L
        pnl_up = self.executor.get_unrealized_pnl('XAUUSD', 2010.0)
        assert pnl_up > 0
        
        # Price down = negative P&L
        pnl_down = self.executor.get_unrealized_pnl('XAUUSD', 1990.0)
        assert pnl_down < 0
    
    def test_close_all_positions(self):
        """Test closing all positions."""
        # Open position
        order = Order(symbol='XAUUSD', side='buy', qty=0.01)
        self.executor.submit_order(order, current_price=2000.0, skip_validation=True)
        
        assert len(self.executor.positions) == 1
        
        # Close all
        results = self.executor.close_all_positions({'XAUUSD': 2010.0})
        assert len(results) == 1
        assert len(self.executor.positions) == 0
    
    def test_order_history(self):
        """Test order history tracking."""
        order = Order(symbol='XAUUSD', side='buy', qty=0.01)
        self.executor.submit_order(order, current_price=2000.0, skip_validation=True)
        
        assert len(self.executor.order_history) == 1
        assert self.executor.order_history[0]['order'] == order
    
    def test_limit_order_pending(self):
        """Test limit order that doesn't fill immediately."""
        order = Order(symbol='XAUUSD', side='buy', qty=0.01, order_type='limit', price=1900.0)
        result = self.executor.submit_order(order, current_price=2000.0, skip_validation=True)
        
        # Price is above limit, should be pending
        assert result.status == OrderStatus.PENDING


class TestSmartOrderRouter:
    """Test cases for SmartOrderRouter."""
    
    def setup_method(self):
        self.router = SmartOrderRouter()
        self.mock_broker = PaperExecutor()
    
    def test_register_broker(self):
        """Test broker registration."""
        self.router.register_broker('paper', self.mock_broker, is_default=True)
        assert 'paper' in self.router.brokers
        assert self.router.default_broker == 'paper'
    
    def test_route_without_brokers(self):
        """Test routing with no brokers raises error."""
        with pytest.raises(RuntimeError):
            order = Order(symbol='XAUUSD', side='buy', qty=0.01)
            self.router.route_order(order, current_price=2000.0)


if __name__ == '__main__':
    pytest.main([__file__, '-v'])

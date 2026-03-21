#!/usr/bin/env python3
"""
Tests for validation module.
"""

import pytest
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from validation import OrderValidator, Order, PropFirmValidator, validate_order_safe


class TestOrderValidator:
    """Test cases for OrderValidator."""
    
    def setup_method(self):
        self.validator = OrderValidator()
    
    def test_valid_order(self):
        """Test that valid orders pass."""
        order = Order(symbol='XAUUSD', side='buy', qty=0.01, stop_loss=1950.0)
        result = self.validator.validate_order(
            order, current_price=2000.0, account_balance=10000.0
        )
        assert result.valid is True
        assert result.risk_pct is not None
    
    def test_invalid_symbol(self):
        """Test rejection of invalid symbol."""
        order = Order(symbol='INVALID', side='buy', qty=0.01)
        result = self.validator.validate_order(
            order, current_price=100.0, account_balance=10000.0
        )
        assert result.valid is False
        assert 'symbol' in result.reason.lower()
    
    def test_oversized_position(self):
        """Test rejection of oversized positions."""
        order = Order(symbol='XAUUSD', side='buy', qty=1.0)  # Too big for 10k account
        result = self.validator.validate_order(
            order, current_price=2000.0, account_balance=10000.0
        )
        assert result.valid is False
        assert 'risk' in result.reason.lower()
    
    def test_invalid_stop_loss_long(self):
        """Test stop loss validation for long positions."""
        # Stop above entry for long should fail
        order = Order(symbol='XAUUSD', side='buy', qty=0.01, stop_loss=2100.0)
        result = self.validator.validate_order(
            order, current_price=2000.0, account_balance=10000.0
        )
        assert result.valid is False
        assert 'stop loss' in result.reason.lower()
    
    def test_tight_stop_loss(self):
        """Test rejection of too-tight stop loss."""
        order = Order(symbol='XAUUSD', side='buy', qty=0.01, stop_loss=1999.0)
        result = self.validator.validate_order(
            order, current_price=2000.0, account_balance=10000.0
        )
        assert result.valid is False
        assert 'tight' in result.reason.lower()
    
    def test_quantity_bounds(self):
        """Test min/max quantity validation."""
        # Too small
        order = Order(symbol='XAUUSD', side='buy', qty=0.001)
        result = self.validator.validate_order(
            order, current_price=2000.0, account_balance=10000.0
        )
        assert result.valid is False
        
        # Too large
        order = Order(symbol='XAUUSD', side='buy', qty=20.0)
        result = self.validator.validate_order(
            order, current_price=2000.0, account_balance=10000.0
        )
        assert result.valid is False
    
    def test_suspicious_price(self):
        """Test rejection of suspicious XAUUSD prices."""
        order = Order(symbol='XAUUSD', side='buy', qty=0.01)
        result = self.validator.validate_order(
            order, current_price=50000.0, account_balance=10000.0  # Impossible XAUUSD price
        )
        assert result.valid is False
        assert 'suspicious' in result.reason.lower()
    
    def test_daily_risk_tracking(self):
        """Test daily risk counter."""
        order = Order(symbol='XAUUSD', side='buy', qty=0.01)
        result = self.validator.validate_order(
            order, current_price=2000.0, account_balance=10000.0
        )
        assert result.valid is True
        
        initial_risk = self.validator.daily_risk_used
        self.validator.record_trade(result.risk_pct)
        assert self.validator.daily_risk_used > initial_risk


class TestPropFirmValidator:
    """Test cases for PropFirmValidator."""
    
    def setup_method(self):
        self.validator = PropFirmValidator(firm='ftmo')
    
    def test_within_limits(self):
        """Test validation within limits."""
        valid, msg = self.validator.check_limits(current_equity=100000.0)
        assert valid is True
    
    def test_drawdown_violation(self):
        """Test drawdown limit detection."""
        self.validator.peak_equity = 100000.0
        valid, msg = self.validator.check_limits(
            current_equity=89000.0,  # 11% drawdown
            open_pnl=0
        )
        assert valid is False
        assert 'drawdown' in msg.lower()
    
    def test_daily_loss_tracking(self):
        """Test daily loss accumulation."""
        self.validator.record_pnl(-2000)  # $2k loss
        valid, msg = self.validator.check_limits(current_equity=100000.0)
        assert valid is True  # 2% is within 5% daily limit
        
        # Add more losses
        self.validator.record_pnl(-4000)
        valid, msg = self.validator.check_limits(current_equity=94000.0)
        assert valid is False  # Now 6% loss
    
    def test_reset_daily(self):
        """Test daily reset functionality."""
        self.validator.record_pnl(-2000)
        assert self.validator.daily_loss < 0
        
        self.validator.reset_daily()
        assert self.validator.daily_loss == 0.0


class TestConvenienceFunction:
    """Test convenience validation function."""
    
    def test_validate_order_safe_valid(self):
        """Test safe validation with valid order."""
        result = validate_order_safe(
            symbol='XAUUSD',
            side='buy',
            qty=0.01,
            current_price=2000.0,
            account_balance=10000.0,
            stop_loss=1950.0
        )
        assert result is True
    
    def test_validate_order_safe_invalid(self):
        """Test safe validation with invalid order."""
        result = validate_order_safe(
            symbol='INVALID',
            side='buy',
            qty=0.01,
            current_price=2000.0,
            account_balance=10000.0
        )
        assert result is False


if __name__ == '__main__':
    pytest.main([__file__, '-v'])

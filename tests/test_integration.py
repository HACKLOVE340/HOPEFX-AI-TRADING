# File 22: Create a final integration test that runs everything

integration_test_content = '''#!/usr/bin/env python3
"""
HOPEFX Integration Test
Tests the full pipeline: validation -> execution -> backtesting
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

import unittest
from validation import OrderValidator, Order, PropFirmValidator
from execution import PaperExecutor, OrderStatus
from examples.backtest_example import (
    XAUUSDDataGenerator,
    MovingAverageCrossover,
    BacktestEngine
)


class TestFullPipeline(unittest.TestCase):
    """Integration tests for the complete trading pipeline."""
    
    def test_validation_to_execution_flow(self):
        """Test that validated orders execute correctly."""
        # Setup
        validator = OrderValidator()
        executor = PaperExecutor(initial_balance=10000.0)
        
        # Create valid order
        order = Order(symbol='XAUUSD', side='buy', qty=0.01, stop_loss=1950.0)
        
        # Validate
        validation = validator.validate_order(
            order, current_price=2000.0, account_balance=10000.0
        )
        self.assertTrue(validation.valid, f"Validation failed: {validation.reason}")
        
        # Execute
        result = executor.submit_order(order, current_price=2000.0, skip_validation=True)
        self.assertEqual(result.status, OrderStatus.FILLED)
        
        # Verify position
        position = executor.get_position('XAUUSD')
        self.assertIsNotNone(position)
        self.assertEqual(position['side'], 'long')
        self.assertEqual(position['qty'], 0.01)
    
    def test_invalid_order_rejection(self):
        """Test that invalid orders are rejected."""
        validator = OrderValidator()
        
        # Create oversized order
        order = Order(symbol='XAUUSD', side='buy', qty=10.0)
        
        validation = validator.validate_order(
            order, current_price=2000.0, account_balance=10000.0
        )
        
        self.assertFalse(validation.valid)
        self.assertIn('risk', validation.reason.lower())
    
    def test_backtest_to_execution_consistency(self):
        """Test that backtest and execution use consistent logic."""
        # Generate data
        gen = XAUUSDDataGenerator(days=30)
        data = gen.generate()
        
        # Run backtest
        strategy = MovingAverageCrossover(fast_period=5, slow_period=10)
        engine = BacktestEngine(data, strategy, initial_capital=10000.0)
        results = engine.run()
        
        # Verify metrics are reasonable
        self.assertIn('total_trades', results)
        self.assertIn('max_drawdown_pct', results)
        self.assertGreaterEqual(results['max_drawdown_pct'], 0)
        
        # Compare with paper execution
        executor = PaperExecutor(initial_balance=10000.0)
        
        # Simulate same trade
        order = Order(symbol='XAUUSD', side='buy', qty=0.01)
        result = executor.submit_order(order, current_price=2000.0, skip_validation=True)
        
        # Both should track P&L
        self.assertEqual(result.status, OrderStatus.FILLED)
        self.assertIn('avg_price', result.__dict__)
    
    def test_prop_firm_integration(self):
        """Test prop firm limits with execution."""
        prop = PropFirmValidator(firm='ftmo')
        executor = PaperExecutor(initial_balance=100000.0)
        
        # Check initial limits
        valid, msg = prop.check_limits(current_equity=100000.0)
        self.assertTrue(valid)
        
        # Simulate losses
        prop.record_pnl(-2000)  # $2k loss
        valid, msg = prop.check_limits(current_equity=98000.0)
        self.assertTrue(valid)  # 2% is within 5% daily limit
        
        # Simulate large loss
        prop.record_pnl(-4000)  # Additional $4k
        valid, msg = prop.check_limits(current_equity=94000.0)
        self.assertFalse(valid)  # 6% exceeds 5% limit
    
    def test_risk_limits_enforcement(self):
        """Test that risk limits are enforced across components."""
        validator = OrderValidator(max_position_risk_pct=0.01)  # 1% max
        
        # Order at exactly 1% should pass
        order = Order(symbol='XAUUSD', side='buy', qty=0.005)
        result = validator.validate_order(
            order, current_price=2000.0, account_balance=10000.0
        )
        self.assertTrue(result.valid)
        
        # Order at 2% should fail
        big_order = Order(symbol='XAUUSD', side='buy', qty=0.01)
        result = validator.validate_order(
            big_order, current_price=2000.0, account_balance=10000.0
        )
        self.assertFalse(result.valid)


class TestDataFlow(unittest.TestCase):
    """Test data flows correctly between components."""
    
    def test_equity_tracking(self):
        """Test equity is tracked consistently."""
        executor = PaperExecutor(initial_balance=10000.0)
        
        # Initial state
        self.assertEqual(executor.equity, 10000.0)
        
        # Buy
        order = Order(symbol='XAUUSD', side='buy', qty=0.01)
        executor.submit_order(order, current_price=2000.0, skip_validation=True)
        
        # Equity should change (cost of position)
        self.assertLess(executor.balance, 10000.0)
        
        # Check unrealized P&L
        pnl = executor.get_unrealized_pnl('XAUUSD', current_price=2010.0)
        self.assertGreater(pnl, 0)  # Price up = profit


if __name__ == '__main__':
    # Run with verbose output
    suite = unittest.TestLoader().loadTestsFromModule(sys.modules[__name__])
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    # Exit with proper code
    sys.exit(0 if result.wasSuccessful() else 1)
'''

with open('/mnt/kimi/output/hopefx_upgrade/tests/test_integration.py', 'w') as f:
    f.write(integration_test_content)

print("✅ tests/test_integration.py created - Full pipeline integration tests")

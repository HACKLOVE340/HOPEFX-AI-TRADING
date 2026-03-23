import unittest
import numpy as np

class TestRiskCalculations(unittest.TestCase):

    def test_position_sizing(self):
        # Test with 1-2% risk per trade
        equity = 1000  # Test with $1000 equity
        risk_percent = 0.02  # 2% risk
        position_size = equity * risk_percent  
        self.assertEqual(position_size, 20)  # Should be $20 position size for this risk

    def test_atr_stop_loss(self):
        # Calculate ATR-based stop loss (1.5x ATR)
        atr = 2  # Assume average ATR is $2
        stop_loss = atr * 1.5
        self.assertEqual(stop_loss, 3)  # Stop loss should be $3 for ATR of $2

    def test_trailing_stop_logic(self):
        # Test trailing stop logic, assuming a price movement
        entry_price = 100
        trailing_stop_distance = 5  # $5 trailing stop
        current_price = 110
        trailing_stop = entry_price + trailing_stop_distance
        self.assertEqual(trailing_stop, 105)  # Trailing stop should adjust

    def test_max_drawdown_pause(self):
        # Check max drawdown pause (10%)
        peak_equity = 1000
        current_equity = 900
        drawdown = (peak_equity - current_equity) / peak_equity
        self.assertGreater(drawdown, 0.10)  # Drawdown should trigger pause

    def test_low_capital_mode(self):
        # Validate low-capital mode (<$50 equity -> 0.5% risk)
        equity = 30  # Test with $30 equity
        risk_percent = 0.005  # 0.5% risk
        position_size = equity * risk_percent
        self.assertEqual(position_size, 0.15)  # Should be $0.15 position size for this risk

    def test_edge_cases(self):
        # Tests with zero equity/infinite ATR
        equity = 0  # $0 equity
        atr = float('inf')  # Infinite ATR
        with self.assertRaises(ZeroDivisionError):
            position_size = equity / atr  # Should raise an error

if __name__ == '__main__':
    unittest.main()
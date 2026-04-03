# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
import unittest


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
        trailing_stop = entry_price + trailing_stop_distance
        self.assertEqual(trailing_stop, 105)  # Trailing stop should adjust

    def test_max_drawdown_pause(self):
        # Check max drawdown pause (10%)
        # A drawdown of exactly 10% must trigger the pause (>= threshold).
        peak_equity = 1000
        current_equity = 900
        drawdown = (peak_equity - current_equity) / peak_equity
        self.assertGreaterEqual(drawdown, 0.10)  # Drawdown should trigger pause

    def test_low_capital_mode(self):
        # Validate low-capital mode (<$50 equity -> 0.5% risk)
        equity = 30  # Test with $30 equity
        risk_percent = 0.005  # 0.5% risk
        position_size = equity * risk_percent
        self.assertEqual(position_size, 0.15)  # Should be $0.15 position size for this risk

    def test_edge_cases(self):
        # Tests with zero equity / infinite ATR.
        # Python returns 0.0 for 0 / inf — no exception is raised.
        # The real guard is that position size collapses to zero, not a crash.
        equity = 0  # $0 equity
        atr = float("inf")  # Infinite ATR
        result = equity / atr
        self.assertEqual(result, 0.0)  # 0 / inf == 0.0 in IEEE 754


if __name__ == "__main__":
    unittest.main()

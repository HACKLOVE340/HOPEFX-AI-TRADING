# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
import unittest

import pytest

try:
    from auth_module import Auth
    from backtesting_module import Backtester
    from market_data_module import MarketData
    from portfolio_management_module import PortfolioManagement
    from trading_module import TradingExecution

    HAS_LEGACY_MODULES = True
except ImportError:
    HAS_LEGACY_MODULES = False

pytestmark = pytest.mark.skipif(
    not HAS_LEGACY_MODULES,
    reason="legacy module dependencies not available",
)


class TestAuthentication(unittest.TestCase):
    def setUp(self):
        self.auth = Auth()

    def test_login_valid(self):
        result = self.auth.login("valid_user", "valid_password")
        self.assertTrue(result)

    def test_login_invalid(self):
        result = self.auth.login("invalid_user", "invalid_password")
        self.assertFalse(result)


class TestMarketData(unittest.TestCase):
    def setUp(self):
        self.market_data = MarketData()

    def test_get_data(self):
        data = self.market_data.get_data("AAPL")
        self.assertIsNotNone(data)

    def test_data_format(self):
        data = self.market_data.get_data("AAPL")
        self.assertIsInstance(data, dict)


class TestTradingExecution(unittest.TestCase):
    def setUp(self):
        self.trading = TradingExecution()

    def test_execute_trade(self):
        result = self.trading.execute_trade("AAPL", 10)
        self.assertTrue(result)


class TestPortfolioManagement(unittest.TestCase):
    def setUp(self):
        self.portfolio = PortfolioManagement()

    def test_add_stock(self):
        self.portfolio.add_stock("AAPL", 10)
        self.assertIn("AAPL", self.portfolio.stocks)


class TestBacktesting(unittest.TestCase):
    def setUp(self):
        self.backtester = Backtester()

    def test_run_backtest(self):
        result = self.backtester.run_backtest("AAPL", "2021-01-01", "2021-12-31")
        self.assertIsInstance(result, dict)


if __name__ == "__main__":
    unittest.main()

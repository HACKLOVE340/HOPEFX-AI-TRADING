# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
Comprehensive production-module tests.

Replaces the legacy placeholder tests (auth_module / backtesting_module /
market_data_module / portfolio_management_module / trading_module) with
real tests against the production codebase.
"""

import unittest
from datetime import timezone


UTC = timezone.utc

# ---------------------------------------------------------------------------
# Auth — auth/jwt.py
# ---------------------------------------------------------------------------


class TestAuthentication(unittest.TestCase):
    """Test the production JWT auth helpers."""

    def test_password_hash_and_verify_valid(self):
        """hash_password + verify_password round-trip for a correct password."""
        from auth.jwt import hash_password, verify_password

        hashed = hash_password("SecurePass123!")
        assert verify_password("SecurePass123!", hashed) is True

    def test_password_verify_invalid(self):
        """verify_password rejects a wrong password."""
        from auth.jwt import hash_password, verify_password

        hashed = hash_password("RealPass")
        assert verify_password("WrongPass", hashed) is False


# ---------------------------------------------------------------------------
# Market data — cache/market_data_cache.py
# ---------------------------------------------------------------------------


class TestMarketData(unittest.TestCase):
    """Test the production MarketDataCache (in-memory fallback path)."""

    def setUp(self):
        from cache.market_data_cache import MarketDataCache

        # Fresh instance with an isolated in-memory store so prior tests that
        # seed the cache (e.g. integration/test_redis.py) cannot pollute this
        # assertion.  Use a unique symbol that no other test writes to.
        self.cache = MarketDataCache(host="localhost", port=6379, db=0)
        # Wipe any in-memory state left by earlier tests in the same process.
        self.cache._local_cache.clear()
        self.cache._local_ttl.clear()

    def test_get_returns_none_for_missing_key(self):
        # Use a symbol that no other test writes to guarantee a clean miss.
        result = self.cache.get_ohlcv("__TEST_MISSING_SYMBOL__", "1h", limit=1)
        # Returns None or empty list when no data has been cached.
        assert result is None or result == []

    def test_cache_write_then_read_roundtrip(self):
        """Data written to the in-memory cache is retrievable."""
        candle = {"open": 1.0, "high": 1.1, "low": 0.9, "close": 1.05, "volume": 100}
        self.cache.cache_ohlcv("__TEST_ROUNDTRIP__", "1h", [candle])
        result = self.cache.get_ohlcv("__TEST_ROUNDTRIP__", "1h", limit=1)
        assert result is not None and len(result) == 1

    def test_stats_hit_count_increments_on_read(self):
        """Cache hit counter increments after a successful read."""
        candle = {"open": 1.0, "high": 1.1, "low": 0.9, "close": 1.05, "volume": 100}
        self.cache.cache_ohlcv("__TEST_STATS__", "1h", [candle])
        before = self.cache.get_stats().get("total_hits", 0)
        self.cache.get_ohlcv("__TEST_STATS__", "1h", limit=1)
        after = self.cache.get_stats().get("total_hits", 0)
        assert after > before

    def test_data_format_via_stats(self):
        stats = self.cache.get_stats()
        assert isinstance(stats, dict)


# ---------------------------------------------------------------------------
# Trading — paper-trading broker
# ---------------------------------------------------------------------------


class TestTradingExecution(unittest.TestCase):
    """Test the paper-trading execution path (no live broker required)."""

    def test_paper_broker_place_order_returns_order(self):
        """PaperTradingBroker.place_order() returns an Order with an id."""
        import asyncio

        from brokers.base import OrderSide, OrderType
        from brokers.paper_trading import PaperTradingBroker

        broker = PaperTradingBroker({"symbol": "XAUUSD", "initial_balance": 10_000.0})
        asyncio.run(broker.connect())
        order = broker.place_order(
            symbol="XAUUSD",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=0.1,
        )
        assert order is not None
        assert order.id is not None

    def test_paper_broker_get_account_returns_balance(self):
        """PaperTradingBroker.get_account_info() returns an AccountInfo dict."""
        from brokers.paper_trading import PaperTradingBroker

        broker = PaperTradingBroker({"initial_balance": 50_000.0})
        info = broker.get_account_info()
        assert info is not None


# ---------------------------------------------------------------------------
# Portfolio — risk module
# ---------------------------------------------------------------------------


class TestPortfolioManagement(unittest.TestCase):
    """Test the production portfolio/position manager."""

    def test_position_manager_initial_state_empty(self):
        """A fresh PositionManager has no open positions."""
        from execution.position_manager import PositionManager

        pm = PositionManager()
        positions = pm.get_all_positions()
        assert len(positions) == 0

    def test_position_manager_get_all_positions_returns_dict(self):
        """get_all_positions() returns a dict."""
        from execution.position_manager import PositionManager

        pm = PositionManager()
        positions = pm.get_all_positions()
        assert isinstance(positions, dict)


# ---------------------------------------------------------------------------
# Backtesting — backtesting/enhanced_engine.py
# ---------------------------------------------------------------------------


class TestBacktesting(unittest.TestCase):
    """Test the production EnhancedBacktestEngine with minimal synthetic bars."""

    def _make_engine(self):
        import warnings

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            from backtesting.enhanced_engine import EnhancedBacktestEngine

        return EnhancedBacktestEngine()

    def test_engine_instantiation(self):
        """EnhancedBacktestEngine can be created without raising."""
        engine = self._make_engine()
        assert engine is not None

    def test_get_performance_report_returns_dict(self):
        """get_performance_report() on an uninitialised engine returns a dict."""
        engine = self._make_engine()
        report = engine.get_performance_report()
        assert isinstance(report, dict)


if __name__ == "__main__":
    unittest.main()

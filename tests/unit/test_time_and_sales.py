"""
Tests for Time & Sales Service (data/time_and_sales.py)
"""

import pytest
from datetime import datetime, timedelta


class TestExecutedTrade:
    """Tests for ExecutedTrade dataclass."""

    def test_trade_creation(self):
        from data.time_and_sales import ExecutedTrade

        trade = ExecutedTrade(
            timestamp=datetime.utcnow(),
            symbol="XAUUSD",
            price=1950.0,
            size=100.0,
            side="buy",
            is_aggressive_buy=True,
        )

        assert trade.symbol == "XAUUSD"
        assert trade.price == 1950.0
        assert trade.size == 100.0
        assert trade.side == "buy"
        assert trade.is_aggressive_buy is True

    def test_trade_to_dict(self):
        from data.time_and_sales import ExecutedTrade

        trade = ExecutedTrade(
            timestamp=datetime.utcnow(),
            symbol="XAUUSD",
            price=1950.0,
            size=100.0,
            side="buy",
        )

        d = trade.to_dict()
        assert d["symbol"] == "XAUUSD"
        assert d["price"] == 1950.0
        assert "timestamp" in d
        assert "is_large_trade" in d


class TestTradeVelocity:
    """Tests for TradeVelocity dataclass."""

    def test_velocity_to_dict(self):
        from data.time_and_sales import TradeVelocity

        v = TradeVelocity(
            symbol="XAUUSD",
            trades_per_minute=10.0,
            volume_per_minute=500.0,
            avg_trade_size=50.0,
            buy_trades_pct=60.0,
            sell_trades_pct=40.0,
        )

        d = v.to_dict()
        assert d["symbol"] == "XAUUSD"
        assert d["trades_per_minute"] == 10.0
        assert d["buy_trades_pct"] == 60.0


class TestTimeAndSalesService:
    """Tests for TimeAndSalesService."""

    def test_initialization(self):
        from data.time_and_sales import TimeAndSalesService

        service = TimeAndSalesService()
        assert service is not None

    def test_add_trade(self):
        from data.time_and_sales import TimeAndSalesService

        service = TimeAndSalesService()
        trade = service.add_trade("XAUUSD", price=1950.0, size=100.0, side="buy")

        assert trade is not None
        assert trade.symbol == "XAUUSD"
        assert trade.price == 1950.0
        assert service.get_trade_count("XAUUSD") == 1

    def test_add_trade_buy_aggression(self):
        from data.time_and_sales import TimeAndSalesService

        service = TimeAndSalesService()
        trade = service.add_trade(
            "XAUUSD", price=1950.05, size=100.0, side="buy", ask_price=1950.05
        )

        assert trade.is_aggressive_buy is True
        assert trade.is_aggressive_sell is False

    def test_add_trade_sell_aggression(self):
        from data.time_and_sales import TimeAndSalesService

        service = TimeAndSalesService()
        trade = service.add_trade(
            "XAUUSD", price=1950.00, size=100.0, side="sell", bid_price=1950.00
        )

        assert trade.is_aggressive_sell is True
        assert trade.is_aggressive_buy is False

    def test_large_trade_flag(self):
        from data.time_and_sales import TimeAndSalesService

        service = TimeAndSalesService(config={"large_trade_threshold": 200})
        small = service.add_trade("XAUUSD", 1950.0, 50.0, "buy")
        large = service.add_trade("XAUUSD", 1950.0, 250.0, "buy")

        assert small.is_large_trade is False
        assert large.is_large_trade is True

    def test_large_trade_callback(self):
        from data.time_and_sales import TimeAndSalesService

        service = TimeAndSalesService(config={"large_trade_threshold": 100})
        alerts = []
        service.register_large_trade_callback(alerts.append)

        service.add_trade("XAUUSD", 1950.0, 200.0, "buy")
        service.add_trade("XAUUSD", 1950.0, 50.0, "sell")

        assert len(alerts) == 1
        assert alerts[0].size == 200.0

    def test_circular_buffer_limit(self):
        from data.time_and_sales import TimeAndSalesService

        service = TimeAndSalesService(config={"max_trades": 5})
        for i in range(10):
            service.add_trade("XAUUSD", 1950.0, float(i + 1), "buy")

        assert service.get_trade_count("XAUUSD") == 5

    def test_get_recent_trades(self):
        from data.time_and_sales import TimeAndSalesService

        service = TimeAndSalesService()
        for i in range(20):
            service.add_trade("XAUUSD", 1950.0, 10.0, "buy")

        recent = service.get_recent_trades("XAUUSD", n=5)
        assert len(recent) == 5

    def test_get_recent_trades_empty(self):
        from data.time_and_sales import TimeAndSalesService

        service = TimeAndSalesService()
        assert service.get_recent_trades("NONEXISTENT") == []

    def test_get_trades_by_time(self):
        from data.time_and_sales import TimeAndSalesService

        service = TimeAndSalesService()
        base = datetime.utcnow() - timedelta(minutes=30)

        # Old trade
        service.add_trade("XAUUSD", 1950.0, 100.0, "buy", timestamp=base - timedelta(hours=2))
        # Recent trade
        service.add_trade("XAUUSD", 1951.0, 50.0, "sell", timestamp=base)

        trades = service.get_trades_by_time(
            "XAUUSD",
            start_time=base - timedelta(minutes=1),
        )
        assert len(trades) == 1
        assert trades[0].price == 1951.0

    def test_get_large_trades(self):
        from data.time_and_sales import TimeAndSalesService

        service = TimeAndSalesService(config={"large_trade_threshold": 100})
        now = datetime.utcnow()
        service.add_trade("XAUUSD", 1950.0, 500.0, "buy", timestamp=now - timedelta(minutes=5))
        service.add_trade("XAUUSD", 1950.0, 10.0, "sell", timestamp=now)

        large = service.get_large_trades("XAUUSD")
        assert len(large) == 1
        assert large[0].size == 500.0

    def test_get_trade_velocity_no_data(self):
        from data.time_and_sales import TimeAndSalesService

        service = TimeAndSalesService()
        assert service.get_trade_velocity("NONEXISTENT") is None

    def test_get_trade_velocity(self):
        from data.time_and_sales import TimeAndSalesService

        service = TimeAndSalesService(config={"velocity_window_minutes": 5})
        now = datetime.utcnow()
        for i in range(10):
            service.add_trade("XAUUSD", 1950.0, 50.0, "buy" if i % 2 == 0 else "sell",
                              timestamp=now - timedelta(seconds=i * 20))

        velocity = service.get_trade_velocity("XAUUSD")
        assert velocity is not None
        assert velocity.trades_per_minute > 0
        assert velocity.buy_trades_pct + velocity.sell_trades_pct == pytest.approx(100.0, rel=0.01)

    def test_get_aggressor_stats(self):
        from data.time_and_sales import TimeAndSalesService

        service = TimeAndSalesService()
        now = datetime.utcnow()
        for _ in range(7):
            service.add_trade("XAUUSD", 1950.0, 100.0, "buy",
                              timestamp=now - timedelta(minutes=5))
        for _ in range(3):
            service.add_trade("XAUUSD", 1950.0, 100.0, "sell",
                              timestamp=now - timedelta(minutes=5))

        stats = service.get_aggressor_stats("XAUUSD")
        assert stats is not None
        assert stats.buy_trades == 7
        assert stats.sell_trades == 3
        assert stats.buy_pct == pytest.approx(70.0)
        assert stats.net_aggression > 0

    def test_get_aggressor_stats_no_data(self):
        from data.time_and_sales import TimeAndSalesService

        service = TimeAndSalesService()
        assert service.get_aggressor_stats("NONEXISTENT") is None

    def test_get_trade_histogram(self):
        from data.time_and_sales import TimeAndSalesService

        service = TimeAndSalesService()
        now = datetime.utcnow()
        for i in range(20):
            service.add_trade("XAUUSD", 1950.0 + i * 0.5, 100.0, "buy",
                              timestamp=now - timedelta(minutes=5))

        hist = service.get_trade_histogram("XAUUSD", bins=5)
        assert len(hist) > 0
        assert all("price_low" in b for b in hist)
        assert all("total_volume" in b for b in hist)

    def test_get_trade_histogram_empty(self):
        from data.time_and_sales import TimeAndSalesService

        service = TimeAndSalesService()
        assert service.get_trade_histogram("NONEXISTENT") == []

    def test_get_trade_statistics(self):
        from data.time_and_sales import TimeAndSalesService

        service = TimeAndSalesService()
        now = datetime.utcnow()
        for i in range(10):
            service.add_trade("XAUUSD", 1950.0 + i, float(10 + i), "buy",
                              timestamp=now - timedelta(minutes=5))

        stats = service.get_trade_statistics("XAUUSD")
        assert stats["trade_count"] == 10
        assert "total_volume" in stats
        assert stats["price_high"] > stats["price_low"]

    def test_get_symbols(self):
        from data.time_and_sales import TimeAndSalesService

        service = TimeAndSalesService()
        service.add_trade("XAUUSD", 1950.0, 100.0, "buy")
        service.add_trade("EURUSD", 1.08, 1000.0, "sell")

        symbols = service.get_symbols()
        assert "XAUUSD" in symbols
        assert "EURUSD" in symbols

    def test_clear_symbol(self):
        from data.time_and_sales import TimeAndSalesService

        service = TimeAndSalesService()
        service.add_trade("XAUUSD", 1950.0, 100.0, "buy")
        service.clear_symbol("XAUUSD")

        assert service.get_trade_count("XAUUSD") == 0

    def test_clear_all(self):
        from data.time_and_sales import TimeAndSalesService

        service = TimeAndSalesService()
        service.add_trade("XAUUSD", 1950.0, 100.0, "buy")
        service.add_trade("EURUSD", 1.08, 100.0, "sell")
        service.clear_all()

        assert len(service.get_symbols()) == 0

    def test_get_stats(self):
        from data.time_and_sales import TimeAndSalesService

        service = TimeAndSalesService()
        service.add_trade("XAUUSD", 1950.0, 100.0, "buy")

        stats = service.get_stats()
        assert "symbols_tracked" in stats
        assert stats["symbols_tracked"] == 1

    def test_global_instance(self):
        from data.time_and_sales import get_time_and_sales_service

        s1 = get_time_and_sales_service()
        s2 = get_time_and_sales_service()
        assert s1 is s2

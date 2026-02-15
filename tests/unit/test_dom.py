"""
Comprehensive Tests for Data Module

Tests for:
- Depth of Market (DOM) Service
- Order Book Management
"""

import pytest
from datetime import datetime


class TestOrderBookLevel:
    """Tests for OrderBookLevel dataclass."""

    def test_level_creation(self):
        """Test creating an order book level."""
        from data.depth_of_market import OrderBookLevel

        level = OrderBookLevel(
            price=1950.00,
            size=100.0,
            order_count=5
        )

        assert level.price == 1950.00
        assert level.size == 100.0
        assert level.order_count == 5

    def test_level_to_dict(self):
        """Test level serialization."""
        from data.depth_of_market import OrderBookLevel

        level = OrderBookLevel(price=1950.00, size=100.0)
        result = level.to_dict()

        assert result['price'] == 1950.00
        assert result['size'] == 100.0
        assert 'timestamp' in result


class TestOrderBook:
    """Tests for OrderBook dataclass."""

    def test_empty_orderbook(self):
        """Test empty order book."""
        from data.depth_of_market import OrderBook

        ob = OrderBook(symbol="XAUUSD")

        assert ob.symbol == "XAUUSD"
        assert ob.bids == []
        assert ob.asks == []
        assert ob.best_bid is None
        assert ob.best_ask is None
        assert ob.spread is None
        assert ob.mid_price is None

    def test_orderbook_with_levels(self):
        """Test order book with bid/ask levels."""
        from data.depth_of_market import OrderBook, OrderBookLevel

        bids = [
            OrderBookLevel(price=1950.00, size=100),
            OrderBookLevel(price=1949.50, size=150),
        ]
        asks = [
            OrderBookLevel(price=1950.50, size=80),
            OrderBookLevel(price=1951.00, size=120),
        ]

        ob = OrderBook(symbol="XAUUSD", bids=bids, asks=asks)

        assert ob.best_bid == 1950.00
        assert ob.best_ask == 1950.50
        assert ob.spread == 0.5
        assert ob.mid_price == 1950.25

    def test_orderbook_imbalance(self):
        """Test order book imbalance calculation."""
        from data.depth_of_market import OrderBook, OrderBookLevel

        # More bids than asks = positive imbalance (bullish)
        bids = [OrderBookLevel(price=1950.00, size=200)]
        asks = [OrderBookLevel(price=1950.50, size=100)]

        ob = OrderBook(symbol="XAUUSD", bids=bids, asks=asks)

        assert ob.imbalance > 0  # Bullish

    def test_orderbook_weighted_mid_price(self):
        """Test weighted mid price calculation."""
        from data.depth_of_market import OrderBook, OrderBookLevel

        bids = [OrderBookLevel(price=1950.00, size=100)]
        asks = [OrderBookLevel(price=1951.00, size=100)]

        ob = OrderBook(symbol="XAUUSD", bids=bids, asks=asks)

        # Equal volumes should give simple mid price
        assert ob.weighted_mid_price == 1950.5

    def test_orderbook_total_volume(self):
        """Test total volume calculation."""
        from data.depth_of_market import OrderBook, OrderBookLevel

        bids = [
            OrderBookLevel(price=1950.00, size=100),
            OrderBookLevel(price=1949.50, size=150),
        ]
        asks = [
            OrderBookLevel(price=1950.50, size=80),
            OrderBookLevel(price=1951.00, size=70),
        ]

        ob = OrderBook(symbol="XAUUSD", bids=bids, asks=asks)

        assert ob.total_bid_volume == 250
        assert ob.total_ask_volume == 150

    def test_orderbook_to_dict(self):
        """Test order book serialization."""
        from data.depth_of_market import OrderBook, OrderBookLevel

        bids = [OrderBookLevel(price=1950.00, size=100)]
        asks = [OrderBookLevel(price=1950.50, size=80)]

        ob = OrderBook(symbol="XAUUSD", bids=bids, asks=asks)
        result = ob.to_dict()

        assert result['symbol'] == "XAUUSD"
        assert 'bids' in result
        assert 'asks' in result
        assert 'spread' in result
        assert 'imbalance' in result


class TestDepthOfMarketService:
    """Tests for DepthOfMarketService."""

    def test_service_initialization(self):
        """Test service initialization."""
        from data.depth_of_market import DepthOfMarketService

        service = DepthOfMarketService()
        assert service is not None
        assert hasattr(service, '_order_books')

    def test_update_order_book(self):
        """Test updating order book."""
        from data.depth_of_market import DepthOfMarketService

        service = DepthOfMarketService()

        service.update_order_book(
            symbol='XAUUSD',
            bids=[(1950.00, 100), (1949.50, 150)],
            asks=[(1950.50, 80), (1951.00, 120)]
        )

        ob = service.get_order_book('XAUUSD')
        assert ob is not None
        assert ob.best_bid == 1950.00
        assert ob.best_ask == 1950.50

    def test_get_nonexistent_order_book(self):
        """Test getting non-existent order book."""
        from data.depth_of_market import DepthOfMarketService

        service = DepthOfMarketService()
        ob = service.get_order_book('NONEXISTENT')

        assert ob is None

    def test_get_spread(self):
        """Test getting spread."""
        from data.depth_of_market import DepthOfMarketService

        service = DepthOfMarketService()
        service.update_order_book(
            symbol='EURUSD',
            bids=[(1.0800, 1000)],
            asks=[(1.0802, 800)]
        )

        spread = service.get_spread('EURUSD')
        assert spread == pytest.approx(0.0002, rel=0.01)

    def test_get_imbalance(self):
        """Test getting imbalance."""
        from data.depth_of_market import DepthOfMarketService

        service = DepthOfMarketService()
        service.update_order_book(
            symbol='GBPUSD',
            bids=[(1.2500, 200)],
            asks=[(1.2502, 100)]
        )

        imbalance = service.get_imbalance('GBPUSD')
        assert imbalance > 0  # More bids = bullish

    def test_get_order_book_analysis(self):
        """Test order book analysis."""
        from data.depth_of_market import DepthOfMarketService

        service = DepthOfMarketService()
        service.update_order_book(
            symbol='XAUUSD',
            bids=[(1950.00, 100), (1949.50, 150), (1949.00, 200)],
            asks=[(1950.50, 80), (1951.00, 120), (1951.50, 100)]
        )

        analysis = service.get_order_book_analysis('XAUUSD')
        assert analysis is not None
        assert hasattr(analysis, 'spread')
        assert hasattr(analysis, 'imbalance')
        assert hasattr(analysis, 'buying_pressure')
        assert hasattr(analysis, 'selling_pressure')
        assert hasattr(analysis, 'market_bias')

    def test_get_dom_visualization_data(self):
        """Test DOM visualization data."""
        from data.depth_of_market import DepthOfMarketService

        service = DepthOfMarketService()
        service.update_order_book(
            symbol='XAUUSD',
            bids=[(1950.00, 100), (1949.99, 150)],
            asks=[(1950.01, 80), (1950.02, 120)]
        )

        viz = service.get_dom_visualization_data('XAUUSD', levels=10)
        assert viz is not None
        assert 'ladder' in viz
        assert 'summary' in viz
        assert 'timestamp' in viz

    def test_get_order_book_history(self):
        """Test order book history."""
        from data.depth_of_market import DepthOfMarketService

        service = DepthOfMarketService()

        # Add multiple updates
        for i in range(5):
            service.update_order_book(
                symbol='XAUUSD',
                bids=[(1950.00 + i, 100)],
                asks=[(1951.00 + i, 80)]
            )

        history = service.get_order_book_history('XAUUSD', limit=3)
        assert len(history) == 3

    def test_get_imbalance_history(self):
        """Test imbalance history."""
        from data.depth_of_market import DepthOfMarketService

        service = DepthOfMarketService()

        # Add multiple updates
        for i in range(3):
            service.update_order_book(
                symbol='XAUUSD',
                bids=[(1950.00, 100 + i * 50)],
                asks=[(1950.50, 80)]
            )

        history = service.get_imbalance_history('XAUUSD', limit=2)
        assert len(history) == 2
        assert all('imbalance' in h for h in history)

    def test_get_symbols(self):
        """Test getting tracked symbols."""
        from data.depth_of_market import DepthOfMarketService

        service = DepthOfMarketService()
        service.update_order_book('XAUUSD', [(1950, 100)], [(1951, 80)])
        service.update_order_book('EURUSD', [(1.08, 100)], [(1.0801, 80)])

        symbols = service.get_symbols()
        assert 'XAUUSD' in symbols
        assert 'EURUSD' in symbols

    def test_clear_symbol(self):
        """Test clearing a symbol."""
        from data.depth_of_market import DepthOfMarketService

        service = DepthOfMarketService()
        service.update_order_book('XAUUSD', [(1950, 100)], [(1951, 80)])

        service.clear_symbol('XAUUSD')

        assert service.get_order_book('XAUUSD') is None

    def test_clear_all(self):
        """Test clearing all symbols."""
        from data.depth_of_market import DepthOfMarketService

        service = DepthOfMarketService()
        service.update_order_book('XAUUSD', [(1950, 100)], [(1951, 80)])
        service.update_order_book('EURUSD', [(1.08, 100)], [(1.0801, 80)])

        service.clear_all()

        assert len(service.get_symbols()) == 0

    def test_get_stats(self):
        """Test getting service statistics."""
        from data.depth_of_market import DepthOfMarketService

        service = DepthOfMarketService()
        service.update_order_book('XAUUSD', [(1950, 100)], [(1951, 80)])

        stats = service.get_stats()
        assert 'symbols_tracked' in stats
        assert 'total_updates' in stats

    def test_update_single_level(self):
        """Test updating a single level."""
        from data.depth_of_market import DepthOfMarketService, OrderBookSide

        service = DepthOfMarketService()
        service.update_order_book('XAUUSD', [(1950, 100)], [(1951, 80)])

        # Update a single bid level
        service.update_level('XAUUSD', OrderBookSide.BID, 1950.00, 200)

        ob = service.get_order_book('XAUUSD')
        # Should have updated the level
        assert ob is not None

    def test_global_instance(self):
        """Test global DOM service instance."""
        from data.depth_of_market import get_dom_service

        service1 = get_dom_service()
        service2 = get_dom_service()

        # Should be the same instance
        assert service1 is service2


class TestOrderBookSide:
    """Tests for OrderBookSide enum."""

    def test_side_values(self):
        """Test OrderBookSide enum values."""
        from data.depth_of_market import OrderBookSide

        assert OrderBookSide.BID.value == "bid"
        assert OrderBookSide.ASK.value == "ask"

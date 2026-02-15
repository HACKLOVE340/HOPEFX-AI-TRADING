"""
Depth of Market (DOM) Service

Provides Level 2 order book management and visualization:
- Real-time bid/ask order book updates
- Order book imbalance analysis
- Weighted mid-price calculation
- DOM visualization data format
- Order book history snapshots

Inspired by: MT5, Bookmap, NinjaTrader DOM features
"""

import logging
from datetime import datetime
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, field, asdict
from collections import deque
from enum import Enum
import threading

logger = logging.getLogger(__name__)


class OrderBookSide(Enum):
    """Order book side."""
    BID = "bid"
    ASK = "ask"


@dataclass
class OrderBookLevel:
    """Single level in the order book."""
    price: float
    size: float
    order_count: int = 1
    timestamp: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> Dict:
        return {
            'price': self.price,
            'size': self.size,
            'order_count': self.order_count,
            'timestamp': self.timestamp.isoformat()
        }


@dataclass
class OrderBook:
    """
    Complete order book for a symbol.
    """
    symbol: str
    bids: List[OrderBookLevel] = field(default_factory=list)
    asks: List[OrderBookLevel] = field(default_factory=list)
    timestamp: datetime = field(default_factory=datetime.utcnow)
    sequence: int = 0

    @property
    def best_bid(self) -> Optional[float]:
        """Get best bid price."""
        return self.bids[0].price if self.bids else None

    @property
    def best_ask(self) -> Optional[float]:
        """Get best ask price."""
        return self.asks[0].price if self.asks else None

    @property
    def spread(self) -> Optional[float]:
        """Calculate bid-ask spread."""
        if self.best_bid and self.best_ask:
            return round(self.best_ask - self.best_bid, 5)
        return None

    @property
    def spread_pct(self) -> Optional[float]:
        """Calculate spread as percentage of mid price."""
        if self.best_bid and self.best_ask:
            mid = (self.best_bid + self.best_ask) / 2
            return round((self.spread / mid) * 100, 4) if mid > 0 else None
        return None

    @property
    def mid_price(self) -> Optional[float]:
        """Calculate simple mid price."""
        if self.best_bid and self.best_ask:
            return round((self.best_bid + self.best_ask) / 2, 5)
        return None

    @property
    def weighted_mid_price(self) -> Optional[float]:
        """Calculate volume-weighted mid price."""
        if not self.bids or not self.asks:
            return None

        bid_volume = self.bids[0].size
        ask_volume = self.asks[0].size
        total_volume = bid_volume + ask_volume

        if total_volume == 0:
            return self.mid_price

        # Weight by inverse of volume (larger volume = closer to that side)
        weighted = (
            (self.best_bid * ask_volume + self.best_ask * bid_volume) /
            total_volume
        )
        return round(weighted, 5)

    @property
    def total_bid_volume(self) -> float:
        """Total volume on bid side."""
        return sum(level.size for level in self.bids)

    @property
    def total_ask_volume(self) -> float:
        """Total volume on ask side."""
        return sum(level.size for level in self.asks)

    @property
    def imbalance(self) -> float:
        """
        Calculate order book imbalance.
        Positive = more bids (bullish)
        Negative = more asks (bearish)
        Range: -1 to 1
        """
        total_bid = self.total_bid_volume
        total_ask = self.total_ask_volume
        total = total_bid + total_ask

        if total == 0:
            return 0.0

        return round((total_bid - total_ask) / total, 4)

    @property
    def depth_levels(self) -> int:
        """Number of price levels available."""
        return max(len(self.bids), len(self.asks))

    def to_dict(self) -> Dict:
        return {
            'symbol': self.symbol,
            'bids': [level.to_dict() for level in self.bids],
            'asks': [level.to_dict() for level in self.asks],
            'best_bid': self.best_bid,
            'best_ask': self.best_ask,
            'spread': self.spread,
            'spread_pct': self.spread_pct,
            'mid_price': self.mid_price,
            'weighted_mid_price': self.weighted_mid_price,
            'total_bid_volume': self.total_bid_volume,
            'total_ask_volume': self.total_ask_volume,
            'imbalance': self.imbalance,
            'depth_levels': self.depth_levels,
            'timestamp': self.timestamp.isoformat(),
            'sequence': self.sequence
        }


@dataclass
class OrderBookAnalysis:
    """Order book analysis results."""
    symbol: str
    timestamp: datetime

    # Basic metrics
    spread: float
    spread_pct: float
    mid_price: float
    weighted_mid_price: float

    # Volume analysis
    total_bid_volume: float
    total_ask_volume: float
    imbalance: float
    imbalance_pct: float

    # Depth analysis
    bid_depth_5: float  # Volume within 5 levels
    ask_depth_5: float
    bid_depth_10: float  # Volume within 10 levels
    ask_depth_10: float

    # Support/Resistance levels
    key_bid_levels: List[Dict]  # High volume bid levels
    key_ask_levels: List[Dict]  # High volume ask levels

    # Signals
    buying_pressure: str  # 'strong', 'moderate', 'weak'
    selling_pressure: str
    market_bias: str  # 'bullish', 'bearish', 'neutral'

    def to_dict(self) -> Dict:
        return asdict(self)


class DepthOfMarketService:
    """
    Depth of Market (DOM) service for order book management.

    Features:
    - Real-time order book updates
    - Multiple depth levels (10, 20, 50 levels)
    - Order book imbalance calculation
    - Weighted mid-price
    - Historical snapshots
    - DOM visualization data
    - Support/resistance detection from order book

    Usage:
        dom_service = DepthOfMarketService()

        # Update order book
        dom_service.update_order_book(
            'XAUUSD',
            bids=[(1950.00, 100), (1949.95, 150), ...],
            asks=[(1950.05, 80), (1950.10, 120), ...]
        )

        # Get current DOM
        dom = dom_service.get_order_book('XAUUSD')

        # Get analysis
        analysis = dom_service.get_order_book_analysis('XAUUSD')
    """

    def __init__(self, config: Optional[Dict] = None):
        """
        Initialize DOM service.

        Args:
            config: Configuration options
        """
        self.config = config or {}

        # Order books by symbol
        self._order_books: Dict[str, OrderBook] = {}

        # Historical snapshots
        self._history_size = self.config.get('history_size', 100)
        self._history: Dict[str, deque] = {}

        # Sequence counter
        self._sequence = 0

        # Thread safety
        self._lock = threading.RLock()

        # Configuration
        self._max_levels = self.config.get('max_levels', 50)
        self._volume_threshold = self.config.get('volume_threshold', 0.1)

        logger.info("Depth of Market Service initialized")

    # ================================================================
    # ORDER BOOK UPDATES
    # ================================================================

    def update_order_book(
        self,
        symbol: str,
        bids: List[Tuple[float, float]],
        asks: List[Tuple[float, float]],
        timestamp: Optional[datetime] = None
    ):
        """
        Update order book for a symbol.

        Args:
            symbol: Trading symbol
            bids: List of (price, size) tuples, sorted by price desc
            asks: List of (price, size) tuples, sorted by price asc
            timestamp: Update timestamp
        """
        with self._lock:
            self._sequence += 1

            # Convert to OrderBookLevel objects
            bid_levels = [
                OrderBookLevel(price=price, size=size)
                for price, size in bids[:self._max_levels]
            ]
            ask_levels = [
                OrderBookLevel(price=price, size=size)
                for price, size in asks[:self._max_levels]
            ]

            # Create or update order book
            order_book = OrderBook(
                symbol=symbol,
                bids=bid_levels,
                asks=ask_levels,
                timestamp=timestamp or datetime.utcnow(),
                sequence=self._sequence
            )

            self._order_books[symbol] = order_book

            # Store in history
            if symbol not in self._history:
                self._history[symbol] = deque(maxlen=self._history_size)
            self._history[symbol].append(order_book)

            logger.debug(f"Order book updated: {symbol}, seq={self._sequence}")

    def update_level(
        self,
        symbol: str,
        side: OrderBookSide,
        price: float,
        size: float
    ):
        """
        Update a single level in the order book.

        Args:
            symbol: Trading symbol
            side: BID or ASK
            price: Price level
            size: New size (0 to remove)
        """
        with self._lock:
            if symbol not in self._order_books:
                logger.warning(f"No order book for {symbol}")
                return

            order_book = self._order_books[symbol]
            levels = order_book.bids if side == OrderBookSide.BID else order_book.asks

            # Find existing level
            for i, level in enumerate(levels):
                if level.price == price:
                    if size == 0:
                        # Remove level
                        levels.pop(i)
                    else:
                        # Update level
                        level.size = size
                        level.timestamp = datetime.utcnow()
                    return

            # Add new level if size > 0
            if size > 0:
                new_level = OrderBookLevel(price=price, size=size)
                levels.append(new_level)

                # Sort levels
                if side == OrderBookSide.BID:
                    levels.sort(key=lambda x: -x.price)
                else:
                    levels.sort(key=lambda x: x.price)

                # Trim to max levels
                if len(levels) > self._max_levels:
                    levels.pop()

    # ================================================================
    # ORDER BOOK RETRIEVAL
    # ================================================================

    def get_order_book(
        self,
        symbol: str,
        levels: int = 10
    ) -> Optional[OrderBook]:
        """
        Get order book for a symbol.

        Args:
            symbol: Trading symbol
            levels: Number of levels to return

        Returns:
            OrderBook or None
        """
        with self._lock:
            if symbol not in self._order_books:
                return None

            order_book = self._order_books[symbol]

            # Return subset of levels if requested
            if levels < self._max_levels:
                return OrderBook(
                    symbol=symbol,
                    bids=order_book.bids[:levels],
                    asks=order_book.asks[:levels],
                    timestamp=order_book.timestamp,
                    sequence=order_book.sequence
                )

            return order_book

    def get_order_book_dict(
        self,
        symbol: str,
        levels: int = 10
    ) -> Optional[Dict]:
        """Get order book as dictionary."""
        order_book = self.get_order_book(symbol, levels)
        return order_book.to_dict() if order_book else None

    def get_best_bid_ask(self, symbol: str) -> Optional[Dict]:
        """Get best bid and ask for a symbol."""
        with self._lock:
            if symbol not in self._order_books:
                return None

            order_book = self._order_books[symbol]
            return {
                'symbol': symbol,
                'best_bid': order_book.best_bid,
                'best_ask': order_book.best_ask,
                'spread': order_book.spread,
                'mid_price': order_book.mid_price,
                'timestamp': order_book.timestamp.isoformat()
            }

    def get_spread(self, symbol: str) -> Optional[float]:
        """Get current spread for a symbol."""
        with self._lock:
            if symbol not in self._order_books:
                return None
            return self._order_books[symbol].spread

    def get_imbalance(self, symbol: str) -> Optional[float]:
        """Get order book imbalance for a symbol."""
        with self._lock:
            if symbol not in self._order_books:
                return None
            return self._order_books[symbol].imbalance

    # ================================================================
    # ORDER BOOK ANALYSIS
    # ================================================================

    def get_order_book_analysis(self, symbol: str) -> Optional[OrderBookAnalysis]:
        """
        Get comprehensive order book analysis.

        Args:
            symbol: Trading symbol

        Returns:
            OrderBookAnalysis or None
        """
        with self._lock:
            if symbol not in self._order_books:
                return None

            order_book = self._order_books[symbol]

            # Calculate depth at different levels
            bid_depth_5 = sum(level.size for level in order_book.bids[:5])
            ask_depth_5 = sum(level.size for level in order_book.asks[:5])
            bid_depth_10 = sum(level.size for level in order_book.bids[:10])
            ask_depth_10 = sum(level.size for level in order_book.asks[:10])

            # Find key levels (high volume)
            key_bid_levels = self._find_key_levels(order_book.bids)
            key_ask_levels = self._find_key_levels(order_book.asks)

            # Calculate pressure
            total_bid = order_book.total_bid_volume
            total_ask = order_book.total_ask_volume
            imbalance = order_book.imbalance

            buying_pressure = self._classify_pressure(imbalance, positive=True)
            selling_pressure = self._classify_pressure(-imbalance, positive=True)

            # Determine market bias
            if imbalance > 0.2:
                market_bias = 'bullish'
            elif imbalance < -0.2:
                market_bias = 'bearish'
            else:
                market_bias = 'neutral'

            return OrderBookAnalysis(
                symbol=symbol,
                timestamp=order_book.timestamp,
                spread=order_book.spread or 0,
                spread_pct=order_book.spread_pct or 0,
                mid_price=order_book.mid_price or 0,
                weighted_mid_price=order_book.weighted_mid_price or 0,
                total_bid_volume=total_bid,
                total_ask_volume=total_ask,
                imbalance=imbalance,
                imbalance_pct=round(imbalance * 100, 2),
                bid_depth_5=bid_depth_5,
                ask_depth_5=ask_depth_5,
                bid_depth_10=bid_depth_10,
                ask_depth_10=ask_depth_10,
                key_bid_levels=key_bid_levels,
                key_ask_levels=key_ask_levels,
                buying_pressure=buying_pressure,
                selling_pressure=selling_pressure,
                market_bias=market_bias
            )

    def _find_key_levels(
        self,
        levels: List[OrderBookLevel],
        top_n: int = 3
    ) -> List[Dict]:
        """Find key price levels with high volume."""
        if not levels:
            return []

        # Sort by size
        sorted_levels = sorted(levels, key=lambda x: -x.size)

        return [
            {
                'price': level.price,
                'size': level.size,
                'rank': i + 1
            }
            for i, level in enumerate(sorted_levels[:top_n])
        ]

    def _classify_pressure(self, value: float, positive: bool) -> str:
        """Classify pressure level."""
        if positive:
            value = abs(value)

        if value > 0.4:
            return 'strong'
        elif value > 0.15:
            return 'moderate'
        else:
            return 'weak'

    # ================================================================
    # VISUALIZATION DATA
    # ================================================================

    def get_dom_visualization_data(
        self,
        symbol: str,
        levels: int = 20
    ) -> Optional[Dict]:
        """
        Get data formatted for DOM visualization.

        Returns data suitable for rendering a DOM ladder.

        Args:
            symbol: Trading symbol
            levels: Number of levels to include

        Returns:
            Visualization data dict
        """
        with self._lock:
            if symbol not in self._order_books:
                return None

            order_book = self._order_books[symbol]

            # Get price range
            all_prices = set()
            for level in order_book.bids[:levels]:
                all_prices.add(level.price)
            for level in order_book.asks[:levels]:
                all_prices.add(level.price)

            if not all_prices:
                return None

            min_price = min(all_prices)
            max_price = max(all_prices)

            # Create bid/ask maps
            bid_map = {level.price: level.size for level in order_book.bids}
            ask_map = {level.price: level.size for level in order_book.asks}

            # Build ladder
            ladder = []
            tick_size = 0.01  # TODO: Get from symbol config

            # Generate price ladder
            price = max_price
            while price >= min_price:
                row = {
                    'price': price,
                    'bid_size': bid_map.get(price, 0),
                    'ask_size': ask_map.get(price, 0),
                    'is_best_bid': price == order_book.best_bid,
                    'is_best_ask': price == order_book.best_ask,
                    'is_mid': abs(price - (order_book.mid_price or 0)) < tick_size
                }
                ladder.append(row)
                price = round(price - tick_size, 5)

            # Calculate max sizes for scaling
            max_bid = max((row['bid_size'] for row in ladder), default=1)
            max_ask = max((row['ask_size'] for row in ladder), default=1)

            # Add scaled values
            for row in ladder:
                row['bid_pct'] = round(row['bid_size'] / max_bid * 100, 1) if max_bid > 0 else 0
                row['ask_pct'] = round(row['ask_size'] / max_ask * 100, 1) if max_ask > 0 else 0

            return {
                'symbol': symbol,
                'ladder': ladder,
                'summary': {
                    'best_bid': order_book.best_bid,
                    'best_ask': order_book.best_ask,
                    'spread': order_book.spread,
                    'mid_price': order_book.mid_price,
                    'imbalance': order_book.imbalance,
                    'total_bid_volume': order_book.total_bid_volume,
                    'total_ask_volume': order_book.total_ask_volume,
                },
                'timestamp': order_book.timestamp.isoformat()
            }

    # ================================================================
    # HISTORY & SNAPSHOTS
    # ================================================================

    def get_order_book_history(
        self,
        symbol: str,
        limit: int = 50
    ) -> List[Dict]:
        """Get historical order book snapshots."""
        with self._lock:
            if symbol not in self._history:
                return []

            snapshots = list(self._history[symbol])[-limit:]
            return [ob.to_dict() for ob in snapshots]

    def get_imbalance_history(
        self,
        symbol: str,
        limit: int = 50
    ) -> List[Dict]:
        """Get imbalance history for a symbol."""
        with self._lock:
            if symbol not in self._history:
                return []

            snapshots = list(self._history[symbol])[-limit:]
            return [
                {
                    'timestamp': ob.timestamp.isoformat(),
                    'imbalance': ob.imbalance,
                    'spread': ob.spread,
                    'mid_price': ob.mid_price
                }
                for ob in snapshots
            ]

    # ================================================================
    # UTILITY
    # ================================================================

    def get_symbols(self) -> List[str]:
        """Get list of symbols with order books."""
        with self._lock:
            return list(self._order_books.keys())

    def clear_symbol(self, symbol: str):
        """Clear order book for a symbol."""
        with self._lock:
            if symbol in self._order_books:
                del self._order_books[symbol]
            if symbol in self._history:
                del self._history[symbol]

    def clear_all(self):
        """Clear all order books."""
        with self._lock:
            self._order_books.clear()
            self._history.clear()

    def get_stats(self) -> Dict:
        """Get service statistics."""
        with self._lock:
            return {
                'symbols_tracked': len(self._order_books),
                'total_updates': self._sequence,
                'symbols': list(self._order_books.keys()),
                'history_sizes': {
                    symbol: len(history)
                    for symbol, history in self._history.items()
                }
            }


# ================================================================
# FASTAPI INTEGRATION
# ================================================================

def create_dom_router(dom_service: DepthOfMarketService):
    """
    Create FastAPI router with DOM endpoints.

    Args:
        dom_service: DepthOfMarketService instance

    Returns:
        FastAPI APIRouter
    """
    from fastapi import APIRouter, HTTPException

    router = APIRouter(prefix="/api/dom", tags=["Depth of Market"])

    @router.get("/{symbol}")
    async def get_order_book(symbol: str, levels: int = 10):
        """Get order book for a symbol."""
        data = dom_service.get_order_book_dict(symbol, levels)
        if data is None:
            raise HTTPException(status_code=404, detail=f"No order book for {symbol}")
        return data

    @router.get("/{symbol}/analysis")
    async def get_analysis(symbol: str):
        """Get order book analysis."""
        analysis = dom_service.get_order_book_analysis(symbol)
        if analysis is None:
            raise HTTPException(status_code=404, detail=f"No order book for {symbol}")
        return analysis.to_dict()

    @router.get("/{symbol}/visualization")
    async def get_visualization(symbol: str, levels: int = 20):
        """Get DOM visualization data."""
        data = dom_service.get_dom_visualization_data(symbol, levels)
        if data is None:
            raise HTTPException(status_code=404, detail=f"No order book for {symbol}")
        return data

    @router.get("/{symbol}/history")
    async def get_history(symbol: str, limit: int = 50):
        """Get order book history."""
        return dom_service.get_order_book_history(symbol, limit)

    @router.get("/{symbol}/imbalance")
    async def get_imbalance(symbol: str):
        """Get current imbalance."""
        imbalance = dom_service.get_imbalance(symbol)
        if imbalance is None:
            raise HTTPException(status_code=404, detail=f"No order book for {symbol}")
        return {"symbol": symbol, "imbalance": imbalance}

    @router.get("/")
    async def get_all_symbols():
        """Get all tracked symbols."""
        return {"symbols": dom_service.get_symbols()}

    @router.get("/stats")
    async def get_stats():
        """Get service statistics."""
        return dom_service.get_stats()

    return router


# Global instance for easy access
_dom_service: Optional[DepthOfMarketService] = None


def get_dom_service() -> DepthOfMarketService:
    """Get the global DOM service instance."""
    global _dom_service
    if _dom_service is None:
        _dom_service = DepthOfMarketService()
    return _dom_service

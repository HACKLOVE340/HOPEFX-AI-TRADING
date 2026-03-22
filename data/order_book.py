"""Order book data structures."""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
import time


@dataclass
class OrderBookLevel:
    price: float
    size: float


@dataclass
class OrderBook:
    symbol: str
    bids: List[OrderBookLevel] = field(default_factory=list)
    asks: List[OrderBookLevel] = field(default_factory=list)
    timestamp: float = field(default_factory=time.time)

    @property
    def best_bid(self) -> Optional[float]:
        return self.bids[0].price if self.bids else None

    @property
    def best_ask(self) -> Optional[float]:
        return self.asks[0].price if self.asks else None

    @property
    def mid_price(self) -> Optional[float]:
        if self.best_bid and self.best_ask:
            return (self.best_bid + self.best_ask) / 2
        return None

    @property
    def spread(self) -> Optional[float]:
        if self.best_bid and self.best_ask:
            return self.best_ask - self.best_bid
        return None

    def update(self, bids: List[Tuple[float, float]], asks: List[Tuple[float, float]]) -> None:
        self.bids = [OrderBookLevel(p, s) for p, s in sorted(bids, reverse=True)]
        self.asks = [OrderBookLevel(p, s) for p, s in sorted(asks)]
        self.timestamp = time.time()


class MultiSymbolOrderBook:
    """Manages order books for multiple symbols."""

    def __init__(self):
        self._books: Dict[str, OrderBook] = {}

    def get_book(self, symbol: str) -> OrderBook:
        if symbol not in self._books:
            self._books[symbol] = OrderBook(symbol=symbol)
        return self._books[symbol]

    def update(self, symbol: str, bids: List[Tuple[float, float]],
               asks: List[Tuple[float, float]]) -> None:
        self.get_book(symbol).update(bids, asks)

    def get_mid_price(self, symbol: str) -> Optional[float]:
        return self.get_book(symbol).mid_price

    def symbols(self) -> List[str]:
        return list(self._books.keys())

# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""Order book data structures."""

from dataclasses import dataclass, field
import time


@dataclass
class OrderBookLevel:
    price: float
    size: float


@dataclass
class OrderBook:
    symbol: str
    bids: list[OrderBookLevel] = field(default_factory=list)
    asks: list[OrderBookLevel] = field(default_factory=list)
    timestamp: float = field(default_factory=time.time)

    @property
    def best_bid(self) -> float | None:
        return self.bids[0].price if self.bids else None

    @property
    def best_ask(self) -> float | None:
        return self.asks[0].price if self.asks else None

    @property
    def mid_price(self) -> float | None:
        if self.best_bid and self.best_ask:
            return (self.best_bid + self.best_ask) / 2
        return None

    @property
    def spread(self) -> float | None:
        if self.best_bid and self.best_ask:
            return self.best_ask - self.best_bid
        return None

    def update(self, bids: list[tuple[float, float]], asks: list[tuple[float, float]]) -> None:
        self.bids = [OrderBookLevel(p, s) for p, s in sorted(bids, reverse=True)]
        self.asks = [OrderBookLevel(p, s) for p, s in sorted(asks)]
        self.timestamp = time.time()


class MultiSymbolOrderBook:
    """Manages order books for multiple symbols."""

    def __init__(self):
        self._books: dict[str, OrderBook] = {}

    def get_book(self, symbol: str) -> OrderBook:
        if symbol not in self._books:
            self._books[symbol] = OrderBook(symbol=symbol)
        return self._books[symbol]

    def update(
        self,
        symbol: str,
        bids: list[tuple[float, float]],
        asks: list[tuple[float, float]],
    ) -> None:
        self.get_book(symbol).update(bids, asks)

    def get_mid_price(self, symbol: str) -> float | None:
        return self.get_book(symbol).mid_price

    def symbols(self) -> list[str]:
        return list(self._books.keys())

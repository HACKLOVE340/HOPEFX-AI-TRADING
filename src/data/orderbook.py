"""Real-time order book reconstruction with imbalance signals."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Callable

import numpy as np
import structlog

from src.core.types import Tick, Side

logger = structlog.get_logger()


@dataclass(order=True)
class PriceLevel:
    price: Decimal
    volume: Decimal = field(compare=False)
    order_count: int = field(default=1, compare=False)
    timestamp: float = field(default_factory=lambda: asyncio.get_event_loop().time(), compare=False)


class OrderBook:
    """Price-time priority order book."""
    
    def __init__(self, symbol: str, max_depth: int = 100) -> None:
        self.symbol = symbol
        self.max_depth = max_depth
        
        # Sorted containers: bids descending, asks ascending
        self.bids: list[PriceLevel] = []  # Sorted high to low
        self.asks: list[PriceLevel] = []  # Sorted low to high
        
        # Statistics
        self._update_count = 0
        self._last_update = 0.0
        self._imbalance_history: list[float] = []
        self._max_history = 1000
        
        # Callbacks
        self._on_large_imbalance: list[Callable[[float], None]] = []
    
    def update(self, side: Side, price: Decimal, volume: Decimal, is_delete: bool = False) -> None:
        """Update price level."""
        levels = self.bids if side == Side.BUY else self.asks
        
        # Find existing level
        existing = next((l for l in levels if l.price == price), None)
        
        if is_delete or volume <= 0:
            if existing:
                levels.remove(existing)
        elif existing:
            existing.volume = volume
            existing.timestamp = asyncio.get_event_loop().time()
        else:
            new_level = PriceLevel(price=price, volume=volume)
            levels.append(new_level)
            levels.sort(reverse=(side == Side.BUY))
            
            if len(levels) > self.max_depth:
                levels.pop()
        
        self._update_count += 1
        self._last_update = asyncio.get_event_loop().time()
        
        # Check for large imbalance
        imb = self.imbalance_ratio
        self._imbalance_history.append(imb)
        if len(self._imbalance_history) > self._max_history:
            self._imbalance_history.pop(0)
        
        if abs(imb) > 0.7:  # 70% one-sided
            for cb in self._on_large_imbalance:
                cb(imb)
    
    @property
    def best_bid(self) -> PriceLevel | None:
        return self.bids[0] if self.bids else None
    
    @property
    def best_ask(self) -> PriceLevel | None:
        return self.asks[0] if self.asks else None
    
    @property
    def mid_price(self) -> Decimal | None:
        if self.best_bid and self.best_ask:
            return (self.best_bid.price + self.best_ask.price) / 2
        return None
    
    @property
    def spread(self) -> Decimal | None:
        if self.best_bid and self.best_ask:
            return self.best_ask.price - self.best_bid.price
        return None
    
    @property
    def imbalance_ratio(self) -> float:
        """Bid volume / Total volume - 0.5, range [-0.5, 0.5]."""
        bid_vol = sum(l.volume for l in self.bids[:10])
        ask_vol = sum(l.volume for l in self.asks[:10])
        total = bid_vol + ask_vol
        if total == 0:
            return 0.0
        return float(bid_vol / total) - 0.5
    
    @property
    def book_imbalance_signal(self) -> float:
        """Microstructure trading signal."""
        # Weighted by price level (closer to mid = more important)
        bid_weighted = sum(
            l.volume * (1.0 / (i + 1)) 
            for i, l in enumerate(self.bids[:20])
        )
        ask_weighted = sum(
            l.volume * (1.0 / (i + 1))
            for i, l in enumerate(self.asks[:20])
        )
        total = bid_weighted + ask_weighted
        if total == 0:
            return 0.0
        return float((bid_weighted - ask_weighted) / total)
    
    def get_features(self) -> dict[str, float]:
        """Extract features for ML."""
        mid = self.mid_price
        if not mid:
            return {}
        
        spread = self.spread
        spread_bps = (float(spread) / float(mid)) * 10000 if spread else 0
        
        return {
            "book_imbalance": self.imbalance_ratio,
            "book_signal": self.book_imbalance_signal,
            "spread_bps": spread_bps,
            "bid_depth_10": float(sum(l.volume for l in self.bids[:10])),
            "ask_depth_10": float(sum(l.volume for l in self.asks[:10])),
            "bid_depth_50": float(sum(l.volume for l in self.bids)),
            "ask_depth_50": float(sum(l.volume for l in self.asks)),
            "update_frequency": self._update_count / max(1, asyncio.get_event_loop().time() - self._last_update),
        }


class MultiBookAggregator:
    """Aggregate order books across venues."""
    
    def __init__(self) -> None:
        self.books: dict[str, OrderBook] = {}
        self._venue_weights: dict[str, float] = {}
    
    def add_venue(self, venue: str, weight: float = 1.0) -> None:
        """Add venue with weight for aggregation."""
        self._venue_weights[venue] = weight
    
    def update(self, venue: str, symbol: str, side: Side, price: Decimal, volume: Decimal) -> None:
        """Update specific venue book."""
        key = f"{venue}:{symbol}"
        if key not in self.books:
            self.books[key] = OrderBook(symbol)
        
        self.books[key].update(side, price, volume)
    
    def get_consolidated(self, symbol: str) -> dict[str, Any]:
        """Get consolidated view across venues."""
        relevant = [b for k, b in self.books.items() if b.symbol == symbol]
        
        if not relevant:
            return {}
        
        # Weighted mid price
        total_weight = sum(self._venue_weights.get(k.split(":")[0], 1.0) for k in self.books if symbol in k)
        
        # Aggregate features
        features = {}
        for book in relevant:
            f = book.get_features()
            for k, v in f.items():
                features[k] = features.get(k, 0) + v
        
        # Average
        for k in features:
            features[k] /= len(relevant)
        
        return {
            "symbol": symbol,
            "venue_count": len(relevant),
            "consolidated_features": features,
            "best_global_bid": max((b.best_bid for b in relevant if b.best_bid), key=lambda x: x.price, default=None),
            "best_global_ask": min((b.best_ask for b in relevant if b.best_ask), key=lambda x: x.price, default=None),
        }

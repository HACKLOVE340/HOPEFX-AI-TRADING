"""
Level 2 order book reconstruction.
"""

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Callable

import numpy as np


@dataclass(order=True)
class PriceLevel:
    """Single price level in order book."""
    price: Decimal
    volume: Decimal
    side: str  # "bid" or "ask"
    order_count: int = 0
    
    def __post_init__(self):
        # Make hashable for heap operations
        self._key = (float(self.price), self.side)


class OrderBook:
    """
    Level 2 order book with microstructure analysis.
    """
    
    def __init__(self, symbol: str, max_levels: int = 100):
        self.symbol = symbol
        self.max_levels = max_levels
        
        self._bids: dict[Decimal, PriceLevel] = {}
        self._asks: dict[Decimal, PriceLevel] = {}
        self._callbacks: list[Callable] = []
        
        self._last_update: float = 0.0
        self._update_count: int = 0
    
    def update(self, side: str, price: Decimal, volume: Decimal, is_delete: bool = False) -> None:
        """Update order book level."""
        book = self._bids if side == "bid" else self._asks
        
        if is_delete or volume == 0:
            book.pop(price, None)
        else:
            book[price] = PriceLevel(
                price=price,
                volume=volume,
                side=side,
                order_count=book[price].order_count + 1 if price in book else 1
            )
        
        # Maintain max levels
        if len(book) > self.max_levels:
            # Remove worst level
            worst_price = min(book.keys()) if side == "bid" else max(book.keys())
            book.pop(worst_price, None)
        
        self._update_count += 1
    
    def get_bid_ask(self) -> tuple[Decimal, Decimal]:
        """Get best bid and ask."""
        best_bid = max(self._bids.keys()) if self._bids else Decimal("0")
        best_ask = min(self._asks.keys()) if self._asks else Decimal("0")
        return best_bid, best_ask
    
    def get_mid(self) -> Decimal:
        """Calculate mid price."""
        bid, ask = self.get_bid_ask()
        if bid > 0 and ask > 0:
            return (bid + ask) / 2
        return Decimal("0")
    
    def get_spread(self) -> Decimal:
        """Calculate bid-ask spread."""
        bid, ask = self.get_bid_ask()
        return ask - bid
    
    def get_spread_bps(self) -> float:
        """Calculate spread in basis points."""
        mid = self.get_mid()
        spread = self.get_spread()
        if mid > 0:
            return float(spread / mid) * 10000
        return 0.0
    
    def get_volume_imbalance(self) -> float:
        """
        Calculate order book imbalance.
        Positive = more bids (bullish), Negative = more asks (bearish)
        """
        bid_volume = sum(l.volume for l in self._bids.values())
        ask_volume = sum(l.volume for l in self._asks.values())
        
        total = bid_volume + ask_volume
        if total == 0:
            return 0.0
        
        return float(bid_volume - ask_volume) / float(total)
    
    def get_weighted_mid(self) -> Decimal:
        """Volume-weighted mid price."""
        bid, ask = self.get_bid_ask()
        bid_vol = self._bids.get(bid, PriceLevel(bid, Decimal("0"), "bid")).volume
        ask_vol = self._asks.get(ask, PriceLevel(ask, Decimal("0"), "ask")).volume
        
        total_vol = bid_vol + ask_vol
        if total_vol == 0:
            return self.get_mid()
        
        weighted_bid = bid * bid_vol
        weighted_ask = ask * ask_vol
        
        return (weighted_bid + weighted_ask) / total_vol
    
    def estimate_impact(self, order_size: Decimal, side: str) -> Decimal:
        """
        Estimate price impact for order.
        Walks through order book levels.
        """
        book = self._asks if side == "buy" else self._bids
        
        # Sort: ascending for asks, descending for bids
        sorted_levels = sorted(
            book.values(),
            key=lambda x: x.price,
            reverse=(side == "sell")
        )
        
        remaining = order_size
        total_cost = Decimal("0")
        
        for level in sorted_levels:
            if remaining <= 0:
                break
            
            take = min(remaining, level.volume)
            total_cost += take * level.price
            remaining -= take
        
        # If couldn't fill entire order, use last price for remainder
        if remaining > 0 and sorted_levels:
            last_price = sorted_levels[-1].price
            total_cost += remaining * last_price
        
        if order_size > 0:
            avg_price = total_cost / order_size
            return avg_price
        
        return Decimal("0")
    
    def get_snapshot(self) -> dict:
        """Get order book snapshot."""
        return {
            "symbol": self.symbol,
            "timestamp": self._last_update,
            "bids": [
                {"price": float(l.price), "volume": float(l.volume)}
                for l in sorted(self._bids.values(), key=lambda x: x.price, reverse=True)[:10]
            ],
            "asks": [
                {"price": float(l.price), "volume": float(l.volume)}
                for l in sorted(self._asks.values(), key=lambda x: x.price)[:10]
            ],
            "spread_bps": self.get_spread_bps(),
            "imbalance": self.get_volume_imbalance(),
        }

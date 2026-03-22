"""Paper trading broker with realistic slippage."""
from __future__ import annotations

import asyncio
import random
from datetime import datetime
from decimal import Decimal
from typing import Any

import structlog

from src.core.types import (
    Order, Fill, Position, Side, OrderType, 
    OrderStatus, Symbol, Venue
)
from src.execution.brokers.base import Broker

logger = structlog.get_logger()


class PaperBroker(Broker):
    """Realistic paper trading."""
    
    def __init__(self, latency_ms: tuple[int, int] = (50, 200)) -> None:
        self.latency_range = latency_ms
        self._orders: dict[str, Order] = {}
        self._positions: dict[str, Position] = {}
        self._fills: list[Fill] = []
        self._balance = Decimal("100000.00")
        self._equity = Decimal("100000.00")
        self._connected = False
        
        # Slippage model
        self.base_slippage_bps = 2  # Base 2 bps
        self.vol_slippage_factor = 0.5  # Additional per vol unit
    
    async def connect(self) -> bool:
        """Simulate connection."""
        await asyncio.sleep(random.randint(*self.latency_range) / 1000)
        self._connected = True
        logger.info("Paper broker connected")
        return True
    
    async def disconnect(self) -> None:
        self._connected = False
    
    async def place_order(self, order: Order) -> Order:
        """Simulate order placement with latency and slippage."""
        # Simulate latency
        latency = random.randint(*self.latency_range) / 1000
        await asyncio.sleep(latency)
        
        # Calculate slippage
        slippage_bps = self._calculate_slippage(order)
        slippage_pct = Decimal(str(slippage_bps / 10000))
        
        if order.side == Side.BUY:
            fill_price = order.price * (Decimal("1") + slippage_pct) if order.price else Decimal("1800")
        else:
            fill_price = order.price * (Decimal("1") - slippage_pct) if order.price else Decimal("1800")
        
        # Simulate fill probability
        fill_prob = 0.95 if order.order_type == OrderType.MARKET else 0.7
        
        if random.random() < fill_prob:
            order.status = OrderStatus.FILLED
            order.filled_qty = order.quantity
            order.avg_fill_price = fill_price
            
            fill = Fill(
                order_id=order.id,
                fill_id=f"fill_{datetime.utcnow().timestamp()}",
                symbol=order.symbol,
                side=order.side,
                quantity=order.quantity,
                price=fill_price,
                timestamp=datetime.utcnow(),
                venue=Venue.PAPER,
                commission=order.quantity * fill_price * Decimal("0.0001"),  # 1 bp commission
                slippage=slippage_pct * order.price if order.price else Decimal("0")
            )
            self._fills.append(fill)
            
            # Update position
            await self._update_position(order, fill)
        else:
            order.status = OrderStatus.REJECTED
        
        self._orders[order.id] = order
        return order
    
    def _calculate_slippage(self, order: Order) -> float:
        """Calculate realistic slippage."""
        base = self.base_slippage_bps
        
        # Size impact (larger = more slippage)
        size_factor = float(order.quantity) / 100  # Normalize to 100 oz
        
        # Volatility impact
        vol = random.uniform(0.1, 0.5)  # Simulated volatility
        vol_factor = vol * self.vol_slippage_factor
        
        return base + size_factor + vol_factor
    
    async def _update_position(self, order: Order, fill: Fill) -> None:
        """Update position state."""
        pos_key = f"{order.symbol}_{order.side}"
        
        if pos_key in self._positions:
            pos = self._positions[pos_key]
            # Average down/up
            total_qty = pos.quantity + fill.quantity
            pos.entry_price = (
                (pos.entry_price * pos.quantity + fill.price * fill.quantity) / total_qty
            )
            pos.quantity = total_qty
        else:
            self._positions[pos_key] = Position(
                id=f"pos_{fill.fill_id}",
                symbol=order.symbol,
                side=order.side,
                entry_price=fill.price,
                quantity=fill.quantity,
                open_time=fill.timestamp,
                margin_used=fill.price * fill.quantity * Decimal("0.05")  # 5% margin
            )
    
    async def cancel_order(self, order_id: str) -> bool:
        if order_id in self._orders:
            self._orders[order_id].status = OrderStatus.CANCELLED
            return True
        return False
    
    async def get_positions(self) -> list[Position]:
        return list(self._positions.values())
    
    async def get_account(self) -> dict[str, Any]:
        return {
            "balance": self._balance,
            "equity": self._equity,
            "margin_used": sum(p.margin_used for p in self._positions.values()),
            "open_positions": len(self._positions),
        }
    
    async def stream_quotes(self, symbols: list[Symbol], callback: callable) -> None:
        """Simulate quote stream."""
        while self._connected:
            for symbol in symbols:
                base_price = Decimal("1800.00")
                noise = Decimal(str(random.uniform(-0.5, 0.5)))
                price = base_price + noise
                
                await callback({
                    "symbol": symbol,
                    "bid": price - Decimal("0.05"),
                    "ask": price + Decimal("0.05"),
                    "timestamp": datetime.utcnow()
                })
            
            await asyncio.sleep(1)

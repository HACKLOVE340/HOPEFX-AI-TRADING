"""
Paper trading broker for testing and development.
"""
import asyncio
import random
from decimal import Decimal
from datetime import datetime
from typing import Dict, Any, List
import uuid

from src.brokers.base import BaseBroker, TickData, Order, OrderSide, Position


class PaperBroker(BaseBroker):
    """
    Paper trading implementation with realistic slippage and latency simulation.
    """
    
    def __init__(self, initial_balance: Decimal = Decimal("100000.00")):
        super().__init__("paper", paper_mode=True)
        self._balance = initial_balance
        self._equity = initial_balance
        self._positions: Dict[str, Position] = {}
        self._orders: Dict[str, Dict] = {}
        self._trade_history: List[Dict] = []
        self._price_feed: Dict[str, TickData] = {}
        
        # Simulated latency (ms)
        self._latency_mean = 50
        self._latency_std = 20
        
    async def connect(self) -> bool:
        """Simulate connection."""
        await asyncio.sleep(0.1)  # Simulate connection latency
        self._connected = True
        return True
    
    async def disconnect(self) -> None:
        """Disconnect."""
        self._connected = False
    
    async def get_account_info(self) -> Dict[str, Any]:
        """Get paper account info."""
        return {
            "balance": self._balance,
            "equity": self._equity,
            "margin_used": sum(
                abs(p.quantity) * p.avg_entry_price * Decimal("0.02")  # 2% margin
                for p in self._positions.values()
            ),
            "margin_available": self._equity * Decimal("50"),  # 1:50 leverage
            "currency": "USD",
        }
    
    async def get_positions(self) -> List[Position]:
        """Get open positions."""
        return list(self._positions.values())
    
    async def place_order(self, order: Order) -> Dict[str, Any]:
        """Execute paper order with slippage simulation."""
        # Simulate latency
        latency = random.gauss(self._latency_mean, self._latency_std) / 1000
        await asyncio.sleep(max(0.001, latency))
        
        # Get current price
        current = self._price_feed.get(order.symbol)
        if not current:
            raise Exception(f"No price feed for {order.symbol}")
        
        # Apply slippage (0.1-0.5 pips for XAUUSD)
        slippage = Decimal(str(random.uniform(0.0001, 0.0005)))
        if order.side == OrderSide.BUY:
            fill_price = current.ask + slippage
        else:
            fill_price = current.bid - slippage
        
        order_id = str(uuid.uuid4())
        fill_time = datetime.utcnow()
        
        # Record trade
        trade = {
            "order_id": order_id,
            "symbol": order.symbol,
            "side": order.side,
            "quantity": order.quantity,
            "fill_price": fill_price,
            "fill_time": fill_time,
            "slippage": slippage,
        }
        self._orders[order_id] = trade
        
        # Update positions (simplified - no partial fills in paper mode)
        await self._update_position(order, fill_price)
        
        return {
            "order_id": order_id,
            "status": "FILLED",
            "filled_quantity": order.quantity,
            "avg_fill_price": fill_price,
            "commission": order.quantity * fill_price * Decimal("0.00002"),  # 0.002%
        }
    
    async def cancel_order(self, order_id: str) -> bool:
        """Cancel order."""
        if order_id in self._orders:
            self._orders[order_id]["status"] = "CANCELLED"
            return True
        return False
    
    async def get_quote(self, symbol: str) -> TickData:
        """Get current quote."""
        if symbol not in self._price_feed:
            # Generate synthetic price for XAUUSD
            base_price = Decimal("2030.00")
            noise = Decimal(str(random.uniform(-0.5, 0.5)))
            price = base_price + noise
            
            self._price_feed[symbol] = TickData(
                symbol=symbol,
                timestamp=datetime.utcnow(),
                bid=price - Decimal("0.01"),
                ask=price + Decimal("0.01"),
                volume=random.randint(100, 1000),
                source="paper"
            )
        
        return self._price_feed[symbol]
    
    async def update_price(self, symbol: str, bid: Decimal, ask: Decimal, 
                          volume: int) -> None:
        """Update price feed (called by data engine)."""
        self._price_feed[symbol] = TickData(
            symbol=symbol,
            timestamp=datetime.utcnow(),
            bid=bid,
            ask=ask,
            volume=volume,
            source="paper"
        )
        
        # Update unrealized P&L
        await self._update_unrealized_pnl()
    
    async def _update_position(self, order: Order, fill_price: Decimal) -> None:
        """Update position tracking."""
        existing = self._positions.get(order.symbol)
        
        if existing:
            # Close or modify existing
            if (existing.quantity > 0 and order.side == OrderSide.SELL) or \
               (existing.quantity < 0 and order.side == OrderSide.BUY):
                # Closing/reducing
                close_qty = min(abs(existing.quantity), order.quantity)
                pnl = (fill_price - existing.avg_entry_price) * close_qty
                if existing.quantity < 0:
                    pnl = -pnl
                
                self._balance += pnl
                remaining = existing.quantity - close_qty if existing.quantity > 0 else existing.quantity + close_qty
                
                if remaining == 0:
                    del self._positions[order.symbol]
                else:
                    existing.quantity = remaining
            else:
                # Adding to position
                total_qty = existing.quantity + order.quantity
                existing.avg_entry_price = (
                    (existing.avg_entry_price * abs(existing.quantity) + fill_price * order.quantity)
                    / total_qty
                )
                existing.quantity = total_qty
        else:
            # New position
            self._positions[order.symbol] = Position(
                symbol=order.symbol,
                quantity=order.quantity if order.side == OrderSide.BUY else -order.quantity,
                avg_entry_price=fill_price,
                unrealized_pnl=Decimal("0"),
                realized_pnl=Decimal("0"),
                open_time=datetime.utcnow()
            )
    
    async def _update_unrealized_pnl(self) -> None:
        """Recalculate unrealized P&L."""
        total_unrealized = Decimal("0")
        
        for symbol, position in self._positions.items():
            current = self._price_feed.get(symbol)
            if not current:
                continue
            
            if position.quantity > 0:
                unrealized = (current.bid - position.avg_entry_price) * position.quantity
            else:
                unrealized = (position.avg_entry_price - current.ask) * abs(position.quantity)
            
            position.unrealized_pnl = unrealized
            total_unrealized += unrealized
        
        self._equity = self._balance + total_unrealized

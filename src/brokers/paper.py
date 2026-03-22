"""
Paper trading broker with realistic slippage simulation.
"""

import asyncio
import random
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from uuid import uuid4

from src.brokers.base import Broker
from src.domain.enums import BrokerType, OrderStatus, PositionStatus, TradeDirection
from src.domain.models import Account, Order, Position, TickData


class PaperBroker(Broker):
    """
    Paper trading with realistic fill simulation.
    """
    
    def __init__(
        self,
        initial_balance: Decimal = Decimal("100000"),
        slippage_model: str = "variable"
    ):
        super().__init__(BrokerType.PAPER, {})
        
        self._balance = initial_balance
        self._equity = initial_balance
        self._positions: dict[str, Position] = {}
        self._orders: dict[str, Order] = {}
        self._slippage_model = slippage_model
        self._last_prices: dict[str, TickData] = {}
    
    async def connect(self) -> bool:
        """Simulate connection."""
        self._connected = True
        return True
    
    async def disconnect(self) -> None:
        """Disconnect."""
        self._connected = False
    
    async def get_account(self) -> Account:
        """Get paper account."""
        unrealized = sum(
            pos.unrealized_pnl for pos in self._positions.values()
        )
        
        return Account(
            broker=BrokerType.PAPER,
            account_id="PAPER_001",
            balance=self._balance,
            equity=self._equity + unrealized,
            margin_used=Decimal("0"),
            margin_available=self._balance,
            open_positions=self._positions,
            daily_pnl=Decimal("0"),
            total_pnl=self._equity - Decimal("100000")
        )
    
    async def submit_order(self, order: Order) -> Order:
        """Simulate order fill."""
        # Get current price
        if order.symbol not in self._last_prices:
            raise ValueError(f"No price data for {order.symbol}")
        
        tick = self._last_prices[order.symbol]
        
        # Apply slippage
        fill_price = self._apply_slippage(tick, order.direction)
        
        # Fill immediately for market orders
        order.broker_id = str(uuid4())
        order.status = OrderStatus.FILLED
        order.filled_quantity = order.quantity
        
        # Update positions
        await self._update_position(order, fill_price)
        
        return order
    
    def _apply_slippage(self, tick: TickData, direction: TradeDirection) -> Decimal:
        """Apply realistic slippage."""
        base_price = tick.ask if direction == TradeDirection.LONG else tick.bid
        
        # Variable slippage based on volatility
        slippage_pct = Decimal(str(random.gauss(0.0001, 0.0002)))
        slippage_pct = max(Decimal("0"), slippage_pct)  # No negative slippage
        
        if direction == TradeDirection.LONG:
            return base_price * (Decimal("1") + slippage_pct)
        else:
            return base_price * (Decimal("1") - slippage_pct)
    
    async def _update_position(self, order: Order, fill_price: Decimal) -> None:
        """Update position tracking."""
        existing = self._positions.get(order.symbol)
        
        if existing:
            # Close or reduce position
            if existing.direction != order.direction:
                # Closing logic
                pnl = (fill_price - existing.entry_price) * order.quantity
                if existing.direction == TradeDirection.SHORT:
                    pnl = -pnl
                
                self._balance += pnl
                existing.quantity -= order.quantity
                
                if existing.quantity <= 0:
                    del self._positions[order.symbol]
            else:
                # Adding to position
                existing.quantity += order.quantity
                existing.entry_price = (
                    (existing.entry_price * (existing.quantity - order.quantity) +
                     fill_price * order.quantity) / existing.quantity
                )
        else:
            # New position
            self._positions[order.symbol] = Position(
                symbol=order.symbol,
                direction=order.direction,
                entry_price=fill_price,
                quantity=order.quantity,
                status=PositionStatus.OPEN,
                opened_at=datetime.now(timezone.utc)
            )
    
    async def cancel_order(self, order_id: str) -> bool:
        """Cancel order."""
        if order_id in self._orders:
            self._orders[order_id].status = OrderStatus.CANCELLED
            return True
        return False
    
    async def get_positions(self) -> list[Position]:
        """Get positions."""
        return list(self._positions.values())
    
    async def get_quote(self, symbol: str) -> TickData:
        """Get last price."""
        return self._last_prices.get(symbol)
    
    async def stream_quotes(self, symbols: list[str], callback: callable) -> None:
        """Simulate price stream."""
        # In real implementation, would connect to data feed
        pass
    
    def update_price(self, tick: TickData) -> None:
        """Update market price (called by data feed)."""
        self._last_prices[tick.symbol] = tick
        
        # Update unrealized P&L
        for pos in self._positions.values():
            if pos.symbol == tick.symbol:
                pos.unrealized_pnl = pos.calculate_unrealized_pnl(tick.mid)

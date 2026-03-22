"""Order Management System."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import uuid4

import structlog

from src.core.events import OrderEvent, FillEvent
from src.core.types import Order, Fill, OrderStatus, OrderType, Side, Symbol, Venue
from src.execution.brokers.base import Broker

logger = structlog.get_logger()


@dataclass
class OrderState:
    """Order state tracking."""
    order: Order
    fills: list[Fill] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)


class OMS:
    """Order Management System."""
    
    def __init__(self, broker: Broker) -> None:
        self.broker = broker
        self._orders: dict[str, OrderState] = {}
        self._pending: asyncio.Queue[Order] = asyncio.Queue()
        self._lock = asyncio.Lock()
        self._running = False
    
    async def start(self) -> None:
        """Start OMS."""
        self._running = True
        await self.broker.connect()
        asyncio.create_task(self._process_loop())
        logger.info("OMS started")
    
    async def stop(self) -> None:
        """Stop OMS."""
        self._running = False
        await self.broker.disconnect()
        logger.info("OMS stopped")
    
    async def submit_order(
        self,
        symbol: Symbol,
        side: Side,
        quantity: Decimal,
        order_type: OrderType = OrderType.MARKET,
        price: Decimal | None = None,
        stop_price: Decimal | None = None,
        venue: Venue = Venue.PAPER
    ) -> Order:
        """Submit new order."""
        order = Order(
            id=str(uuid4()),
            symbol=symbol,
            side=side,
            order_type=order_type,
            quantity=quantity,
            price=price,
            stop_price=stop_price,
            venue=venue,
            client_order_id=f"cl_{uuid4().hex[:8]}"
        )
        
        await self._pending.put(order)
        logger.info(f"Order submitted: {order.id}")
        
        return order
    
    async def cancel(self, order_id: str) -> bool:
        """Cancel order."""
        async with self._lock:
            if order_id in self._orders:
                success = await self.broker.cancel_order(order_id)
                if success:
                    self._orders[order_id].order.status = OrderStatus.CANCELLED
                return success
        return False
    
    async def get_order(self, order_id: str) -> OrderState | None:
        """Get order state."""
        async with self._lock:
            return self._orders.get(order_id)
    
    async def get_all_orders(self) -> list[OrderState]:
        """Get all orders."""
        async with self._lock:
            return list(self._orders.values())
    
    async def _process_loop(self) -> None:
        """Main processing loop."""
        while self._running:
            try:
                order = await asyncio.wait_for(self._pending.get(), timeout=1.0)
                await self._execute_order(order)
            except asyncio.TimeoutError:
                continue
            except Exception as e:
                logger.error(f"OMS processing error: {e}")
    
    async def _execute_order(self, order: Order) -> None:
        """Execute order through broker."""
        async with self._lock:
            self._orders[order.id] = OrderState(order=order)
        
        # Emit pending event
        await self._emit_order_event(order, None)
        
        # Execute
        try:
            updated = await self.broker.place_order(order)
            
            async with self._lock:
                self._orders[order.id].order = updated
                self._orders[order.id].updated_at = datetime.utcnow()
            
            await self._emit_order_event(updated, order.status)
            
            # Handle fills
            if updated.status == OrderStatus.FILLED:
                await self._handle_fill(updated)
                
        except Exception as e:
            logger.error(f"Order execution failed: {e}")
            order.status = OrderStatus.REJECTED
            await self._emit_order_event(order, OrderStatus.PENDING)
    
    async def _handle_fill(self, order: Order) -> None:
        """Process fill."""
        # Create synthetic fill for tracking
        fill = Fill(
            order_id=order.id,
            fill_id=f"fill_{uuid4().hex}",
            symbol=order.symbol,
            side=order.side,
            quantity=order.filled_qty,
            price=order.avg_fill_price or Decimal("0"),
            timestamp=datetime.utcnow(),
            venue=order.venue
        )
        
        async with self._lock:
            self._orders[order.id].fills.append(fill)
        
        await self._emit_fill_event(fill)
    
    async def _emit_order_event(self, order: Order, previous: OrderStatus | None) -> None:
        """Emit order event."""
        from src.core.bus import event_bus
        from src.core.events import OrderEvent
        
        event = OrderEvent(order=order, previous_status=previous.value if previous else None)
        await event_bus.publish(event)
    
    async def _emit_fill_event(self, fill: Fill) -> None:
        """Emit fill event."""
        from src.core.bus import event_bus
        from src.core.events import FillEvent
        
        event = FillEvent(fill=fill)
        await event_bus.publish(event)

OrderManagementSystem = OMS

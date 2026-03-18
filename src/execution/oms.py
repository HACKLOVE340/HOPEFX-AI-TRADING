"""
Order Management System with partial fill handling.
"""

import asyncio
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from src.core.events import Event, OrderFilled, OrderSubmitted, get_event_bus
from src.core.logging_config import get_logger
from src.domain.enums import OrderStatus, OrderType, TimeInForce, TradeDirection
from src.domain.models import Order
from src.brokers.base import Broker

logger = get_logger(__name__)


class OrderManagementSystem:
    """
    Institutional OMS with order lifecycle management.
    """
    
    def __init__(self, broker: Broker):
        self.broker = broker
        self._orders: dict[UUID, Order] = {}
        self._event_bus = get_event_bus()
        self._lock = asyncio.Lock()
    
    async def submit_order(
        self,
        symbol: str,
        direction: TradeDirection,
        quantity: Decimal,
        order_type: OrderType = OrderType.MARKET,
        price: Decimal | None = None,
        stop_price: Decimal | None = None,
        time_in_force: TimeInForce = TimeInForce.GTC,
        strategy_id: str | None = None,
        metadata: dict[str, Any] | None = None
    ) -> Order:
        """
        Submit order with full validation.
        """
        async with self._lock:
            order = Order(
                symbol=symbol,
                direction=direction,
                order_type=order_type,
                quantity=quantity,
                price=price,
                stop_price=stop_price,
                time_in_force=time_in_force,
                strategy_id=strategy_id,
                metadata=metadata or {}
            )
            
            # Validate
            if order_type in (OrderType.LIMIT, OrderType.STOP_LIMIT) and price is None:
                raise ValueError("Limit orders require price")
            
            # Submit to broker
            try:
                filled_order = await self.broker.submit_order(order)
                self._orders[order.id] = filled_order
                
                # Emit event
                await self._event_bus.emit(
                    Event.create(
                        OrderSubmitted(
                            order_id=order.id,
                            symbol=symbol,
                            quantity=float(quantity),
                            order_type=order_type.value
                        ),
                        source="oms"
                    )
                )
                
                # Handle immediate fills
                if filled_order.is_filled:
                    await self._handle_fill(filled_order)
                
                return filled_order
                
            except Exception as e:
                order.status = OrderStatus.REJECTED
                logger.error(f"Order submission failed: {e}")
                raise
    
    async def cancel_order(self, order_id: UUID) -> bool:
        """Cancel pending order."""
        async with self._lock:
            order = self._orders.get(order_id)
            if not order:
                return False
            
            if order.status not in (OrderStatus.PENDING, OrderStatus.SUBMITTED):
                return False
            
            success = await self.broker.cancel_order(str(order_id))
            if success:
                order.status = OrderStatus.CANCELLED
            
            return success
    
    async def handle_partial_fill(
        self,
        order_id: UUID,
        fill_price: Decimal,
        fill_quantity: Decimal
    ) -> None:
        """Handle partial fill notification."""
        async with self._lock:
            order = self._orders.get(order_id)
            if not order:
                return
            
            order.filled_quantity += fill_quantity
            order.status = (
                OrderStatus.FILLED 
                if order.filled_quantity >= order.quantity 
                else OrderStatus.PARTIAL_FILL
            )
            
            await self._handle_fill(order, fill_price, fill_quantity)
    
    async def _handle_fill(
        self,
        order: Order,
        fill_price: Decimal | None = None,
        fill_quantity: Decimal | None = None
    ) -> None:
        """Process fill event."""
        price = fill_price or order.price
        qty = fill_quantity or order.quantity
        
        # Emit fill event
        await self._event_bus.emit(
            Event.create(
                OrderFilled(
                    order_id=order.id,
                    fill_price=float(price) if price else 0.0,
                    fill_quantity=float(qty),
                    commission=0.0  # Calculate based on broker fees
                ),
                source="oms"
            )
        )
        
        logger.info(
            f"Order filled: {order.id} {order.symbol} "
            f"{order.direction.value} @ {price}"
        )
    
    def get_order(self, order_id: UUID) -> Order | None:
        """Get order by ID."""
        return self._orders.get(order_id)
    
    def get_open_orders(self) -> list[Order]:
        """Get all open orders."""
        return [
            o for o in self._orders.values()
            if o.status in (OrderStatus.PENDING, OrderStatus.SUBMITTED, OrderStatus.PARTIAL_FILL)
        ]

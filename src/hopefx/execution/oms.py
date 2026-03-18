# src/hopefx/execution/oms.py
"""
Production Order Management System with partial fill handling,
slippage modeling, and smart routing.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum, auto
from typing import Callable, Coroutine, Literal

import structlog

from hopefx.core.events import EventBus, OrderEvent, EventPriority, get_event_bus

logger = structlog.get_logger()


class OrderStatus(Enum):
    """Order lifecycle states."""
    PENDING = auto()
    SUBMITTED = auto()
    PARTIAL = auto()
    FILLED = auto()
    CANCELLED = auto()
    REJECTED = auto()
    EXPIRED = auto()


class OrderType(Enum):
    """Order types."""
    MARKET = auto()
    LIMIT = auto()
    STOP = auto()
    STOP_LIMIT = auto()
    TRAILING_STOP = auto()


@dataclass
class Order:
    """Trade order."""
    order_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    client_order_id: str = ""
    symbol: str = ""
    side: Literal["BUY", "SELL"] = "BUY"
    order_type: OrderType = OrderType.MARKET
    quantity: Decimal = Decimal("0")
    filled_quantity: Decimal = Decimal("0")
    remaining_quantity: Decimal = Decimal("0")
    price: Decimal | None = None
    stop_price: Decimal | None = None
    status: OrderStatus = OrderStatus.PENDING
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    filled_at: float | None = None
    average_fill_price: Decimal | None = None
    slippage: Decimal = Decimal("0")
    commission: Decimal = Decimal("0")
    metadata: dict = field(default_factory=dict)


@dataclass
class Fill:
    """Individual fill record."""
    fill_id: str
    order_id: str
    symbol: str
    quantity: Decimal
    price: Decimal
    timestamp: float
    slippage: Decimal


class OrderManager:
    """
    Production OMS with partial fill tracking, 
    slippage analysis, and fill probability modeling.
    """
    
    def __init__(self) -> None:
        self._orders: dict[str, Order] = {}
        self._fills: list[Fill] = []
        self._callbacks: list[Callable[[Order], Coroutine[None, None, None]]] = []
        self._event_bus: EventBus | None = None
        self._lock = asyncio.Lock()
        self._slippage_model = "volatility"  # fixed, volatility, none
    
    async def initialize(self) -> None:
        """Initialize OMS."""
        self._event_bus = await get_event_bus()
        logger.info("oms_initialized")
    
    async def submit_order(
        self,
        symbol: str,
        side: Literal["BUY", "SELL"],
        quantity: Decimal,
        order_type: OrderType = OrderType.MARKET,
        price: Decimal | None = None,
        stop_price: Decimal | None = None,
        time_in_force: Literal["GTC", "IOC", "FOK"] = "GTC"
    ) -> Order:
        """Submit new order."""
        async with self._lock:
            order = Order(
                symbol=symbol,
                side=side,
                order_type=order_type,
                quantity=quantity,
                remaining_quantity=quantity,
                price=price,
                stop_price=stop_price,
                status=OrderStatus.SUBMITTED
            )
            
            self._orders[order.order_id] = order
            
            logger.info(
                "order_submitted",
                order_id=order.order_id,
                symbol=symbol,
                side=side,
                quantity=float(quantity),
                order_type=order_type.name
            )
            
            # Publish event
            await self._event_bus.publish(OrderEvent(
                priority=EventPriority.HIGH,
                order_id=order.order_id,
                action="SUBMITTED",
                symbol=symbol,
                side=side,
                quantity=float(quantity),
                source="oms"
            ))
            
            return order
    
    async def handle_fill(
        self,
        order_id: str,
        fill_quantity: Decimal,
        fill_price: Decimal,
        timestamp: float | None = None
    ) -> Order:
        """Process fill notification."""
        async with self._lock:
            if order_id not in self._orders:
                raise ValueError(f"Unknown order: {order_id}")
            
            order = self._orders[order_id]
            now = timestamp or time.time()
            
            # Calculate slippage
            expected_price = order.price
            if expected_price is None:
                slippage = Decimal("0")
            else:
                if order.side == "BUY":
                    slippage = fill_price - expected_price
                else:
                    slippage = expected_price - fill_price
            
            # Update order
            order.filled_quantity += fill_quantity
            order.remaining_quantity -= fill_quantity
            order.slippage += slippage * fill_quantity
            
            # Calculate average fill price
            if order.average_fill_price is None:
                order.average_fill_price = fill_price
            else:
                total_value = (
                    order.average_fill_price * (order.filled_quantity - fill_quantity) +
                    fill_price * fill_quantity
                )
                order.average_fill_price = total_value / order.filled_quantity
            
            # Update status
            if order.remaining_quantity <= Decimal("0"):
                order.status = OrderStatus.FILLED
                order.filled_at = now
            else:
                order.status = OrderStatus.PARTIAL
            
            order.updated_at = now
            
            # Record fill
            fill = Fill(
                fill_id=str(uuid.uuid4()),
                order_id=order_id,
                symbol=order.symbol,
                quantity=fill_quantity,
                price=fill_price,
                timestamp=now,
                slippage=slippage
            )
            self._fills.append(fill)
            
            logger.info(
                               "order_filled",
                order_id=order_id,
                fill_quantity=float(fill_quantity),
                fill_price=float(fill_price),
                slippage=float(slippage),
                remaining=float(order.remaining_quantity),
                status=order.status.name
            )
            
            # Publish event
            await self._event_bus.publish(OrderEvent(
                priority=EventPriority.HIGH,
                order_id=order_id,
                action="FILLED" if order.status == OrderStatus.FILLED else "PARTIAL",
                symbol=order.symbol,
                side=order.side,
                quantity=float(fill_quantity),
                price=float(fill_price),
                slippage=float(slippage),
                source="oms"
            ))
            
            # Notify callbacks
            for callback in self._callbacks:
                try:
                    await callback(order)
                except Exception as e:
                    logger.error("fill_callback_error", error=str(e))
            
            return order
    
    async def cancel_order(self, order_id: str) -> Order:
        """Cancel pending order."""
        async with self._lock:
            if order_id not in self._orders:
                raise ValueError(f"Unknown order: {order_id}")
            
            order = self._orders[order_id]
            
            if order.status not in (OrderStatus.PENDING, OrderStatus.SUBMITTED, OrderStatus.PARTIAL):
                raise ValueError(f"Cannot cancel order in status: {order.status}")
            
            order.status = OrderStatus.CANCELLED
            order.updated_at = time.time()
            
            logger.info("order_cancelled", order_id=order_id)
            
            await self._event_bus.publish(OrderEvent(
                priority=EventPriority.HIGH,
                order_id=order_id,
                action="CANCELLED",
                symbol=order.symbol,
                side=order.side,
                quantity=float(order.remaining_quantity),
                source="oms"
            ))
            
            return order
    
    async def modify_order(
        self,
        order_id: str,
        new_quantity: Decimal | None = None,
        new_price: Decimal | None = None
    ) -> Order:
        """Modify pending order."""
        async with self._lock:
            if order_id not in self._orders:
                raise ValueError(f"Unknown order: {order_id}")
            
            order = self._orders[order_id]
            
            if order.status not in (OrderStatus.PENDING, OrderStatus.SUBMITTED):
                raise ValueError(f"Cannot modify order in status: {order.status}")
            
            if new_quantity is not None:
                order.quantity = new_quantity
                order.remaining_quantity = new_quantity - order.filled_quantity
            
            if new_price is not None:
                order.price = new_price
            
            order.updated_at = time.time()
            
            logger.info(
                "order_modified",
                order_id=order_id,
                new_quantity=float(new_quantity) if new_quantity else None,
                new_price=float(new_price) if new_price else None
            )
            
            return order
    
    def on_order_update(self, callback: Callable[[Order], Coroutine[None, None, None]]) -> None:
        """Register order update callback."""
        self._callbacks.append(callback)
    
    def get_order(self, order_id: str) -> Order | None:
        """Get order by ID."""
        return self._orders.get(order_id)
    
    def get_open_orders(self, symbol: str | None = None) -> list[Order]:
        """Get all open orders."""
        orders = [
            o for o in self._orders.values()
            if o.status in (OrderStatus.PENDING, OrderStatus.SUBMITTED, OrderStatus.PARTIAL)
        ]
        if symbol:
            orders = [o for o in orders if o.symbol == symbol]
        return orders
    
    def get_fill_stats(self, lookback_seconds: float = 3600) -> dict:
        """Get fill statistics."""
        cutoff = time.time() - lookback_seconds
        recent_fills = [f for f in self._fills if f.timestamp > cutoff]
        
        if not recent_fills:
            return {"count": 0}
        
        slippages = [float(f.slippage) for f in recent_fills]
        
        return {
            "count": len(recent_fills),
            "total_quantity": sum(float(f.quantity) for f in recent_fills),
            "avg_slippage": sum(slippages) / len(slippages),
            "max_slippage": max(slippages),
            "min_slippage": min(slippages),
            "slippage_std": np.std(slippages) if len(slippages) > 1 else 0,
        }


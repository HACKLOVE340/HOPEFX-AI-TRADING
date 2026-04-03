# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
# execution/oms.py
"""
HOPEFX Order Management System
Institutional-grade OMS with order lifecycle management
"""

import asyncio
import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
UTC = timezone.utc
from decimal import Decimal
from enum import Enum, auto

logger = logging.getLogger(__name__)


class OrderStatus(Enum):
    CREATED = auto()
    PENDING_NEW = auto()
    NEW = auto()
    PARTIALLY_FILLED = auto()
    FILLED = auto()
    PENDING_CANCEL = auto()
    CANCELLED = auto()
    REJECTED = auto()
    EXPIRED = auto()


class TimeInForce(Enum):
    GTC = "GTC"  # Good Till Cancelled
    IOC = "IOC"  # Immediate Or Cancel
    FOK = "FOK"  # Fill Or Kill
    GTD = "GTD"  # Good Till Date
    DAY = "DAY"  # Day Order


@dataclass
class Order:
    """Complete order representation"""

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    client_order_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    symbol: str = "XAUUSD"
    side: str = "BUY"  # BUY or SELL
    order_type: str = "LIMIT"  # MARKET, LIMIT, STOP, STOP_LIMIT
    quantity: Decimal = Decimal(0)
    price: Decimal | None = None
    stop_price: Decimal | None = None
    time_in_force: TimeInForce = TimeInForce.GTC
    status: OrderStatus = OrderStatus.CREATED
    filled_quantity: Decimal = Decimal(0)
    avg_fill_price: Decimal | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    expires_at: datetime | None = None
    parent_order_id: str | None = None  # For OCO, bracket orders
    child_orders: list[str] = field(default_factory=list)
    strategy_id: str = "unknown"
    tags: list[str] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)

    @property
    def remaining_quantity(self) -> Decimal:
        return self.quantity - self.filled_quantity

    @property
    def is_active(self) -> bool:
        return self.status in [
            OrderStatus.PENDING_NEW,
            OrderStatus.NEW,
            OrderStatus.PARTIALLY_FILLED,
            OrderStatus.PENDING_CANCEL,
        ]

    def can_fill(self, fill_qty: Decimal, fill_price: Decimal) -> bool:
        """Validate fill against order constraints"""
        if self.status not in [OrderStatus.NEW, OrderStatus.PARTIALLY_FILLED]:
            return False

        if fill_qty > self.remaining_quantity:
            return False

        # Price checks for limit orders
        if self.order_type == "LIMIT":
            if self.side == "BUY" and fill_price > self.price:
                return False
            if self.side == "SELL" and fill_price < self.price:
                return False

        return True


class OrderLifecycleManager:
    """
    Manages complete order lifecycle with state machine.
    Ensures valid state transitions and audit logging.
    """

    VALID_TRANSITIONS = {
        OrderStatus.CREATED: {OrderStatus.PENDING_NEW, OrderStatus.CANCELLED},
        OrderStatus.PENDING_NEW: {
            OrderStatus.NEW,
            OrderStatus.REJECTED,
            OrderStatus.CANCELLED,
        },
        OrderStatus.NEW: {
            OrderStatus.PARTIALLY_FILLED,
            OrderStatus.FILLED,
            OrderStatus.PENDING_CANCEL,
            OrderStatus.EXPIRED,
        },
        OrderStatus.PARTIALLY_FILLED: {OrderStatus.FILLED, OrderStatus.PENDING_CANCEL},
        OrderStatus.PENDING_CANCEL: {OrderStatus.CANCELLED, OrderStatus.FILLED},
        OrderStatus.CANCELLED: set(),
        OrderStatus.FILLED: set(),
        OrderStatus.REJECTED: set(),
        OrderStatus.EXPIRED: set(),
    }

    def __init__(self, event_bus=None, broker=None):
        self.orders: dict[str, Order] = {}
        self.active_orders: set[str] = set()
        self.order_history: list[dict] = []
        self.event_bus = event_bus
        self._broker = broker  # BrokerConnector instance; None = paper/backtest mode
        self._callbacks: dict[OrderStatus, list[Callable]] = {status: [] for status in OrderStatus}

    def register_callback(self, status: OrderStatus, callback: Callable):
        """Register callback for status changes"""
        self._callbacks[status].append(callback)

    def create_order(self, **kwargs) -> Order:
        """Create new order"""
        order = Order(**kwargs)
        self.orders[order.id] = order
        self._transition(order, OrderStatus.CREATED)
        return order

    def submit_order(self, order_id: str) -> bool:
        """Submit order to market.

        Kill switch is checked first — before any state mutation — so that
        orders submitted directly to the OMS (bypassing the API route layer)
        are also blocked when trading is halted.  This provides defense-in-depth
        beyond the API-level kill switch check.
        """
        # ── Kill switch: defense-in-depth gate ───────────────────────────────
        # Check unconditionally so direct OMS callers cannot bypass the halt.
        try:
            from kill_switch import KillSwitch as _KillSwitch

            _ks = _KillSwitch()
            if _ks.is_active():
                logger.critical(
                    "OMS.submit_order BLOCKED by kill switch (order=%s reason=%r)",
                    order_id,
                    _ks.reason,
                )
                return False
        except Exception as _ks_exc:
            # Kill switch check itself failed — fail closed: block the order.
            logger.critical(
                "OMS.submit_order: kill switch check raised %s — blocking order %s",
                _ks_exc,
                order_id,
            )
            return False
        # ─────────────────────────────────────────────────────────────────────

        order = self.orders.get(order_id)
        if not order:
            return False

        success = self._transition(order, OrderStatus.PENDING_NEW)
        if success:
            # Simulate async submission
            _t = asyncio.create_task(self._async_submit(order))
            _t.add_done_callback(lambda _: None)
        return success

    async def _async_submit(self, order: Order):
        """Async order submission to broker.

        Delegates to the registered broker connector if available.
        Transitions to NEW on acceptance; REJECTED on broker refusal.
        """
        broker = getattr(self, "_broker", None)
        if broker is None:
            # No broker wired — accept immediately (paper/backtest mode)
            self._transition(order, OrderStatus.NEW)
            self.active_orders.add(order.id)
            return

        try:
            result = await broker.place_order(
                {
                    "symbol": order.symbol,
                    "side": order.side.value if hasattr(order.side, "value") else str(order.side),
                    "quantity": float(order.quantity),
                    "order_type": order.order_type.value
                    if hasattr(order.order_type, "value")
                    else str(order.order_type),
                    "price": float(order.price) if order.price else None,
                    "client_order_id": order.client_order_id,
                }
            )
            status = (result or {}).get("status", "")
            if str(status).lower() in ("rejected", "error", "failed"):
                reason = (result or {}).get("reason", "BROKER_REJECTED")
                self._transition(order, OrderStatus.REJECTED, reason=reason)
            else:
                self._transition(order, OrderStatus.NEW)
                self.active_orders.add(order.id)
        except Exception as exc:
            logger.error("OMS broker submit failed for %s: %s", order.id, exc)
            self._transition(order, OrderStatus.REJECTED, reason=str(exc))

    def fill_order(self, order_id: str, fill_qty: Decimal, fill_price: Decimal) -> bool:
        """Process order fill"""
        order = self.orders.get(order_id)
        if not order or not order.can_fill(fill_qty, fill_price):
            return False

        # Update fill
        prev_filled = order.filled_quantity
        order.filled_quantity += fill_qty

        # Update average price
        if order.avg_fill_price is None:
            order.avg_fill_price = fill_price
        else:
            total_value = (prev_filled * order.avg_fill_price) + (fill_qty * fill_price)
            order.avg_fill_price = total_value / order.filled_quantity

        order.updated_at = datetime.now(UTC)

        # Determine new status
        if order.filled_quantity >= order.quantity:
            new_status = OrderStatus.FILLED
            self.active_orders.discard(order.id)
        else:
            new_status = OrderStatus.PARTIALLY_FILLED

        return self._transition(
            order,
            new_status,
            fill_qty=fill_qty,
            fill_price=fill_price,
        )

    def cancel_order(self, order_id: str) -> bool:
        """Request order cancellation"""
        order = self.orders.get(order_id)
        if not order or not order.is_active:
            return False

        return self._transition(order, OrderStatus.PENDING_CANCEL)

    def expire_orders(self):
        """Expire GTD and DAY orders"""
        now = datetime.now(UTC)
        for order_id in list(self.active_orders):
            order = self.orders[order_id]
            if order.expires_at and now > order.expires_at:
                self._transition(order, OrderStatus.EXPIRED)
                self.active_orders.discard(order_id)

    def _transition(self, order: Order, new_status: OrderStatus, **context) -> bool:
        """Execute valid state transition"""
        current = order.status

        if new_status not in self.VALID_TRANSITIONS.get(current, set()):
            logger.warning("Invalid transition: %s -> %s", current.name, new_status.name)
            return False

        # Execute transition
        order.status = new_status
        order.updated_at = datetime.now(UTC)

        # Log
        event = {
            "timestamp": datetime.now(UTC).isoformat(),
            "order_id": order.id,
            "from_status": current.name,
            "to_status": new_status.name,
            "context": context,
        }
        self.order_history.append(event)

        # Emit event
        if self.event_bus:
            from core.event_bus import DomainEvent

            asyncio.create_task(
                self.event_bus.publish(
                    DomainEvent.create("ORDER_STATUS_CHANGE", "oms", event),
                ),
            )

        # Callbacks
        for callback in self._callbacks.get(new_status, []):
            try:
                callback(order, context)
            except Exception as e:
                logger.error(
                    "OMS callback error for order %s status %s: %s",
                    order.id[:8],
                    new_status.name,
                    e,
                    exc_info=True,
                )

        logger.info("Order %s: %s -> %s", order.id[:8], current.name, new_status.name)
        return True

    def get_order_book(self, symbol: str) -> dict:
        """Get current order book for symbol"""
        buys = []
        sells = []

        for order_id in self.active_orders:
            order = self.orders[order_id]
            if order.symbol != symbol:
                continue

            entry = {
                "id": order.id[:8],
                "price": float(order.price) if order.price else None,
                "quantity": float(order.remaining_quantity),
                "time_in_force": order.time_in_force.value,
            }

            if order.side == "BUY":
                buys.append(entry)
            else:
                sells.append(entry)

        return {
            "symbol": symbol,
            "bids": sorted(buys, key=lambda x: x["price"] or 0, reverse=True),
            "asks": sorted(sells, key=lambda x: x["price"] or float("inf")),
            "timestamp": datetime.now(UTC).isoformat(),
        }


class ComplexOrderManager:
    """
    Handles complex order types: OCO, Bracket, Iceberg, TWAP
    """

    def __init__(self, oms: OrderLifecycleManager):
        self.oms = oms

    def create_oco(self, orders: list[Order]) -> str:
        """
        One-Cancels-Other order.
        When one fills, others are automatically cancelled.
        """
        parent_id = str(uuid.uuid4())

        for order in orders:
            order.parent_order_id = parent_id
            order.tags.append("OCO")
            self.oms.create_order(**order.__dict__)

        # Register callback
        self.oms.register_callback(
            OrderStatus.FILLED,
            lambda o, ctx: self._cancel_siblings(o),
        )

        return parent_id

    def _cancel_siblings(self, filled_order: Order):
        """Cancel other orders in OCO group"""
        if not filled_order.parent_order_id:
            return

        for order in self.oms.orders.values():
            if (
                order.parent_order_id == filled_order.parent_order_id
                and order.id != filled_order.id
                and order.is_active
            ):
                self.oms.cancel_order(order.id)

    def create_bracket(
        self,
        entry: Order,
        take_profit: Decimal,
        stop_loss: Decimal,
    ) -> str:
        """
        Bracket order: Entry + Take Profit + Stop Loss.
        When entry fills, TP and SL are placed as OCO.
        """
        bracket_id = str(uuid.uuid4())
        entry.parent_order_id = bracket_id
        entry.tags.append("BRACKET_ENTRY")

        # Create entry
        self.oms.create_order(**entry.__dict__)

        # Register callback to place TP/SL on fill
        self.oms.register_callback(
            OrderStatus.FILLED,
            lambda o, ctx: (
                self._place_bracket_exits(o, take_profit, stop_loss, bracket_id) if "BRACKET_ENTRY" in o.tags else None
            ),
        )

        return bracket_id

    def _place_bracket_exits(
        self,
        entry: Order,
        tp: Decimal,
        sl: Decimal,
        bracket_id: str,
    ):
        """Place take profit and stop loss as OCO"""
        # Create TP order
        tp_side = "SELL" if entry.side == "BUY" else "BUY"
        tp_order = Order(
            symbol=entry.symbol,
            side=tp_side,
            order_type="LIMIT",
            quantity=entry.filled_quantity,
            price=tp,
            parent_order_id=bracket_id,
            tags=["BRACKET_TP"],
        )

        # Create SL order
        sl_order = Order(
            symbol=entry.symbol,
            side=tp_side,
            order_type="STOP",
            quantity=entry.filled_quantity,
            stop_price=sl,
            parent_order_id=bracket_id,
            tags=["BRACKET_SL"],
        )

        # Submit as OCO
        self.create_oco([tp_order, sl_order])

    def create_iceberg(
        self,
        total_quantity: Decimal,
        display_size: Decimal,
        symbol: str,
        side: str,
        price: Decimal,
    ) -> str:
        """
        Iceberg order: Only shows display_size at a time.
        When slice fills, next slice is revealed.
        """
        str(uuid.uuid4())

        # Create parent order (invisible)
        parent = Order(
            symbol=symbol,
            side=side,
            order_type="LIMIT",
            quantity=total_quantity,
            price=price,
            tags=["ICEBERG_PARENT"],
            metadata={"display_size": float(display_size), "revealed": 0},
        )
        parent_id = self.oms.create_order(**parent.__dict__).id

        # Reveal first slice
        self._reveal_slice(parent_id, display_size)

        # Register callback to reveal next slice on fill
        self.oms.register_callback(
            OrderStatus.PARTIALLY_FILLED,
            lambda o, ctx: (
                self._check_reveal_next(o, parent_id, display_size) if o.parent_order_id == parent_id else None
            ),
        )

        return parent_id

    def _reveal_slice(self, parent_id: str, display_size: Decimal):
        """Reveal next slice of iceberg"""
        parent = self.oms.orders.get(parent_id)
        if not parent:
            return

        revealed = parent.metadata.get("revealed", 0)
        remaining = parent.quantity - Decimal(str(revealed))

        if remaining <= 0:
            return

        slice_size = min(display_size, remaining)

        slice_order = Order(
            symbol=parent.symbol,
            side=parent.side,
            order_type="LIMIT",
            quantity=slice_size,
            price=parent.price,
            parent_order_id=parent_id,
            time_in_force=TimeInForce.GTC,
            tags=["ICEBERG_SLICE"],
        )

        child_id = self.oms.create_order(**slice_order.__dict__).id
        parent.child_orders.append(child_id)
        parent.metadata["revealed"] = revealed + float(slice_size)

        self.oms.submit_order(child_id)

    def _check_reveal_next(
        self,
        filled_slice: Order,
        parent_id: str,
        display_size: Decimal,
    ):
        """Check if we should reveal next iceberg slice"""
        # If slice is fully filled, reveal next
        if filled_slice.filled_quantity >= filled_slice.quantity:
            self._reveal_slice(parent_id, display_size)

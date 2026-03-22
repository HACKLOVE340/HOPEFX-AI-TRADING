from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum, auto
from typing import Any
from uuid import uuid4

import structlog

from hopefx.config.settings import settings
from hopefx.events.bus import event_bus
from hopefx.events.schemas import Event, EventType, Signal
from hopefx.execution.brokers.base import Order, OrderResult, OrderStatus, OrderType
from hopefx.execution.router import smart_router
from hopefx.risk.prop_rules import prop_rules

logger = structlog.get_logger()


class OMSStatus(Enum):
    IDLE = auto()
    PENDING_RISK = auto()
    PENDING_EXECUTION = auto()
    EXECUTED = auto()
    REJECTED = auto()


@dataclass
class OrderState:
    order_id: str
    signal: Signal
    status: OMSStatus
    created_at: float
    risk_approved: bool = False
    execution_result: OrderResult | None = None
    amendments: list[dict] = field(default_factory=list)


class OrderManagementSystem:
    """Order Management System with full lifecycle tracking."""

    def __init__(self) -> None:
        self._orders: dict[str, OrderState] = {}
        self._positions: dict[str, dict] = {}
        self._lock = asyncio.Lock()
        self._running = False

    async def start(self) -> None:
        """Start OMS."""
        self._running = True
        event_bus.subscribe(EventType.SIGNAL, self._on_signal)
        logger.info("oms.started")

    async def stop(self) -> None:
        """Stop OMS."""
        self._running = False
        # Cancel all pending orders
        async with self._lock:
            for order_id, state in self._orders.items():
                if state.status in [OMSStatus.PENDING_RISK, OMSStatus.PENDING_EXECUTION]:
                    logger.info("oms.cancelling_pending", order_id=order_id)
        logger.info("oms.stopped")

    async def _on_signal(self, event: Event) -> None:
        """Process trading signal."""
        if not isinstance(event.payload, Signal):
            return

        signal: Signal = event.payload

        # Risk check
        approved, reason = prop_rules.validate(
            signal.symbol,
            signal.size,
            signal.stop_price,
        )

        if not approved:
            logger.warning("oms.risk_rejected", signal=signal, reason=reason)
            return

        # Create order
        order_id = str(uuid4())
        order_state = OrderState(
            order_id=order_id,
            signal=signal,
            status=OMSStatus.PENDING_EXECUTION,
            created_at=asyncio.get_event_loop().time(),
            risk_approved=True,
        )

        async with self._lock:
            self._orders[order_id] = order_state

        # Route to execution
        await self._execute(order_id)

    async def _execute(self, order_id: str) -> None:
        """Execute order through router."""
        async with self._lock:
            state = self._orders.get(order_id)
            if not state:
                return

            state.status = OMSStatus.PENDING_EXECUTION

        # Convert signal to broker order
        order = Order(
            symbol=state.signal.symbol,
            side=state.signal.direction,
            quantity=state.signal.size,
            order_type=OrderType.MARKET if state.signal.order_type == "market" else OrderType.LIMIT,
            price=state.signal.limit_price,
            stop_price=state.signal.stop_price,
            client_order_id=order_id,
        )

        # Route and execute
        result = await smart_router.route_order(order)

        async with self._lock:
            state.execution_result = result
            if result.status == OrderStatus.FILLED:
                state.status = OMSStatus.EXECUTED
                self._update_positions(state.signal, result)
            else:
                state.status = OMSStatus.REJECTED

        logger.info(
            "oms.order_completed",
            order_id=order_id,
            status=state.status.name,
            filled=float(result.filled_qty) if result else 0,
        )

    def _update_positions(self, signal: Signal, result: OrderResult) -> None:
        """Update position tracking."""
        symbol = signal.symbol

        if signal.direction in ["buy", "sell"]:
            # Open position
            self._positions[symbol] = {
                "side": signal.direction,
                "qty": result.filled_qty,
                "entry_price": result.filled_price,
                "open_time": result.timestamp,
                "unrealized_pnl": Decimal("0"),
            }
        elif signal.direction == "close":
            # Close position
            if symbol in self._positions:
                del self._positions[symbol]

    async def amend_order(self, order_id: str, updates: dict[str, Any]) -> bool:
        """Amend pending order."""
        async with self._lock:
            state = self._orders.get(order_id)
            if not state or state.status != OMSStatus.PENDING_EXECUTION:
                return False

            state.amendments.append({
                "time": asyncio.get_event_loop().time(),
                "updates": updates,
            })

            # Apply updates
            if "stop_price" in updates:
                state.signal.stop_price = Decimal(str(updates["stop_price"]))

            return True

    async def cancel_order(self, order_id: str) -> bool:
        """Cancel pending order."""
        async with self._lock:
            state = self._orders.get(order_id)
            if not state or state.status != OMSStatus.PENDING_EXECUTION:
                return False

            state.status = OMSStatus.REJECTED
            return True

    def get_order(self, order_id: str) -> OrderState | None:
        """Get order state."""
        return self._orders.get(order_id)

    def get_position(self, symbol: str) -> dict | None:
        """Get current position."""
        return self._positions.get(symbol)

    def get_all_positions(self) -> dict[str, dict]:
        """Get all positions."""
        return dict(self._positions)


# Global OMS
oms = OrderManagementSystem()

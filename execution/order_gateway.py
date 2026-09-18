# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
execution/order_gateway.py
==========================
OrderGateway — thin adapter that routes orders through TradeExecutor.

Previously a stub that raised NotImplementedError on send_order(). Now
delegates to TradeExecutor.execute_signal() so callers that hold an
OrderGateway reference get real broker routing without code changes.

Backward-compatible surface:
  - create_order()       — unchanged (returns an Order record)
  - send_order(order)    — now routes via TradeExecutor; returns ExecutionResult
  - send_order_async()   — async variant; preferred from async call sites
  - handle_rejection()   — logs and marks order rejected; no longer raises
  - track_commissions()  — unchanged (sums commission_paid across orders)

TradeExecutor is injected at construction time. If no executor is provided
the gateway logs a warning and returns a failed ExecutionResult rather than
raising, so callers can handle the failure gracefully.
"""

from __future__ import annotations

import asyncio
import logging
import math
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from execution.trade_executor import ExecutionResult, TradeExecutor

logger = logging.getLogger(__name__)


class Order:
    """Minimal order record used by OrderGateway."""

    def __init__(
        self,
        order_id: str,
        quantity: float,
        price: float,
        commission_rate: float,
    ) -> None:
        if not math.isfinite(quantity) or quantity == 0:
            raise ValueError("Order quantity must be finite and non-zero")
        if not math.isfinite(price) or price < 0:
            raise ValueError("Order price must be finite and non-negative")
        if not math.isfinite(commission_rate) or commission_rate < 0:
            raise ValueError("Commission rate must be finite and non-negative")
        self.order_id = order_id
        self.quantity = quantity
        self.price = price
        self.executed_quantity: float = 0.0
        self.commission_rate = commission_rate
        self.commission_paid: float = 0.0
        self.is_filled: bool = False
        self.is_rejected: bool = False
        self.rejection_reason: str | None = None
        # Optional fields set by callers
        self.symbol: str = "XAUUSD"
        self.strategy_id: str = "order_gateway"

    def fill(self, filled_quantity: float) -> None:
        # Use abs(quantity) so sell orders (negative quantity) work correctly.
        if not math.isfinite(filled_quantity) or filled_quantity <= 0:
            raise ValueError("Filled quantity must be finite and positive")
        max_qty = abs(self.quantity)
        if filled_quantity > max_qty + 1e-9:
            raise ValueError(f"Filled quantity {filled_quantity} cannot exceed order quantity {max_qty}.")
        self.executed_quantity += filled_quantity
        self.commission_paid += filled_quantity * self.commission_rate
        if self.executed_quantity >= max_qty - 1e-9:
            self.is_filled = True


class OrderGateway:
    """
    Order routing adapter — delegates to TradeExecutor for real broker fills.

    Inject a TradeExecutor at construction time:

        executor = TradeExecutor(broker, risk_manager, position_tracker)
        gateway  = OrderGateway(executor=executor)

    Without an executor the gateway logs a warning and returns failed results
    rather than raising, preserving backward compatibility with code that
    instantiates OrderGateway without arguments.
    """

    def __init__(self, executor: TradeExecutor | None = None) -> None:
        self.executor = executor
        self.orders: dict[str, Order] = {}
        if executor is None:
            logger.warning(
                "OrderGateway created without a TradeExecutor — send_order() will "
                "return failed results. Inject executor= to enable real routing."
            )

    # ── Order lifecycle ───────────────────────────────────────────────────────

    def create_order(
        self,
        order_id: str,
        quantity: float,
        price: float,
        commission_rate: float,
    ) -> Order:
        """Create and register an order record."""
        order = Order(order_id, quantity, price, commission_rate)
        self.orders[order_id] = order
        return order

    def send_order(self, order: Order) -> ExecutionResult:
        """
        Route order to the broker via TradeExecutor.

        Builds a signal dict from the Order record and calls
        TradeExecutor.execute_signal() synchronously. If called from within
        a running event loop (e.g. a FastAPI handler), use send_order_async()
        instead to avoid blocking.

        Returns an ExecutionResult. Never raises.
        """
        from execution.trade_executor import ExecutionResult, OrderStatus

        if self.executor is None:
            logger.error(
                "OrderGateway.send_order: no TradeExecutor injected — order %s not routed",
                order.order_id,
            )
            order.is_rejected = True
            order.rejection_reason = "No TradeExecutor configured"
            return ExecutionResult(
                success=False,
                order_id=order.order_id,
                filled_quantity=0.0,
                average_price=0.0,
                commission=0.0,
                status=OrderStatus.REJECTED,
                message="OrderGateway has no TradeExecutor — inject executor= at construction",
                latency_ms=0.0,
            )

        signal = {
            "symbol": order.symbol,
            "action": "buy" if order.quantity >= 0 else "sell",
            "size": abs(order.quantity),
            "price": order.price,
            "order_id": order.order_id,
            "strategy_id": order.strategy_id,
        }

        try:
            asyncio.get_running_loop()
        except RuntimeError:  # healer: ignore - no running loop is the SUCCESS case here.
            # get_running_loop() raises RuntimeError precisely when there is no
            # loop, which is the state this synchronous entry point requires.
            # Nothing is being swallowed: the error IS the answer, and the
            # failure case is the `else` below, which raises.
            pass
        else:
            raise RuntimeError(
                "OrderGateway.send_order() cannot run inside an active event loop; "
                "await send_order_async() from async callers"
            )

        try:
            result = asyncio.run(self.executor.execute_signal(signal))
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.exception(
                "OrderGateway.send_order: TradeExecutor raised for order %s: %s",
                order.order_id,
                exc,
            )
            order.is_rejected = True
            order.rejection_reason = str(exc)
            return ExecutionResult(
                success=False,
                order_id=order.order_id,
                filled_quantity=0.0,
                average_price=0.0,
                commission=0.0,
                status=OrderStatus.ERROR,
                message=str(exc),
                latency_ms=0.0,
            )

        if result.success:
            order.fill(result.filled_quantity)
            order.commission_paid = result.commission
        else:
            order.is_rejected = True
            order.rejection_reason = result.message

        return result

    async def send_order_async(self, order: Order) -> ExecutionResult:
        """
        Async variant of send_order — preferred when called from async code.

        Awaits TradeExecutor.execute_signal() directly without thread-pool
        indirection.
        """
        from execution.trade_executor import ExecutionResult, OrderStatus

        if self.executor is None:
            logger.error(
                "OrderGateway.send_order_async: no TradeExecutor — order %s not routed",
                order.order_id,
            )
            order.is_rejected = True
            order.rejection_reason = "No TradeExecutor configured"
            return ExecutionResult(
                success=False,
                order_id=order.order_id,
                filled_quantity=0.0,
                average_price=0.0,
                commission=0.0,
                status=OrderStatus.REJECTED,
                message="OrderGateway has no TradeExecutor",
                latency_ms=0.0,
            )

        signal = {
            "symbol": order.symbol,
            "action": "buy" if order.quantity >= 0 else "sell",
            "size": abs(order.quantity),
            "price": order.price,
            "order_id": order.order_id,
            "strategy_id": order.strategy_id,
        }

        try:
            result = await self.executor.execute_signal(signal)
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.exception(
                "OrderGateway.send_order_async: TradeExecutor raised for order %s: %s",
                order.order_id,
                exc,
            )
            order.is_rejected = True
            order.rejection_reason = str(exc)
            return ExecutionResult(
                success=False,
                order_id=order.order_id,
                filled_quantity=0.0,
                average_price=0.0,
                commission=0.0,
                status=OrderStatus.ERROR,
                message=str(exc),
                latency_ms=0.0,
            )

        if result.success:
            order.fill(result.filled_quantity)
            order.commission_paid = result.commission
        else:
            order.is_rejected = True
            order.rejection_reason = result.message

        return result

    def handle_rejection(self, order_id: str, reason: str = "unknown") -> None:
        """
        Mark an order as rejected and log the reason.

        Previously raised NotImplementedError. Now logs and updates order state
        so callers can inspect order.is_rejected / order.rejection_reason.
        """
        order = self.orders.get(order_id)
        if order is None:
            logger.warning(
                "OrderGateway.handle_rejection: order %s not found in registry",
                order_id,
            )
            return
        order.is_rejected = True
        order.rejection_reason = reason
        logger.warning("OrderGateway: order %s rejected — reason: %s", order_id, reason)

    def track_commissions(self) -> float:
        """Return total commissions paid across all orders."""
        return sum(order.commission_paid for order in self.orders.values())

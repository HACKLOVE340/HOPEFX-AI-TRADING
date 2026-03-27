# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
execution/order_gateway.py
==========================
OrderGateway is a placeholder class retained for import compatibility.
It is NOT connected to any broker and must NOT be used for live or paper
trading. All real order execution goes through TradeExecutor → BrokerConnector.

Any call to send_order() raises NotImplementedError immediately so
accidental usage is caught at development time rather than silently
producing fake fills.
"""

import logging

logger = logging.getLogger(__name__)


class Order:
    """Minimal order record used by OrderGateway."""

    def __init__(self, order_id, quantity, price, commission_rate):
        self.order_id = order_id
        self.quantity = quantity
        self.price = price
        self.executed_quantity = 0
        self.commission_rate = commission_rate
        self.commission_paid = 0.0
        self.is_filled = False

    def fill(self, filled_quantity):
        if filled_quantity > self.quantity:
            raise ValueError("Filled quantity cannot exceed order quantity.")
        self.executed_quantity += filled_quantity
        self.commission_paid += filled_quantity * self.commission_rate
        if self.executed_quantity >= self.quantity:
            self.is_filled = True


class OrderGateway:
    """
    Stub gateway — NOT connected to any broker.

    Use TradeExecutor (execution/trade_executor.py) for all real order
    routing. This class exists only to avoid import errors in code that
    references it by name.
    """

    def __init__(self):
        self.orders = {}
        logger.warning(
            "OrderGateway instantiated — this class is a stub and does not "
            "route orders to any broker. Use TradeExecutor instead."
        )

    def create_order(self, order_id, quantity, price, commission_rate):
        order = Order(order_id, quantity, price, commission_rate)
        self.orders[order_id] = order
        return order

    def send_order(self, order):
        raise NotImplementedError(
            "OrderGateway.send_order() is not implemented. "
            "Route orders through TradeExecutor → BrokerConnector instead."
        )

    def handle_rejection(self, order_id):
        raise NotImplementedError(
            "OrderGateway.handle_rejection() is not implemented. "
            "Use TradeExecutor for real order lifecycle management."
        )

    def track_commissions(self):
        total_commissions = sum(order.commission_paid for order in self.orders.values())
        return total_commissions

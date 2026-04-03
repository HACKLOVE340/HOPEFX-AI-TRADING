# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
tests/test_order_gateway_integration.py
========================================
Integration tests for the OrderGateway → TradeExecutor delegation chain.

Covers the four failure conditions identified in Section 4.3:
1. Broker exception (timeout, connection error)
2. Partial fill
3. Order rejection (pre-trade gate, risk manager)
4. Kill switch active

Each test uses mocks to isolate the delegation chain from real broker
and risk manager dependencies.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from execution.order_gateway import Order, OrderGateway
from execution.trade_executor import ExecutionResult, OrderStatus, TradeExecutor

# ─────────────────────────────────────────────────────────────────────────────
# Helpers / fixtures
# ─────────────────────────────────────────────────────────────────────────────


def _make_order(
    order_id: str = "ORD-001",
    quantity: float = 0.1,
    price: float = 3300.0,
    commission_rate: float = 0.0001,
    symbol: str = "XAUUSD",
) -> Order:
    o = Order(order_id, quantity, price, commission_rate)
    o.symbol = symbol
    o.strategy_id = "test_strategy"
    return o


def _filled_result(order_id: str = "ORD-001", qty: float = 0.1, price: float = 3300.0) -> ExecutionResult:
    return ExecutionResult(
        success=True,
        order_id=order_id,
        filled_quantity=qty,
        average_price=price,
        commission=0.33,
        status=OrderStatus.FILLED,
        message="Order filled",
        latency_ms=12.5,
    )


def _rejected_result(order_id: str = "ORD-001", reason: str = "Insufficient margin") -> ExecutionResult:
    return ExecutionResult(
        success=False,
        order_id=order_id,
        filled_quantity=0.0,
        average_price=0.0,
        commission=0.0,
        status=OrderStatus.REJECTED,
        message=reason,
        latency_ms=5.0,
    )


def _partial_result(order_id: str = "ORD-001", filled: float = 0.05, price: float = 3300.0) -> ExecutionResult:
    return ExecutionResult(
        success=True,
        order_id=order_id,
        filled_quantity=filled,
        average_price=price,
        commission=0.165,
        status=OrderStatus.PARTIAL,
        message="Order partially filled",
        latency_ms=18.0,
    )


@pytest.fixture
def mock_executor() -> MagicMock:
    """Return a MagicMock TradeExecutor with execute_signal as AsyncMock."""
    executor = MagicMock(spec=TradeExecutor)
    executor.execute_signal = AsyncMock()
    return executor


@pytest.fixture
def gateway(mock_executor) -> OrderGateway:
    return OrderGateway(executor=mock_executor)


# ─────────────────────────────────────────────────────────────────────────────
# 1. Successful fill
# ─────────────────────────────────────────────────────────────────────────────


class TestSuccessfulFill:
    def test_send_order_delegates_to_executor(self, gateway, mock_executor):
        """send_order() calls TradeExecutor.execute_signal with correct signal dict."""
        order = _make_order()
        mock_executor.execute_signal.return_value = _filled_result()

        result = gateway.send_order(order)

        assert result.success is True
        assert result.status == OrderStatus.FILLED
        assert order.is_filled is True
        assert order.executed_quantity == pytest.approx(0.1)

        # Verify signal dict passed to executor
        call_args = mock_executor.execute_signal.call_args[0][0]
        assert call_args["symbol"] == "XAUUSD"
        assert call_args["action"] == "buy"
        assert call_args["size"] == pytest.approx(0.1)
        assert call_args["order_id"] == "ORD-001"

    @pytest.mark.asyncio
    async def test_send_order_async_delegates_to_executor(self, gateway, mock_executor):
        """send_order_async() awaits TradeExecutor.execute_signal directly."""
        order = _make_order()
        mock_executor.execute_signal.return_value = _filled_result()

        result = await gateway.send_order_async(order)

        assert result.success is True
        assert result.status == OrderStatus.FILLED
        assert order.is_filled is True

    def test_sell_order_maps_action_correctly(self, gateway, mock_executor):
        """Negative quantity maps to 'sell' action; size is abs(quantity)."""
        order = _make_order(quantity=-0.1)
        mock_executor.execute_signal.return_value = _filled_result(qty=0.1)

        result = gateway.send_order(order)

        assert result.success is True
        assert order.is_filled is True
        call_args = mock_executor.execute_signal.call_args[0][0]
        assert call_args["action"] == "sell"
        assert call_args["size"] == pytest.approx(0.1)  # abs(quantity)


# ─────────────────────────────────────────────────────────────────────────────
# 2. Broker exception (timeout, connection error)
# ─────────────────────────────────────────────────────────────────────────────


class TestBrokerException:
    def test_broker_timeout_returns_error_result(self, gateway, mock_executor):
        """When TradeExecutor raises asyncio.TimeoutError, send_order returns ERROR."""
        order = _make_order()
        mock_executor.execute_signal.side_effect = TimeoutError("broker timeout")

        result = gateway.send_order(order)

        assert result.success is False
        assert result.status == OrderStatus.ERROR
        assert "timeout" in result.message.lower()
        assert order.is_rejected is True
        assert "timeout" in (order.rejection_reason or "").lower()

    def test_broker_connection_error_returns_error_result(self, gateway, mock_executor):
        """When TradeExecutor raises ConnectionError, send_order returns ERROR."""
        order = _make_order()
        mock_executor.execute_signal.side_effect = ConnectionError("broker disconnected")

        result = gateway.send_order(order)

        assert result.success is False
        assert result.status == OrderStatus.ERROR
        assert order.is_rejected is True

    def test_broker_generic_exception_returns_error_result(self, gateway, mock_executor):
        """Any unexpected exception from TradeExecutor returns ERROR, never raises."""
        order = _make_order()
        mock_executor.execute_signal.side_effect = RuntimeError("unexpected broker error")

        result = gateway.send_order(order)

        assert result.success is False
        assert result.status == OrderStatus.ERROR
        assert "unexpected broker error" in result.message

    @pytest.mark.asyncio
    async def test_async_broker_timeout_returns_error_result(self, gateway, mock_executor):
        """send_order_async() handles broker timeout without raising."""
        order = _make_order()
        mock_executor.execute_signal.side_effect = TimeoutError("async timeout")

        result = await gateway.send_order_async(order)

        assert result.success is False
        assert result.status == OrderStatus.ERROR
        assert order.is_rejected is True

    def test_send_order_never_raises(self, gateway, mock_executor):
        """send_order() must never propagate exceptions to the caller."""
        order = _make_order()
        mock_executor.execute_signal.side_effect = Exception("catastrophic failure")

        # Must not raise
        result = gateway.send_order(order)
        assert result.success is False

    def test_no_executor_returns_rejected(self):
        """OrderGateway without executor returns REJECTED, never raises."""
        gw = OrderGateway(executor=None)
        order = _make_order()

        result = gw.send_order(order)

        assert result.success is False
        assert result.status == OrderStatus.REJECTED
        assert order.is_rejected is True
        assert "TradeExecutor" in (order.rejection_reason or "")


# ─────────────────────────────────────────────────────────────────────────────
# 3. Partial fill
# ─────────────────────────────────────────────────────────────────────────────


class TestPartialFill:
    def test_partial_fill_marks_order_partially_filled(self, gateway, mock_executor):
        """Partial fill: order.executed_quantity = filled amount, not full quantity."""
        order = _make_order(quantity=0.1)
        mock_executor.execute_signal.return_value = _partial_result(filled=0.05)

        result = gateway.send_order(order)

        assert result.success is True
        assert result.status == OrderStatus.PARTIAL
        assert result.filled_quantity == pytest.approx(0.05)
        # Order is NOT fully filled
        assert order.is_filled is False
        assert order.executed_quantity == pytest.approx(0.05)

    def test_partial_fill_commission_recorded(self, gateway, mock_executor):
        """Commission from partial fill is recorded on the order."""
        order = _make_order(quantity=0.1)
        mock_executor.execute_signal.return_value = _partial_result(filled=0.05)

        gateway.send_order(order)

        assert order.commission_paid == pytest.approx(0.165)

    @pytest.mark.asyncio
    async def test_async_partial_fill(self, gateway, mock_executor):
        """send_order_async() handles partial fill correctly."""
        order = _make_order(quantity=0.1)
        mock_executor.execute_signal.return_value = _partial_result(filled=0.03)

        result = await gateway.send_order_async(order)

        assert result.success is True
        assert result.status == OrderStatus.PARTIAL
        assert order.executed_quantity == pytest.approx(0.03)
        assert order.is_filled is False

    def test_full_fill_after_partial_marks_filled(self, gateway, mock_executor):
        """Two sequential fills that sum to full quantity mark order as filled."""
        order = _make_order(quantity=0.1)
        # First: partial
        mock_executor.execute_signal.return_value = _partial_result(filled=0.05)
        gateway.send_order(order)
        assert order.is_filled is False

        # Second: remaining quantity
        mock_executor.execute_signal.return_value = _filled_result(qty=0.05)
        gateway.send_order(order)
        assert order.is_filled is True
        assert order.executed_quantity == pytest.approx(0.1)


# ─────────────────────────────────────────────────────────────────────────────
# 4. Order rejection (broker-side and pre-trade gate)
# ─────────────────────────────────────────────────────────────────────────────


class TestOrderRejection:
    def test_broker_rejection_marks_order_rejected(self, gateway, mock_executor):
        """Broker REJECTED result marks order.is_rejected and records reason."""
        order = _make_order()
        mock_executor.execute_signal.return_value = _rejected_result(reason="Insufficient margin")

        result = gateway.send_order(order)

        assert result.success is False
        assert result.status == OrderStatus.REJECTED
        assert order.is_rejected is True
        assert "Insufficient margin" in (order.rejection_reason or "")

    def test_handle_rejection_marks_order_rejected(self, gateway):
        """handle_rejection() marks order.is_rejected without raising."""
        order = _make_order()
        gateway.orders[order.order_id] = order

        gateway.handle_rejection(order.order_id, reason="position limit exceeded")

        assert order.is_rejected is True
        assert "position limit exceeded" in (order.rejection_reason or "")

    def test_handle_rejection_unknown_order_does_not_raise(self, gateway):
        """handle_rejection() on unknown order_id logs warning, never raises."""
        gateway.handle_rejection("NONEXISTENT-ORDER", reason="test")
        # No exception raised

    @pytest.mark.asyncio
    async def test_async_rejection(self, gateway, mock_executor):
        """send_order_async() handles REJECTED result correctly."""
        order = _make_order()
        mock_executor.execute_signal.return_value = _rejected_result(reason="[KILL_SWITCH] Trading halted")

        result = await gateway.send_order_async(order)

        assert result.success is False
        assert result.status == OrderStatus.REJECTED
        assert order.is_rejected is True

    def test_pre_trade_gate_rejection_propagates(self, gateway, mock_executor):
        """Pre-trade gate rejection (from TradeExecutor) is surfaced correctly."""
        order = _make_order()
        mock_executor.execute_signal.return_value = ExecutionResult(
            success=False,
            order_id="ORD-001",
            filled_quantity=0.0,
            average_price=0.0,
            commission=0.0,
            status=OrderStatus.REJECTED,
            message="[KILL_SWITCH_ACTIVE] All trading halted",
            latency_ms=1.0,
        )

        result = gateway.send_order(order)

        assert result.success is False
        assert "KILL_SWITCH" in result.message
        assert order.is_rejected is True


# ─────────────────────────────────────────────────────────────────────────────
# 5. Kill switch active
# ─────────────────────────────────────────────────────────────────────────────


class TestKillSwitchActive:
    def test_kill_switch_active_blocks_order_via_executor(self, gateway, mock_executor):
        """When kill switch is active, TradeExecutor returns REJECTED with kill switch message."""
        order = _make_order()
        mock_executor.execute_signal.return_value = ExecutionResult(
            success=False,
            order_id=None,
            filled_quantity=0.0,
            average_price=0.0,
            commission=0.0,
            status=OrderStatus.REJECTED,
            message="[KILL_SWITCH_ACTIVE] All new orders blocked",
            latency_ms=0.5,
        )

        result = gateway.send_order(order)

        assert result.success is False
        assert result.status == OrderStatus.REJECTED
        assert "KILL_SWITCH" in result.message
        assert order.is_rejected is True

    @pytest.mark.asyncio
    async def test_kill_switch_active_blocks_async_order(self, gateway, mock_executor):
        """send_order_async() surfaces kill switch rejection correctly."""
        order = _make_order()
        mock_executor.execute_signal.return_value = ExecutionResult(
            success=False,
            order_id=None,
            filled_quantity=0.0,
            average_price=0.0,
            commission=0.0,
            status=OrderStatus.REJECTED,
            message="[KILL_SWITCH_ACTIVE] All new orders blocked",
            latency_ms=0.5,
        )

        result = await gateway.send_order_async(order)

        assert result.success is False
        assert "KILL_SWITCH" in result.message

    def test_kill_switch_exception_from_executor_handled(self, gateway, mock_executor):
        """If TradeExecutor raises due to kill switch, gateway returns ERROR."""
        order = _make_order()
        mock_executor.execute_signal.side_effect = RuntimeError("KillSwitch is active — all trading halted")

        result = gateway.send_order(order)

        assert result.success is False
        assert result.status == OrderStatus.ERROR
        assert order.is_rejected is True

    def test_multiple_orders_all_blocked_when_kill_switch_active(self, gateway, mock_executor):
        """All orders are blocked when kill switch is active — no partial execution."""
        mock_executor.execute_signal.return_value = ExecutionResult(
            success=False,
            order_id=None,
            filled_quantity=0.0,
            average_price=0.0,
            commission=0.0,
            status=OrderStatus.REJECTED,
            message="[KILL_SWITCH_ACTIVE]",
            latency_ms=0.5,
        )

        orders = [_make_order(order_id=f"ORD-{i:03d}") for i in range(5)]
        results = [gateway.send_order(o) for o in orders]

        assert all(not r.success for r in results)
        assert all(o.is_rejected for o in orders)
        assert mock_executor.execute_signal.call_count == 5


# ─────────────────────────────────────────────────────────────────────────────
# 6. Commission tracking
# ─────────────────────────────────────────────────────────────────────────────


class TestCommissionTracking:
    def test_track_commissions_sums_all_orders(self, gateway, mock_executor):
        """track_commissions() returns total commission across all filled orders."""
        mock_executor.execute_signal.return_value = _filled_result()

        for i in range(3):
            order = _make_order(order_id=f"ORD-{i:03d}")
            gateway.orders[order.order_id] = order
            gateway.send_order(order)

        total = gateway.track_commissions()
        # Each fill: commission_rate=0.0001 * qty=0.1 * price=3300 = 0.033
        # But commission comes from ExecutionResult.commission = 0.33
        assert total == pytest.approx(0.33 * 3, abs=0.01)

    def test_rejected_orders_contribute_zero_commission(self, gateway, mock_executor):
        """Rejected orders do not add to commission total."""
        mock_executor.execute_signal.return_value = _rejected_result()

        order = _make_order()
        gateway.orders[order.order_id] = order
        gateway.send_order(order)

        assert gateway.track_commissions() == pytest.approx(0.0)


# ─────────────────────────────────────────────────────────────────────────────
# 7. Order creation
# ─────────────────────────────────────────────────────────────────────────────


class TestOrderCreation:
    def test_create_order_registers_in_registry(self, gateway):
        """create_order() adds the order to gateway.orders."""
        order = gateway.create_order("ORD-NEW", 0.1, 3300.0, 0.0001)

        assert "ORD-NEW" in gateway.orders
        assert gateway.orders["ORD-NEW"] is order

    def test_create_order_initial_state(self, gateway):
        """Newly created order has correct initial state."""
        order = gateway.create_order("ORD-INIT", 0.5, 2000.0, 0.0002)

        assert order.quantity == pytest.approx(0.5)
        assert order.price == pytest.approx(2000.0)
        assert order.executed_quantity == pytest.approx(0.0)
        assert order.commission_paid == pytest.approx(0.0)
        assert order.is_filled is False
        assert order.is_rejected is False

    def test_order_fill_raises_on_overfill(self, gateway):
        """Order.fill() raises ValueError when filled_quantity > order.quantity."""
        order = gateway.create_order("ORD-OVER", 0.1, 3300.0, 0.0001)

        with pytest.raises(ValueError, match="cannot exceed"):
            order.fill(0.2)

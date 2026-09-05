from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from execution.order_gateway import OrderGateway
from execution.trade_executor import ExecutionResult, OrderStatus


@pytest.fixture
def successful_executor() -> AsyncMock:
    executor = AsyncMock()
    executor.execute_signal.return_value = ExecutionResult(
        success=True,
        order_id="order-1",
        filled_quantity=1.0,
        average_price=2000.0,
        commission=0.5,
        status=OrderStatus.FILLED,
        message="filled",
    )
    return executor


@pytest.mark.asyncio
async def test_sync_send_order_fails_fast_inside_running_event_loop(successful_executor: AsyncMock) -> None:
    gateway = OrderGateway(executor=successful_executor)
    order = gateway.create_order("order-1", 1.0, 2000.0, 0.5)

    with pytest.raises(RuntimeError, match="await send_order_async"):
        gateway.send_order(order)

    successful_executor.execute_signal.assert_not_awaited()


@pytest.mark.asyncio
async def test_async_send_order_routes_without_blocking(successful_executor: AsyncMock) -> None:
    gateway = OrderGateway(executor=successful_executor)
    order = gateway.create_order("order-1", 1.0, 2000.0, 0.5)

    result = await gateway.send_order_async(order)

    assert result.success is True
    assert order.is_filled is True
    successful_executor.execute_signal.assert_awaited_once()

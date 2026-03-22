from __future__ import annotations

import asyncio
from decimal import Decimal

import structlog
import zmq.asyncio

from hopefx.execution.brokers.base import BaseBroker, Order, OrderResult, OrderStatus

logger = structlog.get_logger()


class MT5Broker(BaseBroker):
    """MetaTrader 5 via ZeroMQ."""

    def __init__(self, host: str = "localhost", port: int = 5555) -> None:
        super().__init__("mt5", paper=False)
        self.host = host
        self.port = port
        self._context: zmq.asyncio.Context | None = None
        self._socket: zmq.asyncio.Socket | None = None

    async def connect(self) -> None:
        self._context = zmq.asyncio.Context()
        self._socket = self._context.socket(zmq.DEALER)
        self._socket.connect(f"tcp://{self.host}:{self.port}")
        self._connected = True
        logger.info("mt5.connected", host=self.host, port=self.port)

    async def disconnect(self) -> None:
        if self._socket:
            self._socket.close()
        if self._context:
            self._context.term()
        self._connected = False

    async def place_order(self, order: Order) -> OrderResult:
        if not self._socket:
            raise RuntimeError("Not connected")

        request = {
            "action": "ORDER",
            "symbol": order.symbol,
            "side": order.side.upper(),
            "volume": float(order.quantity),
            "type": "MARKET",
            "magic": 123456,
        }

        await self._socket.send_json(request)
        response = await asyncio.wait_for(self._socket.recv_json(), timeout=10.0)

        return OrderResult(
            order_id=str(response.get("ticket", "unknown")),
            status=OrderStatus.FILLED if response.get("success") else OrderStatus.REJECTED,
            filled_qty=order.quantity if response.get("success") else Decimal("0"),
            filled_price=Decimal(str(response.get("price", 0))),
            remaining_qty=Decimal("0") if response.get("success") else order.quantity,
            commission=Decimal("0"),
            slippage=Decimal("0"),
            timestamp=response.get("time", ""),
            raw_response=response,
        )

    async def cancel_order(self, order_id: str) -> bool:
        """Cancel a pending MT5 order via ZeroMQ."""
        if not self._socket:
            return False
        try:
            request = {"action": "CANCEL", "ticket": int(order_id)}
            await self._socket.send_json(request)
            response = await asyncio.wait_for(self._socket.recv_json(), timeout=10.0)
            success = bool(response.get("success", False))
            if success:
                logger.info("mt5.order_cancelled", order_id=order_id)
            else:
                logger.warning("mt5.cancel_failed", order_id=order_id,
                               reason=response.get("error", "unknown"))
            return success
        except Exception as exc:
            logger.error("mt5.cancel_order_error", order_id=order_id, error=str(exc))
            return False

    async def get_position(self, symbol: str) -> dict:
        """Get open position for a symbol from MT5 via ZeroMQ."""
        if not self._socket:
            return {}
        try:
            request = {"action": "GET_POSITION", "symbol": symbol}
            await self._socket.send_json(request)
            response = await asyncio.wait_for(self._socket.recv_json(), timeout=10.0)
            return response.get("position", {})
        except Exception as exc:
            logger.error("mt5.get_position_error", symbol=symbol, error=str(exc))
            return {}

    async def get_account(self) -> dict:
        """Get MT5 account summary via ZeroMQ."""
        if not self._socket:
            return {}
        try:
            request = {"action": "GET_ACCOUNT"}
            await self._socket.send_json(request)
            response = await asyncio.wait_for(self._socket.recv_json(), timeout=10.0)
            return response.get("account", {})
        except Exception as exc:
            logger.error("mt5.get_account_error", error=str(exc))
            return {}

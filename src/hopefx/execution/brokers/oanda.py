from __future__ import annotations

import asyncio
from decimal import Decimal

import aiohttp
import structlog
from oandapyV20 import API
from oandapyV20.contrib.requests import MarketOrderRequest
from oandapyV20.endpoints.orders import OrderCreate
from oandapyV20.exceptions import V20Error

from hopefx.config.vault import vault
from hopefx.execution.brokers.base import (
    BaseBroker,
    Order,
    OrderResult,
    OrderStatus,
    OrderType,
)

logger = structlog.get_logger()


class OandaBroker(BaseBroker):
    """OANDA v20 REST API implementation."""

    def __init__(self, account_id: str | None = None, paper: bool = True) -> None:
        super().__init__("oanda", paper)
        self.account_id = account_id or vault.retrieve("oanda_account_id")
        self.api_key = vault.retrieve("oanda_api_key")
        self.api: API | None = None
        self._session: aiohttp.ClientSession | None = None

    async def connect(self) -> None:
        """Connect to OANDA."""
        if not self.api_key:
            raise ValueError("OANDA API key not found in vault")

        environment = "practice" if self.paper else "live"
        self.api = API(access_token=self.api_key, environment=environment)

        # Test connection
        try:
            from oandapyV20.endpoints.accounts import AccountSummary
            r = AccountSummary(self.account_id)
            self.api.request(r)
            self._connected = True
            logger.info("oanda.connected", environment=environment, account=self.account_id)
        except V20Error as e:
            logger.exception("oanda.connection_failed", error=str(e))
            raise

    async def disconnect(self) -> None:
        """Disconnect."""
        self._connected = False
        logger.info("oanda.disconnected")

    async def place_order(self, order: Order) -> OrderResult:
        """Place order with OANDA."""
        if not self._connected or not self.api:
            raise RuntimeError("Not connected to OANDA")

        import time
        start_time = time.time()

        try:
            # Map order type
            if order.order_type == OrderType.MARKET:
                ordr = MarketOrderRequest(
                    instrument=order.symbol,
                    units=float(order.quantity) if order.side == "buy" else -float(order.quantity),
                )
            else:
                raise NotImplementedError(f"Order type {order.order_type} not implemented")

            r = OrderCreate(self.account_id, data=ordr.data)
            response = self.api.request(r)

            latency = (time.time() - start_time) * 1000
            self._latency_ms = latency

            # Parse response
            order_id = response.get("orderFillTransaction", {}).get("id", "unknown")
            filled_qty = Decimal(str(response.get("orderFillTransaction", {}).get("units", 0)))
            filled_price = Decimal(str(response.get("orderFillTransaction", {}).get("price", 0)))

            return OrderResult(
                order_id=order_id,
                status=OrderStatus.FILLED,
                filled_qty=abs(filled_qty),
                filled_price=filled_price,
                remaining_qty=Decimal("0"),
                commission=Decimal("0"),
                slippage=Decimal("0"),
                timestamp=response.get("orderFillTransaction", {}).get("time", ""),
                raw_response=response,
            )

        except V20Error as e:
            logger.exception("oanda.order_failed", error=str(e))
            return OrderResult(
                order_id="failed",
                status=OrderStatus.REJECTED,
                filled_qty=Decimal("0"),
                filled_price=Decimal("0"),
                remaining_qty=order.quantity,
                commission=Decimal("0"),
                slippage=Decimal("0"),
                timestamp="",
                raw_response=str(e),
            )

    async def cancel_order(self, order_id: str) -> bool:
        """Cancel order."""
        # Implementation for OANDA cancel
        return True

    async def get_position(self, symbol: str) -> dict:
        """Get position."""
        from oandapyV20.endpoints.positions import PositionDetails
        r = PositionDetails(accountID=self.account_id, instrument=symbol)
        try:
            response = self.api.request(r)
            return response.get("position", {})
        except V20Error:
            return {}

    async def get_account(self) -> dict:
        """Get account summary."""
        from oandapyV20.endpoints.accounts import AccountSummary
        r = AccountSummary(self.account_id)
        return self.api.request(r)

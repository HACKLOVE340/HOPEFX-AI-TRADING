from __future__ import annotations

from decimal import Decimal

import structlog
from binance.spot import Spot as SpotClient

from hopefx.execution.brokers.base import BaseBroker, Order, OrderResult, OrderStatus

logger = structlog.get_logger()


class BinanceBroker(BaseBroker):
    """Binance Spot/Margin API."""

    def __init__(self, api_key: str | None = None, secret: str | None = None, paper: bool = True) -> None:
        super().__init__("binance", paper)
        self.api_key = api_key
        self.secret = secret
        self._client: SpotClient | None = None

    async def connect(self) -> None:
        self._client = SpotClient(api_key=self.api_key, api_secret=self.secret)
        self._connected = True
        logger.info("binance.connected", paper=self.paper)

    async def disconnect(self) -> None:
        self._connected = False

    async def place_order(self, order: Order) -> OrderResult:
        if not self._client:
            raise RuntimeError("Not connected")

        result = self._client.new_order(
            symbol=order.symbol.replace("/", ""),
            side=order.side.upper(),
            type="MARKET",
            quantity=float(order.quantity),
        )

        fill = result.get("fills", [{}])[0]
        
        return OrderResult(
            order_id=str(result.get("orderId")),
            status=OrderStatus.FILLED,
            filled_qty=Decimal(str(result.get("executedQty", 0))),
            filled_price=Decimal(str(fill.get("price", 0))),
            remaining_qty=Decimal("0"),
            commission=Decimal(str(fill.get("commission", 0))),
            slippage=Decimal("0"),
            timestamp=str(result.get("transactTime")),
            raw_response=result,
        )

    async def cancel_order(self, order_id: str) -> bool:
        return True  # TODO

    async def get_position(self, symbol: str) -> dict:
        return {}  # TODO

    async def get_account(self) -> dict:
        return self._client.account() if self._client else {}

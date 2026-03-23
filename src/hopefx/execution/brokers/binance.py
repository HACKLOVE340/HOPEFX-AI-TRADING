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
        """Cancel an open order by order ID."""
        if not self._client:
            raise RuntimeError("Not connected")
        try:
            # symbol is required by Binance; derive it from open orders if not cached
            open_orders = self._client.get_open_orders()
            symbol = next(
                (o["symbol"] for o in open_orders if str(o["orderId"]) == str(order_id)),
                None,
            )
            if symbol is None:
                logger.warning("binance.cancel_order: order %s not found in open orders", order_id)
                return False
            result = self._client.cancel_order(symbol=symbol, orderId=int(order_id))
            return result.get("status") == "CANCELED"
        except Exception as exc:
            logger.error("binance.cancel_order error: %s", exc)
            return False

    async def get_position(self, symbol: str) -> dict:
        """
        Return the current spot balance for the base asset of `symbol`.

        For spot accounts there are no margin positions; this returns the
        free + locked balance of the base asset (e.g. BTC for BTCUSDT).
        """
        if not self._client:
            raise RuntimeError("Not connected")
        try:
            account = self._client.account()
            # Derive base asset: strip quote currencies (USDT, BTC, ETH, BNB)
            base = symbol.replace("USDT", "").replace("BTC", "").replace("ETH", "").replace("BNB", "")
            for balance in account.get("balances", []):
                if balance["asset"] == base:
                    free = float(balance["free"])
                    locked = float(balance["locked"])
                    total = free + locked
                    if total == 0:
                        return {}
                    return {
                        "symbol": symbol,
                        "asset": base,
                        "free": free,
                        "locked": locked,
                        "total": total,
                    }
            return {}
        except Exception as exc:
            logger.error("binance.get_position error: %s", exc)
            return {}

    async def get_account(self) -> dict:
        return self._client.account() if self._client else {}

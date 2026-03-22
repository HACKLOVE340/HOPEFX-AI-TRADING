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
        if not self._client:
            return False
        try:
            # Binance requires the symbol to cancel; try to extract from stored orders
            # For robustness, cancel by orderId across all open orders when symbol unknown
            open_orders = self._client.get_open_orders()
            for o in open_orders:
                if str(o.get("orderId")) == str(order_id):
                    self._client.cancel_order(
                        symbol=o["symbol"], orderId=int(order_id)
                    )
                    logger.info("binance.order_cancelled", order_id=order_id)
                    return True
            logger.warning("binance.cancel_order_not_found", order_id=order_id)
            return False
        except Exception as exc:
            logger.error("binance.cancel_order_failed", order_id=order_id, error=str(exc))
            return False

    async def get_position(self, symbol: str) -> dict:
        """Return open position info for a symbol (uses account balances for spot)."""
        if not self._client:
            return {}
        try:
            acct = self._client.account()
            clean_symbol = symbol.replace("/", "").upper()
            # For a spot account the 'position' is the asset balance
            for bal in acct.get("balances", []):
                asset = bal.get("asset", "")
                if clean_symbol.startswith(asset) and asset:
                    free = float(bal.get("free", 0))
                    locked = float(bal.get("locked", 0))
                    total = free + locked
                    if total > 0:
                        return {
                            "symbol": clean_symbol,
                            "asset": asset,
                            "free": free,
                            "locked": locked,
                            "total": total,
                        }
            return {}
        except Exception as exc:
            logger.error("binance.get_position_failed", symbol=symbol, error=str(exc))
            return {}

    async def get_account(self) -> dict:
        if not self._client:
            return {}
        try:
            return self._client.account()
        except Exception as exc:
            logger.error("binance.get_account_failed", error=str(exc))
            return {}

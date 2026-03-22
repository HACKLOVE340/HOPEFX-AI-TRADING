"""Interactive Brokers TWS/Gateway integration."""

from __future__ import annotations

import asyncio
from decimal import Decimal
from typing import Optional

import structlog
from ib_async import IB, Stock, Forex, Future, Order as IBJavaOrder

from hopefx.execution.brokers.base import BaseBroker, Order, OrderResult, OrderStatus

logger = structlog.get_logger()


class InteractiveBrokers(BaseBroker):
    """Interactive Brokers integration via ib_async."""

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 7497,  # 7496 for TWS, 7497 for IB Gateway
        client_id: int = 1,
        paper: bool = True
    ) -> None:
        super().__init__("interactive_brokers", paper)
        self.host = host
        self.port = port
        self.client_id = client_id
        self._ib = IB()
        self._order_callbacks: dict = {}

    async def connect(self) -> None:
        """Connect to TWS/Gateway."""
        try:
            await asyncio.to_thread(
                self._ib.connect,
                self.host,
                self.port,
                clientId=self.client_id
            )
            self._connected = True
            
            # Setup callbacks
            self._ib.orderStatusEvent += self._on_order_status
            
            logger.info("ib.connected", host=self.host, port=self.port)
        except Exception as e:
            logger.exception("ib.connection_failed", error=str(e))
            raise

    async def disconnect(self) -> None:
        """Disconnect from TWS."""
        if self._ib.isConnected():
            self._ib.disconnect()
        self._connected = False

    def _on_order_status(self, trade) -> None:
        """Handle order status updates."""
        # Callback for async order updates
        pass

    async def place_order(self, order: Order) -> OrderResult:
        """Place order with IB."""
        # Map symbol to IB contract
        contract = self._get_contract(order.symbol)
        
        # Create IB order
        ib_order = IBJavaOrder()
        ib_order.action = order.side.upper()
        ib_order.totalQuantity = float(order.quantity)
        ib_order.orderType = order.order_type.upper()
        
        if order.price:
            ib_order.lmtPrice = float(order.price)
        if order.stop_price:
            ib_order.auxPrice = float(order.stop_price)

        # Submit order
        trade = self._ib.placeOrder(contract, ib_order)
        
        # Wait for fill or timeout
        filled = await self._wait_for_fill(trade, timeout=30)
        
        if filled:
            fill = trade.fills[0] if trade.fills else None
            return OrderResult(
                order_id=str(trade.order.orderId),
                status=OrderStatus.FILLED,
                filled_qty=Decimal(str(trade.filled())),
                filled_price=Decimal(str(fill.execution.price)) if fill else Decimal("0"),
                remaining_qty=Decimal(str(trade.remaining())),
                commission=Decimal(str(fill.commissionReport.commission)) if fill and fill.commissionReport else Decimal("0"),
                slippage=self._calculate_slippage(order, fill),
                timestamp=datetime.utcnow().isoformat(),
                raw_response=trade
            )
        else:
            # Cancel if not filled
            self._ib.cancelOrder(trade.order)
            return OrderResult(
                order_id=str(trade.order.orderId),
                status=OrderStatus.CANCELLED,
                filled_qty=Decimal(str(trade.filled())),
                filled_price=Decimal("0"),
                remaining_qty=Decimal(str(trade.remaining())),
                commission=Decimal("0"),
                slippage=Decimal("0"),
                timestamp=datetime.utcnow().isoformat(),
                raw_response="Timeout"
            )

    def _get_contract(self, symbol: str):
        """Get IB contract for symbol."""
        if symbol == "XAUUSD":
            # Gold CFD or futures
            return Future('GC', exchange='COMEX')
        elif len(symbol) == 6 and symbol.isalpha():
            # Forex pair
            return Forex(symbol[:3] + '.' + symbol[3:])
        else:
            return Stock(symbol, 'SMART', 'USD')

    async def _wait_for_fill(self, trade, timeout: int) -> bool:
        """Wait for order fill."""
        start = asyncio.get_event_loop().time()
        while asyncio.get_event_loop().time() - start < timeout:
            if trade.isDone():
                return True
            await asyncio.sleep(0.1)
        return False

    def _calculate_slippage(self, order: Order, fill) -> Decimal:
        """Calculate execution slippage."""
        if not fill:
            return Decimal("0")
        # Implementation
        return Decimal("0")

    async def cancel_order(self, order_id: str) -> bool:
        """Cancel order."""
        # Implementation
        return True

    async def get_position(self, symbol: str) -> dict:
        """Get position."""
        positions = self._ib.positions()
        for pos in positions:
            if pos.contract.symbol == symbol:
                return {
                    "symbol": symbol,
                    "qty": pos.position,
                    "avg_cost": pos.avgCost
                }
        return {}

    async def get_account(self) -> dict:
        """Get account summary."""
        account = self._ib.accountSummary()
        return {a.tag: a.value for a in account}

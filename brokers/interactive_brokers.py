# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
Interactive Brokers Connector

Universal connector for Interactive Brokers (IB).
Supports stocks, options, futures, forex, and more.
"""

import logging
from datetime import datetime, timezone

UTC = timezone.utc
from typing import Any

logger = logging.getLogger(__name__)

try:
    from ib_insync import (
        IB,
        Forex,
        Future,
        LimitOrder,
        MarketOrder,
        Stock,
        StopOrder,
    )

    IB_AVAILABLE = True
except ImportError:
    IB_AVAILABLE = False
    logger.warning("ib_insync package not installed. IB connector will not work.")

from .base import (
    AccountInfo,
    BrokerConnector,
    Order,
    OrderSide,
    OrderStatus,
    OrderType,
    Position,
)


class InteractiveBrokersConnector(BrokerConnector):
    """
    Interactive Brokers (IB) Universal Connector.

    Supports all asset types:
    - Stocks (NYSE, NASDAQ, etc.)
    - Options
    - Futures
    - Forex
    - Bonds
    - Crypto (via IB)

    Configuration:
        host: IB Gateway/TWS host (default: '127.0.0.1')
        port: IB Gateway port (paper: 7497, live: 7496, TWS paper: 7497)
        client_id: Unique client ID (default: 1)
        account: IB account number (optional)
        paper: True for paper trading (default: True)

    Example:
        config = {
            'host': '127.0.0.1',
            'port': 7497,  # Paper trading port
            'client_id': 1,
            'paper': True
        }
        ib = InteractiveBrokersConnector(config)
        ib.connect()
    """

    def __init__(self, config: dict[str, Any]):
        """Initialize IB connector."""
        super().__init__(config)

        if not IB_AVAILABLE:
            raise ImportError(
                "ib_insync package not installed. Install with: pip install ib_insync",
            )

        self.host = config.get("host", "127.0.0.1")
        self.port = config.get("port", 7497)  # Paper trading default
        self.client_id = config.get("client_id", 1)
        self.account = config.get("account")
        self.paper = config.get("paper", True)

        self.ib = IB()
        self.connected = False

    def connect(self) -> bool:
        """Connect to IB Gateway or TWS."""
        try:
            self.ib.connect(
                host=self.host,
                port=self.port,
                clientId=self.client_id,
                readonly=False,
            )

            self.connected = True

            # Get account summary
            accounts = self.ib.managedAccounts()
            if accounts:
                if not self.account:
                    self.account = accounts[0]
                logger.info("Connected to IB account: %s", self.account)

                logger.info("Mode: %s", "PAPER" if self.paper else "LIVE")

            return True

        except Exception as e:
            logger.error("IB connection error: %s", e)

            return False

    def disconnect(self) -> bool:
        """Disconnect from IB."""
        try:
            self.ib.disconnect()
            self.connected = False
            logger.info("Disconnected from IB")
            return True
        except Exception as e:
            logger.error("IB disconnect error: %s", e)

            return False

    def place_order(  # pylint: disable=arguments-differ
        self,
        symbol: str,
        side: OrderSide,
        quantity: float = 0.0,
        order_type: OrderType = OrderType.MARKET,
        price: float | None = None,
        stop_price: float | None = None,
        **kwargs,
    ) -> Order | None:
        """
        Place order on IB.

        Args:
            symbol: Symbol (e.g., 'AAPL', 'EUR.USD', 'ESZ3')
            side: BUY or SELL
            quantity: Number of shares/contracts
            order_type: Market, Limit, Stop
            price: Limit price

        Returns:
            Order object
        """
        if not self.connected:
            logger.error("Not connected to IB")
            return None

        try:
            # Create contract (stocks by default, can be extended)
            asset_type = kwargs.get("asset_type", "stock")

            if asset_type == "stock":
                exchange = kwargs.get("exchange", "SMART")
                contract = Stock(symbol, exchange, "USD")
            elif asset_type == "forex":
                contract = Forex(symbol)
            elif asset_type == "future":
                contract = Future(symbol, exchange=kwargs.get("exchange", "GLOBEX"))
            else:
                contract = Stock(symbol, "SMART", "USD")

            # Qualify contract
            self.ib.qualifyContracts(contract)

            # Create order
            action = "BUY" if side == OrderSide.BUY else "SELL"

            if order_type == OrderType.MARKET:
                ib_order = MarketOrder(action, quantity)
            elif order_type == OrderType.LIMIT:
                ib_order = LimitOrder(action, quantity, price)
            elif order_type == OrderType.STOP:
                ib_order = StopOrder(action, quantity, price)
            else:
                logger.error("Unsupported order type: %s", order_type)

                return None

            # Place order
            trade = self.ib.placeOrder(contract, ib_order)

            # Wait for order to be acknowledged
            self.ib.sleep(0.5)

            # Create Order object
            order = Order(
                id=str(trade.order.orderId),
                symbol=symbol,
                side=side,
                type=order_type,
                quantity=quantity,
                price=price,
                status=OrderStatus.PENDING,
                timestamp=datetime.now(UTC),
                metadata={"ib_order_id": trade.order.orderId},
            )

            logger.info("IB order placed: %s %s %s", symbol, side.value, quantity)

            return order

        except Exception as e:
            logger.error("IB place order error: %s", e)

            return None

    def cancel_order(self, order_id: str) -> bool:
        """Cancel order."""
        if not self.connected:
            return False

        try:
            # Find trade by order ID
            for trade in self.ib.trades():
                if str(trade.order.orderId) == order_id:
                    self.ib.cancelOrder(trade.order)
                    logger.info("Cancelled order: %s", order_id)

                    return True

            logger.warning("Order not found: %s", order_id)

            return False

        except Exception as e:
            logger.error("IB cancel order error: %s", e)

            return False

    def get_order(self, order_id: str) -> Order | None:
        """Get order by ID."""
        if not self.connected:
            return None

        try:
            for trade in self.ib.trades():
                if str(trade.order.orderId) == order_id:
                    return self._ib_trade_to_order(trade)
            return None
        except Exception as e:
            logger.error("IB get order error: %s", e)

            return None

    def get_positions(self, symbol: str | None = None) -> list[Position]:
        """Get open positions."""
        if not self.connected:
            return []

        try:
            positions = self.ib.positions()
            result = []

            for pos in positions:
                if symbol and pos.contract.symbol != symbol:
                    continue

                # Get current price
                ticker = self.ib.reqTicker(pos.contract)
                current_price = ticker.marketPrice() if ticker else 0.0

                # Calculate P&L
                unrealized_pnl = pos.unrealizedPNL if hasattr(pos, "unrealizedPNL") else 0.0

                position = Position(
                    symbol=pos.contract.symbol,
                    side="LONG" if pos.position > 0 else "SHORT",
                    quantity=abs(pos.position),
                    entry_price=pos.avgCost / abs(pos.position) if pos.position != 0 else 0.0,
                    current_price=current_price,
                    unrealized_pnl=unrealized_pnl,
                    realized_pnl=0.0,
                    timestamp=datetime.now(UTC),
                )
                result.append(position)

            return result

        except Exception as e:
            logger.error("IB get positions error: %s", e)

            return []

    def close_position(self, symbol: str, quantity: float | None = None) -> bool:
        """Close position."""
        if not self.connected:
            return False

        try:
            positions = self.get_positions(symbol)
            if not positions:
                logger.warning("No position found for %s", symbol)

                return False

            for position in positions:
                # Create closing order
                close_side = OrderSide.SELL if position.side == "LONG" else OrderSide.BUY
                close_qty = quantity or position.quantity

                # Place closing order
                self.place_order(
                    symbol=symbol,
                    side=close_side,
                    quantity=close_qty,
                    order_type=OrderType.MARKET,
                )

            logger.info("Closed position: %s", symbol)

            return True

        except Exception as e:
            logger.error("IB close position error: %s", e)

            return False

    def get_account_info(self) -> AccountInfo | None:
        """Get account information."""
        if not self.connected:
            return None

        try:
            account_values = self.ib.accountValues()

            balance = 0.0
            equity = 0.0
            margin_used = 0.0
            margin_available = 0.0

            for value in account_values:
                if value.tag == "TotalCashValue":
                    balance = float(value.value)
                elif value.tag == "NetLiquidation":
                    equity = float(value.value)
                elif value.tag == "MaintMarginReq":
                    margin_used = float(value.value)
                elif value.tag == "AvailableFunds":
                    margin_available = float(value.value)

            positions = len(self.get_positions())

            return AccountInfo(
                balance=balance,
                equity=equity,
                margin_used=margin_used,
                margin_available=margin_available,
                positions_count=positions,
                timestamp=datetime.now(UTC),
            )

        except Exception as e:
            logger.error("IB get account info error: %s", e)

            return None

    def get_market_data(  # pylint: disable=arguments-differ
        self,
        symbol: str,
        timeframe: str = "1 hour",
        limit: int = 100,
    ) -> list[dict[str, Any]] | None:
        """Get historical market data."""
        if not self.connected:
            return None

        try:
            # Create contract
            contract = Stock(symbol, "SMART", "USD")
            self.ib.qualifyContracts(contract)

            # Request historical data
            duration = f"{limit} D"  # Simplified
            bars = self.ib.reqHistoricalData(
                contract,
                endDateTime="",
                durationStr=duration,
                barSizeSetting=timeframe,
                whatToShow="TRADES",
                useRTH=True,
            )

            candles = []
            for bar in bars:
                candles.append(
                    {
                        "time": bar.date,
                        "open": bar.open,
                        "high": bar.high,
                        "low": bar.low,
                        "close": bar.close,
                        "volume": bar.volume,
                    },
                )

            return candles

        except Exception as e:
            logger.error("IB get market data error: %s", e)

            return None

    def _ib_trade_to_order(self, trade) -> Order:
        """Convert IB trade to Order object."""
        return Order(
            id=str(trade.order.orderId),
            symbol=trade.contract.symbol,
            side=OrderSide.BUY if trade.order.action == "BUY" else OrderSide.SELL,
            type=OrderType.MARKET if trade.order.orderType == "MKT" else OrderType.LIMIT,
            quantity=trade.order.totalQuantity,
            price=trade.order.lmtPrice if hasattr(trade.order, "lmtPrice") else None,
            status=OrderStatus.OPEN if trade.orderStatus.status == "Submitted" else OrderStatus.FILLED,
            timestamp=datetime.now(UTC),
        )


# ---------------------------------------------------------------------------
# Backward-compatible alias
# ---------------------------------------------------------------------------
# The modern production connector lives in brokers/ibkr_connector.py as
# IBKRConnector.  Register it as a virtual subclass of
# InteractiveBrokersConnector so that isinstance/issubclass checks used in
# tests and factory validation continue to work with either class name.
try:
    from brokers.ibkr_connector import IBKRConnector as _IBKRConnector

    InteractiveBrokersConnector.register(_IBKRConnector)
except Exception as _exc:  # pragma: no cover – registration is best-effort
    import logging as _logging
    _logging.getLogger(__name__).debug("IBKRConnector registration skipped: %s", _exc)

"""
Interactive Brokers Connector

Universal connector for Interactive Brokers (IB).
Supports stocks, options, futures, forex, and more.
"""

from typing import Dict, List, Optional, Any
from datetime import datetime
import logging

try:
    from ib_insync import IB, Stock, Forex, Future, Option, MarketOrder, LimitOrder, StopOrder
    IB_AVAILABLE = True
except ImportError:
    IB_AVAILABLE = False
    logging.warning("ib_insync package not installed. IB connector will not work.")

from .base import (
    BrokerConnector,
    Order,
    Position,
    AccountInfo,
    OrderType,
    OrderSide,
    OrderStatus,
)

logger = logging.getLogger(__name__)


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

    def __init__(self, config: Dict[str, Any]):
        """Initialize IB connector."""
        super().__init__(config)

        if not IB_AVAILABLE:
            raise ImportError(
                "ib_insync package not installed. "
                "Install with: pip install ib_insync"
            )

        self.host = config.get('host', '127.0.0.1')
        self.port = config.get('port', 7497)  # Paper trading default
        self.client_id = config.get('client_id', 1)
        self.account = config.get('account', None)
        self.paper = config.get('paper', True)

        self.ib = IB()
        self.connected = False

    def connect(self) -> bool:
        """Connect to IB Gateway or TWS."""
        try:
            self.ib.connect(
                host=self.host,
                port=self.port,
                clientId=self.client_id,
                readonly=False
            )

            self.connected = True

            # Get account summary
            accounts = self.ib.managedAccounts()
            if accounts:
                if not self.account:
                    self.account = accounts[0]
                logger.info(f"Connected to IB account: {self.account}")
                logger.info(f"Mode: {'PAPER' if self.paper else 'LIVE'}")

            return True

        except Exception as e:
            logger.error(f"IB connection error: {e}")
            return False

    def disconnect(self) -> bool:
        """Disconnect from IB."""
        try:
            self.ib.disconnect()
            self.connected = False
            logger.info("Disconnected from IB")
            return True
        except Exception as e:
            logger.error(f"IB disconnect error: {e}")
            return False

    def place_order(
        self,
        symbol: str,
        side: OrderSide,
        quantity: float,
        order_type: OrderType = OrderType.MARKET,
        price: Optional[float] = None,
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None,
        **kwargs
    ) -> Optional[Order]:
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
            asset_type = kwargs.get('asset_type', 'stock')

            if asset_type == 'stock':
                exchange = kwargs.get('exchange', 'SMART')
                contract = Stock(symbol, exchange, 'USD')
            elif asset_type == 'forex':
                contract = Forex(symbol)
            elif asset_type == 'future':
                contract = Future(symbol, exchange=kwargs.get('exchange', 'GLOBEX'))
            else:
                contract = Stock(symbol, 'SMART', 'USD')

            # Qualify contract
            self.ib.qualifyContracts(contract)

            # Create order
            action = 'BUY' if side == OrderSide.BUY else 'SELL'

            if order_type == OrderType.MARKET:
                ib_order = MarketOrder(action, quantity)
            elif order_type == OrderType.LIMIT:
                ib_order = LimitOrder(action, quantity, price)
            elif order_type == OrderType.STOP:
                ib_order = StopOrder(action, quantity, price)
            else:
                logger.error(f"Unsupported order type: {order_type}")
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
                timestamp=datetime.now(),
                metadata={'ib_order_id': trade.order.orderId}
            )

            logger.info(f"IB order placed: {symbol} {side.value} {quantity}")
            return order

        except Exception as e:
            logger.error(f"IB place order error: {e}")
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
                    logger.info(f"Cancelled order: {order_id}")
                    return True

            logger.warning(f"Order not found: {order_id}")
            return False

        except Exception as e:
            logger.error(f"IB cancel order error: {e}")
            return False

    def get_order(self, order_id: str) -> Optional[Order]:
        """Get order by ID."""
        if not self.connected:
            return None

        try:
            for trade in self.ib.trades():
                if str(trade.order.orderId) == order_id:
                    return self._ib_trade_to_order(trade)
            return None
        except Exception as e:
            logger.error(f"IB get order error: {e}")
            return None

    def get_positions(self, symbol: Optional[str] = None) -> List[Position]:
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
                unrealized_pnl = pos.unrealizedPNL if hasattr(pos, 'unrealizedPNL') else 0.0

                position = Position(
                    symbol=pos.contract.symbol,
                    side="LONG" if pos.position > 0 else "SHORT",
                    quantity=abs(pos.position),
                    entry_price=pos.avgCost / abs(pos.position) if pos.position != 0 else 0.0,
                    current_price=current_price,
                    unrealized_pnl=unrealized_pnl,
                    realized_pnl=0.0,
                    timestamp=datetime.now()
                )
                result.append(position)

            return result

        except Exception as e:
            logger.error(f"IB get positions error: {e}")
            return []

    def close_position(
        self,
        symbol: str,
        quantity: Optional[float] = None
    ) -> bool:
        """Close position."""
        if not self.connected:
            return False

        try:
            positions = self.get_positions(symbol)
            if not positions:
                logger.warning(f"No position found for {symbol}")
                return False

            for position in positions:
                # Create closing order
                close_side = OrderSide.SELL if position.side == "LONG" else OrderSide.BUY
                close_qty = quantity if quantity else position.quantity

                # Place closing order
                self.place_order(
                    symbol=symbol,
                    side=close_side,
                    quantity=close_qty,
                    order_type=OrderType.MARKET
                )

            logger.info(f"Closed position: {symbol}")
            return True

        except Exception as e:
            logger.error(f"IB close position error: {e}")
            return False

    def get_account_info(self) -> Optional[AccountInfo]:
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
                if value.tag == 'TotalCashValue':
                    balance = float(value.value)
                elif value.tag == 'NetLiquidation':
                    equity = float(value.value)
                elif value.tag == 'MaintMarginReq':
                    margin_used = float(value.value)
                elif value.tag == 'AvailableFunds':
                    margin_available = float(value.value)

            positions = len(self.get_positions())

            return AccountInfo(
                balance=balance,
                equity=equity,
                margin_used=margin_used,
                margin_available=margin_available,
                positions_count=positions,
                timestamp=datetime.now()
            )

        except Exception as e:
            logger.error(f"IB get account info error: {e}")
            return None

    def get_market_data(
        self,
        symbol: str,
        timeframe: str = "1 hour",
        count: int = 100
    ) -> Optional[List[Dict[str, Any]]]:
        """Get historical market data."""
        if not self.connected:
            return None

        try:
            # Create contract
            contract = Stock(symbol, 'SMART', 'USD')
            self.ib.qualifyContracts(contract)

            # Request historical data
            duration = f"{count} D"  # Simplified
            bars = self.ib.reqHistoricalData(
                contract,
                endDateTime='',
                durationStr=duration,
                barSizeSetting=timeframe,
                whatToShow='TRADES',
                useRTH=True
            )

            candles = []
            for bar in bars:
                candles.append({
                    'time': bar.date,
                    'open': bar.open,
                    'high': bar.high,
                    'low': bar.low,
                    'close': bar.close,
                    'volume': bar.volume,
                })

            return candles

        except Exception as e:
            logger.error(f"IB get market data error: {e}")
            return None

    def _ib_trade_to_order(self, trade) -> Order:
        """Convert IB trade to Order object."""
        return Order(
            id=str(trade.order.orderId),
            symbol=trade.contract.symbol,
            side=OrderSide.BUY if trade.order.action == 'BUY' else OrderSide.SELL,
            type=OrderType.MARKET if trade.order.orderType == 'MKT' else OrderType.LIMIT,
            quantity=trade.order.totalQuantity,
            price=trade.order.lmtPrice if hasattr(trade.order, 'lmtPrice') else None,
            status=OrderStatus.OPEN if trade.orderStatus.status == 'Submitted' else OrderStatus.FILLED,
            timestamp=datetime.now()
        )

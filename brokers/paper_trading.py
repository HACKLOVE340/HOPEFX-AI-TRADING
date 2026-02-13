"""
Paper Trading Broker

Simulated broker for testing strategies without real money.
"""

from typing import Dict, List, Optional, Any
from datetime import datetime
import uuid
import logging

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


class PaperTradingBroker(BrokerConnector):
    """
    Paper trading broker for testing.

    Simulates order execution and position management
    without connecting to real exchanges.
    """

    def __init__(self, config: Dict[str, Any]):
        """
        Initialize paper trading broker.

        Args:
            config: Configuration with 'initial_balance'
        """
        super().__init__(config)

        self.initial_balance = config.get('initial_balance', 10000.0)
        self.balance = self.initial_balance
        self.equity = self.initial_balance

        self.orders: Dict[str, Order] = {}
        self.positions: Dict[str, Position] = {}

        # Simulated market prices
        self.market_prices = {
            'BTC/USD': 50000.0,
            'ETH/USD': 3000.0,
            'XAUUSD': 2000.0,
        }

    def connect(self) -> bool:
        """Connect to paper trading broker (always succeeds)"""
        self.connected = True
        logger.info(f"Connected to {self.name} (Paper Trading)")
        logger.info(f"Initial balance: ${self.initial_balance:,.2f}")
        return True

    def disconnect(self) -> bool:
        """Disconnect from paper trading broker"""
        self.connected = False
        logger.info(f"Disconnected from {self.name}")
        return True

    def place_order(
        self,
        symbol: str,
        side: OrderSide,
        order_type: OrderType,
        quantity: float,
        price: Optional[float] = None,
        stop_price: Optional[float] = None,
        **kwargs
    ) -> Order:
        """
        Place a simulated order.

        Market orders are filled immediately at current market price.
        Limit orders are filled if price conditions are met.
        """
        if not self.connected:
            raise ConnectionError("Not connected to broker")

        # Generate order ID
        order_id = str(uuid.uuid4())

        # Get current market price
        current_price = self.market_prices.get(symbol, 0.0)
        if current_price == 0.0:
            logger.warning(f"Unknown symbol {symbol}, using default price 1000.0")
            current_price = 1000.0

        # Create order
        order = Order(
            id=order_id,
            symbol=symbol,
            side=side,
            type=order_type,
            quantity=quantity,
            price=price,
            stop_price=stop_price,
            status=OrderStatus.PENDING,
            timestamp=datetime.utcnow(),
        )

        # Process order
        if order_type == OrderType.MARKET:
            # Execute immediately
            order.status = OrderStatus.FILLED
            order.filled_quantity = quantity
            order.average_price = current_price

            # Update position
            self._update_position(symbol, side, quantity, current_price)

            logger.info(
                f"Market order filled: {side.value} {quantity} {symbol} @ ${current_price}"
            )
        else:
            # For limit/stop orders, just mark as open
            order.status = OrderStatus.OPEN
            logger.info(
                f"Limit order placed: {side.value} {quantity} {symbol} @ ${price}"
            )

        self.orders[order_id] = order
        return order

    def cancel_order(self, order_id: str) -> bool:
        """Cancel an order"""
        if order_id in self.orders:
            order = self.orders[order_id]
            if order.status in [OrderStatus.PENDING, OrderStatus.OPEN]:
                order.status = OrderStatus.CANCELLED
                logger.info(f"Order cancelled: {order_id}")
                return True

        logger.warning(f"Cannot cancel order {order_id}")
        return False

    def get_order(self, order_id: str) -> Optional[Order]:
        """Get order by ID"""
        return self.orders.get(order_id)

    def get_positions(self) -> List[Position]:
        """Get all open positions"""
        # Update unrealized P&L for each position
        positions = []
        for position in self.positions.values():
            current_price = self.market_prices.get(position.symbol, position.entry_price)

            if position.side == "LONG":
                unrealized_pnl = (current_price - position.entry_price) * position.quantity
            else:  # SHORT
                unrealized_pnl = (position.entry_price - current_price) * position.quantity

            position.current_price = current_price
            position.unrealized_pnl = unrealized_pnl
            positions.append(position)

        return positions

    def close_position(self, symbol: str) -> bool:
        """Close a position"""
        if symbol not in self.positions:
            logger.warning(f"No open position for {symbol}")
            return False

        position = self.positions[symbol]
        current_price = self.market_prices.get(symbol, position.entry_price)

        # Calculate P&L
        if position.side == "LONG":
            pnl = (current_price - position.entry_price) * position.quantity
        else:
            pnl = (position.entry_price - current_price) * position.quantity

        # Update balance
        self.balance += pnl
        self.equity = self.balance

        # Remove position
        del self.positions[symbol]

        logger.info(
            f"Position closed: {symbol}, P&L: ${pnl:.2f}, "
            f"New balance: ${self.balance:.2f}"
        )

        return True

    def get_account_info(self) -> AccountInfo:
        """Get account information"""
        # Calculate total unrealized P&L
        total_unrealized = sum(
            p.unrealized_pnl for p in self.get_positions()
        )

        equity = self.balance + total_unrealized

        return AccountInfo(
            balance=self.balance,
            equity=equity,
            margin_used=0.0,  # Not used in paper trading
            margin_available=equity,
            positions_count=len(self.positions),
            timestamp=datetime.utcnow(),
        )

    def get_market_data(
        self,
        symbol: str,
        timeframe: str = "1h",
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """
        Get simulated market data.

        Returns simple OHLCV data for testing.
        """
        current_price = self.market_prices.get(symbol, 1000.0)

        # Generate dummy OHLCV data
        data = []
        for i in range(limit):
            # Simple price variation
            price = current_price * (1 + (i % 10 - 5) / 100)
            data.append({
                'timestamp': datetime.utcnow().isoformat(),
                'open': price,
                'high': price * 1.01,
                'low': price * 0.99,
                'close': price,
                'volume': 1000.0,
            })

        return data

    def update_market_price(self, symbol: str, price: float):
        """
        Update simulated market price.

        Args:
            symbol: Trading symbol
            price: New price
        """
        self.market_prices[symbol] = price
        logger.debug(f"Updated {symbol} price to ${price}")

    def _update_position(
        self,
        symbol: str,
        side: OrderSide,
        quantity: float,
        price: float
    ):
        """Update or create position"""
        position_side = "LONG" if side == OrderSide.BUY else "SHORT"

        if symbol in self.positions:
            # Update existing position
            position = self.positions[symbol]

            # For simplicity, assume same side
            total_quantity = position.quantity + quantity
            avg_price = (
                (position.entry_price * position.quantity + price * quantity) /
                total_quantity
            )

            position.quantity = total_quantity
            position.entry_price = avg_price
        else:
            # Create new position
            self.positions[symbol] = Position(
                symbol=symbol,
                side=position_side,
                quantity=quantity,
                entry_price=price,
                current_price=price,
                unrealized_pnl=0.0,
                timestamp=datetime.utcnow(),
            )

"""
OANDA Broker Connector

Implements real trading with OANDA v20 REST API for Forex trading.
"""

from typing import Dict, List, Optional, Any
from datetime import datetime
import logging
import requests
from decimal import Decimal

from .base import (
    BrokerConnector, Order, Position, AccountInfo,
    OrderType, OrderSide, OrderStatus
)

logger = logging.getLogger(__name__)


class OANDAConnector(BrokerConnector):
    """
    OANDA broker connector for Forex trading.

    Requires:
        - API key (token)
        - Account ID
        - Practice/Live environment selection

    Features:
        - Real-time forex data
        - Market/Limit/Stop orders
        - Position management
        - Account information
        - WebSocket streaming (optional)
    """

    # OANDA API endpoints
    PRACTICE_URL = "https://api-fxpractice.oanda.com/v3"
    LIVE_URL = "https://api-fxtrade.oanda.com/v3"
    STREAM_PRACTICE = "https://stream-fxpractice.oanda.com/v3"
    STREAM_LIVE = "https://stream-fxtrade.oanda.com/v3"

    def __init__(self, config: Dict[str, Any]):
        """
        Initialize OANDA connector.

        Args:
            config: Configuration dictionary with:
                - api_key: OANDA API token
                - account_id: OANDA account ID
                - environment: 'practice' or 'live' (default: practice)
        """
        super().__init__(config)

        self.api_key = config.get('api_key')
        self.account_id = config.get('account_id')
        self.environment = config.get('environment', 'practice')

        # Set API URLs based on environment
        if self.environment == 'live':
            self.base_url = self.LIVE_URL
            self.stream_url = self.STREAM_LIVE
        else:
            self.base_url = self.PRACTICE_URL
            self.stream_url = self.STREAM_PRACTICE

        self.connected = False
        self.session = None

        if not self.api_key or not self.account_id:
            raise ValueError("OANDA requires 'api_key' and 'account_id' in config")

    def connect(self) -> bool:
        """
        Connect to OANDA API.

        Returns:
            bool: True if connection successful
        """
        try:
            self.session = requests.Session()
            self.session.headers.update({
                'Authorization': f'Bearer {self.api_key}',
                'Content-Type': 'application/json',
            })

            # Test connection by fetching account info
            response = self.session.get(
                f"{self.base_url}/accounts/{self.account_id}"
            )
            response.raise_for_status()

            self.connected = True
            logger.info(f"Connected to OANDA ({self.environment})")
            return True

        except Exception as e:
            logger.error(f"Failed to connect to OANDA: {e}")
            self.connected = False
            return False

    def disconnect(self) -> bool:
        """
        Disconnect from OANDA API.

        Returns:
            bool: True if disconnection successful
        """
        try:
            if self.session:
                self.session.close()
            self.connected = False
            logger.info("Disconnected from OANDA")
            return True
        except Exception as e:
            logger.error(f"Error disconnecting from OANDA: {e}")
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
    ) -> Optional[Order]:
        """
        Place an order with OANDA.

        Args:
            symbol: Currency pair (e.g., "EUR_USD")
            side: BUY or SELL
            quantity: Number of units
            order_type: MARKET, LIMIT, STOP, STOP_LIMIT
            price: Limit price (for LIMIT orders)
            stop_loss: Stop loss price
            take_profit: Take profit price

        Returns:
            Order object if successful, None otherwise
        """
        if not self.connected:
            logger.error("Not connected to OANDA")
            return None

        try:
            # Convert symbol format (EUR/USD -> EUR_USD)
            oanda_symbol = symbol.replace('/', '_')

            # Build order request
            order_data = {
                "order": {
                    "type": self._convert_order_type(order_type),
                    "instrument": oanda_symbol,
                    "units": str(int(quantity if side == OrderSide.BUY else -quantity)),
                }
            }

            # Add price for limit orders
            if order_type == OrderType.LIMIT and price:
                order_data["order"]["price"] = str(price)

            # Add stop loss if provided
            if stop_loss:
                order_data["order"]["stopLossOnFill"] = {
                    "price": str(stop_loss)
                }

            # Add take profit if provided
            if take_profit:
                order_data["order"]["takeProfitOnFill"] = {
                    "price": str(take_profit)
                }

            # Send order
            response = self.session.post(
                f"{self.base_url}/accounts/{self.account_id}/orders",
                json=order_data
            )
            response.raise_for_status()

            result = response.json()

            # Parse response
            if 'orderFillTransaction' in result:
                fill_tx = result['orderFillTransaction']
                order = Order(
                    id=fill_tx['id'],
                    symbol=symbol,
                    side=side,
                    type=order_type,
                    quantity=abs(float(fill_tx['units'])),
                    price=float(fill_tx.get('price', 0)),
                    status=OrderStatus.FILLED,
                    filled_quantity=abs(float(fill_tx['units'])),
                    average_price=float(fill_tx.get('price', 0)),
                    timestamp=datetime.now(),
                    metadata=result
                )
            elif 'orderCreateTransaction' in result:
                create_tx = result['orderCreateTransaction']
                order = Order(
                    id=create_tx['id'],
                    symbol=symbol,
                    side=side,
                    type=order_type,
                    quantity=abs(float(create_tx['units'])),
                    price=price,
                    status=OrderStatus.OPEN,
                    timestamp=datetime.now(),
                    metadata=result
                )
            else:
                logger.error(f"Unknown order response: {result}")
                return None

            logger.info(f"Order placed: {order.id} - {side.value} {quantity} {symbol}")
            return order

        except Exception as e:
            logger.error(f"Failed to place order: {e}")
            return None

    def cancel_order(self, order_id: str) -> bool:
        """
        Cancel an open order.

        Args:
            order_id: Order ID to cancel

        Returns:
            bool: True if cancellation successful
        """
        if not self.connected:
            logger.error("Not connected to OANDA")
            return False

        try:
            response = self.session.put(
                f"{self.base_url}/accounts/{self.account_id}/orders/{order_id}/cancel"
            )
            response.raise_for_status()

            logger.info(f"Order cancelled: {order_id}")
            return True

        except Exception as e:
            logger.error(f"Failed to cancel order {order_id}: {e}")
            return False

    def get_order(self, order_id: str) -> Optional[Order]:
        """
        Get order details.

        Args:
            order_id: Order ID

        Returns:
            Order object if found, None otherwise
        """
        if not self.connected:
            logger.error("Not connected to OANDA")
            return None

        try:
            response = self.session.get(
                f"{self.base_url}/accounts/{self.account_id}/orders/{order_id}"
            )
            response.raise_for_status()

            order_data = response.json()['order']

            # Parse order data
            units = float(order_data['units'])
            side = OrderSide.BUY if units > 0 else OrderSide.SELL

            order = Order(
                id=order_data['id'],
                symbol=order_data['instrument'].replace('_', '/'),
                side=side,
                type=self._parse_order_type(order_data['type']),
                quantity=abs(units),
                price=float(order_data.get('price', 0)),
                status=self._parse_order_status(order_data['state']),
                timestamp=datetime.fromisoformat(order_data['createTime'].replace('Z', '+00:00')),
                metadata=order_data
            )

            return order

        except Exception as e:
            logger.error(f"Failed to get order {order_id}: {e}")
            return None

    def get_positions(self) -> List[Position]:
        """
        Get all open positions.

        Returns:
            List of Position objects
        """
        if not self.connected:
            logger.error("Not connected to OANDA")
            return []

        try:
            response = self.session.get(
                f"{self.base_url}/accounts/{self.account_id}/openPositions"
            )
            response.raise_for_status()

            positions = []
            for pos_data in response.json()['positions']:
                # OANDA can have both long and short on same instrument
                if pos_data['long']['units'] != '0':
                    positions.append(self._parse_position(pos_data, 'long'))

                if pos_data['short']['units'] != '0':
                    positions.append(self._parse_position(pos_data, 'short'))

            return positions

        except Exception as e:
            logger.error(f"Failed to get positions: {e}")
            return []

    def close_position(self, symbol: str, quantity: Optional[float] = None) -> bool:
        """
        Close a position (or partial).

        Args:
            symbol: Currency pair
            quantity: Number of units to close (None = close all)

        Returns:
            bool: True if position closed successfully
        """
        if not self.connected:
            logger.error("Not connected to OANDA")
            return False

        try:
            oanda_symbol = symbol.replace('/', '_')

            # Close long position
            long_data = {}
            if quantity:
                long_data['units'] = str(int(quantity))
            else:
                long_data['units'] = 'ALL'

            response = self.session.put(
                f"{self.base_url}/accounts/{self.account_id}/positions/{oanda_symbol}/close",
                json={"longUnits": long_data['units']}
            )

            if response.status_code == 200:
                logger.info(f"Position closed: {symbol}")
                return True

            # Try closing short position if long failed
            response = self.session.put(
                f"{self.base_url}/accounts/{self.account_id}/positions/{oanda_symbol}/close",
                json={"shortUnits": long_data['units']}
            )

            if response.status_code == 200:
                logger.info(f"Position closed: {symbol}")
                return True

            return False

        except Exception as e:
            logger.error(f"Failed to close position {symbol}: {e}")
            return False

    def get_account_info(self) -> Optional[AccountInfo]:
        """
        Get account information.

        Returns:
            AccountInfo object if successful, None otherwise
        """
        if not self.connected:
            logger.error("Not connected to OANDA")
            return None

        try:
            response = self.session.get(
                f"{self.base_url}/accounts/{self.account_id}"
            )
            response.raise_for_status()

            account_data = response.json()['account']

            info = AccountInfo(
                balance=float(account_data['balance']),
                equity=float(account_data['NAV']),
                margin_used=float(account_data['marginUsed']),
                margin_available=float(account_data['marginAvailable']),
                positions_count=int(account_data['openPositionCount']),
                timestamp=datetime.now()
            )

            return info

        except Exception as e:
            logger.error(f"Failed to get account info: {e}")
            return None

    def get_market_data(
        self,
        symbol: str,
        timeframe: str = 'M1',
        count: int = 100
    ) -> Optional[List[Dict[str, Any]]]:
        """
        Get historical market data (candles).

        Args:
            symbol: Currency pair (e.g., "EUR_USD")
            timeframe: Candle timeframe (M1, M5, H1, D)
            count: Number of candles

        Returns:
            List of candle dictionaries
        """
        if not self.connected:
            logger.error("Not connected to OANDA")
            return None

        try:
            oanda_symbol = symbol.replace('/', '_')

            response = self.session.get(
                f"{self.base_url}/instruments/{oanda_symbol}/candles",
                params={
                    'granularity': timeframe,
                    'count': count
                }
            )
            response.raise_for_status()

            candles = []
            for candle in response.json()['candles']:
                if candle['complete']:
                    candles.append({
                        'timestamp': datetime.fromisoformat(candle['time'].replace('Z', '+00:00')),
                        'open': float(candle['mid']['o']),
                        'high': float(candle['mid']['h']),
                        'low': float(candle['mid']['l']),
                        'close': float(candle['mid']['c']),
                        'volume': int(candle['volume'])
                    })

            return candles

        except Exception as e:
            logger.error(f"Failed to get market data for {symbol}: {e}")
            return None

    def _convert_order_type(self, order_type: OrderType) -> str:
        """Convert OrderType to OANDA format"""
        mapping = {
            OrderType.MARKET: "MARKET",
            OrderType.LIMIT: "LIMIT",
            OrderType.STOP: "STOP",
            OrderType.STOP_LIMIT: "STOP"  # OANDA doesn't have STOP_LIMIT
        }
        return mapping.get(order_type, "MARKET")

    def _parse_order_type(self, oanda_type: str) -> OrderType:
        """Parse OANDA order type to OrderType"""
        mapping = {
            "MARKET": OrderType.MARKET,
            "LIMIT": OrderType.LIMIT,
            "STOP": OrderType.STOP,
            "MARKET_IF_TOUCHED": OrderType.STOP
        }
        return mapping.get(oanda_type, OrderType.MARKET)

    def _parse_order_status(self, oanda_state: str) -> OrderStatus:
        """Parse OANDA order state to OrderStatus"""
        mapping = {
            "PENDING": OrderStatus.PENDING,
            "FILLED": OrderStatus.FILLED,
            "TRIGGERED": OrderStatus.OPEN,
            "CANCELLED": OrderStatus.CANCELLED
        }
        return mapping.get(oanda_state, OrderStatus.PENDING)

    def _parse_position(self, pos_data: Dict, side: str) -> Position:
        """Parse OANDA position data"""
        side_data = pos_data[side]
        units = float(side_data['units'])

        return Position(
            symbol=pos_data['instrument'].replace('_', '/'),
            side='LONG' if side == 'long' else 'SHORT',
            quantity=abs(units),
            entry_price=float(side_data['averagePrice']),
            current_price=0.0,  # Would need separate call to get current price
            unrealized_pnl=float(side_data['unrealizedPL']),
            realized_pnl=float(side_data.get('realizedPL', 0)),
            timestamp=datetime.now()
        )

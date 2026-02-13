"""
Binance Broker Connector

Implements real crypto trading with Binance REST API and WebSocket.
"""

from typing import Dict, List, Optional, Any
from datetime import datetime
import logging
import hmac
import hashlib
import time
import requests

from .base import (
    BrokerConnector, Order, Position, AccountInfo,
    OrderType, OrderSide, OrderStatus
)

logger = logging.getLogger(__name__)


class BinanceConnector(BrokerConnector):
    """
    Binance broker connector for cryptocurrency trading.

    Requires:
        - API key
        - API secret
        - Testnet/Live environment selection

    Features:
        - Spot trading (BTC, ETH, altcoins)
        - Market/Limit/Stop orders
        - Real-time price feeds
        - WebSocket streaming
        - Account balances
    """

    # Binance API endpoints
    LIVE_URL = "https://api.binance.com"
    TESTNET_URL = "https://testnet.binance.vision"

    def __init__(self, config: Dict[str, Any]):
        """
        Initialize Binance connector.

        Args:
            config: Configuration dictionary with:
                - api_key: Binance API key
                - api_secret: Binance API secret
                - testnet: True for testnet, False for live (default: True)
        """
        super().__init__(config)

        self.api_key = config.get('api_key')
        self.api_secret = config.get('api_secret')
        self.testnet = config.get('testnet', True)

        # Set API URL based on environment
        self.base_url = self.TESTNET_URL if self.testnet else self.LIVE_URL

        self.connected = False
        self.session = None

        if not self.api_key or not self.api_secret:
            raise ValueError("Binance requires 'api_key' and 'api_secret' in config")

    def connect(self) -> bool:
        """
        Connect to Binance API.

        Returns:
            bool: True if connection successful
        """
        try:
            self.session = requests.Session()
            self.session.headers.update({
                'X-MBX-APIKEY': self.api_key
            })

            # Test connection
            response = self.session.get(f"{self.base_url}/api/v3/ping")
            response.raise_for_status()

            # Test API key permissions
            timestamp = int(time.time() * 1000)
            params = {'timestamp': timestamp}
            signature = self._generate_signature(params)
            params['signature'] = signature

            response = self.session.get(
                f"{self.base_url}/api/v3/account",
                params=params
            )
            response.raise_for_status()

            self.connected = True
            env = "testnet" if self.testnet else "live"
            logger.info(f"Connected to Binance ({env})")
            return True

        except Exception as e:
            logger.error(f"Failed to connect to Binance: {e}")
            self.connected = False
            return False

    def disconnect(self) -> bool:
        """
        Disconnect from Binance API.

        Returns:
            bool: True if disconnection successful
        """
        try:
            if self.session:
                self.session.close()
            self.connected = False
            logger.info("Disconnected from Binance")
            return True
        except Exception as e:
            logger.error(f"Error disconnecting from Binance: {e}")
            return False

    def place_order(
        self,
        symbol: str,
        side: OrderSide,
        quantity: float,
        order_type: OrderType = OrderType.MARKET,
        price: Optional[float] = None,
        stop_price: Optional[float] = None,
    ) -> Optional[Order]:
        """
        Place an order with Binance.

        Args:
            symbol: Trading pair (e.g., "BTCUSDT")
            side: BUY or SELL
            quantity: Quantity to trade
            order_type: MARKET, LIMIT, STOP, STOP_LIMIT
            price: Limit price (for LIMIT orders)
            stop_price: Stop price (for STOP orders)

        Returns:
            Order object if successful, None otherwise
        """
        if not self.connected:
            logger.error("Not connected to Binance")
            return None

        try:
            # Format symbol (remove /)
            binance_symbol = symbol.replace('/', '').upper()

            # Build order parameters
            timestamp = int(time.time() * 1000)
            params = {
                'symbol': binance_symbol,
                'side': side.value,
                'type': self._convert_order_type(order_type),
                'quantity': self._format_quantity(binance_symbol, quantity),
                'timestamp': timestamp
            }

            # Add price for limit orders
            if order_type == OrderType.LIMIT and price:
                params['timeInForce'] = 'GTC'  # Good Till Cancel
                params['price'] = str(price)

            # Add stop price for stop orders
            if order_type in [OrderType.STOP, OrderType.STOP_LIMIT] and stop_price:
                params['stopPrice'] = str(stop_price)
                if order_type == OrderType.STOP_LIMIT and price:
                    params['price'] = str(price)
                    params['timeInForce'] = 'GTC'

            # Sign request
            params['signature'] = self._generate_signature(params)

            # Send order
            response = self.session.post(
                f"{self.base_url}/api/v3/order",
                params=params
            )
            response.raise_for_status()

            result = response.json()

            # Parse response
            order = Order(
                id=str(result['orderId']),
                symbol=symbol,
                side=side,
                type=order_type,
                quantity=float(result['origQty']),
                price=float(result.get('price', 0)) if result.get('price') else None,
                status=self._parse_order_status(result['status']),
                filled_quantity=float(result.get('executedQty', 0)),
                average_price=float(result.get('price', 0)) if result.get('price') else None,
                timestamp=datetime.fromtimestamp(result['transactTime'] / 1000),
                metadata=result
            )

            logger.info(f"Order placed: {order.id} - {side.value} {quantity} {symbol}")
            return order

        except Exception as e:
            logger.error(f"Failed to place order: {e}")
            return None

    def cancel_order(self, order_id: str, symbol: str = None) -> bool:
        """
        Cancel an open order.

        Args:
            order_id: Order ID to cancel
            symbol: Trading pair (required for Binance)

        Returns:
            bool: True if cancellation successful
        """
        if not self.connected:
            logger.error("Not connected to Binance")
            return False

        if not symbol:
            logger.error("Symbol is required to cancel order on Binance")
            return False

        try:
            binance_symbol = symbol.replace('/', '').upper()
            timestamp = int(time.time() * 1000)

            params = {
                'symbol': binance_symbol,
                'orderId': order_id,
                'timestamp': timestamp
            }
            params['signature'] = self._generate_signature(params)

            response = self.session.delete(
                f"{self.base_url}/api/v3/order",
                params=params
            )
            response.raise_for_status()

            logger.info(f"Order cancelled: {order_id}")
            return True

        except Exception as e:
            logger.error(f"Failed to cancel order {order_id}: {e}")
            return False

    def get_order(self, order_id: str, symbol: str = None) -> Optional[Order]:
        """
        Get order details.

        Args:
            order_id: Order ID
            symbol: Trading pair (required for Binance)

        Returns:
            Order object if found, None otherwise
        """
        if not self.connected:
            logger.error("Not connected to Binance")
            return None

        if not symbol:
            logger.error("Symbol is required to get order on Binance")
            return None

        try:
            binance_symbol = symbol.replace('/', '').upper()
            timestamp = int(time.time() * 1000)

            params = {
                'symbol': binance_symbol,
                'orderId': order_id,
                'timestamp': timestamp
            }
            params['signature'] = self._generate_signature(params)

            response = self.session.get(
                f"{self.base_url}/api/v3/order",
                params=params
            )
            response.raise_for_status()

            result = response.json()

            # Parse order data
            side = OrderSide.BUY if result['side'] == 'BUY' else OrderSide.SELL

            order = Order(
                id=str(result['orderId']),
                symbol=symbol,
                side=side,
                type=self._parse_order_type(result['type']),
                quantity=float(result['origQty']),
                price=float(result.get('price', 0)) if result.get('price') else None,
                status=self._parse_order_status(result['status']),
                filled_quantity=float(result.get('executedQty', 0)),
                timestamp=datetime.fromtimestamp(result['time'] / 1000),
                metadata=result
            )

            return order

        except Exception as e:
            logger.error(f"Failed to get order {order_id}: {e}")
            return None

    def get_positions(self) -> List[Position]:
        """
        Get all open positions (non-zero balances).

        Note: Binance Spot doesn't have traditional positions,
        this returns non-zero balances as "positions"

        Returns:
            List of Position objects
        """
        if not self.connected:
            logger.error("Not connected to Binance")
            return []

        try:
            timestamp = int(time.time() * 1000)
            params = {'timestamp': timestamp}
            params['signature'] = self._generate_signature(params)

            response = self.session.get(
                f"{self.base_url}/api/v3/account",
                params=params
            )
            response.raise_for_status()

            account_data = response.json()
            positions = []

            # Convert non-zero balances to positions
            for balance in account_data['balances']:
                free = float(balance['free'])
                locked = float(balance['locked'])
                total = free + locked

                if total > 0:
                    # Treat as a LONG position
                    position = Position(
                        symbol=balance['asset'],
                        side='LONG',
                        quantity=total,
                        entry_price=0.0,  # Not tracked in spot trading
                        current_price=0.0,  # Would need separate price call
                        unrealized_pnl=0.0,  # Not calculated for spot
                        realized_pnl=0.0,
                        timestamp=datetime.now()
                    )
                    positions.append(position)

            return positions

        except Exception as e:
            logger.error(f"Failed to get positions: {e}")
            return []

    def close_position(self, symbol: str, quantity: Optional[float] = None) -> bool:
        """
        Close a position by selling the asset.

        Args:
            symbol: Asset symbol (e.g., "BTC")
            quantity: Quantity to sell (None = sell all)

        Returns:
            bool: True if position closed successfully
        """
        if not self.connected:
            logger.error("Not connected to Binance")
            return False

        try:
            # Get current balance
            timestamp = int(time.time() * 1000)
            params = {'timestamp': timestamp}
            params['signature'] = self._generate_signature(params)

            response = self.session.get(
                f"{self.base_url}/api/v3/account",
                params=params
            )
            response.raise_for_status()

            account_data = response.json()

            # Find balance for symbol
            balance = 0.0
            for bal in account_data['balances']:
                if bal['asset'] == symbol.replace('/', '').upper():
                    balance = float(bal['free'])
                    break

            if balance <= 0:
                logger.warning(f"No balance to close for {symbol}")
                return False

            # Sell quantity (or all)
            sell_qty = quantity if quantity else balance

            # Create trading pair (assume USDT for now)
            trading_pair = f"{symbol}USDT"

            # Place market sell order
            order = self.place_order(
                symbol=trading_pair,
                side=OrderSide.SELL,
                quantity=sell_qty,
                order_type=OrderType.MARKET
            )

            if order:
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
            logger.error("Not connected to Binance")
            return None

        try:
            timestamp = int(time.time() * 1000)
            params = {'timestamp': timestamp}
            params['signature'] = self._generate_signature(params)

            response = self.session.get(
                f"{self.base_url}/api/v3/account",
                params=params
            )
            response.raise_for_status()

            account_data = response.json()

            # Calculate total balance in USDT equivalent
            total_balance = 0.0
            positions_count = 0

            for balance in account_data['balances']:
                free = float(balance['free'])
                locked = float(balance['locked'])
                total = free + locked

                if total > 0:
                    positions_count += 1
                    # For simplicity, count USDT directly, others would need price conversion
                    if balance['asset'] == 'USDT':
                        total_balance += total

            info = AccountInfo(
                balance=total_balance,
                equity=total_balance,  # Same as balance for spot
                margin_used=0.0,  # Not applicable for spot
                margin_available=total_balance,
                positions_count=positions_count,
                timestamp=datetime.now()
            )

            return info

        except Exception as e:
            logger.error(f"Failed to get account info: {e}")
            return None

    def get_market_data(
        self,
        symbol: str,
        timeframe: str = '1m',
        limit: int = 100
    ) -> Optional[List[Dict[str, Any]]]:
        """
        Get historical market data (klines/candlesticks).

        Args:
            symbol: Trading pair (e.g., "BTCUSDT")
            timeframe: Kline interval (1m, 5m, 1h, 1d, etc.)
            limit: Number of klines (max 1000)

        Returns:
            List of candle dictionaries
        """
        if not self.connected:
            logger.error("Not connected to Binance")
            return None

        try:
            binance_symbol = symbol.replace('/', '').upper()

            params = {
                'symbol': binance_symbol,
                'interval': timeframe,
                'limit': min(limit, 1000)
            }

            response = self.session.get(
                f"{self.base_url}/api/v3/klines",
                params=params
            )
            response.raise_for_status()

            candles = []
            for kline in response.json():
                candles.append({
                    'timestamp': datetime.fromtimestamp(kline[0] / 1000),
                    'open': float(kline[1]),
                    'high': float(kline[2]),
                    'low': float(kline[3]),
                    'close': float(kline[4]),
                    'volume': float(kline[5])
                })

            return candles

        except Exception as e:
            logger.error(f"Failed to get market data for {symbol}: {e}")
            return None

    def _generate_signature(self, params: Dict) -> str:
        """Generate HMAC SHA256 signature for Binance API"""
        query_string = '&'.join([f"{k}={v}" for k, v in params.items()])
        signature = hmac.new(
            self.api_secret.encode('utf-8'),
            query_string.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()
        return signature

    def _convert_order_type(self, order_type: OrderType) -> str:
        """Convert OrderType to Binance format"""
        mapping = {
            OrderType.MARKET: "MARKET",
            OrderType.LIMIT: "LIMIT",
            OrderType.STOP: "STOP_LOSS",
            OrderType.STOP_LIMIT: "STOP_LOSS_LIMIT"
        }
        return mapping.get(order_type, "MARKET")

    def _parse_order_type(self, binance_type: str) -> OrderType:
        """Parse Binance order type to OrderType"""
        mapping = {
            "MARKET": OrderType.MARKET,
            "LIMIT": OrderType.LIMIT,
            "STOP_LOSS": OrderType.STOP,
            "STOP_LOSS_LIMIT": OrderType.STOP_LIMIT,
            "TAKE_PROFIT": OrderType.LIMIT,
            "TAKE_PROFIT_LIMIT": OrderType.LIMIT
        }
        return mapping.get(binance_type, OrderType.MARKET)

    def _parse_order_status(self, binance_status: str) -> OrderStatus:
        """Parse Binance order status to OrderStatus"""
        mapping = {
            "NEW": OrderStatus.OPEN,
            "PARTIALLY_FILLED": OrderStatus.OPEN,
            "FILLED": OrderStatus.FILLED,
            "CANCELED": OrderStatus.CANCELLED,
            "PENDING_CANCEL": OrderStatus.PENDING,
            "REJECTED": OrderStatus.REJECTED,
            "EXPIRED": OrderStatus.CANCELLED
        }
        return mapping.get(binance_status, OrderStatus.PENDING)

    def _format_quantity(self, symbol: str, quantity: float) -> str:
        """Format quantity according to symbol's LOT_SIZE filter"""
        # Simplified - in production, should fetch exchange info for precise formatting
        return f"{quantity:.8f}".rstrip('0').rstrip('.')

"""
Alpaca Broker Connector

Implements real stock trading with Alpaca REST API (commission-free US stocks).
"""

from typing import Dict, List, Optional, Any
from datetime import datetime
import logging
import requests

from .base import (
    BrokerConnector, Order, Position, AccountInfo,
    OrderType, OrderSide, OrderStatus
)

logger = logging.getLogger(__name__)


class AlpacaConnector(BrokerConnector):
    """
    Alpaca broker connector for US stock trading.
    
    Requires:
        - API key
        - API secret
        - Paper/Live trading selection
    
    Features:
        - Commission-free US stocks
        - Real-time and delayed market data
        - Market/Limit/Stop orders
        - Fractional shares
        - Extended hours trading
    """
    
    # Alpaca API endpoints
    PAPER_URL = "https://paper-api.alpaca.markets"
    LIVE_URL = "https://api.alpaca.markets"
    DATA_URL = "https://data.alpaca.markets"
    
    def __init__(self, config: Dict[str, Any]):
        """
        Initialize Alpaca connector.
        
        Args:
            config: Configuration dictionary with:
                - api_key: Alpaca API key
                - api_secret: Alpaca API secret
                - paper: True for paper trading, False for live (default: True)
        """
        super().__init__(config)
        
        self.api_key = config.get('api_key')
        self.api_secret = config.get('api_secret')
        self.paper = config.get('paper', True)
        
        # Set API URL based on environment
        self.base_url = self.PAPER_URL if self.paper else self.LIVE_URL
        
        self.connected = False
        self.session = None
        
        if not self.api_key or not self.api_secret:
            raise ValueError("Alpaca requires 'api_key' and 'api_secret' in config")
    
    def connect(self) -> bool:
        """
        Connect to Alpaca API.
        
        Returns:
            bool: True if connection successful
        """
        try:
            self.session = requests.Session()
            self.session.headers.update({
                'APCA-API-KEY-ID': self.api_key,
                'APCA-API-SECRET-KEY': self.api_secret,
            })
            
            # Test connection by fetching account
            response = self.session.get(f"{self.base_url}/v2/account")
            response.raise_for_status()
            
            self.connected = True
            env = "paper" if self.paper else "live"
            logger.info(f"Connected to Alpaca ({env})")
            return True
            
        except Exception as e:
            logger.error(f"Failed to connect to Alpaca: {e}")
            self.connected = False
            return False
    
    def disconnect(self) -> bool:
        """
        Disconnect from Alpaca API.
        
        Returns:
            bool: True if disconnection successful
        """
        try:
            if self.session:
                self.session.close()
            self.connected = False
            logger.info("Disconnected from Alpaca")
            return True
        except Exception as e:
            logger.error(f"Error disconnecting from Alpaca: {e}")
            return False
    
    def place_order(
        self,
        symbol: str,
        side: OrderSide,
        quantity: float,
        order_type: OrderType = OrderType.MARKET,
        price: Optional[float] = None,
        stop_price: Optional[float] = None,
        time_in_force: str = 'day',
        extended_hours: bool = False,
    ) -> Optional[Order]:
        """
        Place an order with Alpaca.
        
        Args:
            symbol: Stock ticker (e.g., "AAPL", "TSLA")
            side: BUY or SELL
            quantity: Number of shares (can be fractional)
            order_type: MARKET, LIMIT, STOP, STOP_LIMIT
            price: Limit price (for LIMIT orders)
            stop_price: Stop price (for STOP orders)
            time_in_force: 'day', 'gtc', 'ioc', 'fok'
            extended_hours: Allow extended hours trading
        
        Returns:
            Order object if successful, None otherwise
        """
        if not self.connected:
            logger.error("Not connected to Alpaca")
            return None
        
        try:
            # Build order request
            order_data = {
                'symbol': symbol.upper(),
                'qty': quantity,
                'side': side.value.lower(),
                'type': self._convert_order_type(order_type),
                'time_in_force': time_in_force,
            }
            
            # Add price for limit orders
            if order_type == OrderType.LIMIT and price:
                order_data['limit_price'] = str(price)
            
            # Add stop price for stop orders
            if order_type in [OrderType.STOP, OrderType.STOP_LIMIT] and stop_price:
                order_data['stop_price'] = str(stop_price)
                if order_type == OrderType.STOP_LIMIT and price:
                    order_data['limit_price'] = str(price)
            
            # Extended hours
            if extended_hours:
                order_data['extended_hours'] = True
            
            # Send order
            response = self.session.post(
                f"{self.base_url}/v2/orders",
                json=order_data
            )
            response.raise_for_status()
            
            result = response.json()
            
            # Parse response
            order = Order(
                id=result['id'],
                symbol=result['symbol'],
                side=OrderSide.BUY if result['side'] == 'buy' else OrderSide.SELL,
                type=self._parse_order_type(result['type']),
                quantity=float(result['qty']),
                price=float(result.get('limit_price', 0)) if result.get('limit_price') else None,
                stop_price=float(result.get('stop_price', 0)) if result.get('stop_price') else None,
                status=self._parse_order_status(result['status']),
                filled_quantity=float(result.get('filled_qty', 0)),
                average_price=float(result.get('filled_avg_price', 0)) if result.get('filled_avg_price') else None,
                timestamp=datetime.fromisoformat(result['created_at'].replace('Z', '+00:00')),
                metadata=result
            )
            
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
            logger.error("Not connected to Alpaca")
            return False
        
        try:
            response = self.session.delete(
                f"{self.base_url}/v2/orders/{order_id}"
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
            logger.error("Not connected to Alpaca")
            return None
        
        try:
            response = self.session.get(
                f"{self.base_url}/v2/orders/{order_id}"
            )
            response.raise_for_status()
            
            result = response.json()
            
            # Parse order data
            order = Order(
                id=result['id'],
                symbol=result['symbol'],
                side=OrderSide.BUY if result['side'] == 'buy' else OrderSide.SELL,
                type=self._parse_order_type(result['type']),
                quantity=float(result['qty']),
                price=float(result.get('limit_price', 0)) if result.get('limit_price') else None,
                stop_price=float(result.get('stop_price', 0)) if result.get('stop_price') else None,
                status=self._parse_order_status(result['status']),
                filled_quantity=float(result.get('filled_qty', 0)),
                average_price=float(result.get('filled_avg_price', 0)) if result.get('filled_avg_price') else None,
                timestamp=datetime.fromisoformat(result['created_at'].replace('Z', '+00:00')),
                metadata=result
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
            logger.error("Not connected to Alpaca")
            return []
        
        try:
            response = self.session.get(f"{self.base_url}/v2/positions")
            response.raise_for_status()
            
            positions = []
            for pos_data in response.json():
                qty = float(pos_data['qty'])
                
                position = Position(
                    symbol=pos_data['symbol'],
                    side='LONG' if qty > 0 else 'SHORT',
                    quantity=abs(qty),
                    entry_price=float(pos_data['avg_entry_price']),
                    current_price=float(pos_data['current_price']),
                    unrealized_pnl=float(pos_data['unrealized_pl']),
                    realized_pnl=0.0,  # Not provided by Alpaca in position data
                    timestamp=datetime.now()
                )
                positions.append(position)
            
            return positions
            
        except Exception as e:
            logger.error(f"Failed to get positions: {e}")
            return []
    
    def close_position(self, symbol: str, quantity: Optional[float] = None) -> bool:
        """
        Close a position (or partial).
        
        Args:
            symbol: Stock ticker
            quantity: Number of shares to close (None = close all)
        
        Returns:
            bool: True if position closed successfully
        """
        if not self.connected:
            logger.error("Not connected to Alpaca")
            return False
        
        try:
            if quantity:
                # Partial close - need to determine side and place opposite order
                positions = self.get_positions()
                for pos in positions:
                    if pos.symbol == symbol.upper():
                        opposite_side = OrderSide.SELL if pos.side == 'LONG' else OrderSide.BUY
                        order = self.place_order(
                            symbol=symbol,
                            side=opposite_side,
                            quantity=quantity,
                            order_type=OrderType.MARKET
                        )
                        return order is not None
                
                logger.warning(f"No position found for {symbol}")
                return False
            else:
                # Close entire position
                response = self.session.delete(
                    f"{self.base_url}/v2/positions/{symbol.upper()}"
                )
                response.raise_for_status()
                
                logger.info(f"Position closed: {symbol}")
                return True
            
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
            logger.error("Not connected to Alpaca")
            return None
        
        try:
            response = self.session.get(f"{self.base_url}/v2/account")
            response.raise_for_status()
            
            account_data = response.json()
            
            info = AccountInfo(
                balance=float(account_data['cash']),
                equity=float(account_data['equity']),
                margin_used=float(account_data.get('initial_margin', 0)),
                margin_available=float(account_data['buying_power']),
                positions_count=int(account_data.get('position_count', 0)),
                timestamp=datetime.now()
            )
            
            return info
            
        except Exception as e:
            logger.error(f"Failed to get account info: {e}")
            return None
    
    def get_market_data(
        self,
        symbol: str,
        timeframe: str = '1Min',
        limit: int = 100
    ) -> Optional[List[Dict[str, Any]]]:
        """
        Get historical market data (bars).
        
        Args:
            symbol: Stock ticker
            timeframe: Bar timeframe (1Min, 5Min, 15Min, 1Hour, 1Day)
            limit: Number of bars
        
        Returns:
            List of bar dictionaries
        """
        if not self.connected:
            logger.error("Not connected to Alpaca")
            return None
        
        try:
            # Use data API v2
            response = self.session.get(
                f"{self.DATA_URL}/v2/stocks/{symbol.upper()}/bars",
                params={
                    'timeframe': timeframe,
                    'limit': limit
                }
            )
            response.raise_for_status()
            
            bars_data = response.json()
            
            candles = []
            if 'bars' in bars_data:
                for bar in bars_data['bars']:
                    candles.append({
                        'timestamp': datetime.fromisoformat(bar['t'].replace('Z', '+00:00')),
                        'open': float(bar['o']),
                        'high': float(bar['h']),
                        'low': float(bar['l']),
                        'close': float(bar['c']),
                        'volume': int(bar['v'])
                    })
            
            return candles
            
        except Exception as e:
            logger.error(f"Failed to get market data for {symbol}: {e}")
            return None
    
    def get_quote(self, symbol: str) -> Optional[Dict[str, Any]]:
        """
        Get latest quote for a symbol.
        
        Args:
            symbol: Stock ticker
        
        Returns:
            Dictionary with bid/ask prices
        """
        if not self.connected:
            logger.error("Not connected to Alpaca")
            return None
        
        try:
            response = self.session.get(
                f"{self.DATA_URL}/v2/stocks/{symbol.upper()}/quotes/latest"
            )
            response.raise_for_status()
            
            quote_data = response.json()
            
            if 'quote' in quote_data:
                quote = quote_data['quote']
                return {
                    'bid': float(quote.get('bp', 0)),
                    'ask': float(quote.get('ap', 0)),
                    'bid_size': int(quote.get('bs', 0)),
                    'ask_size': int(quote.get('as', 0)),
                    'timestamp': datetime.fromisoformat(quote['t'].replace('Z', '+00:00'))
                }
            
            return None
            
        except Exception as e:
            logger.error(f"Failed to get quote for {symbol}: {e}")
            return None
    
    def _convert_order_type(self, order_type: OrderType) -> str:
        """Convert OrderType to Alpaca format"""
        mapping = {
            OrderType.MARKET: "market",
            OrderType.LIMIT: "limit",
            OrderType.STOP: "stop",
            OrderType.STOP_LIMIT: "stop_limit"
        }
        return mapping.get(order_type, "market")
    
    def _parse_order_type(self, alpaca_type: str) -> OrderType:
        """Parse Alpaca order type to OrderType"""
        mapping = {
            "market": OrderType.MARKET,
            "limit": OrderType.LIMIT,
            "stop": OrderType.STOP,
            "stop_limit": OrderType.STOP_LIMIT,
            "trailing_stop": OrderType.STOP
        }
        return mapping.get(alpaca_type, OrderType.MARKET)
    
    def _parse_order_status(self, alpaca_status: str) -> OrderStatus:
        """Parse Alpaca order status to OrderStatus"""
        mapping = {
            "new": OrderStatus.OPEN,
            "pending_new": OrderStatus.PENDING,
            "accepted": OrderStatus.OPEN,
            "partially_filled": OrderStatus.OPEN,
            "filled": OrderStatus.FILLED,
            "done_for_day": OrderStatus.OPEN,
            "canceled": OrderStatus.CANCELLED,
            "expired": OrderStatus.CANCELLED,
            "replaced": OrderStatus.CANCELLED,
            "pending_cancel": OrderStatus.PENDING,
            "pending_replace": OrderStatus.PENDING,
            "rejected": OrderStatus.REJECTED,
            "suspended": OrderStatus.PENDING,
            "calculated": OrderStatus.OPEN
        }
        return mapping.get(alpaca_status, OrderStatus.PENDING)

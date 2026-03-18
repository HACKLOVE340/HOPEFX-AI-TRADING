"""
Binance broker implementation for crypto trading.
"""

from decimal import Decimal
from typing import Any

import aiohttp

from src.brokers.base import Broker
from src.core.config import settings
from src.core.exceptions import BrokerError, BrokerConnectionError
from src.domain.enums import BrokerType, OrderStatus, TradeDirection
from src.domain.models import Account, Order, Position, TickData


class BinanceBroker(Broker):
    """
    Binance Spot/Margin trading.
    """
    
    def __init__(
        self,
        api_key: str | None = None,
        secret: str | None = None,
        testnet: bool = True,
        credentials: dict[str, Any] | None = None
    ):
        super().__init__(BrokerType.BINANCE, credentials or {})
        
        self.api_key = api_key or settings.broker.binance_api_key
        self.secret = secret or settings.broker.binance_secret
        self.testnet = testnet
        
        self._base_url = (
            "https://testnet.binance.vision"
            if testnet else
            "https://api.binance.com"
        )
        self._session: aiohttp.ClientSession | None = None
    
    async def connect(self) -> bool:
        """Connect and verify API key."""
        self._session = aiohttp.ClientSession()
        
        try:
            # Test connection
            async with self._session.get(
                f"{self._base_url}/api/v3/account",
                headers={"X-MBX-APIKEY": self.api_key}
            ) as response:
                if response.status == 200:
                    self._connected = True
                    return True
                else:
                    raise BrokerConnectionError(f"Binance auth failed: {response.status}")
                    
        except Exception as e:
            raise BrokerConnectionError(f"Binance connection failed: {e}")
    
    async def disconnect(self) -> None:
        """Disconnect."""
        if self._session:
            await self._session.close()
        self._connected = False
    
    async def get_account(self) -> Account:
        """Get account info."""
        import time
        import hmac
        import hashlib
        
        timestamp = int(time.time() * 1000)
        query_string = f"timestamp={timestamp}"
        signature = hmac.new(
            self.secret.encode(),
            query_string.encode(),
            hashlib.sha256
        ).hexdigest()
        
        url = f"{self._base_url}/api/v3/account?{query_string}&signature={signature}"
        
        async with self._session.get(
            url,
            headers={"X-MBX-APIKEY": self.api_key}
        ) as response:
            data = await response.json()
            
            balances = {b["asset"]: b for b in data.get("balances", [])}
            
            return Account(
                broker=BrokerType.BINANCE,
                account_id=str(data.get("accountId", "0")),
                balance=Decimal(balances.get("USDT", {}).get("free", "0")),
                equity=Decimal("0"),  # Calculate from balances
                margin_used=Decimal("0"),
                margin_available=Decimal(balances.get("USDT", {}).get("free", "0")),
                open_positions={},
                daily_pnl=Decimal("0"),
                total_pnl=Decimal("0")
            )
    
    async def submit_order(self, order: Order) -> Order:
        """Submit order."""
        import time
        import hmac
        import hashlib
        
        side = "BUY" if order.direction == TradeDirection.LONG else "SELL"
        
        params = {
            "symbol": order.symbol.replace("/", ""),
            "side": side,
            "type": "MARKET" if order.order_type.value == "MARKET" else "LIMIT",
            "quantity": float(order.quantity),
            "timestamp": int(time.time() * 1000)
        }
        
        if order.price and order.order_type.value == "LIMIT":
            params["price"] = float(order.price)
            params["timeInForce"] = "GTC"
        
        # Sign request
        query_string = "&".join([f"{k}={v}" for k, v in params.items()])
        signature = hmac.new(
            self.secret.encode(),
            query_string.encode(),
            hashlib.sha256
        ).hexdigest()
        
        url = f"{self._base_url}/api/v3/order?{query_string}&signature={signature}"
        
        async with self._session.post(
            url,
            headers={"X-MBX-APIKEY": self.api_key}
        ) as response:
            data = await response.json()
            
            order.broker_id = str(data.get("orderId", 0))
            order.status = (
                OrderStatus.FILLED 
                if data.get("status") == "FILLED" 
                else OrderStatus.SUBMITTED
            )
            
            return order
    
    async def cancel_order(self, order_id: str) -> bool:
        """Cancel order."""
        # Implementation similar to submit_order
        return True
    
    async def get_positions(self) -> list[Position]:
        """Get open positions."""
        # Binance doesn't have traditional positions for spot
        return []
    
    async def get_quote(self, symbol: str) -> TickData:
        """Get ticker."""
        url = f"{self._base_url}/api/v3/ticker/bookTicker?symbol={symbol.replace('/', '')}"
        
        async with self._session.get(url) as response:
            data = await response.json()
            
            return TickData(
                symbol=symbol,
                bid=Decimal(data.get("bidPrice", "0")),
                ask=Decimal(data.get("askPrice", "0")),
                mid=(Decimal(data.get("bidPrice", "0")) + Decimal(data.get("askPrice", "0"))) / 2,
                volume=0,
                source="BINANCE"
            )
    
    async def stream_quotes(self, symbols: list[str], callback: Any) -> None:
        """Use WebSocketFeed instead."""
        pass

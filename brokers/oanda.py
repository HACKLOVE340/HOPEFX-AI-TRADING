"""
OANDA v20 API implementation.
"""

import asyncio
from decimal import Decimal
from typing import Any

import aiohttp
from oandapyV20 import API
from oandapyV20.endpoints import accounts, orders, pricing, positions
from oandapyV20.exceptions import V20Error

from src.brokers.base import Broker
from src.core.config import settings
from src.core.exceptions import BrokerError, BrokerConnectionError
from src.domain.enums import BrokerType, OrderStatus, TradeDirection
from src.domain.models import Account, Order, Position, TickData


class OandaBroker(Broker):
    """
    OANDA v20 REST API implementation.
    """
    
    def __init__(self, credentials: dict[str, Any] | None = None):
        creds = credentials or {
            "api_key": settings.broker.oanda_api_key,
            "account_id": settings.broker.oanda_account_id,
            "environment": settings.broker.oanda_environment
        }
        super().__init__(BrokerType.OANDA, creds)
        
        self.api: API | None = None
        self._session: aiohttp.ClientSession | None = None
    
    async def connect(self) -> bool:
        """Connect to OANDA."""
        try:
            self.api = API(
                access_token=self.credentials["api_key"],
                environment=self.credentials["environment"]
            )
            
            # Test connection
            r = accounts.AccountDetails(self.credentials["account_id"])
            self.api.request(r)
            
            self._connected = True
            return True
            
        except V20Error as e:
            raise BrokerConnectionError(f"OANDA connection failed: {e}")
    
    async def disconnect(self) -> None:
        """Disconnect."""
        self._connected = False
        if self._session:
            await self._session.close()
    
    async def get_account(self) -> Account:
        """Get account details."""
        r = accounts.AccountSummary(self.credentials["account_id"])
        response = self.api.request(r)
        
        account_data = response["account"]
        
        return Account(
            broker=BrokerType.OANDA,
            account_id=self.credentials["account_id"],
            balance=Decimal(account_data["balance"]),
            equity=Decimal(account_data["NAV"]),
            margin_used=Decimal(account_data["marginUsed"]),
            margin_available=Decimal(account_data["marginAvailable"]),
            open_positions={},
            daily_pnl=Decimal("0"),  # Calculate from transactions
            total_pnl=Decimal(account_data["pl"]),
            max_drawdown=Decimal("0")
        )
    
    async def submit_order(self, order: Order) -> Order:
        """Submit order to OANDA."""
        # Convert to OANDA format
        units = str(int(order.quantity)) if order.direction == TradeDirection.LONG else str(-int(order.quantity))
        
        order_data = {
            "order": {
                "type": "MARKET" if order.order_type.value == "MARKET" else "LIMIT",
                "instrument": order.symbol.replace("/", "_"),
                "units": units,
                "timeInForce": "FOK" if order.time_in_force.value == "FOK" else "GTC"
            }
        }
        
        if order.price and order.order_type.value == "LIMIT":
            order_data["order"]["price"] = str(order.price)
        
        r = orders.OrderCreate(self.credentials["account_id"], data=order_data)
        
        try:
            response = self.api.request(r)
            order.broker_id = response["orderFillTransaction"]["id"]
            order.status = OrderStatus.FILLED
            return order
        except V20Error as e:
            order.status = OrderStatus.REJECTED
            raise BrokerError(f"Order rejected: {e}")
    
    async def cancel_order(self, order_id: str) -> bool:
        """Cancel pending order."""
        r = orders.OrderCancel(self.credentials["account_id"], orderID=order_id)
        try:
            self.api.request(r)
            return True
        except V20Error:
            return False
    
    async def get_positions(self) -> list[Position]:
        """Get open positions."""
        r = positions.OpenPositions(self.credentials["account_id"])
        response = self.api.request(r)
        
        positions_list = []
        for pos in response.get("positions", []):
            direction = TradeDirection.LONG if Decimal(pos["long"]["units"]) > 0 else TradeDirection.SHORT
            positions_list.append(Position(
                symbol=pos["instrument"].replace("_", "/"),
                direction=direction,
                entry_price=Decimal(pos.get("averagePrice", "0")),
                quantity=Decimal(pos["long"]["units"] or pos["short"]["units"]),
                unrealized_pnl=Decimal(pos["unrealizedPL"])
            ))
        
        return positions_list
    
    async def get_quote(self, symbol: str) -> TickData:
        """Get current price."""
        formatted_symbol = symbol.replace("/", "_")
        r = pricing.PricingInfo(
            self.credentials["account_id"],
            params={"instruments": formatted_symbol}
        )
        
        response = self.api.request(r)
        price = response["prices"][0]
        
        return TickData(
            symbol=symbol,
            bid=Decimal(price["bids"][0]["price"]),
            ask=Decimal(price["asks"][0]["price"]),
            mid=(Decimal(price["bids"][0]["price"]) + Decimal(price["asks"][0]["price"])) / 2,
            volume=0,
            source="OANDA"
        )
    
    async def stream_quotes(self, symbols: list[str], callback: callable) -> None:
        """Stream prices via WebSocket."""
        # OANDA uses polling for streaming in v20
        formatted_symbols = [s.replace("/", "_") for s in symbols]
        
        while self._connected:
            try:
                params = {"instruments": ",".join(formatted_symbols)}
                r = pricing.PricingInfo(self.credentials["account_id"], params=params)
                response = self.api.request(r)
                
                for price in response.get("prices", []):
                    tick = TickData(
                        symbol=price["instrument"].replace("_", "/"),
                        bid=Decimal(price["bids"][0]["price"]),
                        ask=Decimal(price["asks"][0]["price"]),
                        mid=(Decimal(price["bids"][0]["price"]) + Decimal(price["asks"][0]["price"])) / 2,
                        volume=0,
                        source="OANDA"
                    )
                    await callback(tick)
                
                await asyncio.sleep(1)  # Rate limit
                
            except Exception as e:
                print(f"Streaming error: {e}")
                await asyncio.sleep(5) 

# Alias expected by tests
OANDAConnector = OandaBroker

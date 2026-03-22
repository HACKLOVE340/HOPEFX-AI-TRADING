"""
MetaTrader 5 broker implementation via ZeroMQ.
"""

from decimal import Decimal
from typing import Any

import zmq.asyncio

from src.brokers.base import Broker
from src.core.config import settings
from src.core.exceptions import BrokerError, BrokerConnectionError
from src.domain.enums import BrokerType, OrderStatus, TradeDirection
from src.domain.models import Account, Order, Position, TickData


class MT5Broker(Broker):
    """
    MetaTrader 5 broker via ZeroMQ bridge.
    """
    
    def __init__(
        self,
        host: str = "localhost",
        port: int = 15556,
        credentials: dict[str, Any] | None = None
    ):
        super().__init__(BrokerType.META_TRADER_5, credentials or {})
        
        self.host = host
        self.port = port
        self._ctx: zmq.asyncio.Context | None = None
        self._socket: zmq.asyncio.Socket | None = None
    
    async def connect(self) -> bool:
        """Connect to MT5."""
        try:
            self._ctx = zmq.asyncio.Context()
            self._socket = self._ctx.socket(zmq.REQ)
            self._socket.connect(f"tcp://{self.host}:{self.port}")
            
            # Test connection
            response = await self._send_command("PING")
            if response.get("status") != "ok":
                raise BrokerConnectionError("MT5 ping failed")
            
            self._connected = True
            return True
            
        except Exception as e:
            raise BrokerConnectionError(f"MT5 connection failed: {e}")
    
    async def disconnect(self) -> None:
        """Disconnect."""
        if self._socket:
            self._socket.close()
        if self._ctx:
            self._ctx.term()
        self._connected = False
    
    async def get_account(self) -> Account:
        """Get account info."""
        response = await self._send_command("ACCOUNT_INFO")
        data = response.get("data", {})
        
        return Account(
            broker=BrokerType.META_TRADER_5,
            account_id=str(data.get("login", "0")),
            balance=Decimal(str(data.get("balance", 0))),
            equity=Decimal(str(data.get("equity", 0))),
            margin_used=Decimal(str(data.get("margin", 0))),
            margin_available=Decimal(str(data.get("margin_free", 0))),
            open_positions={},
            daily_pnl=Decimal("0"),
            total_pnl=Decimal(str(data.get("profit", 0)))
        )
    
    async def submit_order(self, order: Order) -> Order:
        """Send order to MT5."""
        direction = 0 if order.direction == TradeDirection.BUY else 1
        
        response = await self._send_command("ORDER_SEND", {
            "symbol": order.symbol,
            "type": direction,
            "volume": float(order.quantity),
            "price": float(order.price) if order.price else 0,
            "sl": 0,
            "tp": 0,
            "comment": f"HOPEFX_{order.strategy_id}"
        })
        
        if response.get("status") == "ok":
            result = response.get("data", {})
            order.broker_id = str(result.get("ticket", 0))
            order.status = OrderStatus.FILLED if result.get("retcode") == 10009 else OrderStatus.REJECTED
        else:
            order.status = OrderStatus.REJECTED
        
        return order
    
    async def cancel_order(self, order_id: str) -> bool:
        """Cancel order."""
        response = await self._send_command("ORDER_CANCEL", {
            "ticket": int(order_id)
        })
        return response.get("status") == "ok"
    
    async def get_positions(self) -> list[Position]:
        """Get open positions."""
        response = await self._send_command("POSITIONS_GET")
        positions_data = response.get("data", [])
        
        positions = []
        for p in positions_data:
            direction = TradeDirection.LONG if p["type"] == 0 else TradeDirection.SHORT
            positions.append(Position(
                symbol=p["symbol"],
                direction=direction,
                entry_price=Decimal(str(p["price_open"])),
                quantity=Decimal(str(p["volume"])),
                unrealized_pnl=Decimal(str(p["profit"]))
            ))
        
        return positions
    
    async def get_quote(self, symbol: str) -> TickData:
        """Get current price."""
        response = await self._send_command("MARKET_BOOK_GET", {"symbol": symbol})
        data = response.get("data", {})
        
        return TickData(
            symbol=symbol,
            bid=Decimal(str(data.get("bid", 0))),
            ask=Decimal(str(data.get("ask", 0))),
            mid=(Decimal(str(data.get("bid", 0))) + Decimal(str(data.get("ask", 0)))) / 2,
            volume=0,
            source="MT5"
        )
    
    async def stream_quotes(self, symbols: list[str], callback: Any) -> None:
        """Streaming handled by MT5Bridge."""
        pass
    
    async def _send_command(self, command: str, params: dict | None = None) -> dict:
        """Send command to MT5."""
        import json
        
        request = {
            "command": command,
            "params": params or {}
        }
        
        await self._socket.send_string(json.dumps(request))
        response = await self._socket.recv_string()
        return json.loads(response)

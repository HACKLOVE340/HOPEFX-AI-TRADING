"""
Interactive Brokers TWS/Gateway implementation.
"""

from decimal import Decimal
from typing import Any

from ib_insync import IB, Forex, MarketOrder

from src.brokers.base import Broker
from src.core.config import settings
from src.core.exceptions import BrokerConnectionError, BrokerError
from src.domain.enums import BrokerType, OrderStatus, TradeDirection
from src.domain.models import Account, Order, Position, TickData


class InteractiveBrokers(Broker):
    """
    Interactive Brokers implementation using ib_insync.
    """
    
    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 7497,  # TWS: 7496, Gateway: 4002
        client_id: int = 1,
        credentials: dict[str, Any] | None = None
    ):
        super().__init__(BrokerType.INTERACTIVE_BROKERS, credentials or {})
        
        self.host = host
        self.port = port
        self.client_id = client_id
        self._ib = IB()
    
    async def connect(self) -> bool:
        """Connect to TWS/Gateway."""
        try:
            self._ib.connect(self.host, self.port, clientId=self.client_id)
            self._connected = self._ib.isConnected()
            return self._connected
            
        except Exception as e:
            raise BrokerConnectionError(f"IB connection failed: {e}")
    
    async def disconnect(self) -> None:
        """Disconnect."""
        self._ib.disconnect()
        self._connected = False
    
    async def get_account(self) -> Account:
        """Get account summary."""
        account_values = self._ib.accountSummary()
        
        values = {av.tag: av.value for av in account_values}
        
        return Account(
            broker=BrokerType.INTERACTIVE_BROKERS,
            account_id=values.get("AccountCode", "Unknown"),
            balance=Decimal(values.get("CashBalance", "0")),
            equity=Decimal(values.get("NetLiquidation", "0")),
            margin_used=Decimal(values.get("InitMarginReq", "0")),
            margin_available=Decimal(values.get("AvailableFunds", "0")),
            open_positions={},
            daily_pnl=Decimal(values.get("RealizedPnL", "0")),
            total_pnl=Decimal(values.get("UnrealizedPnL", "0"))
        )
    
    async def submit_order(self, order: Order) -> Order:
        """Submit order."""
        # Create contract
        contract = Forex(order.symbol.replace("/", ""))
        self._ib.qualifyContracts(contract)
        
        # Create IB order
        ib_order = MarketOrder(
            "BUY" if order.direction == TradeDirection.LONG else "SELL",
            float(order.quantity)
        )
        
        # Place order
        trade = self._ib.placeOrder(contract, ib_order)
        
        order.broker_id = str(trade.order.orderId)
        order.status = OrderStatus.SUBMITTED
        
        return order
    
    async def cancel_order(self, order_id: str) -> bool:
        """Cancel order."""
        try:
            self._ib.cancelOrder(int(order_id))
            return True
        except Exception:
            return False
    
    async def get_positions(self) -> list[Position]:
        """Get positions."""
        ib_positions = self._ib.positions()
        
        positions = []
        for p in ib_positions:
            direction = TradeDirection.LONG if p.position > 0 else TradeDirection.SHORT
            positions.append(Position(
                symbol=p.contract.symbol + "/" + p.contract.currency,
                direction=direction,
                entry_price=Decimal(str(p.avgCost)),
                quantity=Decimal(str(abs(p.position))),
                unrealized_pnl=Decimal("0")  # Would need to calculate
            ))
        
        return positions
    
    async def get_quote(self, symbol: str) -> TickData:
        """Get quote."""
        contract = Forex(symbol.replace("/", ""))
        self._ib.qualifyContracts(contract)
        
        # Request market data
        ticker = self._ib.reqMktData(contract, '', False, False)
        self._ib.sleep(1)  # Wait for data
        
        return TickData(
            symbol=symbol,
            bid=Decimal(str(ticker.bid)) if ticker.bid else Decimal("0"),
            ask=Decimal(str(ticker.ask)) if ticker.ask else Decimal("0"),
            mid=Decimal(str(ticker.midpoint())) if ticker.midpoint else Decimal("0"),
            volume=int(ticker.volume) if ticker.volume else 0,
            source="IBKR"
        )
    
    async def stream_quotes(self, symbols: list[str], callback: Any) -> None:
        """Stream quotes."""
        for symbol in symbols:
            contract = Forex(symbol.replace("/", ""))
            self._ib.qualifyContracts(contract)
            
            ticker = self._ib.reqMktData(contract)
            
            def on_tick(t):
                asyncio.create_task(callback(TickData(
                    symbol=symbol,
                    bid=Decimal(str(t.bid)) if t.bid else Decimal("0"),
                    ask=Decimal(str(t.ask)) if t.ask else Decimal("0"),
                    mid=Decimal(str(t.midpoint())) if t.midpoint else Decimal("0"),
                    volume=0,
                    source="IBKR"
                )))
            
            ticker.updateEvent += on_tick

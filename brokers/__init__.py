
# 3. BROKER MODULE - Paper trading and live broker support

broker_code = '''"""
HOPEFX Broker Module
Unified interface for paper trading and live broker integration
Supports: Paper trading (simulation), OANDA, Interactive Brokers
"""

import asyncio
import logging
import time
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
import random
import aiohttp

logger = logging.getLogger(__name__)

class OrderType(Enum):
    MARKET = "market"
    LIMIT = "limit"
    STOP = "stop"
    STOP_LIMIT = "stop_limit"

class OrderSide(Enum):
    BUY = "buy"
    SELL = "sell"

class OrderStatus(Enum):
    PENDING = "pending"
    FILLED = "filled"
    PARTIAL = "partial"
    CANCELLED = "cancelled"
    REJECTED = "rejected"

@dataclass
class Order:
    id: str
    symbol: str
    side: OrderSide
    type: OrderType
    quantity: float
    price: Optional[float] = None
    stop_price: Optional[float] = None
    status: OrderStatus = OrderStatus.PENDING
    filled_quantity: float = 0.0
    average_fill_price: float = 0.0
    created_at: float = field(default_factory=time.time)
    filled_at: Optional[float] = None
    
@dataclass
class Position:
    id: str
    symbol: str
    side: OrderSide
    quantity: float
    entry_price: float
    current_price: float
    unrealized_pnl: float
    realized_pnl: float = 0.0
    opened_at: float = field(default_factory=time.time)
    
    @property
    def market_value(self) -> float:
        return self.quantity * self.current_price
    
    @property
    def total_pnl(self) -> float:
        return self.unrealized_pnl + self.realized_pnl

class BaseBroker:
    """Abstract base class for all brokers"""
    
    async def connect(self):
        raise NotImplementedError
    
    async def disconnect(self):
        raise NotImplementedError
    
    async def get_account_info(self) -> Dict:
        raise NotImplementedError
    
    async def place_order(self, order: Order) -> Order:
        raise NotImplementedError
    
    async def cancel_order(self, order_id: str) -> bool:
        raise NotImplementedError
    
    async def get_positions(self) -> List[Position]:
        raise NotImplementedError
    
    async def close_position(self, position_id: str) -> bool:
        raise NotImplementedError
    
    async def get_pending_orders(self) -> List[Order]:
        raise NotImplementedError

class PaperTradingBroker(BaseBroker):
    """
    Realistic paper trading simulation
    - Simulates slippage and latency
    - Tracks P&L accurately
    - Handles partial fills
    """
    
    def __init__(self, initial_balance: float = 100000.0):
        self.initial_balance = initial_balance
        self.balance = initial_balance
        self.equity = initial_balance
        
        self.orders: Dict[str, Order] = {}
        self.positions: Dict[str, Position] = {}
        self.order_history: List[Order] = []
        self.trade_history: List[Dict] = []
        
        self.price_feed: Optional[Any] = None  # Injected price engine
        self.connected = False
        
        # Simulation parameters
        self.slippage_std = 0.0001  # 1 pip standard deviation
        self.latency_ms = 50  # 50ms simulated latency
        self.partial_fill_prob = 0.1  # 10% chance of partial fill
        
        logger.info(f"PaperTradingBroker initialized with ${initial_balance:,.2f}")
    
    def set_price_feed(self, price_engine):
        """Inject price feed"""
        self.price_feed = price_engine
    
    async def connect(self):
        self.connected = True
        logger.info("PaperTradingBroker connected (simulation)")
        return True
    
    async def disconnect(self):
        self.connected = False
        logger.info("PaperTradingBroker disconnected")
        return True
    
    async def get_account_info(self) -> Dict:
        """Get current account status"""
        # Calculate equity
        total_unrealized = sum(p.unrealized_pnl for p in self.positions.values())
        self.equity = self.balance + total_unrealized
        
        margin_used = sum(p.market_value for p in self.positions.values()) * 0.02  # 2% margin
        
        return {
            'balance': self.balance,
            'equity': self.equity,
            'margin_used': margin_used,
            'free_margin': self.equity - margin_used,
            'unrealized_pnl': total_unrealized,
            'realized_pnl': self.equity - self.initial_balance - total_unrealized,
            'open_positions': len(self.positions)
        }
    
    async def place_market_order(self, symbol: str, side: str, quantity: float) -> Order:
        """Place a market order with realistic simulation"""
        await asyncio.sleep(self.latency_ms / 1000)  # Simulate latency
        
        # Get current price
        if not self.price_feed:
            raise ValueError("No price feed available")
        
        tick = self.price_feed.get_last_price(symbol)
        if not tick:
            raise ValueError(f"No price available for {symbol}")
        
        # Apply slippage
        slippage = random.gauss(0, self.slippage_std)
        if side == 'buy':
            fill_price = tick.ask * (1 + slippage)
        else:
            fill_price = tick.bid * (1 - slippage)
        
        # Create order
        order = Order(
            id=f"paper_{int(time.time()*1000)}_{random.randint(1000,9999)}",
            symbol=symbol,
            side=OrderSide(side),
            type=OrderType.MARKET,
            quantity=quantity,
            price=fill_price
        )
        
        # Simulate partial fill
        if random.random() < self.partial_fill_prob:
            order.filled_quantity = quantity * random.uniform(0.5, 0.99)
            order.status = OrderStatus.PARTIAL
        else:
            order.filled_quantity = quantity
            order.status = OrderStatus.FILLED
            order.filled_at = time.time()
        
        order.average_fill_price = fill_price
        
        # Store order
        self.orders[order.id] = order
        self.order_history.append(order)
        
        # Update positions
        await self._update_position(order)
        
        logger.info(f"Paper order executed: {side} {quantity} {symbol} @ {fill_price:.5f}")
        return order
    
    async def place_order(self, order: Order) -> Order:
        """Place any order type"""
        if order.type == OrderType.MARKET:
            return await self.place_market_order(
                order.symbol, order.side.value, order.quantity
            )
        else:
            # For limit/stop orders, store as pending
            order.id = f"paper_{int(time.time()*1000)}"
            order.status = OrderStatus.PENDING
            self.orders[order.id] = order
            logger.info(f"Paper pending order: {order.type.value} {order.side.value} {order.quantity} {order.symbol}")
            return order
    
    async def cancel_order(self, order_id: str) -> bool:
        """Cancel a pending order"""
        if order_id in self.orders:
            order = self.orders[order_id]
            if order.status == OrderStatus.PENDING:
                order.status = OrderStatus.CANCELLED
                logger.info(f"Paper order cancelled: {order_id}")
                return True
        return False
    
    async def get_positions(self) -> List[Position]:
        """Get all open positions"""
        # Update position prices
        for pos in self.positions.values():
            if self.price_feed:
                tick = self.price_feed.get_last_price(pos.symbol)
                if tick:
                    pos.current_price = tick.mid
                    # Recalculate P&L
                    if pos.side == OrderSide.BUY:
                        pos.unrealized_pnl = (pos.current_price - pos.entry_price) * pos.quantity
                    else:
                        pos.unrealized_pnl = (pos.entry_price - pos.current_price) * pos.quantity
        
        return list(self.positions.values())
    
    async def close_position(self, position_id: str) -> bool:
        """Close a position"""
        if position_id not in self.positions:
            return False
        
        pos = self.positions[position_id]
        
        # Place opposite order to close
        close_side = 'sell' if pos.side == OrderSide.BUY else 'buy'
        order = await self.place_market_order(pos.symbol, close_side, pos.quantity)
        
        # Realize P&L
        realized_pnl = pos.unrealized_pnl
        self.balance += realized_pnl
        
        # Record trade
        self.trade_history.append({
            'position_id': position_id,
            'symbol': pos.symbol,
            'entry_price': pos.entry_price,
            'exit_price': order.average_fill_price,
            'pnl': realized_pnl,
            'closed_at': time.time()
        })
        
        # Remove position
        del self.positions[position_id]
        
        logger.info(f"Position closed: {position_id} P&L: ${realized_pnl:,.2f}")
        return True
    
    async def close_all_positions(self) -> List[str]:
        """Close all positions"""
        closed = []
        for pos_id in list(self.positions.keys()):
            if await self.close_position(pos_id):
                closed.append(pos_id)
        return closed
    
    async def get_pending_orders(self) -> List[Order]:
        """Get pending orders"""
        return [o for o in self.orders.values() if o.status == OrderStatus.PENDING]
    
    async def cancel_all_orders(self) -> List[str]:
        """Cancel all pending orders"""
        cancelled = []
        for order_id, order in self.orders.items():
            if order.status == OrderStatus.PENDING:
                order.status = OrderStatus.CANCELLED
                cancelled.append(order_id)
        return cancelled
    
    async def _update_position(self, order: Order):
        """Update positions based on filled order"""
        if order.status not in [OrderStatus.FILLED, OrderStatus.PARTIAL]:
            return
        
        # Find existing position
        position_key = f"{order.symbol}_{order.side.value}"
        
        if position_key in self.positions:
            # Update existing position
            pos = self.positions[position_key]
            total_quantity = pos.quantity + order.filled_quantity
            pos.entry_price = (pos.entry_price * pos.quantity + order.average_fill_price * order.filled_quantity) / total_quantity
            pos.quantity = total_quantity
        else:
            # Create new position
            self.positions[position_key] = Position(
                id=position_key,
                symbol=order.symbol,
                side=order.side,
                quantity=order.filled_quantity,
                entry_price=order.average_fill_price,
                current_price=order.average_fill_price,
                unrealized_pnl=0.0
            )
        
        # Deduct balance for buys (simplified)
        if order.side == OrderSide.BUY:
            cost = order.filled_quantity * order.average_fill_price
            self.balance -= cost

class OANDABroker(BaseBroker):
    """OANDA v20 API implementation"""
    
    def __init__(self, api_key: str, account_id: str, practice: bool = True):
        self.api_key = api_key
        self.account_id = account_id
        self.practice = practice
        self.base_url = "https://api-fxpractice.oanda.com" if practice else "https://api-fxtrade.oanda.com"
        self.session: Optional[aiohttp.ClientSession] = None
        
    async def connect(self):
        self.session = aiohttp.ClientSession(
            headers={"Authorization": f"Bearer {self.api_key}"}
        )
        # Verify connection
        async with self.session.get(f"{self.base_url}/v3/accounts/{self.account_id}") as resp:
            if resp.status != 200:
                raise ConnectionError("Failed to connect to OANDA")
        logger.info("OANDA broker connected")
        return True
    
    async def disconnect(self):
        if self.session:
            await self.session.close()
        return True
    
    async def get_account_info(self) -> Dict:
        async with self.session.get(f"{self.base_url}/v3/accounts/{self.account_id}") as resp:
            data = await resp.json()
            account = data.get('account', {})
            return {
                'balance': float(account.get('balance', 0)),
                'equity': float(account.get('NAV', 0)),
                'margin_used': float(account.get('marginUsed', 0)),
                'free_margin': float(account.get('marginAvailable', 0)),
                'unrealized_pnl': float(account.get('unrealizedPL', 0)),
                'realized_pnl': float(account.get('realizedPL', 0))
            }
    
    async def place_market_order(self, symbol: str, side: str, quantity: float) -> Order:
        # OANDA uses units and instrument formatting
        instrument = symbol.replace('/', '_')
        units = quantity if side == 'buy' else -quantity
        
        body = {
            "order": {
                "type": "MARKET",
                "instrument": instrument,
                "units": str(int(units))
            }
        }
        
        async with self.session.post(
            f"{self.base_url}/v3/accounts/{self.account_id}/orders",
            json=body
        ) as resp:
            data = await resp.json()
            
            if resp.status != 201:
                raise ValueError(f"Order failed: {data}")
            
            order_data = data.get('orderFillTransaction', {})
            return Order(
                id=order_data.get('id', ''),
                symbol=symbol,
                side=OrderSide(side),
                type=OrderType.MARKET,
                quantity=quantity,
                price=float(order_data.get('price', 0)),
                status=OrderStatus.FILLED,
                filled_quantity=quantity,
                average_fill_price=float(order_data.get('price', 0)),
                filled_at=time.time()
            )
    
    async def get_positions(self) -> List[Position]:
        async with self.session.get(f"{self.base_url}/v3/accounts/{self.account_id}/positions") as resp:
            data = await resp.json()
            positions = []
            for pos in data.get('positions', []):
                # Parse long and short positions
                for side in ['long', 'short']:
                    side_data = pos.get(side, {})
                    if side_data and float(side_data.get('units', 0)) != 0:
                        positions.append(Position(
                            id=f"{pos['instrument']}_{side}",
                            symbol=pos['instrument'].replace('_', '/'),
                            side=OrderSide.BUY if side == 'long' else OrderSide.SELL,
                            quantity=abs(float(side_data.get('units', 0))),
                            entry_price=float(side_data.get('averagePrice', 0)),
                            current_price=float(side_data.get('markPrice', 0)),
                            unrealized_pnl=float(side_data.get('unrealizedPL', 0))
                        ))
            return positions
    
    async def close_position(self, position_id: str) -> bool:
        # Extract instrument and side from position_id
        parts = position_id.rsplit('_', 1)
        if len(parts) != 2:
            return False
        
        instrument, side = parts
        instrument = instrument.replace('/', '_')
        
        # Close all units on that side
        async with self.session.put(
            f"{self.base_url}/v3/accounts/{self.account_id}/positions/{instrument}/close",
            json={"longUnits": "ALL" if side == 'long' else "NONE",
                  "shortUnits": "ALL" if side == 'short' else "NONE"}
        ) as resp:
            return resp.status == 200

# Factory function
def create_broker(broker_type: str, config: Dict) -> BaseBroker:
    """Create appropriate broker instance"""
    if broker_type == 'paper':
        return PaperTradingBroker(config.get('initial_balance', 100000.0))
    elif broker_type == 'oanda':
        return OANDABroker(
            api_key=config['api_key'],
            account_id=config['account_id'],
            practice=config.get('practice', True)
        )
    else:
        raise ValueError(f"Unknown broker type: {broker_type}")
'''

with open(project_root / "brokers" / "__init__.py", "w") as f:
    f.write(broker_code)

print("✓ Created brokers/__init__.py with PaperTrading and OANDA support")

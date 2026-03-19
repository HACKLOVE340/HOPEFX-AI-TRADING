"""
HOPEFX Broker Module - PRODUCTION VERSION
Fixed: Thread safety, proper position tracking, realistic simulation, timeouts
"""

import asyncio
import logging
import time
import uuid
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
import random

try:
    import aiohttp
    AIOHTTP_AVAILABLE = True
except ImportError:
    AIOHTTP_AVAILABLE = False
    logging.warning("aiohttp not available, OANDA broker disabled")

try:
    import numpy as np
    NUMPY_AVAILABLE = True
except ImportError:
    NUMPY_AVAILABLE = False

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
    ERROR = "error"


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
    rejected_reason: Optional[str] = None
    commission: float = 0.0
    slippage: float = 0.0
    
    @property
    def remaining_quantity(self) -> float:
        return self.quantity - self.filled_quantity
    
    @property
    def is_complete(self) -> bool:
        return self.status in (OrderStatus.FILLED, OrderStatus.CANCELLED, OrderStatus.REJECTED)
    
    def to_dict(self) -> Dict:
        return {
            'id': self.id,
            'symbol': self.symbol,
            'side': self.side.value,
            'type': self.type.value,
            'quantity': self.quantity,
            'price': self.price,
            'status': self.status.value,
            'filled_quantity': self.filled_quantity,
            'average_fill_price': self.average_fill_price,
            'commission': self.commission,
            'slippage': self.slippage,
            'created_at': self.created_at
        }


@dataclass
class Position:
    id: str
    symbol: str
    side: OrderSide
    quantity: float
    entry_price: float
    current_price: float
    unrealized_pnl: float = 0.0
    realized_pnl: float = 0.0
    opened_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    total_commission: float = 0.0
    
    @property
    def market_value(self) -> float:
        return self.quantity * self.current_price
    
    @property
    def total_pnl(self) -> float:
        return self.unrealized_pnl + self.realized_pnl
    
    def update_price(self, new_price: float):
        """Update position with new price"""
        self.current_price = new_price
        self.updated_at = time.time()
        
        if self.side == OrderSide.BUY:
            self.unrealized_pnl = (new_price - self.entry_price) * self.quantity
        else:
            self.unrealized_pnl = (self.entry_price - new_price) * self.quantity
    
    def to_dict(self) -> Dict:
        return {
            'id': self.id,
            'symbol': self.symbol,
            'side': self.side.value,
            'quantity': self.quantity,
            'entry_price': self.entry_price,
            'current_price': self.current_price,
            'unrealized_pnl': self.unrealized_pnl,
            'realized_pnl': self.realized_pnl,
            'total_pnl': self.total_pnl,
            'market_value': self.market_value,
            'opened_at': self.opened_at
        }


class BaseBroker:
    """Abstract base class with proper interface and connection management"""
    
    def __init__(self):
        self.connected = False
        self._lock = asyncio.Lock()
        self._session = None
        self._connection_lock = asyncio.Lock()
    
    async def connect(self):
        raise NotImplementedError
    
    async def disconnect(self):
        raise NotImplementedError
    
    async def get_account_info(self) -> Dict:
        raise NotImplementedError
    
    async def place_market_order(self, symbol: str, side: str, quantity: float) -> Order:
        raise NotImplementedError
    
    async def cancel_order(self, order_id: str) -> bool:
        raise NotImplementedError
    
    async def get_positions(self) -> List[Position]:
        raise NotImplementedError
    
    async def close_position(self, position_id: str) -> bool:
        raise NotImplementedError
    
    async def close_all_positions(self) -> List[str]:
        """Close all positions with error tracking"""
        positions = await self.get_positions()
        closed = []
        failed = []
        
        for pos in positions:
            try:
                if await self.close_position(pos.id):
                    closed.append(pos.id)
                else:
                    failed.append(pos.id)
            except Exception as e:
                logger.error(f"Failed to close position {pos.id}: {e}")
                failed.append(pos.id)
        
        if failed:
            logger.warning(f"Failed to close {len(failed)} positions: {failed}")
        
        return closed
    
    async def get_pending_orders(self) -> List[Order]:
        raise NotImplementedError
    
    async def cancel_all_orders(self) -> List[str]:
        """Cancel all pending orders with error tracking"""
        orders = await self.get_pending_orders()
        cancelled = []
        failed = []
        
        for order in orders:
            try:
                if await self.cancel_order(order.id):
                    cancelled.append(order.id)
                else:
                    failed.append(order.id)
            except Exception as e:
                logger.error(f"Failed to cancel order {order.id}: {e}")
                failed.append(order.id)
        
        return cancelled


class PaperTradingBroker(BaseBroker):
    """
    PRODUCTION-GRADE Paper Trading Simulation
    
    Features:
    - Thread-safe position/order management (asyncio.Lock)
    - Realistic slippage model (Gaussian distribution)
    - Commission calculation per lot
    - Partial fill simulation for large orders
    - Comprehensive P&L tracking
    - Performance reporting
    """
    
    def __init__(
        self,
        initial_balance: float = 100000.0,
        base_currency: str = "USD",
        commission_per_lot: float = 3.5,
        slippage_model: str = "gaussian"
    ):
        super().__init__()
        
        self.initial_balance = initial_balance
        self.balance = initial_balance
        self.equity = initial_balance
        self.base_currency = base_currency
        self.commission_per_lot = commission_per_lot
        self.slippage_model = slippage_model
        
        # THREAD SAFETY: Separate locks for orders and positions
        self._orders_lock = asyncio.Lock()
        self._positions_lock = asyncio.Lock()
        self._account_lock = asyncio.Lock()
        
        # Storage
        self._orders: Dict[str, Order] = {}
        self._positions: Dict[str, Position] = {}
        self._order_history: List[Order] = []
        self._trade_history: List[Dict] = []
        
        self.price_feed = None
        
        # Simulation parameters (calibrated to real market conditions)
        self.slippage_std_pips = 0.5
        self.latency_ms_mean = 150
        self.latency_ms_std = 50
        self.partial_fill_threshold = 100000
        
        # Performance tracking
        self._total_commissions = 0.0
        self._total_slippage = 0.0
        self._start_time = time.time()
        
        logger.info(
            f"PaperTradingBroker initialized | "
            f"Balance: ${initial_balance:,.2f} | "
            f"Commission: ${commission_per_lot}/lot"
        )
    
    def set_price_feed(self, price_engine):
        """Inject price feed"""
        self.price_feed = price_engine
        logger.info("Price feed connected to paper broker")
    
    async def connect(self):
        """Connect to simulation"""
        async with self._connection_lock:
            self.connected = True
        logger.info("PaperTradingBroker connected (simulation mode)")
        return True
    
    async def disconnect(self):
        """Disconnect and generate report"""
        async with self._connection_lock:
            self.connected = False
        
        # Generate final report
        report = self._generate_report()
        logger.info(f"Final Trading Report:\\n{report}")
        return True
    
    async def get_account_info(self) -> Dict:
        """Get account information with proper locking"""
        async with self._positions_lock, self._account_lock:
            # Calculate equity from positions
            total_unrealized = sum(
                p.unrealized_pnl for p in self._positions.values()
            )
            self.equity = self.balance + total_unrealized
            
            # Calculate margin (2% per position)
            margin_used = sum(
                p.market_value * 0.02 for p in self._positions.values()
            )
            
            realized_pnl = self.equity - self.initial_balance - total_unrealized
            
            return {
                'balance': round(self.balance, 2),
                'equity': round(self.equity, 2),
                'margin_used': round(margin_used, 2),
                'free_margin': round(self.equity - margin_used, 2),
                'unrealized_pnl': round(total_unrealized, 2),
                'realized_pnl': round(realized_pnl, 2),
                'open_positions': len(self._positions),
                'total_commissions': round(self._total_commissions, 2),
                'currency': self.base_currency,
                'uptime_seconds': time.time() - self._start_time
            }
    
    async def place_market_order(
        self,
        symbol: str,
        side: str,
        quantity: float
    ) -> Order:
        """
        Place market order with realistic simulation
        
        Simulates:
        1. Network latency (Gaussian distribution)
        2. Slippage (market impact based on order size)
        3. Partial fills for large orders
        4. Commission calculation
        """
        if not self.connected:
            raise ConnectionError("Broker not connected")
        
        if quantity <= 0:
            raise ValueError(f"Quantity must be positive, got {quantity}")
        
        if side not in ('buy', 'sell'):
            raise ValueError(f"Side must be 'buy' or 'sell', got {side}")
        
        # 1. Simulate network latency
        latency_ms = max(0, random.gauss(self.latency_ms_mean, self.latency_ms_std))
        await asyncio.sleep(latency_ms / 1000)
        
        # 2. Get current price
        if not self.price_feed:
            raise ValueError("No price feed available")
        
        tick = self.price_feed.get_last_price(symbol)
        if not tick:
            raise ValueError(f"No price available for {symbol}")
        
        # 3. Calculate slippage
        slippage_pips = self._calculate_slippage(symbol, quantity, side)
        pip_value = self._get_pip_value(symbol)
        slippage_factor = slippage_pips * pip_value
        
        # Apply slippage
        if side == 'buy':
            fill_price = tick.ask * (1 + slippage_factor)
        else:
            fill_price = tick.bid * (1 - slippage_factor)
        
        # 4. Simulate partial fills
        fill_quantity = self._simulate_fill_quantity(quantity, symbol)
        
        # 5. Calculate commission
        lots = fill_quantity / 100000
        commission = lots * self.commission_per_lot * 2  # Round trip
        
        # Create order with unique ID
        order_id = f"paper_{uuid.uuid4().hex[:12]}"
        
        order = Order(
            id=order_id,
            symbol=symbol,
            side=OrderSide(side),
            type=OrderType.MARKET,
            quantity=quantity,
            price=fill_price,
            status=OrderStatus.PARTIAL if fill_quantity < quantity else OrderStatus.FILLED,
            filled_quantity=fill_quantity,
            average_fill_price=fill_price,
            filled_at=time.time(),
            commission=commission,
            slippage=slippage_pips
        )
        
        # Update tracking (with locks)
        async with self._orders_lock:
            self._orders[order_id] = order
            self._order_history.append(order)
        
        async with self._positions_lock:
            await self._update_position(order)
            self._total_commissions += commission
            self._total_slippage += abs(slippage_pips)
        
        logger.info(
            f"Order Executed | {side.upper()} {fill_quantity:.0f}/{quantity:.0f} {symbol} | "
            f"Price: {fill_price:.5f} | Slippage: {slippage_pips:.1f}pips | "
            f"Commission: ${commission:.2f} | ID: {order_id}"
        )
        
        return order
    
    def _calculate_slippage(self, symbol: str, quantity: float, side: str) -> float:
        """Calculate realistic slippage based on order size"""
        if self.slippage_model == "none":
            return 0.0
        
        # Base slippage increases with order size
        base_slippage = 0.1  # 0.1 pips base
        size_factor = min(quantity / 100000, 5.0)
        
        if self.slippage_model == "gaussian":
            slippage = random.gauss(base_slippage * size_factor, 0.2)
        else:
            slippage = random.uniform(0, base_slippage * size_factor * 2)
        
        return max(0, slippage)
    
    def _simulate_fill_quantity(self, quantity: float, symbol: str) -> float:
        """Simulate partial fills for large orders"""
        if quantity < self.partial_fill_threshold:
            return quantity
        
        fill_prob = min(0.95, 0.5 + (self.partial_fill_threshold / quantity))
        
        if random.random() > fill_prob:
            # Partial fill
            return quantity * random.uniform(0.6, 0.95)
        
        return quantity
    
    def _get_pip_value(self, symbol: str) -> float:
        """Get pip value for symbol"""
        if 'JPY' in symbol:
            return 0.01
        if 'XAU' in symbol or 'GOLD' in symbol:
            return 0.01
        return 0.0001
    
    async def _update_position(self, order: Order):
        """Update positions based on filled order - THREAD SAFE (caller must hold lock)"""
        if order.status not in (OrderStatus.FILLED, OrderStatus.PARTIAL):
            return
        
        position_key = f"{order.symbol}_{order.side.value}"
        fill_qty = order.filled_quantity
        fill_price = order.average_fill_price
        
        # Deduct commission from balance
        self.balance -= order.commission
        
        if position_key in self._positions:
            # Update existing position
            pos = self._positions[position_key]
            
            # Calculate new average entry price
            total_qty = pos.quantity + fill_qty
            pos.entry_price = (
                (pos.entry_price * pos.quantity) + (fill_price * fill_qty)
            ) / total_qty
            pos.quantity = total_qty
            pos.total_commission += order.commission
            pos.updated_at = time.time()
            
            logger.debug(f"Updated position {position_key}: Qty={total_qty:.0f}, AvgPrice={pos.entry_price:.5f}")
        else:
            # Create new position
            self._positions[position_key] = Position(
                id=position_key,
                symbol=order.symbol,
                side=order.side,
                quantity=fill_qty,
                entry_price=fill_price,
                current_price=fill_price,
                unrealized_pnl=-order.commission,
                opened_at=time.time(),
                total_commission=order.commission
            )
            
            # For buys, deduct cost from balance
            if order.side == OrderSide.BUY:
                cost = fill_qty * fill_price
                self.balance -= cost
            
            logger.debug(f"New position created: {position_key}")
    
    async def cancel_order(self, order_id: str) -> bool:
        """Cancel a pending order"""
        async with self._orders_lock:
            if order_id not in self._orders:
                return False
            
            order = self._orders[order_id]
            if order.status == OrderStatus.PENDING:
                order.status = OrderStatus.CANCELLED
                logger.info(f"Order cancelled: {order_id}")
                return True
            
            return False
    
    async def get_positions(self) -> List[Position]:
        """Get all open positions with updated prices"""
        async with self._positions_lock:
            positions = list(self._

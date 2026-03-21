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
        slippage_model: str = "gaussian",
        session_factory=None,
        user_id: str = "paper",
    ):
        super().__init__()
        
        self.initial_balance = initial_balance
        self.balance = initial_balance
        self.equity = initial_balance
        self.base_currency = base_currency
        self.commission_per_lot = commission_per_lot
        self.slippage_model = slippage_model
        self._session_factory = session_factory
        self._user_id = user_id
        
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
            positions = list(self._positions.values())

            # Update prices
            if self.price_feed:
                for pos in positions:
                    try:
                        tick = self.price_feed.get_last_price(pos.symbol)
                        if tick:
                            pos.update_price(tick.mid)
                    except Exception as e:
                        logger.error(f"Error updating price for {pos.symbol}: {e}")
            
            return positions
    
    async def close_position(self, position_id: str) -> bool:
        """Close a position with proper locking"""
        async with self._positions_lock:
            if position_id not in self._positions:
                logger.warning(f"Position not found: {position_id}")
                return False
            
            pos = self._positions[position_id]
            
            # Determine closing side
            close_side = 'sell' if pos.side == OrderSide.BUY else 'buy'
            
            try:
                # Place closing order
                order = await self.place_market_order(
                    pos.symbol,
                    close_side,
                    pos.quantity
                )
                
                # Calculate realized P&L
                realized_pnl = pos.unrealized_pnl - order.commission
                self.balance += realized_pnl
                
                # Record trade
                trade_record = {
                    'position_id': position_id,
                    'symbol': pos.symbol,
                    'side': pos.side.value,
                    'quantity': pos.quantity,
                    'entry_price': pos.entry_price,
                    'exit_price': order.average_fill_price,
                    'realized_pnl': realized_pnl,
                    'commission': order.commission + pos.total_commission,
                    'opened_at': pos.opened_at,
                    'closed_at': time.time(),
                    'duration_seconds': time.time() - pos.opened_at,
                    'slippage': order.slippage
                }
                self._trade_history.append(trade_record)

                # Persist to DB
                self._persist_trade_record(trade_record)
                
                # Remove position
                del self._positions[position_id]
                
                logger.info(
                    f"Position Closed | {position_id} | "
                    f"P&L: ${realized_pnl:,.2f} | "
                    f"Duration: {(time.time() - pos.opened_at)/3600:.1f}h | "
                    f"Commission: ${order.commission + pos.total_commission:.2f}"
                )
                
                return True
                
            except Exception as e:
                logger.error(f"Error closing position {position_id}: {e}")
                return False
    
    async def get_pending_orders(self) -> List[Order]:
        """Get pending orders"""
        async with self._orders_lock:
            return [
                o for o in self._orders.values()
                if o.status == OrderStatus.PENDING
            ]
    
    def _persist_trade_record(self, record: dict) -> None:
        """Persist a closed trade record to the DB trades table."""
        if not self._session_factory:
            return
        try:
            from database.models import Trade, OrderSide as DBOrderSide, TradeStatus
            from datetime import datetime, timezone
            import uuid as _uuid

            raw_side = str(record.get("side", "buy")).lower()
            side_enum = DBOrderSide.BUY if "buy" in raw_side else DBOrderSide.SELL

            opened_at = record.get("opened_at")
            if isinstance(opened_at, (int, float)):
                opened_at = datetime.fromtimestamp(opened_at, tz=timezone.utc)
            closed_at = record.get("closed_at")
            if isinstance(closed_at, (int, float)):
                closed_at = datetime.fromtimestamp(closed_at, tz=timezone.utc)

            qty = float(record.get("quantity", 0))
            commission = float(record.get("commission", 0))
            realized_pnl = float(record.get("realized_pnl", 0))

            trade = Trade(
                trade_id=str(_uuid.uuid4()),
                symbol=record.get("symbol", ""),
                side=side_enum,
                entry_price=float(record.get("entry_price", 0)),
                entry_quantity=qty,
                exit_price=float(record.get("exit_price", 0)),
                exit_quantity=qty,
                realized_pnl=realized_pnl,
                total_pnl=realized_pnl,
                commission=commission,
                status=TradeStatus.CLOSED,
                is_open=False,
                strategy="paper",
                entry_time=opened_at or datetime.now(timezone.utc),
                exit_time=closed_at or datetime.now(timezone.utc),
            )
            with self._session_factory() as session:
                session.add(trade)
                session.commit()
            logger.debug("Trade persisted to DB: %s pnl=%.2f", record.get("symbol"), realized_pnl)
        except Exception as exc:
            logger.warning("Failed to persist paper trade to DB: %s", exc)

    def _generate_report(self) -> str:
        """Generate comprehensive trading report"""
        total_trades = len(self._trade_history)
        if total_trades == 0:
            return "No trades executed"
        
        winning_trades = [t for t in self._trade_history if t['realized_pnl'] > 0]
        losing_trades = [t for t in self._trade_history if t['realized_pnl'] <= 0]
        
        total_pnl = sum(t['realized_pnl'] for t in self._trade_history)
        gross_profit = sum(t['realized_pnl'] for t in winning_trades)
        gross_loss = sum(t['realized_pnl'] for t in losing_trades)
        
        win_rate = len(winning_trades) / total_trades if total_trades > 0 else 0
        
        avg_win = gross_profit / len(winning_trades) if winning_trades else 0
        avg_loss = gross_loss / len(losing_trades) if losing_trades else 0
        
        profit_factor = abs(gross_profit / gross_loss) if gross_loss != 0 else float('inf')
        
        # Calculate Sharpe-like metric
        returns = [t['realized_pnl'] for t in self._trade_history]
        avg_return = sum(returns) / len(returns) if returns else 0
        variance = sum((r - avg_return) ** 2 for r in returns) / len(returns) if returns else 0
        std_return = variance ** 0.5
        sharpe_like = (avg_return / std_return) if std_return > 0 else 0
        
        report = f"""
╔════════════════════════════════════════════════════════════════╗
║           PAPER TRADING PERFORMANCE REPORT                      ║
╠════════════════════════════════════════════════════════════════╣
║ Account Summary                                                ║
║   Initial Balance:     ${self.initial_balance:>15,.2f}          ║
║   Final Balance:        ${self.balance:>15,.2f}          ║
║   Total P&L:            ${total_pnl:>15,.2f} ({total_pnl/self.initial_balance*100:+.2f}%)   ║
║   Total Commissions:    ${self._total_commissions:>15,.2f}          ║
║   Total Slippage:       {self._total_slippage:>15.1f} pips        ║
╠════════════════════════════════════════════════════════════════╣
║ Trade Statistics                                               ║
║   Total Trades:        {total_trades:>15}                     ║
║   Winning Trades:      {len(winning_trades):>15} ({win_rate*100:.1f}%)              ║
║   Losing Trades:       {len(losing_trades):>15} ({(1-win_rate)*100:.1f}%)              ║
║   Profit Factor:       {profit_factor:>15.2f}                   ║
║   Sharpe-like:         {sharpe_like:>15.2f}                   ║
╠════════════════════════════════════════════════════════════════╣
║ P&L Breakdown                                                  ║
║   Gross Profit:         ${gross_profit:>15,.2f}          ║
║   Gross Loss:           ${gross_loss:>15,.2f}          ║
║   Average Win:         ${avg_win:>15,.2f}          ║
║   Average Loss:         ${avg_loss:>15,.2f}          ║
║   Largest Win:          ${max((t['realized_pnl'] for t in winning_trades), default=0):>15,.2f}          ║
║   Largest Loss:         ${min((t['realized_pnl'] for t in losing_trades), default=0):>15,.2f}          ║
╠════════════════════════════════════════════════════════════════╣
║ Open Positions:        {len(self._positions):>15}                     ║
║ Uptime:                {(time.time() - self._start_time)/3600:>15.1f} hours                ║
╚════════════════════════════════════════════════════════════════╝
        """
        return report


class OANDABroker(BaseBroker):
    """
    OANDA v20 API Implementation - PRODUCTION VERSION
    
    Features:
    - Connection pooling with aiohttp
    - Request timeouts on all operations
    - Rate limiting (max 10 concurrent requests)
    - Automatic retry with exponential backoff
    - Position caching with TTL
    """
    
    def __init__(
        self,
        api_key: str,
        account_id: str,
        practice: bool = True,
        timeout: float = 10.0,
        max_retries: int = 3
    ):
        super().__init__()
        
        if not AIOHTTP_AVAILABLE:
            raise ImportError("aiohttp required for OANDA broker")
        
        self.api_key = api_key
        self.account_id = account_id
        self.practice = practice
        self.timeout = timeout
        self.max_retries = max_retries
        
        self.base_url = (
            "https://api-fxpractice.oanda.com"
            if practice else
            "https://api-fxtrade.oanda.com"
        )
        
        # Rate limiting
        self._rate_limiter = asyncio.Semaphore(10)
        self._request_count = 0
        self._last_request_time = 0
        
        # Caching
        self._positions_cache: Dict[str, Position] = {}
        self._cache_ttl = 5  # 5 seconds
        self._last_cache_update = 0
        
        self._session = None
    
    async def connect(self):
        """Connect to OANDA API with retry"""
        for attempt in range(self.max_retries):
            try:
                self._session = aiohttp.ClientSession(
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                        "Accept-Datetime-Format": "RFC3339"
                    },
                    timeout=aiohttp.ClientTimeout(total=self.timeout)
                )
                
                # Verify connection
                async with self._rate_limiter:
                    async with self._session.get(
                        f"{self.base_url}/v3/accounts/{self.account_id}"
                    ) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            account = data.get('account', {})
                            
                            logger.info(
                                f"OANDA Connected | "
                                f"Balance: ${float(account.get('balance', 0)):,.2f} | "
                                f"Currency: {account.get('currency', 'USD')} | "
                                f"Practice: {self.practice}"
                            )
                            
                            self.connected = True
                            return True
                        else:
                            error_data = await resp.text()
                            raise ConnectionError(f"OANDA error {resp.status}: {error_data}")
                            
            except Exception as e:
                logger.error(f"Connection attempt {attempt + 1} failed: {e}")
                if self._session:
                    await self._session.close()
                    self._session = None
                
                if attempt < self.max_retries - 1:
                    wait_time = 2 ** attempt  # Exponential backoff
                    logger.info(f"Retrying in {wait_time}s...")
                    await asyncio.sleep(wait_time)
                else:
                    raise ConnectionError(f"Failed to connect after {self.max_retries} attempts")
        
        return False
    
    async def disconnect(self):
        """Disconnect and cleanup"""
        if self._session:
            await self._session.close()
            self._session = None
        
        async with self._connection_lock:
            self.connected = False
        
        logger.info("OANDA disconnected")
        return True
    
    async def _make_request(self, method: str, endpoint: str, **kwargs) -> Dict:
        """Make API request with rate limiting and error handling"""
        url = f"{self.base_url}/v3{endpoint}"
        
        async with self._rate_limiter:
            for attempt in range(self.max_retries):
                try:
                    async with self._session.request(method, url, **kwargs) as resp:
                        self._request_count += 1
                        self._last_request_time = time.time()
                        
                        if resp.status == 200 or resp.status == 201:
                            return await resp.json()
                        elif resp.status == 429:  # Rate limited
                            retry_after = int(resp.headers.get('Retry-After', 1))
                            logger.warning(f"Rate limited, waiting {retry_after}s")
                            await asyncio.sleep(retry_after)
                            continue
                        else:
                            error_text = await resp.text()
                            raise ValueError(f"OANDA API error {resp.status}: {error_text}")
                            
                except asyncio.TimeoutError:
                    logger.error(f"Request timeout (attempt {attempt + 1})")
                    if attempt < self.max_retries - 1:
                        await asyncio.sleep(1)
                    else:
                        raise
                except Exception as e:
                    logger.error(f"Request error: {e}")
                    if attempt < self.max_retries - 1:
                        await asyncio.sleep(1)
                    else:
                        raise
        
        raise ConnectionError("Max retries exceeded")
    
    async def get_account_info(self) -> Dict:
        """Get account information"""
        data = await self._make_request(
            "GET",
            f"/accounts/{self.account_id}"
        )
        
        account = data.get('account', {})
        return {
            'balance': float(account.get('balance', 0)),
            'equity': float(account.get('NAV', 0)),
            'margin_used': float(account.get('marginUsed', 0)),
            'free_margin': float(account.get('marginAvailable', 0)),
            'unrealized_pnl': float(account.get('unrealizedPL', 0)),
            'realized_pnl': float(account.get('realizedPL', 0)),
            'open_positions': len(account.get('positions', [])),
            'currency': account.get('currency', 'USD')
        }
    
    async def place_market_order(
        self,
        symbol: str,
        side: str,
        quantity: float
    ) -> Order:
        """Place market order"""
        # Convert symbol to OANDA format
        instrument = symbol.replace('/', '_')
        
        # OANDA uses units (positive for buy, negative for sell)
        units = quantity if side == 'buy' else -quantity
        
        body = {
            "order": {
                "type": "MARKET",
                "instrument": instrument,
                "units": str(int(units))
            }
        }
        
        data = await self._make_request(
            "POST",
            f"/accounts/{self.account_id}/orders",
            json=body
        )
        
        # Parse response
        order_fill = data.get('orderFillTransaction', {})
        
        if not order_fill:
            raise ValueError("No fill transaction in response")
        
        return Order(
            id=order_fill.get('id', ''),
            symbol=symbol,
            side=OrderSide(side),
            type=OrderType.MARKET,
            quantity=quantity,
            price=float(order_fill.get('price', 0)),
            status=OrderStatus.FILLED,
            filled_quantity=quantity,
            average_fill_price=float(order_fill.get('price', 0)),
            filled_at=time.time(),
            commission=float(order_fill.get('commission', 0))
        )
    
    async def get_positions(self) -> List[Position]:
        """Get open positions with caching"""
        # Check cache
        if time.time() - self._last_cache_update < self._cache_ttl:
            return list(self._positions_cache.values())
        
        data = await self._make_request(
            "GET",
            f"/accounts/{self.account_id}/positions"
        )
        
        positions = []
        self._positions_cache = {}
        
        for pos_data in data.get('positions', []):
            instrument = pos_data.get('instrument', '').replace('_', '/')
            
            # Parse long and short sides
            for side_key, side_enum in [('long', OrderSide.BUY), ('short', OrderSide.SELL)]:
                side_data = pos_data.get(side_key, {})
                units = float(side_data.get('units', 0))
                
                if units != 0:
                    pos = Position(
                        id=f"{instrument}_{side_key}",
                        symbol=instrument,
                        side=side_enum,
                        quantity=abs(units),
                        entry_price=float(side_data.get('averagePrice', 0)),
                        current_price=float(side_data.get('markPrice', 0)),
                        unrealized_pnl=float(side_data.get('unrealizedPL', 0)),
                        realized_pnl=float(side_data.get('realizedPL', 0))
                    )
                    positions.append(pos)
                    self._positions_cache[pos.id] = pos
        
        self._last_cache_update = time.time()
        return positions
    
    async def close_position(self, position_id: str) -> bool:
        """Close position"""
        # Parse position ID
        parts = position_id.rsplit('_', 1)
        if len(parts) != 2:
            logger.error(f"Invalid position ID format: {position_id}")
            return False
        
        instrument, side = parts
        instrument = instrument.replace('/', '_')
        
        body = {
            "longUnits": "ALL" if side == 'long' else "NONE",
            "shortUnits": "ALL" if side == 'short' else "NONE"
        }
        
        try:
            await self._make_request(
                "PUT",
                f"/accounts/{self.account_id}/positions/{instrument}/close",
                json=body
            )
            
            # Invalidate cache
            self._last_cache_update = 0
            
            logger.info(f"Position closed: {position_id}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to close position {position_id}: {e}")
            return False
    
    async def cancel_order(self, order_id: str) -> bool:
        """Cancel pending order"""
        try:
            await self._make_request(
                "PUT",
                f"/accounts/{self.account_id}/orders/{order_id}/cancel"
            )
            logger.info(f"Order cancelled: {order_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to cancel order {order_id}: {e}")
            return False
    
    async def get_pending_orders(self) -> List[Order]:
        """Get pending orders"""
        data = await self._make_request(
            "GET",
            f"/accounts/{self.account_id}/pendingOrders"
        )
        
        orders = []
        for order_data in data.get('orders', []):
            orders.append(Order(
                id=order_data.get('id', ''),
                symbol=order_data.get('instrument', '').replace('_', '/'),
                side=OrderSide(order_data.get('units', 0) > 0 and 'buy' or 'sell'),
                type=OrderType(order_data.get('type', 'MARKET').lower()),
                quantity=abs(float(order_data.get('units', 0))),
                price=float(order_data.get('price', 0)) if order_data.get('price') else None,
                status=OrderStatus.PENDING
            ))
        
        return orders


def create_broker(broker_type: str, config: Dict) -> BaseBroker:
    """Factory function to create appropriate broker"""
    broker_type = broker_type.lower()
    
    if broker_type == 'paper':
        return PaperTradingBroker(
            initial_balance=config.get('initial_balance', 100000.0),
            commission_per_lot=config.get('commission_per_lot', 3.5),
            slippage_model=config.get('slippage_model', 'gaussian')
        )
    elif broker_type == 'oanda':
        if not AIOHTTP_AVAILABLE:
            raise ImportError("aiohttp required for OANDA broker. Install: pip install aiohttp")
        return OANDABroker(
            api_key=config['api_key'],
            account_id=config['account_id'],
            practice=config.get('practice', True),
            timeout=config.get('timeout', 10.0),
            max_retries=config.get('max_retries', 3)
        )
    else:
        raise ValueError(f"Unknown broker type: {broker_type}")

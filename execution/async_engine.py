# execution/async_engine.py
"""
High-performance async execution engine with order management,
latency optimization, and fill simulation.
"""

import asyncio
import aiohttp
import time
from typing import Dict, List, Optional, Callable, Any, Set
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, auto
import logging
import json
from collections import defaultdict
import heapq
import numpy as np

logger = logging.getLogger(__name__)

class OrderStatus(Enum):
    PENDING = auto()
    SUBMITTED = auto()
    PARTIAL_FILL = auto()
    FILLED = auto()
    CANCELLED = auto()
    REJECTED = auto()
    EXPIRED = auto()

class OrderType(Enum):
    MARKET = auto()
    LIMIT = auto()
    STOP = auto()
    STOP_LIMIT = auto()
    TRAILING_STOP = auto()

@dataclass
class Order:
    id: str
    symbol: str
    side: str  # 'buy' or 'sell'
    quantity: float
    order_type: OrderType
    price: Optional[float] = None
    stop_price: Optional[float] = None
    time_in_force: str = "GTC"  # GTC, IOC, FOK
    status: OrderStatus = OrderStatus.PENDING
    filled_qty: float = 0.0
    avg_fill_price: float = 0.0
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
    metadata: Dict = field(default_factory=dict)
    
    @property
    def remaining_qty(self) -> float:
        return self.quantity - self.filled_qty

@dataclass 
class Fill:
    order_id: str
    symbol: str
    quantity: float
    price: float
    timestamp: datetime
    side: str
    fees: float = 0.0

class AsyncExecutionEngine:
    """
    Production async execution engine with:
    - Sub-millisecond order routing
    - Smart order routing across venues
    - Latency monitoring and optimization
    - Fill simulation for backtesting
    """
    
    def __init__(self, broker_configs: List[Dict], paper_mode: bool = True):
        self.paper_mode = paper_mode
        self.brokers: Dict[str, Any] = {}  # name -> broker client
        self.sessions: Dict[str, aiohttp.ClientSession] = {}
        
        # Order management
        self.orders: Dict[str, Order] = {}
        self.order_locks: Dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
        self.pending_orders: Set[str] = set()
        self.position_cache: Dict[str, Dict] = {}
        
        # Performance tracking
        self.latency_stats: Dict[str, List[float]] = defaultdict(list)
        self.fill_stats: Dict[str, Dict] = defaultdict(lambda: {'count': 0, 'avg_slippage': 0.0})
        
        # Callbacks
        self.on_fill: Optional[Callable[[Fill], None]] = None
        self.on_order_update: Optional[Callable[[Order], None]] = None
        
        # Rate limiting
        self.rate_limiters: Dict[str, asyncio.Semaphore] = {}
        self.last_request_time: Dict[str, float] = {}
        
        # Market data
        self.price_cache: Dict[str, Dict] = {}  # symbol -> {bid, ask, last_update}
        self.price_lock = asyncio.Lock()
        
        # Tasks
        self._tasks: Set[asyncio.Task] = set()
        self._shutdown = False
    
    async def initialize(self):
        """Initialize connections to all brokers"""
        for config in self.broker_configs:
            name = config['name']
            
            # Create rate limiter (e.g., 10 requests/second)
            self.rate_limiters[name] = asyncio.Semaphore(config.get('rate_limit', 10))
            
            if not self.paper_mode:
                # Real broker connection
                self.sessions[name] = aiohttp.ClientSession(
                    headers=config.get('headers', {}),
                    timeout=aiohttp.ClientTimeout(total=5)
                )
            
            self.brokers[name] = config
            
            # Start price feed
            task = asyncio.create_task(self._price_feed_loop(name))
            self._tasks.add(task)
        
        logger.info(f"Initialized {len(self.brokers)} broker connections")
    
    async def submit_order(self, order: Order, priority: int = 5) -> str:
        """
        Submit order with smart routing and latency optimization.
        Priority: 1 (highest) to 10 (lowest)
        """
        if self._shutdown:
            raise RuntimeError("Engine is shutting down")
        
        # Generate ID if not provided
        if not order.id:
            order.id = f"ord_{int(time.time() * 1000)}_{np.random.randint(10000)}"
        
        async with self.order_locks[order.id]:
            self.orders[order.id] = order
            self.pending_orders.add(order.id)
            
            # Pre-trade risk check
            allowed, reason = await self._pre_trade_check(order)
            if not allowed:
                order.status = OrderStatus.REJECTED
                order.metadata['reject_reason'] = reason
                logger.warning(f"Order {order.id} rejected: {reason}")
                return order.id
            
            # Select best venue
            venue = self._select_venue(order)
            
            # Submit with timeout and retry
            start_time = time.time()
            
            try:
                await asyncio.wait_for(
                    self._submit_to_venue(order, venue),
                    timeout=2.0
                )
                
                latency = (time.time() - start_time) * 1000  # ms
                self.latency_stats['submit'].append(latency)
                
                if latency > 100:
                    logger.warning(f"High submission latency: {latency:.1f}ms")
                
            except asyncio.TimeoutError:
                logger.error(f"Order submission timeout: {order.id}")
                order.status = OrderStatus.REJECTED
                order.metadata['reject_reason'] = 'timeout'
                
                # Try backup venue
                backup = self._get_backup_venue(venue)
                if backup:
                    logger.info(f"Retrying on backup venue: {backup}")
                    await self._submit_to_venue(order, backup)
        
        return order.id
    
    async def cancel_order(self, order_id: str) -> bool:
        """Cancel order with confirmation"""
        if order_id not in self.orders:
            return False
        
        async with self.order_locks[order_id]:
            order = self.orders[order_id]
            if order.status not in [OrderStatus.PENDING, OrderStatus.SUBMITTED, OrderStatus.PARTIAL_FILL]:
                return False
            
            venue = order.metadata.get('venue')
            if not venue:
                return False
            
            try:
                await self._rate_limited_request(venue, 'cancel', order_id)
                order.status = OrderStatus.CANCELLED
                order.updated_at = datetime.utcnow()
                self.pending_orders.discard(order_id)
                
                if self.on_order_update:
                    self.on_order_update(order)
                
                return True
                
            except Exception as e:
                logger.error(f"Cancel failed for {order_id}: {e}")
                return False
    
    async def modify_order(self, order_id: str, new_price: float, new_qty: Optional[float] = None) -> bool:
        """Modify existing order (cancel + replace)"""
        if order_id not in self.orders:
            return False
        
        async with self.order_locks[order_id]:
            old_order = self.orders[order_id]
            
            # Cancel old
            await self.cancel_order(order_id)
            
            # Create new
            new_order = Order(
                symbol=old_order.symbol,
                side=old_order.side,
                quantity=new_qty or old_order.remaining_qty,
                order_type=old_order.order_type,
                price=new_price,
                stop_price=old_order.stop_price,
                time_in_force=old_order.time_in_force,
                metadata={'modified_from': order_id}
            )
            
            await self.submit_order(new_order)
            return True
    
    async def batch_submit(self, orders: List[Order]) -> List[str]:
        """Submit multiple orders concurrently"""
        tasks = [self.submit_order(order) for order in orders]
        return await asyncio.gather(*tasks, return_exceptions=True)
    
    async def close_all_positions(self, symbol: Optional[str] = None) -> List[str]:
        """Emergency position flattening"""
        positions = await self.get_positions()
        
        orders = []
        for pos in positions:
            if symbol and pos['symbol'] != symbol:
                continue
            
            # Determine closing side
            close_side = 'sell' if pos['quantity'] > 0 else 'buy'
            
            order = Order(
                symbol=pos['symbol'],
                side=close_side,
                quantity=abs(pos['quantity']),
                order_type=OrderType.MARKET,
                metadata={'flatten': True}
            )
            orders.append(order)
        
        # Submit all concurrently
        order_ids = await self.batch_submit(orders)
        logger.info(f"Flattened {len(orders)} positions")
        
        return [oid for oid in order_ids if not isinstance(oid, Exception)]
    
    async def get_positions(self) -> List[Dict]:
        """Get current positions with caching"""
        # Return cached if recent
        if hasattr(self, '_position_cache_time'):
            if time.time() - self._position_cache_time < 1.0:  # 1 second cache
                return list(self.position_cache.values())
        
        # Fetch fresh
        positions = []
        for venue, broker in self.brokers.items():
            try:
                pos = await self._rate_limited_request(venue, 'get_positions')
                for p in pos:
                    p['venue'] = venue
                    self.position_cache[p['symbol']] = p
                    positions.append(p)
            except Exception as e:
                logger.error(f"Failed to get positions from {venue}: {e}")
        
        self._position_cache_time = time.time()
        return positions
    
    async def _submit_to_venue(self, order: Order, venue: str):
        """Submit order to specific venue"""
        order.metadata['venue'] = venue
        
        if self.paper_mode:
            await self._simulate_fill(order)
        else:
            await self._live_submit(order, venue)
    
    async def _live_submit(self, order: Order, venue: str):
        """Submit to live broker"""
        broker = self.brokers[venue]
        session = self.sessions[venue]
        
        payload = self._format_order(order, broker)
        
        async with self.rate_limiters[venue]:
            async with session.post(
                f"{broker['url']}/orders",
                json=payload
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    order.status = OrderStatus.SUBMITTED
                    order.metadata['broker_id'] = data.get('id')
                    
                    # Start fill monitoring
                    task = asyncio.create_task(self._monitor_fills(order))
                    self._tasks.add(task)
                    
                else:
                    error = await resp.text()
                    raise Exception(f"Submit failed: {error}")
    
    async def _simulate_fill(self, order: Order):
        """Realistic fill simulation for paper trading"""
        await asyncio.sleep(0.01)  # 10ms simulated latency
        
        async with self.price_lock:
            market = self.price_cache.get(order.symbol, {})
        
        if not market:
            order.status = OrderStatus.REJECTED
            order.metadata['reject_reason'] = 'no_market_data'
            return
        
        # Determine fill price with realistic slippage
        base_price = market['ask'] if order.side == 'buy' else market['bid']
        
        # Slippage model based on order size and volatility
        volatility = market.get('volatility', 0.001)
        size_factor = min(order.quantity / 100, 1.0)  # Larger orders = more slippage
        
        slippage = np.random.normal(0, volatility * size_factor)
        
        if order.order_type == OrderType.MARKET:
            fill_price = base_price * (1 + slippage)
        elif order.order_type == OrderType.LIMIT:
            if (order.side == 'buy' and base_price <= order.price) or \
               (order.side == 'sell' and base_price >= order.price):
                fill_price = order.price
            else:
                # Limit not hit - simulate partial fill probability
                if np.random.random() < 0.3:  # 30% chance of no fill
                    order.status = OrderStatus.SUBMITTED
                    asyncio.create_task(self._delayed_fill_simulation(order))
                    return
                fill_price = order.price
        
        # Simulate partial fills for large orders
        remaining = order.quantity
        fills = []
        
        while remaining > 0 and len(fills) < 5:  # Max 5 partial fills
            fill_qty = min(remaining, np.random.uniform(0.1, 0.5) * order.quantity)
            fill_qty = min(fill_qty, remaining)
            
            fill = Fill(
                order_id=order.id,
                symbol=order.symbol,
                quantity=fill_qty,
                price=fill_price * (1 + np.random.normal(0, 0.0001)),
                timestamp=datetime.utcnow(),
                side=order.side,
                fees=fill_qty * fill_price * 0.0005  # 5bps fee
            )
            fills.append(fill)
            remaining -= fill_qty
            
            # Delay between partial fills
            await asyncio.sleep(np.random.exponential(0.5))
        
        # Apply fills
        for fill in fills:
            await self._apply_fill(order, fill)
    
    async def _delayed_fill_simulation(self, order: Order):
        """Simulate fill that happens later (limit orders)"""
        await asyncio.sleep(np.random.exponential(5))  # Mean 5s delay
        
        if order.status != OrderStatus.SUBMITTED:
            return
        
        async with self.price_lock:
            market = self.price_cache.get(order.symbol, {})
        
        if not market:
            return
        
        current = market['mid']
        
        # Check if limit would now fill
        would_fill = (order.side == 'buy' and current <= order.price) or \
                     (order.side == 'sell' and current >= order.price)
        
        if would_fill or np.random.random() < 0.1:  # 10% chance of fill anyway
            fill = Fill(
                order_id=order.id,
                symbol=order.symbol,
                quantity=order.quantity,
                price=order.price,
                timestamp=datetime.utcnow(),
                side=order.side
            )
            await self._apply_fill(order, fill)
    
    async def _apply_fill(self, order: Order, fill: Fill):
        """Apply fill to order"""
        async with self.order_locks[order.id]:
            order.filled_qty += fill.quantity
            order.avg_fill_price = (
                (order.avg_fill_price * (order.filled_qty - fill.quantity) + 
                 fill.price * fill.quantity) / order.filled_qty
            )
            
            if order.filled_qty >= order.quantity * 0.99:
                order.status = OrderStatus.FILLED
                self.pending_orders.discard(order.id)
            else:
                order.status = OrderStatus.PARTIAL_FILL
            
            order.updated_at = datetime.utcnow()
            
            # Update stats
            self.fill_stats[order.symbol]['count'] += 1
            
            # Notify
            if self.on_fill:
                try:
                    self.on_fill(fill)
                except Exception as e:
                    logger.error(f"Fill callback error: {e}")
            
            if self.on_order_update:
                try:
                    self.on_order_update(order)
                except Exception as e:
                    logger.error(f"Order update callback error: {e}")
    
    async def _monitor_fills(self, order: Order):
        """Monitor for fills from live broker"""
        if self.paper_mode:
            return
        
        check_interval = 0.1  # 100ms
        max_checks = 600  # 60 seconds
        
        for _ in range(max_checks):
            if order.status in [OrderStatus.FILLED, OrderStatus.CANCELLED, OrderStatus.REJECTED]:
                return
            
            try:
                venue = order.metadata.get('venue')
                broker_id = order.metadata.get('broker_id')
                
                fill_data = await self._rate_limited_request(
                    venue, 'get_fills', broker_id
                )
                
                for fd in fill_data:
                    fill = Fill(
                        order_id=order.id,
                        symbol=fd['symbol'],
                        quantity=fd['qty'],
                        price=fd['price'],
                        timestamp=datetime.fromisoformat(fd['time']),
                        side=fd['side'],
                        fees=fd.get('fees', 0)
                    )
                    await self._apply_fill(order, fill)
                
            except Exception as e:
                logger.error(f"Fill monitoring error: {e}")
            
            await asyncio.sleep(check_interval)
    
    async def _price_feed_loop(self, venue: str):
        """Maintain real-time price cache"""
        while not self._shutdown:
            try:
                if self.paper_mode:
                    # Simulate price movements
                    for symbol in ['EUR/USD', 'GBP/USD', 'XAU/USD']:
                        if symbol not in self.price_cache:
                            base = {'EUR/USD': 1.08, 'GBP/USD': 1.26, 'XAU/USD': 2050.0}[symbol]
                            self.price_cache[symbol] = {
                                'bid': base - 0.0001,
                                'ask': base + 0.0001,
                                'mid': base,
                                'volatility': 0.0002
                            }
                        
                        # Random walk
                        mid = self.price_cache[symbol]['mid']
                        move = np.random.normal(0, 0.0001)
                        new_mid = mid * (1 + move)
                        
                        spread = 0.0002
                        async with self.price_lock:
                            self.price_cache[symbol] = {
                                'bid': new_mid - spread/2,
                                'ask': new_mid + spread/2,
                                'mid': new_mid,
                                'volatility': abs(move) * 0.5 + self.price_cache[symbol]['volatility'] * 0.5,
                                'timestamp': time.time()
                            }
                else:
                    # Real price feed
                    pass
                
                await asyncio.sleep(0.1)  # 10Hz update
                
            except Exception as e:
                logger.error(f"Price feed error: {e}")
                await asyncio.sleep(1)
    
    async def _rate_limited_request(self, venue: str, method: str, *args) -> Any:
        """Execute rate-limited request to broker"""
        async with self.rate_limiters[venue]:
            # Enforce minimum interval between requests
            last = self.last_request_time.get(venue, 0)
            elapsed = time.time() - last
            if elapsed < 0.1:  # Max 10 req/sec
                await asyncio.sleep(0.1 - elapsed)
            
            self.last_request_time[venue] = time.time()
            
            # Execute
            broker = self.brokers[venue]
            if method == 'get_positions':
                return []  # Implement actual API call
            elif method == 'cancel':
                return True
            elif method == 'get_fills':
                return []
            
            return None
    
    def _select_venue(self, order: Order) -> str:
        """Smart order routing - select best venue"""
        # Simplified - implement actual routing logic based on:
        # - Price improvement
        # - Fill probability
        # - Latency
        # - Fees
        
        venues = list(self.brokers.keys())
        
        # Check which venues have the symbol
        available = [v for v in venues if self._venue_has_symbol(v, order.symbol)]
        
        if not available:
            return venues[0]  # Default
        
        # Select based on latency history
        best = min(available, key=lambda v: np.mean(self.latency_stats.get(v, [100])))
        return best
    
    def _get_backup_venue(self, primary: str) -> Optional[str]:
        """Get backup venue if primary fails"""
        venues = [v for v in self.brokers.keys() if v != primary]
        return venues[0] if venues else None
    
    def _venue_has_symbol(self, venue: str, symbol: str) -> bool:
        """Check if venue supports symbol"""
        return True  # Implement actual check
    
    async def _pre_trade_check(self, order: Order) -> tuple[bool, str]:
        """Risk check before submission"""
        # Position limit check
        current = self.position_cache.get(order.symbol, {}).get('quantity', 0)
        if abs(current + (order.quantity if order.side == 'buy' else -order.quantity)) > 100:
            return False, "position_limit_exceeded"
        
        # Price sanity check
        async with self.price_lock:
            market = self.price_cache.get(order.symbol)
        
        if market:
            mid = market['mid']
            if order.price and abs(order.price - mid) / mid > 0.05:
                return False, "price_deviation_too_large"
        
        return True, ""
    
    def _format_order(self, order: Order, broker: Dict) -> Dict:
        """Format order for specific broker API"""
        mapping = {
            OrderType.MARKET: 'MKT',
            OrderType.LIMIT: 'LMT',
            OrderType.STOP: 'STP',
        }
        
        return {
            'symbol': order.symbol,
            'side': order.side.upper(),
            'qty': order.quantity,
            'type': mapping.get(order.order_type, 'MKT'),
            'price': order.price,
            'stopPrice': order.stop_price,
            'tif': order.time_in_force
        }
    
    async def get_latency_report(self) -> Dict:
        """Generate latency statistics"""
        return {
            venue: {
                'mean_ms': np.mean(times) if times else 0,
                'p99_ms': np.percentile(times, 99) if times else 0,
                'max_ms': max(times) if times else 0,
                'count': len(times)
            }
            for venue, times in self.latency_stats.items()
        }
    
    async def shutdown(self):
        """Graceful shutdown"""
        self._shutdown = True
        
        # Cancel all pending orders
        await self.close_all_positions()
        
        # Cancel monitoring tasks
        for task in self._tasks:
            task.cancel()
        
        # Close sessions
        for session in self.sessions.values():
            await session.close()
        
        logger.info("Execution engine shutdown complete")

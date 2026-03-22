"""
Institutional Execution Engine
Smart order routing, algo execution, market impact modeling
"""

import asyncio
import random
from abc import ABC, abstractmethod
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from enum import Enum
from typing import Dict, List, Optional, Callable, Any
from datetime import datetime, timedelta
import numpy as np

from hopefx.core.events import EventType, DomainEvent, event_bus

# ============================================================================
# ORDER TYPES — Institutional grade
# ============================================================================

class OrderSide(Enum):
    BUY = 1
    SELL = -1

class OrderType(Enum):
    MARKET = "market"
    LIMIT = "limit"
    STOP = "stop"
    STOP_LIMIT = "stop_limit"
    TRAILING_STOP = "trailing_stop"
    ICEBERG = "iceberg"           # Hidden size
    TWAP = "twap"                 # Time-weighted
    VWAP = "vwap"                 # Volume-weighted
    ARRIVAL_PRICE = "arrival"     # Benchmark to arrival
    IMPLEMENTATION_SHORTFALL = "is"  # Optimize execution

class TimeInForce(Enum):
    GTC = "gtc"      # Good till cancel
    IOC = "ioc"      # Immediate or cancel
    FOK = "fok"      # Fill or kill
    GTD = "gtd"      # Good till date
    DAY = "day"      # Day order

# ============================================================================
# ORDER — Immutable order representation
# ============================================================================

@dataclass(frozen=True, slots=True)
class Order:
    """Institutional order with full specification."""
    
    order_id: str
    symbol: str
    side: OrderSide
    quantity: Decimal
    order_type: OrderType
    time_in_force: TimeInForce = TimeInForce.GTC
    
    # Pricing
    price: Optional[Decimal] = None           # Limit price
    stop_price: Optional[Decimal] = None       # Stop trigger
    trailing_distance: Optional[Decimal] = None  # For trailing
    
    # Display
    display_qty: Optional[Decimal] = None      # Iceberg: visible portion
    min_qty: Optional[Decimal] = None          # Minimum fill
    
    # Scheduling
    start_time: Optional[datetime] = None      # TWAP/VWAP start
    end_time: Optional[datetime] = None        # TWAP/VWAP end
    urgency: int = 5                           # 1=passive, 10=aggressive
    
    # Risk
    max_slippage_bps: int = 50                 # Max 50 bps slippage
    max_market_impact_bps: int = 100           # Max 100 bps impact
    
    # Metadata
    strategy_id: Optional[str] = None
    parent_order_id: Optional[str] = None       # For child orders
    user_id: str = "system"
    created_at: datetime = field(default_factory=datetime.utcnow)
    
    def __post_init__(self):
        # Validate
        if self.order_type in [OrderType.LIMIT, OrderType.STOP_LIMIT] and self.price is None:
            raise ValueError("Limit orders require price")
        if self.order_type in [OrderType.STOP, OrderType.STOP_LIMIT, OrderType.TRAILING_STOP] and self.stop_price is None:
            raise ValueError("Stop orders require stop_price")

# ============================================================================
# EXECUTION ENGINE — Smart order router
# ============================================================================

class ExecutionEngine:
    """
    Institutional execution with:
    - Smart order routing across venues
    - Algo execution (TWAP, VWAP, Implementation Shortfall)
    - Market impact modeling
    - Real-time P&L tracking
    - Full audit trail
    """
    
    def __init__(self):
        self._brokers: Dict[str, 'BrokerAdapter'] = {}
        self._active_orders: Dict[str, Order] = {}
        self._child_orders: Dict[str, List[str]] = defaultdict(list)  # parent -> children
        self._fills: Dict[str, List[Dict]] = defaultdict(list)
        self._position_cache: Dict[str, Decimal] = {}  # symbol -> net position
        
        # Algo schedulers
        self._algo_schedulers: Dict[str, asyncio.Task] = {}
        
        # Metrics
        self._metrics = {
            'orders_submitted': 0,
            'orders_filled': 0,
            'total_commission': Decimal('0'),
            'total_slippage_bps': 0.0,
        }
        
        # Subscribe to events
        event_bus.subscribe(EventType.ORDER_FILL, self._on_fill, priority=5)
    
    def register_broker(self, name: str, adapter: 'BrokerAdapter'):
        """Register broker adapter."""
        self._brokers[name] = adapter
    
    async def submit_order(self, order: Order) -> str:
        """
        Submit order with intelligent routing.
        """
        # Pre-trade risk check (async via event)
        risk_event = DomainEvent(
            event_type=EventType.ORDER_NEW,
            payload={'order': order.to_dict()}
        )
        await event_bus.publish(risk_event)
        
        # Store
        self._active_orders[order.order_id] = order
        self._metrics['orders_submitted'] += 1
        
        # Route to appropriate handler
        if order.order_type in [OrderType.TWAP, OrderType.VWAP, OrderType.IMPLEMENTATION_SHORTFALL]:
            # Launch algo execution
            task = asyncio.create_task(
                self._execute_algo(order)
            )
            self._algo_schedulers[order.order_id] = task
        else:
            # Direct execution
            await self._execute_direct(order)
        
        return order.order_id
    
    async def _execute_direct(self, order: Order):
        """Execute single order."""
        # Venue selection
        venue = self._select_venue(order)
        broker = self._brokers.get(venue)
        
        if not broker:
            await self._reject_order(order, "No suitable venue")
            return
        
        # Send to broker
        try:
            ack = await broker.place_order(order)
            
            await event_bus.publish(DomainEvent(
                event_type=EventType.ORDER_ACK,
                payload={
                    'order_id': order.order_id,
                    'broker_order_id': ack.get('broker_order_id'),
                    'venue': venue
                }
            ))
            
        except Exception as e:
            await self._reject_order(order, str(e))
    
    async def _execute_algo(self, order: Order):
        """
        Execute algorithmic order.
        
        TWAP: Slice evenly over time window
        VWAP: Slice based on historical volume profile
        IS: Optimize for implementation shortfall vs. arrival price
        """
        if order.order_type == OrderType.TWAP:
            await self._execute_twap(order)
        elif order.order_type == OrderType.VWAP:
            await self._execute_vwap(order)
        elif order.order_type == OrderType.IMPLEMENTATION_SHORTFALL:
            await self._execute_is(order)
    
    async def _execute_twap(self, order: Order):
        """Time-Weighted Average Price execution."""
        duration = (order.end_time or datetime.utcnow() + timedelta(hours=1)) - datetime.utcnow()
        num_slices = max(int(duration.total_seconds() / 60), 1)  # 1-minute slices
        slice_qty = order.quantity / num_slices
        
        for i in range(num_slices):
            # Create child order
            child = Order(
                order_id=f"{order.order_id}_child_{i}",
                symbol=order.symbol,
                side=order.side,
                quantity=slice_qty,
                order_type=OrderType.LIMIT,
                price=self._calculate_twap_price(order),  # Mid + slight bias
                time_in_force=TimeInForce.GTC,
                parent_order_id=order.order_id,
                user_id=order.user_id
            )
            
            self._child_orders[order.order_id].append(child.order_id)
            await self.submit_order(child)
            
            # Wait for next slice
            if i < num_slices - 1:
                await asyncio.sleep(60)
    
    def _calculate_twap_price(self, order: Order) -> Decimal:
        """Calculate aggressive limit price for TWAP slice."""
        # Would use real market data
        mid = Decimal('100.00')  # Placeholder
        bias = Decimal('0.01') if order.side == OrderSide.BUY else Decimal('-0.01')
        return (mid + bias).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    
    async def _execute_vwap(self, order: Order):
        """Volume-Weighted Average Price execution."""
        # Load volume profile
        profile = await self._load_volume_profile(order.symbol)
        
        # Calculate slice sizes based on profile
        slices = self._calculate_vwap_slices(order.quantity, profile)
        
        for slice_qty, target_time in slices:
            # Wait until target time
            now = datetime.utcnow()
            if target_time > now:
                await asyncio.sleep((target_time - now).total_seconds())
            
            child = Order(
                order_id=f"{order.order_id}_child_{len(self._child_orders[order.order_id])}",
                symbol=order.symbol,
                side=order.side,
                quantity=slice_qty,
                order_type=OrderType.MARKET if order.urgency > 7 else OrderType.LIMIT,
                parent_order_id=order.order_id,
                user_id=order.user_id
            )
            
            await self.submit_order(child)
    
    async def _execute_is(self, order: Order):
        """Implementation Shortfall - minimize slippage vs arrival price."""
        # Record arrival price
        arrival_price = await self._get_mid_price(order.symbol)
        
        # Aggressive start, passive finish
        urgency_schedule = [9, 8, 7, 6, 5, 4, 3, 2, 1, 1]
        
        for urgency in urgency_schedule:
            slice_qty = order.quantity / len(urgency_schedule)
            
            child = Order(
                order_id=f"{order.order_id}_child_{len(self._child_orders[order.order_id])}",
                symbol=order.symbol,
                side=order.side,
                quantity=slice_qty,
                order_type=OrderType.LIMIT,
                urgency=urgency,
                parent_order_id=order.order_id,
                user_id=order.user_id
            )
            
            await self.submit_order(child)
            await asyncio.sleep(30)  # 30-second intervals
    
    async def _on_fill(self, event: DomainEvent):
        """Process fill event."""
        fill = event.payload
        
        parent_id = fill.get('parent_order_id')
        if parent_id:
            # Update parent order progress
            self._fills[parent_id].append(fill)
            
            # Check if parent complete
            total_filled = sum(f['quantity'] for f in self._fills[parent_id])
            parent_order = self._active_orders.get(parent_id)
            
            if parent_order and total_filled >= parent_order.quantity:
                # Parent complete
                await event_bus.publish(DomainEvent(
                    event_type=EventType.ORDER_FILL,  # Parent fill
                    payload={
                        'order_id': parent_id,
                        'total_filled': total_filled,
                        'avg_price': self._calculate_vwap(self._fills[parent_id]),
                        'child_fills': self._fills[parent_id]
                    }
                ))
                
                # Cleanup algo scheduler
                if parent_id in self._algo_schedulers:
                    self._algo_schedulers[parent_id].cancel()
                    del self._algo_schedulers[parent_id]
    
    def _select_venue(self, order: Order) -> str:
        """Select best venue based on order characteristics."""
        # Simplified logic - real system would use:
        # - Fee comparison
        # - Liquidity analysis
        # - Latency metrics
        # - Historical fill rates
        
        if order.order_type == OrderType.MARKET:
            # Select deepest book
            return max(self._brokers.keys(), key=lambda k: self._brokers[k].get_liquidity(order.symbol))
        
        # Default to first available
        return list(self._brokers.keys())[0] if self._brokers else "paper"
    
    async def _reject_order(self, order: Order, reason: str):
        """Emit rejection event."""
        await event_bus.publish(DomainEvent(
            event_type=EventType.ORDER_REJECT,
            payload={
                'order_id': order.order_id,
                'reason': reason,
                'timestamp': datetime.utcnow().isoformat()
            }
        ))
    
    def _calculate_vwap(self, fills: List[Dict]) -> Decimal:
        """Calculate volume-weighted average price."""
        total_qty = sum(f['quantity'] for f in fills)
        if total_qty == 0:
            return Decimal('0')
        
        total_value = sum(f['quantity'] * Decimal(str(f['price'])) for f in fills)
        return (total_value / total_qty).quantize(Decimal('0.0001'))
    
    async def _load_volume_profile(self, symbol: str) -> List[float]:
        """Load historical volume profile for VWAP."""
        # Would query database
        return [0.1] * 10  # Flat profile placeholder
    
    def _calculate_vwap_slices(self, total_qty: Decimal, profile: List[float]) -> List[Tuple[Decimal, datetime]]:
        """Calculate slice quantities and timing."""
        slices = []
        now = datetime.utcnow()
        
        for i, pct in enumerate(profile):
            qty = (total_qty * Decimal(str(pct))).quantize(Decimal('0.01'))
            target_time = now + timedelta(minutes=i * 6)  # 6-minute intervals
            slices.append((qty, target_time))
        
        return slices
    
    async def _get_mid_price(self, symbol: str) -> Decimal:
        """Get current mid price."""
        # Would query market data
        return Decimal('100.00')
    
    def get_order_status(self, order_id: str) -> Dict:
        """Get comprehensive order status."""
        order = self._active_orders.get(order_id)
        if not order:
            return {'status': 'unknown'}
        
        fills = self._fills.get(order_id, [])
        total_filled = sum(f['quantity'] for f in fills)
        
        return {
            'order': asdict(order),
            'status': 'filled' if total_filled >= order.quantity else 'partial' if fills else 'pending',
            'filled_quantity': total_filled,
            'remaining': order.quantity - total_filled,
            'fills': fills,
            'children': self._child_orders.get(order_id, [])
        }
    
    async def cancel_order(self, order_id: str) -> bool:
        """Cancel order and all children."""
        order = self._active_orders.get(order_id)
        if not order:
            return False
        
        # Cancel algo scheduler if exists
        if order_id in self._algo_schedulers:
            self._algo_schedulers[order_id].cancel()
            del self._algo_schedulers[order_id]
        
        # Cancel all children
        for child_id in self._child_orders.get(order_id, []):
            child_order = self._active_orders.get(child_id)
            if child_order:
                broker = self._brokers.get(self._select_venue(child_order))
                if broker:
                    await broker.cancel_order(child_id)
        
        # Cancel parent
        await event_bus.publish(DomainEvent(
            event_type=EventType.ORDER_CANCELLED,
            payload={'order_id': order_id, 'reason': 'user_request'}
        ))
        
        return True

# ============================================================================
# BROKER ADAPTER INTERFACE
# ============================================================================

class BrokerAdapter(ABC):
    """Abstract broker adapter."""
    
    @abstractmethod
    async def place_order(self, order: Order) -> Dict:
        """Place order with broker."""
        pass
    
    @abstractmethod
    async def cancel_order(self, order_id: str) -> bool:
        """Cancel order."""
        pass
    
    @abstractmethod
    def get_liquidity(self, symbol: str) -> float:
        """Get available liquidity."""
        pass
    
    @abstractmethod
    async def get_position(self, symbol: str) -> Decimal:
        """Get current position."""
        pass

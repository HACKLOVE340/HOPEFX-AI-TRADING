"""
Advanced Order Types

Professional order management system supporting:
- One-Cancels-Other (OCO) orders
- Bracket orders (entry with stop-loss and take-profit)
- Trailing stop orders
- Time-based orders (GTC, GTD, IOC, FOK)
- Conditional orders
- Scaled orders
"""

from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
import uuid
import logging
from threading import Lock

logger = logging.getLogger(__name__)


class OrderType(Enum):
    """Order types."""
    MARKET = "market"
    LIMIT = "limit"
    STOP = "stop"
    STOP_LIMIT = "stop_limit"
    TRAILING_STOP = "trailing_stop"
    OCO = "oco"  # One-Cancels-Other
    BRACKET = "bracket"
    CONDITIONAL = "conditional"
    SCALED = "scaled"


class OrderSide(Enum):
    """Order side."""
    BUY = "buy"
    SELL = "sell"


class OrderStatus(Enum):
    """Order status."""
    PENDING = "pending"
    OPEN = "open"
    FILLED = "filled"
    PARTIALLY_FILLED = "partially_filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"
    EXPIRED = "expired"
    TRIGGERED = "triggered"


class TimeInForce(Enum):
    """Time in force options."""
    GTC = "gtc"  # Good Till Cancelled
    GTD = "gtd"  # Good Till Date
    IOC = "ioc"  # Immediate Or Cancel
    FOK = "fok"  # Fill Or Kill
    DAY = "day"  # Day order


@dataclass
class Order:
    """Base order structure."""
    id: str
    symbol: str
    side: OrderSide
    order_type: OrderType
    quantity: float
    price: Optional[float] = None
    stop_price: Optional[float] = None
    time_in_force: TimeInForce = TimeInForce.GTC
    status: OrderStatus = OrderStatus.PENDING
    filled_quantity: float = 0.0
    average_fill_price: float = 0.0
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
    expires_at: Optional[datetime] = None
    parent_id: Optional[str] = None
    child_orders: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict:
        return {
            'id': self.id,
            'symbol': self.symbol,
            'side': self.side.value,
            'order_type': self.order_type.value,
            'quantity': self.quantity,
            'price': self.price,
            'stop_price': self.stop_price,
            'time_in_force': self.time_in_force.value,
            'status': self.status.value,
            'filled_quantity': self.filled_quantity,
            'average_fill_price': self.average_fill_price,
            'created_at': self.created_at.isoformat(),
            'updated_at': self.updated_at.isoformat(),
            'expires_at': self.expires_at.isoformat() if self.expires_at else None,
            'parent_id': self.parent_id,
            'child_orders': self.child_orders,
            'metadata': self.metadata
        }


@dataclass
class TrailingStopOrder(Order):
    """Trailing stop order with dynamic stop price."""
    trail_amount: Optional[float] = None  # Fixed dollar/pip amount
    trail_percent: Optional[float] = None  # Percentage
    activation_price: Optional[float] = None  # Price to activate trailing
    highest_price: float = 0.0  # For long positions
    lowest_price: float = float('inf')  # For short positions


@dataclass
class OCOOrder:
    """One-Cancels-Other order pair."""
    id: str
    symbol: str
    order1: Order  # Typically limit order (take profit)
    order2: Order  # Typically stop order (stop loss)
    status: OrderStatus = OrderStatus.PENDING
    triggered_order_id: Optional[str] = None
    cancelled_order_id: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> Dict:
        return {
            'id': self.id,
            'symbol': self.symbol,
            'order1': self.order1.to_dict(),
            'order2': self.order2.to_dict(),
            'status': self.status.value,
            'triggered_order_id': self.triggered_order_id,
            'cancelled_order_id': self.cancelled_order_id,
            'created_at': self.created_at.isoformat()
        }


@dataclass
class BracketOrder:
    """
    Bracket order: Entry order with attached stop-loss and take-profit.

    Structure:
    - Entry: Market or limit order to enter position
    - Stop-Loss: Stop order to limit losses
    - Take-Profit: Limit order to lock in profits
    """
    id: str
    symbol: str
    side: OrderSide
    entry_order: Order
    stop_loss_order: Order
    take_profit_order: Order
    status: OrderStatus = OrderStatus.PENDING
    position_filled: bool = False
    created_at: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> Dict:
        return {
            'id': self.id,
            'symbol': self.symbol,
            'side': self.side.value,
            'entry_order': self.entry_order.to_dict(),
            'stop_loss_order': self.stop_loss_order.to_dict(),
            'take_profit_order': self.take_profit_order.to_dict(),
            'status': self.status.value,
            'position_filled': self.position_filled,
            'created_at': self.created_at.isoformat()
        }


@dataclass
class ConditionalOrder:
    """
    Conditional order that triggers based on conditions.

    Conditions can include:
    - Price conditions (price above/below threshold)
    - Indicator conditions (RSI, MA crossover, etc.)
    - Time conditions
    - Custom conditions via callback
    """
    id: str
    order: Order
    conditions: List[Dict[str, Any]]
    condition_logic: str = "AND"  # AND, OR
    status: OrderStatus = OrderStatus.PENDING
    evaluation_count: int = 0
    last_evaluated: Optional[datetime] = None
    created_at: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> Dict:
        return {
            'id': self.id,
            'order': self.order.to_dict(),
            'conditions': self.conditions,
            'condition_logic': self.condition_logic,
            'status': self.status.value,
            'evaluation_count': self.evaluation_count,
            'last_evaluated': self.last_evaluated.isoformat() if self.last_evaluated else None,
            'created_at': self.created_at.isoformat()
        }


@dataclass
class ScaledOrder:
    """
    Scaled order that places multiple orders at different price levels.

    Use cases:
    - Dollar-cost averaging into position
    - Scaling out of winning positions
    - Laddered limit orders
    """
    id: str
    symbol: str
    side: OrderSide
    total_quantity: float
    levels: List[Dict[str, float]]  # [{'price': X, 'quantity': Y}, ...]
    child_orders: List[Order] = field(default_factory=list)
    filled_levels: int = 0
    status: OrderStatus = OrderStatus.PENDING
    created_at: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> Dict:
        return {
            'id': self.id,
            'symbol': self.symbol,
            'side': self.side.value,
            'total_quantity': self.total_quantity,
            'levels': self.levels,
            'child_orders': [o.to_dict() for o in self.child_orders],
            'filled_levels': self.filled_levels,
            'status': self.status.value,
            'created_at': self.created_at.isoformat()
        }


class AdvancedOrderManager:
    """
    Manages advanced order types including OCO, bracket, trailing stops, etc.

    Features:
    - Order lifecycle management
    - Automatic order linking (OCO, brackets)
    - Trailing stop price updates
    - Conditional order evaluation
    - Order expiration handling
    - Thread-safe operations
    """

    def __init__(self, broker_callback: Callable = None, config: Optional[Dict] = None):
        """
        Initialize advanced order manager.

        Args:
            broker_callback: Callback function to execute orders
            config: Configuration options
        """
        self.config = config or {}
        self.broker_callback = broker_callback

        # Order storage
        self.orders: Dict[str, Order] = {}
        self.oco_orders: Dict[str, OCOOrder] = {}
        self.bracket_orders: Dict[str, BracketOrder] = {}
        self.trailing_stops: Dict[str, TrailingStopOrder] = {}
        self.conditional_orders: Dict[str, ConditionalOrder] = {}
        self.scaled_orders: Dict[str, ScaledOrder] = {}

        # Thread safety
        self._lock = Lock()

        # Statistics
        self.stats = {
            'total_orders': 0,
            'filled_orders': 0,
            'cancelled_orders': 0,
            'oco_triggered': 0,
            'brackets_completed': 0,
        }

        logger.info("Advanced Order Manager initialized")

    def create_order(
        self,
        symbol: str,
        side: OrderSide,
        order_type: OrderType,
        quantity: float,
        price: Optional[float] = None,
        stop_price: Optional[float] = None,
        time_in_force: TimeInForce = TimeInForce.GTC,
        expires_at: Optional[datetime] = None,
        metadata: Optional[Dict] = None
    ) -> Order:
        """Create a basic order."""
        order = Order(
            id=str(uuid.uuid4()),
            symbol=symbol,
            side=side,
            order_type=order_type,
            quantity=quantity,
            price=price,
            stop_price=stop_price,
            time_in_force=time_in_force,
            expires_at=expires_at,
            metadata=metadata or {}
        )

        with self._lock:
            self.orders[order.id] = order
            self.stats['total_orders'] += 1

        logger.info(f"Created order: {order.id} - {side.value} {quantity} {symbol}")
        return order

    def create_trailing_stop(
        self,
        symbol: str,
        side: OrderSide,
        quantity: float,
        trail_amount: Optional[float] = None,
        trail_percent: Optional[float] = None,
        activation_price: Optional[float] = None
    ) -> TrailingStopOrder:
        """
        Create a trailing stop order.

        Args:
            symbol: Trading symbol
            side: Order side (SELL for long position, BUY for short)
            quantity: Order quantity
            trail_amount: Fixed trailing amount in price units
            trail_percent: Trailing percentage
            activation_price: Price at which trailing begins

        Returns:
            TrailingStopOrder
        """
        order = TrailingStopOrder(
            id=str(uuid.uuid4()),
            symbol=symbol,
            side=side,
            order_type=OrderType.TRAILING_STOP,
            quantity=quantity,
            trail_amount=trail_amount,
            trail_percent=trail_percent,
            activation_price=activation_price
        )

        with self._lock:
            self.trailing_stops[order.id] = order
            self.orders[order.id] = order
            self.stats['total_orders'] += 1

        logger.info(f"Created trailing stop: {order.id} - {side.value} {quantity} {symbol}")
        return order

    def create_oco_order(
        self,
        symbol: str,
        side: OrderSide,
        quantity: float,
        limit_price: float,  # Take profit
        stop_price: float,   # Stop loss
        limit_order_type: OrderType = OrderType.LIMIT,
        stop_order_type: OrderType = OrderType.STOP
    ) -> OCOOrder:
        """
        Create One-Cancels-Other order.

        When either order fills, the other is automatically cancelled.

        Args:
            symbol: Trading symbol
            side: Order side
            quantity: Order quantity
            limit_price: Price for limit order (take profit)
            stop_price: Price for stop order (stop loss)

        Returns:
            OCOOrder
        """
        # Create the two orders
        limit_order = Order(
            id=str(uuid.uuid4()),
            symbol=symbol,
            side=side,
            order_type=limit_order_type,
            quantity=quantity,
            price=limit_price
        )

        stop_order = Order(
            id=str(uuid.uuid4()),
            symbol=symbol,
            side=side,
            order_type=stop_order_type,
            quantity=quantity,
            stop_price=stop_price
        )

        oco = OCOOrder(
            id=str(uuid.uuid4()),
            symbol=symbol,
            order1=limit_order,
            order2=stop_order
        )

        # Link orders
        limit_order.parent_id = oco.id
        stop_order.parent_id = oco.id

        with self._lock:
            self.oco_orders[oco.id] = oco
            self.orders[limit_order.id] = limit_order
            self.orders[stop_order.id] = stop_order
            self.stats['total_orders'] += 2

        logger.info(f"Created OCO order: {oco.id} - TP@{limit_price}, SL@{stop_price}")
        return oco

    def create_bracket_order(
        self,
        symbol: str,
        side: OrderSide,
        quantity: float,
        entry_type: OrderType,
        entry_price: Optional[float],
        stop_loss_price: float,
        take_profit_price: float
    ) -> BracketOrder:
        """
        Create bracket order (entry + SL + TP).

        Args:
            symbol: Trading symbol
            side: Entry side (BUY for long, SELL for short)
            quantity: Position size
            entry_type: Entry order type (MARKET or LIMIT)
            entry_price: Entry price (required for LIMIT)
            stop_loss_price: Stop loss price
            take_profit_price: Take profit price

        Returns:
            BracketOrder
        """
        # Exit side is opposite of entry
        exit_side = OrderSide.SELL if side == OrderSide.BUY else OrderSide.BUY

        # Create entry order
        entry_order = Order(
            id=str(uuid.uuid4()),
            symbol=symbol,
            side=side,
            order_type=entry_type,
            quantity=quantity,
            price=entry_price
        )

        # Create stop loss (initially pending until entry fills)
        stop_loss_order = Order(
            id=str(uuid.uuid4()),
            symbol=symbol,
            side=exit_side,
            order_type=OrderType.STOP,
            quantity=quantity,
            stop_price=stop_loss_price,
            status=OrderStatus.PENDING
        )

        # Create take profit (initially pending until entry fills)
        take_profit_order = Order(
            id=str(uuid.uuid4()),
            symbol=symbol,
            side=exit_side,
            order_type=OrderType.LIMIT,
            quantity=quantity,
            price=take_profit_price,
            status=OrderStatus.PENDING
        )

        bracket = BracketOrder(
            id=str(uuid.uuid4()),
            symbol=symbol,
            side=side,
            entry_order=entry_order,
            stop_loss_order=stop_loss_order,
            take_profit_order=take_profit_order
        )

        # Link orders
        entry_order.parent_id = bracket.id
        entry_order.child_orders = [stop_loss_order.id, take_profit_order.id]
        stop_loss_order.parent_id = bracket.id
        take_profit_order.parent_id = bracket.id

        with self._lock:
            self.bracket_orders[bracket.id] = bracket
            self.orders[entry_order.id] = entry_order
            self.orders[stop_loss_order.id] = stop_loss_order
            self.orders[take_profit_order.id] = take_profit_order
            self.stats['total_orders'] += 3

        logger.info(
            f"Created bracket order: {bracket.id} - "
            f"Entry@{entry_price or 'MARKET'}, SL@{stop_loss_price}, TP@{take_profit_price}"
        )
        return bracket

    def create_conditional_order(
        self,
        order: Order,
        conditions: List[Dict[str, Any]],
        condition_logic: str = "AND"
    ) -> ConditionalOrder:
        """
        Create conditional order.

        Conditions format:
        [
            {'type': 'price_above', 'value': 2100.00},
            {'type': 'price_below', 'value': 2050.00},
            {'type': 'indicator', 'name': 'RSI', 'operator': '>', 'value': 70},
            {'type': 'time_after', 'value': '09:00'},
        ]

        Args:
            order: The order to execute when conditions are met
            conditions: List of condition definitions
            condition_logic: "AND" or "OR"

        Returns:
            ConditionalOrder
        """
        conditional = ConditionalOrder(
            id=str(uuid.uuid4()),
            order=order,
            conditions=conditions,
            condition_logic=condition_logic
        )

        order.parent_id = conditional.id

        with self._lock:
            self.conditional_orders[conditional.id] = conditional
            self.orders[order.id] = order
            self.stats['total_orders'] += 1

        logger.info(f"Created conditional order: {conditional.id} with {len(conditions)} conditions")
        return conditional

    def create_scaled_order(
        self,
        symbol: str,
        side: OrderSide,
        total_quantity: float,
        num_levels: int,
        start_price: float,
        end_price: float,
        distribution: str = "equal"  # 'equal', 'pyramid', 'inverse_pyramid'
    ) -> ScaledOrder:
        """
        Create scaled order with multiple price levels.

        Args:
            symbol: Trading symbol
            side: Order side
            total_quantity: Total quantity across all levels
            num_levels: Number of price levels
            start_price: Starting price
            end_price: Ending price
            distribution: Quantity distribution method

        Returns:
            ScaledOrder
        """
        # Calculate price levels
        price_step = (end_price - start_price) / (num_levels - 1) if num_levels > 1 else 0
        prices = [start_price + (i * price_step) for i in range(num_levels)]

        # Calculate quantities based on distribution
        if distribution == "equal":
            quantities = [total_quantity / num_levels] * num_levels
        elif distribution == "pyramid":
            # More at favorable prices (lower for buy, higher for sell)
            weights = list(range(1, num_levels + 1))
            total_weight = sum(weights)
            quantities = [(w / total_weight) * total_quantity for w in weights]
        elif distribution == "inverse_pyramid":
            weights = list(range(num_levels, 0, -1))
            total_weight = sum(weights)
            quantities = [(w / total_weight) * total_quantity for w in weights]
        else:
            quantities = [total_quantity / num_levels] * num_levels

        # Create levels
        levels = [{'price': p, 'quantity': q} for p, q in zip(prices, quantities)]

        # Create child orders
        child_orders = []
        for level in levels:
            child = Order(
                id=str(uuid.uuid4()),
                symbol=symbol,
                side=side,
                order_type=OrderType.LIMIT,
                quantity=level['quantity'],
                price=level['price']
            )
            child_orders.append(child)

        scaled = ScaledOrder(
            id=str(uuid.uuid4()),
            symbol=symbol,
            side=side,
            total_quantity=total_quantity,
            levels=levels,
            child_orders=child_orders
        )

        # Link orders
        for child in child_orders:
            child.parent_id = scaled.id

        with self._lock:
            self.scaled_orders[scaled.id] = scaled
            for child in child_orders:
                self.orders[child.id] = child
            self.stats['total_orders'] += len(child_orders)

        logger.info(f"Created scaled order: {scaled.id} with {num_levels} levels")
        return scaled

    def update_trailing_stop(self, order_id: str, current_price: float) -> Optional[float]:
        """
        Update trailing stop price based on current price.

        Args:
            order_id: Trailing stop order ID
            current_price: Current market price

        Returns:
            New stop price if updated, None otherwise
        """
        with self._lock:
            if order_id not in self.trailing_stops:
                return None

            order = self.trailing_stops[order_id]

            # Check activation
            if order.activation_price:
                if order.side == OrderSide.SELL and current_price < order.activation_price:
                    return None  # Not yet activated
                if order.side == OrderSide.BUY and current_price > order.activation_price:
                    return None

            # Update highest/lowest price
            if order.side == OrderSide.SELL:  # Long position
                if current_price > order.highest_price:
                    order.highest_price = current_price

                    # Calculate new stop
                    if order.trail_percent:
                        new_stop = current_price * (1 - order.trail_percent / 100)
                    elif order.trail_amount:
                        new_stop = current_price - order.trail_amount
                    else:
                        return None

                    order.stop_price = new_stop
                    order.updated_at = datetime.utcnow()
                    logger.debug(f"Updated trailing stop {order_id}: {new_stop}")
                    return new_stop

            else:  # Short position
                if current_price < order.lowest_price:
                    order.lowest_price = current_price

                    if order.trail_percent:
                        new_stop = current_price * (1 + order.trail_percent / 100)
                    elif order.trail_amount:
                        new_stop = current_price + order.trail_amount
                    else:
                        return None

                    order.stop_price = new_stop
                    order.updated_at = datetime.utcnow()
                    logger.debug(f"Updated trailing stop {order_id}: {new_stop}")
                    return new_stop

        return None

    def evaluate_conditional_order(
        self,
        order_id: str,
        market_data: Dict[str, Any]
    ) -> bool:
        """
        Evaluate conditions for a conditional order.

        Args:
            order_id: Conditional order ID
            market_data: Current market data

        Returns:
            True if conditions are met
        """
        with self._lock:
            if order_id not in self.conditional_orders:
                return False

            conditional = self.conditional_orders[order_id]
            conditional.evaluation_count += 1
            conditional.last_evaluated = datetime.utcnow()

            results = []
            current_price = market_data.get('price', 0)

            for condition in conditional.conditions:
                cond_type = condition.get('type', '')
                value = condition.get('value')

                if cond_type == 'price_above':
                    results.append(current_price > value)
                elif cond_type == 'price_below':
                    results.append(current_price < value)
                elif cond_type == 'indicator':
                    # Would need indicator values from market_data
                    indicator_value = market_data.get(condition.get('name'), 0)
                    operator = condition.get('operator', '>')
                    if operator == '>':
                        results.append(indicator_value > value)
                    elif operator == '<':
                        results.append(indicator_value < value)
                    elif operator == '==':
                        results.append(indicator_value == value)
                elif cond_type == 'time_after':
                    current_time = datetime.utcnow().time()
                    target_time = datetime.strptime(str(value), '%H:%M').time()
                    results.append(current_time >= target_time)

            # Apply logic
            if conditional.condition_logic == "AND":
                return all(results) if results else False
            else:  # OR
                return any(results) if results else False

    def handle_order_fill(self, order_id: str, fill_price: float, fill_quantity: float):
        """
        Handle order fill event.

        Manages linked orders (OCO cancellation, bracket activation, etc.)

        Args:
            order_id: Filled order ID
            fill_price: Fill price
            fill_quantity: Filled quantity
        """
        with self._lock:
            if order_id not in self.orders:
                return

            order = self.orders[order_id]
            order.filled_quantity += fill_quantity
            order.average_fill_price = fill_price
            order.updated_at = datetime.utcnow()

            if order.filled_quantity >= order.quantity:
                order.status = OrderStatus.FILLED
                self.stats['filled_orders'] += 1
            else:
                order.status = OrderStatus.PARTIALLY_FILLED

            # Handle OCO
            if order.parent_id in self.oco_orders:
                self._handle_oco_fill(order.parent_id, order_id)

            # Handle bracket
            if order.parent_id in self.bracket_orders:
                self._handle_bracket_fill(order.parent_id, order_id)

        logger.info(f"Order filled: {order_id} - {fill_quantity}@{fill_price}")

    def _handle_oco_fill(self, oco_id: str, filled_order_id: str):
        """Handle OCO order fill - cancel the other order."""
        oco = self.oco_orders[oco_id]

        if oco.order1.id == filled_order_id:
            other_order = oco.order2
        else:
            other_order = oco.order1

        # Cancel the other order
        other_order.status = OrderStatus.CANCELLED
        oco.triggered_order_id = filled_order_id
        oco.cancelled_order_id = other_order.id
        oco.status = OrderStatus.FILLED
        self.stats['oco_triggered'] += 1

        logger.info(f"OCO triggered: {oco_id} - Cancelled {other_order.id}")

    def _handle_bracket_fill(self, bracket_id: str, filled_order_id: str):
        """Handle bracket order fill."""
        bracket = self.bracket_orders[bracket_id]

        # If entry filled, activate SL and TP
        if filled_order_id == bracket.entry_order.id:
            bracket.position_filled = True
            bracket.stop_loss_order.status = OrderStatus.OPEN
            bracket.take_profit_order.status = OrderStatus.OPEN
            logger.info(f"Bracket entry filled: {bracket_id} - SL and TP activated")

        # If SL or TP filled, cancel the other
        elif filled_order_id == bracket.stop_loss_order.id:
            bracket.take_profit_order.status = OrderStatus.CANCELLED
            bracket.status = OrderStatus.FILLED
            self.stats['brackets_completed'] += 1
            logger.info(f"Bracket completed: {bracket_id} - SL hit")

        elif filled_order_id == bracket.take_profit_order.id:
            bracket.stop_loss_order.status = OrderStatus.CANCELLED
            bracket.status = OrderStatus.FILLED
            self.stats['brackets_completed'] += 1
            logger.info(f"Bracket completed: {bracket_id} - TP hit")

    def cancel_order(self, order_id: str) -> bool:
        """Cancel an order."""
        with self._lock:
            if order_id not in self.orders:
                return False

            order = self.orders[order_id]
            if order.status not in [OrderStatus.PENDING, OrderStatus.OPEN]:
                return False

            order.status = OrderStatus.CANCELLED
            order.updated_at = datetime.utcnow()
            self.stats['cancelled_orders'] += 1

            logger.info(f"Order cancelled: {order_id}")
            return True

    def get_order(self, order_id: str) -> Optional[Order]:
        """Get order by ID."""
        return self.orders.get(order_id)

    def get_open_orders(self, symbol: str = None) -> List[Order]:
        """Get all open orders, optionally filtered by symbol."""
        with self._lock:
            open_orders = [
                o for o in self.orders.values()
                if o.status in [OrderStatus.PENDING, OrderStatus.OPEN]
            ]
            if symbol:
                open_orders = [o for o in open_orders if o.symbol == symbol]
            return open_orders

    def get_statistics(self) -> Dict[str, Any]:
        """Get order manager statistics."""
        with self._lock:
            return {
                **self.stats,
                'active_orders': len([o for o in self.orders.values()
                                     if o.status in [OrderStatus.PENDING, OrderStatus.OPEN]]),
                'active_oco': len([o for o in self.oco_orders.values()
                                  if o.status == OrderStatus.PENDING]),
                'active_brackets': len([b for b in self.bracket_orders.values()
                                       if b.status in [OrderStatus.PENDING, OrderStatus.OPEN]]),
                'trailing_stops': len(self.trailing_stops),
                'conditional_orders': len(self.conditional_orders),
            }

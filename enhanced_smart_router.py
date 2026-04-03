# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
# enhanced_smart_router.py
"""
Institutional-Grade Smart Order Router v3.0
Multi-Venue Execution | AI-Powered Routing | Market Impact Optimization
"""

import asyncio
import logging
from abc import ABC, abstractmethod
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum, auto
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)


class OrderType(Enum):
    """Order types"""

    MARKET = auto()
    LIMIT = auto()
    STOP = auto()
    STOP_LIMIT = auto()
    ICEBERG = auto()
    TWAP = auto()
    VWAP = auto()
    IMPLEMENTATION_SHORTFALL = auto()
    ADAPTIVE = auto()


class OrderSide(Enum):
    """Order sides"""

    BUY = 1
    SELL = -1


class OrderStatus(Enum):
    """Order lifecycle"""

    PENDING = auto()
    SUBMITTED = auto()
    PARTIAL = auto()
    FILLED = auto()
    CANCELLED = auto()
    REJECTED = auto()
    EXPIRED = auto()


class VenueType(Enum):
    """Trading venue types"""

    EXCHANGE = auto()
    DARK_POOL = auto()
    ATS = auto()
    MAKER = auto()  # Internal matching
    OTC = auto()


@dataclass
class Venue:
    """Trading venue configuration"""

    name: str
    venue_type: VenueType
    maker_fee: float = 0.0
    taker_fee: float = 0.0004  # 4 bps
    latency_ms: float = 10.0
    reliability_score: float = 1.0  # 0-1

    # Capacity
    max_order_size: float = 1000000
    min_order_size: float = 0.01

    # Specialization
    preferred_assets: set[str] = field(default_factory=set)

    def total_cost(self, notional: float, is_maker: bool = False) -> float:
        """Calculate total cost for trade"""
        fee = self.maker_fee if is_maker else self.taker_fee
        return notional * fee


@dataclass
class Order:
    """Order structure"""

    id: str
    symbol: str
    side: OrderSide
    size: float
    order_type: OrderType
    price: float | None = None  # For limit orders
    stop_price: float | None = None  # For stop orders

    # Execution parameters
    time_in_force: str = "GTC"  # GTC, IOC, FOK, DAY
    display_size: float | None = None  # For iceberg
    arrival_price: float | None = None

    # State
    status: OrderStatus = OrderStatus.PENDING
    filled_size: float = 0.0
    avg_fill_price: float = 0.0
    remaining_size: float = field(init=False)

    # Metadata
    created_at: datetime = field(default_factory=datetime.now)
    strategy_id: str | None = None
    parent_order_id: str | None = None  # For child orders

    def __post_init__(self):
        self.remaining_size = self.size - self.filled_size

    @property
    def is_filled(self) -> bool:
        return abs(self.filled_size - self.size) < 0.0001

    @property
    def notional(self) -> float:
        price = self.price or self.avg_fill_price or 0
        return abs(self.size) * price


@dataclass
class Fill:
    """Execution fill"""

    fill_id: str
    order_id: str
    symbol: str
    size: float
    price: float
    venue: str
    timestamp: datetime
    fee: float
    is_maker: bool = False
    slippage_bps: float = 0.0


class MarketImpactModel:
    """
    Almgren-Chriss market impact model.
    Separates temporary and permanent impact.
    """

    def __init__(
        self,
        eta: float = 0.142,  # Temporary impact coefficient
        gamma: float = 0.314,  # Permanent impact coefficient
        beta: float = 0.6,  # Decay exponent
        sigma: float = 0.02,
    ):  # Daily volatility
        self.eta = eta
        self.gamma = gamma
        self.beta = beta
        self.sigma = sigma

    def temporary_impact(
        self,
        X: float,  # Order size
        T: float,  # Execution time (fraction of day)
        V: float,  # Average daily volume
    ) -> float:
        """
        Temporary impact (decays after execution).
        h(X/T) = eta * sigma * (X/(V*T))^beta
        """
        if T <= 0 or V <= 0:
            return 0.0

        participation = X / (V * T)
        return self.eta * self.sigma * (participation**self.beta)

    def permanent_impact(
        self,
        X: float,  # Order size
        V: float,  # ADV
    ) -> float:
        """
        Permanent impact (persists after execution).
        g(X) = gamma * sigma * (X/V)^beta
        """
        if V <= 0:
            return 0.0

        participation = X / V
        return self.gamma * self.sigma * (participation**self.beta)

    def total_cost(self, X: float, T: float, V: float, price: float) -> dict[str, float]:
        """Calculate total market impact cost"""
        temp = self.temporary_impact(X, T, V)
        perm = self.permanent_impact(X, V)

        return {
            "temporary_impact_bps": temp * 10000,
            "permanent_impact_bps": perm * 10000,
            "total_impact_bps": (temp + perm) * 10000,
            "temporary_cost": temp * price * X,
            "permanent_cost": perm * price * X,
            "total_cost": (temp + perm) * price * X,
        }


class ExecutionStrategy(ABC):
    """Base class for execution algorithms"""

    def __init__(self, order: Order, venues: list[Venue]):
        self.order = order
        self.venues = venues
        self.fills: list[Fill] = []
        self.is_complete = False
        # Per-strategy seeded RNG for deterministic simulation in tests.
        # Seed is derived from the order id so different orders get different
        # but reproducible sequences.
        self._rng = np.random.default_rng(seed=abs(hash(order.id)) % (2**31) if order.id else 42)

    @abstractmethod
    async def execute(self) -> list[Fill]:
        """Execute the order"""

    def update_order(self, fill: Fill):
        """Update order state with new fill"""
        self.order.filled_size += fill.size
        self.order.remaining_size -= fill.size

        # Update average fill price
        total_value = self.order.avg_fill_price * (self.order.filled_size - fill.size)
        total_value += fill.price * fill.size
        self.order.avg_fill_price = total_value / self.order.filled_size if self.order.filled_size > 0 else 0

        self.fills.append(fill)

        if self.order.is_filled:
            self.is_complete = True
            self.order.status = OrderStatus.FILLED


class TWAPStrategy(ExecutionStrategy):
    """
    Time-Weighted Average Price execution.
    Slices order into equal time buckets.
    """

    def __init__(
        self,
        order: Order,
        venues: list[Venue],
        duration_minutes: int = 30,
        num_slices: int = 10,
    ):
        super().__init__(order, venues)
        self.duration = duration_minutes
        self.num_slices = num_slices
        self.slice_size = order.size / num_slices
        self.interval = (duration_minutes * 60) / num_slices

    async def execute(self) -> list[Fill]:
        """Execute TWAP slices"""
        logger.info("Starting TWAP: %s in %s slices", self.order.size, self.num_slices)


        for i in range(self.num_slices):
            if self.is_complete:
                break

            # Select best venue for this slice
            venue = self._select_venue()

            # Place slice order
            slice_order = Order(
                id=f"{self.order.id}_slice_{i}",
                symbol=self.order.symbol,
                side=self.order.side,
                size=self.slice_size,
                order_type=OrderType.MARKET,
                parent_order_id=self.order.id,
            )

            # Simulate fill (would be actual API call)
            fill = await self._simulate_fill(slice_order, venue)
            if fill:
                self.update_order(fill)
                logger.info("Slice %s/%s filled: %s @ %s", i + 1, self.num_slices, fill.size, fill.price)


            # Wait for next interval
            if i < self.num_slices - 1:
                await asyncio.sleep(self.interval)

        return self.fills

    def _select_venue(self) -> Venue:
        """Select optimal venue based on cost and latency"""
        # Simple selection: lowest total cost
        costs = []
        for venue in self.venues:
            cost = venue.total_cost(self.slice_size * self.order.price if self.order.price else 100000)
            latency_penalty = venue.latency_ms * 0.001  # Convert to cost
            costs.append((cost + latency_penalty, venue))

        return min(costs, key=lambda x: x[0])[1]

    async def _simulate_fill(self, order: Order, venue: Venue) -> Fill | None:
        """
        Simulate a fill for paper-trading / backtesting.

        Uses the order's arrival_price or limit price as the reference price.
        Raises RuntimeError if no reference price is available — callers must
        supply a real market price via order.arrival_price before simulating.
        """
        # Simulate latency
        await asyncio.sleep(venue.latency_ms / 1000)

        # Use the real reference price supplied by the caller.
        base_price = order.arrival_price or order.price
        if base_price is None or base_price <= 0:
            raise RuntimeError(
                f"Cannot simulate fill for order {order.id}: "
                "order.arrival_price or order.price must be set to a real market price."
            )

        # Apply realistic slippage: ~1 bps std, bid/ask spread on sell side.
        slippage = self._rng.normal(0, 0.0001)  # 1 bps std
        fill_price = base_price * (1 + slippage)
        if order.side == OrderSide.SELL:
            fill_price *= 1 - venue.taker_fee  # Bid side net of fee

        fee = venue.total_cost(order.size * fill_price, is_maker=False)

        return Fill(
            fill_id=f"fill_{order.id}",
            order_id=order.id,
            symbol=order.symbol,
            size=order.size,
            price=fill_price,
            venue=venue.name,
            timestamp=datetime.now(UTC),
            fee=fee,
            is_maker=False,
            slippage_bps=slippage * 10000,
        )


class VWAPStrategy(ExecutionStrategy):
    """
    Volume-Weighted Average Price execution.
    Trades in proportion to historical volume profile.
    """

    def __init__(
        self,
        order: Order,
        venues: list[Venue],
        volume_profile: list[float],  # Historical volume by time bucket
        duration_minutes: int = 60,
    ):
        super().__init__(order, venues)
        self.volume_profile = volume_profile
        self.duration = duration_minutes
        self.total_volume = sum(volume_profile)

    async def execute(self) -> list[Fill]:
        """Execute based on volume profile"""
        # Calculate slice sizes based on volume profile
        slice_sizes = [(vol / self.total_volume) * self.order.size for vol in self.volume_profile]

        for i, size in enumerate(slice_sizes):
            if size < 0.001 or self.is_complete:
                continue

            venue = self._select_venue()

            slice_order = Order(
                id=f"{self.order.id}_vwap_{i}",
                symbol=self.order.symbol,
                side=self.order.side,
                size=size,
                order_type=OrderType.MARKET,
                parent_order_id=self.order.id,
            )

            fill = await self._simulate_fill(slice_order, venue)
            if fill:
                self.update_order(fill)

            # Wait proportionally
            await asyncio.sleep((self.duration * 60) / len(self.volume_profile))

        return self.fills

    def _select_venue(self) -> Venue:
        """Select venue with capacity for volume"""
        # Prefer venues with lower fees for large slices
        suitable = [v for v in self.venues if v.max_order_size > self.order.size / len(self.volume_profile)]
        return min(suitable, key=lambda v: v.taker_fee) if suitable else self.venues[0]


class ImplementationShortfallStrategy(ExecutionStrategy):
    """
    Implementation Shortfall (Arrival Price) strategy.
    Balances market impact vs opportunity cost.
    """

    def __init__(
        self,
        order: Order,
        venues: list[Venue],
        risk_aversion: float = 1.0,  # 1 = risk-neutral, >1 = more urgency
        expected_volatility: float = 0.02,
    ):
        super().__init__(order, venues)
        self.risk_aversion = risk_aversion
        self.volatility = expected_volatility
        if not order.arrival_price or order.arrival_price <= 0:
            raise ValueError(
                f"ImplementationShortfallStrategy requires order.arrival_price "
                f"to be set to a real market price (got {order.arrival_price!r})."
            )
        self.arrival_price = order.arrival_price

        # Almgren-Chriss parameters
        self.impact_model = MarketImpactModel()

    def optimal_trajectory(self) -> list[float]:
        """
        Calculate optimal trading trajectory using Almgren-Chriss.
        Returns list of trade sizes for each period.
        """
        # Simplified: Linear decay with urgency adjustment
        T = 10  # Number of periods
        urgency = self.risk_aversion * self.volatility

        # More urgency = faster execution
        decay_factor = 1 + urgency

        trajectory = []
        remaining = self.order.size

        for t in range(T):
            trade = remaining * (decay_factor / (T - t + decay_factor - 1))
            trajectory.append(trade)
            remaining -= trade

        return trajectory

    async def execute(self) -> list[Fill]:
        """Execute optimal trajectory"""
        trajectory = self.optimal_trajectory()

        for i, size in enumerate(trajectory):
            if self.is_complete:
                break

            # Adjust based on market conditions
            venue = self._select_venue()

            slice_order = Order(
                id=f"{self.order.id}_is_{i}",
                symbol=self.order.symbol,
                side=self.order.side,
                size=size,
                order_type=OrderType.MIXED,  # Adaptive
                parent_order_id=self.order.id,
            )

            fill = await self._simulate_fill(slice_order, venue)
            if fill:
                self.update_order(fill)

                # Calculate implementation shortfall
                shortfall = (fill.price - self.arrival_price) / self.arrival_price
                if self.order.side == OrderSide.SELL:
                    shortfall = -shortfall

                logger.info("Slice %s: IS = %s", i + 1, shortfall)


            await asyncio.sleep(6)  # 10 slices over 1 minute

        return self.fills

    def _select_venue(self) -> Venue:
        """Select venue minimizing total cost including impact"""
        notional = self.order.size * self.arrival_price
        return min(self.venues, key=lambda v: v.total_cost(notional))


class SmartOrderRouter:
    """
    Intelligent order routing across multiple venues.
    Optimizes for cost, latency, and execution quality.
    """

    def __init__(
        self,
        venues: list[Venue] | None = None,
        default_strategy: OrderType = OrderType.TWAP,
    ):
        self.venues = venues or self._default_venues()
        self.default_strategy = default_strategy

        # State
        self.active_orders: dict[str, Order] = {}
        self.order_history: deque = deque(maxlen=10000)
        self.fill_history: deque = deque(maxlen=10000)

        # Performance tracking
        self.venue_performance: dict[str, deque] = {v.name: deque(maxlen=100) for v in self.venues}

        # Market impact model
        self.impact_model = MarketImpactModel()

        # Routing AI
        self.routing_weights: dict[str, float] = {
            "cost": 0.3,
            "latency": 0.2,
            "reliability": 0.3,
            "fill_rate": 0.2,
        }

        logger.info("SmartOrderRouter initialized with %s venues", len(self.venues))


    def _default_venues(self) -> list[Venue]:
        """Create default venue configuration"""
        return [
            Venue(
                "Exchange_A",
                VenueType.EXCHANGE,
                maker_fee=0.0002,
                taker_fee=0.0005,
                latency_ms=15,
            ),
            Venue(
                "Exchange_B",
                VenueType.EXCHANGE,
                maker_fee=0.0001,
                taker_fee=0.0004,
                latency_ms=20,
            ),
            Venue(
                "DarkPool_1",
                VenueType.DARK_POOL,
                maker_fee=0.0001,
                taker_fee=0.0003,
                latency_ms=25,
            ),
            Venue("Internal", VenueType.MAKER, maker_fee=0.0, taker_fee=0.0, latency_ms=1),
        ]

    def route_order(self, order: Order) -> ExecutionStrategy:
        """
        Determine optimal execution strategy and venues.
        """
        # Select execution algorithm
        if order.order_type == OrderType.TWAP or self.default_strategy == OrderType.TWAP:
            strategy = TWAPStrategy(order, self.venues)
        elif order.order_type == OrderType.VWAP:
            strategy = VWAPStrategy(order, self.venues, [0.1] * 10)  # Flat profile
        elif order.order_type == OrderType.IMPLEMENTATION_SHORTFALL:
            strategy = ImplementationShortfallStrategy(order, self.venues)
        else:
            # Smart order routing for immediate execution
            strategy = self._create_smart_strategy(order)

        self.active_orders[order.id] = order
        return strategy

    def _create_smart_strategy(self, order: Order) -> ExecutionStrategy:
        """Create adaptive smart routing strategy"""
        # Score venues
        venue_scores = []
        for venue in self.venues:
            score = self._score_venue(venue, order)
            venue_scores.append((score, venue))

        # Select top venues
        venue_scores.sort(reverse=True)
        selected_venues = [v for _, v in venue_scores[:2]]  # Top 2

        # Create adaptive strategy
        return TWAPStrategy(order, selected_venues, num_slices=5)

    def _score_venue(self, venue: Venue, order: Order) -> float:
        """
        Score venue for this order using multi-factor model.
        """
        # Cost score (lower is better, so invert)
        cost_score = 1 - (venue.total_cost(order.notional) / order.notional * 100)

        # Latency score (lower is better)
        latency_score = 1 - (venue.latency_ms / 100)

        # Reliability score
        reliability_score = venue.reliability_score

        # Historical fill rate
        fills = self.venue_performance.get(venue.name, deque())
        fill_rate = np.mean(fills) if fills else 0.5

        # Weighted combination
        total_score = (
            self.routing_weights["cost"] * cost_score
            + self.routing_weights["latency"] * latency_score
            + self.routing_weights["reliability"] * reliability_score
            + self.routing_weights["fill_rate"] * fill_rate
        )

        return total_score

    async def execute_order(self, order: Order) -> dict[str, Any]:
        """
        Execute order with full lifecycle management.
        """
        logger.info("Routing order %s: %s %s %s", order.id, order.side.name, order.size, order.symbol)


        # Route to strategy
        strategy = self.route_order(order)

        # Execute
        fills = await strategy.execute()

        # Update performance
        for fill in fills:
            self.fill_history.append(fill)
            self.venue_performance[fill.venue].append(1.0)  # Success

        # Complete order
        order.status = OrderStatus.FILLED if order.is_filled else OrderStatus.PARTIAL
        self.order_history.append(order)
        del self.active_orders[order.id]

        # Calculate performance metrics
        vwap = self._calculate_vwap(fills)
        arrival_price = order.arrival_price or fills[0].price if fills else 0

        return {
            "order_id": order.id,
            "status": order.status.name,
            "filled_size": order.filled_size,
            "avg_price": order.avg_fill_price,
            "vwap": vwap,
            "implementation_shortfall": (order.avg_fill_price - arrival_price) / arrival_price if arrival_price else 0,
            "total_fees": sum(f.fee for f in fills),
            "total_slippage_bps": np.mean([f.slippage_bps for f in fills]),
            "fills": len(fills),
            "duration_seconds": (datetime.now(UTC) - order.created_at).total_seconds() if fills else 0,
        }

    def _calculate_vwap(self, fills: list[Fill]) -> float:
        """Calculate volume-weighted average price"""
        if not fills:
            return 0.0
        total_value = sum(f.price * f.size for f in fills)
        total_size = sum(f.size for f in fills)
        return total_value / total_size if total_size > 0 else 0.0

    def get_routing_report(self) -> dict[str, Any]:
        """Generate comprehensive routing performance report"""
        if not self.fill_history:
            return {"status": "no_data"}

        recent_fills = list(self.fill_history)[-100:]

        return {
            "total_orders": len(self.order_history),
            "total_fills": len(self.fill_history),
            "avg_slippage_bps": np.mean([f.slippage_bps for f in recent_fills]),
            "total_fees": sum(f.fee for f in self.fill_history),
            "venue_usage": self._calculate_venue_distribution(),
            "venue_performance": {
                name: {
                    "fill_rate": np.mean(list(history)) if history else 0,
                    "avg_slippage": np.mean([f.slippage_bps for f in self.fill_history if f.venue == name])
                    if self.fill_history
                    else 0,
                }
                for name, history in self.venue_performance.items()
            },
        }

    def _calculate_venue_distribution(self) -> dict[str, float]:
        """Calculate percentage of volume routed to each venue"""
        if not self.fill_history:
            return {}

        venue_volumes = defaultdict(float)
        for fill in self.fill_history:
            venue_volumes[fill.venue] += fill.size

        total = sum(venue_volumes.values())
        return {k: v / total for k, v in venue_volumes.items()}


# =============================================================================
# EXAMPLE USAGE & TESTING
# =============================================================================

if __name__ == "__main__":
    print("=" * 70)
    print("ENHANCED SMART ROUTER v3.0 - TEST SUITE")
    print("=" * 70)

    async def test_router():
        # Initialize router
        router = SmartOrderRouter()

        # Create test order
        order = Order(
            id="test_001",
            symbol="XAUUSD",
            side=OrderSide.BUY,
            size=100.0,
            order_type=OrderType.TWAP,
            arrival_price=1950.0,
        )

        print(f"\nOrder: {order.side.name} {order.size} {order.symbol}")
        print(f"Arrival price: {order.arrival_price}")

        # Execute
        result = await router.execute_order(order)

        print("\n" + "=" * 70)
        print("EXECUTION RESULT")
        print("=" * 70)
        print(f"Status: {result['status']}")
        print(f"Filled: {result['filled_size']:.2f}")
        print(f"Avg Price: {result['avg_price']:.4f}")
        print(f"VWAP: {result['vwap']:.4f}")
        print(f"Implementation Shortfall: {result['implementation_shortfall']:.4%}")
        print(f"Total Fees: ${result['total_fees']:.2f}")
        print(f"Avg Slippage: {result['total_slippage_bps']:.2f} bps")
        print(f"Duration: {result['duration_seconds']:.2f}s")

        # Routing report
        print("\n" + "=" * 70)
        print("ROUTING REPORT")
        print("=" * 70)
        report = router.get_routing_report()
        print(f"Venue distribution: {report['venue_usage']}")

        print("\n✅ Smart Router test completed!")

    # Run test
    asyncio.run(test_router())

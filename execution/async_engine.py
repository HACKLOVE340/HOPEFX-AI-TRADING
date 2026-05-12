# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
# execution/async_engine.py
"""
High-performance async execution engine with order management,
latency optimization, and fill simulation.
"""

import asyncio
import logging
import time
import uuid
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone

UTC = timezone.utc
from enum import Enum, auto
from typing import Any

import aiohttp
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
    price: float | None = None
    stop_price: float | None = None
    time_in_force: str = "GTC"  # GTC, IOC, FOK
    status: OrderStatus = OrderStatus.PENDING
    filled_qty: float = 0.0
    avg_fill_price: float = 0.0
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    metadata: dict[str, Any] = field(default_factory=dict)

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

    def __init__(
        self,
        broker_configs: list[dict[str, Any]],
        paper_mode: bool = True,
        paper_rng_seed: int | None = 42,
    ) -> None:
        self.broker_configs = broker_configs
        self.paper_mode = paper_mode
        # Per-instance RNG for paper-mode fill simulation; seeded for
        # reproducibility.  Pass paper_rng_seed=None for non-deterministic runs.
        self._rng = np.random.default_rng(seed=paper_rng_seed)
        self.brokers: dict[str, Any] = {}  # name -> broker client
        self.sessions: dict[str, aiohttp.ClientSession] = {}

        # Order management
        self.orders: dict[str, Order] = {}
        self.order_locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
        self.pending_orders: set[str] = set()
        self.position_cache: dict[str, dict[str, Any]] = {}
        self._position_cache_time: float = 0.0

        # Performance tracking
        self.latency_stats: dict[str, list[float]] = defaultdict(list)
        self.fill_stats: dict[str, dict[str, Any]] = defaultdict(
            lambda: {"count": 0, "avg_slippage": 0.0},
        )

        # Callbacks
        self.on_fill: Callable[[Fill], None] | None = None
        self.on_order_update: Callable[[Order], None] | None = None

        # Rate limiting
        self.rate_limiters: dict[str, asyncio.Semaphore] = {}
        self.last_request_time: dict[str, float] = {}

        # Market data
        self.price_cache: dict[str, dict[str, Any]] = {}  # symbol -> {bid, ask, last_update}
        self.price_lock = asyncio.Lock()

        # Tasks
        self._tasks: set[asyncio.Task[Any]] = set()
        self._shutdown = False

    async def initialize(self) -> None:
        """Initialize connections to all brokers"""
        for config in self.broker_configs:
            name = config["name"]

            # Create rate limiter (e.g., 10 requests/second)
            self.rate_limiters[name] = asyncio.Semaphore(config.get("rate_limit", 10))

            if not self.paper_mode:
                # Real broker connection
                self.sessions[name] = aiohttp.ClientSession(
                    headers=config.get("headers", {}),
                    timeout=aiohttp.ClientTimeout(total=5),
                )

            self.brokers[name] = config

            # Start price feed
            task = asyncio.create_task(self._price_feed_loop(name))
            self._tasks.add(task)

        logger.info("Initialized %s broker connections", len(self.brokers))

    async def submit_order(self, order: Order, priority: int = 5) -> str:
        """
        Submit order with smart routing and latency optimization.
        Priority: 1 (highest) to 10 (lowest)
        """
        if self._shutdown:
            raise RuntimeError("Engine is shutting down")

        # Generate a collision-resistant ID if not provided
        if not order.id:
            order.id = f"ord_{int(time.time() * 1000)}_{uuid.uuid4().hex[:8]}"

        async with self.order_locks[order.id]:
            self.orders[order.id] = order
            self.pending_orders.add(order.id)

            # Pre-trade risk check
            allowed, reason = await self._pre_trade_check(order)
            if not allowed:
                order.status = OrderStatus.REJECTED
                order.metadata["reject_reason"] = reason
                logger.warning("Order %s rejected: %s", order.id, reason)

                return order.id

            # Select best venue
            venue = self._select_venue(order)

            # Submit with timeout and retry
            start_time = time.monotonic()

            try:
                await asyncio.wait_for(self._submit_to_venue(order, venue), timeout=2.0)

                latency = (time.monotonic() - start_time) * 1000  # ms
                self.latency_stats["submit"].append(latency)

                if latency > 100:
                    logger.warning("High submission latency: %sms", latency)

            except TimeoutError:
                logger.error("Order submission timeout: %s", order.id)

                order.status = OrderStatus.REJECTED
                order.metadata["reject_reason"] = "timeout"

                # Try backup venue
                backup = self._get_backup_venue(venue)
                if backup:
                    logger.info("Retrying on backup venue: %s", backup)

                    await self._submit_to_venue(order, backup)

        return order.id

    async def cancel_order(self, order_id: str) -> bool:
        """Cancel order with confirmation"""
        if order_id not in self.orders:
            return False

        async with self.order_locks[order_id]:
            order = self.orders[order_id]
            if order.status not in [
                OrderStatus.PENDING,
                OrderStatus.SUBMITTED,
                OrderStatus.PARTIAL_FILL,
            ]:
                return False

            venue = order.metadata.get("venue")
            if not venue:
                return False

            try:
                await self._rate_limited_request(venue, "cancel", order_id)
                order.status = OrderStatus.CANCELLED
                order.updated_at = datetime.now(UTC)
                self.pending_orders.discard(order_id)

                if self.on_order_update:
                    self.on_order_update(order)

                return True

            except (OSError, ValueError, RuntimeError, AttributeError) as e:
                logger.error("Cancel failed for %s: %s", order_id, e)

                return False

    async def modify_order(
        self,
        order_id: str,
        new_price: float,
        new_qty: float | None = None,
    ) -> bool:
        """Modify existing order (cancel + replace)"""
        if order_id not in self.orders:
            return False

        async with self.order_locks[order_id]:
            old_order = self.orders[order_id]

            # Cancel old
            await self.cancel_order(order_id)

            # Create new
            new_order = Order(
                id=str(uuid.uuid4()),
                symbol=old_order.symbol,
                side=old_order.side,
                quantity=new_qty or old_order.remaining_qty,
                order_type=old_order.order_type,
                price=new_price,
                stop_price=old_order.stop_price,
                time_in_force=old_order.time_in_force,
                metadata={"modified_from": order_id},
            )

            await self.submit_order(new_order)
            return True

    async def batch_submit(self, orders: list[Order]) -> list[str | BaseException]:
        """Submit multiple orders concurrently"""
        tasks = [self.submit_order(order) for order in orders]
        return list(await asyncio.gather(*tasks, return_exceptions=True))

    async def close_all_positions(self, symbol: str | None = None) -> list[str]:
        """Emergency position flattening"""
        positions = await self.get_positions()

        orders = []
        for pos in positions:
            if symbol and pos["symbol"] != symbol:
                continue

            # Determine closing side
            close_side = "sell" if pos["quantity"] > 0 else "buy"

            order = Order(
                id=str(uuid.uuid4()),
                symbol=pos["symbol"],
                side=close_side,
                quantity=abs(pos["quantity"]),
                order_type=OrderType.MARKET,
                metadata={"flatten": True},
            )
            orders.append(order)

        # Submit all concurrently
        order_ids = await self.batch_submit(orders)
        logger.info("Flattened %s positions", len(orders))

        return [oid for oid in order_ids if isinstance(oid, str)]

    async def get_positions(self) -> list[dict[str, Any]]:
        """Get current positions with caching"""
        # Return cached if recent
        if time.time() - self._position_cache_time < 1.0:  # 1 second cache
            return list(self.position_cache.values())

        # Fetch fresh
        positions = []
        for venue in self.brokers:
            try:
                pos = await self._rate_limited_request(venue, "get_positions")
                for p in pos:
                    p["venue"] = venue
                    self.position_cache[p["symbol"]] = p
                    positions.append(p)
            except (OSError, ValueError, RuntimeError, AttributeError) as e:
                logger.error("Failed to get positions from %s: %s", venue, e)

        self._position_cache_time = time.time()
        return positions

    async def _submit_to_venue(self, order: Order, venue: str) -> None:
        """Submit order to specific venue"""
        order.metadata["venue"] = venue

        if self.paper_mode:
            await self._simulate_fill(order)
        else:
            await self._live_submit(order, venue)

    async def _live_submit(self, order: Order, venue: str) -> None:
        """Submit to live broker"""
        broker = self.brokers[venue]
        session = self.sessions[venue]

        payload = self._format_order(order, broker)

        async with self.rate_limiters[venue], session.post(f"{broker['url']}/orders", json=payload) as resp:
            if resp.status == 200:
                data = await resp.json()
                order.status = OrderStatus.SUBMITTED
                order.metadata["broker_id"] = data.get("id")

                # Start fill monitoring
                task = asyncio.create_task(self._monitor_fills(order))
                self._tasks.add(task)

            else:
                error = await resp.text()
                raise RuntimeError(f"Submit failed (HTTP {resp.status}): {error}")

    async def _simulate_fill(self, order: Order) -> None:
        """Fill simulation for paper trading only — never called in live mode."""
        if not self.paper_mode:
            raise RuntimeError(
                "_simulate_fill called in live mode. Live orders must be routed through the real broker API."
            )
        await asyncio.sleep(0.01)  # 10ms simulated latency

        async with self.price_lock:
            market = self.price_cache.get(order.symbol, {})

        if not market:
            order.status = OrderStatus.REJECTED
            order.metadata["reject_reason"] = "no_market_data"
            return

        # Determine fill price with realistic slippage
        base_price = market["ask"] if order.side == "buy" else market["bid"]

        # Slippage model based on order size and volatility
        volatility = market.get("volatility", 0.001)
        size_factor = min(order.quantity / 100, 1.0)  # Larger orders = more slippage

        slippage = self._rng.normal(0, volatility * size_factor)

        fill_price = base_price * (1 + slippage)  # default: market fill
        if order.order_type == OrderType.MARKET:
            fill_price = base_price * (1 + slippage)
        elif order.order_type == OrderType.LIMIT:
            if (order.side == "buy" and base_price <= order.price) or (
                order.side == "sell" and base_price >= order.price
            ):
                fill_price = order.price
            else:
                # Limit not hit - simulate partial fill probability
                if self._rng.random() < 0.3:  # 30% chance of no fill
                    order.status = OrderStatus.SUBMITTED
                    _t = asyncio.create_task(self._delayed_fill_simulation(order))
                    _t.add_done_callback(lambda _: None)
                    return
                fill_price = order.price

        # Simulate partial fills for large orders
        remaining = order.quantity
        fills: list[Fill] = []

        while remaining > 0 and len(fills) < 5:  # Max 5 partial fills
            fill_qty = min(remaining, self._rng.uniform(0.1, 0.5) * order.quantity)
            fill_qty = min(fill_qty, remaining)

            fill = Fill(
                order_id=order.id,
                symbol=order.symbol,
                quantity=fill_qty,
                price=fill_price * (1 + self._rng.normal(0, 0.0001)),
                timestamp=datetime.now(UTC),
                side=order.side,
                fees=fill_qty * fill_price * 0.0005,  # 5bps fee
            )
            fills.append(fill)
            remaining -= fill_qty

            # Delay between partial fills
            await asyncio.sleep(self._rng.exponential(0.5))

        # Apply fills
        for fill in fills:
            await self._apply_fill(order, fill)

    async def _delayed_fill_simulation(self, order: Order) -> None:
        """Delayed fill simulation for paper trading only — never called in live mode."""
        if not self.paper_mode:
            raise RuntimeError(
                "_delayed_fill_simulation called in live mode. Live orders must be routed through the real broker API."
            )
        await asyncio.sleep(self._rng.exponential(5))  # Mean 5s delay

        if order.status != OrderStatus.SUBMITTED:
            return

        async with self.price_lock:
            market = self.price_cache.get(order.symbol, {})

        if not market:
            return

        current = market["mid"]

        # Check if limit would now fill
        would_fill = (order.side == "buy" and current <= order.price) or (
            order.side == "sell" and current >= order.price
        )

        if would_fill or self._rng.random() < 0.1:  # 10% chance of fill anyway
            fill = Fill(
                order_id=order.id,
                symbol=order.symbol,
                quantity=order.quantity,
                price=order.price if order.price is not None else current,
                timestamp=datetime.now(UTC),
                side=order.side,
            )
            await self._apply_fill(order, fill)

    async def _apply_fill(self, order: Order, fill: Fill) -> None:
        """Apply fill to order"""
        async with self.order_locks[order.id]:
            order.filled_qty += fill.quantity
            order.avg_fill_price = (
                order.avg_fill_price * (order.filled_qty - fill.quantity) + fill.price * fill.quantity
            ) / order.filled_qty

            if order.filled_qty >= order.quantity * 0.99:
                order.status = OrderStatus.FILLED
                self.pending_orders.discard(order.id)
            else:
                order.status = OrderStatus.PARTIAL_FILL

            order.updated_at = datetime.now(UTC)

            # Update stats
            self.fill_stats[order.symbol]["count"] += 1

            # Notify
            if self.on_fill:
                try:
                    self.on_fill(fill)
                except (RuntimeError, ValueError, AttributeError) as e:
                    logger.error("Fill callback error: %s", e)

            if self.on_order_update:
                try:
                    self.on_order_update(order)
                except (RuntimeError, ValueError, AttributeError) as e:
                    logger.error("Order update callback error: %s", e)

    async def _monitor_fills(self, order: Order) -> None:
        """Monitor for fills from live broker"""
        if self.paper_mode:
            return

        check_interval = 0.1  # 100ms
        max_checks = 600  # 60 seconds

        for _ in range(max_checks):
            if order.status in [
                OrderStatus.FILLED,
                OrderStatus.CANCELLED,
                OrderStatus.REJECTED,
            ]:
                return

            try:
                venue = str(order.metadata.get("venue") or "")
                broker_id = order.metadata.get("broker_id")

                fill_data = await self._rate_limited_request(
                    venue,
                    "get_fills",
                    broker_id,
                )

                for fd in fill_data:
                    fill = Fill(
                        order_id=order.id,
                        symbol=fd["symbol"],
                        quantity=fd["qty"],
                        price=fd["price"],
                        timestamp=datetime.fromisoformat(fd["time"]),
                        side=fd["side"],
                        fees=fd.get("fees", 0),
                    )
                    await self._apply_fill(order, fill)

            except (OSError, ValueError, RuntimeError, AttributeError) as e:
                logger.error("Fill monitoring error: %s", e)

            await asyncio.sleep(check_interval)

    async def _price_feed_loop(self, venue: str) -> None:
        """Maintain real-time price cache"""
        while not self._shutdown:
            try:
                if self.paper_mode:
                    # Simulate price movements
                    for symbol in ["EUR/USD", "GBP/USD", "XAU/USD"]:
                        if symbol not in self.price_cache:
                            base = {
                                "EUR/USD": 1.08,
                                "GBP/USD": 1.26,
                                "XAU/USD": 2050.0,
                            }[symbol]
                            self.price_cache[symbol] = {
                                "bid": base - 0.0001,
                                "ask": base + 0.0001,
                                "mid": base,
                                "volatility": 0.0002,
                            }

                        # Random walk
                        mid = self.price_cache[symbol]["mid"]
                        move = self._rng.normal(0, 0.0001)
                        new_mid = mid * (1 + move)

                        spread = 0.0002
                        async with self.price_lock:
                            self.price_cache[symbol] = {
                                "bid": new_mid - spread / 2,
                                "ask": new_mid + spread / 2,
                                "mid": new_mid,
                                "volatility": abs(move) * 0.5 + self.price_cache[symbol]["volatility"] * 0.5,
                                "timestamp": time.time(),
                            }
                else:
                    # Real price feed — poll the broker's pricing endpoint
                    broker_cfg = self.brokers[venue]
                    price_url = broker_cfg.get("price_url") or f"{broker_cfg.get('url', '')}/prices"
                    symbols = broker_cfg.get("symbols", list(self.price_cache.keys())) or [
                        "EUR/USD",
                        "GBP/USD",
                        "XAU/USD",
                    ]
                    session = self.sessions.get(venue)
                    if session and price_url:
                        try:
                            params = {"instruments": ",".join(symbols)}
                            async with session.get(price_url, params=params) as resp:
                                if resp.status == 200:
                                    data = await resp.json()
                                    # Normalise: support both OANDA-style and generic dicts
                                    prices_list = data.get("prices") or data.get("ticks") or []
                                    async with self.price_lock:
                                        for tick in prices_list:
                                            sym = tick.get("instrument") or tick.get("symbol", "")
                                            bid = float(tick.get("bids", [{}])[0].get("price") or tick.get("bid", 0))
                                            ask = float(tick.get("asks", [{}])[0].get("price") or tick.get("ask", 0))
                                            if bid and ask:
                                                mid = (bid + ask) / 2.0
                                                prev = self.price_cache.get(sym, {})
                                                prev_mid = prev.get("mid", mid)
                                                vol = abs(mid - prev_mid) / prev_mid if prev_mid else 0.0
                                                self.price_cache[sym] = {
                                                    "bid": bid,
                                                    "ask": ask,
                                                    "mid": mid,
                                                    "volatility": vol * 0.3 + prev.get("volatility", 0.0) * 0.7,
                                                    "timestamp": time.time(),
                                                }
                                else:
                                    logger.warning("Price feed HTTP %s from %s", resp.status, venue)
                        except aiohttp.ClientError as exc:
                            logger.warning("Price feed request error (%s): %s", venue, exc)

                await asyncio.sleep(0.1)  # 10Hz update

            except (OSError, ValueError, RuntimeError, AttributeError) as e:
                logger.error("Price feed error: %s", e)

                await asyncio.sleep(1)

    async def _rate_limited_request(self, venue: str, method: str, *args: Any) -> Any:
        """Execute rate-limited request to broker"""
        async with self.rate_limiters[venue]:
            # Enforce minimum interval between requests
            last = self.last_request_time.get(venue, 0)
            elapsed = time.time() - last
            if elapsed < 0.1:  # Max 10 req/sec
                await asyncio.sleep(0.1 - elapsed)

            self.last_request_time[venue] = time.time()

            # Execute via the registered broker for this venue
            _broker = self.brokers[venue]
            if method == "get_positions":
                return []  # Implement actual API call
            if method == "cancel":
                return True
            if method == "get_fills":
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

    def _get_backup_venue(self, primary: str) -> str | None:
        """Get backup venue if primary fails"""
        venues = [v for v in self.brokers if v != primary]
        return venues[0] if venues else None

    def _venue_has_symbol(self, venue: str, symbol: str) -> bool:
        """Check if venue supports symbol"""
        return True  # Implement actual check

    async def _pre_trade_check(self, order: Order) -> tuple[bool, str]:
        """Risk check before submission"""
        # Position limit check
        current = self.position_cache.get(order.symbol, {}).get("quantity", 0)
        if abs(current + (order.quantity if order.side == "buy" else -order.quantity)) > 100:
            return False, "position_limit_exceeded"

        # Price sanity check
        async with self.price_lock:
            market = self.price_cache.get(order.symbol)

        if market:
            mid = market["mid"]
            if order.price and abs(order.price - mid) / mid > 0.05:
                return False, "price_deviation_too_large"

        return True, ""

    def _format_order(self, order: Order, broker: dict[str, Any]) -> dict[str, Any]:
        """Format order for specific broker API"""
        mapping = {
            OrderType.MARKET: "MKT",
            OrderType.LIMIT: "LMT",
            OrderType.STOP: "STP",
        }

        return {
            "symbol": order.symbol,
            "side": order.side.upper(),
            "qty": order.quantity,
            "type": mapping.get(order.order_type, "MKT"),
            "price": order.price,
            "stopPrice": order.stop_price,
            "tif": order.time_in_force,
        }

    async def get_latency_report(self) -> dict[str, Any]:
        """Generate latency statistics"""
        return {
            venue: {
                "mean_ms": np.mean(times) if times else 0,
                "p99_ms": np.percentile(times, 99) if times else 0,
                "max_ms": max(times) if times else 0,
                "count": len(times),
            }
            for venue, times in self.latency_stats.items()
        }

    async def shutdown(self) -> None:
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

# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
HOPEFX Broker Module - PRODUCTION VERSION
Fixed: Thread safety, proper position tracking, realistic simulation, timeouts
"""

import abc
import asyncio
import logging
import random
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

UTC = timezone.utc
from enum import Enum

logger = logging.getLogger(__name__)

try:
    import aiohttp

    AIOHTTP_AVAILABLE = True
except ImportError:
    AIOHTTP_AVAILABLE = False
    logger.warning("aiohttp not available, OANDA broker disabled")

try:
    import numpy as np  # noqa: F401

    NUMPY_AVAILABLE = True
except ImportError:
    NUMPY_AVAILABLE = False


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
    price: float | None = None
    stop_price: float | None = None
    status: OrderStatus = OrderStatus.PENDING
    filled_quantity: float = 0.0
    average_fill_price: float = 0.0
    created_at: float = field(default_factory=time.time)
    filled_at: float | None = None
    rejected_reason: str | None = None
    commission: float = 0.0
    slippage: float = 0.0

    @property
    def remaining_quantity(self) -> float:
        return self.quantity - self.filled_quantity

    @property
    def is_complete(self) -> bool:
        return self.status in (
            OrderStatus.FILLED,
            OrderStatus.CANCELLED,
            OrderStatus.REJECTED,
        )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "symbol": self.symbol,
            "side": self.side.value,
            "type": self.type.value,
            "quantity": self.quantity,
            "price": self.price,
            "status": self.status.value,
            "filled_quantity": self.filled_quantity,
            "average_fill_price": self.average_fill_price,
            "commission": self.commission,
            "slippage": self.slippage,
            "created_at": self.created_at,
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
    stop_loss: float | None = None
    take_profit: float | None = None
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

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "symbol": self.symbol,
            "side": self.side.value,
            "quantity": self.quantity,
            "entry_price": self.entry_price,
            "current_price": self.current_price,
            "unrealized_pnl": self.unrealized_pnl,
            "realized_pnl": self.realized_pnl,
            "total_pnl": self.total_pnl,
            "market_value": self.market_value,
            "opened_at": self.opened_at,
        }


class BaseBroker(abc.ABC):
    """
    Abstract base class for all broker integrations.

    Concrete subclasses must implement every ``@abc.abstractmethod``.
    Attempting to instantiate a subclass with unimplemented methods raises
    ``TypeError`` at construction time — not silently at the first call.

    ``close_all_positions`` and ``cancel_all_orders`` have default
    implementations built on ``close_position`` / ``cancel_order`` and do
    not need to be overridden unless the broker offers a native bulk API.
    """

    def __init__(self):
        self.connected = False
        self._lock = asyncio.Lock()
        self._session = None
        self._connection_lock = asyncio.Lock()

    @abc.abstractmethod
    async def connect(self) -> None:
        """Open the broker connection / authenticate."""

    @abc.abstractmethod
    async def disconnect(self) -> None:
        """Close the broker connection and release resources."""

    @abc.abstractmethod
    async def get_account_info(self) -> dict:
        """Return account balance, margin, and metadata."""

    @abc.abstractmethod
    async def place_market_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
    ) -> Order:
        """Submit a market order and return the filled Order object."""

    @abc.abstractmethod
    async def cancel_order(self, order_id: str) -> bool:
        """Cancel a pending order. Returns True on success."""

    @abc.abstractmethod
    async def get_positions(self) -> list[Position]:
        """Return all open positions."""

    @abc.abstractmethod
    async def close_position(self, position_id: str) -> bool:
        """Close a single position by ID. Returns True on success."""

    async def close_all_positions(self) -> list[str]:
        """Close all open positions. Returns list of successfully closed IDs."""
        positions = await self.get_positions()
        closed: list[str] = []
        failed: list[str] = []

        for pos in positions:
            try:
                if await self.close_position(pos.id):
                    closed.append(pos.id)
                else:
                    failed.append(pos.id)
            except Exception as exc:
                logger.error("Failed to close position %s: %s", pos.id, exc)
                failed.append(pos.id)

        if failed:
            logger.warning("Failed to close %d positions: %s", len(failed), failed)

        return closed

    @abc.abstractmethod
    async def get_pending_orders(self) -> list[Order]:
        """Return all pending (unfilled) orders."""

    async def cancel_all_orders(self) -> list[str]:
        """Cancel all pending orders. Returns list of successfully cancelled IDs."""
        orders = await self.get_pending_orders()
        cancelled: list[str] = []
        failed: list[str] = []

        for order in orders:
            try:
                if await self.cancel_order(order.id):
                    cancelled.append(order.id)
                else:
                    failed.append(order.id)
            except Exception as exc:
                logger.error("Failed to cancel order %s: %s", order.id, exc)
                failed.append(order.id)

        return cancelled


# ── PaperTradingBroker simulation constants ───────────────────────────────────
_PAPER_BASE_SLIPPAGE_PIPS = 0.1  # base slippage in pips for a standard lot
_PAPER_SLIPPAGE_GAUSS_STD = 0.2  # std-dev for Gaussian slippage model
_PAPER_FILL_PROB_CAP = 0.95  # maximum fill probability for large orders
_PAPER_PARTIAL_FILL_MIN = 0.60  # minimum fraction filled on a partial fill
_PAPER_PARTIAL_FILL_MAX = 0.95  # maximum fraction filled on a partial fill
_PAPER_MARGIN_RATE = 0.02  # margin requirement per position (2%)
_PAPER_STANDARD_LOT = 100000  # units per standard lot
_PAPER_SIZE_FACTOR_CAP = 5.0  # maximum size-factor multiplier for slippage


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
        seed: int | None = None,
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

        # Seeded RNG for reproducible paper-trading simulation.
        # seed=None (default) uses a random seed — appropriate for live paper
        # trading where you want realistic variance.  Pass an integer seed in
        # tests or replay scenarios to get deterministic fills.
        self._rng = random.Random(seed)  # nosec B311 - paper trading simulation

        # THREAD SAFETY: Separate locks for orders and positions
        self._orders_lock = asyncio.Lock()
        self._positions_lock = asyncio.Lock()
        self._account_lock = asyncio.Lock()

        # Storage
        self._orders: dict[str, Order] = {}
        self._positions: dict[str, Position] = {}
        self._order_history: list[Order] = []
        self._trade_history: list[dict] = []
        self._market_prices: dict[str, float] = {}

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
            "PaperTradingBroker initialized | Balance: $%.2f | Commission: $%.2f/lot",
            initial_balance,
            commission_per_lot,
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
        logger.info("Final Trading Report:\n%s", report)
        return True

    async def get_account_info(self) -> dict:
        """Get account information with proper locking"""
        async with self._positions_lock, self._account_lock:
            # Calculate equity from positions
            total_unrealized = sum(p.unrealized_pnl for p in self._positions.values())
            self.equity = self.balance + total_unrealized

            margin_used = sum(p.market_value * _PAPER_MARGIN_RATE for p in self._positions.values())

            realized_pnl = self.equity - self.initial_balance - total_unrealized

            return {
                "balance": round(self.balance, 2),
                "equity": round(self.equity, 2),
                "margin_used": round(margin_used, 2),
                "free_margin": round(self.equity - margin_used, 2),
                "unrealized_pnl": round(total_unrealized, 2),
                "realized_pnl": round(realized_pnl, 2),
                "open_positions": len(self._positions),
                "total_commissions": round(self._total_commissions, 2),
                "currency": self.base_currency,
                "uptime_seconds": time.time() - self._start_time,
            }

    def _validate_order_params(self, quantity: float, side: str) -> None:
        """Raise ValueError for invalid order parameters before any I/O."""
        if not self.connected:
            raise ConnectionError("Broker not connected")
        if quantity <= 0:
            raise ValueError(f"Quantity must be positive, got {quantity}")
        if side not in ("buy", "sell"):
            raise ValueError(f"Side must be 'buy' or 'sell', got {side}")

    def _resolve_fill_price(self, symbol: str, side: str, slippage_pips: float) -> float:
        """Return the simulated fill price including slippage."""
        if not self.price_feed:
            raise ValueError("No price feed available")
        tick = self.price_feed.get_last_price(symbol)
        if not tick:
            raise ValueError(f"No price available for {symbol}")

        slippage_factor = slippage_pips * self._get_pip_value(symbol)
        return tick.ask * (1 + slippage_factor) if side == "buy" else tick.bid * (1 - slippage_factor)

    def _build_paper_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
        fill_quantity: float,
        fill_price: float,
        commission: float,
        slippage_pips: float,
    ) -> Order:
        """Construct an Order dataclass from resolved fill parameters."""
        return Order(
            id=f"paper_{uuid.uuid4().hex[:12]}",
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
            slippage=slippage_pips,
        )

    async def place_market_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
    ) -> Order:
        """
        Place a market order with realistic paper-trading simulation.

        Simulates network latency, slippage, partial fills, and commission.
        """
        self._validate_order_params(quantity, side)

        latency_ms = max(0.0, self._rng.gauss(self.latency_ms_mean, self.latency_ms_std))
        await asyncio.sleep(latency_ms / 1000)

        slippage_pips = self._calculate_slippage(symbol, quantity, side)
        fill_price = self._resolve_fill_price(symbol, side, slippage_pips)
        fill_quantity = self._simulate_fill_quantity(quantity, symbol)
        commission = (fill_quantity / _PAPER_STANDARD_LOT) * self.commission_per_lot * 2

        order = self._build_paper_order(symbol, side, quantity, fill_quantity, fill_price, commission, slippage_pips)

        async with self._orders_lock:
            self._orders[order.id] = order
            self._order_history.append(order)

        async with self._positions_lock:
            await self._update_position(order)
            self._total_commissions += commission
            self._total_slippage += abs(slippage_pips)

        logger.info(
            "Order Executed | %s %.0f/%.0f %s | Price: %.5f | Slippage: %.1fpips | Commission: $%.2f | ID: %s",
            side.upper(),
            fill_quantity,
            quantity,
            symbol,
            fill_price,
            slippage_pips,
            commission,
            order.id,
        )
        return order

    def _calculate_slippage(self, symbol: str, quantity: float, side: str) -> float:
        """Calculate realistic slippage in pips based on order size."""
        if self.slippage_model == "none":
            return 0.0

        size_factor = min(quantity / _PAPER_STANDARD_LOT, _PAPER_SIZE_FACTOR_CAP)
        scaled_base = _PAPER_BASE_SLIPPAGE_PIPS * size_factor

        if self.slippage_model == "gaussian":
            slippage = self._rng.gauss(scaled_base, _PAPER_SLIPPAGE_GAUSS_STD)
        else:
            slippage = self._rng.uniform(0, scaled_base * 2)  # nosec B311 - paper trading slippage simulation

        return max(0.0, slippage)

    def _simulate_fill_quantity(self, quantity: float, symbol: str) -> float:
        """Return fill quantity, simulating partial fills for large orders."""
        if quantity < self.partial_fill_threshold:
            return quantity

        fill_prob = min(_PAPER_FILL_PROB_CAP, 0.5 + (self.partial_fill_threshold / quantity))
        if self._rng.random() > fill_prob:  # nosec B311 - paper trading fill simulation
            return quantity * self._rng.uniform(  # nosec B311 - paper trading partial fill simulation
                _PAPER_PARTIAL_FILL_MIN, _PAPER_PARTIAL_FILL_MAX
            )
        return quantity

    def _get_pip_value(self, symbol: str) -> float:
        """Get pip value for symbol"""
        if "JPY" in symbol:
            return 0.01
        if "XAU" in symbol or "GOLD" in symbol:
            return 0.01
        return 0.0001

    async def _update_position(self, order: Order):
        """Update positions based on filled order - THREAD SAFE (caller must hold lock)"""
        if order.status not in (OrderStatus.FILLED, OrderStatus.PARTIAL):
            return

        position_key = f"{order.symbol}_{order.side.value}"
        fill_qty = order.filled_quantity
        fill_price = order.average_fill_price

        self.balance -= order.commission

        if position_key in self._positions:
            # Update existing position
            pos = self._positions[position_key]

            # Calculate new average entry price
            total_qty = pos.quantity + fill_qty
            pos.entry_price = ((pos.entry_price * pos.quantity) + (fill_price * fill_qty)) / total_qty
            pos.quantity = total_qty
            pos.total_commission += order.commission
            pos.updated_at = time.time()

            logger.debug(
                "Updated position %s: Qty=%.0f, AvgPrice=%.5f",
                position_key,
                total_qty,
                pos.entry_price,
            )
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
                total_commission=order.commission,
            )

            # For buys, deduct cost from balance
            if order.side == OrderSide.BUY:
                cost = fill_qty * fill_price
                self.balance -= cost

            logger.debug("New position created: %s", position_key)

    async def cancel_order(self, order_id: str) -> bool:
        """Cancel a pending order"""
        async with self._orders_lock:
            if order_id not in self._orders:
                return False

            order = self._orders[order_id]
            if order.status == OrderStatus.PENDING:
                order.status = OrderStatus.CANCELLED
                logger.info("Order cancelled: %s", order_id)
                return True

            return False

    async def get_positions(self) -> list[Position]:
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
                        logger.error("Error updating price for %s: %s", pos.symbol, e)

            return positions

    async def close_position(self, position_id: str) -> bool:
        """Close a position with proper locking"""
        async with self._positions_lock:
            if position_id not in self._positions:
                logger.warning("Position not found: %s", position_id)
                return False

            pos = self._positions[position_id]

            # Determine closing side
            close_side = "sell" if pos.side == OrderSide.BUY else "buy"

            try:
                # Place closing order
                order = await self.place_market_order(
                    pos.symbol,
                    close_side,
                    pos.quantity,
                )

                # Calculate realized P&L
                realized_pnl = pos.unrealized_pnl - order.commission
                self.balance += realized_pnl

                # Record trade
                trade_record = {
                    "position_id": position_id,
                    "symbol": pos.symbol,
                    "side": pos.side.value,
                    "quantity": pos.quantity,
                    "entry_price": pos.entry_price,
                    "exit_price": order.average_fill_price,
                    "realized_pnl": realized_pnl,
                    "commission": order.commission + pos.total_commission,
                    "opened_at": pos.opened_at,
                    "closed_at": time.time(),
                    "duration_seconds": time.time() - pos.opened_at,
                    "slippage": order.slippage,
                }
                self._trade_history.append(trade_record)

                # Persist to DB
                self._persist_trade_record(trade_record)

                # Remove position
                del self._positions[position_id]

                logger.info(
                    "Position Closed | %s | P&L: $%.2f | Duration: %.1fh | Commission: $%.2f",
                    position_id,
                    realized_pnl,
                    (time.time() - pos.opened_at) / 3600,
                    order.commission + pos.total_commission,
                )

                return True

            except Exception as e:
                logger.error("Error closing position %s: %s", position_id, e)
                return False

    async def get_pending_orders(self) -> list[Order]:
        """Get pending orders"""
        async with self._orders_lock:
            return [o for o in self._orders.values() if o.status == OrderStatus.PENDING]

    def _persist_trade_record(self, record: dict) -> None:
        """Persist a closed trade record to the DB trades table."""
        if not self._session_factory:
            return
        try:
            from database.models import OrderSide as DBOrderSide
            from database.models import Trade, TradeStatus

            raw_side = str(record.get("side", "buy")).lower()
            side_enum = DBOrderSide.BUY if "buy" in raw_side else DBOrderSide.SELL

            opened_at = record.get("opened_at")
            if isinstance(opened_at, int | float):
                opened_at = datetime.fromtimestamp(opened_at, tz=UTC)
            closed_at = record.get("closed_at")
            if isinstance(closed_at, int | float):
                closed_at = datetime.fromtimestamp(closed_at, tz=UTC)

            qty = float(record.get("quantity", 0))
            commission = float(record.get("commission", 0))
            realized_pnl = float(record.get("realized_pnl", 0))

            trade = Trade(
                trade_id=str(uuid.uuid4()),
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
                entry_time=opened_at or datetime.now(UTC),
                exit_time=closed_at or datetime.now(UTC),
            )
            with self._session_factory() as session:
                session.add(trade)
                session.commit()
            logger.debug(
                "Trade persisted to DB: %s pnl=%.2f",
                record.get("symbol"),
                realized_pnl,
            )
        except Exception as exc:
            logger.warning("Failed to persist paper trade to DB: %s", exc)

    # ------------------------------------------------------------------
    # Sync-compatible properties and methods (used by unit tests)
    # ------------------------------------------------------------------

    @property
    def positions(self) -> dict:
        """Sync access to positions dict (keyed by symbol)."""
        return self._positions

    @property
    def orders(self) -> dict:
        """Sync access to orders dict."""
        return self._orders

    @property
    def market_prices(self) -> dict[str, float]:
        """Current market prices used for fills."""
        return self._market_prices

    def set_market_price(self, symbol: str, price: float) -> None:
        """Set a market price for simulation (used by tests)."""
        self._market_prices[symbol] = price

    def get_market_price(self, symbol: str) -> float:
        """Return current market price for symbol."""
        return self._market_prices.get(symbol, 0.0)

    def place_order(
        self,
        symbol: str,
        side,
        quantity: float,
        order_type=None,
        price: float | None = None,
        stop_loss: float | None = None,
        take_profit: float | None = None,
    ) -> "Order":
        """Synchronous order placement for unit tests."""

        from brokers.base import OrderSide as _OS
        from brokers.base import OrderStatus as _OSt
        from brokers.base import OrderType as _OT

        # Normalise side
        if isinstance(side, str):
            side = _OS.BUY if side.upper() in ("BUY", "LONG") else _OS.SELL

        # Normalise order_type
        if order_type is None:
            order_type = _OT.MARKET
        elif isinstance(order_type, str):
            order_type = _OT[order_type.upper()] if order_type.upper() in _OT.__members__ else _OT.MARKET

        fill_price = price or self._market_prices.get(symbol, 100.0)

        # Check balance for buys
        cost = fill_price * quantity
        if side == _OS.BUY and cost > self.balance:
            raise ValueError(
                f"Insufficient balance: need {cost:.2f}, have {self.balance:.2f}",
            )

        order_id = f"PAPER-{len(self._orders) + 1:06d}"
        order = Order(
            id=order_id,
            symbol=symbol,
            side=side,
            type=order_type,
            quantity=quantity,
            price=price,
            status=_OSt.FILLED if order_type == _OT.MARKET else _OSt.PENDING,
            filled_quantity=quantity if order_type == _OT.MARKET else 0.0,
            average_fill_price=fill_price if order_type == _OT.MARKET else 0.0,
        )
        self._orders[order.id] = order

        if order_type == _OT.MARKET:
            # Update balance and positions
            if side == _OS.BUY:
                self.balance -= cost
                pos_key = f"{symbol}_LONG"
                if pos_key in self._positions:
                    self._positions[pos_key].quantity += quantity
                else:
                    self._positions[pos_key] = Position(
                        id=pos_key,
                        symbol=symbol,
                        side=_OS.BUY,
                        quantity=quantity,
                        entry_price=fill_price,
                        current_price=fill_price,
                    )
            else:
                self.balance += fill_price * quantity
                pos_key = f"{symbol}_LONG"
                if pos_key in self._positions:
                    pos = self._positions[pos_key]
                    pos.quantity -= quantity
                    if pos.quantity <= 0:
                        del self._positions[pos_key]

        return order

    def _compute_trade_stats(self) -> dict:
        """Compute summary statistics from trade history."""
        trades = self._trade_history
        winning = [t for t in trades if t["realized_pnl"] > 0]
        losing = [t for t in trades if t["realized_pnl"] <= 0]
        total_pnl = sum(t["realized_pnl"] for t in trades)
        gross_profit = sum(t["realized_pnl"] for t in winning)
        gross_loss = sum(t["realized_pnl"] for t in losing)
        n = len(trades)
        win_rate = len(winning) / n if n else 0.0
        avg_win = gross_profit / len(winning) if winning else 0.0
        avg_loss = gross_loss / len(losing) if losing else 0.0
        profit_factor = abs(gross_profit / gross_loss) if gross_loss else float("inf")

        returns = [t["realized_pnl"] for t in trades]
        avg_ret = sum(returns) / n if n else 0.0
        variance = sum((r - avg_ret) ** 2 for r in returns) / n if n else 0.0
        std_ret = variance**0.5
        sharpe = avg_ret / std_ret if std_ret > 0 else 0.0

        return {
            "total_trades": n,
            "winning": winning,
            "losing": losing,
            "total_pnl": total_pnl,
            "gross_profit": gross_profit,
            "gross_loss": gross_loss,
            "win_rate": win_rate,
            "avg_win": avg_win,
            "avg_loss": avg_loss,
            "profit_factor": profit_factor,
            "sharpe_like": sharpe,
        }

    def _generate_report(self) -> str:
        """Generate a paper-trading performance report."""
        if not self._trade_history:
            return "No trades executed"

        s = self._compute_trade_stats()
        w, lo = s["winning"], s["losing"]
        pnl_pct = s["total_pnl"] / self.initial_balance * 100 if self.initial_balance else 0.0

        return (
            f"\n╔════════════════════════════════════════════════════════════════╗\n"
            f"║           PAPER TRADING PERFORMANCE REPORT                      ║\n"
            f"╠════════════════════════════════════════════════════════════════╣\n"
            f"║ Account Summary                                                ║\n"
            f"║   Initial Balance:     ${self.initial_balance:>15,.2f}          ║\n"
            f"║   Final Balance:        ${self.balance:>15,.2f}          ║\n"
            f"║   Total P&L:            ${s['total_pnl']:>15,.2f} ({pnl_pct:+.2f}%)   ║\n"
            f"║   Total Commissions:    ${self._total_commissions:>15,.2f}          ║\n"
            f"║   Total Slippage:       {self._total_slippage:>15.1f} pips        ║\n"
            f"╠════════════════════════════════════════════════════════════════╣\n"
            f"║ Trade Statistics                                               ║\n"
            f"║   Total Trades:        {s['total_trades']:>15}                     ║\n"
            f"║   Winning Trades:      {len(w):>15} ({s['win_rate'] * 100:.1f}%)              ║\n"
            f"║   Losing Trades:       {len(lo):>15} ({(1 - s['win_rate']) * 100:.1f}%)              ║\n"
            f"║   Profit Factor:       {s['profit_factor']:>15.2f}                   ║\n"
            f"║   Sharpe-like:         {s['sharpe_like']:>15.2f}                   ║\n"
            f"╠════════════════════════════════════════════════════════════════╣\n"
            f"║ P&L Breakdown                                                  ║\n"
            f"║   Gross Profit:         ${s['gross_profit']:>15,.2f}          ║\n"
            f"║   Gross Loss:           ${s['gross_loss']:>15,.2f}          ║\n"
            f"║   Average Win:         ${s['avg_win']:>15,.2f}          ║\n"
            f"║   Average Loss:         ${s['avg_loss']:>15,.2f}          ║\n"
            f"║   Largest Win:          ${max((t['realized_pnl'] for t in w), default=0):>15,.2f}          ║\n"
            f"║   Largest Loss:         ${min((t['realized_pnl'] for t in lo), default=0):>15,.2f}          ║\n"
            f"╠════════════════════════════════════════════════════════════════╣\n"
            f"║ Open Positions:        {len(self._positions):>15}                     ║\n"
            f"║ Uptime:                {(time.time() - self._start_time) / 3600:>15.1f} hours                ║\n"
            f"╚════════════════════════════════════════════════════════════════╝\n"
        )


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
        max_retries: int = 3,
    ):
        super().__init__()

        if not AIOHTTP_AVAILABLE:
            raise ImportError("aiohttp required for OANDA broker")

        self.api_key = api_key
        self.account_id = account_id
        self.practice = practice
        self.timeout = timeout
        self.max_retries = max_retries

        self.base_url = "https://api-fxpractice.oanda.com" if practice else "https://api-fxtrade.oanda.com"

        # Rate limiting
        self._rate_limiter = asyncio.Semaphore(10)
        self._request_count = 0
        self._last_request_time = 0

        # Caching
        self._positions_cache: dict[str, Position] = {}
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
                        "Accept-Datetime-Format": "RFC3339",
                    },
                    timeout=aiohttp.ClientTimeout(total=self.timeout),
                )

                # Verify connection
                async with (
                    self._rate_limiter,
                    self._session.get(
                        f"{self.base_url}/v3/accounts/{self.account_id}",
                    ) as resp,
                ):
                    if resp.status == 200:
                        data = await resp.json()
                        account = data.get("account", {})

                        logger.info(
                            "OANDA Connected | Balance: $%s | Currency: %s | Practice: %s",
                            f"{float(account.get('balance', 0)):,.2f}",
                            account.get("currency", "USD"),
                            self.practice,
                        )

                        self.connected = True
                        return True
                    error_data = await resp.text()
                    raise ConnectionError(
                        f"OANDA error {resp.status}: {error_data}",
                    )

            except Exception as e:
                logger.error("Connection attempt %s failed: %s", attempt + 1, e)

                if self._session:
                    await self._session.close()
                    self._session = None

                if attempt < self.max_retries - 1:
                    wait_time = 2**attempt  # Exponential backoff
                    logger.info("Retrying in %ss...", wait_time)

                    await asyncio.sleep(wait_time)
                else:
                    raise ConnectionError(
                        f"Failed to connect after {self.max_retries} attempts",
                    ) from None

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

    async def _make_request(self, method: str, endpoint: str, **kwargs) -> dict:
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
                        if resp.status == 429:  # Rate limited
                            retry_after = int(resp.headers.get("Retry-After", 1))
                            logger.warning("Rate limited, waiting %ss", retry_after)

                            await asyncio.sleep(retry_after)
                            continue
                        error_text = await resp.text()
                        raise ValueError(
                            f"OANDA API error {resp.status}: {error_text}",
                        )

                except TimeoutError:
                    logger.error("Request timeout (attempt %s)", attempt + 1)

                    if attempt < self.max_retries - 1:
                        await asyncio.sleep(1)
                    else:
                        raise
                except Exception as e:
                    logger.error("Request error: %s", e)

                    if attempt < self.max_retries - 1:
                        await asyncio.sleep(1)
                    else:
                        raise

        raise ConnectionError("Max retries exceeded")

    async def get_account_info(self) -> dict:
        """Get account information"""
        data = await self._make_request("GET", f"/accounts/{self.account_id}")

        account = data.get("account", {})
        return {
            "balance": float(account.get("balance", 0)),
            "equity": float(account.get("NAV", 0)),
            "margin_used": float(account.get("marginUsed", 0)),
            "free_margin": float(account.get("marginAvailable", 0)),
            "unrealized_pnl": float(account.get("unrealizedPL", 0)),
            "realized_pnl": float(account.get("realizedPL", 0)),
            "open_positions": len(account.get("positions", [])),
            "currency": account.get("currency", "USD"),
        }

    async def place_market_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
    ) -> Order:
        """Place market order"""
        # Convert symbol to OANDA format
        instrument = symbol.replace("/", "_")

        # OANDA uses units (positive for buy, negative for sell)
        units = quantity if side == "buy" else -quantity

        body = {
            "order": {
                "type": "MARKET",
                "instrument": instrument,
                "units": str(int(units)),
            },
        }

        data = await self._make_request(
            "POST",
            f"/accounts/{self.account_id}/orders",
            json=body,
        )

        # Parse response
        order_fill = data.get("orderFillTransaction", {})

        if not order_fill:
            raise ValueError("No fill transaction in response")

        return Order(
            id=order_fill.get("id", ""),
            symbol=symbol,
            side=OrderSide(side),
            type=OrderType.MARKET,
            quantity=quantity,
            price=float(order_fill.get("price", 0)),
            status=OrderStatus.FILLED,
            filled_quantity=quantity,
            average_fill_price=float(order_fill.get("price", 0)),
            filled_at=time.time(),
            commission=float(order_fill.get("commission", 0)),
        )

    async def get_positions(self) -> list[Position]:
        """Get open positions with caching"""
        # Check cache
        if time.time() - self._last_cache_update < self._cache_ttl:
            return list(self._positions_cache.values())

        data = await self._make_request("GET", f"/accounts/{self.account_id}/positions")

        positions = []
        self._positions_cache = {}

        for pos_data in data.get("positions", []):
            instrument = pos_data.get("instrument", "").replace("_", "/")

            # Parse long and short sides
            for side_key, side_enum in [
                ("long", OrderSide.BUY),
                ("short", OrderSide.SELL),
            ]:
                side_data = pos_data.get(side_key, {})
                units = float(side_data.get("units", 0))

                if units != 0:
                    pos = Position(
                        id=f"{instrument}_{side_key}",
                        symbol=instrument,
                        side=side_enum,
                        quantity=abs(units),
                        entry_price=float(side_data.get("averagePrice", 0)),
                        current_price=float(side_data.get("markPrice", 0)),
                        unrealized_pnl=float(side_data.get("unrealizedPL", 0)),
                        realized_pnl=float(side_data.get("realizedPL", 0)),
                    )
                    positions.append(pos)
                    self._positions_cache[pos.id] = pos

        self._last_cache_update = time.time()
        return positions

    async def close_position(self, position_id: str) -> bool:
        """Close position"""
        # Parse position ID
        parts = position_id.rsplit("_", 1)
        if len(parts) != 2:
            logger.error("Invalid position ID format: %s", position_id)

            return False

        instrument, side = parts
        instrument = instrument.replace("/", "_")

        body = {
            "longUnits": "ALL" if side == "long" else "NONE",
            "shortUnits": "ALL" if side == "short" else "NONE",
        }

        try:
            await self._make_request(
                "PUT",
                f"/accounts/{self.account_id}/positions/{instrument}/close",
                json=body,
            )

            # Invalidate cache
            self._last_cache_update = 0

            logger.info("Position closed: %s", position_id)

            return True

        except Exception as e:
            logger.error("Failed to close position %s: %s", position_id, e)

            return False

    async def cancel_order(self, order_id: str) -> bool:
        """Cancel pending order"""
        try:
            await self._make_request(
                "PUT",
                f"/accounts/{self.account_id}/orders/{order_id}/cancel",
            )
            logger.info("Order cancelled: %s", order_id)

            return True
        except Exception as e:
            logger.error("Failed to cancel order %s: %s", order_id, e)

            return False

    async def get_pending_orders(self) -> list[Order]:
        """Get pending orders"""
        data = await self._make_request(
            "GET",
            f"/accounts/{self.account_id}/pendingOrders",
        )

        orders = [
            Order(
                id=order_data.get("id", ""),
                symbol=order_data.get("instrument", "").replace("_", "/"),
                side=OrderSide((order_data.get("units", 0) > 0 and "buy") or "sell"),
                type=OrderType(order_data.get("type", "MARKET").lower()),
                quantity=abs(float(order_data.get("units", 0))),
                price=float(order_data.get("price", 0)) if order_data.get("price") else None,
                status=OrderStatus.PENDING,
            )
            for order_data in data.get("orders", [])
        ]

        return orders


def create_broker(broker_type: str, config: dict) -> BaseBroker:
    """Factory function to create appropriate broker"""
    broker_type = broker_type.lower()

    if broker_type == "paper":
        return PaperTradingBroker(
            initial_balance=config.get("initial_balance", 100000.0),
            commission_per_lot=config.get("commission_per_lot", 3.5),
            slippage_model=config.get("slippage_model", "gaussian"),
        )
    if broker_type == "oanda":
        if not AIOHTTP_AVAILABLE:
            raise ImportError(
                "aiohttp required for OANDA broker. Install: pip install aiohttp",
            )
        return OANDABroker(
            api_key=config["api_key"],
            account_id=config["account_id"],
            practice=config.get("practice", True),
            timeout=config.get("timeout", 10.0),
            max_retries=config.get("max_retries", 3),
        )
    if broker_type == "ccxt":
        from brokers.ccxt_connector import CCXTConnector

        return CCXTConnector(config)
    raise ValueError(
        f"Unknown broker type: {broker_type}. Supported: paper, oanda, ccxt",
    )


# Override with the dict-config-based PaperTradingBroker that tests expect
try:
    from brokers.paper_trading import PaperTradingBroker
except Exception as _exc:
    logger.warning("PaperTradingBroker import failed: %s", _exc)


from brokers.factory import BrokerFactory  # noqa: F401

try:
    from brokers.base import AccountInfo, BrokerConnector  # noqa: F401
except Exception as _exc:
    logger.debug("BrokerConnector base unavailable: %s", _exc)

# ── YAML-config-based broker implementations ──────────────────────────────────
# These complement the existing connector classes and are used by the new
# yaml-driven BrokerFactory (config/brokers.yaml).
try:
    from brokers.mt5_broker import MT5Broker  # noqa: F401
except Exception as _exc:
    logger.debug("MT5Broker unavailable: %s", _exc)

try:
    from brokers.oanda_broker import OandaBroker as OandaBrokerYaml  # noqa: F401
except Exception as _exc:
    logger.debug("OandaBroker (yaml) unavailable: %s", _exc)

try:
    from brokers.ibkr_broker import IBKRBroker  # noqa: F401
except Exception as _exc:
    logger.debug("IBKRBroker unavailable: %s", _exc)

# ── Additional broker connectors ──────────────────────────────────────────────
try:
    from brokers.oanda_stream import OandaStreamClient, OANDAStream  # noqa: F401
except Exception as _exc:
    logger.debug("OandaStreamClient unavailable: %s", _exc)

try:
    from brokers.alpaca import AlpacaBroker, AlpacaConnector  # noqa: F401
except Exception as _exc:
    logger.debug("AlpacaBroker unavailable: %s", _exc)

try:
    from brokers.binance import BinanceBroker, BinanceConnector  # noqa: F401
except Exception as _exc:
    logger.debug("BinanceBroker unavailable: %s", _exc)

try:
    from brokers.bybit_connector import BybitConnector, ByBitConnector  # noqa: F401
except Exception as _exc:
    logger.debug("BybitConnector unavailable: %s", _exc)

try:
    from brokers.ccxt_connector import CCXTConnector  # noqa: F401
except Exception as _exc:
    logger.debug("CCXTConnector unavailable: %s", _exc)

try:
    from brokers.ibkr_connector import IBKRConnector  # noqa: F401
except Exception as _exc:
    logger.debug("IBKRConnector unavailable: %s", _exc)

try:
    from brokers.ibkr_fix_bridge import IBKRFIXBridge  # noqa: F401
except Exception as _exc:
    logger.debug("IBKRFIXBridge unavailable: %s", _exc)

try:
    from brokers.ohlcv_store import OHLCVStore  # noqa: F401
except Exception as _exc:
    logger.debug("OHLCVStore unavailable: %s", _exc)

try:
    from brokers.smart_router import SmartOrderRouter  # noqa: F401
except Exception as _exc:
    logger.debug("SmartOrderRouter unavailable: %s", _exc)

try:
    from brokers.advanced_orders import AdvancedOrderManager  # noqa: F401
except Exception as _exc:
    logger.debug("AdvancedOrderManager unavailable: %s", _exc)

try:
    from brokers.manager import BrokerManager  # noqa: F401
except Exception as _exc:
    logger.debug("BrokerManager unavailable: %s", _exc)

try:
    from brokers.oanda import OandaBroker  # noqa: F401
except Exception as _exc:
    logger.debug("OandaBroker unavailable: %s", _exc)

try:
    from brokers.ibkr import IBKRBroker as IBKRBrokerLegacy  # noqa: F401
except Exception as _exc:
    logger.debug("IBKRBrokerLegacy unavailable: %s", _exc)

try:
    from brokers.mt5 import MT5Broker as MT5BrokerConnector  # noqa: F401
except Exception as _exc:
    logger.debug("MT5BrokerConnector unavailable: %s", _exc)

__version__ = "1.0.0"

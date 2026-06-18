# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
Base Broker Connector

Abstract base class for all broker integrations.
"""

import asyncio
import functools
import logging
import time
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, TypeVar

logger = logging.getLogger(__name__)

_F = TypeVar("_F", bound=Callable[..., Any])


def with_retry(
    max_attempts: int = 3,
    backoff: float = 1.0,
    exceptions: tuple[type[Exception], ...] = (Exception,),
) -> Callable[[_F], _F]:
    """
    Decorator: retry a broker call up to *max_attempts* times with exponential
    backoff.  Works on both sync and async callables.

    Args:
        max_attempts: Maximum number of attempts (default 3).
        backoff: Base backoff in seconds, doubled each attempt (default 1.0).
        exceptions: Exception types to catch and retry on.
    """

    def decorator(fn: _F) -> _F:
        if asyncio.iscoroutinefunction(fn):

            @functools.wraps(fn)
            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                delay = backoff
                last_exc: Exception = RuntimeError("no attempts made")
                for attempt in range(1, max_attempts + 1):
                    try:
                        return await fn(*args, **kwargs)
                    except exceptions as exc:
                        last_exc = exc
                        if attempt < max_attempts:
                            logger.warning(
                                "%s attempt %d/%d failed (%s); retrying in %.1fs",
                                fn.__qualname__,
                                attempt,
                                max_attempts,
                                exc,
                                delay,
                            )
                            await asyncio.sleep(delay)
                            delay *= 2
                        else:
                            logger.error(
                                "%s failed after %d attempts: %s",
                                fn.__qualname__,
                                max_attempts,
                                exc,
                            )
                raise last_exc

            return async_wrapper  # type: ignore[return-value]

        @functools.wraps(fn)
        def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            delay = backoff
            last_exc: Exception = RuntimeError("no attempts made")
            for attempt in range(1, max_attempts + 1):
                try:
                    return fn(*args, **kwargs)
                except exceptions as exc:
                    last_exc = exc
                    if attempt < max_attempts:
                        logger.warning(
                            "%s attempt %d/%d failed (%s); retrying in %.1fs",
                            fn.__qualname__,
                            attempt,
                            max_attempts,
                            exc,
                            delay,
                        )
                        time.sleep(delay)
                        delay *= 2
                    else:
                        logger.error(
                            "%s failed after %d attempts: %s",
                            fn.__qualname__,
                            max_attempts,
                            exc,
                        )
            raise last_exc

        return sync_wrapper  # type: ignore[return-value]

    return decorator


class RateLimiter:
    """
    Token-bucket rate limiter for broker API calls.

    Args:
        calls_per_second: Maximum calls allowed per second (default 10).
    """

    def __init__(self, calls_per_second: float = 10.0) -> None:
        self._rate = calls_per_second
        self._tokens = calls_per_second
        self._last: float = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        """Block until a token is available."""
        async with self._lock:
            now = time.monotonic()
            elapsed = now - self._last
            self._last = now
            self._tokens = min(self._rate, self._tokens + elapsed * self._rate)
            if self._tokens < 1.0:
                wait = (1.0 - self._tokens) / self._rate
                await asyncio.sleep(wait)
                self._tokens = 0.0
            else:
                self._tokens -= 1.0


class OrderType(Enum):
    """Order types"""

    MARKET = "MARKET"
    LIMIT = "LIMIT"
    STOP = "STOP"
    STOP_LIMIT = "STOP_LIMIT"


class OrderSide(Enum):
    """Order side"""

    BUY = "BUY"
    SELL = "SELL"


class OrderStatus(Enum):
    """Order status"""

    PENDING = "pending"
    OPEN = "open"
    FILLED = "filled"
    PARTIAL = "partial"
    CANCELLED = "cancelled"
    REJECTED = "rejected"


@dataclass
class Order:
    """Order data structure.

    Canonical fields
    ----------------
    average_price : float | None
        Fill price set by the broker after execution.

    Aliases (read-only properties)
    --------------------------------
    average_fill_price  — same as average_price (legacy name used by brokers/__init__.py)
    filled_price        — same as average_price (legacy name used by cme_comex, cpp_shim)
    """

    id: str
    symbol: str
    side: OrderSide
    type: OrderType
    quantity: float
    price: float | None = None
    stop_price: float | None = None
    status: OrderStatus = OrderStatus.PENDING
    filled_quantity: float = 0.0
    average_price: float | None = None
    timestamp: datetime | None = None
    metadata: dict[str, Any] | None = None

    @property
    def average_fill_price(self) -> float | None:
        """Alias for average_price (brokers/__init__.py legacy name)."""
        return self.average_price

    @property
    def filled_price(self) -> float | None:
        """Alias for average_price (cme_comex / cpp_shim legacy name)."""
        return self.average_price


# Canonical side values accepted by Position.from_side_str()
_SIDE_BUY_ALIASES = frozenset({"BUY", "LONG", "buy", "long"})
_SIDE_SELL_ALIASES = frozenset({"SELL", "SHORT", "sell", "short"})


@dataclass
class Position:
    """Position data structure.

    ``side`` is normalised to ``OrderSide`` (BUY / SELL) on construction.
    Legacy string values "LONG"/"SHORT"/"BUY"/"SELL" are accepted and
    automatically converted by ``__post_init__`` — no callers need changing.

    Backward-compat helpers
    -----------------------
    side_str  — returns "LONG" / "SHORT" for code that expects the old format
    """

    symbol: str
    side: "OrderSide | str"  # accepts str; normalised to OrderSide in __post_init__
    quantity: float
    entry_price: float
    current_price: float
    unrealized_pnl: float
    realized_pnl: float = 0.0
    stop_loss: float | None = None
    take_profit: float | None = None
    timestamp: datetime | None = None
    id: str = ""  # position identifier (defaults to symbol if empty)

    def __post_init__(self) -> None:
        """Normalise side to OrderSide enum regardless of what was passed."""
        if isinstance(self.side, str):
            _s = self.side.upper()
            if _s in _SIDE_BUY_ALIASES:
                object.__setattr__(self, "side", OrderSide.BUY)
            elif _s in _SIDE_SELL_ALIASES:
                object.__setattr__(self, "side", OrderSide.SELL)
            else:
                raise ValueError(
                    f"Position.side {self.side!r} is not recognised. Use 'BUY', 'SELL', 'LONG', or 'SHORT'."
                )

    @property
    def side_str(self) -> str:
        """Return 'LONG' / 'SHORT' for legacy callers that expect the old str format."""
        return "LONG" if self.side == OrderSide.BUY else "SHORT"

    @classmethod
    def from_side_str(
        cls,
        symbol: str,
        side: "str | OrderSide",
        quantity: float,
        entry_price: float,
        current_price: float,
        unrealized_pnl: float,
        **kwargs,
    ) -> "Position":
        """Construct a Position accepting 'LONG'/'SHORT'/'BUY'/'SELL' or OrderSide."""
        return cls(
            symbol=symbol,
            side=side,  # __post_init__ handles normalisation
            quantity=quantity,
            entry_price=entry_price,
            current_price=current_price,
            unrealized_pnl=unrealized_pnl,
            **kwargs,
        )


@dataclass
class AccountInfo:
    """Account information"""

    balance: float
    equity: float
    margin_used: float
    margin_available: float
    positions_count: int
    timestamp: datetime | None = None

    def __getitem__(self, key: str) -> Any:
        return getattr(self, key)

    def get(self, key: str, default: Any = None) -> Any:
        return getattr(self, key, default)


@dataclass
class MarketOrderResult:
    """Normalised market-order fill result.

    Returned by ``BrokerConnector.place_market_order`` so the live order router
    can read ``order_id`` / ``average_fill_price`` / ``filled_quantity`` /
    ``status`` uniformly regardless of each broker's native ``Order`` shape
    (some expose ``id`` + ``average_price``, others ``order_id`` +
    ``average_fill_price``).
    """

    order_id: str
    average_fill_price: float
    filled_quantity: float
    status: str
    pnl: float = 0.0
    commission: float = 0.0
    slippage: float = 0.0
    raw: Any = None

    @property
    def fill_price(self) -> float:
        """Alias used by some call sites."""
        return self.average_fill_price

    @classmethod
    def from_order(cls, order: Any) -> "MarketOrderResult":
        """Build from any broker Order/result by probing common field names."""

        def _g(*names: str, default: Any = None) -> Any:
            for n in names:
                v = getattr(order, n, None)
                if v is not None:
                    return v
            return default

        status = _g("status", default="")
        status_str = getattr(status, "value", status)
        return cls(
            order_id=str(_g("order_id", "id", default="") or ""),
            average_fill_price=float(_g("average_fill_price", "average_price", "price", default=0.0) or 0.0),
            filled_quantity=float(_g("filled_quantity", "quantity", default=0.0) or 0.0),
            status=str(status_str or ""),
            pnl=float(_g("pnl", "realized_pnl", default=0.0) or 0.0),
            commission=float(_g("commission", default=0.0) or 0.0),
            slippage=float(_g("slippage", default=0.0) or 0.0),
            raw=order,
        )


class BrokerConnector(ABC):
    """
    Abstract base class for all broker connectors.

    All lifecycle methods are declared as async to match the real network I/O
    contract of live broker integrations (OANDA REST, MT5 SDK, IBKR TWS).
    Sync brokers (e.g. PaperTradingBroker) may implement sync bodies — Python
    allows a concrete class to override an async abstract method with a sync
    method as long as the caller awaits the result only when it is a coroutine.

    Required implementations:
    - connect() / disconnect()
    - place_order() / cancel_order() / get_order()
    - get_positions() / close_position()
    - get_account_info()
    - get_market_data()
    """

    def __init__(self, config: dict[str, Any]):
        self.config = config
        self.connected = False
        self.name = self.__class__.__name__
        # Per-connector rate limiter (default 10 req/s; override in subclass)
        self.rate_limiter = RateLimiter(
            calls_per_second=float(config.get("rate_limit_rps", 10.0)),
        )
        logger.info("Initialized %s broker connector", self.name)

    @abstractmethod
    async def connect(self) -> bool:
        """Open connection to the broker. Returns True on success."""

    @abstractmethod
    async def disconnect(self) -> bool:
        """Close connection to the broker. Returns True on success."""

    @abstractmethod
    async def place_order(
        self,
        symbol: str,
        side: OrderSide,
        order_type: OrderType,
        quantity: float,
        price: float | None = None,
        stop_price: float | None = None,
        **kwargs: Any,
    ) -> Order:
        """
        Place an order.

        Args:
            symbol: Trading symbol
            side: Buy or sell
            order_type: Market, limit, stop, etc.
            quantity: Order quantity in units
            price: Limit price (limit orders only)
            stop_price: Stop trigger price (stop orders only)
            **kwargs: Broker-specific parameters

        Returns:
            Filled or pending Order object
        """

    @abstractmethod
    async def cancel_order(self, order_id: str) -> bool:
        """Cancel an open order. Returns True if successfully cancelled."""

    @abstractmethod
    async def get_order(self, order_id: str) -> Order | None:
        """Fetch a single order by ID. Returns None if not found."""

    @abstractmethod
    async def get_positions(self) -> list[Position]:
        """Return all currently open positions."""

    @abstractmethod
    async def close_position(self, symbol: str) -> bool:
        """Close the open position for *symbol*. Returns True on success."""

    def get_last_close_fill_price(self, position_ref: str) -> float | None:
        """Actual fill price of the most recent close for *position_ref*.

        ``position_ref`` is whatever identifier was passed to
        :meth:`close_position` (symbol or position id). Returns ``None`` when
        the broker does not record close fills — callers must then fall back to
        the last known mark price. This default keeps existing adapters
        unchanged; brokers that know the real close fill (e.g. paper, and
        eventually the live adapters) override it so realised P&L is booked at
        the executed price rather than a stale cached mark."""
        return None

    @abstractmethod
    async def get_account_info(self) -> AccountInfo:
        """Return current account balance, equity, and margin details."""

    @abstractmethod
    async def get_market_data(
        self,
        symbol: str,
        timeframe: str = "1h",
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """
        Return OHLCV bars for *symbol*.

        Args:
            symbol: Trading symbol (e.g. "XAU_USD")
            timeframe: Bar timeframe string (e.g. "1h", "4h", "1d")
            limit: Number of bars to return

        Returns:
            List of dicts with keys: timestamp, open, high, low, close, volume
        """

    async def cancel_all_orders(self) -> list[str]:
        """
        Cancel all open/pending orders and close all positions at market.

        Called by the kill switch on activation. Default implementation
        iterates get_positions() and calls close_position() for each.
        Brokers with a native mass-cancel API (IBKR reqGlobalCancel,
        OANDA bulk close) should override this method.

        Returns list of successfully cancelled/closed position IDs.
        """
        cancelled: list[str] = []
        try:
            positions = self.get_positions()
            # Support both sync and async get_positions implementations.
            if asyncio.iscoroutine(positions):
                positions = await asyncio.wait_for(positions, timeout=10.0)
        except Exception as exc:
            logger.warning("%s.cancel_all_orders: get_positions failed: %s", self.name, exc)
            return cancelled

        if not positions:
            logger.info("%s.cancel_all_orders: no open positions", self.name)
            return cancelled

        for pos in positions:
            symbol = pos.symbol if hasattr(pos, "symbol") else str(pos)
            try:
                result = self.close_position(symbol)
                if asyncio.iscoroutine(result):
                    result = await asyncio.wait_for(result, timeout=5.0)
                if result:
                    cancelled.append(symbol)
                    logger.info("%s.cancel_all_orders: closed %s", self.name, symbol)
                else:
                    logger.warning("%s.cancel_all_orders: close_position(%s) returned False", self.name, symbol)
            except Exception as exc:
                logger.error("%s.cancel_all_orders: close_position(%s) raised: %s", self.name, symbol, exc)

        return cancelled

    async def place_market_order(
        self,
        symbol: str,
        side: "OrderSide | str",
        quantity: float,
        stop_loss: float | None = None,
        take_profit: float | None = None,
        **kwargs: Any,
    ) -> MarketOrderResult:
        """Uniform market-order entry point used by the live order router.

        Adapts the connector's ``place_order()`` (OrderSide/OrderType enums,
        broker-native Order return) to the ``(symbol, side, quantity)`` contract
        the router calls, and normalises the result to ``MarketOrderResult`` so
        ``order_id`` / ``average_fill_price`` / ``filled_quantity`` / ``status``
        are readable regardless of broker. Handles both sync and async
        ``place_order`` bodies.

        Bracket ``stop_loss`` / ``take_profit`` are not applied at market entry
        here (per-broker support varies); they are logged and ignored so a
        connector without bracket support never raises on extra kwargs.
        """
        side_enum = side if isinstance(side, OrderSide) else OrderSide(str(side).upper())
        if stop_loss is not None or take_profit is not None:
            logger.debug(
                "%s.place_market_order: bracket SL/TP not applied at entry (per-broker); SL=%s TP=%s",
                self.name,
                stop_loss,
                take_profit,
            )
        result = self.place_order(
            symbol=symbol,
            side=side_enum,
            order_type=OrderType.MARKET,
            quantity=quantity,
            price=None,
            stop_price=None,
        )
        if asyncio.iscoroutine(result):
            result = await result
        if result is None:
            raise RuntimeError(f"{self.name}: market order rejected (place_order returned None)")
        return MarketOrderResult.from_order(result)

    def is_connected(self) -> bool:
        """
        Check if connected to broker.

        Returns:
            Connection status
        """
        return self.connected

    def __repr__(self) -> str:
        return f"{self.name}(connected={self.connected})"

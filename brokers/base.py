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
    """Order data structure"""

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
        """Alias for average_price."""
        return self.average_price


@dataclass
class Position:
    """Position data structure"""

    symbol: str
    side: str  # "LONG" or "SHORT"
    quantity: float
    entry_price: float
    current_price: float
    unrealized_pnl: float
    realized_pnl: float = 0.0
    timestamp: datetime | None = None
    id: str = ""  # position identifier (defaults to symbol if empty)


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

    def is_connected(self) -> bool:
        """
        Check if connected to broker.

        Returns:
            Connection status
        """
        return self.connected

    def __repr__(self) -> str:
        return f"{self.name}(connected={self.connected})"

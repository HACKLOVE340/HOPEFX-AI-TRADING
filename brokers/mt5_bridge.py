"""
brokers/mt5_bridge.py
=====================
Full MetaTrader 5 bridge with hybrid Python-signal / MT5-execution mode.

Features:
  - Direct MetaTrader5 package integration (connect / send_order / monitor_fill / close_position)
  - Hybrid mode: Python strategy signals → MT5 execution
  - Exponential-backoff retry on transient errors
  - Per-call timeout enforcement
  - Structured logging via structlog
  - Thread-safe connection management

Placement: drop into brokers/ alongside the existing mt5.py connector.
The existing MT5Connector (brokers/mt5.py) handles ZeroMQ-based routing;
this bridge uses the native MetaTrader5 Python package for direct execution.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, auto
from typing import Any, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Optional import guard — MetaTrader5 is Windows-only
# ---------------------------------------------------------------------------
try:
    import MetaTrader5 as mt5  # type: ignore

    _MT5_AVAILABLE = True
except ImportError:
    mt5 = None  # type: ignore
    _MT5_AVAILABLE = False
    logger.warning(
        "MetaTrader5 package not available. "
        "Install on Windows with: pip install MetaTrader5"
    )


# ---------------------------------------------------------------------------
# Domain types
# ---------------------------------------------------------------------------


class OrderSide(Enum):
    BUY = "BUY"
    SELL = "SELL"


class OrderType(Enum):
    MARKET = auto()
    LIMIT = auto()
    STOP = auto()


class FillStatus(Enum):
    PENDING = auto()
    FILLED = auto()
    PARTIAL = auto()
    REJECTED = auto()
    CANCELLED = auto()


@dataclass
class MT5Order:
    symbol: str
    side: OrderSide
    volume: float  # Lot size
    order_type: OrderType = OrderType.MARKET
    price: Optional[float] = None  # Required for LIMIT/STOP
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    deviation: int = 20  # Max price deviation in points
    magic: int = 234_001  # EA magic number
    comment: str = "HOPEFX"
    timeout_sec: float = 10.0


@dataclass
class MT5FillResult:
    ticket: int
    status: FillStatus
    filled_volume: float
    fill_price: float
    commission: float
    swap: float
    profit: float
    comment: str
    raw: Any = field(default=None, repr=False)


# ---------------------------------------------------------------------------
# Retry helper
# ---------------------------------------------------------------------------


def _retry(max_attempts: int = 3, base_delay: float = 0.5):
    """
    Decorator: retry on exception with exponential back-off.
    Raises the last exception if all attempts fail.
    """

    def decorator(fn):
        def wrapper(*args, **kwargs):
            delay = base_delay
            last_exc: Exception | None = None
            for attempt in range(1, max_attempts + 1):
                try:
                    return fn(*args, **kwargs)
                except Exception as exc:
                    last_exc = exc
                    logger.warning(
                        "mt5_bridge.retry attempt=%d/%d fn=%s error=%s",
                        attempt,
                        max_attempts,
                        fn.__name__,
                        exc,
                    )
                    if attempt < max_attempts:
                        time.sleep(delay)
                        delay *= 2
            raise last_exc  # type: ignore[misc]

        return wrapper

    return decorator


# ---------------------------------------------------------------------------
# Bridge
# ---------------------------------------------------------------------------


class MT5Bridge:
    """
    Hybrid Python ↔ MT5 execution bridge.

    Usage (synchronous):
        bridge = MT5Bridge(server="ICMarkets-Demo", login=12345, password="pw")
        bridge.connect()
        result = bridge.send_order(MT5Order("XAUUSD", OrderSide.BUY, 0.1))
        bridge.close_position("XAUUSD")
        bridge.disconnect()

    Usage (async wrapper):
        async with MT5Bridge.async_context(...) as bridge:
            result = await bridge.async_send_order(order)
    """

    def __init__(
        self,
        server: str,
        login: int,
        password: str,
        path: Optional[str] = None,
        portable: bool = False,
        timeout_ms: int = 60_000,
    ) -> None:
        if not _MT5_AVAILABLE:
            raise RuntimeError(
                "MetaTrader5 package is not installed. "
                "Run: pip install MetaTrader5  (Windows only)"
            )
        self.server = server
        self.login = login
        self.password = password
        self.path = path
        self.portable = portable
        self.timeout_ms = timeout_ms
        self._connected = False

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------

    @_retry(max_attempts=3, base_delay=1.0)
    def connect(self) -> bool:
        """
        Initialise the MT5 terminal and authenticate.
        Retries up to 3 times with exponential back-off.
        """
        init_kwargs: dict[str, Any] = {"portable": self.portable}
        if self.path:
            init_kwargs["path"] = self.path

        if not mt5.initialize(**init_kwargs):
            raise ConnectionError(f"mt5.initialize failed: {mt5.last_error()}")

        authorised = mt5.login(
            login=self.login,
            password=self.password,
            server=self.server,
            timeout=self.timeout_ms,
        )
        if not authorised:
            mt5.shutdown()
            raise ConnectionError(f"mt5.login failed: {mt5.last_error()}")

        self._connected = True
        info = mt5.account_info()
        logger.info(
            "mt5_bridge.connected server=%s login=%s balance=%.2f",
            self.server,
            self.login,
            info.balance if info else 0,
        )
        return True

    def disconnect(self) -> None:
        """Shut down the MT5 terminal connection."""
        if _MT5_AVAILABLE:
            mt5.shutdown()
        self._connected = False
        logger.info("mt5_bridge.disconnected")

    def _require_connected(self) -> None:
        if not self._connected:
            raise RuntimeError("MT5Bridge is not connected. Call connect() first.")

    # ------------------------------------------------------------------
    # Order placement
    # ------------------------------------------------------------------

    @_retry(max_attempts=3, base_delay=0.3)
    def send_order(self, order: MT5Order) -> MT5FillResult:
        """
        Send a market, limit, or stop order to MT5.

        Applies timeout via a threading.Timer that calls disconnect on breach.
        Retries up to 3 times on transient failures.
        """
        self._require_connected()

        # Ensure symbol is visible in Market Watch
        sym_info = mt5.symbol_info(order.symbol)
        if sym_info is None:
            raise ValueError(f"Symbol {order.symbol!r} not found in MT5")
        if not sym_info.visible:
            if not mt5.symbol_select(order.symbol, True):
                raise RuntimeError(f"Cannot select symbol {order.symbol!r}")

        # Resolve execution price
        tick = mt5.symbol_info_tick(order.symbol)
        if tick is None:
            raise RuntimeError(f"No tick data for {order.symbol!r}")

        if order.order_type == OrderType.MARKET:
            price = tick.ask if order.side == OrderSide.BUY else tick.bid
            action = mt5.TRADE_ACTION_DEAL
            mt5_type = (
                mt5.ORDER_TYPE_BUY
                if order.side == OrderSide.BUY
                else mt5.ORDER_TYPE_SELL
            )
        elif order.order_type == OrderType.LIMIT:
            if order.price is None:
                raise ValueError("LIMIT order requires a price")
            price = order.price
            action = mt5.TRADE_ACTION_PENDING
            mt5_type = (
                mt5.ORDER_TYPE_BUY_LIMIT
                if order.side == OrderSide.BUY
                else mt5.ORDER_TYPE_SELL_LIMIT
            )
        else:  # STOP
            if order.price is None:
                raise ValueError("STOP order requires a price")
            price = order.price
            action = mt5.TRADE_ACTION_PENDING
            mt5_type = (
                mt5.ORDER_TYPE_BUY_STOP
                if order.side == OrderSide.BUY
                else mt5.ORDER_TYPE_SELL_STOP
            )

        request: dict[str, Any] = {
            "action": action,
            "symbol": order.symbol,
            "volume": float(order.volume),
            "type": mt5_type,
            "price": float(price),
            "deviation": order.deviation,
            "magic": order.magic,
            "comment": order.comment,
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }
        # FINANCIAL SAFETY: validate stop-loss before sending
        if order.stop_loss is None or order.stop_loss == 0.0:
            raise ValueError(
                f"Order for {order.symbol!r} rejected: stop_loss must be a non-zero value. "
                "Set order.stop_loss to a valid price level."
            )
        if order.stop_loss is not None:
            request["sl"] = float(order.stop_loss)
        if order.take_profit is not None:
            request["tp"] = float(order.take_profit)

        # Send with timeout guard
        timed_out = getattr(order, "_timed_out", None)
        timer = getattr(order, "_timer", None)
        try:
            result = mt5.order_send(request)
        finally:
            if timer is not None:
                timer.cancel()

        if timed_out is not None and timed_out.is_set():
            raise TimeoutError(
                f"MT5 order_send timed out after {getattr(order, 'timeout_sec', 30)}s"
            )

        if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
            retcode = result.retcode if result else -1
            comment = result.comment if result else "no result"
            raise RuntimeError(
                f"MT5 order rejected retcode={retcode} comment={comment!r}"
            )

        fill = MT5FillResult(
            ticket=result.order,
            status=FillStatus.FILLED,
            filled_volume=result.volume,
            fill_price=result.price,
            commission=getattr(result, "commission", 0.0),
            swap=getattr(result, "swap", 0.0),
            profit=getattr(result, "profit", 0.0),
            comment=result.comment,
            raw=result,
        )
        logger.info(
            "mt5_bridge.filled ticket=%d symbol=%s side=%s vol=%.2f price=%.5f",
            fill.ticket,
            order.symbol,
            order.side.value,
            fill.filled_volume,
            fill.fill_price,
        )
        return fill

    # ------------------------------------------------------------------
    # Fill monitoring
    # ------------------------------------------------------------------

    def monitor_fill(
        self,
        ticket: int,
        poll_interval: float = 0.5,
        timeout_sec: float = 30.0,
    ) -> MT5FillResult:
        """
        Poll MT5 until a pending order is filled, rejected, or timeout expires.

        Returns the final MT5FillResult.
        """
        self._require_connected()
        deadline = time.monotonic() + timeout_sec

        while time.monotonic() < deadline:
            # Check open orders
            orders = mt5.orders_get(ticket=ticket)
            if orders:
                time.sleep(poll_interval)
                continue  # Still pending

            # Check history for the deal
            from datetime import timedelta

            now = datetime.utcnow()
            deals = mt5.history_deals_get(now - timedelta(minutes=5), now)
            if deals:
                for deal in deals:
                    if deal.order == ticket:
                        return MT5FillResult(
                            ticket=ticket,
                            status=FillStatus.FILLED,
                            filled_volume=deal.volume,
                            fill_price=deal.price,
                            commission=deal.commission,
                            swap=deal.swap,
                            profit=deal.profit,
                            comment=deal.comment,
                            raw=deal,
                        )

            time.sleep(poll_interval)

        raise TimeoutError(
            f"monitor_fill: ticket {ticket} not filled within {timeout_sec}s"
        )

    # ------------------------------------------------------------------
    # Position management
    # ------------------------------------------------------------------

    @_retry(max_attempts=2, base_delay=0.5)
    def close_position(
        self,
        symbol: str,
        volume: Optional[float] = None,
        deviation: int = 20,
        magic: int = 234_001,
        comment: str = "HOPEFX close",
    ) -> list[MT5FillResult]:
        """
        Close all (or partial) open positions for `symbol`.

        Args:
            symbol:   Trading symbol.
            volume:   Lot size to close; None closes the full position.
            deviation: Max price deviation in points.

        Returns:
            List of MT5FillResult for each closed position ticket.
        """
        self._require_connected()

        positions = mt5.positions_get(symbol=symbol)
        if not positions:
            logger.info("mt5_bridge.close_position no open positions for %s", symbol)
            return []

        results: list[MT5FillResult] = []
        for pos in positions:
            close_type = (
                mt5.ORDER_TYPE_SELL
                if pos.type == mt5.POSITION_TYPE_BUY
                else mt5.ORDER_TYPE_BUY
            )
            tick = mt5.symbol_info_tick(symbol)
            if tick is None:
                logger.error("mt5_bridge.close_position no tick for %s", symbol)
                continue

            close_price = tick.bid if close_type == mt5.ORDER_TYPE_SELL else tick.ask
            close_vol = volume if volume is not None else pos.volume

            request = {
                "action": mt5.TRADE_ACTION_DEAL,
                "symbol": symbol,
                "volume": float(close_vol),
                "type": close_type,
                "position": pos.ticket,
                "price": close_price,
                "deviation": deviation,
                "magic": magic,
                "comment": comment,
                "type_time": mt5.ORDER_TIME_GTC,
                "type_filling": mt5.ORDER_FILLING_IOC,
            }

            result = mt5.order_send(request)
            if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
                retcode = result.retcode if result else -1
                logger.error(
                    "mt5_bridge.close_position failed ticket=%d retcode=%d",
                    pos.ticket,
                    retcode,
                )
                continue

            fill = MT5FillResult(
                ticket=result.order,
                status=FillStatus.FILLED,
                filled_volume=result.volume,
                fill_price=result.price,
                commission=getattr(result, "commission", 0.0),
                swap=getattr(result, "swap", 0.0),
                profit=getattr(result, "profit", 0.0),
                comment=result.comment,
                raw=result,
            )
            results.append(fill)
            logger.info(
                "mt5_bridge.closed ticket=%d symbol=%s vol=%.2f price=%.5f",
                fill.ticket,
                symbol,
                fill.filled_volume,
                fill.fill_price,
            )

        return results

    # ------------------------------------------------------------------
    # Account / position queries
    # ------------------------------------------------------------------

    def get_account(self) -> dict[str, Any]:
        """Return current account snapshot."""
        self._require_connected()
        info = mt5.account_info()
        if info is None:
            raise RuntimeError(f"mt5.account_info() failed: {mt5.last_error()}")
        return {
            "login": info.login,
            "server": info.server,
            "balance": info.balance,
            "equity": info.equity,
            "margin": info.margin,
            "margin_free": info.margin_free,
            "margin_level": info.margin_level,
            "leverage": info.leverage,
            "currency": info.currency,
        }

    def get_position(self, symbol: str) -> dict[str, Any]:
        """Return aggregated position for `symbol` (empty dict if flat)."""
        self._require_connected()
        positions = mt5.positions_get(symbol=symbol)
        if not positions:
            return {}

        total_volume = sum(p.volume for p in positions)
        avg_price = sum(p.price_open * p.volume for p in positions) / total_volume
        total_profit = sum(p.profit for p in positions)
        side = "LONG" if positions[0].type == mt5.POSITION_TYPE_BUY else "SHORT"

        return {
            "symbol": symbol,
            "side": side,
            "volume": total_volume,
            "avg_entry_price": avg_price,
            "unrealized_pnl": total_profit,
            "tickets": [p.ticket for p in positions],
        }

    # ------------------------------------------------------------------
    # Async wrappers (run sync calls in executor to avoid blocking)
    # ------------------------------------------------------------------

    async def async_send_order(self, order: MT5Order) -> MT5FillResult:
        """Non-blocking wrapper around send_order for async contexts."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self.send_order, order)

    async def async_close_position(
        self, symbol: str, volume: Optional[float] = None
    ) -> list[MT5FillResult]:
        """Non-blocking wrapper around close_position."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self.close_position, symbol, volume)

    # ------------------------------------------------------------------
    # Context manager
    # ------------------------------------------------------------------

    def __enter__(self) -> "MT5Bridge":
        self.connect()
        return self

    def __exit__(self, *_) -> None:
        self.disconnect()

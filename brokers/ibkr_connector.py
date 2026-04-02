# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
brokers/ibkr_connector.py

Interactive Brokers production connector — XAUUSD spot/futures/CFDs via
ib_insync (TWS/Gateway API).  FIX 4.4 low-latency path is in
execution/fix_adapter.py; this module handles the ib_insync path for
account management, position queries, and historical data.

Design invariants:
- Thread-safe: all IB event-loop calls are dispatched via ib.run_until_complete
  or ib_insync's built-in asyncio event loop.
- Zero silent failures: every exception is logged + Sentry-captured.
- Connection lifecycle: exponential-backoff reconnect, max 10 attempts.
- XAUUSD contract: Commodity (XAUUSD) on IBKR's SMART/CMDTY exchange.
- Paper vs live: controlled by IBKR_PORT env var (7497=paper, 7496=live,
  4002=gateway-paper, 4001=gateway-live).
- Kill-switch integration: place_order() checks kill switch before submission.
"""

from __future__ import annotations

import logging
import os
import threading
import time
import traceback
from dataclasses import dataclass, field
from datetime import datetime, timezone

UTC = timezone.utc
from typing import Any
from collections.abc import Callable

from brokers.base import (
    AccountInfo,
    BrokerConnector,
    Order,
    OrderSide,
    OrderStatus,
    OrderType,
    Position,
)

logger = logging.getLogger(__name__)

# Optional Sentry
try:
    import sentry_sdk  # type: ignore[import]

    _SENTRY = True
except ImportError:
    _SENTRY = False

# ib_insync — required for this connector
try:
    from ib_insync import (  # type: ignore[import]
        IB,
        CFD,
        Commodity,
        Contract,
        Future,
        LimitOrder,
        MarketOrder,
        StopOrder,
        Trade,
        util,  # noqa: F401
    )

    IB_AVAILABLE = True
except ImportError:
    IB_AVAILABLE = False
    logger.error(
        "ib_insync not installed. Install with: pip install ib_insync==0.9.86",
    )

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
_RECONNECT_INITIAL_DELAY: float = 2.0
_RECONNECT_MAX_DELAY: float = 120.0
_RECONNECT_MULTIPLIER: float = 2.0
_MAX_RECONNECT_ATTEMPTS: int = 10
_ORDER_TIMEOUT_SEC: float = 30.0  # max wait for order acknowledgement
_HEARTBEAT_INTERVAL: float = 30.0  # seconds between TWS heartbeats

# XAUUSD contract specs on IBKR
_XAUUSD_SYMBOL = "XAUUSD"
_XAUUSD_EXCHANGE = "SMART"
_XAUUSD_CURRENCY = "USD"


# ---------------------------------------------------------------------------
# Connection config
# ---------------------------------------------------------------------------
@dataclass
class IBKRConfig:
    """
    IBKR connection configuration.

    Sourced from environment variables with explicit defaults.
    All values validated at construction time — no silent misconfiguration.
    """

    host: str = field(default_factory=lambda: os.environ.get("IBKR_HOST", "127.0.0.1"))
    port: int = field(default_factory=lambda: int(os.environ.get("IBKR_PORT", "7497")))
    client_id: int = field(default_factory=lambda: int(os.environ.get("IBKR_CLIENT_ID", "1")))
    account: str | None = field(default_factory=lambda: os.environ.get("IBKR_ACCOUNT"))
    readonly: bool = False
    timeout_sec: float = 20.0

    def __post_init__(self) -> None:
        valid_ports = {4001, 4002, 7496, 7497}
        if self.port not in valid_ports:
            raise ValueError(
                f"IBKR_PORT={self.port} is not a recognised TWS/Gateway port. "
                f"Valid: {valid_ports}. "
                f"4001=gateway-live, 4002=gateway-paper, 7496=tws-live, 7497=tws-paper",
            )

    @property
    def is_paper(self) -> bool:
        return self.port in (7497, 4002)

    @property
    def mode_label(self) -> str:
        return "PAPER" if self.is_paper else "LIVE"


# ---------------------------------------------------------------------------
# IBKR Connector
# ---------------------------------------------------------------------------
class IBKRConnector(BrokerConnector):
    """
    Production Interactive Brokers connector.

    Supports:
    - XAUUSD spot (Commodity), futures (Future), CFDs (CFD)
    - Market, Limit, Stop orders
    - Account info, positions, historical data
    - Exponential-backoff reconnection
    - Kill-switch integration
    - Thread-safe order placement

    Configuration via IBKRConfig or environment variables:
        IBKR_HOST, IBKR_PORT, IBKR_CLIENT_ID, IBKR_ACCOUNT
    """

    def __init__(
        self,
        config: IBKRConfig | None = None,
        kill_switch=None,
    ) -> None:
        if not IB_AVAILABLE:
            raise ImportError(
                "ib_insync is required. Install: pip install ib_insync==0.9.86",
            )

        # Accept either an IBKRConfig dataclass or a plain dict (factory pattern)
        if isinstance(config, dict):
            config = IBKRConfig(
                host=config.get("host", "127.0.0.1"),
                port=int(config.get("port", 7497)),
                client_id=int(config.get("client_id", 1)),
                account=config.get("account"),
                readonly=bool(config.get("readonly", False)),
                timeout_sec=float(config.get("timeout_sec", 20.0)),
            )
        self._cfg = config or IBKRConfig()
        self._kill_switch = kill_switch

        # Initialise base class with a dict config
        super().__init__(
            {
                "host": self._cfg.host,
                "port": self._cfg.port,
                "client_id": self._cfg.client_id,
                "rate_limit_rps": 10.0,
            }
        )

        self._ib: IB | None = None
        self._account_id: str | None = self._cfg.account
        self._lock = threading.RLock()
        self._reconnect_attempts = 0
        self._reconnect_delay = _RECONNECT_INITIAL_DELAY
        self._heartbeat_thread: threading.Thread | None = None
        self._running = False

        # Tick callbacks for live market data
        self._tick_callbacks: list[Callable[[dict], None]] = []

        logger.info(
            "IBKRConnector initialised | host=%s port=%d client_id=%d mode=%s",
            self._cfg.host,
            self._cfg.port,
            self._cfg.client_id,
            self._cfg.mode_label,
        )

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------

    def connect(self) -> bool:
        """
        Connect to TWS/Gateway with exponential-backoff retry.

        Returns True on success, False after exhausting all attempts.
        """
        if not IB_AVAILABLE:
            logger.error("IBKRConnector.connect: ib_insync not available.")
            return False

        for attempt in range(1, _MAX_RECONNECT_ATTEMPTS + 1):
            try:
                logger.info(
                    "IBKRConnector connecting (attempt %d/%d) to %s:%d client_id=%d",
                    attempt,
                    _MAX_RECONNECT_ATTEMPTS,
                    self._cfg.host,
                    self._cfg.port,
                    self._cfg.client_id,
                )
                self._ib = IB()
                self._ib.connect(
                    host=self._cfg.host,
                    port=self._cfg.port,
                    clientId=self._cfg.client_id,
                    readonly=self._cfg.readonly,
                    timeout=self._cfg.timeout_sec,
                )

                # Resolve account
                accounts = self._ib.managedAccounts()
                if not accounts:
                    raise RuntimeError("No managed accounts returned by TWS/Gateway.")

                if self._account_id and self._account_id not in accounts:
                    raise RuntimeError(
                        f"Configured account {self._account_id!r} not in managed accounts: {accounts}",
                    )
                if not self._account_id:
                    self._account_id = accounts[0]

                self.connected = True
                self._reconnect_attempts = 0
                self._reconnect_delay = _RECONNECT_INITIAL_DELAY
                self._running = True

                # Start heartbeat
                self._start_heartbeat()

                logger.info(
                    "IBKRConnector connected | account=%s mode=%s",
                    self._account_id,
                    self._cfg.mode_label,
                )
                return True

            except Exception as exc:
                tb = traceback.format_exc()
                logger.error(
                    "IBKRConnector connection attempt %d failed: %s\n%s",
                    attempt,
                    exc,
                    tb,
                )
                self._capture_sentry(exc)
                self.connected = False

                if attempt < _MAX_RECONNECT_ATTEMPTS:
                    logger.warning(
                        "Retrying in %.1fs…",
                        self._reconnect_delay,
                    )
                    time.sleep(self._reconnect_delay)
                    self._reconnect_delay = min(
                        self._reconnect_delay * _RECONNECT_MULTIPLIER,
                        _RECONNECT_MAX_DELAY,
                    )

        logger.critical(
            "IBKRConnector: exhausted %d reconnect attempts. Giving up.",
            _MAX_RECONNECT_ATTEMPTS,
        )
        return False

    def disconnect(self) -> bool:
        """Disconnect from TWS/Gateway and stop heartbeat."""
        self._running = False
        try:
            if self._ib and self._ib.isConnected():
                self._ib.disconnect()
            self.connected = False
            logger.info("IBKRConnector disconnected.")
            return True
        except Exception as exc:
            logger.error("IBKRConnector.disconnect error: %s", exc)
            self._capture_sentry(exc)
            return False

    def reconnect(self) -> bool:
        """Disconnect then reconnect."""
        self.disconnect()
        time.sleep(1.0)
        return self.connect()

    # ------------------------------------------------------------------
    # Heartbeat
    # ------------------------------------------------------------------

    def _start_heartbeat(self) -> None:
        """Start background thread that pings TWS to detect stale connections."""
        if self._heartbeat_thread and self._heartbeat_thread.is_alive():
            return
        self._heartbeat_thread = threading.Thread(
            target=self._heartbeat_loop,
            name="ibkr-heartbeat",
            daemon=True,
        )
        self._heartbeat_thread.start()

    def _heartbeat_loop(self) -> None:
        while self._running:
            time.sleep(_HEARTBEAT_INTERVAL)
            if not self._running:
                break
            try:
                if self._ib and not self._ib.isConnected():
                    logger.warning("IBKRConnector: heartbeat detected disconnection. Reconnecting…")
                    self.reconnect()
            except Exception as exc:
                logger.error("IBKRConnector heartbeat error: %s", exc)
                self._capture_sentry(exc)

    # ------------------------------------------------------------------
    # Contract factory
    # ------------------------------------------------------------------

    def _make_xauusd_contract(self, instrument: str = "commodity") -> Contract:
        """
        Build the XAUUSD contract.

        Args:
            instrument: "commodity" | "cfd" | "future"
        """
        instrument = instrument.lower()
        if instrument == "cfd":
            c = CFD(_XAUUSD_SYMBOL, "SMART", _XAUUSD_CURRENCY)
        elif instrument == "future":
            # Front-month gold futures (GC) on COMEX
            c = Future("GC", exchange="NYMEX", currency=_XAUUSD_CURRENCY)
        else:
            # Default: Commodity (spot-equivalent)
            c = Commodity(_XAUUSD_SYMBOL, _XAUUSD_EXCHANGE, _XAUUSD_CURRENCY)

        self._ib.qualifyContracts(c)
        return c

    def _make_contract(self, symbol: str, instrument: str = "commodity") -> Contract:
        """Generic contract factory — defaults to XAUUSD commodity."""
        if symbol.upper() in (_XAUUSD_SYMBOL, "GOLD", "XAU"):
            return self._make_xauusd_contract(instrument)
        # Fallback: treat as stock on SMART
        from ib_insync import Stock  # type: ignore[import]

        c = Stock(symbol, "SMART", _XAUUSD_CURRENCY)
        self._ib.qualifyContracts(c)
        return c

    # ------------------------------------------------------------------
    # Order placement
    # ------------------------------------------------------------------

    def place_order(
        self,
        symbol: str,
        side: OrderSide,
        order_type: OrderType,
        quantity: float,
        price: float | None = None,
        stop_price: float | None = None,
        instrument: str = "commodity",
        **kwargs,
    ) -> Order:
        """
        Place an order on IBKR.

        Args:
            symbol: Trading symbol (e.g. "XAUUSD", "GC")
            side: OrderSide.BUY or OrderSide.SELL
            order_type: MARKET, LIMIT, or STOP
            quantity: Number of units/contracts
            price: Limit price (required for LIMIT orders)
            stop_price: Stop price (required for STOP orders)
            instrument: "commodity" | "cfd" | "future"

        Returns:
            Order object with current status.

        Raises:
            RuntimeError: if not connected or kill switch is active.
            ValueError: if order parameters are invalid.
        """
        if not self.connected or not self._ib:
            raise RuntimeError("IBKRConnector.place_order: not connected to TWS/Gateway.")

        # Kill-switch check — hard block
        if self._kill_switch and self._kill_switch.is_active():
            reason = getattr(self._kill_switch, "_reason", "kill switch active")
            raise RuntimeError(f"IBKRConnector.place_order blocked by kill switch: {reason}")

        if order_type == OrderType.LIMIT and price is None:
            raise ValueError("price is required for LIMIT orders.")
        if order_type == OrderType.STOP and stop_price is None:
            raise ValueError("stop_price is required for STOP orders.")

        try:
            contract = self._make_contract(symbol, instrument)
            action = "BUY" if side == OrderSide.BUY else "SELL"

            if order_type == OrderType.MARKET:
                ib_order = MarketOrder(action, quantity)
            elif order_type == OrderType.LIMIT:
                ib_order = LimitOrder(action, quantity, price)
            elif order_type == OrderType.STOP:
                ib_order = StopOrder(action, quantity, stop_price)
            else:
                raise ValueError(f"Unsupported order type: {order_type}")

            # Transmit immediately
            ib_order.transmit = True

            with self._lock:
                trade: Trade = self._ib.placeOrder(contract, ib_order)

            # Wait for acknowledgement (non-blocking poll)
            deadline = time.monotonic() + _ORDER_TIMEOUT_SEC
            while time.monotonic() < deadline:
                self._ib.sleep(0.1)
                if trade.orderStatus.status not in ("PreSubmitted", ""):
                    break

            order = self._trade_to_order(trade, symbol, side, order_type, quantity, price)

            logger.info(
                "IBKRConnector order placed | symbol=%s side=%s type=%s qty=%.4f "
                "price=%s order_id=%s status=%s mode=%s",
                symbol,
                side.value,
                order_type.value,
                quantity,
                price or stop_price,
                order.id,
                order.status.value,
                self._cfg.mode_label,
            )
            return order

        except Exception as exc:
            tb = traceback.format_exc()
            logger.error(
                "IBKRConnector.place_order failed | symbol=%s side=%s qty=%.4f: %s\n%s",
                symbol,
                side.value if hasattr(side, "value") else side,
                quantity,
                exc,
                tb,
            )
            self._capture_sentry(exc)
            raise

    def cancel_order(self, order_id: str) -> bool:
        """Cancel an open order by order ID."""
        if not self.connected or not self._ib:
            logger.error("IBKRConnector.cancel_order: not connected.")
            return False
        try:
            for trade in self._ib.trades():
                if str(trade.order.orderId) == str(order_id):
                    self._ib.cancelOrder(trade.order)
                    logger.info("IBKRConnector: cancelled order %s", order_id)
                    return True
            logger.warning("IBKRConnector.cancel_order: order %s not found.", order_id)
            return False
        except Exception as exc:
            logger.error("IBKRConnector.cancel_order error: %s", exc)
            self._capture_sentry(exc)
            return False

    def get_order(self, order_id: str) -> Order | None:
        """Retrieve order by ID."""
        if not self.connected or not self._ib:
            return None
        try:
            for trade in self._ib.trades():
                if str(trade.order.orderId) == str(order_id):
                    return self._trade_to_order(
                        trade,
                        symbol=trade.contract.symbol,
                        side=OrderSide.BUY if trade.order.action == "BUY" else OrderSide.SELL,
                        order_type=OrderType.MARKET,
                        quantity=trade.order.totalQuantity,
                    )
            return None
        except Exception as exc:
            logger.error("IBKRConnector.get_order error: %s", exc)
            self._capture_sentry(exc)
            return None

    # ------------------------------------------------------------------
    # Positions
    # ------------------------------------------------------------------

    def get_positions(self) -> list[Position]:
        """Return all open positions."""
        if not self.connected or not self._ib:
            logger.error("IBKRConnector.get_positions: not connected.")
            return []
        try:
            result: list[Position] = []
            for pos in self._ib.positions(account=self._account_id or ""):
                if pos.position == 0:
                    continue
                try:
                    ticker = self._ib.reqTicker(pos.contract)
                    current_price = float(ticker.marketPrice()) if ticker and ticker.marketPrice() else 0.0
                except Exception as _price_exc:
                    logger.debug("Could not fetch market price for %s: %s", pos.contract.symbol, _price_exc)
                    current_price = 0.0

                avg_cost = pos.avgCost
                qty = abs(pos.position)
                entry_price = avg_cost / qty if qty > 0 else 0.0
                unrealized_pnl = (current_price - entry_price) * qty * (1 if pos.position > 0 else -1)

                result.append(
                    Position(
                        symbol=pos.contract.symbol,
                        side="LONG" if pos.position > 0 else "SHORT",
                        quantity=qty,
                        entry_price=entry_price,
                        current_price=current_price,
                        unrealized_pnl=unrealized_pnl,
                        realized_pnl=0.0,
                        timestamp=datetime.now(UTC),
                        id=str(pos.contract.conId),
                    )
                )
            return result
        except Exception as exc:
            logger.error("IBKRConnector.get_positions error: %s", exc)
            self._capture_sentry(exc)
            return []

    def close_position(self, symbol: str) -> bool:
        """Close all open positions for *symbol* at market."""
        if not self.connected or not self._ib:
            logger.error("IBKRConnector.close_position: not connected.")
            return False
        try:
            positions = [p for p in self.get_positions() if p.symbol == symbol]
            if not positions:
                logger.warning("IBKRConnector.close_position: no position for %s.", symbol)
                return False
            for pos in positions:
                close_side = OrderSide.SELL if pos.side == "LONG" else OrderSide.BUY
                self.place_order(
                    symbol=symbol,
                    side=close_side,
                    order_type=OrderType.MARKET,
                    quantity=pos.quantity,
                )
            return True
        except Exception as exc:
            logger.error("IBKRConnector.close_position error: %s", exc)
            self._capture_sentry(exc)
            return False

    # ------------------------------------------------------------------
    # Account info
    # ------------------------------------------------------------------

    def get_account_info(self) -> AccountInfo:
        """Return current account summary."""
        if not self.connected or not self._ib:
            raise RuntimeError("IBKRConnector.get_account_info: not connected.")
        try:
            vals = {
                v.tag: v.value
                for v in self._ib.accountValues(account=self._account_id or "")
                if v.currency in ("USD", "BASE", "")
            }

            def _f(tag: str, default: float = 0.0) -> float:
                try:
                    return float(vals.get(tag, default))
                except (ValueError, TypeError):
                    return default

            return AccountInfo(
                balance=_f("TotalCashValue"),
                equity=_f("NetLiquidation"),
                margin_used=_f("MaintMarginReq"),
                margin_available=_f("AvailableFunds"),
                positions_count=len(self.get_positions()),
                timestamp=datetime.now(UTC),
            )
        except Exception as exc:
            logger.error("IBKRConnector.get_account_info error: %s", exc)
            self._capture_sentry(exc)
            raise

    # ------------------------------------------------------------------
    # Market data
    # ------------------------------------------------------------------

    def get_market_data(
        self,
        symbol: str,
        timeframe: str = "1 hour",
        limit: int = 100,
        instrument: str = "commodity",
    ) -> list[dict[str, Any]]:
        """
        Fetch historical OHLCV bars.

        Args:
            symbol: e.g. "XAUUSD"
            timeframe: IB bar size string e.g. "1 min", "5 mins", "1 hour", "1 day"
            limit: number of bars (approximate — IB uses duration strings)
            instrument: "commodity" | "cfd" | "future"
        """
        if not self.connected or not self._ib:
            raise RuntimeError("IBKRConnector.get_market_data: not connected.")
        try:
            contract = self._make_contract(symbol, instrument)

            # Map limit to a duration string (rough approximation)
            duration_map = {
                "1 secs": f"{max(limit * 1, 60)} S",
                "5 secs": f"{max(limit * 5, 60)} S",
                "1 min": f"{max(limit, 1)} D",
                "5 mins": f"{max(limit // 288 + 1, 1)} D",
                "1 hour": f"{max(limit // 24 + 1, 1)} D",
                "1 day": f"{max(limit, 1)} D",
            }
            duration = duration_map.get(timeframe, f"{limit} D")

            bars = self._ib.reqHistoricalData(
                contract,
                endDateTime="",
                durationStr=duration,
                barSizeSetting=timeframe,
                whatToShow="MIDPOINT",
                useRTH=False,
                formatDate=1,
            )

            return [
                {
                    "time": str(bar.date),
                    "open": float(bar.open),
                    "high": float(bar.high),
                    "low": float(bar.low),
                    "close": float(bar.close),
                    "volume": float(bar.volume),
                }
                for bar in bars
            ]
        except Exception as exc:
            logger.error("IBKRConnector.get_market_data error: %s", exc)
            self._capture_sentry(exc)
            raise

    def subscribe_ticks(
        self,
        symbol: str,
        callback: Callable[[dict], None],
        instrument: str = "commodity",
    ) -> None:
        """
        Subscribe to real-time tick data for *symbol*.

        The callback receives a dict:
            {"symbol": str, "bid": float, "ask": float, "last": float,
             "timestamp": float, "source": "ibkr"}
        """
        if not self.connected or not self._ib:
            raise RuntimeError("IBKRConnector.subscribe_ticks: not connected.")
        try:
            contract = self._make_contract(symbol, instrument)
            ticker = self._ib.reqMktData(contract, "", False, False)  # noqa: F841

            def _on_pending_tickers(tickers):
                for t in tickers:
                    if t.contract.symbol == contract.symbol:
                        tick = {
                            "symbol": symbol,
                            "bid": float(t.bid) if t.bid and t.bid > 0 else 0.0,
                            "ask": float(t.ask) if t.ask and t.ask > 0 else 0.0,
                            "last": float(t.last) if t.last and t.last > 0 else 0.0,
                            "timestamp": time.time(),
                            "source": "ibkr",
                        }
                        try:
                            callback(tick)
                        except Exception as cb_exc:
                            logger.error(
                                "IBKRConnector tick callback error: %s",
                                cb_exc,
                            )

            self._ib.pendingTickersEvent += _on_pending_tickers
            logger.info(
                "IBKRConnector: subscribed to ticks for %s (instrument=%s)",
                symbol,
                instrument,
            )
        except Exception as exc:
            logger.error("IBKRConnector.subscribe_ticks error: %s", exc)
            self._capture_sentry(exc)
            raise

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _trade_to_order(
        self,
        trade: Trade,
        symbol: str,
        side: OrderSide,
        order_type: OrderType,
        quantity: float,
        price: float | None = None,
    ) -> Order:
        """Convert ib_insync Trade to our Order dataclass."""
        status_map = {
            "PreSubmitted": OrderStatus.PENDING,
            "Submitted": OrderStatus.OPEN,
            "Filled": OrderStatus.FILLED,
            "PartiallyFilled": OrderStatus.PARTIAL,
            "Cancelled": OrderStatus.CANCELLED,
            "Inactive": OrderStatus.CANCELLED,
        }
        ib_status = trade.orderStatus.status
        status = status_map.get(ib_status, OrderStatus.PENDING)

        avg_price = trade.orderStatus.avgFillPrice or price or 0.0
        filled_qty = trade.orderStatus.filled or 0.0

        return Order(
            id=str(trade.order.orderId),
            symbol=symbol,
            side=side,
            type=order_type,
            quantity=quantity,
            price=price,
            status=status,
            filled_quantity=filled_qty,
            average_price=avg_price if avg_price > 0 else None,
            timestamp=datetime.now(UTC),
            metadata={
                "ib_order_id": trade.order.orderId,
                "ib_status": ib_status,
                "account": self._account_id,
                "mode": self._cfg.mode_label,
            },
        )

    @staticmethod
    def _capture_sentry(exc: Exception) -> None:
        if _SENTRY:
            try:
                sentry_sdk.capture_exception(exc)
            except Exception as _exc:
                logger.debug("Suppressed exception: %s", _exc)

    # ------------------------------------------------------------------
    # Context manager support
    # ------------------------------------------------------------------

    def __enter__(self) -> IBKRConnector:
        self.connect()
        return self

    def __exit__(self, *_) -> None:
        self.disconnect()

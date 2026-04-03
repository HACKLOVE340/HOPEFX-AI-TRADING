# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
brokers/ibkr.py
================
Interactive Brokers broker — ORDER EXECUTION ONLY.

This module handles ONLY:
  - TWS/Gateway connection lifecycle
  - Order placement (market, limit, stop, stop-limit)
  - Order cancellation
  - Position and account queries
  - Fill confirmation via ib_insync callbacks

This module NEVER:
  - Returns price data, ticks, bid/ask, or spreads
  - Streams market data via reqMktData
  - Fetches historical bars via reqHistoricalData
  - Provides any market data to the execution pipeline

ALL market data flows exclusively through data_layer.orchestrator.
Any attempt to call get_market_data(), subscribe_ticks(), or
reqHistoricalData() raises MarketDataForbiddenError to enforce the
architectural boundary at runtime.

Connection config
-----------------
  IBKR_HOST      — TWS/Gateway host (default: 127.0.0.1)
  IBKR_PORT      — 7497 (paper TWS) | 7496 (live TWS) |
                   4002 (paper gateway) | 4001 (live gateway)
  IBKR_CLIENT_ID — unique integer per connection (default: 1)

XAUUSD contract
---------------
  Commodity("XAUUSD", "SMART", "USD") — spot gold CFD
  Futures path available via _build_gold_contract(use_futures=True)
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
UTC = timezone.utc
from typing import Any

logger = logging.getLogger(__name__)

# ib_insync — optional dependency
try:
    from ib_insync import (  # type: ignore[import]
        IB,
        Commodity,
        Future,
        LimitOrder,
        MarketOrder,
        StopLimitOrder,
        StopOrder,
    )

    _IB_AVAILABLE = True
except ImportError:
    _IB_AVAILABLE = False
    IB = None
    logger.warning("ib_insync not installed — IBKRBroker unavailable. pip install ib_insync==0.9.86")

# ── env config ────────────────────────────────────────────────────────────────
_HOST = os.getenv("IBKR_HOST", "127.0.0.1")
_PORT_PAPER = int(os.getenv("IBKR_PORT_PAPER", "7497"))
_PORT_LIVE = int(os.getenv("IBKR_PORT_LIVE", "7496"))
_CLIENT_ID = int(os.getenv("IBKR_CLIENT_ID", "1"))
_CONNECT_TIMEOUT = float(os.getenv("IBKR_CONNECT_TIMEOUT_S", "30"))
_ORDER_TIMEOUT = float(os.getenv("IBKR_ORDER_TIMEOUT_S", "30"))
_RECONNECT_DELAY = float(os.getenv("IBKR_RECONNECT_DELAY_S", "5"))
_MAX_RECONNECTS = int(os.getenv("IBKR_MAX_RECONNECTS", "10"))


# ── Architectural boundary enforcement ───────────────────────────────────────


class MarketDataForbiddenError(RuntimeError):
    """
    Raised when code attempts to fetch market data through a broker connector.

    All market data must flow through data_layer.orchestrator exclusively.
    """

    def __init__(self, method: str) -> None:
        super().__init__(
            f"ARCHITECTURAL VIOLATION: {method}() called on IBKRBroker. "
            "Market data is forbidden in broker connectors. "
            "Use data_layer.orchestrator.get_latest_tick() and "
            "orchestrator.get_ml_features() instead."
        )


# ── Data classes ──────────────────────────────────────────────────────────────


@dataclass
class AccountInfo:
    account_id: str
    currency: str
    balance: float
    nav: float
    unrealized_pnl: float
    buying_power: float
    margin_used: float
    timestamp: datetime


@dataclass
class IBKRConfig:
    host: str = _HOST
    port: int = _PORT_PAPER
    client_id: int = _CLIENT_ID
    paper: bool = True


# ── IBKRBroker ────────────────────────────────────────────────────────────────


class IBKRBroker:
    """
    Interactive Brokers broker via ib_insync — order execution only.

    Parameters
    ----------
    config : dict
        Keys: server ("paper" | "live"), host (str), client_id (int).
    """

    def __init__(self, config: dict | None = None) -> None:
        config = config or {}
        server = str(config.get("server", os.getenv("IBKR_ENV", "paper")))
        self._cfg = IBKRConfig(
            host=str(config.get("host", _HOST)),
            port=_PORT_LIVE if server == "live" else _PORT_PAPER,
            client_id=int(config.get("client_id", _CLIENT_ID)),
            paper=server != "live",
        )
        self._ib: Any | None = None  # IB instance
        self.connected: bool = False
        self._reconnects: int = 0
        self._total_orders: int = 0
        self._total_fills: int = 0
        self._fill_callbacks: list[Callable] = []

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def connect(self) -> bool:
        if not _IB_AVAILABLE:
            logger.error("IBKRBroker: ib_insync not installed")
            return False
        if self.connected:
            return True
        try:
            self._ib = IB()
            await asyncio.wait_for(
                self._ib.connectAsync(
                    self._cfg.host,
                    self._cfg.port,
                    clientId=self._cfg.client_id,
                ),
                timeout=_CONNECT_TIMEOUT,
            )
            self._ib.orderStatusEvent += self._on_order_status
            self._ib.execDetailsEvent += self._on_exec_details
            self._ib.errorEvent += self._on_error
            self.connected = True
            self._reconnects = 0
            logger.info(
                "IBKRBroker: connected to %s:%d clientId=%d paper=%s",
                self._cfg.host,
                self._cfg.port,
                self._cfg.client_id,
                self._cfg.paper,
            )
            return True
        except TimeoutError:
            logger.error("IBKRBroker: connect timeout after %.0fs", _CONNECT_TIMEOUT)
            return False
        except Exception as exc:
            logger.error("IBKRBroker: connect failed: %s", exc)
            return False

    async def disconnect(self) -> None:
        if self._ib and self.connected:
            self._ib.disconnect()
        self.connected = False
        logger.info("IBKRBroker: disconnected")

    async def reconnect(self) -> bool:
        """Exponential-backoff reconnect, max _MAX_RECONNECTS attempts."""
        for attempt in range(1, _MAX_RECONNECTS + 1):
            delay = min(_RECONNECT_DELAY * (2 ** (attempt - 1)), 120.0)
            logger.warning(
                "IBKRBroker: reconnect attempt %d/%d in %.0fs",
                attempt,
                _MAX_RECONNECTS,
                delay,
            )
            await asyncio.sleep(delay)
            if await self.connect():
                return True
        logger.critical("IBKRBroker: all reconnect attempts exhausted")
        return False

    # ── Account info ──────────────────────────────────────────────────────────

    async def get_account_info(self) -> AccountInfo | None:
        """Query account values. Does NOT return price data."""
        if not self.connected or not self._ib:
            return None
        try:
            vals = {v.tag: v.value for v in self._ib.accountValues()}
            currency = vals.get("Currency", "USD")
            return AccountInfo(
                account_id=self._ib.managedAccounts()[0] if self._ib.managedAccounts() else "",
                currency=currency,
                balance=float(vals.get("CashBalance", 0)),
                nav=float(vals.get("NetLiquidation", 0)),
                unrealized_pnl=float(vals.get("UnrealizedPnL", 0)),
                buying_power=float(vals.get("BuyingPower", 0)),
                margin_used=float(vals.get("MaintMarginReq", 0)),
                timestamp=datetime.now(UTC),
            )
        except Exception as exc:
            logger.error("IBKRBroker get_account_info: %s", exc)
            return None

    # ── Order placement ───────────────────────────────────────────────────────

    async def place_order(self, order_request: dict) -> dict:
        """
        Place a market or limit order for XAUUSD.

        order_request keys (from SmartRouter / HopeFXEngine):
          symbol, direction, quantity, order_type, mid_price (for limit),
          order_id (client ref), signal_id

        Returns dict with: status, fill_price, quantity, broker, latency_ms
        """
        if not self.connected or not self._ib:
            return {"status": "rejected", "reason": "not_connected", "broker": "ibkr"}

        t0 = time.monotonic()
        symbol = order_request.get("symbol", "XAUUSD")
        direction = order_request.get("direction", "long")
        quantity = float(order_request.get("quantity", 0))
        order_type = order_request.get("order_type", "MARKET").upper()
        client_ref = order_request.get("order_id", str(uuid.uuid4()))

        if quantity <= 0:
            return {"status": "rejected", "reason": "zero_quantity", "broker": "ibkr"}

        action = "BUY" if direction.lower() in ("long", "buy") else "SELL"

        try:
            contract = self._build_gold_contract(symbol)
            ib_order = self._build_ib_order(action, quantity, order_type, order_request)

            trade = self._ib.placeOrder(contract, ib_order)
            self._total_orders += 1

            # Wait for fill or timeout
            fill_result = await self._wait_for_fill(trade, client_ref)
            fill_result["latency_ms"] = round((time.monotonic() - t0) * 1000, 2)

            if fill_result.get("status") == "filled":
                self._total_fills += 1

            return fill_result

        except Exception:
            logger.exception("IBKRBroker place_order: %s")
            return {"status": "rejected", "reason": "Order failed — check server logs", "broker": "ibkr"}

    def _build_gold_contract(self, symbol: str, use_futures: bool = False) -> Any:
        """Build IBKR XAUUSD contract. Never fetches price data."""
        if not _IB_AVAILABLE:
            raise RuntimeError("ib_insync not available")
        clean = symbol.replace("_", "").replace("/", "").upper()
        c = Future(symbol="GC", exchange="NYMEX", currency="USD") if use_futures else Commodity(clean, "SMART", "USD")
        return c

    def _build_ib_order(self, action: str, quantity: float, order_type: str, req: dict) -> Any:
        if not _IB_AVAILABLE:
            raise RuntimeError("ib_insync not available")
        qty = float(quantity)
        if order_type == "MARKET":
            return MarketOrder(action, qty)
        if order_type == "LIMIT":
            price = float(req.get("mid_price", 0))
            return LimitOrder(action, qty, price)
        if order_type == "STOP":
            stop_price = float(req.get("stop_price", req.get("mid_price", 0)))
            return StopOrder(action, qty, stop_price)
        if order_type == "STOP_LIMIT":
            lmt = float(req.get("mid_price", 0))
            stop = float(req.get("stop_price", lmt))
            return StopLimitOrder(action, qty, lmt, stop)
        return MarketOrder(action, qty)

    async def _wait_for_fill(self, trade: Any, client_ref: str) -> dict:
        """Poll trade status until filled, cancelled, or timeout."""
        deadline = time.monotonic() + _ORDER_TIMEOUT
        while time.monotonic() < deadline:
            await asyncio.sleep(0.1)
            status = trade.orderStatus.status
            if status == "Filled":
                avg_price = trade.orderStatus.avgFillPrice
                filled = trade.orderStatus.filled
                action = trade.order.action
                return {
                    "status": "filled",
                    "fill_price": float(avg_price),
                    "quantity": float(filled),
                    "direction": "long" if action == "BUY" else "short",
                    "order_id": str(trade.order.orderId),
                    "client_ref": client_ref,
                    "broker": "ibkr",
                }
            if status in ("Cancelled", "ApiCancelled", "Inactive"):
                return {
                    "status": "rejected",
                    "reason": f"ibkr_status:{status}",
                    "broker": "ibkr",
                }
        # Timeout — cancel the order
        try:
            self._ib.cancelOrder(trade.order)
        except Exception as _exc:
            logger.debug("Suppressed exception: %s", _exc)
        return {"status": "rejected", "reason": "fill_timeout", "broker": "ibkr"}

    # ── Order cancellation ────────────────────────────────────────────────────

    async def cancel_order(self, order_id: int) -> bool:
        if not self.connected or not self._ib:
            return False
        try:
            open_trades = self._ib.openTrades()
            for trade in open_trades:
                if trade.order.orderId == order_id:
                    self._ib.cancelOrder(trade.order)
                    return True
            return False
        except Exception as exc:
            logger.error("IBKRBroker cancel_order %s: %s", order_id, exc)
            return False

    # ── Position queries ──────────────────────────────────────────────────────

    async def get_open_positions(self) -> list[dict]:
        """Return open positions. Does NOT return price data."""
        if not self.connected or not self._ib:
            return []
        try:
            positions = []
            for pos in self._ib.positions():
                if pos.position != 0:
                    positions.append(
                        {
                            "symbol": pos.contract.symbol,
                            "quantity": pos.position,
                            "direction": "long" if pos.position > 0 else "short",
                            "avg_cost": pos.avgCost,
                        }
                    )
            return positions
        except Exception as exc:
            logger.error("IBKRBroker get_open_positions: %s", exc)
            return []

    # ── Ping ──────────────────────────────────────────────────────────────────

    async def ping(self) -> float:
        """Measure TWS round-trip latency. Returns ms."""
        if not self.connected or not self._ib:
            return 9999.0
        t0 = time.monotonic()
        try:
            await self._ib.reqCurrentTimeAsync()
            return (time.monotonic() - t0) * 1000
        except Exception as exc:
            logger.warning("IBKRBroker.ping() failed: %s", exc)
            return 9999.0

    # ── IB event callbacks ────────────────────────────────────────────────────

    def _on_order_status(self, trade: Any) -> None:
        logger.debug(
            "IBKRBroker order_status: id=%s status=%s filled=%s",
            trade.order.orderId,
            trade.orderStatus.status,
            trade.orderStatus.filled,
        )

    def _on_exec_details(self, trade: Any, fill: Any) -> None:
        logger.info(
            "IBKRBroker exec_details: id=%s price=%s qty=%s",
            trade.order.orderId,
            fill.execution.price,
            fill.execution.shares,
        )
        for cb in self._fill_callbacks:
            try:
                cb(trade, fill)
            except Exception as exc:
                logger.error("IBKRBroker fill callback error: %s", exc)

    def _on_error(self, req_id: int, error_code: int, error_string: str, contract: Any) -> None:
        if error_code in (2104, 2106, 2158):
            return  # informational only
        logger.error(
            "IBKRBroker error: req_id=%d code=%d msg=%s",
            req_id,
            error_code,
            error_string,
        )

    def register_fill_callback(self, cb: Callable) -> None:
        self._fill_callbacks.append(cb)

    # ── FORBIDDEN: market data methods ───────────────────────────────────────

    def get_market_data(self, *args, **kwargs):
        raise MarketDataForbiddenError("get_market_data")

    def subscribe_ticks(self, *args, **kwargs):
        raise MarketDataForbiddenError("subscribe_ticks")

    async def reqMktData(self, *args, **kwargs):
        raise MarketDataForbiddenError("reqMktData")

    async def reqHistoricalData(self, *args, **kwargs):
        raise MarketDataForbiddenError("reqHistoricalData")

    async def get_ohlcv(self, *args, **kwargs):
        raise MarketDataForbiddenError("get_ohlcv")

    async def get_current_price(self, *args, **kwargs):
        raise MarketDataForbiddenError("get_current_price")

    async def stream_prices(self, *args, **kwargs):
        raise MarketDataForbiddenError("stream_prices")

    # ── Diagnostics ───────────────────────────────────────────────────────────

    def metrics(self) -> dict[str, Any]:
        return {
            "broker": "ibkr",
            "connected": self.connected,
            "paper": self._cfg.paper,
            "total_orders": self._total_orders,
            "total_fills": self._total_fills,
            "fill_rate": self._total_fills / max(self._total_orders, 1),
        }


# ── Backward-compat aliases ───────────────────────────────────────────────────
IBKRConnector = IBKRBroker
InteractiveBrokers = IBKRBroker

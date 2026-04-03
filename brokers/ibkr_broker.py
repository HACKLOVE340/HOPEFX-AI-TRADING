# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
IBKRBroker — yaml-config-driven Interactive Brokers broker implementation.

Credential mapping (matches config/brokers.yaml):
    login    → IB username (informational; TWS/Gateway uses session auth)
    password → IB password (informational; TWS/Gateway uses session auth)
    server   → "paper" (port 7497) | "live" (port 7496)
    host     → TWS/Gateway host (default: "127.0.0.1")
    client_id → unique integer per simultaneous connection (default: 1)

Requires TWS or IB Gateway to be running and API connections enabled.
Uses ib_insync for the async event loop integration.

Usage
-----
    broker = IBKRBroker(config)
    await broker.connect()
    info = await broker.get_account_info()
    result = await broker.place_order({
        "symbol": "XAUUSD",
        "action": "BUY",
        "quantity": 1,
        "order_type": "MKT",
    })
    await broker.disconnect()
"""

import asyncio
import logging
import os
from typing import ClassVar

# Maximum number of TWS reconnection attempts before giving up.
_MAX_RECONNECT_ATTEMPTS = 3
# Backoff multiplier (seconds) between reconnect attempts.
_RECONNECT_BASE_DELAY = 1.0

logger = logging.getLogger(__name__)

try:
    from ib_insync import (  # type: ignore
        IB,
        Contract,
        LimitOrder,
        MarketOrder,
        StopOrder,
    )

    _IB_AVAILABLE = True
except ImportError:
    IB = None  # type: ignore
    _IB_AVAILABLE = False
    logger.warning("ib_insync not installed — IBKRBroker will be unavailable. Install with: pip install ib_insync")

# TWS / IB Gateway default ports.
_PORT_PAPER = 7497
_PORT_LIVE = 7496

# Default connection timeout (seconds).
_CONNECT_TIMEOUT = 30


def _resolve_env(value: object) -> str:
    """Expand ``${ENV_VAR:default}`` placeholders."""
    if not isinstance(value, str):
        return str(value) if value is not None else ""
    if value.startswith("${") and value.endswith("}"):
        inner = value[2:-1]
        var, _, default = inner.partition(":")
        return os.environ.get(var, default)
    return value


class IBKRBroker:
    """
    Async Interactive Brokers broker backed by ib_insync.

    Parameters
    ----------
    config:
        Dict with keys ``login``, ``password``, ``server`` ("paper" | "live").
        Optional: ``host`` (str, default "127.0.0.1"), ``client_id`` (int, default 1).
    """

    def __init__(self, config: dict) -> None:
        self._config = config
        self.connected: bool = False
        self._ib: object | None = IB() if _IB_AVAILABLE else None
        self._server_type: str | None = None
        self._host: str | None = None
        self._port: int | None = None
        self._client_id: int | None = None
        self._account: str | None = None

    # ── Lifecycle ──────────────────────────────────────────────────────────────

    async def connect(self) -> bool:
        """
        Connect to TWS or IB Gateway.

        Returns True on success, False on any failure (SDK missing, TWS not
        running, wrong port, etc.).
        """
        if not _IB_AVAILABLE:
            logger.error("IBKRBroker.connect: ib_insync not installed")
            return False

        self._server_type = _resolve_env(self._config.get("server", "paper")).lower()
        self._host = _resolve_env(self._config.get("host", "127.0.0.1"))
        self._client_id = int(self._config.get("client_id", 1))
        self._port = _PORT_PAPER if self._server_type == "paper" else _PORT_LIVE

        username = _resolve_env(self._config.get("login", ""))
        if not username or username.startswith("your_ibkr"):
            logger.warning(
                "IBKRBroker: login appears to be a placeholder ('%s'). "
                "Set IBKR_USERNAME env var or update config/brokers.yaml. "
                "Note: TWS/Gateway uses session-based auth — username is informational.",
                username,
            )

        try:
            await asyncio.wait_for(
                self._ib.connectAsync(
                    host=self._host,
                    port=self._port,
                    clientId=self._client_id,
                    readonly=False,
                ),
                timeout=_CONNECT_TIMEOUT,
            )
            self.connected = True
            accounts = self._ib.managedAccounts()
            self._account = accounts[0] if accounts else None
            logger.info(
                "IBKRBroker connected | %s | host=%s:%s | clientId=%s | account=%s",
                "Paper" if self._server_type == "paper" else "Live",
                self._host,
                self._port,
                self._client_id,
                self._account,
            )
            return True
        except TimeoutError:
            logger.error(
                "IBKRBroker connect timed out after %ss — is TWS/Gateway running on %s:%s?",
                _CONNECT_TIMEOUT,
                self._host,
                self._port,
            )
            return False
        except Exception as exc:
            logger.error("IBKRBroker connect failed: %s", exc)
            return False

    async def disconnect(self) -> None:
        """Disconnect from TWS / IB Gateway."""
        if self.connected and _IB_AVAILABLE and self._ib:
            self._ib.disconnect()
            self.connected = False
            logger.info("IBKRBroker disconnected (account=%s)", self._account)

    # ── Account ───────────────────────────────────────────────────────────────

    async def get_account_info(self) -> dict | None:
        """Return account summary as a plain dict."""
        if not self._assert_connected("get_account_info"):
            return None
        summary = self._ib.accountSummary(account=self._account or "")
        result: ClassVar[dict] = {}
        for item in summary:
            result[item.tag] = item.value
        # Normalise the most common fields.
        return {
            "account": self._account,
            "net_liquidation": _safe_float(result.get("NetLiquidation")),
            "total_cash": _safe_float(result.get("TotalCashValue")),
            "buying_power": _safe_float(result.get("BuyingPower")),
            "gross_position_value": _safe_float(result.get("GrossPositionValue")),
            "unrealized_pnl": _safe_float(result.get("UnrealizedPnL")),
            "realized_pnl": _safe_float(result.get("RealizedPnL")),
            "currency": result.get("Currency", "USD"),
            "raw": result,
        }

    async def get_positions(self) -> list[dict]:
        """Return all open positions."""
        if not self._assert_connected("get_positions"):
            return []
        positions = self._ib.positions(account=self._account or "")
        return [
            {
                "account": p.account,
                "symbol": p.contract.symbol,
                "sec_type": p.contract.secType,
                "exchange": p.contract.exchange,
                "currency": p.contract.currency,
                "position": p.position,
                "avg_cost": p.avgCost,
                "market_value": p.position * p.avgCost,
            }
            for p in positions
        ]

    async def get_orders(self) -> list[dict]:
        """Return all open/pending orders."""
        if not self._assert_connected("get_orders"):
            return []
        trades = self._ib.openTrades()
        return [
            {
                "order_id": t.order.orderId,
                "perm_id": t.order.permId,
                "symbol": t.contract.symbol,
                "action": t.order.action,
                "quantity": t.order.totalQuantity,
                "order_type": t.order.orderType,
                "limit_price": t.order.lmtPrice,
                "aux_price": t.order.auxPrice,
                "status": t.orderStatus.status,
                "filled": t.orderStatus.filled,
                "remaining": t.orderStatus.remaining,
            }
            for t in trades
        ]

    # ── Order execution ───────────────────────────────────────────────────────

    async def place_order(self, order_params: dict) -> dict:
        """
        Place an order via TWS / IB Gateway.

        Parameters
        ----------
        order_params:
            symbol      (str)   — e.g. "XAUUSD", "AAPL"
            action      (str)   — "BUY" | "SELL"
            quantity    (float) — number of units / contracts
            order_type  (str)   — "MKT" (default) | "LMT" | "STP"
            limit_price (float) — required for LMT orders
            aux_price   (float) — stop price for STP orders
            sec_type    (str)   — "CASH" (default for FX) | "STK" | "FUT" | "CFD"
            exchange    (str)   — exchange (default: "IDEALPRO" for FX, "SMART" for stocks)
            currency    (str)   — currency (default: "USD")
            account     (str)   — override account (default: first managed account)

        Returns
        -------
        Dict with keys: ``success`` (bool), ``order_id`` (int), ``perm_id`` (int),
        ``status`` (str), ``comment`` (str).
        """
        if not self._assert_connected("place_order"):
            return {"success": False, "order_id": 0, "comment": "Not connected"}

        symbol: str = order_params.get("symbol", "XAUUSD")
        action: str = order_params.get("action", "BUY").upper()
        quantity: float = float(order_params.get("quantity", 1))
        order_type: str = order_params.get("order_type", "MKT").upper()
        limit_price: float = float(order_params.get("limit_price", 0.0))
        aux_price: float = float(order_params.get("aux_price", 0.0))
        sec_type: str = order_params.get("sec_type", "CASH")
        currency: str = order_params.get("currency", "USD")
        account: str = order_params.get("account", self._account or "")

        # Default exchange by security type.
        default_exchange = "IDEALPRO" if sec_type == "CASH" else "SMART"
        exchange: str = order_params.get("exchange", default_exchange)

        # Build contract.
        contract = _build_contract(symbol, sec_type, exchange, currency)

        # Build order.
        if order_type == "MKT":
            ib_order = MarketOrder(action=action, totalQuantity=quantity)
        elif order_type == "LMT":
            ib_order = LimitOrder(action=action, totalQuantity=quantity, lmtPrice=limit_price)
        elif order_type == "STP":
            ib_order = StopOrder(action=action, totalQuantity=quantity, stopPrice=aux_price)
        else:
            return {
                "success": False,
                "order_id": 0,
                "comment": f"Unsupported order_type: {order_type}",
            }

        if account:
            ib_order.account = account

        try:
            trade = self._ib.placeOrder(contract, ib_order)
            # ib_insync.placeOrder() is synchronous — it submits the order to the
            # local TWS message queue and returns a Trade object immediately.
            # No sleep is needed; the TWS acknowledgement arrives asynchronously
            # through the ib_insync event loop and is reflected in trade.orderStatus.
            logger.info(
                "IBKR order placed | symbol=%s | action=%s | qty=%.2f | type=%s | order_id=%s",
                symbol,
                action,
                quantity,
                order_type,
                trade.order.orderId,
            )
            return {
                "success": True,
                "order_id": trade.order.orderId,
                "perm_id": trade.order.permId,
                "status": trade.orderStatus.status,
                "comment": "OK",
            }
        except ConnectionError as exc:
            logger.error(
                "IBKRBroker.place_order: TWS connection lost | symbol=%s | error=%s",
                symbol,
                exc,
            )
            self.connected = False
            return {
                "success": False,
                "order_id": 0,
                "comment": f"TWS connection lost: {exc}",
                "error_type": "connection",
            }
        except ValueError as exc:
            logger.error(
                "IBKRBroker.place_order: invalid order parameters | symbol=%s | error=%s",
                symbol,
                exc,
            )
            return {
                "success": False,
                "order_id": 0,
                "comment": f"Invalid order parameters: {exc}",
                "error_type": "validation",
            }
        except AttributeError as exc:
            # ib_insync raises AttributeError when the IB object is in a bad state.
            logger.error(
                "IBKRBroker.place_order: IB session in bad state | symbol=%s | error=%s",
                symbol,
                exc,
            )
            self.connected = False
            return {
                "success": False,
                "order_id": 0,
                "comment": f"IB session state error: {exc}",
                "error_type": "session",
            }
        except Exception as exc:  # pylint: disable=broad-exception-caught
            # Catch-all for unexpected ib_insync exceptions (e.g. TWS rejection codes
            # surfaced as generic exceptions). Log with full traceback so every
            # failure mode is captured; return structured error to caller.
            logger.exception(
                "IBKRBroker.place_order: unexpected error | symbol=%s | error=%s",
                symbol,
                exc,
            )
            return {
                "success": False,
                "order_id": 0,
                "comment": f"Order failed ({type(exc).__name__}): {exc}",
                "error_type": "unexpected",
            }

    async def cancel_order(self, order_id: int) -> dict:
        """Cancel a pending order by order ID."""
        if not self._assert_connected("cancel_order"):
            return {"success": False, "comment": "Not connected"}
        open_trades = self._ib.openTrades()
        target = next((t for t in open_trades if t.order.orderId == order_id), None)
        if target is None:
            return {
                "success": False,
                "comment": f"Order {order_id} not found in open trades",
            }
        try:
            self._ib.cancelOrder(target.order)
            # cancelOrder() is synchronous — no artificial delay needed.
            logger.info("IBKR order cancelled | order_id=%s", order_id)
            return {"success": True, "comment": "OK"}
        except ConnectionError as exc:
            logger.error("IBKRBroker.cancel_order: TWS connection lost | order_id=%s | error=%s", order_id, exc)
            self.connected = False
            return {"success": False, "comment": f"TWS connection lost: {exc}", "error_type": "connection"}
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.exception("IBKRBroker.cancel_order: unexpected error | order_id=%s | error=%s", order_id, exc)
            return {"success": False, "comment": f"Cancel failed ({type(exc).__name__}): {exc}", "error_type": "unexpected"}

    async def close_position(
        self,
        symbol: str,
        sec_type: str = "CASH",
        exchange: str = "IDEALPRO",
        currency: str = "USD",
    ) -> dict:
        """
        Close all open positions for *symbol* by placing a market order in the
        opposite direction.
        """
        if not self._assert_connected("close_position"):
            return {"success": False, "comment": "Not connected"}

        positions = self._ib.positions(account=self._account or "")
        target = next((p for p in positions if p.contract.symbol == symbol), None)
        if target is None:
            return {"success": False, "comment": f"No open position for {symbol}"}

        close_action = "SELL" if target.position > 0 else "BUY"
        return await self.place_order(
            {
                "symbol": symbol,
                "action": close_action,
                "quantity": abs(target.position),
                "order_type": "MKT",
                "sec_type": sec_type,
                "exchange": exchange,
                "currency": currency,
            }
        )

    async def get_tick(
        self,
        symbol: str,
        sec_type: str = "CASH",
        exchange: str = "IDEALPRO",
        currency: str = "USD",
    ) -> dict | None:
        """Request a snapshot tick for *symbol*."""
        if not self._assert_connected("get_tick"):
            return None
        contract = _build_contract(symbol, sec_type, exchange, currency)
        try:
            ticker = self._ib.reqMktData(contract, "", True, False)
            # Wait up to 2s for the snapshot to populate, checking every 50ms.
            # This is far better than an unconditional sleep(0.5) because we
            # exit as soon as real data arrives, saving up to 450ms per call.
            deadline = asyncio.get_event_loop().time() + 2.0
            while asyncio.get_event_loop().time() < deadline:
                if ticker.bid and ticker.bid > 0 and ticker.ask and ticker.ask > 0:
                    break
                await asyncio.sleep(0.05)
            self._ib.cancelMktData(contract)
            bid = ticker.bid if ticker.bid and ticker.bid > 0 else None
            ask = ticker.ask if ticker.ask and ticker.ask > 0 else None
            return {
                "symbol": symbol,
                "bid": bid,
                "ask": ask,
                "mid": (bid + ask) / 2.0 if bid and ask else None,
                "last": ticker.last,
            }
        except Exception as exc:
            logger.error("IBKRBroker.get_tick error: %s", exc)
            return None

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _assert_connected(self, method: str) -> bool:
        if not self.connected or self._ib is None:
            logger.error("IBKRBroker.%s called before connect()", method)
            return False
        return True

    async def reconnect(self) -> bool:
        """
        Attempt to reconnect to TWS / IB Gateway with exponential backoff.

        Tries up to _MAX_RECONNECT_ATTEMPTS times.  Returns True when a
        connection is (re-)established, False after all attempts fail.
        """
        logger.warning("IBKRBroker: attempting reconnect (was connected=%s)", self.connected)
        await self.disconnect()
        for attempt in range(1, _MAX_RECONNECT_ATTEMPTS + 1):
            delay = _RECONNECT_BASE_DELAY * (2 ** (attempt - 1))
            logger.info("IBKRBroker: reconnect attempt %d/%d in %.1fs...", attempt, _MAX_RECONNECT_ATTEMPTS, delay)
            await asyncio.sleep(delay)
            if await self.connect():
                logger.info("IBKRBroker: reconnect succeeded on attempt %d", attempt)
                return True
            logger.warning("IBKRBroker: reconnect attempt %d failed", attempt)
        logger.error("IBKRBroker: all %d reconnect attempts exhausted", _MAX_RECONNECT_ATTEMPTS)
        return False

    def status(self) -> dict:
        """Return a health snapshot for monitoring."""
        return {
            "broker": "ibkr",
            "connected": self.connected,
            "account": self._account,
            "server_type": self._server_type,
            "host": self._host,
            "port": self._port,
            "client_id": self._client_id,
            "sdk_available": _IB_AVAILABLE,
        }


# ── Module-level helpers ───────────────────────────────────────────────────────


def _build_contract(symbol: str, sec_type: str, exchange: str, currency: str) -> object:
    """Build an ib_insync Contract from basic parameters."""
    if not _IB_AVAILABLE:
        raise RuntimeError("ib_insync not installed")
    contract = Contract()
    contract.symbol = symbol
    contract.secType = sec_type
    contract.exchange = exchange
    contract.currency = currency
    return contract


def _safe_float(value: object) -> float | None:
    """Convert a value to float, returning None on failure."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return None

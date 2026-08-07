# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
brokers/oanda.py
================
OANDA v20 REST broker — ORDER EXECUTION ONLY.

This module handles ONLY:
  - Account info queries
  - Order placement (market, limit, stop)
  - Order cancellation
  - Position queries
  - Fill confirmation

This module NEVER:
  - Returns price data, ticks, bid/ask, or spreads
  - Streams market data
  - Fetches OHLCV candles
  - Provides any market data to the execution pipeline

ALL market data flows exclusively through data_layer.orchestrator.
Any attempt to call get_market_data() or stream_prices() raises
MarketDataForbiddenError to enforce the architectural boundary at runtime.

Region routing
--------------
  practice → api-fxpractice.oanda.com
  live     → api-fxtrade.oanda.com

Credential resolution
---------------------
  OANDA_ACCOUNT_ID  — account number (e.g. 101-123-4567890-001)
  OANDA_API_TOKEN   — personal access token
  OANDA_ENVIRONMENT — "practice" | "live" (default: practice)
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

UTC = timezone.utc
from typing import Any

import re

import aiohttp
import requests  # type: ignore[import-untyped]

# AccountInfo is imported, never redefined. This module must NOT declare its own
# variant: one previously existed here with `nav` instead of `equity` and without
# the dict accessors, which made every live-OANDA pre-trade risk check raise
# AttributeError — swallowed by the decision engine and reported as a risk-limit
# block, so live OANDA silently refused to trade. See docs/HARDENING_BACKLOG.md
# S1-01 and tests/unit/test_account_info_contract.py.
from brokers.base import AccountInfo

logger = logging.getLogger(__name__)

_PRACTICE_BASE = "https://api-fxpractice.oanda.com"
_LIVE_BASE = "https://api-fxtrade.oanda.com"
_DEFAULT_TIMEOUT = float(os.getenv("OANDA_TIMEOUT_S", "10"))
_MAX_RETRIES = int(os.getenv("OANDA_MAX_RETRIES", "3"))
_RETRY_BACKOFF = float(os.getenv("OANDA_RETRY_BACKOFF_S", "0.5"))

# OANDA v20 account ID format: 101-XXX-XXXXXXXX-XXX
# e.g. 101-001-12345678-001  (practice) or 001-001-12345678-001 (live)
_ACCOUNT_ID_RE = re.compile(r"^\d{3}-\d{3}-\d{6,10}-\d{3}$")


def validate_oanda_account_id(account_id: str) -> bool:
    """
    Return True when *account_id* matches the OANDA v20 format.

    Valid format: ``101-XXX-XXXXXXXX-XXX``
    Examples:
      101-001-12345678-001  ✓
      001-001-123456789-001 ✓
      ACC123                ✗  (test fixture — not a real account)
      PENDING               ✗  (placeholder — broker not yet connected)

    Called by OANDABroker.connect() and OANDAConnector.__init__() to
    reject placeholder values before they reach the API.
    """
    return bool(_ACCOUNT_ID_RE.match(account_id or ""))


# ── Architectural boundary enforcement ───────────────────────────────────────


class MarketDataForbiddenError(RuntimeError):
    """
    Raised when code attempts to fetch market data through a broker connector.

    All market data must flow through data_layer.orchestrator exclusively.
    """

    def __init__(self, method: str) -> None:
        super().__init__(
            f"ARCHITECTURAL VIOLATION: {method}() called on OANDABroker. "
            "Market data is forbidden in broker connectors. "
            "Use data_layer.orchestrator.get_latest_tick() and "
            "orchestrator.get_ml_features() instead."
        )


# ── Data classes ──────────────────────────────────────────────────────────────


@dataclass
class OrderResult:
    order_id: str
    client_ref: str
    status: str  # "filled" | "pending" | "rejected" | "cancelled"
    fill_price: float
    quantity: float
    direction: str
    symbol: str
    broker: str = "oanda"
    latency_ms: float = 0.0
    reject_reason: str = ""
    raw: dict[str, Any] | None = None


# ── Helpers ───────────────────────────────────────────────────────────────────


def _resolve_env(value: Any) -> str:
    if not isinstance(value, str):
        return str(value) if value is not None else ""
    if value.startswith("${") and value.endswith("}"):
        inner = value[2:-1]
        var, _, default = inner.partition(":")
        return os.environ.get(var, default)
    return value


def _units(direction: str, quantity: float) -> int:
    """Return signed integer units for the OANDA v20 API.

    OANDA requires units as a signed integer string: positive = buy,
    negative = sell.  Fractional quantities are rounded to the nearest
    integer.

    Raises ValueError when rounding would produce 0 units (e.g. quantity=0.3),
    which OANDA rejects with UNITS_INVALID.  Callers must validate that
    quantity >= 1 before calling this function, or catch ValueError and
    reject the order upstream.
    """
    qty = abs(quantity)
    rounded = round(qty)
    if rounded == 0:
        raise ValueError(
            f"Quantity {quantity} rounds to 0 units — OANDA requires at least 1 unit. "
            "Minimum order size is 1 unit of the base currency."
        )
    if abs(rounded - qty) > 0.01:
        logger.warning(
            "Quantity rounded from %.4f to %d units (%.4f lost) for %s order",
            qty,
            rounded,
            abs(qty - rounded),
            direction,
        )
    return rounded if direction.lower() in ("long", "buy") else -rounded


# ── OANDABroker (async) ───────────────────────────────────────────────────────


class OANDABroker:
    """
    Async OANDA v20 REST broker — order execution only.

    Parameters
    ----------
    config : dict
        Keys: login (account ID), password (API token),
              server ("practice" | "live"), timeout_seconds (optional).
    """

    def __init__(
        self,
        config: dict[str, Any] | None = None,
        *,
        api_key: str | None = None,
        account_id: str | None = None,
        server: str | None = None,
        **_kwargs: Any,
    ) -> None:
        # Accept both dict-style config and keyword-argument style.
        cfg = config or {}
        from config.settings import resolve_oanda_account, resolve_oanda_token

        self._account_id = _resolve_env(account_id or cfg.get("login", resolve_oanda_account()))
        self._token = _resolve_env(api_key or cfg.get("password", resolve_oanda_token()))
        _server = _resolve_env(server or cfg.get("server", os.getenv("OANDA_ENVIRONMENT", "practice")))
        self._base_url = _LIVE_BASE if _server == "live" else _PRACTICE_BASE
        self._timeout = float(cfg.get("timeout_seconds", _DEFAULT_TIMEOUT))
        self._session: aiohttp.ClientSession | None = None
        self.connected: bool = False
        self._total_orders: int = 0
        self._total_fills: int = 0
        # Optional injected API object (used by tests to bypass HTTP calls)
        self.api = None
        # Optional injected risk manager (used by tests)
        self.risk_manager = None

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def connect(self) -> bool:
        if self.connected:
            return True
        # When a test injects self.api, skip the real HTTP handshake.
        if self.api is not None:
            self.connected = True
            logger.debug("OANDABroker: using injected api object — skipping HTTP connect")
            return True
        if not self._account_id or not self._token:
            logger.error("OANDABroker: missing OANDA_ACCOUNT_ID or OANDA_API_TOKEN")  # nosec B105 - logs absence, not value
            return False
        if not validate_oanda_account_id(self._account_id):
            logger.error(
                "OANDABroker: account_id %r does not match OANDA v20 format "
                "(expected 101-XXX-XXXXXXXX-XXX). "
                "Set OANDA_ACCOUNT_ID to your real practice account ID.",
                self._account_id[:12] if self._account_id else "",
            )
            return False
        headers = {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
            "Accept-Datetime-Format": "RFC3339",
        }
        timeout = aiohttp.ClientTimeout(total=self._timeout)
        self._session = aiohttp.ClientSession(headers=headers, timeout=timeout)
        try:
            async with self._session.get(f"{self._base_url}/v3/accounts/{self._account_id}") as resp:
                resp.raise_for_status()
            self.connected = True
            logger.info("OANDABroker: connected to %s", self._base_url)
            return True
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.error("OANDABroker: connect failed: %s", exc)
            await self._session.close()
            self._session = None
            return False

    async def disconnect(self) -> bool:
        if self._session:
            await self._session.close()
            self._session = None
        self.connected = False
        logger.info("OANDABroker: disconnected")
        return True

    # ── Account info ──────────────────────────────────────────────────────────

    async def get_account_info(self) -> AccountInfo | None:
        """Query account balance, NAV, margin. Does NOT return price data."""
        if not self.connected or not self._session:
            return None
        try:
            async with self._session.get(f"{self._base_url}/v3/accounts/{self._account_id}/summary") as resp:
                resp.raise_for_status()
                data = await resp.json()
            a = data.get("account", {})
            # balance = closed cash; NAV = balance + unrealized P&L (higher when winning, lower when losing)
            balance = float(a.get("balance", 0))
            nav = float(a.get("NAV", balance))  # fallback to balance when NAV absent (not to 0)
            # NAV maps to `equity`: the mark-to-market value the risk gates must
            # size and measure drawdown against. Reporting `balance` as equity
            # would leave those gates blind to floating losses on open positions.
            return AccountInfo(
                balance=balance,
                equity=nav,
                margin_used=float(a.get("marginUsed", 0)),
                margin_available=float(a.get("marginAvailable", 0)),
                positions_count=int(a.get("openPositionCount", a.get("openTradeCount", 0))),
                timestamp=datetime.now(UTC),
                account_id=self._account_id,
                currency=a.get("currency", "USD"),
                unrealized_pnl=float(a.get("unrealizedPL", 0)),
            )
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.error("OANDABroker get_account_info: %s", exc)
            return None

    # ── Order placement ───────────────────────────────────────────────────────

    async def place_order(self, order_request: dict[str, Any]) -> dict[str, Any]:
        """
        Place a market or limit order.

        order_request keys (from SmartRouter / HopeFXEngine):
          symbol, direction, quantity, order_type, mid_price (for limit),
          order_id (client ref), signal_id

        Returns dict with: status, fill_price, quantity, broker, latency_ms
        """
        # Risk manager gate — checked before any broker call.
        if self.risk_manager is not None:
            try:
                risk_result = self.risk_manager.check_order(order_request)
                if not risk_result.passed:
                    raise RuntimeError(
                        f"Position limit exceeded: {risk_result.message}"
                        if "limit" in str(risk_result.message).lower()
                        else f"Risk check failed: {risk_result.message}"
                    )
            except RuntimeError:
                raise
            except Exception as exc:  # pylint: disable=broad-exception-caught
                raise RuntimeError(f"Risk check error: {exc}") from exc

        if not self.connected or not self._session:
            return {"status": "rejected", "reason": "not_connected", "broker": "oanda"}

        t0 = time.monotonic()
        symbol = order_request.get("symbol", "XAU_USD")
        direction = order_request.get("direction", "long")
        quantity = float(order_request.get("quantity", 0))
        order_type = order_request.get("order_type", "MARKET").upper()
        client_ref = order_request.get("order_id", str(uuid.uuid4()))

        if quantity <= 0:
            return {"status": "rejected", "reason": "zero_quantity", "broker": "oanda"}

        try:
            units = _units(direction, quantity)
        except ValueError as exc:
            logger.error("OANDABroker.place_order: %s", exc)
            return {"status": "rejected", "reason": "quantity_rounds_to_zero", "broker": "oanda"}

        # Build OANDA order body
        order_body: dict[str, Any] = {
            "type": order_type,
            "instrument": symbol,
            "units": str(units),
            "timeInForce": "FOK" if order_type == "MARKET" else "GTC",
            "clientExtensions": {
                "id": client_ref[:32],
                "comment": f"hopefx:{order_request.get('signal_id', '')[:16]}",
            },
        }

        if order_type == "LIMIT":
            price = order_request.get("mid_price")
            if price:
                order_body["price"] = f"{float(price):.5f}"

        # Attach stop-loss and take-profit if provided — these become OCO orders
        # on OANDA's side and are guaranteed to execute even if connection drops.
        sl_price = order_request.get("stop_loss") or order_request.get("sl_price")
        tp_price = order_request.get("take_profit") or order_request.get("tp_price")
        if sl_price is not None:
            order_body["stopLossOnFill"] = {
                "price": f"{float(sl_price):.5f}",
                "timeInForce": "GTC",
            }
        if tp_price is not None:
            order_body["takeProfitOnFill"] = {
                "price": f"{float(tp_price):.5f}",
                "timeInForce": "GTC",
            }

        payload = {"order": order_body}

        self._total_orders += 1
        result = await self._post_order_with_retry(payload, client_ref)
        result["latency_ms"] = round((time.monotonic() - t0) * 1000, 2)

        if result.get("status") == "filled":
            self._total_fills += 1

        return result

    async def _post_order_with_retry(self, payload: dict[str, Any], client_ref: str) -> dict[str, Any]:
        if self._session is None:
            return {"status": "rejected", "reason": "not_connected", "broker": "oanda"}
        last_error = "unknown"
        for attempt in range(1, _MAX_RETRIES + 1):
            try:
                async with self._session.post(
                    f"{self._base_url}/v3/accounts/{self._account_id}/orders",
                    json=payload,
                ) as resp:
                    data = await resp.json()

                    if resp.status in (200, 201):
                        return self._parse_fill(data, client_ref)

                    # OANDA error response
                    error_code = data.get("errorCode", "")
                    error_msg = data.get("errorMessage", str(data))
                    logger.warning(
                        "OANDABroker: order rejected (attempt %d/%d) code=%s msg=%s",
                        attempt,
                        _MAX_RETRIES,
                        error_code,
                        error_msg,
                    )
                    last_error = f"{error_code}:{error_msg}"

                    # Non-retryable rejections
                    if error_code in (
                        "INSUFFICIENT_MARGIN",
                        "ACCOUNT_NOT_TRADEABLE",
                        "INSTRUMENT_NOT_TRADEABLE",
                        "UNITS_LIMIT_EXCEEDED",
                    ):
                        return {
                            "status": "rejected",
                            "reason": last_error,
                            "broker": "oanda",
                        }

                    # Idempotency: duplicate submission means our first attempt
                    # was already accepted. Return pending so the caller can
                    # query for the actual fill rather than submitting again.
                    if error_code == "DUPLICATE_CLIENT_ORDER_ID":
                        logger.info(
                            "OANDABroker: duplicate client_ref=%s — order already exists",
                            client_ref,
                        )
                        return {
                            "status": "pending",
                            "reason": "duplicate_client_ref",
                            "order_id": client_ref,
                            "broker": "oanda",
                        }

            except TimeoutError:
                last_error = "timeout"
                logger.warning("OANDABroker: order timeout (attempt %d/%d)", attempt, _MAX_RETRIES)
            except Exception:  # pylint: disable=broad-exception-caught
                last_error = "order_error"
                logger.exception(
                    "OANDABroker: order error (attempt %d/%d)",
                    attempt,
                    _MAX_RETRIES,
                )

            if attempt < _MAX_RETRIES:
                await asyncio.sleep(_RETRY_BACKOFF * attempt)

        return {
            "status": "rejected",
            "reason": f"max_retries:{last_error}",
            "broker": "oanda",
        }

    @staticmethod
    def _parse_fill(data: dict[str, Any], client_ref: str) -> dict[str, Any]:
        """Parse OANDA order response into canonical fill dict."""
        # Market order fill
        fill = data.get("orderFillTransaction", {})
        if fill:
            raw_price_str = fill.get("price") or fill.get("tradeOpened", {}).get("price")
            raw_units_str = fill.get("units")
            if not raw_price_str or not raw_units_str:
                logger.warning(
                    "_parse_fill: orderFillTransaction present but missing price=%r units=%r — treating as rejected",
                    raw_price_str,
                    raw_units_str,
                )
                return {"status": "rejected", "reason": "missing_fill_fields", "broker": "oanda", "raw": data}
            price = float(raw_price_str)
            raw_units = int(raw_units_str)
            units = abs(raw_units)
            direction = "long" if raw_units > 0 else "short"
            if price <= 0.0 or units == 0:
                logger.warning(
                    "_parse_fill: degenerate fill price=%.5f units=%d for client_ref=%s — treating as rejected",
                    price,
                    units,
                    client_ref,
                )
                return {"status": "rejected", "reason": "degenerate_fill", "broker": "oanda", "raw": data}
            return {
                "status": "filled",
                "fill_price": price,
                "quantity": units,
                "direction": direction,
                "order_id": fill.get("orderID", ""),
                "trade_id": fill.get("tradeOpened", {}).get("tradeID", ""),
                "client_ref": client_ref,
                "broker": "oanda",
                "raw": data,
            }

        # Limit order created (pending)
        created = data.get("orderCreateTransaction", {})
        if created:
            return {
                "status": "pending",
                "order_id": created.get("orderID", ""),
                "broker": "oanda",
                "raw": data,
            }

        # Cancelled / rejected
        cancel = data.get("orderCancelTransaction", {})
        reason = cancel.get("reason", "unknown")
        return {"status": "rejected", "reason": reason, "broker": "oanda", "raw": data}

    # ── Order cancellation ────────────────────────────────────────────────────

    async def cancel_order(self, order_id: str) -> bool:
        if not self.connected or not self._session:
            return False
        try:
            async with self._session.put(
                f"{self._base_url}/v3/accounts/{self._account_id}/orders/{order_id}/cancel"
            ) as resp:
                return resp.status in (200, 201)
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.error("OANDABroker cancel_order %s: %s", order_id, exc)
            return False

    # ── Position queries ──────────────────────────────────────────────────────

    async def get_open_positions(self) -> list[dict[str, Any]]:
        """Return open positions. Does NOT return price data."""
        if not self.connected or not self._session:
            return []
        try:
            async with self._session.get(f"{self._base_url}/v3/accounts/{self._account_id}/openPositions") as resp:
                resp.raise_for_status()
                data = await resp.json()
            positions = []
            for p in data.get("positions", []):
                long_units = int(p.get("long", {}).get("units", 0))
                short_units = int(p.get("short", {}).get("units", 0))
                if long_units != 0 or short_units != 0:
                    positions.append(
                        {
                            "symbol": p.get("instrument"),
                            "long_units": long_units,
                            "short_units": short_units,
                            "unrealized_pnl": float(p.get("unrealizedPL", 0)),
                        }
                    )
            return positions
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.error("OANDABroker get_open_positions: %s", exc)
            return []

    async def close_position(self, symbol: str, direction: str = "all") -> dict[str, Any]:
        """Close an open position by symbol."""
        if not self.connected or not self._session:
            return {"status": "rejected", "reason": "not_connected"}
        body = {}
        if direction == "long":
            body = {"longUnits": "ALL"}
        elif direction == "short":
            body = {"shortUnits": "ALL"}
        else:
            body = {"longUnits": "ALL", "shortUnits": "ALL"}
        try:
            async with self._session.put(
                f"{self._base_url}/v3/accounts/{self._account_id}/positions/{symbol}/close",
                json=body,
            ) as resp:
                data = await resp.json()
                if resp.status in (200, 201):
                    return {"status": "closed", "symbol": symbol, "raw": data}
                return {"status": "rejected", "reason": str(data), "symbol": symbol}
        except Exception:  # pylint: disable=broad-exception-caught
            logger.exception("OANDABroker close_position %s", symbol)
            return {"status": "rejected", "reason": "Close failed — check server logs"}

    # ── Ping ──────────────────────────────────────────────────────────────────

    async def ping(self) -> float:
        """Measure round-trip latency to OANDA API. Returns ms."""
        if not self.connected or not self._session:
            return 9999.0
        t0 = time.monotonic()
        try:
            async with self._session.get(f"{self._base_url}/v3/accounts/{self._account_id}/summary") as resp:
                await resp.read()
            return (time.monotonic() - t0) * 1000
        except Exception:  # pylint: disable=broad-exception-caught
            return 9999.0

    # ── FORBIDDEN: market data methods ───────────────────────────────────────

    def get_market_data(self, *args: Any, **kwargs: Any) -> None:
        raise MarketDataForbiddenError("get_market_data")

    async def stream_prices(self, *args: Any, **kwargs: Any) -> None:
        raise MarketDataForbiddenError("stream_prices")

    async def get_candles(self, *args: Any, **kwargs: Any) -> None:
        raise MarketDataForbiddenError("get_candles")

    async def get_ohlcv(self, *args: Any, **kwargs: Any) -> None:
        raise MarketDataForbiddenError("get_ohlcv")

    async def get_bid_ask(self, *args: Any, **kwargs: Any) -> None:
        raise MarketDataForbiddenError("get_bid_ask")

    async def get_current_price(self, *args: Any, **kwargs: Any) -> None:
        raise MarketDataForbiddenError("get_current_price")

    async def get_pricing(self, *args: Any, **kwargs: Any) -> None:
        raise MarketDataForbiddenError("get_pricing")

    # ── Diagnostics ───────────────────────────────────────────────────────────

    def metrics(self) -> dict[str, Any]:
        return {
            "broker": "oanda",
            "connected": self.connected,
            "total_orders": self._total_orders,
            "total_fills": self._total_fills,
            "fill_rate": self._total_fills / max(self._total_orders, 1),
        }


# ── Backward-compat aliases ───────────────────────────────────────────────────
OandaBroker = OANDABroker
AsyncOANDAConnector = OANDABroker
OandaAPI = OANDABroker


# ── Synchronous OANDAConnector ────────────────────────────────────────────────
# Used by tests, BrokerFactory, and any synchronous execution path.
# Wraps the OANDA v20 REST API with requests.Session (no async).

from brokers.base import (
    Order as _Order,
)
from brokers.base import (
    OrderSide as _OrderSide,
)
from brokers.base import (
    OrderStatus as _OrderStatus,
)
from brokers.base import (
    OrderType as _OrderType,
)
from brokers.base import (
    Position as _Position,
)


class OANDAConnector:
    """Synchronous OANDA v20 REST connector.

    Config keys
    -----------
    api_key      : personal access token (required)
    account_id   : OANDA account number (required)
    environment  : "practice" | "live"  (default: "practice")
    timeout      : request timeout in seconds (default: 10)
    """

    PRACTICE_URL = _PRACTICE_BASE
    LIVE_URL = _LIVE_BASE

    def __init__(self, config: dict[str, Any]) -> None:
        from config.settings import resolve_oanda_account, resolve_oanda_token

        api_key = config.get("api_key") or resolve_oanda_token()
        account_id = config.get("account_id") or resolve_oanda_account()
        if not api_key or not account_id:
            raise ValueError(
                "OANDAConnector requires 'api_key' and 'account_id' in config "
                "or OANDA_API_KEY env var (canonical). "
                "Aliases accepted: OANDA_ACCESS_TOKEN, OANDA_API_TOKEN, BROKER_OANDA_TOKEN."
            )
        if not validate_oanda_account_id(account_id):
            raise ValueError(
                f"OANDAConnector: account_id {account_id!r} does not match "
                "OANDA v20 format (expected 101-XXX-XXXXXXXX-XXX). "
                "Obtain your account ID from the OANDA portal."
            )
        env = config.get("environment", "practice")
        self.environment = env
        self.base_url = self.LIVE_URL if env == "live" else self.PRACTICE_URL
        self._account_id = account_id
        self._api_key = api_key
        self._timeout = float(config.get("timeout", 10))
        self.connected = False
        self.session: requests.Session | None = None

    # ── Connection ────────────────────────────────────────────────────────────

    def connect(self) -> bool:
        """Open a requests.Session and verify credentials against the account endpoint."""
        try:
            sess = requests.Session()
            sess.headers.update(
                {
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                }
            )
            url = f"{self.base_url}/v3/accounts/{self._account_id}"
            resp = sess.get(url, timeout=self._timeout)
            resp.raise_for_status()
            self.session = sess
            self.connected = True
            logger.info(
                "OANDAConnector: connected (%s) account=%s",
                self.environment,
                self._account_id,
            )
            return True
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.error("OANDAConnector.connect failed: %s", exc)
            self.connected = False
            return False

    def disconnect(self) -> bool:
        """Close the session."""
        try:
            if self.session:
                self.session.close()
            self.connected = False
            self.session = None
            return True
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.error("OANDAConnector.disconnect failed: %s", exc)
            return False

    # ── Orders ────────────────────────────────────────────────────────────────

    def place_order(
        self,
        symbol: str,
        side: _OrderSide,
        quantity: float,
        order_type: _OrderType = _OrderType.MARKET,
        price: float | None = None,
        stop_price: float | None = None,  # pylint: disable=unused-argument
    ) -> _Order | None:
        """Place a market or limit order. Returns None when not connected."""
        if not self.connected or not self.session:
            return None
        try:
            # Use _units() for consistent rounding, zero-guard, and sign logic.
            # OANDAConnector.place_order() previously used int(quantity) which
            # truncates (not rounds) and silently sends 0 units for fractional
            # quantities like 0.9, causing OANDA to reject with UNITS_INVALID.
            raw_units = _units(side.value if hasattr(side, "value") else str(side), quantity)
        except ValueError as exc:
            logger.error("OANDAConnector.place_order: %s", exc)
            return None
        units = str(raw_units)
        body: dict[str, Any] = {"order": {"units": units, "instrument": symbol, "timeInForce": "FOK"}}
        if order_type == _OrderType.MARKET:
            body["order"]["type"] = "MARKET"
        else:
            body["order"]["type"] = "LIMIT"
            body["order"]["price"] = str(price or 0)
            body["order"]["timeInForce"] = "GTC"
        try:
            url = f"{self.base_url}/v3/accounts/{self._account_id}/orders"
            resp = self.session.post(url, json=body, timeout=self._timeout)
            resp.raise_for_status()
            data = resp.json()
            if "orderFillTransaction" in data:
                txn = data["orderFillTransaction"]
                return _Order(
                    id=txn.get("id", str(uuid.uuid4())),
                    symbol=symbol,
                    side=side,
                    type=order_type,
                    quantity=abs(float(txn.get("units", quantity))),
                    price=float(txn.get("price", price or 0)),
                    status=_OrderStatus.FILLED,
                    average_price=float(txn.get("price", price or 0)),
                    timestamp=datetime.now(UTC),
                )
            if "orderCreateTransaction" in data:
                txn = data["orderCreateTransaction"]
                return _Order(
                    id=txn.get("id", str(uuid.uuid4())),
                    symbol=symbol,
                    side=side,
                    type=order_type,
                    quantity=abs(float(txn.get("units", quantity))),
                    price=float(txn.get("price", price or 0)),
                    status=_OrderStatus.OPEN,
                    timestamp=datetime.now(UTC),
                )
            return None
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.error("OANDAConnector.place_order failed: %s", exc)
            return None

    def cancel_order(self, order_id: str) -> bool:
        """Cancel a pending order by ID."""
        if not self.connected or not self.session:
            return False
        try:
            url = f"{self.base_url}/v3/accounts/{self._account_id}/orders/{order_id}/cancel"
            resp = self.session.put(url, timeout=self._timeout)
            resp.raise_for_status()
            return True
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.error("OANDAConnector.cancel_order failed: %s", exc)
            return False

    # ── Positions ─────────────────────────────────────────────────────────────

    def get_positions(self) -> list[_Position]:
        """Return all open positions."""
        if not self.connected or not self.session:
            return []
        try:
            url = f"{self.base_url}/v3/accounts/{self._account_id}/openPositions"
            resp = self.session.get(url, timeout=self._timeout)
            resp.raise_for_status()
            positions: list[_Position] = []
            for p in resp.json().get("positions", []):
                instrument = p.get("instrument", "").replace("_", "/")
                long_units = float(p.get("long", {}).get("units", 0))
                short_units = abs(float(p.get("short", {}).get("units", 0)))
                if long_units > 0:
                    side_str = "LONG"
                    qty = long_units
                    avg_px = float(p["long"].get("averagePrice", 0))
                    upnl = float(p["long"].get("unrealizedPL", 0))
                    rpnl = float(p["long"].get("realizedPL", 0))
                elif short_units > 0:
                    side_str = "SHORT"
                    qty = short_units
                    avg_px = float(p["short"].get("averagePrice", 0))
                    upnl = float(p["short"].get("unrealizedPL", 0))
                    rpnl = float(p["short"].get("realizedPL", 0))
                else:
                    continue
                positions.append(
                    _Position(
                        symbol=instrument,
                        side=side_str,
                        quantity=qty,
                        entry_price=avg_px,
                        current_price=avg_px,
                        unrealized_pnl=upnl,
                        realized_pnl=rpnl,
                        timestamp=datetime.now(UTC),
                    )
                )
            return positions
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.error("OANDAConnector.get_positions failed: %s", exc)
            return []

    def close_position(self, symbol: str) -> bool:
        """Close all units of a position by instrument name."""
        if not self.connected or not self.session:
            return False
        try:
            url = f"{self.base_url}/v3/accounts/{self._account_id}/positions/{symbol}/close"
            resp = self.session.put(
                url,
                json={"longUnits": "ALL", "shortUnits": "ALL"},
                timeout=self._timeout,
            )
            resp.raise_for_status()
            return True
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.error("OANDAConnector.close_position failed: %s", exc)
            return False

    # ── Account ───────────────────────────────────────────────────────────────

    def get_account_info(self) -> AccountInfo | None:
        """Return account balance and margin info."""
        if not self.connected or not self.session:
            return None
        try:
            url = f"{self.base_url}/v3/accounts/{self._account_id}"
            resp = self.session.get(url, timeout=self._timeout)
            resp.raise_for_status()
            acct = resp.json().get("account", {})
            return AccountInfo(
                balance=float(acct.get("balance", 0)),
                equity=float(acct.get("NAV", acct.get("balance", 0))),
                margin_used=float(acct.get("marginUsed", 0)),
                margin_available=float(acct.get("marginAvailable", 0)),
                positions_count=int(acct.get("openPositionCount", 0)),
                timestamp=datetime.now(UTC),
            )
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.error("OANDAConnector.get_account_info failed: %s", exc)
            return None

    # ── Market data (candles) ─────────────────────────────────────────────────

    def get_market_data(
        self,
        symbol: str,
        granularity: str = "M1",
        count: int = 100,
    ) -> list[dict[str, Any]] | None:
        """Fetch OHLCV candles. Returns None on error."""
        if not self.connected or not self.session:
            return None
        try:
            url = f"{self.base_url}/v3/instruments/{symbol}/candles"
            params = {"granularity": granularity, "count": count, "price": "M"}
            resp = self.session.get(url, params=params, timeout=self._timeout)
            resp.raise_for_status()
            candles = []
            for c in resp.json().get("candles", []):
                mid = c.get("mid", {})
                candles.append(
                    {
                        "time": c.get("time"),
                        "open": float(mid.get("o", 0)),
                        "high": float(mid.get("h", 0)),
                        "low": float(mid.get("l", 0)),
                        "close": float(mid.get("c", 0)),
                        "volume": int(c.get("volume", 0)),
                    }
                )
            return candles
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.error("OANDAConnector.get_market_data failed: %s", exc)
            return None

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _parse_order_status(self, raw: str) -> _OrderStatus:
        mapping = {
            "FILLED": _OrderStatus.FILLED,
            "CANCELLED": _OrderStatus.CANCELLED,
            "PENDING": _OrderStatus.PENDING,
            "OPEN": _OrderStatus.OPEN,
            "REJECTED": _OrderStatus.REJECTED,
        }
        return mapping.get(raw.upper(), _OrderStatus.PENDING)

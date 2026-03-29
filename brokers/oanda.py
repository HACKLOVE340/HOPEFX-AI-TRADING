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
MarketDataForbidden to enforce the architectural boundary at runtime.

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
from typing import Any, Dict, List, Optional

import aiohttp

logger = logging.getLogger(__name__)

_PRACTICE_BASE = "https://api-fxpractice.oanda.com"
_LIVE_BASE     = "https://api-fxtrade.oanda.com"
_DEFAULT_TIMEOUT = float(os.getenv("OANDA_TIMEOUT_S", "10"))
_MAX_RETRIES     = int(os.getenv("OANDA_MAX_RETRIES", "3"))
_RETRY_BACKOFF   = float(os.getenv("OANDA_RETRY_BACKOFF_S", "0.5"))


# ── Architectural boundary enforcement ───────────────────────────────────────

class MarketDataForbidden(RuntimeError):
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
class AccountInfo:
    account_id:        str
    currency:          str
    balance:           float
    nav:               float
    unrealized_pnl:    float
    margin_used:       float
    margin_available:  float
    positions_count:   int
    timestamp:         datetime


@dataclass
class OrderResult:
    order_id:      str
    client_ref:    str
    status:        str        # "filled" | "pending" | "rejected" | "cancelled"
    fill_price:    float
    quantity:      float
    direction:     str
    symbol:        str
    broker:        str = "oanda"
    latency_ms:    float = 0.0
    reject_reason: str = ""
    raw:           Optional[Dict] = None


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
    """OANDA uses signed units: positive = buy, negative = sell."""
    qty = abs(quantity)
    return int(qty) if direction.lower() in ("long", "buy") else -int(qty)


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

    def __init__(self, config: Dict) -> None:
        self._account_id = _resolve_env(config.get("login", os.getenv("OANDA_ACCOUNT_ID", "")))
        self._token      = _resolve_env(config.get("password", os.getenv("OANDA_API_TOKEN", "")))
        server           = _resolve_env(config.get("server", os.getenv("OANDA_ENVIRONMENT", "practice")))
        self._base_url   = _LIVE_BASE if server == "live" else _PRACTICE_BASE
        self._timeout    = float(config.get("timeout_seconds", _DEFAULT_TIMEOUT))
        self._session:   Optional[aiohttp.ClientSession] = None
        self.connected:  bool = False
        self._total_orders: int = 0
        self._total_fills:  int = 0

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def connect(self) -> bool:
        if self.connected:
            return True
        if not self._account_id or not self._token:
            logger.error("OANDABroker: missing OANDA_ACCOUNT_ID or OANDA_API_TOKEN")
            return False
        headers = {
            "Authorization":  f"Bearer {self._token}",
            "Content-Type":   "application/json",
            "Accept-Datetime-Format": "RFC3339",
        }
        timeout = aiohttp.ClientTimeout(total=self._timeout)
        self._session = aiohttp.ClientSession(headers=headers, timeout=timeout)
        try:
            async with self._session.get(
                f"{self._base_url}/v3/accounts/{self._account_id}"
            ) as resp:
                resp.raise_for_status()
            self.connected = True
            logger.info("OANDABroker: connected to %s account=%s", self._base_url, self._account_id)
            return True
        except Exception as exc:
            logger.error("OANDABroker: connect failed: %s", exc)
            await self._session.close()
            self._session = None
            return False

    async def disconnect(self) -> None:
        if self._session:
            await self._session.close()
            self._session = None
        self.connected = False
        logger.info("OANDABroker: disconnected")

    # ── Account info ──────────────────────────────────────────────────────────

    async def get_account_info(self) -> Optional[AccountInfo]:
        """Query account balance, NAV, margin. Does NOT return price data."""
        if not self.connected or not self._session:
            return None
        try:
            async with self._session.get(
                f"{self._base_url}/v3/accounts/{self._account_id}/summary"
            ) as resp:
                resp.raise_for_status()
                data = await resp.json()
            a = data.get("account", {})
            nav = float(a.get("NAV", a.get("balance", 0)))
            return AccountInfo(
                account_id       = self._account_id,
                currency         = a.get("currency", "USD"),
                balance          = float(a.get("balance", 0)),
                nav              = nav,
                unrealized_pnl   = float(a.get("unrealizedPL", 0)),
                margin_used      = float(a.get("marginUsed", 0)),
                margin_available = float(a.get("marginAvailable", nav)),
                positions_count  = int(a.get("openPositionCount", a.get("openTradeCount", 0))),
                timestamp        = datetime.now(timezone.utc),
            )
        except Exception as exc:
            logger.error("OANDABroker get_account_info: %s", exc)
            return None

    # ── Order placement ───────────────────────────────────────────────────────

    async def place_order(self, order_request: Dict) -> Dict:
        """
        Place a market or limit order.

        order_request keys (from SmartRouter / HopeFXEngine):
          symbol, direction, quantity, order_type, mid_price (for limit),
          order_id (client ref), signal_id

        Returns dict with: status, fill_price, quantity, broker, latency_ms
        """
        if not self.connected or not self._session:
            return {"status": "rejected", "reason": "not_connected", "broker": "oanda"}

        t0         = time.monotonic()
        symbol     = order_request.get("symbol", "XAU_USD")
        direction  = order_request.get("direction", "long")
        quantity   = float(order_request.get("quantity", 0))
        order_type = order_request.get("order_type", "MARKET").upper()
        client_ref = order_request.get("order_id", str(uuid.uuid4()))

        if quantity <= 0:
            return {"status": "rejected", "reason": "zero_quantity", "broker": "oanda"}

        units = _units(direction, quantity)

        # Build OANDA order body
        order_body: Dict[str, Any] = {
            "type":        order_type,
            "instrument":  symbol,
            "units":       str(units),
            "timeInForce": "FOK" if order_type == "MARKET" else "GTC",
            "clientExtensions": {
                "id":      client_ref[:32],
                "comment": f"hopefx:{order_request.get('signal_id', '')[:16]}",
            },
        }

        if order_type == "LIMIT":
            price = order_request.get("mid_price")
            if price:
                order_body["price"] = f"{float(price):.5f}"

        payload = {"order": order_body}

        self._total_orders += 1
        result = await self._post_order_with_retry(payload, client_ref)
        result["latency_ms"] = round((time.monotonic() - t0) * 1000, 2)

        if result.get("status") == "filled":
            self._total_fills += 1

        return result

    async def _post_order_with_retry(self, payload: Dict, client_ref: str) -> Dict:
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
                    error_msg  = data.get("errorMessage", str(data))
                    logger.warning(
                        "OANDABroker: order rejected (attempt %d/%d) code=%s msg=%s",
                        attempt, _MAX_RETRIES, error_code, error_msg,
                    )
                    last_error = f"{error_code}:{error_msg}"

                    # Non-retryable rejections
                    if error_code in ("INSUFFICIENT_MARGIN", "ACCOUNT_NOT_TRADEABLE",
                                      "INSTRUMENT_NOT_TRADEABLE", "UNITS_LIMIT_EXCEEDED"):
                        return {"status": "rejected", "reason": last_error, "broker": "oanda"}

            except asyncio.TimeoutError:
                last_error = "timeout"
                logger.warning("OANDABroker: order timeout (attempt %d/%d)", attempt, _MAX_RETRIES)
            except Exception as exc:
                last_error = str(exc)
                logger.error("OANDABroker: order error (attempt %d/%d): %s", attempt, _MAX_RETRIES, exc)

            if attempt < _MAX_RETRIES:
                await asyncio.sleep(_RETRY_BACKOFF * attempt)

        return {"status": "rejected", "reason": f"max_retries:{last_error}", "broker": "oanda"}

    @staticmethod
    def _parse_fill(data: Dict, client_ref: str) -> Dict:
        """Parse OANDA order response into canonical fill dict."""
        # Market order fill
        fill = data.get("orderFillTransaction", {})
        if fill:
            price = float(fill.get("price", fill.get("tradeOpened", {}).get("price", 0)))
            units = abs(int(fill.get("units", 0)))
            direction = "long" if int(fill.get("units", 0)) > 0 else "short"
            return {
                "status":     "filled",
                "fill_price": price,
                "quantity":   units,
                "direction":  direction,
                "order_id":   fill.get("orderID", ""),
                "trade_id":   fill.get("tradeOpened", {}).get("tradeID", ""),
                "client_ref": client_ref,
                "broker":     "oanda",
                "raw":        data,
            }

        # Limit order created (pending)
        created = data.get("orderCreateTransaction", {})
        if created:
            return {
                "status":   "pending",
                "order_id": created.get("orderID", ""),
                "broker":   "oanda",
                "raw":      data,
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
        except Exception as exc:
            logger.error("OANDABroker cancel_order %s: %s", order_id, exc)
            return False

    # ── Position queries ──────────────────────────────────────────────────────

    async def get_open_positions(self) -> List[Dict]:
        """Return open positions. Does NOT return price data."""
        if not self.connected or not self._session:
            return []
        try:
            async with self._session.get(
                f"{self._base_url}/v3/accounts/{self._account_id}/openPositions"
            ) as resp:
                resp.raise_for_status()
                data = await resp.json()
            positions = []
            for p in data.get("positions", []):
                long_units  = int(p.get("long",  {}).get("units", 0))
                short_units = int(p.get("short", {}).get("units", 0))
                if long_units != 0 or short_units != 0:
                    positions.append({
                        "symbol":      p.get("instrument"),
                        "long_units":  long_units,
                        "short_units": short_units,
                        "unrealized_pnl": float(p.get("unrealizedPL", 0)),
                    })
            return positions
        except Exception as exc:
            logger.error("OANDABroker get_open_positions: %s", exc)
            return []

    async def close_position(self, symbol: str, direction: str = "all") -> Dict:
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
        except Exception as exc:
            logger.error("OANDABroker close_position %s: %s", symbol, exc)
            return {"status": "rejected", "reason": str(exc)}

    # ── Ping ──────────────────────────────────────────────────────────────────

    async def ping(self) -> float:
        """Measure round-trip latency to OANDA API. Returns ms."""
        if not self.connected or not self._session:
            return 9999.0
        t0 = time.monotonic()
        try:
            async with self._session.get(
                f"{self._base_url}/v3/accounts/{self._account_id}/summary"
            ) as resp:
                await resp.read()
            return (time.monotonic() - t0) * 1000
        except Exception:
            return 9999.0

    # ── FORBIDDEN: market data methods ───────────────────────────────────────

    def get_market_data(self, *args, **kwargs):
        raise MarketDataForbidden("get_market_data")

    async def stream_prices(self, *args, **kwargs):
        raise MarketDataForbidden("stream_prices")

    async def get_candles(self, *args, **kwargs):
        raise MarketDataForbidden("get_candles")

    async def get_ohlcv(self, *args, **kwargs):
        raise MarketDataForbidden("get_ohlcv")

    async def get_bid_ask(self, *args, **kwargs):
        raise MarketDataForbidden("get_bid_ask")

    async def get_current_price(self, *args, **kwargs):
        raise MarketDataForbidden("get_current_price")

    async def get_pricing(self, *args, **kwargs):
        raise MarketDataForbidden("get_pricing")

    # ── Diagnostics ───────────────────────────────────────────────────────────

    def metrics(self) -> Dict[str, Any]:
        return {
            "broker":        "oanda",
            "connected":     self.connected,
            "total_orders":  self._total_orders,
            "total_fills":   self._total_fills,
            "fill_rate":     self._total_fills / max(self._total_orders, 1),
        }


# ── Backward-compat aliases ───────────────────────────────────────────────────
OandaBroker      = OANDABroker
AsyncOANDAConnector = OANDABroker
OandaAPI         = OANDABroker

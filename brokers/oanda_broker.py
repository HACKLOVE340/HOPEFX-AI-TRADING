# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
OandaBroker — yaml-config-driven OANDA v20 REST broker implementation.

Credential mapping (matches config/brokers.yaml):
    login    → OANDA account number  (e.g. "101-123-4567890-001")
    password → OANDA personal access token (Bearer token)
    server   → "practice" (demo) | "live"

All network calls are async via aiohttp.  The session is created on connect()
and closed on disconnect().

Usage
-----
    broker = OandaBroker(config)
    await broker.connect()
    info = await broker.get_account_info()
    result = await broker.place_order({
        "instrument": "XAU_USD",
        "units": 100,          # positive = buy, negative = sell
        "order_type": "MARKET",
    })
    await broker.disconnect()
"""

import asyncio
import logging
import os
import uuid as _uuid_mod
from typing import Any

import aiohttp

from brokers.base import BrokerConnector, Order, OrderSide, OrderType, Position, AccountInfo

logger = logging.getLogger(__name__)

_PRACTICE_BASE = "https://api-fxpractice.oanda.com"
_LIVE_BASE = "https://api-fxtrade.oanda.com"

# Default request timeout (seconds).
_DEFAULT_TIMEOUT = 10

# Retry configuration for transient network errors and rate-limits.
# Max retries (not counting the initial attempt).
_MAX_RETRIES = 3
# Base delay in seconds for the first retry; doubles on each subsequent attempt.
_RETRY_BASE_DELAY = 0.5
# HTTP status codes that are safe to retry (transient failures).
_RETRYABLE_STATUSES = {429, 500, 502, 503, 504}


def _resolve_env(value: object) -> str:
    """Expand ``${ENV_VAR:default}`` placeholders."""
    if not isinstance(value, str):
        return str(value) if value is not None else ""
    if value.startswith("${") and value.endswith("}"):
        inner = value[2:-1]
        var, _, default = inner.partition(":")
        return os.environ.get(var, default)
    return value


def _mask_account(account_id: str | None) -> str:
    """Return a masked account ID showing only the last 4 characters."""
    if not account_id:
        return "****"
    return ("..." + account_id[-4:]) if len(account_id) > 4 else "****"


class OandaBroker(BrokerConnector):
    """
    Async OANDA v20 REST broker.

    Parameters
    ----------
    config:
        Dict with keys ``login`` (account ID), ``password`` (API token),
        ``server`` ("practice" | "live").
        Optional: ``timeout_seconds`` (int, default 10).
    """

    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__(config)
        self._config = config
        self._session: aiohttp.ClientSession | None = None
        self._account_id: str | None = None
        self._token: str | None = None
        self._base_url: str | None = None

    # ── Lifecycle ──────────────────────────────────────────────────────────────

    async def connect(self) -> bool:
        """
        Open the aiohttp session and verify the account is reachable.

        Returns True on success, False on any failure.
        """
        self._account_id = _resolve_env(self._config.get("login", ""))
        self._token = _resolve_env(self._config.get("password", ""))
        server = _resolve_env(self._config.get("server", "practice"))
        timeout_s = int(self._config.get("timeout_seconds", _DEFAULT_TIMEOUT))

        if not self._account_id or self._account_id.startswith("101-123"):
            logger.warning(
                "OandaBroker: account_id appears to be a placeholder ('%s'). "
                "Set OANDA_ACCOUNT_ID env var or update config/brokers.yaml.",
                _mask_account(self._account_id),
            )

        self._base_url = _PRACTICE_BASE if "practice" in server.lower() else _LIVE_BASE

        self._session = aiohttp.ClientSession(
            headers={
                "Authorization": f"Bearer {self._token}",
                "Content-Type": "application/json",
            },
            timeout=aiohttp.ClientTimeout(total=timeout_s),
        )

        try:
            async with self._session.get(f"{self._base_url}/v3/accounts/{self._account_id}") as resp:
                if resp.status == 200:
                    data = await resp.json()
                    currency = data.get("account", {}).get("currency", "?")
                    self.connected = True
                    # Balance is financial data — log currency only, not the amount.
                    logger.info(
                        "OandaBroker connected | account=%s | server=%s | currency=%s",
                        _mask_account(self._account_id),
                        server,
                        currency,
                    )
                    return True
                # Truncate error body to avoid leaking token details from OANDA
                # error responses (e.g. "Invalid access token" messages that echo
                # back request metadata).
                _raw_body = await resp.text()
                _safe_body = _raw_body[:120] if len(_raw_body) > 120 else _raw_body
                logger.error(
                    "OandaBroker connect failed | status=%s | error=%s",
                    resp.status,
                    _safe_body,
                )
                await self._session.close()
                return False
        except aiohttp.ClientError as exc:
            logger.error("OandaBroker connect error: %s", type(exc).__name__)
            await self._session.close()
            return False

    async def disconnect(self) -> bool:
        """Close the aiohttp session."""
        if self._session and not self._session.closed:
            await self._session.close()
        self.connected = False
        logger.info("OandaBroker disconnected (account=%s)", _mask_account(self._account_id))
        return True

    # ── Account ───────────────────────────────────────────────────────────────

    async def get_account_info(self) -> dict[str, Any] | None:
        """Return account summary as a plain dict."""
        if not self._assert_connected("get_account_info") or self._session is None:
            return None
        async with self._session.get(f"{self._base_url}/v3/accounts/{self._account_id}/summary") as resp:
            if resp.status != 200:
                logger.error("get_account_info failed: %s", resp.status)
                return None
            data = await resp.json()
            acct = data.get("account", {})
            return {
                "account_id": acct.get("id"),
                "currency": acct.get("currency"),
                "balance": float(acct.get("balance", 0)),
                "nav": float(acct.get("NAV", 0)),
                "unrealized_pl": float(acct.get("unrealizedPL", 0)),
                "realized_pl": float(acct.get("pl", 0)),
                "margin_used": float(acct.get("marginUsed", 0)),
                "margin_available": float(acct.get("marginAvailable", 0)),
                "open_trade_count": acct.get("openTradeCount", 0),
                "open_position_count": acct.get("openPositionCount", 0),
                "leverage": acct.get("marginRate"),
            }

    async def get_positions(self) -> list[dict[str, Any]]:
        """Return all open positions."""
        if not self._assert_connected("get_positions") or self._session is None:
            return []
        async with self._session.get(f"{self._base_url}/v3/accounts/{self._account_id}/openPositions") as resp:
            if resp.status != 200:
                return []
            data = await resp.json()
            positions = []
            for p in data.get("positions", []):
                long_units = float(p.get("long", {}).get("units", 0))
                short_units = float(p.get("short", {}).get("units", 0))
                positions.append(
                    {
                        "instrument": p.get("instrument"),
                        "long_units": long_units,
                        "short_units": short_units,
                        "net_units": long_units + short_units,
                        "unrealized_pl": float(p.get("unrealizedPL", 0)),
                        "pl": float(p.get("pl", 0)),
                    }
                )
            return positions

    async def get_orders(self) -> list[dict[str, Any]]:
        """Return all pending orders."""
        if not self._assert_connected("get_orders") or self._session is None:
            return []
        async with self._session.get(f"{self._base_url}/v3/accounts/{self._account_id}/pendingOrders") as resp:
            if resp.status != 200:
                return []
            data = await resp.json()
            return [
                {
                    "id": o.get("id"),
                    "type": o.get("type"),
                    "instrument": o.get("instrument"),
                    "units": o.get("units"),
                    "price": o.get("price"),
                    "state": o.get("state"),
                    "time_in_force": o.get("timeInForce"),
                }
                for o in data.get("orders", [])
            ]

    # ── Order execution ───────────────────────────────────────────────────────

    async def place_order(self, order_params: dict[str, Any]) -> dict[str, Any]:
        """
        Place a trade order via the OANDA v20 Orders endpoint.

        Parameters
        ----------
        order_params:
            instrument  (str)   — e.g. "XAU_USD"
            units       (float) — positive = buy, negative = sell
            order_type  (str)   — "MARKET" (default) | "LIMIT" | "STOP"
            price       (float) — required for LIMIT/STOP orders
            sl_distance (float) — stop-loss distance in price units (optional)
            tp_price    (float) — take-profit price (optional)
            time_in_force (str) — "FOK" (default for MARKET) | "GTC" | "GFD"
            client_id   (str)   — optional client order ID (used as idempotency key)

        Returns
        -------
        Dict with keys: ``success`` (bool), ``order_id`` (str), ``trade_id`` (str),
        ``fill_price`` (float), ``comment`` (str).

        Retry behaviour
        ---------------
        Transient network errors (aiohttp.ClientError) and server-side failures
        (HTTP 500/502/503/504) are retried up to _MAX_RETRIES times with
        exponential backoff.  HTTP 429 (rate-limit) respects the Retry-After
        header when present.  Non-retryable failures (400, 401, 403, 404) are
        returned immediately.

        Idempotency
        -----------
        A UUID idempotency key is generated for every order (or taken from
        ``client_id``) and sent as the OANDA clientExtensions ID.  This
        prevents duplicate fills when the network fails after submission but
        before a response is received.
        """
        if not self._assert_connected("place_order") or self._session is None:
            return {"success": False, "order_id": None, "comment": "Not connected"}

        instrument = order_params.get("instrument", "XAU_USD")
        units = str(order_params.get("units", 0))
        order_type = order_params.get("order_type", "MARKET").upper()
        price = order_params.get("price")
        sl_distance = order_params.get("sl_distance")
        tp_price = order_params.get("tp_price")
        time_in_force = order_params.get("time_in_force", "FOK" if order_type == "MARKET" else "GTC")
        # Generate a stable idempotency key for this order attempt.
        client_id = order_params.get("client_id") or str(_uuid_mod.uuid4())

        order_body: dict[str, Any] = {
            "type": order_type,
            "instrument": instrument,
            "units": units,
            "timeInForce": time_in_force,
        }

        if order_type in ("LIMIT", "STOP") and price is not None:
            order_body["price"] = str(price)

        if sl_distance is not None:
            order_body["stopLossOnFill"] = {
                "distance": str(sl_distance),
                "timeInForce": "GTC",
            }

        if tp_price is not None:
            order_body["takeProfitOnFill"] = {
                "price": str(tp_price),
                "timeInForce": "GTC",
            }

        # Always attach the idempotency key so OANDA deduplicates on retry.
        # Truncate to 128 chars for OANDA API limits (UUIDs are 36 chars so this is safe).
        # Log a warning if a custom ID is unusually long to alert operators.
        if len(client_id) > 128:
            logger.warning(
                "OANDA client_id length %d exceeds 128-char limit — truncating. "
                "Provide shorter IDs to avoid potential collision risk.",
                len(client_id),
            )
        order_body["clientExtensions"] = {"id": client_id[:128]}

        payload = {"order": order_body}
        url = f"{self._base_url}/v3/accounts/{self._account_id}/orders"

        last_error: str = "Unknown error"
        for attempt in range(_MAX_RETRIES + 1):
            try:
                async with self._session.post(url, json=payload) as resp:
                    # Non-retryable client errors — return immediately.
                    if resp.status in (400, 401, 403, 404):
                        data = await resp.json()
                        error_msg = data.get("errorMessage", str(data))
                        logger.warning(
                            "OANDA order rejected (non-retryable) | status=%s | error=%s | instrument=%s",
                            resp.status,
                            error_msg,
                            instrument,
                        )
                        return {"success": False, "order_id": None, "comment": error_msg}

                    if resp.status == 429:
                        # Rate-limited — honour Retry-After if present, with a safe fallback.
                        default_delay = min(_RETRY_BASE_DELAY * (2**attempt), 30.0)
                        try:
                            retry_after = float(resp.headers.get("Retry-After", default_delay))
                        except (ValueError, TypeError):
                            retry_after = default_delay
                        logger.warning(
                            "OANDA rate-limited (429) | retry_after=%.1fs | attempt=%d/%d",
                            retry_after,
                            attempt + 1,
                            _MAX_RETRIES + 1,
                        )
                        if attempt < _MAX_RETRIES:
                            await asyncio.sleep(retry_after)
                            continue
                        return {"success": False, "order_id": None, "comment": "Rate limited — max retries exceeded"}

                    if resp.status in (500, 502, 503, 504):
                        last_error = f"HTTP {resp.status}"
                        if attempt < _MAX_RETRIES:
                            delay = _RETRY_BASE_DELAY * (2**attempt)
                            logger.warning(
                                "OANDA server error %s | retrying in %.1fs | attempt=%d/%d",
                                resp.status,
                                delay,
                                attempt + 1,
                                _MAX_RETRIES + 1,
                            )
                            await asyncio.sleep(delay)
                            continue
                        return {"success": False, "order_id": None, "comment": last_error}

                    data = await resp.json()
                    if resp.status in (200, 201):
                        fill = data.get("orderFillTransaction", {})
                        created = data.get("orderCreateTransaction", {})
                        order_id = fill.get("orderID") or created.get("id")
                        trade_id = fill.get("tradeOpened", {}).get("tradeID")
                        fill_price = fill.get("price")
                        logger.info(
                            "OANDA order placed | instrument=%s | units=%s | order_id=%s | trade_id=%s | attempt=%d",
                            instrument,
                            units,
                            order_id,
                            trade_id,
                            attempt + 1,
                        )
                        return {
                            "success": True,
                            "order_id": order_id,
                            "trade_id": trade_id,
                            "fill_price": float(fill_price) if fill_price else None,
                            "comment": "OK",
                            "idempotency_key": client_id,
                        }
                    error_msg = data.get("errorMessage", str(data))
                    logger.warning(
                        "OANDA order failed | status=%s | error=%s | instrument=%s",
                        resp.status,
                        error_msg,
                        instrument,
                    )
                    return {"success": False, "order_id": None, "comment": error_msg}

            except aiohttp.ServerTimeoutError as exc:
                # ServerTimeoutError ⊂ ClientConnectionError — must come first.
                last_error = f"Timeout: {exc}"
                if attempt < _MAX_RETRIES:
                    delay = _RETRY_BASE_DELAY * (2**attempt)
                    logger.warning(
                        "OANDA timeout | retrying in %.1fs | attempt=%d/%d",
                        delay,
                        attempt + 1,
                        _MAX_RETRIES + 1,
                    )
                    await asyncio.sleep(delay)
                    continue
                logger.error("OandaBroker.place_order: timed out after %d attempts", _MAX_RETRIES + 1)
                return {"success": False, "order_id": None, "comment": last_error}
            except aiohttp.ClientConnectionError as exc:
                last_error = f"Connection error: {exc}"
                if attempt < _MAX_RETRIES:
                    delay = _RETRY_BASE_DELAY * (2**attempt)
                    logger.warning(
                        "OANDA connection error | retrying in %.1fs | attempt=%d/%d | error=%s",
                        delay,
                        attempt + 1,
                        _MAX_RETRIES + 1,
                        type(exc).__name__,
                    )
                    await asyncio.sleep(delay)
                    continue
                logger.error("OandaBroker.place_order: connection failed after %d attempts", _MAX_RETRIES + 1)
                return {"success": False, "order_id": None, "comment": last_error}
            except aiohttp.ClientError as exc:
                logger.exception("OandaBroker.place_order: non-retryable client error: %s", type(exc).__name__)
                return {"success": False, "order_id": None, "comment": f"Network error: {type(exc).__name__}"}

        return {"success": False, "order_id": None, "comment": last_error}

    async def close_trade(self, trade_id: str, units: str | None = "ALL") -> dict[str, Any]:
        """
        Close an open trade (full or partial) with exponential-backoff retry.

        Parameters
        ----------
        trade_id: OANDA trade ID string.
        units: "ALL" for full close, or a numeric string for partial close.
        """
        if not self._assert_connected("close_trade") or self._session is None:
            return {"success": False, "comment": "Not connected"}
        payload = {"units": units}
        url = f"{self._base_url}/v3/accounts/{self._account_id}/trades/{trade_id}/close"

        last_error = "Unknown error"
        for attempt in range(_MAX_RETRIES + 1):
            try:
                async with self._session.put(url, json=payload) as resp:
                    if resp.status in (400, 401, 403, 404):
                        data = await resp.json()
                        return {"success": False, "comment": data.get("errorMessage", "Close rejected")}
                    if resp.status in _RETRYABLE_STATUSES and attempt < _MAX_RETRIES:
                        default_delay = min(_RETRY_BASE_DELAY * (2**attempt), 30.0)
                        if resp.status == 429:
                            try:
                                delay = float(resp.headers.get("Retry-After", default_delay))
                            except (ValueError, TypeError):
                                delay = default_delay
                        else:
                            delay = default_delay
                        logger.warning(
                            "OANDA close_trade %s | retrying in %.1fs | attempt=%d/%d",
                            resp.status,
                            delay,
                            attempt + 1,
                            _MAX_RETRIES + 1,
                        )
                        await asyncio.sleep(delay)
                        continue
                    data = await resp.json()
                    if resp.status == 200:
                        logger.info("OANDA trade closed | trade_id=%s | units=%s", trade_id, units)
                        return {"success": True, "comment": "OK", "data": data}
                    error_msg = data.get("errorMessage", "Close rejected")
                    return {"success": False, "comment": error_msg}
            except aiohttp.ClientConnectionError as exc:
                last_error = f"Connection error: {exc}"
                if attempt < _MAX_RETRIES:
                    await asyncio.sleep(_RETRY_BASE_DELAY * (2**attempt))
                    continue
                logger.error("OandaBroker.close_trade: connection failed: %s", exc)
                return {"success": False, "comment": last_error}
            except aiohttp.ClientError as exc:
                logger.exception("OandaBroker.close_trade: network error: %s", exc)
                return {"success": False, "comment": f"Network error: {exc}"}

        return {"success": False, "comment": last_error}

    async def cancel_order(self, order_id: str) -> dict[str, Any]:
        """Cancel a pending order by ID with exponential-backoff retry."""
        if not self._assert_connected("cancel_order") or self._session is None:
            return {"success": False, "comment": "Not connected"}
        url = f"{self._base_url}/v3/accounts/{self._account_id}/orders/{order_id}/cancel"

        last_error = "Unknown error"
        for attempt in range(_MAX_RETRIES + 1):
            try:
                async with self._session.put(url) as resp:
                    if resp.status in (400, 401, 403, 404):
                        data = await resp.json()
                        return {"success": False, "comment": data.get("errorMessage", "Cancel rejected")}
                    if resp.status in _RETRYABLE_STATUSES and attempt < _MAX_RETRIES:
                        default_delay = min(_RETRY_BASE_DELAY * (2**attempt), 30.0)
                        if resp.status == 429:
                            try:
                                delay = float(resp.headers.get("Retry-After", default_delay))
                            except (ValueError, TypeError):
                                delay = default_delay
                        else:
                            delay = default_delay
                        await asyncio.sleep(delay)
                        continue
                    if resp.status == 200:
                        logger.info("OANDA order cancelled | order_id=%s", order_id)
                        return {"success": True, "comment": "OK"}
                    data = await resp.json()
                    return {"success": False, "comment": data.get("errorMessage", "Cancel rejected")}
            except aiohttp.ClientConnectionError as exc:
                last_error = f"Connection error: {exc}"
                if attempt < _MAX_RETRIES:
                    await asyncio.sleep(_RETRY_BASE_DELAY * (2**attempt))
                    continue
                logger.error("OandaBroker.cancel_order: connection failed: %s", exc)
                return {"success": False, "comment": last_error}
            except aiohttp.ClientError as exc:
                logger.exception("OandaBroker.cancel_order: network error: %s", exc)
                return {"success": False, "comment": f"Network error: {exc}"}

        return {"success": False, "comment": last_error}

    async def cancel_all_orders(self) -> list[str]:
        """
        Cancel all pending orders and close all open positions.

        Called by the kill switch on activation. Uses OANDA's bulk
        position-close endpoint (PUT /positions/{instrument}/close) for
        each open position, then cancels all pending orders individually.
        Returns list of successfully closed/cancelled IDs.
        """
        cancelled: list[str] = []
        if not self._assert_connected("cancel_all_orders") or self._session is None:
            return cancelled

        session = self._session  # narrowed — not None past this point

        # 1. Close all open positions
        try:
            positions = await self.get_positions()
            for pos in positions:
                instrument = pos.get("instrument")
                if not instrument:
                    continue
                long_units = pos.get("long_units", 0)
                short_units = pos.get("short_units", 0)
                body: dict[str, Any] = {}
                if long_units > 0:
                    body["longUnits"] = "ALL"
                if short_units < 0:
                    body["shortUnits"] = "ALL"
                if not body:
                    continue
                url = f"{self._base_url}/v3/accounts/{self._account_id}/positions/{instrument}/close"
                try:
                    async with session.put(url, json=body) as resp:
                        if resp.status == 200:
                            cancelled.append(instrument)
                            logger.warning("OandaBroker.cancel_all_orders: closed position %s", instrument)
                        else:
                            data = await resp.json()
                            logger.error(
                                "OandaBroker.cancel_all_orders: close %s failed (%s): %s",
                                instrument,
                                resp.status,
                                data.get("errorMessage", ""),
                            )
                except Exception as exc:
                    logger.error("OandaBroker.cancel_all_orders: close %s raised: %s", instrument, exc)
        except Exception as exc:
            logger.error("OandaBroker.cancel_all_orders: get_positions failed: %s", exc)

        # 2. Cancel all pending orders
        try:
            orders = await self.get_orders()
            for order in orders:
                order_id = order.get("id")
                if not order_id:
                    continue
                result = await self.cancel_order(order_id)
                if result.get("success"):
                    cancelled.append(str(order_id))
                else:
                    logger.warning(
                        "OandaBroker.cancel_all_orders: cancel order %s failed: %s",
                        order_id,
                        result.get("comment"),
                    )
        except Exception as exc:
            logger.error("OandaBroker.cancel_all_orders: cancel orders failed: %s", exc)

        logger.warning("OandaBroker.cancel_all_orders: complete (cancelled=%d)", len(cancelled))
        return cancelled

    async def get_tick(self, instrument: str = "XAU_USD") -> dict[str, Any] | None:
        """Return the latest bid/ask for *instrument*."""
        if not self._assert_connected("get_tick") or self._session is None:
            return None
        try:
            async with self._session.get(
                f"{self._base_url}/v3/accounts/{self._account_id}/pricing",
                params={"instruments": instrument},
            ) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json()
                prices = data.get("prices", [])
                if not prices:
                    return None
                p = prices[0]
                bids = p.get("bids", [{}])
                asks = p.get("asks", [{}])
                bid = float(bids[0].get("price", 0)) if bids else 0.0
                ask = float(asks[0].get("price", 0)) if asks else 0.0
                return {
                    "instrument": instrument,
                    "bid": bid,
                    "ask": ask,
                    "mid": (bid + ask) / 2.0,
                    "tradeable": p.get("tradeable", False),
                }
        except aiohttp.ClientError as exc:
            logger.error("OandaBroker.get_tick error: %s", exc)
            return None

    # ── Helpers ───────────────────────────────────────────────────────────────

    async def get_ohlcv_candles(
        self,
        instrument: str = "XAU_USD",
        granularity: str = "H1",
        count: int = 500,
        from_time: str | None = None,
        to_time: str | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch OHLCV candles from OANDA v3 instruments endpoint.

        Parameters
        ----------
        instrument  : OANDA instrument name (e.g. ``"XAU_USD"``).
        granularity : Candle granularity.  Common values: ``"M1"``, ``"H1"``,
                      ``"H4"``, ``"D"``.
        count       : Number of candles to fetch (max 5000 per request).
                      Ignored when both ``from_time`` and ``to_time`` are set.
        from_time   : RFC-3339 / ISO-8601 start time (inclusive).
        to_time     : RFC-3339 / ISO-8601 end time (exclusive).

        Returns
        -------
        list of dicts with keys ``time``, ``open``, ``high``, ``low``,
        ``close``, ``volume``.  Returns an empty list on any error.
        """
        if not self._assert_connected("get_ohlcv_candles") or self._session is None:
            return []

        params: dict[str, Any] = {
            "granularity": granularity,
            "price": "M",  # midpoint candles
        }
        if from_time and to_time:
            params["from"] = from_time
            params["to"] = to_time
        elif from_time:
            params["from"] = from_time
            params["count"] = str(count)
        else:
            params["count"] = str(count)

        url = f"{self._base_url}/v3/instruments/{instrument}/candles"
        try:
            async with self._session.get(url, params=params) as resp:
                if resp.status != 200:
                    body = await resp.text()
                    logger.error(
                        "OandaBroker.get_ohlcv_candles: status=%s body=%s",
                        resp.status,
                        body[:200],
                    )
                    return []
                data = await resp.json()
        except aiohttp.ClientError as exc:
            logger.error("OandaBroker.get_ohlcv_candles network error: %s", exc)
            return []

        candles = []
        for c in data.get("candles", []):
            if not c.get("complete", True):
                continue  # skip the still-forming candle
            mid = c.get("mid", {})
            try:
                candles.append(
                    {
                        "time": c["time"],
                        "open": float(mid["o"]),
                        "high": float(mid["h"]),
                        "low": float(mid["l"]),
                        "close": float(mid["c"]),
                        "volume": int(c.get("volume", 0)),
                    }
                )
            except (KeyError, ValueError, TypeError) as exc:
                logger.debug("OandaBroker.get_ohlcv_candles: skipping malformed candle: %s", exc)
        return candles

    # ── BrokerConnector ABC implementations ───────────────────────────────────

    async def get_order(self, order_id: str) -> Order | None:
        """Fetch a single pending order by ID from OANDA."""
        if not self._assert_connected("get_order") or self._session is None:
            return None
        url = f"{self._base_url}/v3/accounts/{self._account_id}/orders/{order_id}"
        try:
            async with self._session.get(url) as resp:
                if resp.status == 404:
                    return None
                if resp.status != 200:
                    logger.warning("OandaBroker.get_order: status=%s", resp.status)
                    return None
                data = await resp.json()
                o = data.get("order", {})
                return Order(
                    id=str(o.get("id", order_id)),
                    symbol=o.get("instrument", ""),
                    side=OrderSide.BUY if float(o.get("units", 0)) > 0 else OrderSide.SELL,
                    type=OrderType.MARKET,
                    quantity=abs(float(o.get("units", 0))),
                    status=o.get("state", "PENDING"),
                )
        except aiohttp.ClientError as exc:
            logger.error("OandaBroker.get_order error: %s", exc)
            return None

    async def close_position(self, symbol: str) -> bool:
        """Close the full open position for *symbol* (instrument name)."""
        if not self._assert_connected("close_position") or self._session is None:
            return False
        # OANDA uses underscore-separated instrument names (e.g. XAU_USD)
        instrument = symbol.replace("/", "_").upper()
        url = f"{self._base_url}/v3/accounts/{self._account_id}/positions/{instrument}/close"
        body: dict[str, Any] = {"longUnits": "ALL", "shortUnits": "ALL"}
        try:
            async with self._session.put(url, json=body) as resp:
                if resp.status == 200:
                    logger.info("OandaBroker.close_position: closed %s", instrument)
                    return True
                data = await resp.json()
                logger.warning(
                    "OandaBroker.close_position: %s failed (%s): %s",
                    instrument, resp.status, data.get("errorMessage", ""),
                )
                return False
        except aiohttp.ClientError as exc:
            logger.error("OandaBroker.close_position error: %s", exc)
            return False

    async def get_market_data(
        self,
        symbol: str,
        timeframe: str = "1h",
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Return OHLCV bars from OANDA instruments endpoint."""
        _tf_map = {
            "1m": "M1", "5m": "M5", "15m": "M15", "30m": "M30",
            "1h": "H1", "4h": "H4", "1d": "D", "1w": "W", "1M": "M",
        }
        granularity = _tf_map.get(timeframe, "H1")
        instrument = symbol.replace("/", "_").upper()
        return await self.get_ohlcv_candles(
            instrument=instrument,
            granularity=granularity,
            count=limit,
        )

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _assert_connected(self, method: str) -> bool:
        if not self.connected or self._session is None or self._session.closed:
            logger.error("OandaBroker.%s called before connect()", method)
            return False
        return True

    def status(self) -> dict[str, Any]:
        """Return a health snapshot for monitoring."""
        return {
            "broker": "oanda",
            "connected": self.connected,
            "account_id": self._account_id,
            "base_url": self._base_url,
        }

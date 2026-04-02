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

import logging
import os

import aiohttp

logger = logging.getLogger(__name__)

_PRACTICE_BASE = "https://api-fxpractice.oanda.com"
_LIVE_BASE = "https://api-fxtrade.oanda.com"

# Default request timeout (seconds).
_DEFAULT_TIMEOUT = 10


def _resolve_env(value: object) -> str:
    """Expand ``${ENV_VAR:default}`` placeholders."""
    if not isinstance(value, str):
        return str(value) if value is not None else ""
    if value.startswith("${") and value.endswith("}"):
        inner = value[2:-1]
        var, _, default = inner.partition(":")
        return os.environ.get(var, default)
    return value


class OandaBroker:
    """
    Async OANDA v20 REST broker.

    Parameters
    ----------
    config:
        Dict with keys ``login`` (account ID), ``password`` (API token),
        ``server`` ("practice" | "live").
        Optional: ``timeout_seconds`` (int, default 10).
    """

    def __init__(self, config: dict) -> None:
        self._config = config
        self.connected: bool = False
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
                self._account_id,
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
                    balance = data.get("account", {}).get("balance", "?")
                    self.connected = True
                    logger.info(
                        "OandaBroker connected | account=%s | server=%s | balance=%s %s",
                        self._account_id,
                        server,
                        balance,
                        currency,
                    )
                    return True
                body = await resp.text()
                logger.error(
                    "OandaBroker connect failed | status=%s | body=%s",
                    resp.status,
                    body,
                )
                await self._session.close()
                return False
        except aiohttp.ClientError as exc:
            logger.error("OandaBroker connect error: %s", exc)
            await self._session.close()
            return False

    async def disconnect(self) -> None:
        """Close the aiohttp session."""
        if self._session and not self._session.closed:
            await self._session.close()
        self.connected = False
        logger.info("OandaBroker disconnected (account=%s)", self._account_id)

    # ── Account ───────────────────────────────────────────────────────────────

    async def get_account_info(self) -> dict | None:
        """Return account summary as a plain dict."""
        if not self._assert_connected("get_account_info"):
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

    async def get_positions(self) -> list[dict]:
        """Return all open positions."""
        if not self._assert_connected("get_positions"):
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

    async def get_orders(self) -> list[dict]:
        """Return all pending orders."""
        if not self._assert_connected("get_orders"):
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

    async def place_order(self, order_params: dict) -> dict:
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
            client_id   (str)   — optional client order ID

        Returns
        -------
        Dict with keys: ``success`` (bool), ``order_id`` (str), ``trade_id`` (str),
        ``fill_price`` (float), ``comment`` (str).
        """
        if not self._assert_connected("place_order"):
            return {"success": False, "order_id": None, "comment": "Not connected"}

        instrument = order_params.get("instrument", "XAU_USD")
        units = str(order_params.get("units", 0))
        order_type = order_params.get("order_type", "MARKET").upper()
        price = order_params.get("price")
        sl_distance = order_params.get("sl_distance")
        tp_price = order_params.get("tp_price")
        time_in_force = order_params.get("time_in_force", "FOK" if order_type == "MARKET" else "GTC")
        client_id = order_params.get("client_id")

        order_body: dict = {
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

        if client_id:
            order_body["clientExtensions"] = {"id": client_id}

        payload = {"order": order_body}

        try:
            async with self._session.post(
                f"{self._base_url}/v3/accounts/{self._account_id}/orders",
                json=payload,
            ) as resp:
                data = await resp.json()
                if resp.status in (200, 201):
                    fill = data.get("orderFillTransaction", {})
                    created = data.get("orderCreateTransaction", {})
                    order_id = fill.get("orderID") or created.get("id")
                    trade_id = fill.get("tradeOpened", {}).get("tradeID")
                    fill_price = fill.get("price")
                    logger.info(
                        "OANDA order placed | instrument=%s | units=%s | order_id=%s | trade_id=%s",
                        instrument,
                        units,
                        order_id,
                        trade_id,
                    )
                    return {
                        "success": True,
                        "order_id": order_id,
                        "trade_id": trade_id,
                        "fill_price": float(fill_price) if fill_price else None,
                        "comment": "OK",
                    }
                error_msg = data.get("errorMessage", str(data))
                logger.warning("OANDA order failed | status=%s | error=%s", resp.status, error_msg)
                return {"success": False, "order_id": None, "comment": error_msg}
        except aiohttp.ClientError as exc:
            logger.error("OandaBroker.place_order network error: %s", exc)
            return {"success": False, "order_id": None, "comment": str(exc)}

    async def close_trade(self, trade_id: str, units: str | None = "ALL") -> dict:
        """
        Close an open trade (full or partial).

        Parameters
        ----------
        trade_id: OANDA trade ID string.
        units: "ALL" for full close, or a numeric string for partial close.
        """
        if not self._assert_connected("close_trade"):
            return {"success": False, "comment": "Not connected"}
        payload = {"units": units}
        try:
            async with self._session.put(
                f"{self._base_url}/v3/accounts/{self._account_id}/trades/{trade_id}/close",
                json=payload,
            ) as resp:
                data = await resp.json()
                if resp.status == 200:
                    logger.info("OANDA trade closed | trade_id=%s | units=%s", trade_id, units)
                    return {"success": True, "comment": "OK", "data": data}
                error_msg = data.get("errorMessage", str(data))
                return {"success": False, "comment": error_msg}
        except aiohttp.ClientError as exc:
            return {"success": False, "comment": str(exc)}

    async def cancel_order(self, order_id: str) -> dict:
        """Cancel a pending order by ID."""
        if not self._assert_connected("cancel_order"):
            return {"success": False, "comment": "Not connected"}
        try:
            async with self._session.put(
                f"{self._base_url}/v3/accounts/{self._account_id}/orders/{order_id}/cancel"
            ) as resp:
                if resp.status == 200:
                    logger.info("OANDA order cancelled | order_id=%s", order_id)
                    return {"success": True, "comment": "OK"}
                data = await resp.json()
                return {
                    "success": False,
                    "comment": data.get("errorMessage", str(data)),
                }
        except aiohttp.ClientError as exc:
            return {"success": False, "comment": str(exc)}

    async def get_tick(self, instrument: str = "XAU_USD") -> dict | None:
        """Return the latest bid/ask for *instrument*."""
        if not self._assert_connected("get_tick"):
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

    def _assert_connected(self, method: str) -> bool:
        if not self.connected or self._session is None or self._session.closed:
            logger.error("OandaBroker.%s called before connect()", method)
            return False
        return True

    def status(self) -> dict:
        """Return a health snapshot for monitoring."""
        return {
            "broker": "oanda",
            "connected": self.connected,
            "account_id": self._account_id,
            "base_url": self._base_url,
        }

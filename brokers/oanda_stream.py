# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
brokers/oanda_stream.py — OANDA v20 execution broker (REST only).

Responsibilities
----------------
  * Account info queries
  * Order placement  (market, limit, stop)
  * Order cancellation
  * Position queries and close
  * Historical candle fetch (for strategy warm-up only — not live ticks)

NOT responsible for
-------------------
  * Live price streaming  → use data_feed.NuclearStreamer
  * Tick delivery         → use data_feed.NuclearStreamer
  * Any real-time market data

Architectural boundary
----------------------
``stream_prices()`` raises ``StreamingForbiddenError`` at runtime to catch any
code that still tries to use this class as a data source.  All live price
data must flow through ``data_feed.NuclearStreamer``.

Credential resolution
---------------------
  OANDA_API_KEY     — personal access token (Bearer)
  OANDA_ACCOUNT_ID  — account number (e.g. 101-123-4567890-001)
  OANDA_PRACTICE    — "true" | "false"  (default: "true")
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

UTC = timezone.utc
from typing import Any, ClassVar

import aiohttp

from brokers.base import (
    AccountInfo,
    Order,
    OrderSide,
    OrderStatus,
    OrderType,
    Position,
)

logger = logging.getLogger(__name__)

# ── URL constants ─────────────────────────────────────────────────────────────

_PRACTICE_REST = "https://api-fxpractice.oanda.com"
_LIVE_REST = "https://api-fxtrade.oanda.com"

_TF_MAP = {
    "1m": "M1",
    "5m": "M5",
    "15m": "M15",
    "30m": "M30",
    "1h": "H1",
    "4h": "H4",
    "1d": "D",
    "1w": "W",
}

_DEFAULT_TIMEOUT = 10  # seconds


# ── Architectural boundary enforcement ───────────────────────────────────────


class StreamingForbiddenError(RuntimeError):
    """
    Raised when code attempts to stream prices through OANDAStream.

    Live price data must flow exclusively through data_feed.NuclearStreamer.
    """

    def __init__(self) -> None:
        super().__init__(
            "ARCHITECTURAL VIOLATION: stream_prices() called on OANDAStream. "
            "Live price streaming is handled exclusively by "
            "data_feed.NuclearStreamer (Finnhub / Twelve Data / Polygon). "
            "OANDAStream is for ORDER EXECUTION ONLY."
        )


# ── OANDAStream — execution broker ───────────────────────────────────────────


class OANDAStream:
    """
    Async OANDA v20 REST execution broker.

    Handles account queries, order placement, position management, and
    historical candle retrieval.  Does NOT stream live prices.

    Parameters
    ----------
    api_key:
        OANDA personal access token.
    account_id:
        OANDA account number.
    instruments:
        List of OANDA instrument codes (e.g. ``["XAU_USD", "EUR_USD"]``).
        Stored for reference; not used for streaming.
    practice:
        True -> practice (sandbox) endpoints; False -> live endpoints.
    event_bus:
        Optional event bus.  Kept for interface compatibility; not used for
        price events (those come from NuclearStreamer).
    """

    def __init__(
        self,
        api_key: str,
        account_id: str,
        instruments: list[str],
        practice: bool = True,
        event_bus: Any | None = None,
        on_tick: Any | None = None,  # accepted but ignored — streaming is forbidden
    ) -> None:
        if not api_key or not account_id:
            raise ValueError("api_key and account_id are required")

        self.api_key = api_key
        self.account_id = account_id
        self.instruments = instruments
        self.practice = practice
        self.event_bus = event_bus

        if on_tick is not None:
            logger.warning(
                "OANDAStream: on_tick callback ignored — price streaming is "
                "handled by data_feed.NuclearStreamer, not by broker connectors."
            )

        self._rest_base = _PRACTICE_REST if practice else _LIVE_REST
        self._headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept-Datetime-Format": "RFC3339",
        }
        self._session: aiohttp.ClientSession | None = None

    # ── Context manager ───────────────────────────────────────────────────────

    async def __aenter__(self) -> OANDAStream:
        self._session = aiohttp.ClientSession(headers=self._headers)
        return self

    async def __aexit__(self, *_) -> None:
        if self._session:
            await self._session.close()
            self._session = None

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def connect(self) -> bool:
        """Verify credentials by fetching account summary."""
        if not self._session:
            self._session = aiohttp.ClientSession(headers=self._headers)
        try:
            url = f"{self._rest_base}/v3/accounts/{self.account_id}/summary"
            async with self._session.get(url, timeout=aiohttp.ClientTimeout(total=_DEFAULT_TIMEOUT)) as r:
                r.raise_for_status()
                data = await r.json()
                bal = data.get("account", {}).get("balance", "?")
                logger.info(
                    "OANDA connected — account %s balance %s",
                    self.account_id,
                    bal,
                )
                return True
        except Exception as exc:
            logger.error("OANDA connect failed: %s", exc)
            return False

    async def disconnect(self) -> None:
        """Close the HTTP session."""
        if self._session:
            await self._session.close()
            self._session = None

    # ── Architectural boundary ────────────────────────────────────────────────

    async def stream_prices(self, *_args, **_kwargs) -> None:
        """
        Raises StreamingForbiddenError unconditionally.

        Live price streaming is handled by data_feed.NuclearStreamer.
        """
        raise StreamingForbiddenError

    # ── Account ───────────────────────────────────────────────────────────────

    async def get_account_info(self) -> AccountInfo | None:
        """Fetch live account summary."""
        try:
            url = f"{self._rest_base}/v3/accounts/{self.account_id}/summary"
            async with self._session.get(url, timeout=aiohttp.ClientTimeout(total=_DEFAULT_TIMEOUT)) as r:
                r.raise_for_status()
                a = (await r.json()).get("account", {})
                bal = float(a.get("balance", 0))
                nav = float(a.get("NAV", bal))
                return AccountInfo(
                    balance=bal,
                    equity=nav,
                    margin_used=float(a.get("marginUsed", 0)),
                    margin_available=float(a.get("marginAvailable", nav)),
                    positions_count=int(a.get("openPositionCount", a.get("openTradeCount", 0))),
                    timestamp=datetime.now(UTC),
                )
        except Exception as exc:
            logger.error("get_account_info: %s", exc)
            return None

    # ── Positions ─────────────────────────────────────────────────────────────

    async def get_positions(self) -> list[Position]:
        """Fetch all open positions."""
        try:
            url = f"{self._rest_base}/v3/accounts/{self.account_id}/openPositions"
            async with self._session.get(url, timeout=aiohttp.ClientTimeout(total=_DEFAULT_TIMEOUT)) as r:
                r.raise_for_status()
                out: ClassVar[list[Position]] = []
                for p in (await r.json()).get("positions", []):
                    lu = float(p.get("long", {}).get("units", 0))
                    su = float(p.get("short", {}).get("units", 0))
                    if lu != 0:
                        side, units = "LONG", lu
                        avg = float(p["long"].get("averagePrice", 0))
                        upnl = float(p["long"].get("unrealizedPL", 0))
                        rpnl = float(p["long"].get("realizedPL", 0))
                    elif su != 0:
                        side, units = "SHORT", abs(su)
                        avg = float(p["short"].get("averagePrice", 0))
                        upnl = float(p["short"].get("unrealizedPL", 0))
                        rpnl = float(p["short"].get("realizedPL", 0))
                    else:
                        continue
                    out.append(
                        Position(
                            symbol=p.get("instrument", "").replace("_", "/"),
                            side=side,
                            quantity=units,
                            entry_price=avg,
                            current_price=avg,
                            unrealized_pnl=upnl,
                            realized_pnl=rpnl,
                            timestamp=datetime.now(UTC),
                        )
                    )
                return out
        except Exception as exc:
            logger.error("get_positions: %s", exc)
            return []

    async def close_position(self, symbol: str) -> bool:
        """Close all units of a position."""
        try:
            url = f"{self._rest_base}/v3/accounts/{self.account_id}/positions/{symbol}/close"
            async with self._session.put(
                url,
                json={"longUnits": "ALL", "shortUnits": "ALL"},
                timeout=aiohttp.ClientTimeout(total=_DEFAULT_TIMEOUT),
            ) as r:
                r.raise_for_status()
                return True
        except Exception as exc:
            logger.error("close_position %s: %s", symbol, exc)
            return False

    # ── Orders ────────────────────────────────────────────────────────────────

    async def place_order(
        self,
        symbol: str,
        side: OrderSide,
        units: float,
        order_type: OrderType = OrderType.MARKET,
        price: float | None = None,
        stop_loss: float | None = None,
        take_profit: float | None = None,
    ) -> Order | None:
        """Place a market or limit order."""
        signed_units = units if side == OrderSide.BUY else -units
        body: dict[str, Any] = {
            "order": {
                "instrument": symbol,
                "units": str(int(signed_units)),
                "type": "MARKET" if order_type == OrderType.MARKET else "LIMIT",
                "timeInForce": "FOK" if order_type == OrderType.MARKET else "GTC",
            }
        }
        if price and order_type != OrderType.MARKET:
            body["order"]["price"] = str(price)
        if stop_loss:
            body["order"]["stopLossOnFill"] = {"price": str(stop_loss)}
        if take_profit:
            body["order"]["takeProfitOnFill"] = {"price": str(take_profit)}

        try:
            url = f"{self._rest_base}/v3/accounts/{self.account_id}/orders"
            async with self._session.post(
                url,
                json=body,
                timeout=aiohttp.ClientTimeout(total=_DEFAULT_TIMEOUT),
            ) as r:
                r.raise_for_status()
                return self._parse_order_response(await r.json(), symbol, side, units)
        except Exception as exc:
            logger.error("place_order: %s", exc)
            return None

    async def cancel_order(self, order_id: str) -> bool:
        """Cancel a pending order by ID."""
        try:
            url = f"{self._rest_base}/v3/accounts/{self.account_id}/orders/{order_id}/cancel"
            async with self._session.put(url, timeout=aiohttp.ClientTimeout(total=_DEFAULT_TIMEOUT)) as r:
                r.raise_for_status()
                return True
        except Exception as exc:
            logger.error("cancel_order %s: %s", order_id, exc)
            return False

    async def get_open_orders(self) -> list[Order]:
        """Fetch all pending (open) orders."""
        try:
            url = f"{self._rest_base}/v3/accounts/{self.account_id}/pendingOrders"
            async with self._session.get(url, timeout=aiohttp.ClientTimeout(total=_DEFAULT_TIMEOUT)) as r:
                r.raise_for_status()
                orders = []
                for o in (await r.json()).get("orders", []):
                    side_str = o.get("units", "0")
                    side = OrderSide.BUY if float(side_str) > 0 else OrderSide.SELL
                    orders.append(
                        Order(
                            id=str(o.get("id", "")),
                            symbol=o.get("instrument", ""),
                            side=side,
                            type=OrderType.LIMIT,
                            quantity=abs(float(o.get("units", 0))),
                            price=float(o["price"]) if o.get("price") else None,
                            status=OrderStatus.OPEN,
                            filled_quantity=0.0,
                            timestamp=datetime.now(UTC),
                        )
                    )
                return orders
        except Exception as exc:
            logger.error("get_open_orders: %s", exc)
            return []

    # ── Historical candles (strategy warm-up only) ────────────────────────────

    async def get_candles(
        self,
        symbol: str,
        timeframe: str = "H1",
        count: int = 500,
    ) -> list[dict]:
        """
        Fetch completed OHLCV candles for strategy warm-up.

        This is historical data retrieval, not live streaming.
        For live prices use data_feed.NuclearStreamer.
        """
        gran = _TF_MAP.get(timeframe, timeframe)
        try:
            url = f"{self._rest_base}/v3/instruments/{symbol}/candles"
            async with self._session.get(
                url,
                params={"granularity": gran, "count": min(count, 5000)},
                timeout=aiohttp.ClientTimeout(total=15),
            ) as r:
                r.raise_for_status()
                return [
                    {
                        "timestamp": c["time"],
                        "open": float(c["mid"]["o"]),
                        "high": float(c["mid"]["h"]),
                        "low": float(c["mid"]["l"]),
                        "close": float(c["mid"]["c"]),
                        "volume": int(c.get("volume", 0)),
                    }
                    for c in (await r.json()).get("candles", [])
                    if c.get("complete", True)
                ]
        except Exception as exc:
            logger.error("get_candles %s: %s", symbol, exc)
            return []

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _parse_order_response(
        self,
        data: dict,
        symbol: str,
        side: OrderSide,
        qty: float,
    ) -> Order:
        fill = data.get("orderFillTransaction")
        create = data.get("orderCreateTransaction")
        if fill:
            return Order(
                id=str(fill.get("id", "")),
                symbol=symbol,
                side=side,
                type=OrderType.MARKET,
                quantity=abs(float(fill.get("units", qty))),
                price=float(fill["price"]) if fill.get("price") else None,
                status=OrderStatus.FILLED,
                filled_quantity=abs(float(fill.get("units", qty))),
                average_price=float(fill["price"]) if fill.get("price") else None,
                timestamp=datetime.now(UTC),
            )
        if create:
            return Order(
                id=str(create.get("id", "")),
                symbol=symbol,
                side=side,
                type=OrderType.LIMIT,
                quantity=abs(float(create.get("units", qty))),
                price=float(create["price"]) if create.get("price") else None,
                status=OrderStatus.OPEN,
                filled_quantity=0.0,
                timestamp=datetime.now(UTC),
            )
        return Order(
            id="",
            symbol=symbol,
            side=side,
            type=OrderType.MARKET,
            quantity=qty,
            status=OrderStatus.REJECTED,
            filled_quantity=0.0,
            timestamp=datetime.now(UTC),
        )


# Alias for consistent naming across the codebase
OandaStreamClient = OANDAStream

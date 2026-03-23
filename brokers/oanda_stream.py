"""
OANDA v20 async streaming connector.

Connects to OANDA's SSE pricing stream and publishes DomainEvents onto the
event bus for every tick.  Also wraps the REST v20 API with async/await so
the rest of the system never blocks the event loop.

Usage
-----
    from brokers.oanda_stream import OANDAStream

    stream = OANDAStream(
        api_key=os.environ["OANDA_API_KEY"],
        account_id=os.environ["OANDA_ACCOUNT_ID"],
        instruments=["EUR_USD", "XAU_USD"],
        practice=True,          # False for live
        event_bus=bus,          # optional – publishes DomainEvents if supplied
    )

    async with stream:
        await stream.stream_prices()   # runs until cancelled
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

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

# ── constants ────────────────────────────────────────────────────────────────

_PRACTICE_REST    = "https://api-fxpractice.oanda.com"
_LIVE_REST        = "https://api-fxtrade.oanda.com"
_PRACTICE_STREAM  = "https://stream-fxpractice.oanda.com"
_LIVE_STREAM      = "https://stream-fxtrade.oanda.com"

_TF_MAP = {
    "1m": "M1", "5m": "M5", "15m": "M15", "30m": "M30",
    "1h": "H1", "4h": "H4", "1d": "D",   "1w": "W",
}


# ── tick dataclass ────────────────────────────────────────────────────────────

class Tick:
    """A single price tick from OANDA."""

    __slots__ = ("instrument", "bid", "ask", "mid", "time", "tradeable")

    def __init__(self, instrument: str, bid: float, ask: float,
                 time: datetime, tradeable: bool = True):
        self.instrument = instrument
        self.bid        = bid
        self.ask        = ask
        self.mid        = (bid + ask) / 2
        self.time       = time
        self.tradeable  = tradeable

    def __repr__(self) -> str:
        return (f"Tick({self.instrument} bid={self.bid:.5f} "
                f"ask={self.ask:.5f} @ {self.time.isoformat()})")


# ── main class ────────────────────────────────────────────────────────────────

class OANDAStream:
    """
    Async OANDA connector.

    * Streams live prices via SSE (no polling).
    * All REST calls are async (aiohttp).
    * Publishes ``DomainEvent`` objects onto an optional event bus.
    * Reconnects automatically on network errors with exponential back-off.
    """

    def __init__(
        self,
        api_key:     str,
        account_id:  str,
        instruments: List[str],
        practice:    bool = True,
        event_bus:   Any  = None,          # core.event_bus.EventBus instance
        on_tick:     Optional[Callable[[Tick], None]] = None,
    ):
        if not api_key or not account_id:
            raise ValueError("api_key and account_id are required")

        self.api_key     = api_key
        self.account_id  = account_id
        self.instruments = instruments
        self.practice    = practice
        self.event_bus   = event_bus
        self.on_tick     = on_tick

        self._rest_base   = _PRACTICE_REST   if practice else _LIVE_REST
        self._stream_base = _PRACTICE_STREAM if practice else _LIVE_STREAM
        self._headers     = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type":  "application/json",
            "Accept-Datetime-Format": "RFC3339",
        }

        self._session:  Optional[aiohttp.ClientSession] = None
        self._running   = False
        self._tick_count = 0

    # ── context manager ───────────────────────────────────────────────────────

    async def __aenter__(self) -> "OANDAStream":
        self._session = aiohttp.ClientSession(headers=self._headers)
        return self

    async def __aexit__(self, *_) -> None:
        self._running = False
        if self._session:
            await self._session.close()
            self._session = None

    # ── public API ────────────────────────────────────────────────────────────

    async def connect(self) -> bool:
        """Verify credentials by fetching account summary."""
        if not self._session:
            self._session = aiohttp.ClientSession(headers=self._headers)
        try:
            url = f"{self._rest_base}/v3/accounts/{self.account_id}/summary"
            async with self._session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as r:
                r.raise_for_status()
                data = await r.json()
                bal  = data.get("account", {}).get("balance", "?")
                logger.info("OANDA connected — account %s balance %s",
                            self.account_id, bal)
                return True
        except Exception as exc:
            logger.error("OANDA connect failed: %s", exc)
            return False

    async def stream_prices(self) -> None:
        """
        Open the SSE pricing stream and yield ticks indefinitely.

        Reconnects with exponential back-off (1 s → 2 s → 4 s … max 60 s)
        on any network error.
        """
        self._running = True
        backoff       = 1.0
        instruments   = ",".join(self.instruments)
        url           = (f"{self._stream_base}/v3/accounts/{self.account_id}"
                         f"/pricing/stream?instruments={instruments}")

        while self._running:
            try:
                logger.info("Opening OANDA price stream for %s", instruments)
                async with self._session.get(
                    url,
                    timeout=aiohttp.ClientTimeout(total=None, connect=10),
                ) as resp:
                    resp.raise_for_status()
                    backoff = 1.0          # reset on successful connection
                    async for raw_line in resp.content:
                        if not self._running:
                            return
                        line = raw_line.strip()
                        if not line:
                            continue
                        try:
                            msg = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        await self._handle_message(msg)

            except asyncio.CancelledError:
                return
            except Exception as exc:
                if not self._running:
                    return
                logger.warning("Stream error (%s) — reconnecting in %.0fs", exc, backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60.0)

    async def get_account_info(self) -> Optional[AccountInfo]:
        """Fetch live account summary."""
        try:
            url = f"{self._rest_base}/v3/accounts/{self.account_id}/summary"
            async with self._session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as r:
                r.raise_for_status()
                a = (await r.json()).get("account", {})
                bal = float(a.get("balance", 0))
                nav = float(a.get("NAV", bal))
                return AccountInfo(
                    balance          = bal,
                    equity           = nav,
                    margin_used      = float(a.get("marginUsed", 0)),
                    margin_available = float(a.get("marginAvailable", nav)),
                    positions_count  = int(a.get("openPositionCount",
                                                  a.get("openTradeCount", 0))),
                    timestamp        = datetime.now(timezone.utc),
                )
        except Exception as exc:
            logger.error("get_account_info: %s", exc)
            return None

    async def get_positions(self) -> List[Position]:
        """Fetch all open positions."""
        try:
            url = (f"{self._rest_base}/v3/accounts/{self.account_id}"
                   "/openPositions")
            async with self._session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as r:
                r.raise_for_status()
                out = []
                for p in (await r.json()).get("positions", []):
                    lu = float(p.get("long",  {}).get("units", 0))
                    su = float(p.get("short", {}).get("units", 0))
                    if lu != 0:
                        side, units = "LONG",  lu
                        avg  = float(p["long"].get("averagePrice", 0))
                        upnl = float(p["long"].get("unrealizedPL",  0))
                        rpnl = float(p["long"].get("realizedPL",    0))
                    elif su != 0:
                        side, units = "SHORT", abs(su)
                        avg  = float(p["short"].get("averagePrice", 0))
                        upnl = float(p["short"].get("unrealizedPL",  0))
                        rpnl = float(p["short"].get("realizedPL",    0))
                    else:
                        continue
                    out.append(Position(
                        symbol        = p.get("instrument", "").replace("_", "/"),
                        side          = side,
                        quantity      = units,
                        entry_price   = avg,
                        current_price = avg,
                        unrealized_pnl= upnl,
                        realized_pnl  = rpnl,
                        timestamp     = datetime.now(timezone.utc),
                    ))
                return out
        except Exception as exc:
            logger.error("get_positions: %s", exc)
            return []

    async def place_order(
        self,
        symbol:     str,
        side:       OrderSide,
        units:      float,
        order_type: OrderType = OrderType.MARKET,
        price:      Optional[float] = None,
        stop_loss:  Optional[float] = None,
        take_profit:Optional[float] = None,
    ) -> Optional[Order]:
        """Place a market or limit order."""
        signed_units = units if side == OrderSide.BUY else -units
        body: Dict[str, Any] = {
            "order": {
                "instrument":  symbol,
                "units":       str(int(signed_units)),
                "type":        "MARKET" if order_type == OrderType.MARKET else "LIMIT",
                "timeInForce": "FOK"    if order_type == OrderType.MARKET else "GTC",
            }
        }
        if price and order_type != OrderType.MARKET:
            body["order"]["price"] = str(price)
        if stop_loss:
            body["order"]["stopLossOnFill"] = {"price": str(stop_loss)}
        if take_profit:
            body["order"]["takeProfitOnFill"] = {"price": str(take_profit)}

        try:
            url = (f"{self._rest_base}/v3/accounts/{self.account_id}/orders")
            async with self._session.post(
                url, json=body, timeout=aiohttp.ClientTimeout(total=10)
            ) as r:
                r.raise_for_status()
                return self._parse_order_response(await r.json(), symbol, side, units)
        except Exception as exc:
            logger.error("place_order: %s", exc)
            return None

    async def close_position(self, symbol: str) -> bool:
        """Close all units of a position."""
        try:
            url = (f"{self._rest_base}/v3/accounts/{self.account_id}"
                   f"/positions/{symbol}/close")
            async with self._session.put(
                url,
                json={"longUnits": "ALL", "shortUnits": "ALL"},
                timeout=aiohttp.ClientTimeout(total=10),
            ) as r:
                r.raise_for_status()
                return True
        except Exception as exc:
            logger.error("close_position %s: %s", symbol, exc)
            return False

    async def get_candles(
        self,
        symbol:    str,
        timeframe: str = "H1",
        count:     int = 500,
    ) -> List[Dict]:
        """Fetch OHLCV candles (up to 5000 per request)."""
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
                        "open":   float(c["mid"]["o"]),
                        "high":   float(c["mid"]["h"]),
                        "low":    float(c["mid"]["l"]),
                        "close":  float(c["mid"]["c"]),
                        "volume": int(c.get("volume", 0)),
                    }
                    for c in (await r.json()).get("candles", [])
                    if c.get("complete", True)
                ]
        except Exception as exc:
            logger.error("get_candles %s: %s", symbol, exc)
            return []

    @property
    def tick_count(self) -> int:
        return self._tick_count

    # ── internals ─────────────────────────────────────────────────────────────

    async def _handle_message(self, msg: Dict) -> None:
        msg_type = msg.get("type")

        if msg_type == "PRICE":
            tick = self._parse_tick(msg)
            if tick is None:
                return
            self._tick_count += 1

            # user callback
            if self.on_tick:
                try:
                    if asyncio.iscoroutinefunction(self.on_tick):
                        await self.on_tick(tick)
                    else:
                        self.on_tick(tick)
                except Exception as exc:
                    logger.error("on_tick callback error: %s", exc)

            # event bus
            if self.event_bus:
                await self._publish_tick(tick)

        elif msg_type == "HEARTBEAT":
            logger.debug("OANDA heartbeat @ %s", msg.get("time"))

        elif msg_type == "DISCONNECT":
            logger.warning("OANDA stream DISCONNECT: %s", msg.get("disconnect", {}).get("description"))

    def _parse_tick(self, msg: Dict) -> Optional[Tick]:
        try:
            bids = msg.get("bids", [])
            asks = msg.get("asks", [])
            if not bids or not asks:
                return None
            bid = float(bids[0]["price"])
            ask = float(asks[0]["price"])
            ts  = datetime.fromisoformat(
                msg["time"].replace("Z", "+00:00")
            )
            return Tick(
                instrument = msg["instrument"],
                bid        = bid,
                ask        = ask,
                time       = ts,
                tradeable  = msg.get("tradeable", True),
            )
        except (KeyError, ValueError, IndexError) as exc:
            logger.debug("tick parse error: %s — %s", exc, msg)
            return None

    async def _publish_tick(self, tick: Tick) -> None:
        """Publish a PRICE_UPDATE DomainEvent onto the event bus."""
        try:
            from core.event_bus import DomainEvent as DE
            event = DE.create(
                event_type = "PRICE_UPDATE",
                source     = f"oanda:{tick.instrument}",
                data       = {
                    "instrument": tick.instrument,
                    "bid":        tick.bid,
                    "ask":        tick.ask,
                    "mid":        tick.mid,
                    "time":       tick.time.isoformat(),
                    "tradeable":  tick.tradeable,
                },
                priority   = 1,   # highest priority
            )
            await self.event_bus.publish(event)
        except Exception as exc:
            logger.error("event bus publish error: %s", exc)

    def _parse_order_response(
        self,
        data:   Dict,
        symbol: str,
        side:   OrderSide,
        qty:    float,
    ) -> Order:
        fill   = data.get("orderFillTransaction")
        create = data.get("orderCreateTransaction")
        if fill:
            return Order(
                id             = str(fill.get("id", "")),
                symbol         = symbol,
                side           = side,
                type           = OrderType.MARKET,
                quantity       = abs(float(fill.get("units", qty))),
                price          = float(fill["price"]) if fill.get("price") else None,
                status         = OrderStatus.FILLED,
                filled_quantity= abs(float(fill.get("units", qty))),
                average_price  = float(fill["price"]) if fill.get("price") else None,
                timestamp      = datetime.now(timezone.utc),
            )
        if create:
            return Order(
                id             = str(create.get("id", "")),
                symbol         = symbol,
                side           = side,
                type           = OrderType.LIMIT,
                quantity       = abs(float(create.get("units", qty))),
                price          = float(create["price"]) if create.get("price") else None,
                status         = OrderStatus.OPEN,
                filled_quantity= 0.0,
                timestamp      = datetime.now(timezone.utc),
            )
        return Order(
            id      = "",
            symbol  = symbol,
            side    = side,
            type    = OrderType.MARKET,
            quantity= qty,
            status  = OrderStatus.REJECTED,
            filled_quantity=0.0,
            timestamp=datetime.now(timezone.utc),
        )

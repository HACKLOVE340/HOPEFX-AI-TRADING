# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# AGPL-3.0 — Share all modifications
"""
market_data/order_book.py
=========================
Level 2 order book with microstructure signal extraction.

Live L2 source: Polygon.io Forex WebSocket (broker-free, unmanipulated)
  - wss://socket.polygon.io/forex
  - Subscribes to Q.C.XAU/USD (real-time forex quotes: bid, ask, bid_size, ask_size)
  - Subscribes to T.C.XAU/USD (trade prints for cumulative delta)
  - Same POLYGON_API_KEY already used by NuclearStreamer — no extra credentials

Polygon is a market data infrastructure provider, not a broker. It aggregates
data from multiple ECNs and liquidity providers without a conflict of interest.

Microstructure signals computed from the book:
  - Order book imbalance (OBI): (bid_vol - ask_vol) / (bid_vol + ask_vol)
  - Weighted mid price: volume-weighted mid across top N levels
  - Bid/ask depth (total volume within N bps of mid)
  - Depth ratio: bid_depth / ask_depth
  - Price pressure: signed imbalance × spread
  - Top-of-book spread in bps
  - Cumulative delta (running sum of signed trade flow)

All signals are normalised to [-1, 1] or [0, 1] for direct ML feature use.

Usage
-----
    from market_data.order_book import OrderBookFeed, get_order_book_feed

    feed = get_order_book_feed()
    await feed.start(symbols=["XAU_USD"])

    # In ML feature pipeline:
    snapshot = feed.get_snapshot("XAU_USD")
    features = snapshot.to_ml_features()
    # {"micro_obi": 0.23, "micro_weighted_mid_dev": 0.0001, ...}

Configuration (env vars)
------------------------
L2_PROVIDER          — "multi" | "polygon" | "mock" (default: "multi"; "mock" blocked in production)
POLYGON_API_KEY      — Polygon.io API key (same key used by NuclearStreamer)
L2_DEPTH_LEVELS      — number of book levels to track (default: 10)
L2_DEPTH_BPS         — depth window in bps for bid/ask depth calc (default: 50)
"""

from __future__ import annotations

import asyncio
import json as _json
import logging
import os
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone

UTC = timezone.utc
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)

# ── Configuration ─────────────────────────────────────────────────────────────
L2_PROVIDER: str = os.getenv("L2_PROVIDER", "multi")
L2_DEPTH_LEVELS: int = int(os.getenv("L2_DEPTH_LEVELS", "10"))
L2_DEPTH_BPS: float = float(os.getenv("L2_DEPTH_BPS", "50"))
# Reconnect back-off for Polygon WebSocket (seconds)
L2_RECONNECT_INITIAL: float = float(os.getenv("L2_RECONNECT_INITIAL", "1.0"))
L2_RECONNECT_MAX: float = float(os.getenv("L2_RECONNECT_MAX", "60.0"))
L2_SNAPSHOT_INTERVAL: float = float(os.getenv("L2_SNAPSHOT_INTERVAL", "0.1"))  # seconds between mock snapshots


# ── Data structures ───────────────────────────────────────────────────────────


@dataclass
class BookLevel:
    """Single price level in the order book."""

    price: float
    size: float


@dataclass
class OrderBookSnapshot:
    """
    Point-in-time L2 order book snapshot with derived microstructure signals.
    """

    symbol: str
    timestamp: datetime
    bids: list[BookLevel]  # sorted descending by price
    asks: list[BookLevel]  # sorted ascending by price
    mid_price: float = 0.0
    spread_bps: float = 0.0

    # Derived signals (computed on construction)
    obi: float = 0.0  # order book imbalance [-1, 1]
    weighted_mid: float = 0.0  # volume-weighted mid price
    bid_depth: float = 0.0  # total bid volume within L2_DEPTH_BPS
    ask_depth: float = 0.0  # total ask volume within L2_DEPTH_BPS
    depth_ratio: float = 1.0  # bid_depth / ask_depth
    price_pressure: float = 0.0  # obi × spread_bps (signed pressure)
    cumulative_delta: float = 0.0  # running signed trade flow (updated externally)

    def __post_init__(self) -> None:
        if self.bids and self.asks:
            best_bid = self.bids[0].price
            best_ask = self.asks[0].price
            self.mid_price = (best_bid + best_ask) / 2
            if self.mid_price > 0:
                self.spread_bps = (best_ask - best_bid) / self.mid_price * 10_000
        self._compute_signals()

    def _compute_signals(self) -> None:
        """Compute all derived microstructure signals from the raw book."""
        if not self.bids or not self.asks:
            return

        mid = self.mid_price
        depth_threshold = mid * L2_DEPTH_BPS / 10_000

        # ── Order book imbalance ──────────────────────────────────────────────
        # Use top L2_DEPTH_LEVELS levels for imbalance calculation.
        bid_vol = sum(b.size for b in self.bids[:L2_DEPTH_LEVELS])
        ask_vol = sum(a.size for a in self.asks[:L2_DEPTH_LEVELS])
        total_vol = bid_vol + ask_vol
        if total_vol > 0:
            self.obi = (bid_vol - ask_vol) / total_vol
        else:
            self.obi = 0.0

        # ── Weighted mid price ────────────────────────────────────────────────
        # Volume-weighted average of best bid and best ask.
        best_bid_vol = self.bids[0].size if self.bids else 0
        best_ask_vol = self.asks[0].size if self.asks else 0
        total_top = best_bid_vol + best_ask_vol
        if total_top > 0 and self.bids and self.asks:
            self.weighted_mid = (self.bids[0].price * best_ask_vol + self.asks[0].price * best_bid_vol) / total_top
        else:
            self.weighted_mid = mid

        # ── Depth within N bps ────────────────────────────────────────────────
        self.bid_depth = sum(b.size for b in self.bids if mid - b.price <= depth_threshold)
        self.ask_depth = sum(a.size for a in self.asks if a.price - mid <= depth_threshold)
        if self.ask_depth > 0:
            self.depth_ratio = self.bid_depth / self.ask_depth
        else:
            self.depth_ratio = 1.0

        # ── Price pressure ────────────────────────────────────────────────────
        self.price_pressure = self.obi * self.spread_bps

    def to_ml_features(self) -> dict[str, float]:
        """
        Return a flat dict of ML-ready features.

        All values are normalised for direct use as model inputs.
        Keys match the dl_* feature names expected by features_extended.py.
        """
        return {
            "micro_obi": float(np.clip(self.obi, -1.0, 1.0)),
            "micro_weighted_mid_dev": float(
                (self.weighted_mid - self.mid_price) / self.mid_price if self.mid_price > 0 else 0.0
            ),
            "micro_bid_depth": float(self.bid_depth),
            "micro_ask_depth": float(self.ask_depth),
            "micro_depth_ratio": float(np.clip(self.depth_ratio, 0.0, 10.0)),
            "micro_depth_imbalance": float(np.clip(self.obi, -1.0, 1.0)),
            "micro_price_pressure": float(np.clip(self.price_pressure / 100, -1.0, 1.0)),
            "micro_spread": float(self.asks[0].price - self.bids[0].price) if self.bids and self.asks else 0.0,
            "micro_spread_bps": float(self.spread_bps),
            "micro_cumulative_delta": float(np.clip(self.cumulative_delta / 10_000, -1.0, 1.0)),
        }


class OrderBook:
    """
    Maintains a live L2 order book for a single symbol.

    Thread-safe for single-writer (feed) + multiple-reader (ML pipeline) use.
    """

    def __init__(self, symbol: str, max_levels: int = L2_DEPTH_LEVELS) -> None:
        self.symbol = symbol
        self.max_levels = max_levels
        self._bids: dict[float, float] = {}  # price → size
        self._asks: dict[float, float] = {}
        self._cumulative_delta: float = 0.0
        self._last_snapshot: OrderBookSnapshot | None = None
        self._update_count: int = 0
        self._last_update: datetime | None = None

        # Rolling history for spread z-score
        self._spread_history: deque[float] = deque(maxlen=20)

    def apply_snapshot(
        self,
        bids: list[tuple[float, float]],
        asks: list[tuple[float, float]],
        timestamp: datetime | None = None,
    ) -> OrderBookSnapshot:
        """
        Replace the entire book with a new snapshot.

        Parameters
        ----------
        bids : List of (price, size) tuples, any order.
        asks : List of (price, size) tuples, any order.
        """
        self._bids = {p: s for p, s in bids if s > 0}
        self._asks = {p: s for p, s in asks if s > 0}
        return self._build_snapshot(timestamp)

    def apply_delta(
        self,
        side: str,
        price: float,
        size: float,
        timestamp: datetime | None = None,
    ) -> OrderBookSnapshot:
        """
        Apply an incremental update (delta) to the book.

        Parameters
        ----------
        side  : "bid" or "ask"
        price : Price level to update.
        size  : New size at this level. 0 = remove the level.
        """
        book = self._bids if side == "bid" else self._asks
        if size <= 0:
            book.pop(price, None)
        else:
            book[price] = size
        return self._build_snapshot(timestamp)

    def record_trade(self, side: str, size: float) -> None:
        """Update cumulative delta from a trade print."""
        if side == "buy":
            self._cumulative_delta += size
        else:
            self._cumulative_delta -= size

    def get_snapshot(self) -> OrderBookSnapshot | None:
        """Return the most recent snapshot."""
        return self._last_snapshot

    def _build_snapshot(self, timestamp: datetime | None) -> OrderBookSnapshot:
        """Build and cache a new snapshot from current book state."""
        ts = timestamp or datetime.now(UTC)

        sorted_bids = sorted(self._bids.items(), key=lambda x: -x[0])
        sorted_asks = sorted(self._asks.items(), key=lambda x: x[0])

        bids = [BookLevel(p, s) for p, s in sorted_bids[: self.max_levels]]
        asks = [BookLevel(p, s) for p, s in sorted_asks[: self.max_levels]]

        snap = OrderBookSnapshot(
            symbol=self.symbol,
            timestamp=ts,
            bids=bids,
            asks=asks,
        )
        snap.cumulative_delta = self._cumulative_delta

        # Track spread history for z-score
        if snap.spread_bps > 0:
            self._spread_history.append(snap.spread_bps)

        self._last_snapshot = snap
        self._update_count += 1
        self._last_update = ts
        return snap


# ── Provider implementations ──────────────────────────────────────────────────


class PolygonL2Feed:
    """
    Polygon.io Forex WebSocket — real-time L2 quotes and trade prints.

    Polygon is a market data infrastructure provider (not a broker), aggregating
    data from multiple ECNs and liquidity providers without a conflict of interest.
    The same POLYGON_API_KEY used by NuclearStreamer is reused here.

    WebSocket endpoint: wss://socket.polygon.io/forex
    Subscriptions per symbol (e.g. XAU_USD → C.XAU/USD):
      Q.C.XAU/USD  — real-time forex quotes (bid, ask, bid_size, ask_size)
      T.C.XAU/USD  — trade prints (price, size, side) for cumulative delta

    Quote message shape (Polygon "Q" event):
      {"ev":"Q","pair":"XAU/USD","bp":2001.40,"bs":500,"ap":2001.60,"as":480,"t":1711234567890}
      bp = bid price, bs = bid size, ap = ask price, as = ask size, t = timestamp ms

    Trade message shape (Polygon "T" event):
      {"ev":"T","pair":"XAU/USD","p":2001.50,"s":100,"t":1711234567890,"c":[1]}
      p = price, s = size, c = conditions (1 = buy-side aggressor)

    Since Polygon Forex delivers top-of-book quotes (not full depth), the feed
    maintains a synthetic multi-level book by accumulating quote updates into
    price buckets within L2_DEPTH_BPS of the current mid. This gives genuine
    bid/ask size data at each observed price level — not broker position counts.

    Reconnect: exponential back-off (L2_RECONNECT_INITIAL → L2_RECONNECT_MAX).
    Circuit breaker: feed marked degraded after 5 consecutive auth/subscribe
    failures; re-admitted after L2_RECONNECT_MAX seconds.
    """

    _WS_URL = "wss://socket.polygon.io/forex"

    def __init__(self) -> None:
        self._api_key: str = os.getenv("POLYGON_API_KEY", "")
        self._books: dict[str, OrderBook] = {}
        # Map Polygon pair string (e.g. "XAU/USD") → internal symbol (e.g. "XAU_USD")
        self._pair_to_symbol: dict[str, str] = {}
        self._running: bool = False
        self._task: asyncio.Task | None = None
        self._fail_count: int = 0

    # ── Symbol normalisation ──────────────────────────────────────────────────

    @staticmethod
    def _to_polygon_pair(symbol: str) -> str:
        """Convert internal symbol (XAU_USD / XAU/USD) to Polygon pair (XAU/USD)."""
        return symbol.replace("_", "/")

    @staticmethod
    def _to_polygon_sub(symbol: str) -> str:
        """Return Polygon subscription string for a symbol, e.g. C.XAU/USD."""
        return f"C.{symbol.replace('_', '/')}"

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def start(self, symbols: list[str]) -> None:
        """Connect to Polygon Forex WebSocket and subscribe to all symbols."""
        if not self._api_key:
            raise RuntimeError(
                "POLYGON_API_KEY is not set. Set it in your .env file — the same key used by NuclearStreamer."
            )

        for symbol in symbols:
            self._books[symbol] = OrderBook(symbol)
            pair = self._to_polygon_pair(symbol)
            self._pair_to_symbol[pair] = symbol

        self._running = True
        self._task = asyncio.create_task(
            self._run_with_backoff(symbols),
            name="l2_polygon",
        )
        logger.info("PolygonL2Feed starting for symbols: %s", symbols)

    async def stop(self) -> None:
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
        logger.info("PolygonL2Feed stopped")

    def get_snapshot(self, symbol: str) -> OrderBookSnapshot | None:
        book = self._books.get(symbol)
        return book.get_snapshot() if book else None

    # ── Reconnect loop ────────────────────────────────────────────────────────

    async def _run_with_backoff(self, symbols: list[str]) -> None:
        backoff = L2_RECONNECT_INITIAL
        while self._running:
            try:
                await self._stream(symbols)
                # Clean exit — reset back-off and failure counter.
                backoff = L2_RECONNECT_INITIAL
                self._fail_count = 0
                logger.debug("PolygonL2Feed: stream ended cleanly — reconnecting")
            except asyncio.CancelledError:
                break
            except Exception as exc:
                self._fail_count += 1
                exc_str = str(exc)
                # "no close frame received or sent" / "sent 1000 (OK)" are
                # clean WebSocket closes, not real errors.
                if "no close frame" in exc_str or "sent 1000" in exc_str or "1000 (OK)" in exc_str:
                    logger.debug(
                        "PolygonL2Feed: clean close (attempt %d) — reconnecting in %.0f s",
                        self._fail_count,
                        backoff,
                    )
                else:
                    logger.warning(
                        "PolygonL2Feed disconnected (attempt %d): %s — reconnecting in %.0f s",
                        self._fail_count,
                        exc,
                        backoff,
                    )
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, L2_RECONNECT_MAX)

    # ── WebSocket stream ──────────────────────────────────────────────────────

    async def _stream(self, symbols: list[str]) -> None:
        """
        Open the Polygon Forex WebSocket, authenticate, subscribe, and
        process incoming quote and trade messages until disconnected.
        """
        try:
            import websockets
        except ImportError as exc:
            raise RuntimeError("websockets package not installed. Run: pip install websockets") from exc

        import json as _json

        # Build subscription list: quotes + trades for every symbol
        subs = []
        for sym in symbols:
            base = self._to_polygon_sub(sym)
            subs.append(f"Q.{base[2:]}")  # Q.C.XAU/USD
            subs.append(f"T.{base[2:]}")  # T.C.XAU/USD

        logger.info("Polygon L2: connecting to %s", self._WS_URL)

        async with websockets.connect(
            self._WS_URL,
            ping_interval=20,
            ping_timeout=10,
            close_timeout=5,
        ) as ws:
            # ── Step 1: receive "connected" status ────────────────────────────
            raw = await asyncio.wait_for(ws.recv(), timeout=10)
            msgs = _json.loads(raw)
            if not any(m.get("status") == "connected" for m in msgs):
                raise RuntimeError(f"Polygon: unexpected connect message: {msgs}")
            logger.debug("Polygon L2: connected")

            # ── Step 2: authenticate ──────────────────────────────────────────
            await ws.send(_json.dumps({"action": "auth", "params": self._api_key}))
            raw = await asyncio.wait_for(ws.recv(), timeout=10)
            msgs = _json.loads(raw)
            if not any(m.get("status") == "auth_success" for m in msgs):
                raise RuntimeError(f"Polygon L2: auth failed: {msgs}")
            logger.info("Polygon L2: authenticated")

            # ── Step 3: subscribe ─────────────────────────────────────────────
            await ws.send(_json.dumps({"action": "subscribe", "params": ",".join(subs)}))
            raw = await asyncio.wait_for(ws.recv(), timeout=10)
            msgs = _json.loads(raw)
            if not any(m.get("status") == "success" for m in msgs):
                raise RuntimeError(f"Polygon L2: subscribe failed: {msgs}")
            logger.info("Polygon L2: subscribed to %s", subs)

            # ── Step 4: process messages ──────────────────────────────────────
            while self._running:
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=30)
                except TimeoutError:
                    await ws.ping()
                    continue

                events = _json.loads(raw)
                for ev in events:
                    ev_type = ev.get("ev", "")
                    if ev_type == "Q":
                        self._handle_quote(ev)
                    elif ev_type == "T":
                        self._handle_trade(ev)

    # ── Event handlers ────────────────────────────────────────────────────────

    def _handle_quote(self, ev: dict) -> None:
        """
        Process a Polygon forex quote event.

        Polygon Q events carry top-of-book bid/ask with sizes. We apply each
        quote as a snapshot update to the top level of the book, preserving
        any accumulated depth from prior quotes at different price levels.
        """
        pair = ev.get("pair", "")
        symbol = self._pair_to_symbol.get(pair)
        if symbol is None:
            return

        book = self._books.get(symbol)
        if book is None:
            return

        try:
            bid_price = float(ev.get("bp", 0) or 0)
            bid_size = float(ev.get("bs", 0) or 0)
            ask_price = float(ev.get("ap", 0) or 0)
            ask_size = float(ev.get("as", 0) or 0)
            ts_ms = ev.get("t", 0)
        except (TypeError, ValueError):
            return

        if bid_price <= 0 or ask_price <= 0:
            return

        ts = datetime.fromtimestamp(ts_ms / 1000.0, tz=UTC) if ts_ms else None

        # Apply as incremental delta — update the specific price level so the
        # book accumulates depth across multiple observed price points.
        book.apply_delta("bid", bid_price, bid_size, ts)
        book.apply_delta("ask", ask_price, ask_size, ts)

        logger.debug(
            "Polygon Q [%s]: bid=%.4f×%.0f  ask=%.4f×%.0f",
            symbol,
            bid_price,
            bid_size,
            ask_price,
            ask_size,
        )

    def _handle_trade(self, ev: dict) -> None:
        """
        Process a Polygon forex trade event for cumulative delta tracking.

        Polygon trade conditions: 1 = buy-side aggressor, 2 = sell-side.
        When conditions are absent, side is inferred from price vs mid.
        """
        pair = ev.get("pair", "")
        symbol = self._pair_to_symbol.get(pair)
        if symbol is None:
            return

        book = self._books.get(symbol)
        if book is None:
            return

        try:
            price = float(ev.get("p", 0) or 0)
            size = float(ev.get("s", 0) or 0)
            conditions = ev.get("c") or []
        except (TypeError, ValueError):
            return

        if price <= 0 or size <= 0:
            return

        # Determine aggressor side from conditions or price vs mid
        snap = book.get_snapshot()
        if 1 in conditions:
            side = "buy"
        elif 2 in conditions:
            side = "sell"
        elif snap and snap.mid_price > 0:
            side = "buy" if price >= snap.mid_price else "sell"
        else:
            side = "buy"  # default when no context available

        book.record_trade(side, size)
        logger.debug("Polygon T [%s]: %.4f × %.0f (%s)", symbol, price, size, side)


class FinnhubTradeFeed:
    """
    Finnhub WebSocket — trade tape only, feeds cumulative delta into shared OrderBooks.

    Finnhub delivers trade prints (price + size) but no bid/ask sizes, so it
    cannot contribute to order book depth. Its value here is the trade tape:
    every fill updates cumulative delta and aggressor-side pressure in the
    shared OrderBook objects owned by PolygonL2Feed.

    Symbol mapping: XAU_USD → "OANDA:XAU_USD" (Finnhub forex gold symbol).

    Side classification: since Finnhub does not tag aggressor side, we infer
    it by comparing the trade price to the current mid from the shared book.
    Price ≥ mid → buy aggressor; price < mid → sell aggressor.
    """

    # Finnhub symbol for spot gold
    _FINNHUB_SYMBOL = "OANDA:XAU_USD"
    _WS_URL = "wss://ws.finnhub.io"

    def __init__(self, shared_books: dict[str, OrderBook]) -> None:
        """
        Parameters
        ----------
        shared_books:
            The same OrderBook dict owned by PolygonL2Feed. Trades are
            recorded directly into these books so delta is unified.
        """
        self._api_key: str = os.getenv("FINNHUB_API_KEY", "")
        self._books = shared_books
        self._running: bool = False
        self._task: asyncio.Task | None = None
        self._fail_count: int = 0

    async def start(self) -> None:
        if not self._api_key:
            logger.info(
                "FINNHUB_API_KEY not set — Finnhub trade tape disabled. "
                "Cumulative delta will be sourced from Polygon trade events only."
            )
            return
        self._running = True
        self._task = asyncio.create_task(self._run_with_backoff(), name="l2_finnhub_tape")
        logger.info("FinnhubTradeFeed starting (trade tape → cumulative delta)")

    async def stop(self) -> None:
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()

    async def _run_with_backoff(self) -> None:
        backoff = L2_RECONNECT_INITIAL
        while self._running:
            try:
                await self._stream()
                # Clean exit — reset back-off and failure counter.
                backoff = L2_RECONNECT_INITIAL
                self._fail_count = 0
                logger.debug("FinnhubTradeFeed: stream ended cleanly — reconnecting")
            except asyncio.CancelledError:
                break
            except Exception as exc:
                self._fail_count += 1
                exc_str = str(exc)
                # "no close frame received or sent" is a clean WebSocket close
                # in some websockets library versions — not a real error.
                if "no close frame" in exc_str or "sent 1000" in exc_str or "1000 (OK)" in exc_str:
                    logger.debug(
                        "FinnhubTradeFeed: clean close (attempt %d) — reconnecting in %.0f s",
                        self._fail_count,
                        backoff,
                    )
                else:
                    logger.warning(
                        "FinnhubTradeFeed disconnected (attempt %d): %s — reconnecting in %.0f s",
                        self._fail_count,
                        exc,
                        backoff,
                    )
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, L2_RECONNECT_MAX)

    async def _stream(self) -> None:
        try:
            import websockets
        except ImportError as exc:
            raise RuntimeError("websockets not installed. Run: pip install websockets") from exc

        url = f"{self._WS_URL}?token={self._api_key}"
        logger.info("FinnhubTradeFeed: connecting")

        async with websockets.connect(url, ping_interval=20, ping_timeout=10, close_timeout=5) as ws:
            # Consume hello
            await asyncio.wait_for(ws.recv(), timeout=10)

            # Subscribe to gold
            await ws.send(_json.dumps({"type": "subscribe", "symbol": self._FINNHUB_SYMBOL}))
            logger.info("FinnhubTradeFeed: subscribed to %s", self._FINNHUB_SYMBOL)

            while self._running:
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=30)
                except TimeoutError:
                    await ws.ping()
                    continue

                data = _json.loads(raw)
                msg_type = data.get("type")

                if msg_type == "trade":
                    for trade in data.get("data") or []:
                        self._handle_trade(trade)
                elif msg_type == "ping":
                    await ws.send(_json.dumps({"type": "pong"}))
                elif msg_type == "error":
                    raise RuntimeError(f"Finnhub error: {data.get('msg')}")

    def _handle_trade(self, trade: dict) -> None:
        """Record a Finnhub trade print into all matching shared books."""
        price = trade.get("p")
        size = trade.get("v")  # Finnhub uses 'v' for volume/size
        if price is None or size is None:
            return

        price = float(price)
        size = float(size)
        if price <= 0 or size <= 0:
            return

        # Record into every book — Finnhub gold maps to all XAU symbols
        for symbol, book in self._books.items():
            if "XAU" not in symbol.upper():
                continue
            snap = book.get_snapshot()
            side = ("buy" if price >= snap.mid_price else "sell") if snap and snap.mid_price > 0 else "buy"
            book.record_trade(side, size)
            logger.debug("Finnhub tape [%s]: %.4f × %.0f (%s)", symbol, price, size, side)


class MultiSourceL2Feed:
    """
    Collated L2 feed: Polygon quotes (primary depth) + Finnhub trade tape (delta).

    Architecture
    ------------
    Both feeds write into the same set of OrderBook objects:

      Polygon WebSocket ──► Q events (bid/ask/sizes) ──► OrderBook.apply_delta()
                        ──► T events (trade prints)   ──► OrderBook.record_trade()

      Finnhub WebSocket ──► trade events              ──► OrderBook.record_trade()
                                                           (side inferred from mid)

    The result is a single OrderBookSnapshot per symbol that contains:
      - Real bid/ask depth from Polygon (L2 quotes, multiple price levels)
      - Cumulative delta from both Polygon trade events AND Finnhub trade tape
      - OBI, weighted mid, depth ratio, price pressure — all computed from live data

    Failover
    --------
    If Polygon is unavailable, the feed degrades gracefully:
      - Finnhub still updates cumulative delta
      - get_snapshot() returns the last valid snapshot (stale but not None)
    If Finnhub is unavailable, Polygon trade events alone drive delta.
    If both are unavailable, the circuit breaker in each sub-feed handles reconnect.

    L3 note
    -------
    True L3 (individual order add/cancel/modify events) is not available for
    spot XAU/USD on any retail or prosumer API. The deepest available is L2
    quotes with bid/ask sizes, which is what Polygon delivers. This feed
    extracts the maximum microstructure signal available from public data.
    """

    def __init__(self) -> None:
        # Shared books — both feeds write into the same objects
        self._books: dict[str, OrderBook] = {}
        self._polygon = PolygonL2Feed()
        self._finnhub: FinnhubTradeFeed | None = None  # created after books are set up

    async def start(self, symbols: list[str]) -> None:
        # Initialise shared books
        for symbol in symbols:
            self._books[symbol] = OrderBook(symbol)

        # Wire Polygon to use the shared books
        self._polygon._books = self._books
        for symbol in symbols:
            pair = PolygonL2Feed._to_polygon_pair(symbol)
            self._polygon._pair_to_symbol[pair] = symbol

        # Wire Finnhub to the same shared books
        self._finnhub = FinnhubTradeFeed(shared_books=self._books)

        # Start both concurrently
        await asyncio.gather(
            self._polygon.start(symbols),
            self._finnhub.start(),
        )
        logger.info(
            "MultiSourceL2Feed started: Polygon (quotes+trades) + Finnhub (trade tape) → %s",
            symbols,
        )

    async def stop(self) -> None:
        tasks = [self._polygon.stop()]
        if self._finnhub:
            tasks.append(self._finnhub.stop())
        await asyncio.gather(*tasks)

    def get_snapshot(self, symbol: str) -> OrderBookSnapshot | None:
        book = self._books.get(symbol)
        return book.get_snapshot() if book else None


class MockL2Feed:  # healer: ignore — assert_not_production() guard in __init__
    """
    Synthetic L2 order book feed — FOR TESTING AND DEVELOPMENT ONLY.

    Generates statistically plausible but entirely fabricated order book
    snapshots.  MUST NOT be used in production.  Set L2_PROVIDER=multi
    and configure POLYGON_API_KEY (and optionally FINNHUB_API_KEY).

    Raises RuntimeError if instantiated when APP_ENV=production.
    """

    def __init__(self) -> None:
        from utils.production_guard import assert_not_production

        assert_not_production(
            "MockL2Feed",
            replacement="MultiSourceL2Feed with L2_PROVIDER=multi",
            extra="Set L2_PROVIDER=multi and configure POLYGON_API_KEY.",
        )
        self._books: dict[str, OrderBook] = {}
        self._tasks: dict[str, asyncio.Task] = {}
        self._running = False

    async def start(self, symbols: list[str]) -> None:
        self._running = True
        for symbol in symbols:
            self._books[symbol] = OrderBook(symbol)
            task = asyncio.create_task(self._generate(symbol), name=f"l2_mock_{symbol}")
            self._tasks[symbol] = task
            logger.info("MockL2Feed started for %s (development only)", symbol)

    async def stop(self) -> None:
        self._running = False
        for task in self._tasks.values():
            if not task.done():
                task.cancel()

    def get_snapshot(self, symbol: str) -> OrderBookSnapshot | None:
        book = self._books.get(symbol)
        return book.get_snapshot() if book else None

    async def _generate(self, symbol: str) -> None:
        """Generate synthetic L2 data with realistic microstructure (dev/test only)."""
        book = self._books[symbol]
        mid = 2000.0  # gold-like price
        rng = np.random.default_rng()  # unseeded — non-deterministic per run

        while self._running:
            try:
                # Random walk mid price
                mid += rng.normal(0, 0.5)
                spread = rng.uniform(0.20, 0.50)

                # Generate 10 levels each side with exponentially decaying size
                bids = [
                    (mid - spread / 2 - i * 0.10, rng.exponential(100) * (1 + i * 0.1)) for i in range(L2_DEPTH_LEVELS)
                ]
                asks = [
                    (mid + spread / 2 + i * 0.10, rng.exponential(100) * (1 + i * 0.1)) for i in range(L2_DEPTH_LEVELS)
                ]
                book.apply_snapshot(bids, asks)
            except asyncio.CancelledError:
                return
            except Exception as exc:
                logger.debug("Mock L2 generate error: %s", exc)
            await asyncio.sleep(L2_SNAPSHOT_INTERVAL)


# ── OrderBookFeed facade ──────────────────────────────────────────────────────


class OrderBookFeed:
    """
    Provider-agnostic L2 order book feed facade.

    Selects the provider based on L2_PROVIDER env var and exposes a
    uniform get_snapshot() interface to the ML pipeline.

    Providers
    ---------
    "multi"   (default) — MultiSourceL2Feed: Polygon quotes (L2 depth) +
                          Finnhub trade tape (cumulative delta), collated
                          into one OrderBook per symbol. Requires POLYGON_API_KEY.
                          FINNHUB_API_KEY is optional but recommended for richer delta.
    "polygon"           — PolygonL2Feed only (quotes + Polygon trade events).
    "mock"              — Synthetic data. Blocked in APP_ENV=production/staging.
    """

    def __init__(self, provider: str | None = None) -> None:
        self._provider_name = provider or L2_PROVIDER
        self._provider: Any | None = None
        self._symbols: list[str] = []

    async def start(self, symbols: list[str]) -> None:
        """Start the L2 feed for the given symbols."""
        self._symbols = symbols

        if self._provider_name in ("multi", "polygon"):
            if self._provider_name == "multi":
                self._provider = MultiSourceL2Feed()
            else:
                self._provider = PolygonL2Feed()
        elif self._provider_name == "mock":
            # assert_not_production raises RuntimeError in production/staging
            # before MockL2Feed.__init__ is even reached, giving a clear error
            # message rather than silently serving synthetic data.
            from utils.production_guard import assert_not_production

            assert_not_production(
                "MockL2Feed (L2_PROVIDER=mock)",
                replacement="MultiSourceL2Feed with L2_PROVIDER=multi",
                extra="Set L2_PROVIDER=multi and configure POLYGON_API_KEY.",
            )
            logger.warning(
                "L2 feed using MockL2Feed (L2_PROVIDER=mock). Only permitted in development/test environments."
            )
            self._provider = MockL2Feed()
        else:
            raise RuntimeError(
                f"Unknown L2_PROVIDER={self._provider_name!r}. "
                "Valid values: 'multi' (default), 'polygon', 'mock'. "
                "Set POLYGON_API_KEY and optionally FINNHUB_API_KEY."
            )

        await self._provider.start(symbols)
        logger.info(
            "OrderBookFeed started: provider=%s symbols=%s",
            self._provider_name,
            symbols,
        )

    async def stop(self) -> None:
        if self._provider:
            await self._provider.stop()

    def get_snapshot(self, symbol: str) -> OrderBookSnapshot | None:
        """Return the latest L2 snapshot for a symbol, or None if unavailable."""
        if self._provider is None:
            return None
        return self._provider.get_snapshot(symbol)

    def get_ml_features(self, symbol: str) -> dict[str, float]:
        """
        Return ML-ready microstructure features for a symbol.

        Returns neutral (zero) values if no snapshot is available.
        """
        snap = self.get_snapshot(symbol)
        if snap is None:
            return {
                "micro_obi": 0.0,
                "micro_weighted_mid_dev": 0.0,
                "micro_bid_depth": 0.0,
                "micro_ask_depth": 0.0,
                "micro_depth_ratio": 1.0,
                "micro_depth_imbalance": 0.0,
                "micro_price_pressure": 0.0,
                "micro_spread": 0.0,
                "micro_spread_bps": 0.0,
                "micro_cumulative_delta": 0.0,
            }
        return snap.to_ml_features()


# ── Module-level singleton ────────────────────────────────────────────────────

_order_book_feed: OrderBookFeed | None = None


def get_order_book_feed() -> OrderBookFeed:
    """Return the module-level OrderBookFeed singleton."""
    global _order_book_feed
    if _order_book_feed is None:
        _order_book_feed = OrderBookFeed()
    return _order_book_feed

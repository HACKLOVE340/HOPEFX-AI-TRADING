# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
# market_data/feed_handler.py
"""
HOPEFX Market Data Feed Handler

Tick processing pipeline:
  1. Exchange-specific parsing  — raw WebSocket frame → Tick
  2. Tick normalization         — spread clamp, size normalisation, mid-price
  3. Trade classification       — Lee-Ready algorithm (tick-test fallback)
  4. L2 order book aggregation  — per-symbol aggregated book across exchanges
  5. Callback distribution      — registered handlers receive normalised Tick

L2 order book
-------------
``L2OrderBook`` maintains a sorted bid/ask price-level map per symbol.
Updates arrive as incremental diffs (side, price, size); size=0 removes
the level.  ``aggregate_books()`` merges books from multiple exchanges into
a single consolidated view.

Trade classification
--------------------
``TradeClassifier`` implements the Lee-Ready (1991) algorithm:
  * If trade price > mid → buyer-initiated (BUY).
  * If trade price < mid → seller-initiated (SELL).
  * If trade price == mid → tick test: compare to previous trade price.
Classified direction is stored in ``Tick.trade_side``.

Tick normalization pipeline
---------------------------
``TickNormalizationPipeline`` applies in order:
  1. Spread sanity clamp (max configurable bps).
  2. Size normalisation to standard lot units.
  3. Mid-price recomputation from normalised bid/ask.
  4. Stale-tick rejection (configurable max age).
  5. Outlier price rejection (z-score against rolling window).
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)

UTC = timezone.utc

try:
    import aiohttp
except ImportError:
    aiohttp = None  # type: ignore[assignment]


# ── Enumerations ──────────────────────────────────────────────────────────────

class TradeSide(str, Enum):
    BUY = "buy"
    SELL = "sell"
    UNKNOWN = "unknown"


# ── Core data structures ──────────────────────────────────────────────────────

@dataclass
class Tick:
    """Normalized market tick."""

    symbol: str
    timestamp: datetime
    bid: float
    ask: float
    bid_size: float
    ask_size: float
    last_price: float
    last_size: float
    exchange: str
    is_trade: bool = False                      # True if trade, False if quote
    trade_side: TradeSide = TradeSide.UNKNOWN   # Lee-Ready classification
    sequence: int | None = None                 # exchange sequence number
    raw: dict | None = None                     # original frame (not repr'd)

    @property
    def mid(self) -> float:
        return (self.bid + self.ask) / 2.0 if self.bid > 0 and self.ask > 0 else self.last_price

    @property
    def spread(self) -> float:
        return self.ask - self.bid if self.bid > 0 and self.ask > 0 else 0.0

    @property
    def spread_bps(self) -> float:
        """Spread in basis points relative to mid."""
        mid = self.mid
        return (self.spread / mid * 10_000.0) if mid > 0 else 0.0


@dataclass
class L2Level:
    """A single price level in an L2 order book."""
    price: float
    size: float
    order_count: int = 0


@dataclass
class L2OrderBook:
    """
    Aggregated L2 order book for a single symbol.

    Bids are stored descending (best bid first).
    Asks are stored ascending (best ask first).
    Updates are incremental: size=0 removes the level.
    """
    symbol: str
    exchange: str = ""
    sequence: int = 0
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    # price → L2Level mappings (unsorted; sorted on demand)
    _bids: dict[float, L2Level] = field(default_factory=dict, repr=False)
    _asks: dict[float, L2Level] = field(default_factory=dict, repr=False)

    def apply_update(self, side: str, price: float, size: float, order_count: int = 0) -> None:
        """Apply an incremental update. side='bid' or 'ask'. size=0 removes level."""
        book = self._bids if side == "bid" else self._asks
        if size == 0.0:
            book.pop(price, None)
        else:
            book[price] = L2Level(price=price, size=size, order_count=order_count)
        self.timestamp = datetime.now(UTC)

    def snapshot_bids(self, depth: int = 10) -> list[L2Level]:
        """Return top *depth* bid levels sorted descending by price."""
        return sorted(self._bids.values(), key=lambda l: -l.price)[:depth]

    def snapshot_asks(self, depth: int = 10) -> list[L2Level]:
        """Return top *depth* ask levels sorted ascending by price."""
        return sorted(self._asks.values(), key=lambda l: l.price)[:depth]

    @property
    def best_bid(self) -> float:
        return max(self._bids.keys(), default=0.0)

    @property
    def best_ask(self) -> float:
        return min(self._asks.keys(), default=0.0)

    @property
    def mid(self) -> float:
        bb, ba = self.best_bid, self.best_ask
        return (bb + ba) / 2.0 if bb > 0 and ba > 0 else 0.0

    @property
    def spread(self) -> float:
        bb, ba = self.best_bid, self.best_ask
        return ba - bb if bb > 0 and ba > 0 else 0.0

    @property
    def bid_depth(self) -> float:
        return sum(l.size for l in self._bids.values())

    @property
    def ask_depth(self) -> float:
        return sum(l.size for l in self._asks.values())

    @property
    def depth_imbalance(self) -> float:
        """(bid_depth - ask_depth) / (bid_depth + ask_depth); 0 if empty."""
        total = self.bid_depth + self.ask_depth
        return (self.bid_depth - self.ask_depth) / total if total > 0 else 0.0

    def to_dict(self, depth: int = 5) -> dict:
        return {
            "symbol": self.symbol,
            "exchange": self.exchange,
            "sequence": self.sequence,
            "timestamp": self.timestamp.isoformat(),
            "best_bid": self.best_bid,
            "best_ask": self.best_ask,
            "mid": self.mid,
            "spread": round(self.spread, 6),
            "bid_depth": self.bid_depth,
            "ask_depth": self.ask_depth,
            "depth_imbalance": round(self.depth_imbalance, 4),
            "bids": [{"price": l.price, "size": l.size} for l in self.snapshot_bids(depth)],
            "asks": [{"price": l.price, "size": l.size} for l in self.snapshot_asks(depth)],
        }


# ── Trade classifier ─────────────────────────────────────────────────────────

class TradeClassifier:
    """
    Lee-Ready (1991) trade direction classifier with tick-test fallback.

    For each symbol, maintains the last mid-price and last trade price so
    the tick test can be applied when the trade price equals the mid.

    Usage::

        clf = TradeClassifier()
        side = clf.classify(symbol="XAUUSD", trade_price=1905.5, mid=1905.0)
        # → TradeSide.BUY
    """

    def __init__(self) -> None:
        # symbol → last mid-price used for quote test
        self._last_mid: dict[str, float] = {}
        # symbol → last trade price used for tick test
        self._last_trade: dict[str, float] = {}

    def classify(self, symbol: str, trade_price: float, mid: float) -> TradeSide:
        """
        Classify a trade as buyer- or seller-initiated.

        Algorithm
        ---------
        1. Quote test: trade > mid → BUY; trade < mid → SELL.
        2. Tick test (trade == mid): compare to previous trade price.
           Up-tick → BUY; down-tick → SELL; no change → UNKNOWN.
        """
        self._last_mid[symbol] = mid
        side = TradeSide.UNKNOWN

        if mid > 0:
            if trade_price > mid:
                side = TradeSide.BUY
            elif trade_price < mid:
                side = TradeSide.SELL
            else:
                # Tick test fallback
                prev = self._last_trade.get(symbol)
                if prev is not None:
                    if trade_price > prev:
                        side = TradeSide.BUY
                    elif trade_price < prev:
                        side = TradeSide.SELL

        self._last_trade[symbol] = trade_price
        return side

    def reset(self, symbol: str | None = None) -> None:
        """Reset state for *symbol*, or all symbols if None."""
        if symbol is None:
            self._last_mid.clear()
            self._last_trade.clear()
        else:
            self._last_mid.pop(symbol, None)
            self._last_trade.pop(symbol, None)


# ── Tick normalization pipeline ───────────────────────────────────────────────

class TickNormalizationPipeline:
    """
    Multi-stage tick normalization pipeline.

    Stages (applied in order):
      1. Spread clamp  — reject ticks whose spread exceeds *max_spread_bps*.
      2. Size normalisation — scale raw sizes to standard lot units.
      3. Mid-price recomputation — recalculate mid from normalised bid/ask.
      4. Stale-tick rejection — discard ticks older than *max_age_seconds*.
      5. Outlier rejection — discard ticks whose price deviates more than
         *outlier_z_threshold* standard deviations from the rolling mean.

    All rejected ticks are counted per rejection reason and accessible via
    ``rejection_counts``.
    """

    def __init__(
        self,
        max_spread_bps: float = 500.0,
        max_age_seconds: float = 30.0,
        outlier_z_threshold: float = 4.0,
        outlier_window: int = 200,
        lot_size: float = 1.0,
    ) -> None:
        self.max_spread_bps = max_spread_bps
        self.max_age_seconds = max_age_seconds
        self.outlier_z_threshold = outlier_z_threshold
        self.lot_size = lot_size

        # Rolling price window per symbol for z-score outlier detection.
        self._price_window: dict[str, deque] = {}
        self._window_size = outlier_window

        self.rejection_counts: dict[str, int] = {
            "spread_clamp": 0,
            "stale": 0,
            "outlier": 0,
        }
        self.accepted_count: int = 0

    def process(self, tick: Tick) -> Tick | None:
        """
        Run *tick* through all normalisation stages.

        Returns the (possibly mutated) tick if it passes all stages, or
        None if it was rejected.
        """
        # Stage 1: spread clamp
        if tick.spread_bps > self.max_spread_bps and tick.bid > 0 and tick.ask > 0:
            self.rejection_counts["spread_clamp"] += 1
            logger.debug(
                "NORM REJECT spread_clamp [%s]: %.1f bps > %.1f bps",
                tick.symbol, tick.spread_bps, self.max_spread_bps,
            )
            return None

        # Stage 2: size normalisation
        if self.lot_size != 1.0:
            tick.bid_size = tick.bid_size / self.lot_size
            tick.ask_size = tick.ask_size / self.lot_size
            tick.last_size = tick.last_size / self.lot_size

        # Stage 3: mid-price recomputation (already a property, nothing to store)

        # Stage 4: stale-tick rejection
        age = (datetime.now(UTC) - tick.timestamp).total_seconds()
        if age > self.max_age_seconds:
            self.rejection_counts["stale"] += 1
            logger.debug(
                "NORM REJECT stale [%s]: age=%.1f s", tick.symbol, age,
            )
            return None

        # Stage 5: outlier rejection via z-score
        price = tick.last_price if tick.is_trade else tick.mid
        if price > 0:
            window = self._price_window.setdefault(tick.symbol, deque(maxlen=self._window_size))
            if len(window) >= 10:
                mean = sum(window) / len(window)
                variance = sum((p - mean) ** 2 for p in window) / len(window)
                std = variance ** 0.5
                if std > 0:
                    z = abs(price - mean) / std
                    if z > self.outlier_z_threshold:
                        self.rejection_counts["outlier"] += 1
                        logger.debug(
                            "NORM REJECT outlier [%s]: z=%.2f > %.2f",
                            tick.symbol, z, self.outlier_z_threshold,
                        )
                        return None
            window.append(price)

        self.accepted_count += 1
        return tick

    def stats(self) -> dict:
        total = self.accepted_count + sum(self.rejection_counts.values())
        return {
            "accepted": self.accepted_count,
            "rejected": dict(self.rejection_counts),
            "total": total,
            "acceptance_rate": self.accepted_count / total if total > 0 else 1.0,
        }


# ── L2 book aggregator ────────────────────────────────────────────────────────

class L2BookAggregator:
    """
    Aggregates L2 order books from multiple exchanges into a single
    consolidated view per symbol.

    Each exchange maintains its own ``L2OrderBook``.  The consolidated book
    merges all exchange books: bid levels are summed at each price, ask levels
    are summed at each price.
    """

    def __init__(self) -> None:
        # (symbol, exchange) → L2OrderBook
        self._books: dict[tuple[str, str], L2OrderBook] = {}

    def get_book(self, symbol: str, exchange: str) -> L2OrderBook:
        key = (symbol, exchange)
        if key not in self._books:
            self._books[key] = L2OrderBook(symbol=symbol, exchange=exchange)
        return self._books[key]

    def apply_update(
        self,
        symbol: str,
        exchange: str,
        side: str,
        price: float,
        size: float,
        sequence: int = 0,
        order_count: int = 0,
    ) -> L2OrderBook:
        """Apply an incremental L2 update and return the updated book."""
        book = self.get_book(symbol, exchange)
        book.apply_update(side, price, size, order_count)
        book.sequence = sequence
        return book

    def consolidated_book(self, symbol: str, depth: int = 10) -> dict:
        """
        Return a consolidated L2 snapshot merging all exchanges for *symbol*.

        Sizes at the same price level are summed across exchanges.
        """
        merged_bids: dict[float, float] = {}
        merged_asks: dict[float, float] = {}

        for (sym, _exch), book in self._books.items():
            if sym != symbol:
                continue
            for lvl in book.snapshot_bids(depth * 2):
                merged_bids[lvl.price] = merged_bids.get(lvl.price, 0.0) + lvl.size
            for lvl in book.snapshot_asks(depth * 2):
                merged_asks[lvl.price] = merged_asks.get(lvl.price, 0.0) + lvl.size

        bids = sorted(
            [{"price": p, "size": s} for p, s in merged_bids.items()],
            key=lambda x: -x["price"],
        )[:depth]
        asks = sorted(
            [{"price": p, "size": s} for p, s in merged_asks.items()],
            key=lambda x: x["price"],
        )[:depth]

        best_bid = bids[0]["price"] if bids else 0.0
        best_ask = asks[0]["price"] if asks else 0.0
        mid = (best_bid + best_ask) / 2.0 if best_bid and best_ask else 0.0
        spread = best_ask - best_bid if best_bid and best_ask else 0.0
        bid_depth = sum(x["size"] for x in bids)
        ask_depth = sum(x["size"] for x in asks)
        total_depth = bid_depth + ask_depth

        return {
            "symbol": symbol,
            "best_bid": best_bid,
            "best_ask": best_ask,
            "mid": mid,
            "spread": round(spread, 6),
            "bid_depth": bid_depth,
            "ask_depth": ask_depth,
            "depth_imbalance": round((bid_depth - ask_depth) / total_depth, 4) if total_depth else 0.0,
            "bids": bids,
            "asks": asks,
            "exchange_count": len({exch for (sym, exch) in self._books if sym == symbol}),
        }

    def symbols(self) -> list[str]:
        return list({sym for sym, _ in self._books})


# ── Feed handler ──────────────────────────────────────────────────────────────

class FeedHandler:
    """
    Normalizes feeds from multiple exchanges into a unified tick stream.

    Enhancements over the base implementation:
    - ``L2BookAggregator`` maintains per-exchange and consolidated L2 books.
    - ``TradeClassifier`` classifies each trade tick via Lee-Ready algorithm.
    - ``TickNormalizationPipeline`` applies spread clamp, size normalisation,
      stale-tick rejection, and outlier z-score filtering before distribution.
    """

    def __init__(
        self,
        max_spread_bps: float = 500.0,
        max_age_seconds: float = 30.0,
        outlier_z_threshold: float = 4.0,
        lot_size: float = 1.0,
    ) -> None:
        self.exchanges: dict[str, ExchangeFeed] = {}
        self.normalized_callbacks: list[Callable[[Tick], None]] = []
        self.symbol_subscriptions: set[str] = set()
        self.tick_buffer: deque = deque(maxlen=10000)
        self.stats: dict[str, Any] = {
            "ticks_processed": 0,
            "ticks_per_second": 0.0,
            "latency_ns": 0,
        }

        # New pipeline components
        self.normalizer = TickNormalizationPipeline(
            max_spread_bps=max_spread_bps,
            max_age_seconds=max_age_seconds,
            outlier_z_threshold=outlier_z_threshold,
            lot_size=lot_size,
        )
        self.classifier = TradeClassifier()
        self.l2_aggregator = L2BookAggregator()

    def add_exchange(self, name: str, feed: "ExchangeFeed"):
        """Add exchange feed"""
        self.exchanges[name] = feed
        feed.set_callback(self._on_exchange_tick)

    def subscribe(self, symbols: list[str]):
        """Subscribe to symbols"""
        self.symbol_subscriptions.update(symbols)
        for exchange in self.exchanges.values():
            exchange.subscribe(symbols)

    def _on_exchange_tick(self, raw_data: dict, exchange_name: str) -> None:
        """Process raw tick from exchange through the full normalization pipeline."""
        start_ns = time.monotonic_ns()

        # Stage 1: parse exchange-specific format
        tick = self._normalize(raw_data, exchange_name)

        if tick.symbol not in self.symbol_subscriptions:
            return

        # Stage 2: normalization pipeline (spread, size, stale, outlier)
        tick = self.normalizer.process(tick)
        if tick is None:
            return

        # Stage 3: trade classification (Lee-Ready)
        if tick.is_trade and tick.last_price > 0:
            tick.trade_side = self.classifier.classify(
                symbol=tick.symbol,
                trade_price=tick.last_price,
                mid=tick.mid,
            )

        # Store in ring buffer
        self.tick_buffer.append(tick)

        # Latency tracking (EMA)
        latency_ns = time.monotonic_ns() - start_ns
        self.stats["latency_ns"] = int(
            0.9 * self.stats["latency_ns"] + 0.1 * latency_ns
        )

        # Distribute to callbacks
        for callback in self.normalized_callbacks:
            try:
                callback(tick)
            except Exception as exc:
                logger.error("Tick callback error: %s", exc)

        self.stats["ticks_processed"] += 1

    def apply_l2_update(
        self,
        symbol: str,
        exchange: str,
        side: str,
        price: float,
        size: float,
        sequence: int = 0,
        order_count: int = 0,
    ) -> L2OrderBook:
        """
        Apply an incremental L2 order book update.

        Parameters
        ----------
        symbol:
            Instrument symbol (e.g. ``"XAUUSD"``).
        exchange:
            Exchange name (e.g. ``"oanda"``).
        side:
            ``"bid"`` or ``"ask"``.
        price:
            Price level.
        size:
            Size at this level; 0 removes the level.
        sequence:
            Exchange sequence number for gap detection.
        order_count:
            Number of orders at this level (optional).
        """
        return self.l2_aggregator.apply_update(
            symbol=symbol,
            exchange=exchange,
            side=side,
            price=price,
            size=size,
            sequence=sequence,
            order_count=order_count,
        )

    def get_consolidated_book(self, symbol: str, depth: int = 10) -> dict:
        """Return consolidated L2 book across all exchanges for *symbol*."""
        return self.l2_aggregator.consolidated_book(symbol, depth)

    def get_l2_book(self, symbol: str, exchange: str) -> L2OrderBook:
        """Return the per-exchange L2 book for *symbol*."""
        return self.l2_aggregator.get_book(symbol, exchange)

    def pipeline_stats(self) -> dict:
        """Return combined stats from the normalization pipeline."""
        return {
            "normalizer": self.normalizer.stats(),
            "ticks_processed": self.stats["ticks_processed"],
            "latency_ns_ema": self.stats["latency_ns"],
        }

    def _normalize(self, raw: dict, exchange: str) -> Tick:
        """Normalize exchange-specific format to Tick"""
        # Exchange-specific parsing
        parsers = {
            "oanda": self._parse_oanda,
            "binance": self._parse_binance,
            "coinbase": self._parse_coinbase,
        }

        parser = parsers.get(exchange, self._parse_generic)
        return parser(raw, exchange)

    def _parse_oanda(self, raw: dict, exchange: str) -> Tick:
        bids = raw.get("bids") or [{}]
        asks = raw.get("asks") or [{}]
        bid = float(bids[0].get("price", 0))
        ask = float(asks[0].get("price", 0))
        return Tick(
            symbol=raw.get("instrument", "").replace("_", ""),
            timestamp=datetime.now(UTC),
            bid=bid,
            ask=ask,
            bid_size=float(bids[0].get("liquidity", 0)),
            ask_size=float(asks[0].get("liquidity", 0)),
            last_price=(bid + ask) / 2.0 if bid and ask else 0.0,
            last_size=0.0,
            exchange=exchange,
            raw=raw,
        )

    def _parse_binance(self, raw: dict, exchange: str) -> Tick:
        ts_ms = raw.get("E") or raw.get("T", 0)
        return Tick(
            symbol=raw.get("s", ""),
            timestamp=datetime.fromtimestamp(ts_ms / 1000.0, tz=UTC),
            bid=float(raw.get("b", 0)),
            ask=float(raw.get("a", 0)),
            bid_size=float(raw.get("B", 0)),
            ask_size=float(raw.get("A", 0)),
            last_price=float(raw.get("p") or raw.get("c", 0)),
            last_size=float(raw.get("q") or raw.get("v", 0)),
            exchange=exchange,
            is_trade=raw.get("e") in ("trade", "aggTrade"),
            sequence=raw.get("u"),  # update ID
            raw=raw,
        )

    def _parse_coinbase(self, raw: dict, exchange: str) -> Tick:
        ts_str = raw.get("time", "")
        try:
            ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            ts = datetime.now(UTC)
        return Tick(
            symbol=raw.get("product_id", "").replace("-", ""),
            timestamp=ts,
            bid=float(raw.get("best_bid", 0)),
            ask=float(raw.get("best_ask", 0)),
            bid_size=float(raw.get("bid_size", 0)),
            ask_size=float(raw.get("ask_size", 0)),
            last_price=float(raw.get("price", 0)),
            last_size=float(raw.get("last_size", 0)),
            exchange=exchange,
            is_trade=raw.get("type") == "match",
            sequence=raw.get("sequence"),
            raw=raw,
        )

    def _parse_generic(self, raw: dict, exchange: str) -> Tick:
        return Tick(
            symbol=str(raw.get("symbol", "")),
            timestamp=datetime.now(UTC),
            bid=float(raw.get("bid", 0)),
            ask=float(raw.get("ask", 0)),
            bid_size=float(raw.get("bidSize", 0)),
            ask_size=float(raw.get("askSize", 0)),
            last_price=float(raw.get("price", 0)),
            last_size=float(raw.get("size", 0)),
            exchange=exchange,
            raw=raw,
        )

    def on_tick(self, callback: Callable[[Tick], None]):
        """Register tick callback"""
        self.normalized_callbacks.append(callback)

    def get_l1_book(self, symbol: str) -> Tick | None:
        """Return the most recent L1 quote tick for *symbol*."""
        for tick in reversed(self.tick_buffer):
            if tick.symbol == symbol and not tick.is_trade:
                return tick
        return None

    def get_recent_trades(self, symbol: str, n: int = 100) -> list[Tick]:
        """Return the *n* most recent classified trade ticks for *symbol*."""
        return [t for t in self.tick_buffer if t.symbol == symbol and t.is_trade][-n:]

    def get_buy_sell_ratio(self, symbol: str, n: int = 100) -> dict:
        """
        Return buy/sell volume ratio for the last *n* classified trades.

        Useful for order-flow imbalance analysis.
        """
        trades = self.get_recent_trades(symbol, n)
        buy_vol = sum(t.last_size for t in trades if t.trade_side == TradeSide.BUY)
        sell_vol = sum(t.last_size for t in trades if t.trade_side == TradeSide.SELL)
        total = buy_vol + sell_vol
        return {
            "buy_volume": buy_vol,
            "sell_volume": sell_vol,
            "total_volume": total,
            "buy_ratio": buy_vol / total if total > 0 else 0.5,
            "delta": buy_vol - sell_vol,
            "trade_count": len(trades),
        }


class ExchangeFeed:
    """Base class for exchange-specific feeds"""

    def __init__(self, name: str, ws_url: str):
        self.name = name
        self.ws_url = ws_url
        self.callback: Callable | None = None
        self.subscribed_symbols: set[str] = set()
        self.connected = False

    def set_callback(self, callback: Callable[[dict, str], None]):
        self.callback = callback

    def subscribe(self, symbols: list[str]):
        self.subscribed_symbols.update(symbols)

    async def connect(self):
        """Connect to WebSocket feed"""
        import aiohttp

        self.session = aiohttp.ClientSession()
        self.ws = await self.session.ws_connect(self.ws_url)
        self.connected = True

        # Send subscription
        await self._send_subscription()

        # Start receive loop
        _t = asyncio.create_task(self._receive_loop())
        _t.add_done_callback(lambda _: None)

    async def disconnect(self):
        """Close WebSocket and underlying HTTP session."""
        self.connected = False
        if hasattr(self, "ws") and self.ws and not self.ws.closed:
            await self.ws.close()
            self.ws = None
        if hasattr(self, "session") and self.session and not self.session.closed:
            await self.session.close()
            self.session = None

    async def _send_subscription(self):
        """Send subscription message"""
        # Override in subclass

    async def _receive_loop(self):
        """Receive and process messages"""
        import aiohttp as _aiohttp

        while self.connected:
            try:
                msg = await self.ws.receive()

                if msg.type == _aiohttp.WSMsgType.TEXT:
                    data = json.loads(msg.data)
                    if self.callback:
                        self.callback(data, self.name)

                elif msg.type == _aiohttp.WSMsgType.CLOSED:
                    break

            except Exception as e:
                logger.error("Feed error: %s", e)
                await asyncio.sleep(1)

        # Reconnect only if still supposed to be connected
        if self.connected:
            self.connected = False
            await asyncio.sleep(5)
            await self.connect()

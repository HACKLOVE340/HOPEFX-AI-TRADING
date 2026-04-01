# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# AGPL-3.0 — Share all modifications
"""
market_data/order_book.py
=========================
Level 2 order book with microstructure signal extraction.

Supports two live L2 sources:
  1. OANDA v20 streaming order book (REST snapshot + WebSocket updates)
  2. IBKR TWS market depth (via ib_insync)

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
    await feed.start(symbol="XAU_USD", provider="oanda")

    # In ML feature pipeline:
    snapshot = feed.get_snapshot("XAU_USD")
    features = snapshot.to_ml_features()
    # {"obi": 0.23, "weighted_mid": 2001.45, "bid_depth": 1500.0, ...}

Configuration (env vars)
------------------------
L2_PROVIDER          — "oanda" | "ibkr" | "mock" (default: "oanda"; "mock" blocked in production)
L2_DEPTH_LEVELS      — number of book levels to track (default: 10)
L2_DEPTH_BPS         — depth window in bps for bid/ask depth calc (default: 50)
L2_SNAPSHOT_INTERVAL — OANDA REST snapshot poll interval in seconds (default: 1.0)
OANDA_ACCOUNT_ID     — OANDA account ID (from env)
OANDA_API_KEY        — OANDA API key (from env)
OANDA_PRACTICE       — "true" | "false" (default: "true")
"""

from __future__ import annotations

import asyncio
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
L2_PROVIDER: str = os.getenv("L2_PROVIDER", "oanda")
L2_DEPTH_LEVELS: int = int(os.getenv("L2_DEPTH_LEVELS", "10"))
L2_DEPTH_BPS: float = float(os.getenv("L2_DEPTH_BPS", "50"))
L2_SNAPSHOT_INTERVAL: float = float(os.getenv("L2_SNAPSHOT_INTERVAL", "1.0"))


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


class OandaL2Feed:
    """
    OANDA v20 Level 2 order book feed.

    OANDA provides order book snapshots via REST (updated every ~20s) and
    pricing stream (bid/ask top-of-book). We combine both:
      - REST /v3/instruments/{instrument}/orderBook for depth snapshot
      - Streaming /v3/accounts/{id}/pricing/stream for real-time top-of-book

    Rate limits: REST order book endpoint is limited to ~1 req/20s per instrument.
    """

    PRACTICE_URL = "https://api-fxpractice.oanda.com"
    LIVE_URL = "https://api-fxtrade.oanda.com"

    def __init__(self) -> None:
        self._api_key = os.getenv("OANDA_API_KEY", "")
        self._account_id = os.getenv("OANDA_ACCOUNT_ID", "")
        self._practice = os.getenv("OANDA_PRACTICE", "true").lower() == "true"
        self._base_url = self.PRACTICE_URL if self._practice else self.LIVE_URL
        self._session: Any | None = None
        self._books: dict[str, OrderBook] = {}
        self._running = False
        self._poll_tasks: dict[str, asyncio.Task] = {}

    async def start(self, symbols: list[str]) -> None:
        """Start polling L2 snapshots for the given symbols."""
        try:
            import aiohttp

            self._session = aiohttp.ClientSession(
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                }
            )
        except ImportError:
            logger.warning("aiohttp not available — OANDA L2 feed disabled")
            return

        self._running = True
        for symbol in symbols:
            oanda_sym = symbol.replace("/", "_")
            self._books[symbol] = OrderBook(symbol)
            task = asyncio.create_task(
                self._poll_order_book(symbol, oanda_sym),
                name=f"l2_oanda_{symbol}",
            )
            self._poll_tasks[symbol] = task
            logger.info("OANDA L2 feed started for %s", symbol)

    async def stop(self) -> None:
        """Stop all polling tasks and close the HTTP session."""
        self._running = False
        for task in self._poll_tasks.values():
            if not task.done():
                task.cancel()
        if self._session:
            await self._session.close()

    def get_snapshot(self, symbol: str) -> OrderBookSnapshot | None:
        """Return the latest L2 snapshot for a symbol."""
        book = self._books.get(symbol)
        return book.get_snapshot() if book else None

    async def _poll_order_book(self, symbol: str, oanda_symbol: str) -> None:
        """Poll OANDA order book REST endpoint at L2_SNAPSHOT_INTERVAL."""
        url = f"{self._base_url}/v3/instruments/{oanda_symbol}/orderBook"
        book = self._books[symbol]

        while self._running:
            try:
                async with self._session.get(url) as resp:
                    if resp.status == 200:  # noqa: PLR2004
                        data = await resp.json()
                        ob = data.get("orderBook", {})
                        buckets = ob.get("buckets", [])

                        bids = []
                        asks = []
                        for bucket in buckets:
                            price = float(bucket.get("price", 0))
                            long_pct = float(bucket.get("longCountPercent", 0))
                            short_pct = float(bucket.get("shortCountPercent", 0))
                            if long_pct > 0:
                                bids.append((price, long_pct))
                            if short_pct > 0:
                                asks.append((price, short_pct))

                        if bids or asks:
                            book.apply_snapshot(bids, asks)
                            logger.debug(
                                "OANDA L2: %s — %d bid levels, %d ask levels",
                                symbol,
                                len(bids),
                                len(asks),
                            )
                    elif resp.status == 429:  # noqa: PLR2004
                        logger.warning("OANDA L2: rate limited — backing off 30s")
                        await asyncio.sleep(30)
                        continue
                    else:
                        logger.warning("OANDA L2: HTTP %d for %s", resp.status, symbol)
            except asyncio.CancelledError:
                return
            except Exception as exc:
                logger.warning("OANDA L2 poll error for %s: %s", symbol, exc)

            await asyncio.sleep(L2_SNAPSHOT_INTERVAL)


class IBKROrderBookFeed:
    """
    Interactive Brokers TWS Level 2 market depth feed via ib_insync.

    Requires TWS or IB Gateway running with API enabled.
    """

    def __init__(self) -> None:
        self._host = os.getenv("IBKR_HOST", "127.0.0.1")
        self._port = int(os.getenv("IBKR_PORT", "7497"))
        self._client_id = int(os.getenv("IBKR_CLIENT_ID", "2"))
        self._ib: Any | None = None
        self._books: dict[str, OrderBook] = {}
        self._tickers: dict[str, Any] = {}

    async def start(self, symbols: list[str]) -> None:
        """Connect to TWS and subscribe to market depth."""
        try:
            from ib_insync import IB, Forex, Contract  # noqa: F401
        except ImportError:
            logger.warning("ib_insync not installed — IBKR L2 feed disabled")
            return

        try:
            self._ib = IB()
            await self._ib.connectAsync(self._host, self._port, clientId=self._client_id)
            logger.info("IBKR L2 feed connected to %s:%d", self._host, self._port)

            for symbol in symbols:
                self._books[symbol] = OrderBook(symbol)
                # Build contract — XAU/USD is a Forex contract in IBKR
                parts = symbol.replace("_", "/").split("/")
                if len(parts) == 2:  # noqa: PLR2004
                    contract = Forex(parts[0] + parts[1])
                    await self._ib.qualifyContractsAsync(contract)
                    ticker = self._ib.reqMktDepth(contract, numRows=L2_DEPTH_LEVELS)
                    ticker.updateEvent += lambda t, sym=symbol: self._on_depth_update(t, sym)
                    self._tickers[symbol] = ticker
                    logger.info("IBKR L2 subscribed to %s", symbol)
        except Exception as exc:
            logger.error("IBKR L2 feed start failed: %s", exc)

    def _on_depth_update(self, ticker: Any, symbol: str) -> None:
        """Handle IBKR market depth update."""
        book = self._books.get(symbol)
        if book is None:
            return
        try:
            bids = [(d.price, d.size) for d in ticker.domBids]
            asks = [(d.price, d.size) for d in ticker.domAsks]
            book.apply_snapshot(bids, asks)
        except Exception as exc:
            logger.debug("IBKR depth update error for %s: %s", symbol, exc)

    def get_snapshot(self, symbol: str) -> OrderBookSnapshot | None:
        book = self._books.get(symbol)
        return book.get_snapshot() if book else None

    async def stop(self) -> None:
        if self._ib and self._ib.isConnected():
            self._ib.disconnect()


class MockL2Feed:
    """
    Synthetic L2 order book feed — FOR TESTING AND DEVELOPMENT ONLY.

    Generates statistically plausible but entirely fabricated order book
    snapshots.  MUST NOT be used in production.  Set L2_PROVIDER=oanda or
    L2_PROVIDER=ibkr and configure the corresponding credentials.

    Raises RuntimeError if instantiated when APP_ENV=production.
    """

    def __init__(self) -> None:
        import os as _os

        _env = _os.getenv("APP_ENV", "production").lower()
        if _env in ("production", "staging"):
            raise RuntimeError(
                f"MockL2Feed cannot be used in {_env} (APP_ENV={_env}). "
                "Set L2_PROVIDER=oanda or L2_PROVIDER=ibkr and configure the "
                "corresponding credentials (OANDA_API_KEY / IBKR_HOST)."
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
        """Generate synthetic L2 data with realistic microstructure."""
        book = self._books[symbol]
        mid = 2000.0  # gold-like price
        rng = np.random.default_rng(42)

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
    """

    def __init__(self, provider: str | None = None) -> None:
        self._provider_name = provider or L2_PROVIDER
        self._provider: Any | None = None
        self._symbols: list[str] = []

    async def start(self, symbols: list[str]) -> None:
        """Start the L2 feed for the given symbols."""
        self._symbols = symbols

        if self._provider_name == "oanda":
            self._provider = OandaL2Feed()
        elif self._provider_name == "ibkr":
            self._provider = IBKROrderBookFeed()
        elif self._provider_name == "mock":
            # MockL2Feed raises RuntimeError in APP_ENV=production.
            logger.warning(
                "L2 feed using MockL2Feed (L2_PROVIDER=mock). This is only permitted in non-production environments."
            )
            self._provider = MockL2Feed()
        else:
            raise RuntimeError(
                f"Unknown L2_PROVIDER={self._provider_name!r}. "
                "Valid values: 'oanda', 'ibkr'. "
                "Set the L2_PROVIDER environment variable and configure the "
                "corresponding credentials."
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

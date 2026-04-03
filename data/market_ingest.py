# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# AGPL-3.0 — Share all modifications

"""
data/market_ingest.py
=====================
Real-time XAUUSD tick ingestion via ccxt WebSocket (ccxt.pro).

Pipeline
--------
  ccxt.pro WebSocket  →  validate tick  →  staleness check  →  publish to EventBus

Features
--------
- Connects to OANDA (or any ccxt.pro exchange) for live XAUUSD ticks.
- Validates each tick: non-zero bid/ask, ask > bid, spread within bounds.
- Staleness guard: if no tick arrives within STALE_TIMEOUT_S, logs a warning
  and publishes a staleness breach event so downstream can pause.
- Publishes validated ticks to hopefx:tick via the EventBus singleton.
- Reconnects automatically on WebSocket drop (exponential back-off).
- Falls back to OANDA REST polling when WebSocket is unavailable.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from datetime import UTC, datetime

# ccxt.pro for async WebSocket streaming
try:
    import ccxt.pro as ccxtpro  # type: ignore

    CCXT_PRO_AVAILABLE = True
except ImportError:
    ccxtpro = None  # type: ignore
    CCXT_PRO_AVAILABLE = False

# ccxt sync for REST fallback

from core.event_bus import bus

logger = logging.getLogger(__name__)

# ── singleton guard ───────────────────────────────────────────────────────────
# Prevents two MarketIngest instances from running in the same process.
# The orchestrator's GoldFeedManager is a separate pipeline (different APIs),
# but two MarketIngest instances would open duplicate OANDA WebSocket connections
# and publish duplicate ticks to hopefx:tick, corrupting downstream consumers.
_INGEST_RUNNING: bool = False

# ── config ────────────────────────────────────────────────────────────────────
SYMBOL: str = os.environ.get("INGEST_SYMBOL", "XAU/USD")
EXCHANGE_ID: str = os.environ.get("INGEST_EXCHANGE", "oanda")
STALE_TIMEOUT_S: float = float(os.environ.get("INGEST_STALE_TIMEOUT_S", "10"))
MAX_SPREAD_USD: float = float(os.environ.get("INGEST_MAX_SPREAD_USD", "5.0"))
REST_POLL_S: float = float(os.environ.get("INGEST_REST_POLL_S", "1.0"))
WS_RECONNECT_BASE: float = 1.0  # initial back-off seconds
WS_RECONNECT_MAX: float = 60.0  # cap back-off at 60 s


# ─────────────────────────────────────────────────────────────────────────────
# Tick validator
# ─────────────────────────────────────────────────────────────────────────────


def _validate_tick(bid: float, ask: float, symbol: str) -> bool:
    """
    Return True when the tick passes all sanity checks.

    Checks
    ------
    - bid and ask are positive non-zero floats
    - ask > bid (no inverted spread)
    - spread does not exceed MAX_SPREAD_USD (catches bad data / flash crashes)
    """
    if bid <= 0 or ask <= 0:
        logger.warning("Tick rejected: non-positive bid/ask  bid=%.5f ask=%.5f", bid, ask)
        return False
    if ask <= bid:
        logger.warning("Tick rejected: inverted spread  bid=%.5f ask=%.5f", bid, ask)
        return False
    spread = ask - bid
    if spread > MAX_SPREAD_USD:
        logger.warning(
            "Tick rejected: spread %.5f > max %.5f  symbol=%s",
            spread,
            MAX_SPREAD_USD,
            symbol,
        )
        return False
    return True


# ─────────────────────────────────────────────────────────────────────────────
# Staleness guard
# ─────────────────────────────────────────────────────────────────────────────


class _StalenessGuard:
    """Fires a breach event when no tick arrives within STALE_TIMEOUT_S."""

    def __init__(self) -> None:
        self._last_tick_ts: float = time.monotonic()
        self._stale_fired: bool = False

    def touch(self) -> None:
        """Call on every valid tick to reset the staleness clock."""
        self._last_tick_ts = time.monotonic()
        self._stale_fired = False

    async def check(self) -> None:
        """Call periodically; publishes a breach event when stale."""
        age = time.monotonic() - self._last_tick_ts
        if age > STALE_TIMEOUT_S and not self._stale_fired:
            self._stale_fired = True
            logger.warning("STALE FEED: no tick for %.1f s on %s", age, SYMBOL)
            await bus.publish_breach(
                {
                    "reason": "stale_feed",
                    "symbol": SYMBOL,
                    "age_s": round(age, 2),
                    "timestamp": datetime.now(UTC).isoformat(),
                }
            )


# ─────────────────────────────────────────────────────────────────────────────
# ccxt.pro WebSocket ingestor
# ─────────────────────────────────────────────────────────────────────────────


class MarketIngest:
    """
    Streams XAUUSD ticks from ccxt.pro WebSocket and publishes to EventBus.

    Usage
    -----
    ingest = MarketIngest()
    await ingest.start()   # runs until cancelled
    """

    def __init__(self) -> None:
        self._exchange: object | None = None
        self._staleness = _StalenessGuard()
        self._running: bool = False
        self._tick_count: int = 0
        self._last_tick: dict | None = None

        # Credentials from env
        self._api_key = os.environ.get("OANDA_API_KEY", "")
        self._api_secret = os.environ.get("OANDA_API_SECRET", os.environ.get("OANDA_API_KEY", ""))
        self._account_id = os.environ.get("OANDA_ACCOUNT_ID", "")
        self._practice = os.environ.get("OANDA_PRACTICE", "true").lower() != "false"

    # ── lifecycle ─────────────────────────────────────────────────────────────

    async def start(self) -> None:
        """Connect to EventBus and begin streaming ticks.

        Raises RuntimeError if another MarketIngest instance is already running
        in this process.  Two instances would open duplicate OANDA WebSocket
        connections and publish duplicate ticks to hopefx:tick.

        Note: MarketIngest (ccxt.pro → OANDA/bitfinex) and the orchestrator's
        GoldFeedManager (REST gold price APIs) are separate pipelines that fetch
        from different sources.  Running both simultaneously is intentional and
        correct — they do NOT double-write lineage because MarketIngest only
        publishes to the EventBus; lineage writes happen exclusively inside the
        orchestrator's _on_tick() path.
        """
        global _INGEST_RUNNING
        if _INGEST_RUNNING:
            raise RuntimeError(
                "MarketIngest is already running in this process. "
                "Only one instance may run at a time to avoid duplicate "
                "OANDA WebSocket connections and duplicate tick events."
            )
        _INGEST_RUNNING = True

        await bus.connect()
        self._running = True
        logger.info("MarketIngest starting — symbol=%s exchange=%s", SYMBOL, EXCHANGE_ID)

        # Run staleness checker in background
        _t = asyncio.create_task(self._staleness_loop())
        _t.add_done_callback(lambda _: None)

        try:
            if CCXT_PRO_AVAILABLE:
                await self._ws_loop()
            else:
                logger.warning("ccxt.pro not available — falling back to REST polling.")
                await self._rest_loop()
        finally:
            _INGEST_RUNNING = False

    async def stop(self) -> None:
        """Graceful shutdown."""
        self._running = False
        if self._exchange and hasattr(self._exchange, "close"):
            await self._exchange.close()
        logger.info("MarketIngest stopped. Total ticks: %d", self._tick_count)

    # ── WebSocket loop ────────────────────────────────────────────────────────

    async def _ws_loop(self) -> None:
        """
        Main WebSocket streaming loop.

        Reconnects with exponential back-off on any error.
        """
        backoff = WS_RECONNECT_BASE

        while self._running:
            try:
                self._exchange = self._build_exchange_ws()
                logger.info("MarketIngest: WebSocket connecting to %s …", EXCHANGE_ID)

                while self._running:
                    # watch_order_book gives bid/ask; watch_ticker gives last/bid/ask
                    ticker = await self._exchange.watch_ticker(SYMBOL)
                    await self._handle_ticker(ticker)
                    backoff = WS_RECONNECT_BASE  # reset on success

            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("MarketIngest WS error: %s — reconnecting in %.1f s", exc, backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, WS_RECONNECT_MAX)
                # Close stale exchange object before reconnecting
                if self._exchange:
                    try:
                        await self._exchange.close()
                    except Exception as close_exc:
                        logger.debug(
                            "MarketIngest: error closing stale exchange on reconnect: %s",
                            close_exc,
                        )

    # ── REST fallback loop ────────────────────────────────────────────────────

    async def _rest_loop(self) -> None:
        """
        Poll OANDA REST API for the latest bid/ask when WebSocket is unavailable.

        Uses aiohttp directly against the OANDA v20 pricing endpoint.
        """
        import aiohttp

        env_prefix = "practice" if self._practice else "trade"
        base_url = f"https://{env_prefix}-api.oanda.com"
        # OANDA instrument format: XAU_USD
        instrument = SYMBOL.replace("/", "_")
        url = f"{base_url}/v3/accounts/{self._account_id}/pricing"
        headers = {"Authorization": f"Bearer {self._api_key}"}

        logger.info("MarketIngest: REST polling %s every %.1f s", url, REST_POLL_S)

        async with aiohttp.ClientSession(headers=headers) as session:
            while self._running:
                try:
                    async with session.get(
                        url,
                        params={"instruments": instrument},
                        timeout=aiohttp.ClientTimeout(total=5),
                    ) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            prices = data.get("prices", [])
                            if prices:
                                p = prices[0]
                                bid = float(p.get("bids", [{}])[0].get("price", 0))
                                ask = float(p.get("asks", [{}])[0].get("price", 0))
                                await self._emit_tick(bid, ask)
                        else:
                            logger.warning("REST poll HTTP %d", resp.status)
                except Exception as exc:
                    logger.error("REST poll error: %s", exc)

                await asyncio.sleep(REST_POLL_S)

    # ── tick handlers ─────────────────────────────────────────────────────────

    async def _handle_ticker(self, ticker: dict) -> None:
        """Extract bid/ask from a ccxt ticker dict and emit."""
        bid = float(ticker.get("bid") or ticker.get("last") or 0)
        ask = float(ticker.get("ask") or ticker.get("last") or 0)
        await self._emit_tick(
            bid,
            ask,
            extra={
                "last": ticker.get("last"),
                "volume": ticker.get("baseVolume"),
            },
        )

    async def _emit_tick(self, bid: float, ask: float, extra: dict | None = None) -> None:
        """Validate, record staleness, and publish a tick to the EventBus."""
        if not _validate_tick(bid, ask, SYMBOL):
            return

        self._staleness.touch()
        self._tick_count += 1

        tick = {
            "symbol": SYMBOL,
            "bid": round(bid, 5),
            "ask": round(ask, 5),
            "mid": round((bid + ask) / 2, 5),
            "spread": round(ask - bid, 5),
            "timestamp": datetime.now(UTC).isoformat(),
            "seq": self._tick_count,
        }
        if extra:
            tick.update({k: v for k, v in extra.items() if v is not None})

        self._last_tick = tick
        await bus.publish_tick(tick)

        if self._tick_count % 100 == 0:
            logger.info(
                "Tick #%d  %s  bid=%.5f ask=%.5f spread=%.5f",
                self._tick_count,
                SYMBOL,
                bid,
                ask,
                ask - bid,
            )

    # ── staleness background task ─────────────────────────────────────────────

    async def _staleness_loop(self) -> None:
        """Check for stale feed every second."""
        while self._running:
            await self._staleness.check()
            await asyncio.sleep(1)

    # ── exchange factory ──────────────────────────────────────────────────────

    def _build_exchange_ws(self) -> object:
        """
        Instantiate a ccxt.pro exchange object.

        Uses OANDA by default; falls back to a generic exchange when OANDA
        is not available in the installed ccxt.pro version.
        """
        config = {
            "apiKey": self._api_key,
            "secret": self._api_secret,
            "options": {"defaultType": "spot"},
        }

        # OANDA-specific sandbox flag
        if self._practice:
            config["urls"] = {
                "api": {
                    "rest": "https://api-fxpractice.oanda.com",
                    "ws": "wss://stream-fxpractice.oanda.com",
                }
            }

        exchange_cls = getattr(ccxtpro, EXCHANGE_ID, None)
        if exchange_cls is None:
            # Fallback to a public exchange that carries XAU/USD (e.g. bitfinex)
            logger.warning(
                "ccxt.pro has no '%s' exchange — falling back to bitfinex for XAU/USD",
                EXCHANGE_ID,
            )
            exchange_cls = ccxtpro.bitfinex
            config.pop("apiKey", None)
            config.pop("secret", None)

        return exchange_cls(config)

    # ── status ────────────────────────────────────────────────────────────────

    @property
    def tick_count(self) -> int:
        return self._tick_count

    @property
    def last_tick(self) -> dict | None:
        return self._last_tick

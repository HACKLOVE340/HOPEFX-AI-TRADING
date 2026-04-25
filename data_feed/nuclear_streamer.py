# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
NuclearStreamer — multi-source WebSocket price ingestion for XAUUSD.

Architecture
------------
Three concurrent WebSocket streams run in parallel:

  1. Finnhub   wss://ws.finnhub.io          (FOREX:OANDA:XAU_USD)
  2. Twelve Data  WebSocket API              (XAU/USD)
  3. Polygon   wss://socket.polygon.io/forex (C.XAU/USD)

Each stream feeds into a shared ``process_tick`` coroutine that:
  * Measures end-to-end latency (event timestamp → now).
  * Detects anomalous price jumps (configurable threshold).
  * Publishes validated ticks to a Redis list (``price_queue``).
  * Exposes a Prometheus latency gauge on port 9090.
  * Notifies all registered subscribers via ``on_new_price(price)``.

Failure handling
----------------
  * Each stream reconnects with exponential back-off (max 60 s).
  * A per-stream circuit breaker opens after ``circuit_breaker_threshold``
    consecutive failures and re-tries after ``circuit_breaker_cooldown`` s.
  * Anomalous ticks are logged and discarded; the last known price is kept.
  * Redis publish errors are logged but never crash the stream.

Thread safety
-------------
``last_price`` is protected by an ``asyncio.Lock`` (not a threading.Lock)
because all code runs inside a single asyncio event loop.

Usage
-----
    streamer = NuclearStreamer()
    streamer.subscribe(brain)
    asyncio.run(streamer.run())

    # Or as a background task inside an existing event loop:
    _t = asyncio.create_task(streamer.run())
    _t.add_done_callback(lambda _: None)

Environment variables
---------------------
  FINNHUB_API_KEY   — Finnhub WebSocket token
  TWELVE_API_KEY    — Twelve Data API key
  POLYGON_API_KEY   — Polygon.io API key (optional; fastest sub-50 ms)
  REDIS_HOST        — Redis hostname (default: localhost)
  REDIS_PORT        — Redis port    (default: 6379)
  REDIS_DB          — Redis DB index (default: 0)
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import time
from datetime import datetime
from typing import Any

import websockets
from prometheus_client import Gauge, start_http_server

logger = logging.getLogger(__name__)

# ── Optional dependencies ──────────────────────────────────────────────────────

try:
    from twelvedata import TDClient as _TDClient  # type: ignore

    _TWELVE_AVAILABLE = True
except ImportError:
    _TDClient = None  # type: ignore
    _TWELVE_AVAILABLE = False
    logger.warning(
        "twelvedata package not installed — Twelve Data stream will be skipped. Install with: pip install twelvedata"
    )

try:
    import redis.asyncio as _aioredis  # type: ignore

    _REDIS_AVAILABLE = True
except ImportError:
    _aioredis = None  # type: ignore
    _REDIS_AVAILABLE = False
    logger.warning("redis package not installed — Redis publishing will be skipped. Install with: pip install redis")

# ── Constants ─────────────────────────────────────────────────────────────────

# Plausible XAUUSD price range — ticks outside this window are rejected.
_PRICE_MIN: float = 1_000.0
_PRICE_MAX: float = 10_000.0

# Maximum age (seconds) a tick may have before it is considered stale and
# discarded.  Ticks older than this (event_ts too far in the past) indicate
# a lagging feed and should not update last_price or trigger signals.
_MAX_STALE_SECONDS: float = float(os.environ.get("NUCLEAR_MAX_STALE_SECONDS", "30"))

# Reconnect back-off: initial 1 s, doubles each attempt, capped at 60 s.
_BACKOFF_INITIAL: float = 1.0
_BACKOFF_MAX: float = 60.0

# Prometheus metrics server port.
_METRICS_PORT: int = 9090

# Redis queue key.
_REDIS_QUEUE: str = "price_queue"

# ── Prometheus gauges (module-level singletons) ────────────────────────────────

_LATENCY_GAUGE = Gauge(
    "price_stream_latency_ms",
    "End-to-end streaming latency in milliseconds",
    ["source"],
)
_PRICE_GAUGE = Gauge(
    "price_stream_last_price",
    "Last validated XAUUSD price",
    ["source"],
)
_ANOMALY_COUNTER_GAUGE = Gauge(
    "price_stream_anomaly_total",
    "Total anomalous ticks discarded",
    ["source"],
)


class NuclearStreamer:
    """
    Concurrent multi-source WebSocket price streamer for XAUUSD.

    Parameters
    ----------
    symbol:
        Trading symbol (default ``XAUUSD``).
    anomaly_jump_pct:
        Percentage price change that triggers an anomaly alert (default 5.0).
    circuit_breaker_threshold:
        Consecutive failures before a stream's circuit breaker opens.
    circuit_breaker_cooldown:
        Seconds to wait before re-trying a tripped stream.
    prometheus_port:
        Port for the Prometheus metrics HTTP server (0 = disabled).
    redis_host / redis_port / redis_db:
        Redis connection parameters (override via env vars).
    """

    def __init__(
        self,
        symbol: str = "XAUUSD",
        anomaly_jump_pct: float = 5.0,
        circuit_breaker_threshold: int = 5,
        circuit_breaker_cooldown: float = 60.0,
        prometheus_port: int = _METRICS_PORT,
        redis_host: str | None = None,
        redis_port: int | None = None,
        redis_db: int | None = None,
    ) -> None:
        self.symbol = symbol
        self.anomaly_jump_pct = anomaly_jump_pct
        self.circuit_breaker_threshold = circuit_breaker_threshold
        self.circuit_breaker_cooldown = circuit_breaker_cooldown
        self.prometheus_port = prometheus_port

        # Credentials from environment.
        self._finnhub_key: str | None = os.getenv("FINNHUB_API_KEY")
        self._twelve_key: str | None = os.getenv("TWELVE_API_KEY")
        self._polygon_key: str | None = os.getenv("POLYGON_API_KEY")

        # Redis config (env overrides constructor args).
        self._redis_host: str = os.getenv("REDIS_HOST", redis_host or "localhost")
        self._redis_port: int = int(os.getenv("REDIS_PORT", str(redis_port or 6379)))
        self._redis_db: int = int(os.getenv("REDIS_DB", str(redis_db or 0)))
        self._redis_password: str | None = os.getenv("REDIS_PASSWORD") or None

        # Suppress repeated Redis publish errors after the first — log once,
        # then demote to DEBUG so the log is not flooded on every tick.
        self._redis_publish_errors: int = 0

        # Shared state — protected by an asyncio lock.
        self._price_lock: asyncio.Lock = asyncio.Lock()
        self._last_price: float | None = None
        self._anomaly_counts: dict[str, int] = {}

        # Circuit-breaker state per source.
        self._fail_counts: dict[str, int] = {}
        self._circuit_open_at: dict[str, float | None] = {}

        # Subscribers notified on every validated tick.
        self._subscribers: list[Any] = []

        # Redis client (created lazily in run()).
        self._redis: Any | None = None

        # Running flag.
        self._running: bool = False

    # ── Public API ─────────────────────────────────────────────────────────────

    def subscribe(self, component: Any) -> None:
        """Register a subscriber with an ``on_new_price(price: float)`` coroutine."""
        self._subscribers.append(component)
        logger.info("NuclearStreamer: %s subscribed", type(component).__name__)

    def unsubscribe(self, component: Any) -> None:
        """Remove a previously registered subscriber."""
        with contextlib.suppress(ValueError):
            self._subscribers.remove(component)

    async def run(self) -> None:
        """
        Start all streams concurrently.

        Blocks until all streams exit (which only happens on unrecoverable
        errors or when ``stop()`` is called).
        """
        self._running = True

        if self.prometheus_port > 0:
            try:
                start_http_server(self.prometheus_port)
                logger.info(
                    "Prometheus metrics available at http://localhost:%d/metrics",
                    self.prometheus_port,
                )
            except OSError:
                # Port already bound (e.g. multiple instances in tests).
                logger.debug("Prometheus port %d already in use — skipping", self.prometheus_port)

        if _REDIS_AVAILABLE:
            self._redis = _aioredis.Redis(
                host=self._redis_host,
                port=self._redis_port,
                db=self._redis_db,
                password=self._redis_password,
                decode_responses=False,
            )
            logger.info(
                "Redis connected: %s:%d db=%d",
                self._redis_host,
                self._redis_port,
                self._redis_db,
            )

        tasks = []
        if self._finnhub_key:
            tasks.append(asyncio.create_task(self._run_with_backoff("finnhub", self._finnhub_stream)))
        else:
            logger.warning("FINNHUB_API_KEY not set — Finnhub stream disabled")

        if self._twelve_key and _TWELVE_AVAILABLE:
            tasks.append(asyncio.create_task(self._run_with_backoff("twelvedata", self._twelve_stream)))
        elif not self._twelve_key:
            logger.warning("TWELVE_API_KEY not set — Twelve Data stream disabled")

        if self._polygon_key:
            tasks.append(asyncio.create_task(self._run_with_backoff("polygon", self._polygon_stream)))
        else:
            logger.warning("POLYGON_API_KEY not set — Polygon stream disabled")

        if not tasks:
            logger.error("No streaming sources configured — set at least one API key")
            return

        logger.info("NuclearStreamer started with %d source(s)", len(tasks))
        await asyncio.gather(*tasks, return_exceptions=True)

        if self._redis:
            await self._redis.aclose()

    async def stop(self) -> None:
        """Signal all streams to stop after the current reconnect cycle."""
        self._running = False
        logger.info("NuclearStreamer stop requested")

    # ── Circuit breaker helpers ────────────────────────────────────────────────

    def _is_circuit_open(self, source: str) -> bool:
        open_at = self._circuit_open_at.get(source)
        if open_at is None:
            return False
        if time.monotonic() - open_at >= self.circuit_breaker_cooldown:
            self._circuit_open_at[source] = None
            self._fail_counts[source] = 0
            logger.info("Circuit breaker CLOSED for source '%s'", source)
            return False
        return True

    def _record_failure(self, source: str) -> None:
        self._fail_counts[source] = self._fail_counts.get(source, 0) + 1
        if self._fail_counts[source] >= self.circuit_breaker_threshold:
            self._circuit_open_at[source] = time.monotonic()
            logger.warning(
                "Circuit breaker OPEN for source '%s' after %d failures",
                source,
                self._fail_counts[source],
            )

    def _record_success(self, source: str) -> None:
        self._fail_counts[source] = 0
        self._circuit_open_at[source] = None

    # ── Back-off wrapper ───────────────────────────────────────────────────────

    async def _run_with_backoff(self, source: str, coro_fn) -> None:
        """
        Run *coro_fn* in a reconnect loop with exponential back-off.

        The loop exits only when ``self._running`` is False.
        """
        backoff = _BACKOFF_INITIAL
        while self._running:
            if self._is_circuit_open(source):
                remaining = self.circuit_breaker_cooldown - (
                    time.monotonic() - (self._circuit_open_at.get(source) or 0)
                )
                logger.info(
                    "Circuit breaker open for '%s' — waiting %.0f s",
                    source,
                    max(remaining, 0),
                )
                await asyncio.sleep(max(remaining, 1))
                continue
            try:
                await coro_fn()
                # Clean exit — reset back-off.
                backoff = _BACKOFF_INITIAL
                self._record_success(source)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                self._record_failure(source)
                logger.warning(
                    "Source '%s' disconnected: %s — reconnecting in %.0f s",
                    source,
                    exc,
                    backoff,
                )
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, _BACKOFF_MAX)

    # ── Tick processing ────────────────────────────────────────────────────────

    async def process_tick(self, price: float, event_ts: float, source: str) -> None:
        """
        Validate and publish a single price tick.

        Parameters
        ----------
        price:
            Raw price value from the upstream source.
        event_ts:
            Unix timestamp (seconds) when the event was generated upstream.
        source:
            Human-readable source label (``finnhub``, ``twelvedata``, ``polygon``).
        """
        # Sanity-check the price range.
        if not (_PRICE_MIN < price < _PRICE_MAX):
            logger.debug("Source '%s' out-of-range price rejected: %s", source, price)
            return

        now = time.time()

        # Stale-tick rejection — discard ticks whose event timestamp is older
        # than _MAX_STALE_SECONDS.  A stale tick means the feed is lagging and
        # its price should not drive trading decisions.
        age_seconds = now - event_ts
        if age_seconds > _MAX_STALE_SECONDS:
            logger.warning(
                "STALE TICK [%s]: age=%.1f s exceeds limit=%.0f s — tick discarded",
                source,
                age_seconds,
                _MAX_STALE_SECONDS,
            )
            return

        latency_ms = age_seconds * 1000.0
        _LATENCY_GAUGE.labels(source=source).set(latency_ms)

        # Anomaly detection — compare against last validated price.
        async with self._price_lock:
            if self._last_price is not None:
                pct_change = abs((price - self._last_price) / self._last_price) * 100.0
                if pct_change > self.anomaly_jump_pct:
                    self._anomaly_counts[source] = self._anomaly_counts.get(source, 0) + 1
                    _ANOMALY_COUNTER_GAUGE.labels(source=source).set(self._anomaly_counts[source])
                    logger.warning(
                        "ANOMALY ALERT [%s]: %.2f%% jump (%.4f → %.4f) — tick discarded",
                        source,
                        pct_change,
                        self._last_price,
                        price,
                    )
                    return  # Discard anomalous tick; keep last known price.
            self._last_price = price

        _PRICE_GAUGE.labels(source=source).set(price)

        payload = {
            "symbol": self.symbol,
            "price": price,
            "timestamp": event_ts,
            "received_at": now,
            "source": source,
            "latency_ms": round(latency_ms, 2),
        }

        # Publish to Redis.
        if self._redis:
            try:
                await self._redis.rpush(_REDIS_QUEUE, json.dumps(payload))
                # Reset error counter on success so a reconnect is logged again.
                self._redis_publish_errors = 0
            except Exception as exc:
                self._redis_publish_errors += 1
                if self._redis_publish_errors == 1:
                    # Log the first failure at ERROR so operators are alerted.
                    logger.error("Redis publish error: %s", exc)
                else:
                    # Demote subsequent failures to DEBUG to avoid log flooding
                    # on every tick while Redis is down.
                    logger.debug("Redis publish error (repeated #%d): %s", self._redis_publish_errors, exc)

        logger.debug(
            "%s: %.4f @ %.0f ms [%s]",
            self.symbol,
            price,
            latency_ms,
            source,
        )

        # Notify subscribers.
        await self._broadcast(price)

    async def _broadcast(self, price: float) -> None:
        """Notify all subscribers concurrently; log but never propagate errors."""
        if not self._subscribers:
            return
        tasks = [
            asyncio.create_task(sub.on_new_price(price)) for sub in self._subscribers if hasattr(sub, "on_new_price")
        ]
        if tasks:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for sub, result in zip(self._subscribers, results, strict=False):
                if isinstance(result, Exception):
                    logger.error(
                        "Subscriber %s raised in on_new_price: %s",
                        type(sub).__name__,
                        result,
                    )

    # ── Finnhub stream ─────────────────────────────────────────────────────────

    async def _finnhub_stream(self) -> None:
        """
        Connect to Finnhub WebSocket and stream FOREX trades.

        Finnhub uses the symbol format ``OANDA:XAU_USD`` for spot gold.
        The ``data`` field in a trade message is a list; we iterate all trades.
        """
        url = f"wss://ws.finnhub.io?token={self._finnhub_key}"
        # Finnhub symbol for spot gold via OANDA feed.
        finnhub_symbol = "OANDA:XAU_USD"

        logger.info("Finnhub: connecting to %s", url.split("?", maxsplit=1)[0])
        async with websockets.connect(
            url,
            ping_interval=20,
            ping_timeout=10,
            close_timeout=5,
        ) as ws:
            # Consume the initial "connected" message.
            hello = await asyncio.wait_for(ws.recv(), timeout=10)
            logger.debug("Finnhub hello: %s", hello)

            # Subscribe to the gold symbol.
            await ws.send(json.dumps({"type": "subscribe", "symbol": finnhub_symbol}))
            logger.info("Finnhub: subscribed to %s", finnhub_symbol)

            while self._running:
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=30)
                except TimeoutError:
                    # Send a ping to keep the connection alive.
                    await ws.ping()
                    continue

                data = json.loads(raw)
                msg_type = data.get("type")

                if msg_type == "trade":
                    trades = data.get("data") or []
                    for trade in trades:
                        price = trade.get("p")
                        ts_ms = trade.get("t")
                        if price is None or ts_ms is None:
                            continue
                        await self.process_tick(
                            float(price),
                            float(ts_ms) / 1000.0,
                            "finnhub",
                        )
                elif msg_type == "ping":
                    await ws.send(json.dumps({"type": "pong"}))
                elif msg_type == "error":
                    logger.error("Finnhub error message: %s", data)
                    raise RuntimeError(f"Finnhub server error: {data.get('msg')}")

    # ── Twelve Data stream ─────────────────────────────────────────────────────

    async def _twelve_stream(self) -> None:
        """
        Connect to Twelve Data WebSocket and stream XAU/USD ticks.

        The Twelve Data Python SDK wraps the WebSocket; we use it directly
        to stay within the async event loop rather than spawning threads.
        """
        url = f"wss://ws.twelvedata.com/v1/quotes/price?apikey={self._twelve_key}"
        subscribe_msg = json.dumps(
            {
                "action": "subscribe",
                "params": {"symbols": "XAU/USD"},
            }
        )

        logger.info("Twelve Data: connecting")
        async with websockets.connect(
            url,
            ping_interval=20,
            ping_timeout=10,
            close_timeout=5,
        ) as ws:
            await ws.send(subscribe_msg)
            logger.info("Twelve Data: subscribed to XAU/USD")

            while self._running:
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=30)
                except TimeoutError:
                    await ws.ping()
                    continue

                data = json.loads(raw)
                event = data.get("event")

                if event == "price":
                    price = data.get("price")
                    # Twelve Data timestamps are ISO-8601 strings or Unix ms.
                    ts_raw = data.get("timestamp")
                    if price is None or ts_raw is None:
                        continue
                    # Normalise timestamp to Unix seconds.
                    if isinstance(ts_raw, int | float):
                        ts = float(ts_raw) / 1000.0 if ts_raw > 1e10 else float(ts_raw)
                    else:
                        try:
                            ts = datetime.fromisoformat(str(ts_raw)).timestamp()
                        except ValueError:
                            ts = time.time()
                    await self.process_tick(float(price), ts, "twelvedata")

                elif event == "heartbeat":
                    logger.debug("Twelve Data heartbeat received")

                elif event == "subscribe-status":
                    status = data.get("status")
                    if status != "ok":
                        logger.error("Twelve Data subscribe failed: %s", data)
                        raise RuntimeError(f"Twelve Data subscribe error: {data}")
                    logger.info("Twelve Data: subscription confirmed")

                elif event == "error":
                    logger.error("Twelve Data error: %s", data)
                    raise RuntimeError(f"Twelve Data server error: {data.get('message')}")

    # ── Polygon stream ─────────────────────────────────────────────────────────

    async def _polygon_stream(self) -> None:
        """
        Connect to Polygon.io Forex WebSocket and stream XAU/USD ticks.

        Polygon uses a two-step auth flow: connect → auth → subscribe.
        The forex channel uses ``C.`` prefix for currency pairs.
        """
        url = "wss://socket.polygon.io/forex"
        # Polygon symbol for spot gold quoted in USD.
        polygon_symbol = "C.XAU/USD"

        logger.info("Polygon: connecting to %s", url)
        async with websockets.connect(
            url,
            ping_interval=20,
            ping_timeout=10,
            close_timeout=5,
        ) as ws:
            # Step 1: authenticate.
            await ws.send(json.dumps({"action": "auth", "params": self._polygon_key}))
            auth_resp = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
            # auth_resp is a list; check the first element.
            auth_msg = auth_resp[0] if isinstance(auth_resp, list) else auth_resp
            if auth_msg.get("status") != "auth_success":
                raise RuntimeError(f"Polygon auth failed: {auth_msg}")
            logger.info("Polygon: authenticated")

            # Step 2: subscribe.
            await ws.send(json.dumps({"action": "subscribe", "params": polygon_symbol}))
            sub_resp = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
            sub_msg = sub_resp[0] if isinstance(sub_resp, list) else sub_resp
            if sub_msg.get("status") not in ("success", "subscribed"):
                raise RuntimeError(f"Polygon subscribe failed: {sub_msg}")
            logger.info("Polygon: subscribed to %s", polygon_symbol)

            while self._running:
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=30)
                except TimeoutError:
                    await ws.ping()
                    continue

                messages = json.loads(raw)
                if not isinstance(messages, list):
                    messages = [messages]

                for msg in messages:
                    ev = msg.get("ev")
                    if ev == "C":
                        # Polygon forex tick: ask price (``a``) is the best offer.
                        # Use mid-price: (bid + ask) / 2 when both are present.
                        bid = msg.get("b")
                        ask = msg.get("a")
                        if ask is None:
                            continue
                        price = (float(bid) + float(ask)) / 2.0 if bid else float(ask)
                        ts_ms = msg.get("t")
                        if ts_ms is None:
                            continue
                        await self.process_tick(
                            price,
                            float(ts_ms) / 1000.0,
                            "polygon",
                        )
                    elif ev == "status":
                        logger.debug("Polygon status: %s", msg)

    # ── Diagnostics ───────────────────────────────────────────────────────────

    def status(self) -> dict:
        """Return a snapshot of streamer health for monitoring / dashboards."""
        return {
            "symbol": self.symbol,
            "last_price": self._last_price,
            "anomaly_counts": dict(self._anomaly_counts),
            "fail_counts": dict(self._fail_counts),
            "circuit_breakers": {
                src: (
                    {
                        "open": True,
                        "open_at": self._circuit_open_at.get(src),
                        "cooldown_remaining": max(
                            0,
                            self.circuit_breaker_cooldown - (time.monotonic() - (self._circuit_open_at.get(src) or 0)),
                        ),
                    }
                    if self._circuit_open_at.get(src)
                    else {"open": False}
                )
                for src in ("finnhub", "twelvedata", "polygon")
            },
            "subscriber_count": len(self._subscribers),
            "is_running": self._running,
        }


# ── Standalone entry point ─────────────────────────────────────────────────────


async def _main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s — %(message)s",
    )
    streamer = NuclearStreamer()
    logger.info("Nuclear Broker-Free Streaming — starting")
    await streamer.run()


if __name__ == "__main__":
    asyncio.run(_main())

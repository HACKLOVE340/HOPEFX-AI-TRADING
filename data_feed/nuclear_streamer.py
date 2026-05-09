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
  * Records latency into a Prometheus Histogram and an in-process sorted
    sample buffer for p50/p95/p99/p999 percentile queries.
  * Deduplicates ticks using a SHA-1 fingerprint ring-buffer per source
    (configurable window via NUCLEAR_DEDUP_WINDOW_SECONDS).
  * Detects sequence gaps when the caller passes a ``sequence`` number
    (configurable threshold via NUCLEAR_SEQ_GAP_THRESHOLD).
  * Detects anomalous price jumps (configurable threshold).
  * Publishes validated ticks to a Redis list (``price_queue``).
  * Exposes Prometheus metrics (gauge + histogram) on port 9090.
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
  REDIS_HOST                    — Redis hostname (default: localhost)
  REDIS_PORT                    — Redis port    (default: 6379)
  REDIS_DB                      — Redis DB index (default: 0)
  NUCLEAR_MAX_STALE_SECONDS     — Max tick age before stale rejection (default: 30)
  NUCLEAR_DEDUP_WINDOW_SECONDS  — Dedup fingerprint TTL in seconds (default: 2.0)
  NUCLEAR_DEDUP_CACHE_MAX       — Max dedup cache entries per source (default: 1000)
  NUCLEAR_SEQ_GAP_THRESHOLD     — Sequence gap size that triggers a warning (default: 1)
"""

from __future__ import annotations

import asyncio
import bisect
import contextlib
import hashlib
import json
import logging
import os
import time
from collections import deque
from datetime import datetime
from typing import Any

import websockets
from prometheus_client import Gauge, Histogram, start_http_server

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

# Deduplication window: ticks with identical (source, price, event_ts) within
# this many seconds of each other are considered duplicates and discarded.
_DEDUP_WINDOW_SECONDS: float = float(os.environ.get("NUCLEAR_DEDUP_WINDOW_SECONDS", "2.0"))

# Maximum dedup cache entries per source before oldest are evicted.
_DEDUP_CACHE_MAX: int = int(os.environ.get("NUCLEAR_DEDUP_CACHE_MAX", "1000"))

# Sequence gap: if a source's sequence number jumps by more than this, log a
# gap warning.  Set to 0 to disable gap detection for sources without sequence
# numbers (gap detection is opt-in per source via process_tick_sequenced).
_SEQ_GAP_THRESHOLD: int = int(os.environ.get("NUCLEAR_SEQ_GAP_THRESHOLD", "1"))

# Latency histogram buckets in milliseconds.
_LATENCY_BUCKETS = (1, 5, 10, 25, 50, 100, 250, 500, 1000, 2500, 5000)

# ── Prometheus metrics (module-level singletons) ───────────────────────────────

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
_LATENCY_HISTOGRAM = Histogram(
    "price_stream_latency_ms_histogram",
    "End-to-end streaming latency distribution in milliseconds",
    ["source"],
    buckets=_LATENCY_BUCKETS,
)
_DEDUP_COUNTER_GAUGE = Gauge(
    "price_stream_dedup_total",
    "Total duplicate ticks discarded",
    ["source"],
)
_SEQ_GAP_COUNTER_GAUGE = Gauge(
    "price_stream_seq_gap_total",
    "Total sequence gaps detected",
    ["source"],
)
_CONSENSUS_GAUGE = Gauge(
    "price_stream_consensus_price",
    "Last consensus-validated XAUUSD price",
)
_CONSENSUS_REJECT_GAUGE = Gauge(
    "price_stream_consensus_rejected_total",
    "Total ticks rejected by consensus filter",
)

# ── Consensus configuration ───────────────────────────────────────────────────
# Require at least this many sources to agree within _CONSENSUS_TOLERANCE_PCT
# before the consensus price is published.  When fewer sources are active,
# the single-source price is published directly (graceful degradation).
_CONSENSUS_MIN_SOURCES: int = int(os.environ.get("NUCLEAR_CONSENSUS_MIN_SOURCES", "2"))
# Two prices are considered "in agreement" when they differ by less than this
# percentage of the reference price.
_CONSENSUS_TOLERANCE_PCT: float = float(os.environ.get("NUCLEAR_CONSENSUS_TOLERANCE_PCT", "0.05"))
# Maximum age (seconds) of a source's last tick before it is excluded from
# the consensus window.  Stale sources should not block consensus.
_CONSENSUS_WINDOW_SECONDS: float = float(os.environ.get("NUCLEAR_CONSENSUS_WINDOW_SECONDS", "5.0"))


async def _polygon_recv_status(
    ws,
    expected: "str | tuple[str, ...]",
    timeout: float = 10.0,
) -> "dict | None":
    """
    Read frames from a Polygon WebSocket until one matches *expected* status.

    Polygon sends a ``{"status": "connected"}`` frame immediately on connect,
    before any auth or subscribe response.  This helper skips those preamble
    frames so callers don't have to handle the ordering themselves.

    Returns the matching status dict, or None on timeout.
    """
    if isinstance(expected, str):
        expected = (expected,)
    deadline = asyncio.get_running_loop().time() + timeout
    while True:
        remaining = deadline - asyncio.get_running_loop().time()
        if remaining <= 0:
            return None
        try:
            raw = await asyncio.wait_for(ws.recv(), timeout=remaining)
        except (TimeoutError, asyncio.TimeoutError):
            return None
        frames = json.loads(raw)
        if not isinstance(frames, list):
            frames = [frames]
        for frame in frames:
            status = frame.get("status", "")
            if status in expected:
                return frame
            # Skip known preamble frames silently.
            if status == "connected":
                logger.debug("Polygon: skipping 'connected' preamble frame")
                continue
            # Any other unexpected status — return it so the caller can raise.
            return frame


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

        # Redis config: REDIS_URL takes precedence over individual REDIS_HOST/PORT vars.
        # This ensures NuclearStreamer honours the same connection as the rest of the system.
        _redis_url = os.getenv("REDIS_URL", "").strip()
        if _redis_url:
            import urllib.parse as _urlparse
            _parsed = _urlparse.urlparse(_redis_url)
            self._redis_host: str = _parsed.hostname or "localhost"
            self._redis_port: int = _parsed.port or 6379
            self._redis_db: int = int(_parsed.path.lstrip("/") or "0")
            self._redis_password: str | None = _parsed.password or None
        else:
            self._redis_host = os.getenv("REDIS_HOST", redis_host or "localhost")
            self._redis_port = int(os.getenv("REDIS_PORT", str(redis_port or 6379)))
            self._redis_db = int(os.getenv("REDIS_DB", str(redis_db or 0)))
            self._redis_password = os.getenv("REDIS_PASSWORD") or None

        # Suppress repeated Redis publish errors after the first — log once,
        # then demote to DEBUG so the log is not flooded on every tick.
        self._redis_publish_errors: int = 0

        # Shared state — protected by an asyncio lock.
        self._price_lock: asyncio.Lock = asyncio.Lock()
        self._last_price: float | None = None
        self._anomaly_counts: dict[str, int] = {}

        # ── Deduplication ─────────────────────────────────────────────────────
        # Per-source ring-buffer of (fingerprint, received_at) tuples.
        # A tick is a duplicate if its fingerprint appears in the buffer and
        # the prior occurrence is within _DEDUP_WINDOW_SECONDS.
        self._dedup_cache: dict[str, deque] = {}
        self._dedup_counts: dict[str, int] = {}

        # ── Sequence gap detection ────────────────────────────────────────────
        # Per-source last-seen sequence number.  None means no sequence seen yet.
        self._last_seq: dict[str, int | None] = {}
        self._seq_gap_counts: dict[str, int] = {}

        # ── Latency histogram (in-process, per source) ────────────────────────
        # Sorted list of latency samples (ms) for percentile computation.
        # Capped at 10 000 samples per source; oldest evicted when full.
        self._latency_samples: dict[str, list[float]] = {}
        self._latency_samples_max: int = 10_000

        # Circuit-breaker state per source.
        self._fail_counts: dict[str, int] = {}
        self._circuit_open_at: dict[str, float | None] = {}

        # Subscribers notified on every validated tick.
        self._subscribers: list[Any] = []

        # Redis client (created lazily in run()).
        self._redis: Any | None = None

        # Running flag.
        self._running: bool = False

        # ── Consensus state ───────────────────────────────────────────────────
        # Per-source latest validated price and the wall-clock time it arrived.
        # Used to compute a cross-source consensus before broadcasting.
        self._source_prices: dict[str, tuple[float, float]] = {}  # source → (price, received_at)
        self._consensus_reject_count: int = 0

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
                # Fail fast when Redis is unreachable so a down broker does not
                # stall the tick-processing loop for the OS TCP timeout (~2 min).
                socket_connect_timeout=2.0,
                socket_timeout=2.0,
                retry_on_timeout=False,
            )
            logger.info(
                "Redis client created: %s:%d db=%d (connect_timeout=2s)",
                self._redis_host,
                self._redis_port,
                self._redis_db,
            )

        tasks = []
        if self._finnhub_key:
            tasks.append(asyncio.create_task(self._run_with_backoff("finnhub", self._finnhub_stream)))
        else:
            logger.info("FINNHUB_API_KEY not set — Finnhub stream disabled")

        if self._twelve_key and _TWELVE_AVAILABLE:
            tasks.append(asyncio.create_task(self._run_with_backoff("twelvedata", self._twelve_stream)))
        elif not self._twelve_key:
            logger.info("TWELVE_API_KEY not set — Twelve Data stream disabled")

        if self._polygon_key:
            tasks.append(asyncio.create_task(self._run_with_backoff("polygon", self._polygon_stream)))
        else:
            logger.info("POLYGON_API_KEY not set — Polygon stream disabled")

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
                "Circuit breaker OPEN for source '%s' after %d failures — "
                "will retry in %.0f s",
                source,
                self._fail_counts[source],
                self.circuit_breaker_cooldown,
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
                # Clean exit (WebSocket closed with code 1000) — reset back-off.
                # This is normal behaviour when the server closes the connection
                # gracefully; reconnect immediately without counting as a failure.
                backoff = _BACKOFF_INITIAL
                self._record_success(source)
                logger.debug(
                    "Source '%s' disconnected cleanly — reconnecting immediately",
                    source,
                )
            except asyncio.CancelledError:
                break
            except Exception as exc:
                self._record_failure(source)
                exc_str = str(exc)
                # "sent 1000 (OK)" is a clean WebSocket close masquerading as
                # an exception in some websockets library versions — treat it
                # as a non-error reconnect and log at DEBUG.
                if "sent 1000" in exc_str or "1000 (OK)" in exc_str:
                    logger.debug(
                        "Source '%s' closed cleanly (code 1000) — reconnecting in %.0f s",
                        source,
                        backoff,
                    )
                else:
                    logger.warning(
                        "Source '%s' disconnected: %s — reconnecting in %.0f s",
                        source,
                        exc,
                        backoff,
                    )
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, _BACKOFF_MAX)

    # ── Tick processing ────────────────────────────────────────────────────────

    async def process_tick(
        self,
        price: float,
        event_ts: float,
        source: str,
        sequence: int | None = None,
    ) -> None:
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
        sequence:
            Optional monotonic sequence number from the upstream source.
            When provided, gaps larger than ``_SEQ_GAP_THRESHOLD`` are logged
            and counted.  Pass ``None`` for sources that do not emit sequence
            numbers.
        """
        # Sanity-check the price range.
        if not (_PRICE_MIN < price < _PRICE_MAX):
            logger.debug("Source '%s' out-of-range price rejected: %s", source, price)
            return

        now = time.time()

        # ── Deduplication ─────────────────────────────────────────────────────
        # Fingerprint = SHA-1 of (source, price-as-8-byte-hex, event_ts-as-8-byte-hex).
        # SHA-1 is used for speed; collision resistance is not required here.
        fp_raw = f"{source}:{price:.6f}:{event_ts:.3f}"
        fingerprint = hashlib.sha1(fp_raw.encode(), usedforsecurity=False).hexdigest()

        cache = self._dedup_cache.setdefault(source, deque(maxlen=_DEDUP_CACHE_MAX))
        # Evict entries older than the dedup window.
        while cache and (now - cache[0][1]) > _DEDUP_WINDOW_SECONDS:
            cache.popleft()
        # Check for duplicate fingerprint in the active window.
        if any(fp == fingerprint for fp, _ in cache):
            self._dedup_counts[source] = self._dedup_counts.get(source, 0) + 1
            _DEDUP_COUNTER_GAUGE.labels(source=source).set(self._dedup_counts[source])
            logger.debug(
                "DUPLICATE TICK [%s]: fingerprint=%s — discarded (total=%d)",
                source,
                fingerprint[:8],
                self._dedup_counts[source],
            )
            return
        cache.append((fingerprint, now))

        # ── Sequence gap detection ────────────────────────────────────────────
        if sequence is not None:
            last_seq = self._last_seq.get(source)
            if last_seq is not None:
                gap = sequence - last_seq
                if gap > _SEQ_GAP_THRESHOLD:
                    self._seq_gap_counts[source] = self._seq_gap_counts.get(source, 0) + 1
                    _SEQ_GAP_COUNTER_GAUGE.labels(source=source).set(self._seq_gap_counts[source])
                    logger.warning(
                        "SEQUENCE GAP [%s]: expected seq=%d got seq=%d gap=%d (total_gaps=%d)",
                        source,
                        last_seq + 1,
                        sequence,
                        gap,
                        self._seq_gap_counts[source],
                    )
                elif gap < 0:
                    # Out-of-order tick — discard to avoid price regression.
                    logger.debug(
                        "OUT-OF-ORDER TICK [%s]: seq=%d last_seq=%d — discarded",
                        source,
                        sequence,
                        last_seq,
                    )
                    return
            self._last_seq[source] = sequence

        # ── Stale-tick rejection ──────────────────────────────────────────────
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

        # ── Latency metrics ───────────────────────────────────────────────────
        _LATENCY_GAUGE.labels(source=source).set(latency_ms)
        _LATENCY_HISTOGRAM.labels(source=source).observe(latency_ms)

        # In-process sorted latency sample buffer for percentile queries.
        samples = self._latency_samples.setdefault(source, [])
        bisect.insort(samples, latency_ms)
        if len(samples) > self._latency_samples_max:
            samples.pop(0)  # evict oldest (smallest) value

        # ── Anomaly detection ─────────────────────────────────────────────────
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

        # ── Consensus filter ──────────────────────────────────────────────────
        # Record this source's latest price, then check whether enough sources
        # agree within _CONSENSUS_TOLERANCE_PCT.  When consensus is reached,
        # publish the median of the agreeing prices.  When fewer than
        # _CONSENSUS_MIN_SOURCES are active (e.g. only one API key is set),
        # fall through and publish the single-source price directly so the
        # system degrades gracefully rather than going silent.
        self._source_prices[source] = (price, now)

        # Evict stale source entries outside the consensus window.
        stale_cutoff = now - _CONSENSUS_WINDOW_SECONDS
        self._source_prices = {
            s: (p, t)
            for s, (p, t) in self._source_prices.items()
            if t >= stale_cutoff
        }

        active_sources = list(self._source_prices.items())
        consensus_price: float | None = None

        if len(active_sources) < _CONSENSUS_MIN_SOURCES:
            # Graceful degradation: not enough sources — publish directly.
            consensus_price = price
        else:
            # Find the largest group of sources whose prices agree within
            # _CONSENSUS_TOLERANCE_PCT of each other.
            best_group: list[float] = []
            for ref_src, (ref_price, _) in active_sources:
                group = [
                    p for _, (p, _) in active_sources
                    if ref_price > 0 and abs(p - ref_price) / ref_price * 100 <= _CONSENSUS_TOLERANCE_PCT
                ]
                if len(group) > len(best_group):
                    best_group = group

            if len(best_group) >= _CONSENSUS_MIN_SOURCES:
                # Consensus reached — use the median of the agreeing prices.
                sorted_group = sorted(best_group)
                mid = len(sorted_group) // 2
                consensus_price = (
                    sorted_group[mid]
                    if len(sorted_group) % 2 == 1
                    else (sorted_group[mid - 1] + sorted_group[mid]) / 2.0
                )
                _CONSENSUS_GAUGE.set(consensus_price)
                logger.debug(
                    "Consensus: %.4f from %d/%d sources (triggered by %s)",
                    consensus_price,
                    len(best_group),
                    len(active_sources),
                    source,
                )
            else:
                # No consensus — discard this tick.
                self._consensus_reject_count += 1
                _CONSENSUS_REJECT_GAUGE.set(self._consensus_reject_count)
                logger.debug(
                    "Consensus MISS [%s]: price=%.4f — only %d/%d sources agree "
                    "(need %d, tolerance=%.2f%%). Tick discarded (total_rejected=%d).",
                    source,
                    price,
                    len(best_group),
                    len(active_sources),
                    _CONSENSUS_MIN_SOURCES,
                    _CONSENSUS_TOLERANCE_PCT,
                    self._consensus_reject_count,
                )
                return  # Do not publish — wait for more sources to agree.

        payload = {
            "symbol": self.symbol,
            "price": consensus_price,
            "timestamp": event_ts,
            "received_at": now,
            "source": source,
            "latency_ms": round(latency_ms, 2),
            "sequence": sequence,
            "fingerprint": fingerprint,
            "consensus_sources": len(active_sources),
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
                    # Log the first failure as WARNING — Redis being down is
                    # expected in dev/offline environments; ticks still flow
                    # to subscribers via the in-process broadcast path.
                    logger.warning("Redis publish error: %s", exc)
                else:
                    # Suppress subsequent failures to DEBUG to avoid log flooding
                    # on every tick while Redis is down.
                    logger.debug(
                        "Redis publish error (suppressed #%d): %s",
                        self._redis_publish_errors,
                        exc,
                    )

        logger.debug(
            "%s: %.4f (consensus=%.4f) @ %.0f ms [%s] seq=%s",
            self.symbol,
            price,
            consensus_price,
            latency_ms,
            source,
            sequence,
        )

        # Notify subscribers with the consensus-validated price.
        await self._broadcast(consensus_price)

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
                except (TimeoutError, asyncio.TimeoutError):
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
                except (TimeoutError, asyncio.TimeoutError):
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
            # Polygon sends a {"status":"connected"} frame immediately on connect
            # before the auth response arrives.  Drain any such frames first so
            # we don't mistake the connection ack for an auth failure.
            await ws.send(json.dumps({"action": "auth", "params": self._polygon_key}))
            auth_msg = await _polygon_recv_status(ws, expected="auth_success", timeout=10)
            if auth_msg is None:
                raise RuntimeError("Polygon auth timed out")
            if auth_msg.get("status") != "auth_success":
                raise RuntimeError(f"Polygon auth failed: {auth_msg}")
            logger.info("Polygon: authenticated")

            # Step 2: subscribe.
            await ws.send(json.dumps({"action": "subscribe", "params": polygon_symbol}))
            sub_msg = await _polygon_recv_status(ws, expected=("success", "subscribed"), timeout=10)
            if sub_msg is None:
                raise RuntimeError("Polygon subscribe timed out")
            if sub_msg.get("status") not in ("success", "subscribed"):
                raise RuntimeError(f"Polygon subscribe failed: {sub_msg}")
            logger.info("Polygon: subscribed to %s", polygon_symbol)

            while self._running:
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=30)
                except (TimeoutError, asyncio.TimeoutError):
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

    def latency_percentile(self, source: str, pct: float) -> float | None:
        """
        Return the *pct*-th percentile latency in milliseconds for *source*.

        Uses the in-process sorted sample buffer.  Returns None if no samples
        have been recorded yet.

        Parameters
        ----------
        source:
            Source label (e.g. ``"finnhub"``).
        pct:
            Percentile in the range [0, 100].  E.g. 99.0 for p99.
        """
        samples = self._latency_samples.get(source)
        if not samples:
            return None
        idx = max(0, min(len(samples) - 1, int(len(samples) * pct / 100.0)))
        return samples[idx]

    def latency_histogram_snapshot(self, source: str) -> dict[str, float | None]:
        """Return p50/p95/p99/p999 latency snapshot for *source*."""
        return {
            "p50_ms": self.latency_percentile(source, 50.0),
            "p95_ms": self.latency_percentile(source, 95.0),
            "p99_ms": self.latency_percentile(source, 99.0),
            "p999_ms": self.latency_percentile(source, 99.9),
            "sample_count": len(self._latency_samples.get(source) or []),
        }

    def status(self) -> dict:
        """Return a snapshot of streamer health for monitoring / dashboards."""
        sources = ("finnhub", "twelvedata", "polygon")
        return {
            "symbol": self.symbol,
            "last_price": self._last_price,
            "anomaly_counts": dict(self._anomaly_counts),
            "dedup_counts": dict(self._dedup_counts),
            "seq_gap_counts": dict(self._seq_gap_counts),
            "last_sequences": {src: self._last_seq.get(src) for src in sources},
            "latency_histograms": {src: self.latency_histogram_snapshot(src) for src in sources},
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
                for src in sources
            },
            "subscriber_count": len(self._subscribers),
            "is_running": self._running,
            "consensus": {
                "min_sources_required": _CONSENSUS_MIN_SOURCES,
                "tolerance_pct": _CONSENSUS_TOLERANCE_PCT,
                "window_seconds": _CONSENSUS_WINDOW_SECONDS,
                "active_sources": {
                    src: {"price": p, "age_s": round(time.time() - t, 2)}
                    for src, (p, t) in self._source_prices.items()
                },
                "consensus_reject_count": self._consensus_reject_count,
            },
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

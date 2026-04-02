# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
data_layer/feeds/gold/base.py
=============================
Abstract base class for all gold price feed adapters.

Every adapter must implement:
  - fetch_tick()  → GoldTick   (single REST poll)
  - name          → FeedSource (enum identity)

Optional:
  - fetch_ohlcv() → List[OHLCVBar]  (historical bars)
  - start_stream() / stop_stream()  (WebSocket feeds)

The base class handles:
  - Exponential backoff with jitter on HTTP errors
  - Per-adapter rate limiting (respects API tier limits)
  - Circuit breaker: opens after N consecutive errors, half-opens after 60s
  - Structured error logging with source tagging
  - Prometheus metrics per source (latency, errors, ticks)
  - Automatic lineage_id injection
"""

from __future__ import annotations

import asyncio
import logging
import os
import random
import time
import uuid
from abc import ABC, abstractmethod
from datetime import datetime, timezone

UTC = timezone.utc
from enum import Enum

import aiohttp

from data_layer.types import FeedSource, GoldTick, OHLCVBar

logger = logging.getLogger(__name__)

_HTTP_TIMEOUT = aiohttp.ClientTimeout(total=10.0, connect=5.0)

_CB_OPEN_AFTER_ERRORS = int(os.getenv("FEED_CB_OPEN_ERRORS", "5"))
_CB_HALF_OPEN_AFTER_S = float(os.getenv("FEED_CB_HALF_OPEN_S", "60.0"))


class CircuitState(str, Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class GoldFeedBase(ABC):
    """Abstract base for all gold price feed adapters."""

    name: FeedSource
    _base_url: str = ""
    _api_key_env: str = ""

    def __init__(self) -> None:
        self._api_key: str = os.getenv(self._api_key_env, "")
        self._session: aiohttp.ClientSession | None = None
        self._last_call_ts: float = 0.0
        self._min_interval_s: float = 1.0
        self._consecutive_errors: int = 0
        self._total_calls: int = 0
        self._total_errors: int = 0
        self._total_ticks: int = 0
        self._cb_state: CircuitState = CircuitState.CLOSED
        self._cb_opened_at: float = 0.0
        self._last_error_msg: str = ""
        self._prom_ticks = None
        self._prom_errors = None
        self._prom_latency = None
        self._prom_cb_state = None
        self._init_prometheus()

    def _init_prometheus(self) -> None:
        try:
            from prometheus_client import Counter, Gauge, Histogram, REGISTRY

            src = self.name.value

            def _counter(name, doc, labels=None):
                try:
                    return Counter(name, doc, labels or [])
                except ValueError:
                    return REGISTRY._names_to_collectors.get(name)

            def _histogram(name, doc, labels=None, buckets=None):
                kwargs = {"labelnames": labels or []}
                if buckets:
                    kwargs["buckets"] = buckets
                try:
                    return Histogram(name, doc, **kwargs)
                except ValueError:
                    return REGISTRY._names_to_collectors.get(name)

            def _gauge(name, doc, labels=None):
                try:
                    return Gauge(name, doc, labels or [])
                except ValueError:
                    return REGISTRY._names_to_collectors.get(name)

            self._prom_ticks = _counter(
                f"hopefx_feed_{src}_ticks_total",
                f"Total ticks fetched from {src}",
            )
            self._prom_errors = _counter(
                f"hopefx_feed_{src}_errors_total",
                f"Total errors from {src}",
                ["reason"],
            )
            self._prom_latency = _histogram(
                f"hopefx_feed_{src}_fetch_latency_ms",
                f"Fetch latency for {src} in ms",
                buckets=[10, 25, 50, 100, 250, 500, 1000, 2500, 5000],
            )
            self._prom_cb_state = _gauge(
                f"hopefx_feed_{src}_circuit_open",
                f"1 if circuit breaker is open for {src}",
            )
        except Exception as _exc:
            logger.debug("Suppressed exception: %s", _exc)

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            connector = aiohttp.TCPConnector(
                limit=10,
                ttl_dns_cache=300,
                enable_cleanup_closed=True,
            )
            self._session = aiohttp.ClientSession(
                timeout=_HTTP_TIMEOUT,
                connector=connector,
            )
        return self._session

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None

    # ── Circuit breaker ───────────────────────────────────────────────────────

    def _check_circuit(self) -> bool:
        if self._cb_state == CircuitState.CLOSED:
            return True
        if self._cb_state == CircuitState.OPEN:
            if (time.monotonic() - self._cb_opened_at) >= _CB_HALF_OPEN_AFTER_S:
                self._cb_state = CircuitState.HALF_OPEN
                logger.info("%s circuit: HALF-OPEN", self.name.value)
                return True
            return False
        return True  # HALF_OPEN — allow one probe

    def _on_success(self) -> None:
        if self._cb_state == CircuitState.HALF_OPEN:
            self._cb_state = CircuitState.CLOSED
            self._consecutive_errors = 0
            logger.info("%s circuit: CLOSED (recovered)", self.name.value)
        if self._prom_cb_state:
            self._prom_cb_state.set(0)

    def _on_error(self, reason: str = "unknown", msg: str = "") -> None:
        self._consecutive_errors += 1
        self._total_errors += 1
        if msg:
            self._last_error_msg = msg
        if self._prom_errors:
            try:
                self._prom_errors.labels(reason=reason).inc()
            except Exception as _exc:
                logger.debug("Suppressed exception: %s", _exc)
        if self._consecutive_errors >= _CB_OPEN_AFTER_ERRORS and self._cb_state != CircuitState.OPEN:
            self._cb_state = CircuitState.OPEN
            self._cb_opened_at = time.monotonic()
            logger.error(
                "%s circuit: OPEN after %d consecutive errors",
                self.name.value,
                self._consecutive_errors,
            )
            if self._prom_cb_state:
                self._prom_cb_state.set(1)

    # ── Rate limiting ─────────────────────────────────────────────────────────

    async def _rate_limit(self) -> None:
        elapsed = time.monotonic() - self._last_call_ts
        if elapsed < self._min_interval_s:
            await asyncio.sleep(self._min_interval_s - elapsed)
        self._last_call_ts = time.monotonic()

    # ── HTTP helpers ──────────────────────────────────────────────────────────

    async def _get(
        self,
        url: str,
        params: dict | None = None,
        headers: dict | None = None,
    ) -> dict:
        """Authenticated GET with exponential backoff and circuit breaker."""
        if not self._check_circuit():
            raise RuntimeError(f"{self.name.value} circuit breaker OPEN — skipping call")

        await self._rate_limit()
        session = await self._get_session()
        backoff = 1.0
        t0 = time.monotonic()

        for attempt in range(4):
            try:
                async with session.get(url, params=params, headers=headers) as resp:
                    self._total_calls += 1

                    if resp.status == 429:
                        retry_after = float(resp.headers.get("Retry-After", backoff))
                        wait = min(retry_after + random.uniform(0, 1.0), 120.0)  # nosec B311 - retry jitter, not cryptographic
                        logger.warning(
                            "%s rate-limited — sleeping %.1fs (attempt %d)",
                            self.name.value,
                            wait,
                            attempt + 1,
                        )
                        await asyncio.sleep(wait)
                        backoff = min(backoff * 2, 120.0)
                        continue

                    if resp.status in (401, 403):
                        msg = f"HTTP {resp.status} — check {self._api_key_env}"
                        self._on_error("auth", msg=msg)
                        raise RuntimeError(f"{self.name.value}: {msg}")

                    if resp.status >= 500:
                        raise aiohttp.ClientResponseError(
                            resp.request_info,
                            resp.history,
                            status=resp.status,
                        )

                    resp.raise_for_status()

                    latency_ms = (time.monotonic() - t0) * 1000
                    if self._prom_latency:
                        self._prom_latency.observe(latency_ms)

                    self._on_success()
                    return await resp.json(content_type=None)

            except (TimeoutError, aiohttp.ClientError) as exc:
                self._on_error("http", msg=str(exc))
                # Full-jitter: sleep between 0 and cap
                wait = random.uniform(0, min(backoff, 30.0))  # nosec B311 - full-jitter backoff, not cryptographic
                logger.warning(
                    "%s HTTP error attempt=%d/4 err=%s — retry in %.2fs",
                    self.name.value,
                    attempt + 1,
                    exc,
                    wait,
                )
                if attempt < 3:
                    await asyncio.sleep(wait)
                    backoff = min(backoff * 2, 30.0)
                else:
                    raise

        raise RuntimeError(f"{self.name.value}: all 4 retry attempts exhausted")

    # ── Abstract interface ────────────────────────────────────────────────────

    @abstractmethod
    async def fetch_tick(self) -> GoldTick:
        """Fetch the current XAU/USD price. Must return a GoldTick."""
        ...

    async def fetch_ohlcv(self, timeframe: str = "1h", limit: int = 200) -> list[OHLCVBar]:
        """Fetch historical OHLCV bars. Override in adapters that support it."""
        return []

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _make_tick(
        self,
        mid: float,
        bid: float | None = None,
        ask: float | None = None,
        spread_pct: float = 0.0002,
        raw: dict | None = None,
    ) -> GoldTick:
        """
        Construct a GoldTick from a mid price.

        If bid/ask are not provided, synthesise from a typical gold spread
        (default 0.02% each side ≈ $0.40 on $2000 gold).
        """
        half_spread = mid * spread_pct / 2
        bid = bid if (bid is not None and bid > 0) else mid - half_spread
        ask = ask if (ask is not None and ask > 0) else mid + half_spread

        if bid >= ask:
            bid = mid - half_spread
            ask = mid + half_spread

        tick = GoldTick(
            symbol="XAU_USD",
            timestamp=datetime.now(UTC),
            bid=round(bid, 4),
            ask=round(ask, 4),
            mid=round(mid, 4),
            source=self.name,
            spread=round(ask - bid, 4),
            lineage_id=str(uuid.uuid4()),
            raw=raw,
        )
        self._total_ticks += 1
        if self._prom_ticks:
            self._prom_ticks.inc()
        return tick

    @property
    def is_configured(self) -> bool:
        return bool(self._api_key)

    @property
    def circuit_state(self) -> CircuitState:
        return self._cb_state

    def health_summary(self) -> dict:
        return {
            "source": self.name.value,
            "configured": self.is_configured,
            "circuit_state": self._cb_state.value,
            "total_calls": self._total_calls,
            "total_ticks": self._total_ticks,
            "total_errors": self._total_errors,
            "consecutive_errors": self._consecutive_errors,
            "error_rate": round(self._total_errors / max(self._total_calls, 1), 4),
            "last_error": self._last_error_msg or None,
        }

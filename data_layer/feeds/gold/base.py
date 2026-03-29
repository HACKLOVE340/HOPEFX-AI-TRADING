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
  - Structured error logging with source tagging
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
from typing import List, Optional

import aiohttp

from data_layer.types import FeedSource, GoldTick, OHLCVBar

logger = logging.getLogger(__name__)

# Default HTTP timeout for all gold feed requests
_HTTP_TIMEOUT = aiohttp.ClientTimeout(total=10.0, connect=5.0)


class GoldFeedBase(ABC):
    """Abstract base for all gold price feed adapters."""

    # Subclasses set these
    name: FeedSource
    _base_url: str = ""
    _api_key_env: str = ""

    def __init__(self) -> None:
        self._api_key: str = os.getenv(self._api_key_env, "")
        self._session: Optional[aiohttp.ClientSession] = None
        self._last_call_ts: float = 0.0
        self._min_interval_s: float = 1.0   # subclasses override
        self._consecutive_errors: int = 0
        self._total_calls: int = 0
        self._total_errors: int = 0

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(timeout=_HTTP_TIMEOUT)
        return self._session

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()

    # ── Rate limiting ─────────────────────────────────────────────────────────

    async def _rate_limit(self) -> None:
        """Enforce minimum interval between calls."""
        elapsed = time.monotonic() - self._last_call_ts
        if elapsed < self._min_interval_s:
            await asyncio.sleep(self._min_interval_s - elapsed)
        self._last_call_ts = time.monotonic()

    # ── HTTP helpers ──────────────────────────────────────────────────────────

    async def _get(self, url: str, params: dict = None, headers: dict = None) -> dict:
        """
        Authenticated GET with exponential backoff.

        Returns parsed JSON dict. Raises on unrecoverable errors.
        """
        await self._rate_limit()
        session = await self._get_session()
        backoff = 1.0
        for attempt in range(4):
            try:
                async with session.get(url, params=params, headers=headers) as resp:
                    self._total_calls += 1
                    if resp.status == 429:
                        wait = backoff + random.uniform(0, 0.5)
                        logger.warning(
                            "%s rate-limited — sleeping %.1fs", self.name.value, wait
                        )
                        await asyncio.sleep(wait)
                        backoff = min(backoff * 2, 60.0)
                        continue
                    if resp.status >= 500:
                        raise aiohttp.ClientResponseError(
                            resp.request_info, resp.history, status=resp.status
                        )
                    resp.raise_for_status()
                    self._consecutive_errors = 0
                    return await resp.json(content_type=None)
            except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
                self._consecutive_errors += 1
                self._total_errors += 1
                wait = backoff + random.uniform(0, 0.5)
                logger.warning(
                    "%s HTTP error attempt=%d err=%s — retry in %.1fs",
                    self.name.value, attempt + 1, exc, wait,
                )
                if attempt < 3:
                    await asyncio.sleep(wait)
                    backoff = min(backoff * 2, 30.0)
                else:
                    raise

    # ── Abstract interface ────────────────────────────────────────────────────

    @abstractmethod
    async def fetch_tick(self) -> GoldTick:
        """Fetch the current XAU/USD price. Must return a GoldTick."""
        ...

    async def fetch_ohlcv(
        self, timeframe: str = "1h", limit: int = 200
    ) -> List[OHLCVBar]:
        """Fetch historical OHLCV bars. Override in adapters that support it."""
        return []

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _make_tick(
        self,
        mid: float,
        bid: Optional[float] = None,
        ask: Optional[float] = None,
        spread_pct: float = 0.0002,
        raw: Optional[dict] = None,
    ) -> GoldTick:
        """
        Construct a GoldTick from a mid price.

        If bid/ask are not provided by the API, synthesise them from
        a typical gold spread (default 0.02% each side).
        """
        half_spread = mid * spread_pct / 2
        bid = bid if bid is not None else mid - half_spread
        ask = ask if ask is not None else mid + half_spread
        return GoldTick(
            symbol    = "XAU_USD",
            timestamp = datetime.now(timezone.utc),
            bid       = round(bid, 4),
            ask       = round(ask, 4),
            mid       = round(mid, 4),
            source    = self.name,
            spread    = round(ask - bid, 4),
            lineage_id= str(uuid.uuid4()),
            raw       = raw,
        )

    @property
    def is_configured(self) -> bool:
        """True if the API key is present."""
        return bool(self._api_key)

    def health_summary(self) -> dict:
        return {
            "source":             self.name.value,
            "configured":         self.is_configured,
            "total_calls":        self._total_calls,
            "total_errors":       self._total_errors,
            "consecutive_errors": self._consecutive_errors,
            "error_rate":         (
                self._total_errors / max(self._total_calls, 1)
            ),
        }

# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
data_layer/feeds/news/base.py
==============================
Abstract base for all news feed adapters.

Every adapter must implement:
  - fetch_articles(limit) → List[NewsArticle]
  - name                  → NewsSource

The base class handles:
  - HTTP with exponential backoff
  - Deduplication via article_id set (prevents same article scored twice)
  - Rate limiting per API tier
  - Gold relevance pre-filter (rejects articles with zero gold keywords)
"""

from __future__ import annotations

import hashlib
import logging
import os
import random
import time
from abc import ABC, abstractmethod

import aiohttp

from data_layer.types import NewsArticle, NewsSource

logger = logging.getLogger(__name__)

_HTTP_TIMEOUT = aiohttp.ClientTimeout(total=15.0, connect=5.0)

# Keywords that indicate gold/macro relevance — used for pre-filtering
GOLD_KEYWORDS: set[str] = {
    "gold",
    "xau",
    "bullion",
    "precious metal",
    "safe haven",
    "federal reserve",
    "fed",
    "interest rate",
    "inflation",
    "cpi",
    "dollar",
    "dxy",
    "treasury",
    "yield",
    "geopolit",
    "war",
    "conflict",
    "recession",
    "gdp",
    "unemployment",
    "nonfarm",
    "fomc",
    "powell",
    "central bank",
    "monetary policy",
    "quantitative",
    "taper",
    "silver",
    "platinum",
    "commodity",
    "etf",
    "gld",
    "iau",
    "china",
    "russia",
    "ukraine",
    "middle east",
    "opec",
    "oil",
}


class NewsFeedBase(ABC):
    """Abstract base for all news feed adapters."""

    name: NewsSource
    _api_key_env: str = ""
    _min_interval_s: float = 60.0

    def __init__(self) -> None:
        self._api_key: str = os.getenv(self._api_key_env, "")
        self._session: aiohttp.ClientSession | None = None
        self._seen_ids: set[str] = set()
        self._last_call_ts: float = 0.0
        self._total_fetched: int = 0
        self._total_errors: int = 0

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(timeout=_HTTP_TIMEOUT)
        return self._session

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()

    async def _rate_limit(self) -> None:
        import asyncio

        elapsed = time.monotonic() - self._last_call_ts
        if elapsed < self._min_interval_s:
            await asyncio.sleep(self._min_interval_s - elapsed)
        self._last_call_ts = time.monotonic()

    async def _get(self, url: str, params: dict | None = None, headers: dict | None = None) -> dict:
        import asyncio

        await self._rate_limit()
        session = await self._get_session()
        backoff = 1.0
        for attempt in range(4):
            try:
                async with session.get(url, params=params, headers=headers) as resp:
                    if resp.status == 429:
                        wait = backoff + random.uniform(0, 1.0)  # nosec B311 - rate-limit retry jitter, not cryptographic
                        logger.warning("%s rate-limited — sleeping %.1fs", self.name.value, wait)
                        await asyncio.sleep(wait)
                        backoff = min(backoff * 2, 120.0)
                        continue
                    resp.raise_for_status()
                    return await resp.json(content_type=None)
            except (TimeoutError, aiohttp.ClientError) as exc:
                self._total_errors += 1
                # DNS / connection-refused errors are permanent for this session;
                # retrying will not help until the host is reachable again.
                exc_str = str(exc)
                is_permanent = isinstance(exc, aiohttp.ClientConnectorError) and (
                    "Could not contact DNS servers" in exc_str
                    or "Name or service not known" in exc_str
                    or "Connection refused" in exc_str
                )
                # 401/403 mean the API key is invalid or the plan doesn't permit
                # this endpoint — retrying never helps. Stop immediately and log
                # once (the caller logs a summary) instead of hammering 4x/cycle.
                is_auth_error = isinstance(exc, aiohttp.ClientResponseError) and exc.status in (401, 403)
                if is_permanent or is_auth_error:
                    logger.debug(
                        "%s permanent error (%s) — skipping retries",
                        self.name.value,
                        exc,
                    )
                    raise
                wait = backoff + random.uniform(0, 0.5)  # nosec B311 - retry jitter, not cryptographic
                logger.warning(
                    "%s HTTP error attempt=%d: %s — retry %.1fs",
                    self.name.value,
                    attempt + 1,
                    exc,
                    wait,
                )
                if attempt < 3:
                    await asyncio.sleep(wait)
                    backoff = min(backoff * 2, 60.0)
                else:
                    raise

    @abstractmethod
    async def fetch_articles(self, limit: int = 50) -> list[NewsArticle]:
        """Fetch latest gold-relevant news articles."""
        ...

    def _is_gold_relevant(self, text: str) -> bool:
        """Quick keyword pre-filter — avoids scoring irrelevant articles."""
        lower = text.lower()
        return any(kw in lower for kw in GOLD_KEYWORDS)

    def _dedup_id(self, raw_id: str) -> str:
        """Stable article ID — SHA-256 of source + raw_id."""
        return hashlib.sha256(f"{self.name.value}:{raw_id}".encode()).hexdigest()[:16]

    def _is_new(self, article_id: str) -> bool:
        """Return True if this article hasn't been seen before."""
        if article_id in self._seen_ids:
            return False
        self._seen_ids.add(article_id)
        # Bound memory — keep last 10,000 IDs
        if len(self._seen_ids) > 10_000:
            self._seen_ids = set(list(self._seen_ids)[-5_000:])
        return True

    @property
    def is_configured(self) -> bool:
        return bool(self._api_key)

    def health_summary(self) -> dict:
        return {
            "source": self.name.value,
            "configured": self.is_configured,
            "total_fetched": self._total_fetched,
            "total_errors": self._total_errors,
        }

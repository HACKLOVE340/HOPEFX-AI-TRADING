# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
data_layer/feeds/gold/metals_dev.py
=====================================
Metals.dev adapter — https://metals.dev/

Free tier: 100 requests/month
Paid tiers: up to 100,000 requests/month, real-time WebSocket available

REST endpoint: GET https://api.metals.dev/v1/latest?api_key=KEY&currency=USD&unit=toz
Response: {"status":"success","currencies":{"USD":{"XAU":1985.5}}}

WebSocket: wss://stream.metals.dev/v1/stream?api_key=KEY
(Paid tier only — falls back to REST polling on free tier)
"""

from __future__ import annotations

import asyncio
import logging

from data_layer.feeds.gold.base import GoldFeedBase
from data_layer.types import FeedSource, GoldTick
import contextlib

logger = logging.getLogger(__name__)

_REST_BASE = "https://api.metals.dev/v1"
_WS_URL = "wss://stream.metals.dev/v1/stream"


class MetalsDevFeed(GoldFeedBase):
    """Metals.dev — REST polling with optional WebSocket upgrade."""

    name = FeedSource.METALS_DEV
    _api_key_env = "METALS_DEV_KEY"
    _base_url = _REST_BASE
    _min_interval_s = 10.0  # paid tier supports higher frequency

    def __init__(self) -> None:
        super().__init__()
        self._ws_task: asyncio.Task | None = None
        self._latest_tick: GoldTick | None = None
        self._ws_enabled: bool = False  # set True for paid tier

    async def fetch_tick(self) -> GoldTick:
        if not self.is_configured:
            raise RuntimeError("METALS_DEV_KEY not set")

        # If WebSocket is streaming, return cached tick
        if self._ws_enabled and self._latest_tick is not None:
            return self._latest_tick

        data = await self._get(
            f"{_REST_BASE}/latest",
            params={
                "api_key": self._api_key,
                "currency": "USD",
                "unit": "toz",
            },
        )

        if data.get("status") != "success":
            raise ValueError(f"Metals.dev error: {data}")

        currencies = data.get("currencies", {})
        usd_block = currencies.get("USD", {})
        xau_price = float(usd_block.get("XAU", 0))

        if xau_price <= 0:
            raise ValueError(f"Metals.dev invalid price: {data}")

        tick = self._make_tick(mid=xau_price, raw=data)
        self._latest_tick = tick
        return tick

    async def start_websocket(self) -> None:
        """
        Start WebSocket stream (paid tier only).
        Falls back silently if websockets package is unavailable.

        Note: _ws_enabled is set to True only after the first successful
        tick is received, so fetch_tick() never returns a stale None tick
        during the connection window.
        """
        try:
            import websockets  # type: ignore[import]  # noqa: F401
        except ImportError:
            logger.debug("Metals.dev WebSocket: websockets package not installed")
            return

        # Do NOT set _ws_enabled=True here — set it only after first tick received
        self._ws_task = asyncio.create_task(self._ws_loop())

    async def _ws_loop(self) -> None:
        import json
        import random
        import websockets  # type: ignore[import]

        url = f"{_WS_URL}?api_key={self._api_key}"
        backoff = 1.0
        _MAX_BACKOFF = 120.0

        while True:
            try:
                async with websockets.connect(
                    url,
                    ping_interval=20,
                    ping_timeout=10,
                    close_timeout=5,
                ) as ws:
                    logger.info("Metals.dev WebSocket connected")
                    backoff = 1.0  # reset on successful connection
                    async for raw in ws:
                        try:
                            msg = json.loads(raw)
                            price = float(msg.get("price", 0))
                            if price > 0:
                                self._latest_tick = self._make_tick(mid=price, raw=msg)
                                # Enable WS path only after first valid tick
                                if not self._ws_enabled:
                                    self._ws_enabled = True
                                    logger.info(
                                        "Metals.dev WebSocket: first tick received (price=%.4f) — switching to WS mode",
                                        price,
                                    )
                        except Exception as exc:
                            logger.debug("Metals.dev WS parse error: %s", exc)
            except asyncio.CancelledError:
                logger.info("Metals.dev WebSocket: cancelled")
                break
            except Exception as exc:
                # Full-jitter exponential backoff — avoids thundering herd on
                # server-side restarts and prevents tight reconnect loops on
                # auth failures (which would burn through rate limits).
                wait = random.uniform(0, min(backoff, _MAX_BACKOFF))  # nosec B311 - reconnect backoff jitter, not cryptographic
                logger.warning(
                    "Metals.dev WS disconnected: %s — reconnecting in %.1fs",
                    exc,
                    wait,
                )
                self._ws_enabled = False  # fall back to REST while disconnected
                await asyncio.sleep(wait)
                backoff = min(backoff * 2, _MAX_BACKOFF)

    async def stop_websocket(self) -> None:
        if self._ws_task:
            self._ws_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._ws_task
            self._ws_task = None
        self._ws_enabled = False

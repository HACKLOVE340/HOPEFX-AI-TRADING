# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
OANDA Streaming WebSocket Adapter

Wraps OANDA's v20 pricing stream endpoint with:
- Exponential backoff reconnection
- Ping/pong heartbeat detection (OANDA sends heartbeat messages)
- REST fallback when streaming is unavailable
- Automatic resubscription after reconnect
- Configurable timeouts (default 30 s connection, 10 s reconciliation)
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

# Reconnection parameters
_INITIAL_DELAY: float = 1.0
_MAX_DELAY: float = 60.0
_MULTIPLIER: float = 2.0

# Timeouts
_CONNECT_TIMEOUT: float = 30.0  # seconds – kill connection attempt if stuck
_RECONCILE_TIMEOUT: float = 10.0  # seconds – used by callers for reconciliation


class OANDAStreamAdapter:
    """
    Async streaming adapter for OANDA v20 prices.

    Usage::

        adapter = OANDAStreamAdapter(
            api_key="...",
            account_id="...",
            instruments=["XAU_USD", "EUR_USD"],
            on_tick=my_callback,
        )
        await adapter.start()
        # ...
        await adapter.stop()
    """

    PRACTICE_STREAM_URL = "https://stream-fxpractice.oanda.com"
    LIVE_STREAM_URL = "https://stream-fxtrade.oanda.com"

    def __init__(
        self,
        api_key: str,
        account_id: str,
        instruments: List[str],
        practice: bool = True,
        on_tick: Optional[Callable[[Dict], None]] = None,
        connect_timeout: float = _CONNECT_TIMEOUT,
        reconcile_timeout: float = _RECONCILE_TIMEOUT,
    ):
        if not api_key or not account_id:
            raise ValueError("OANDAStreamAdapter requires api_key and account_id")
        self._api_key = api_key
        self._account_id = account_id
        self._instruments = instruments
        self._on_tick = on_tick
        self._connect_timeout = connect_timeout
        self._reconcile_timeout = reconcile_timeout

        base = self.PRACTICE_STREAM_URL if practice else self.LIVE_STREAM_URL
        params = "%2C".join(instruments)  # URL-encoded comma
        self._stream_url = (
            f"{base}/v3/accounts/{account_id}/pricing/stream?instruments={params}"
        )
        self._rest_url = (
            f"{'https://api-fxpractice.oanda.com' if practice else 'https://api-fxtrade.oanda.com'}"
            f"/v3/accounts/{account_id}/pricing?instruments={params}"
        )
        self._headers = {
            "Authorization": f"Bearer {api_key}",
            "Accept-Datetime-Format": "UNIX",
        }

        self._running = False
        self._reconnect_delay = _INITIAL_DELAY
        self._last_heartbeat: float = 0.0
        self._task: Optional[asyncio.Task] = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Start the streaming loop in a background task."""
        self._running = True
        self._task = asyncio.create_task(self._stream_loop())
        logger.info("OANDAStreamAdapter started for instruments: %s", self._instruments)

    async def stop(self) -> None:
        """Gracefully stop the adapter."""
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("OANDAStreamAdapter stopped.")

    async def poll_rest(self) -> List[Dict]:
        """
        One-shot REST snapshot – used as fallback when the stream is down.

        Returns:
            List of price dictionaries for each instrument.
        """
        try:
            import aiohttp
        except ImportError:
            logger.error("aiohttp required for OANDAStreamAdapter REST fallback")
            return []

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    self._rest_url,
                    headers=self._headers,
                    timeout=aiohttp.ClientTimeout(total=self._reconcile_timeout),
                ) as resp:
                    resp.raise_for_status()
                    data = await resp.json()
                    return data.get("prices", [])
        except Exception as exc:
            logger.warning("OANDAStreamAdapter REST fallback error: %s", exc)
            return []

    # ------------------------------------------------------------------
    # Internal streaming loop
    # ------------------------------------------------------------------

    async def _stream_loop(self) -> None:
        """
        Main loop: connect → stream → reconnect with exponential backoff.
        Falls back to REST polling when stream is unavailable.
        """
        while self._running:
            connected = await self._try_stream()
            if not self._running:
                break

            if not connected:
                logger.info(
                    "OANDAStreamAdapter: falling back to REST poll for %.1fs",
                    self._reconnect_delay,
                )
                await self._rest_fallback_burst()

            logger.warning(
                "OANDAStreamAdapter reconnecting in %.1fs…",
                self._reconnect_delay,
            )
            await asyncio.sleep(self._reconnect_delay)
            self._reconnect_delay = min(self._reconnect_delay * _MULTIPLIER, _MAX_DELAY)

        logger.info("OANDAStreamAdapter stream loop exited.")

    async def _try_stream(self) -> bool:
        """
        Attempt to open and consume the OANDA pricing stream.

        Returns:
            True if the stream connected and ran (reset backoff),
            False if connection failed immediately.
        """
        try:
            import aiohttp
        except ImportError:
            logger.error("aiohttp required for OANDAStreamAdapter: pip install aiohttp")
            return False

        try:
            timeout = aiohttp.ClientTimeout(
                total=None,
                connect=self._connect_timeout,
                sock_read=60,
            )
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    self._stream_url,
                    headers=self._headers,
                    timeout=timeout,
                ) as resp:
                    if resp.status != 200:
                        logger.error(
                            "OANDAStreamAdapter stream HTTP %s: %s",
                            resp.status,
                            await resp.text(),
                        )
                        return False

                    logger.info("OANDAStreamAdapter stream connected.")
                    self._reconnect_delay = _INITIAL_DELAY  # Reset on success

                    async for raw_line in resp.content:
                        if not self._running:
                            break
                        line = raw_line.strip()
                        if not line:
                            continue
                        await self._dispatch_line(line.decode("utf-8"))

                    return True

        except asyncio.TimeoutError:
            logger.warning(
                "OANDAStreamAdapter connection timed out (%.1fs).",
                self._connect_timeout,
            )
        except Exception as exc:
            logger.error("OANDAStreamAdapter stream error: %s", exc)

        return False

    async def _dispatch_line(self, line: str) -> None:
        """Parse one newline-delimited JSON message from the stream."""
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            return

        msg_type = msg.get("type")

        if msg_type == "HEARTBEAT":
            self._last_heartbeat = time.time()
            logger.debug("OANDAStreamAdapter heartbeat at %.3f", self._last_heartbeat)
            return

        if msg_type == "PRICE":
            if self._on_tick:
                try:
                    self._on_tick(msg)
                except Exception as exc:
                    logger.error("OANDAStreamAdapter on_tick callback error: %s", exc)
            return

        logger.debug("OANDAStreamAdapter unhandled message type '%s'", msg_type)

    async def _rest_fallback_burst(self) -> None:
        """
        While reconnect delay elapses, poll REST once per second for fresh prices.
        """
        elapsed = 0.0
        interval = 1.0
        while elapsed < self._reconnect_delay and self._running:
            prices = await self.poll_rest()
            for price in prices:
                if self._on_tick:
                    try:
                        self._on_tick(price)
                    except Exception as exc:
                        logger.error(
                            "OANDAStreamAdapter REST fallback callback error: %s",
                            exc,
                        )
            await asyncio.sleep(interval)
            elapsed += interval

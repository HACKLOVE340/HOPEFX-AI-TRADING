# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
market_data/mt5_live_feed.py

MT5 Live Feed — WebSocket with exponential-backoff reconnection, ping/pong
heartbeat, REST fallback, and zero silent failures.

Design invariants:
- Every exception is logged at ERROR level with full traceback.
- Sentry is notified on connection failures and callback errors.
- The feed exposes a `health` property so external monitors can gate on it.
- Tick callback errors are isolated (one bad callback cannot kill the feed)
  but are counted and surfaced via `callback_error_count`.
- If the feed cannot connect after `max_reconnect_attempts`, it sets
  `permanently_failed = True` and stops retrying — callers must restart.
"""

from __future__ import annotations

import json
import logging
import threading
import time
import traceback
from collections.abc import Callable
from dataclasses import dataclass

logger = logging.getLogger(__name__)

try:
    import websocket  # type: ignore[import]

    WEBSOCKET_AVAILABLE = True
except ImportError:
    WEBSOCKET_AVAILABLE = False
    logger.warning(
        "websocket-client not installed. MT5LiveFeed will use REST fallback only. "
        "Install with: pip install websocket-client"
    )

try:
    import sentry_sdk  # type: ignore[import]

    _SENTRY_AVAILABLE = True
except ImportError:
    _SENTRY_AVAILABLE = False

_RECONNECT_INITIAL_DELAY: float = 1.0
_RECONNECT_MAX_DELAY: float = 60.0
_RECONNECT_MULTIPLIER: float = 2.0
_PING_INTERVAL: float = 30.0
_CONNECTION_TIMEOUT: float = 30.0
_DEFAULT_MAX_RECONNECT_ATTEMPTS: int = 20


@dataclass
class FeedHealth:
    connected: bool = False
    permanently_failed: bool = False
    reconnect_attempts: int = 0
    callback_error_count: int = 0
    last_tick_ts: float | None = None
    last_error: str | None = None


class MT5LiveFeed:
    """
    MT5 WebSocket live feed — zero silent failures.

    Thread-safety: all public methods are safe to call from any thread.
    Internal state is protected by a single RLock.
    """

    def __init__(
        self,
        url: str,
        rest_fallback_url: str | None = None,
        on_tick: Callable[[dict], None] | None = None,
        max_reconnect_attempts: int = _DEFAULT_MAX_RECONNECT_ATTEMPTS,
    ) -> None:
        self.url = url
        self.rest_fallback_url = rest_fallback_url
        self._on_tick = on_tick
        self._max_reconnect_attempts = max_reconnect_attempts

        self._lock = threading.RLock()
        self._connected = False
        self._permanently_failed = False
        self._reconnect_attempts = 0
        self._callback_error_count = 0
        self._last_tick_ts: float | None = None
        self._last_error: str | None = None
        self._reconnect_delay = _RECONNECT_INITIAL_DELAY

        self._ws: websocket.WebSocketApp | None = None
        self._running = False
        self._connect_thread: threading.Thread | None = None
        self._latency: list[float] = []
        self._tick_buffer: list[dict] = []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def connected(self) -> bool:
        with self._lock:
            return self._connected

    @property
    def permanently_failed(self) -> bool:
        with self._lock:
            return self._permanently_failed

    @property
    def health(self) -> FeedHealth:
        with self._lock:
            return FeedHealth(
                connected=self._connected,
                permanently_failed=self._permanently_failed,
                reconnect_attempts=self._reconnect_attempts,
                callback_error_count=self._callback_error_count,
                last_tick_ts=self._last_tick_ts,
                last_error=self._last_error,
            )

    def start(self) -> None:
        if self._running:
            logger.warning("MT5LiveFeed.start() called while already running — ignored.")
            return
        self._running = True
        self._connect_thread = threading.Thread(
            target=self._run_with_backoff,
            name="mt5-live-feed",
            daemon=True,
        )
        self._connect_thread.start()
        logger.info("MT5LiveFeed started (url=%s).", self.url)

    def stop(self) -> None:
        self._running = False
        ws = self._ws
        if ws is not None:
            try:
                ws.close()
            except Exception as exc:
                logger.error("MT5LiveFeed.stop: ws.close() raised: %s", exc)
                self._capture_sentry(exc)
        logger.info("MT5LiveFeed stopped.")

    def set_tick_callback(self, callback: Callable[[dict], None]) -> None:
        with self._lock:
            self._on_tick = callback

    # ------------------------------------------------------------------
    # Reconnection loop
    # ------------------------------------------------------------------

    def _run_with_backoff(self) -> None:
        while self._running:
            with self._lock:
                if self._permanently_failed:
                    break
                attempt = self._reconnect_attempts

            if self._max_reconnect_attempts > 0 and attempt >= self._max_reconnect_attempts:
                msg = (
                    f"MT5LiveFeed: exceeded max reconnect attempts "
                    f"({self._max_reconnect_attempts}). Marking permanently failed."
                )
                logger.critical(msg)
                self._capture_sentry(RuntimeError(msg))
                with self._lock:
                    self._permanently_failed = True
                    self._last_error = msg
                break

            if not WEBSOCKET_AVAILABLE:
                logger.warning("MT5LiveFeed: websocket-client unavailable — using REST fallback.")
                self._rest_fallback_loop()
                return

            try:
                logger.info("MT5LiveFeed connecting (attempt %d) to %s", attempt + 1, self.url)
                self._connect()
                with self._lock:
                    if self._connected:
                        self._reconnect_delay = _RECONNECT_INITIAL_DELAY
            except Exception as exc:
                tb = traceback.format_exc()
                logger.error(
                    "MT5LiveFeed connection error (attempt %d): %s\n%s",
                    attempt + 1,
                    exc,
                    tb,
                )
                self._capture_sentry(exc)
                with self._lock:
                    self._last_error = str(exc)

            if not self._running:
                break

            with self._lock:
                self._reconnect_attempts += 1
                delay = self._reconnect_delay
                self._reconnect_delay = min(delay * _RECONNECT_MULTIPLIER, _RECONNECT_MAX_DELAY)
                self._connected = False

            logger.warning(
                "MT5LiveFeed disconnected. Retrying in %.1fs (attempt %d/%s)…",
                delay,
                attempt + 1,
                self._max_reconnect_attempts if self._max_reconnect_attempts > 0 else "inf",
            )
            time.sleep(delay)

        logger.info("MT5LiveFeed reconnection loop exited.")

    def _connect(self) -> None:
        self._ws = websocket.WebSocketApp(
            self.url,
            on_open=self._on_open,
            on_message=self._on_message,
            on_error=self._on_error,
            on_close=self._on_close,
            on_ping=self._on_ping,
            on_pong=self._on_pong,
        )
        self._ws.run_forever(ping_interval=int(_PING_INTERVAL), ping_timeout=10)

    # ------------------------------------------------------------------
    # WebSocket handlers
    # ------------------------------------------------------------------

    def _on_open(self, ws) -> None:
        with self._lock:
            self._connected = True
            self._reconnect_delay = _RECONNECT_INITIAL_DELAY
        logger.info("MT5LiveFeed WebSocket opened.")

    def _on_message(self, ws, message: str) -> None:
        try:
            tick_data = json.loads(message)
        except json.JSONDecodeError as exc:
            logger.error("MT5LiveFeed: JSON decode error on message %r: %s", message[:200], exc)
            with self._lock:
                self._last_error = f"JSONDecodeError: {exc}"
            return

        try:
            self._handle_tick(tick_data)
        except Exception as exc:
            tb = traceback.format_exc()
            logger.error("MT5LiveFeed: unhandled error in _handle_tick: %s\n%s", exc, tb)
            self._capture_sentry(exc)
            with self._lock:
                self._last_error = str(exc)

    def _on_error(self, ws, error) -> None:
        tb = traceback.format_exc()
        logger.error("MT5LiveFeed WebSocket error: %s\n%s", error, tb)
        self._capture_sentry(error if isinstance(error, Exception) else RuntimeError(str(error)))
        with self._lock:
            self._connected = False
            self._last_error = str(error)

    def _on_close(self, ws, close_status_code, close_msg) -> None:
        with self._lock:
            self._connected = False
        logger.warning(
            "MT5LiveFeed WebSocket closed (code=%s msg=%s).",
            close_status_code,
            close_msg,
        )

    def _on_ping(self, ws, message) -> None:
        logger.debug("MT5LiveFeed ping received.")

    def _on_pong(self, ws, message) -> None:
        logger.debug("MT5LiveFeed pong received.")

    # ------------------------------------------------------------------
    # Tick processing
    # ------------------------------------------------------------------

    def _handle_tick(self, tick_data: dict) -> None:
        self._track_latency(tick_data)
        self._smooth_ticks(tick_data)

        with self._lock:
            self._last_tick_ts = time.time()
            callback = self._on_tick

        if callback is None:
            return

        try:
            callback(tick_data)
        except Exception as exc:
            tb = traceback.format_exc()
            logger.error("MT5LiveFeed: on_tick callback raised: %s\n%s", exc, tb)
            self._capture_sentry(exc)
            with self._lock:
                self._callback_error_count += 1
                self._last_error = f"callback error: {exc}"
            # Isolated — do not re-raise; feed thread must survive bad callbacks.

    def _track_latency(self, tick_data: dict) -> None:
        timestamp = tick_data.get("timestamp")
        if timestamp is None:
            return
        try:
            latency = time.time() - float(timestamp)
            with self._lock:
                self._latency.append(latency)
                if len(self._latency) > 100:
                    self._latency.pop(0)
        except (TypeError, ValueError) as exc:
            logger.warning("MT5LiveFeed: bad timestamp in tick: %s", exc)

    def _smooth_ticks(self, tick_data: dict) -> None:
        with self._lock:
            self._tick_buffer.append(tick_data)
            if len(self._tick_buffer) > 10:
                self._tick_buffer.pop(0)

    def get_smoothed_price(self) -> float | None:
        with self._lock:
            prices = [t["price"] for t in self._tick_buffer if "price" in t]
        return sum(prices) / len(prices) if prices else None

    def get_avg_latency_ms(self) -> float | None:
        with self._lock:
            if not self._latency:
                return None
            return (sum(self._latency) / len(self._latency)) * 1000.0

    # ------------------------------------------------------------------
    # REST fallback
    # ------------------------------------------------------------------

    def _rest_fallback_loop(self) -> None:
        if not self.rest_fallback_url:
            msg = "MT5LiveFeed: WebSocket unavailable and no REST fallback URL configured. Feed is non-functional."
            logger.critical(msg)
            self._capture_sentry(RuntimeError(msg))
            with self._lock:
                self._permanently_failed = True
                self._last_error = msg
            return

        import urllib.request
        from urllib.parse import urlparse

        parsed = urlparse(self.rest_fallback_url)
        if parsed.scheme not in ("http", "https"):
            raise ValueError(f"MT5LiveFeed: rest_fallback_url must use http/https scheme, got {parsed.scheme!r}")

        logger.info("MT5LiveFeed: using REST fallback at %s", self.rest_fallback_url)
        while self._running:
            try:
                with urllib.request.urlopen(  # nosec B310 - scheme validated as http/https above
                    self.rest_fallback_url, timeout=_CONNECTION_TIMEOUT
                ) as resp:
                    raw = resp.read().decode()

                try:
                    data = json.loads(raw)
                except json.JSONDecodeError as exc:
                    logger.error(
                        "MT5LiveFeed REST fallback: JSON decode error: %s (raw=%r)",
                        exc,
                        raw[:200],
                    )
                    with self._lock:
                        self._last_error = f"REST JSON error: {exc}"
                    time.sleep(1.0)
                    continue

                self._handle_tick(data)
                with self._lock:
                    self._connected = True
                    self._reconnect_delay = _RECONNECT_INITIAL_DELAY

            except Exception as exc:
                tb = traceback.format_exc()
                logger.error("MT5LiveFeed REST fallback error: %s\n%s", exc, tb)
                self._capture_sentry(exc)
                with self._lock:
                    self._connected = False
                    delay = self._reconnect_delay
                    self._reconnect_delay = min(delay * _RECONNECT_MULTIPLIER, _RECONNECT_MAX_DELAY)
                    self._last_error = str(exc)
                time.sleep(delay)
                continue

            time.sleep(1.0)

    # ------------------------------------------------------------------
    # Sentry helper
    # ------------------------------------------------------------------

    @staticmethod
    def _capture_sentry(exc: Exception) -> None:
        if _SENTRY_AVAILABLE:
            try:
                sentry_sdk.capture_exception(exc)
            except Exception as sentry_exc:
                # Sentry must never crash the feed, but log so the failure
                # is visible in local logs / log aggregators.
                logger.debug("Sentry capture failed (non-fatal): %s", sentry_exc)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    feed = MT5LiveFeed(
        url="wss://your.websocket.url",
        rest_fallback_url="https://your.rest.api/tick",
        max_reconnect_attempts=5,
    )
    feed.start()
    try:
        while True:
            time.sleep(5)
            h = feed.health
            logger.info(
                "Health: connected=%s failed=%s attempts=%d cb_errors=%d",
                h.connected,
                h.permanently_failed,
                h.reconnect_attempts,
                h.callback_error_count,
            )
            if h.permanently_failed:
                logger.critical("Feed permanently failed — exiting.")
                break
    except KeyboardInterrupt:
        feed.stop()

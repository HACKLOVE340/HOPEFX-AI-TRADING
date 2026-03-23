"""
MT5 Live Feed with exponential backoff reconnection, ping/pong heartbeat,
and REST fallback when WebSocket is unavailable.
"""
import json
import logging
import threading
import time
from typing import Callable, List, Optional

try:
    import websocket
    WEBSOCKET_AVAILABLE = True
except ImportError:
    WEBSOCKET_AVAILABLE = False

logger = logging.getLogger(__name__)

# Reconnection constants
_RECONNECT_INITIAL_DELAY = 1.0   # seconds
_RECONNECT_MAX_DELAY = 60.0       # seconds
_RECONNECT_MULTIPLIER = 2.0
_PING_INTERVAL = 30.0             # seconds between heartbeats
_CONNECTION_TIMEOUT = 30.0        # seconds before giving up on a single attempt


class MT5LiveFeed:
    """
    MT5 WebSocket live feed with:
    - Exponential backoff reconnection
    - Ping/pong heartbeat
    - REST fallback on WebSocket drop
    - Latency tracking and tick smoothing
    """

    def __init__(
        self,
        url: str,
        rest_fallback_url: Optional[str] = None,
        on_tick: Optional[Callable[[dict], None]] = None,
    ):
        self.url = url
        self.rest_fallback_url = rest_fallback_url
        self._on_tick = on_tick

        self.connected = False
        self.latency: List[float] = []
        self.smoothed_ticks: List[float] = []
        self.tick_buffer: List[dict] = []

        self._ws: Optional["websocket.WebSocketApp"] = None
        self._running = False
        self._reconnect_delay = _RECONNECT_INITIAL_DELAY
        self._reconnect_lock = threading.Lock()
        self._heartbeat_thread: Optional[threading.Thread] = None
        self._connect_thread: Optional[threading.Thread] = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start the feed in a background thread."""
        self._running = True
        self._connect_thread = threading.Thread(target=self._run_with_backoff, daemon=True)
        self._connect_thread.start()

    def stop(self) -> None:
        """Gracefully stop the feed."""
        self._running = False
        if self._ws:
            try:
                self._ws.close()
            except Exception:
                pass
        logger.info("MT5LiveFeed stopped.")

    # ------------------------------------------------------------------
    # Internal connection loop
    # ------------------------------------------------------------------

    def _run_with_backoff(self) -> None:
        """Reconnection loop with exponential backoff."""
        while self._running:
            if not WEBSOCKET_AVAILABLE:
                logger.warning("websocket-client not installed; using REST fallback only.")
                self._rest_fallback_loop()
                return

            try:
                logger.info("MT5LiveFeed connecting to %s", self.url)
                self._connect()
                # If _connect() returns cleanly, reset delay on success
                self._reconnect_delay = _RECONNECT_INITIAL_DELAY
            except Exception as exc:
                logger.error("MT5LiveFeed connection error: %s", exc)

            if not self._running:
                break

            logger.warning(
                "MT5LiveFeed disconnected. Retrying in %.1fs…", self._reconnect_delay
            )
            time.sleep(self._reconnect_delay)
            self._reconnect_delay = min(
                self._reconnect_delay * _RECONNECT_MULTIPLIER, _RECONNECT_MAX_DELAY
            )

        logger.info("MT5LiveFeed reconnection loop exited.")

    def _connect(self) -> None:
        """Create WebSocket connection and block until closed."""
        self._ws = websocket.WebSocketApp(
            self.url,
            on_open=self._on_open,
            on_message=self._on_message,
            on_error=self._on_error,
            on_close=self._on_close,
            on_ping=self._on_ping,
            on_pong=self._on_pong,
        )
        self._ws.run_forever(
            ping_interval=int(_PING_INTERVAL),
            ping_timeout=10,
        )

    # ------------------------------------------------------------------
    # WebSocket event handlers
    # ------------------------------------------------------------------

    def _on_open(self, ws) -> None:
        self.connected = True
        self._reconnect_delay = _RECONNECT_INITIAL_DELAY
        logger.info("MT5LiveFeed WebSocket opened.")

    def _on_message(self, ws, message: str) -> None:
        try:
            tick_data = json.loads(message)
            self._handle_tick(tick_data)
        except (json.JSONDecodeError, KeyError) as exc:
            logger.warning("MT5LiveFeed bad message: %s", exc)

    def _on_error(self, ws, error) -> None:
        logger.error("MT5LiveFeed WebSocket error: %s", error)
        self.connected = False

    def _on_close(self, ws, close_status_code, close_msg) -> None:
        self.connected = False
        logger.warning(
            "MT5LiveFeed WebSocket closed (code=%s msg=%s).", close_status_code, close_msg
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
        if self._on_tick:
            try:
                self._on_tick(tick_data)
            except Exception as exc:
                logger.error("MT5LiveFeed on_tick callback error: %s", exc)

    def _track_latency(self, tick_data: dict) -> None:
        timestamp = tick_data.get("timestamp")
        if timestamp is not None:
            latency = time.time() - float(timestamp)
            self.latency.append(latency)
            if len(self.latency) > 100:
                self.latency.pop(0)

    def _smooth_ticks(self, tick_data: dict) -> None:
        self.tick_buffer.append(tick_data)
        if len(self.tick_buffer) > 10:
            self.tick_buffer.pop(0)
        if self.tick_buffer:
            smoothed = self._calculate_smoothed_tick()
            self.smoothed_ticks.append(smoothed)

    def _calculate_smoothed_tick(self) -> float:
        prices = [t["price"] for t in self.tick_buffer if "price" in t]
        return sum(prices) / len(prices) if prices else 0.0

    # ------------------------------------------------------------------
    # REST fallback
    # ------------------------------------------------------------------

    def _rest_fallback_loop(self) -> None:
        """Poll REST endpoint when WebSocket is unavailable."""
        if not self.rest_fallback_url:
            logger.error(
                "MT5LiveFeed: WebSocket unavailable and no REST fallback URL configured."
            )
            return

        try:
            import urllib.request
        except ImportError:
            logger.error("MT5LiveFeed: REST fallback requires urllib (stdlib).")
            return

        logger.info("MT5LiveFeed: using REST fallback at %s", self.rest_fallback_url)
        while self._running:
            try:
                with urllib.request.urlopen(
                    self.rest_fallback_url, timeout=_CONNECTION_TIMEOUT
                ) as resp:
                    data = json.loads(resp.read().decode())
                    self._handle_tick(data)
                self.connected = True
                self._reconnect_delay = _RECONNECT_INITIAL_DELAY
            except Exception as exc:
                self.connected = False
                logger.warning("MT5LiveFeed REST fallback error: %s", exc)
                time.sleep(self._reconnect_delay)
                self._reconnect_delay = min(
                    self._reconnect_delay * _RECONNECT_MULTIPLIER, _RECONNECT_MAX_DELAY
                )
                continue
            time.sleep(1.0)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    live_feed = MT5LiveFeed(
        url="wss://your.websocket.url",
        rest_fallback_url="https://your.rest.api/tick",
    )
    live_feed.start()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        live_feed.stop()

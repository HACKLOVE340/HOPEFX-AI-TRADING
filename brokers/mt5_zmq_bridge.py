# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
brokers/mt5_zmq_bridge.py
=========================
ZeroMQ-based bridge between the HopeFX Python strategy engine and MetaTrader 5.

Architecture
------------
Python side (this file)
  - PUSH socket  → sends order/close/modify commands to MT5 EA
  - PULL socket  ← receives fill confirmations and tick data from MT5 EA
  - PUB  socket  → publishes live signals to any subscriber (optional)

MT5 side (see mql5/HopeFX_ZMQ_EA.mq5)
  - PULL socket  ← receives commands from Python
  - PUSH socket  → sends fills/ticks back to Python

Message protocol (JSON over ZMQ)
---------------------------------
Command (Python → MT5):
  {"cmd": "ORDER",  "id": "<uuid>", "symbol": "XAUUSD", "side": "BUY",
   "lots": 0.01, "sl": 1900.0, "tp": 1950.0, "comment": "hopefx"}
  {"cmd": "CLOSE",  "id": "<uuid>", "ticket": 12345678}
  {"cmd": "MODIFY", "id": "<uuid>", "ticket": 12345678, "sl": 1905.0, "tp": 1955.0}
  {"cmd": "PING"}

Response (MT5 → Python):
  {"type": "FILL",  "id": "<uuid>", "ticket": 12345678, "price": 1920.5,
   "lots": 0.01, "ts": 1711234567890}
  {"type": "TICK",  "symbol": "XAUUSD", "bid": 1920.4, "ask": 1920.6,
   "ts": 1711234567890}
  {"type": "ERROR", "id": "<uuid>", "code": 10006, "msg": "Trade disabled"}
  {"type": "PONG",  "ts": 1711234567890}

Environment variables
---------------------
ZMQ_CMD_PORT   — port Python PUSHes commands on  (default 5555)
ZMQ_RESP_PORT  — port Python PULLs responses on  (default 5556)
ZMQ_PUB_PORT   — port Python PUBs signals on     (default 5557)
ZMQ_HOST       — MT5 host (default "localhost")
ZMQ_CONNECT_TIMEOUT_MS — connect timeout in ms   (default 5000)

Usage
-----
    bridge = MT5ZmqBridge()
    bridge.start()

    result = bridge.send_order("XAUUSD", "BUY", lots=0.01, sl=1900.0, tp=1950.0)
    bridge.close_position(ticket=result.ticket)

    bridge.stop()

    # Or as a context manager:
    with MT5ZmqBridge() as bridge:
        bridge.send_order(...)
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
UTC = timezone.utc
from enum import Enum
from queue import Empty, Queue

logger = logging.getLogger(__name__)

# ── optional ZMQ import ───────────────────────────────────────────────────────
try:
    import zmq  # type: ignore

    _ZMQ_AVAILABLE = True
except ImportError:
    zmq = None  # type: ignore
    _ZMQ_AVAILABLE = False
    logger.warning(
        "pyzmq not installed — MT5ZmqBridge will enter DEGRADED state and "
        "reject all order submissions. Install: pip install pyzmq"
    )

# ── config ────────────────────────────────────────────────────────────────────
_CMD_PORT = int(os.environ.get("ZMQ_CMD_PORT", "5555"))
_RESP_PORT = int(os.environ.get("ZMQ_RESP_PORT", "5556"))
_PUB_PORT = int(os.environ.get("ZMQ_PUB_PORT", "5557"))
_HOST = os.environ.get("ZMQ_HOST", "localhost")
_CONNECT_TIMEOUT_MS = int(os.environ.get("ZMQ_CONNECT_TIMEOUT_MS", "5000"))
_RECV_TIMEOUT_MS = 2000
_ORDER_TIMEOUT_S = 30.0


# ── domain types ─────────────────────────────────────────────────────────────


class BridgeStatus(Enum):
    STOPPED = "stopped"
    STARTING = "starting"
    CONNECTED = "connected"
    DEGRADED = "degraded"
    ERROR = "error"


@dataclass
class FillResult:
    """Confirmed order fill from MT5."""

    command_id: str
    ticket: int
    symbol: str
    side: str
    lots: float
    fill_price: float
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    error_code: int | None = None
    error_msg: str | None = None

    @property
    def ok(self) -> bool:
        return self.error_code is None


@dataclass
class TickData:
    """Live tick received from MT5 EA."""

    symbol: str
    bid: float
    ask: float
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))

    @property
    def mid(self) -> float:
        return (self.bid + self.ask) / 2.0

    @property
    def spread_pips(self) -> float:
        return round((self.ask - self.bid) * 10, 1)


@dataclass
class BridgeStats:
    commands_sent: int = 0
    fills_received: int = 0
    errors_received: int = 0
    ticks_received: int = 0
    last_heartbeat: datetime | None = None
    latency_ms: float = 0.0


# ── bridge ────────────────────────────────────────────────────────────────────


class MT5ZmqBridge:
    """
    ZeroMQ bridge between HopeFX Python engine and MetaTrader 5 EA.

    Thread model:
      - _recv_thread: background thread that continuously polls the PULL socket
        and dispatches messages to pending futures or tick callbacks.
      - Main thread: sends commands via PUSH socket (thread-safe via lock).
    """

    def __init__(
        self,
        host: str = _HOST,
        cmd_port: int = _CMD_PORT,
        resp_port: int = _RESP_PORT,
        pub_port: int = _PUB_PORT,
        order_timeout_s: float = _ORDER_TIMEOUT_S,
    ) -> None:
        self.host = host
        self.cmd_port = cmd_port
        self.resp_port = resp_port
        self.pub_port = pub_port
        self.order_timeout_s = order_timeout_s

        self._status = BridgeStatus.STOPPED
        self._stats = BridgeStats()
        self._lock = threading.Lock()
        self._stop_event = threading.Event()

        # Pending command futures: id → Queue(maxsize=1)
        self._pending: dict[str, Queue[dict]] = {}

        # Tick callbacks registered by callers
        self._tick_callbacks: list[Callable[[TickData], None]] = []

        # ZMQ context and sockets (None until start())
        self._ctx: object | None = None
        self._push: object | None = None
        self._pull: object | None = None
        self._pub: object | None = None
        self._recv_thread: threading.Thread | None = None

    # ── lifecycle ─────────────────────────────────────────────────────────────

    def start(self) -> None:
        """Connect ZMQ sockets and start the receive thread."""
        if self._status not in (BridgeStatus.STOPPED, BridgeStatus.ERROR):
            return

        self._status = BridgeStatus.STARTING
        self._stop_event.clear()

        if not _ZMQ_AVAILABLE:
            logger.warning("ZMQ unavailable — bridge running in simulation mode")
            self._status = BridgeStatus.DEGRADED
            return

        try:
            ctx = zmq.Context()
            self._ctx = ctx

            # PUSH: Python → MT5 (commands)
            push = ctx.socket(zmq.PUSH)
            push.setsockopt(zmq.SNDTIMEO, _CONNECT_TIMEOUT_MS)
            push.connect(f"tcp://{self.host}:{self.cmd_port}")
            self._push = push

            # PULL: MT5 → Python (fills, ticks, errors)
            pull = ctx.socket(zmq.PULL)
            pull.setsockopt(zmq.RCVTIMEO, _RECV_TIMEOUT_MS)
            pull.connect(f"tcp://{self.host}:{self.resp_port}")
            self._pull = pull

            # PUB: Python → subscribers (signal broadcast)
            pub = ctx.socket(zmq.PUB)
            pub.bind(f"tcp://*:{self.pub_port}")
            self._pub = pub

            self._recv_thread = threading.Thread(target=self._recv_loop, daemon=True, name="mt5-zmq-recv")
            self._recv_thread.start()

            self._status = BridgeStatus.CONNECTED
            logger.info(
                "MT5ZmqBridge connected — cmd=%s:%d resp=%s:%d pub=*:%d",
                self.host,
                self.cmd_port,
                self.host,
                self.resp_port,
                self.pub_port,
            )
        except Exception as exc:
            self._status = BridgeStatus.ERROR
            logger.error("MT5ZmqBridge failed to start: %s", exc)
            raise

    def stop(self) -> None:
        """Disconnect sockets and stop the receive thread."""
        self._stop_event.set()
        if self._recv_thread and self._recv_thread.is_alive():
            self._recv_thread.join(timeout=3.0)

        for sock in (self._push, self._pull, self._pub):
            if sock is not None:
                try:
                    sock.close(linger=0)  # type: ignore[union-attr]
                except Exception as _exc:
                    logger.debug("Suppressed exception: %s", _exc)

        if self._ctx is not None:
            try:
                self._ctx.term()  # type: ignore[union-attr]
            except Exception as _exc:
                logger.debug("Suppressed exception: %s", _exc)

        self._push = self._pull = self._pub = self._ctx = None
        self._status = BridgeStatus.STOPPED
        logger.info("MT5ZmqBridge stopped")

    # ── public API ────────────────────────────────────────────────────────────

    def send_order(
        self,
        symbol: str,
        side: str,
        lots: float,
        sl: float | None = None,
        tp: float | None = None,
        comment: str = "hopefx",
    ) -> FillResult:
        """
        Send a market order to MT5 and wait for fill confirmation.

        Args:
            symbol: MT5 symbol name (e.g. "XAUUSD").
            side: "BUY" or "SELL".
            lots: Order size in lots.
            sl: Stop-loss price (optional).
            tp: Take-profit price (optional).
            comment: Order comment visible in MT5 terminal.

        Returns:
            FillResult — check .ok to confirm fill.

        Raises:
            TimeoutError: if no fill confirmation within order_timeout_s.
            RuntimeError: if bridge is not connected.
        """
        cmd_id = str(uuid.uuid4())
        payload: dict = {
            "cmd": "ORDER",
            "id": cmd_id,
            "symbol": symbol,
            "side": side.upper(),
            "lots": lots,
            "comment": comment,
        }
        if sl is not None:
            payload["sl"] = sl
        if tp is not None:
            payload["tp"] = tp

        return self._send_and_wait(cmd_id, payload, symbol=symbol, side=side, lots=lots)

    def close_position(self, ticket: int, lots: float | None = None) -> FillResult:
        """
        Close an open MT5 position by ticket number.

        Args:
            ticket: MT5 position ticket.
            lots: Partial close size (None = full close).

        Returns:
            FillResult.
        """
        cmd_id = str(uuid.uuid4())
        payload: dict = {"cmd": "CLOSE", "id": cmd_id, "ticket": ticket}
        if lots is not None:
            payload["lots"] = lots
        return self._send_and_wait(cmd_id, payload, symbol="", side="CLOSE", lots=lots or 0.0)

    def modify_position(
        self,
        ticket: int,
        sl: float | None = None,
        tp: float | None = None,
    ) -> FillResult:
        """Modify SL/TP on an open MT5 position."""
        cmd_id = str(uuid.uuid4())
        payload: dict = {"cmd": "MODIFY", "id": cmd_id, "ticket": ticket}
        if sl is not None:
            payload["sl"] = sl
        if tp is not None:
            payload["tp"] = tp
        return self._send_and_wait(cmd_id, payload, symbol="", side="MODIFY", lots=0.0)

    def ping(self) -> float:
        """
        Send a PING and return round-trip latency in milliseconds.

        Returns:
            Latency in ms, or -1.0 if bridge is not connected / timed out.
        """
        if self._status == BridgeStatus.DEGRADED:
            return -1.0
        cmd_id = str(uuid.uuid4())
        payload = {"cmd": "PING", "id": cmd_id}
        t0 = time.monotonic()
        try:
            self._send_and_wait(cmd_id, payload, symbol="", side="PING", lots=0.0)
            latency = (time.monotonic() - t0) * 1000.0
            self._stats.latency_ms = latency
            self._stats.last_heartbeat = datetime.now(UTC)
            return latency
        except TimeoutError:
            return -1.0

    def publish_signal(self, symbol: str, direction: str, confidence: float) -> None:
        """
        Publish a trading signal on the PUB socket for any ZMQ subscriber.

        Args:
            symbol: Trading symbol.
            direction: "BUY", "SELL", or "HOLD".
            confidence: Model confidence 0–1.
        """
        if self._pub is None:
            return
        msg = json.dumps(
            {
                "type": "SIGNAL",
                "symbol": symbol,
                "direction": direction,
                "confidence": confidence,
                "ts": int(time.time() * 1000),
            }
        )
        try:
            with self._lock:
                self._pub.send_string(msg)  # type: ignore[union-attr]
        except Exception as exc:
            logger.warning("publish_signal failed: %s", exc)

    def register_tick_callback(self, callback: Callable[[TickData], None]) -> None:
        """Register a callback invoked on every tick received from MT5."""
        self._tick_callbacks.append(callback)

    @property
    def status(self) -> BridgeStatus:
        return self._status

    @property
    def stats(self) -> BridgeStats:
        return self._stats

    # ── internals ─────────────────────────────────────────────────────────────

    def _send_and_wait(
        self,
        cmd_id: str,
        payload: dict,
        symbol: str,
        side: str,
        lots: float,
    ) -> FillResult:
        """Send a command and block until a response arrives or timeout."""
        if self._status == BridgeStatus.DEGRADED:
            raise RuntimeError(
                "MT5ZmqBridge is in DEGRADED state (ZMQ unavailable). "
                "Cannot send orders — install pyzmq and ensure the MT5 EA is running. "
                f"Order details: symbol={symbol} side={side} lots={lots}"
            )

        if self._status != BridgeStatus.CONNECTED:
            raise RuntimeError(
                f"MT5ZmqBridge is not connected (status={self._status.value}). Call bridge.start() first."
            )

        q: Queue[dict] = Queue(maxsize=1)
        with self._lock:
            self._pending[cmd_id] = q

        try:
            msg = json.dumps(payload)
            with self._lock:
                self._push.send_string(msg)  # type: ignore[union-attr]
            self._stats.commands_sent += 1
            logger.debug("→ MT5: %s", msg)

            try:
                resp = q.get(timeout=self.order_timeout_s)
            except Empty:
                raise TimeoutError(f"No response from MT5 for command {cmd_id} after {self.order_timeout_s}s") from None

            return self._parse_response(resp, cmd_id, symbol, side, lots)

        finally:
            with self._lock:
                self._pending.pop(cmd_id, None)

    def _recv_loop(self) -> None:
        """Background thread: receive messages from MT5 and dispatch them."""
        logger.debug("MT5ZmqBridge recv loop started")
        while not self._stop_event.is_set():
            try:
                raw = self._pull.recv_string()  # type: ignore[union-attr]
                logger.debug("← MT5: %s", raw)
                msg = json.loads(raw)
                self._dispatch(msg)
            except Exception as exc:
                # RCVTIMEO fires as zmq.Again — normal, just loop
                if _ZMQ_AVAILABLE and isinstance(exc, zmq.Again):
                    continue
                if not self._stop_event.is_set():
                    logger.warning("MT5ZmqBridge recv error: %s", exc)
        logger.debug("MT5ZmqBridge recv loop stopped")

    def _dispatch(self, msg: dict) -> None:
        """Route an incoming MT5 message to the correct handler."""
        msg_type = msg.get("type", "")
        cmd_id = msg.get("id", "")

        if msg_type == "TICK":
            self._stats.ticks_received += 1
            tick = TickData(
                symbol=msg.get("symbol", ""),
                bid=float(msg.get("bid", 0)),
                ask=float(msg.get("ask", 0)),
                timestamp=datetime.fromtimestamp(msg.get("ts", time.time() * 1000) / 1000.0, tz=UTC),
            )
            for cb in self._tick_callbacks:
                try:
                    cb(tick)
                except Exception as exc:
                    logger.warning("Tick callback error: %s", exc)
            return

        if msg_type in ("FILL", "ERROR", "PONG"):
            if msg_type == "FILL":
                self._stats.fills_received += 1
            elif msg_type == "ERROR":
                self._stats.errors_received += 1

            with self._lock:
                q = self._pending.get(cmd_id)
            if q is not None:
                try:
                    q.put_nowait(msg)
                except Exception as _exc:
                    logger.debug("Suppressed exception: %s", _exc)
            return

        logger.debug("Unknown MT5 message type: %s", msg_type)

    def _parse_response(
        self,
        resp: dict,
        cmd_id: str,
        symbol: str,
        side: str,
        lots: float,
    ) -> FillResult:
        """Convert a raw MT5 response dict into a FillResult."""
        if resp.get("type") == "ERROR":
            # fill_price=0.0 signals no fill occurred — callers MUST check
            # error_code (or error_msg) before using fill_price for any
            # calculation. A zero fill_price on a successful trade would be
            # a data error; here it is only valid when error_code is set.
            return FillResult(
                command_id=cmd_id,
                ticket=0,
                symbol=symbol,
                side=side,
                lots=lots,
                fill_price=0.0,
                error_code=resp.get("code"),
                error_msg=resp.get("msg"),
            )

        ts_ms = resp.get("ts", int(time.time() * 1000))
        return FillResult(
            command_id=cmd_id,
            ticket=int(resp.get("ticket", 0)),
            symbol=resp.get("symbol", symbol),
            side=resp.get("side", side),
            lots=float(resp.get("lots", lots)),
            fill_price=float(resp.get("price", 0.0)),
            timestamp=datetime.fromtimestamp(ts_ms / 1000.0, tz=UTC),
        )

    # ── context manager ───────────────────────────────────────────────────────

    def __enter__(self) -> MT5ZmqBridge:
        self.start()
        return self

    def __exit__(self, *_: object) -> None:
        self.stop()


# ── module-level singleton ────────────────────────────────────────────────────

_bridge: MT5ZmqBridge | None = None


def get_bridge() -> MT5ZmqBridge:
    """Return the module-level MT5ZmqBridge singleton, creating it if needed."""
    global _bridge
    if _bridge is None:
        _bridge = MT5ZmqBridge()
    return _bridge

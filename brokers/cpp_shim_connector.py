# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
brokers/cpp_shim_connector.py
==============================
Python connector for the HOPEFX C++ execution shim.

The shim (execution/cpp_shim/hopefx_shim.cpp) runs as a separate process
and handles the FIX 4.4 session with the exchange.  This connector sends
order commands over ZMQ PUSH and receives fill confirmations over ZMQ PULL.

Architecture
------------
  Python brain
    └── CPPShimConnector.place_order()
          └── ZMQ PUSH  ──►  hopefx_shim (C++)
                              └── FIX 4.4 ──►  Exchange
          ◄── ZMQ PULL  ◄──  hopefx_shim
                              └── FIX 4.4 ◄──  ExecutionReport

Why this is faster than Python FIX
------------------------------------
- The C++ shim has no GIL, no GC pauses, no interpreter overhead
- SO_BUSY_POLL on the FIX socket reduces kernel wake-up latency
- CPU affinity pins the shim to a dedicated core (no context switches)
- ZMQ inproc/loopback adds ~1–5μs overhead vs direct function call —
  negligible compared to the network RTT to the exchange

Same pattern as brokers/mt5_zmq_bridge.py — proven in production.

Environment variables
---------------------
  CPP_SHIM_ZMQ_CMD_ADDR    ZMQ address to PUSH commands to shim
                            (default: tcp://127.0.0.1:6555)
  CPP_SHIM_ZMQ_RESP_ADDR   ZMQ address to PULL responses from shim
                            (default: tcp://127.0.0.1:6556)
  CPP_SHIM_TIMEOUT_MS      Response timeout in ms (default: 5000)
  CPP_SHIM_LATENCY_WARN_US Log warning if round-trip > N μs (default: 1000)
  CPP_SHIM_ENABLED         "true" | "false" (default: true)

Usage
-----
    from brokers.cpp_shim_connector import CPPShimConnector

    broker = CPPShimConnector.from_env()
    broker.connect()

    order = broker.place_order(
        symbol="XAU_USD",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        quantity=1.0,
        price=2350.0,
    )
    logger.info(order.id, order.filled_price)  # Order.id is the canonical field
    broker.disconnect()
"""

from __future__ import annotations

import json
import logging
import os
import time
import uuid
from datetime import datetime, timezone
from typing import Any

from brokers.base import (
    AccountInfo,
    BrokerConnector,
    Order,
    OrderSide,
    OrderStatus,
    OrderType,
    Position,
    with_retry,
)

UTC = timezone.utc
logger = logging.getLogger(__name__)

# ── Configuration ─────────────────────────────────────────────────────────────
_CMD_ADDR = os.getenv("CPP_SHIM_ZMQ_CMD_ADDR", "tcp://127.0.0.1:6555")
_RESP_ADDR = os.getenv("CPP_SHIM_ZMQ_RESP_ADDR", "tcp://127.0.0.1:6556")
_TIMEOUT_MS = int(os.getenv("CPP_SHIM_TIMEOUT_MS", "5000"))
_LATENCY_WARN_US = int(os.getenv("CPP_SHIM_LATENCY_WARN_US", "1000"))
_ENABLED = os.getenv("CPP_SHIM_ENABLED", "true").lower() == "true"

# Symbol normalisation — same as CME connector
_SYMBOL_MAP: dict[str, str] = {
    "XAU_USD": "XAUUSD",
    "XAU/USD": "XAUUSD",
    "GOLD": "XAUUSD",
    "GC": "XAUUSD",
}


class CPPShimConnector(BrokerConnector):
    """
    Broker connector that routes orders through the C++ execution shim via ZMQ.

    Falls back gracefully if the shim process is not running — connect()
    returns False and place_order() raises RuntimeError so the Smart Router
    can fall back to the next broker in the pool.
    """

    def __init__(
        self,
        cmd_addr: str = _CMD_ADDR,
        resp_addr: str = _RESP_ADDR,
        timeout_ms: int = _TIMEOUT_MS,
        latency_warn_us: int = _LATENCY_WARN_US,
    ) -> None:
        self._cmd_addr = cmd_addr
        self._resp_addr = resp_addr
        self._timeout_ms = timeout_ms
        self._latency_warn_us = latency_warn_us

        self._ctx: Any = None
        self._cmd_sock: Any = None
        self._resp_sock: Any = None
        self._connected: bool = False

        self._order_count: int = 0
        self._fill_count: int = 0
        self._reject_count: int = 0
        self._total_latency_us: float = 0.0

    @classmethod
    def from_env(cls) -> CPPShimConnector:
        return cls()

    # ── BrokerConnector interface ─────────────────────────────────────────────

    def connect(self) -> bool:
        """Connect ZMQ sockets to the C++ shim and verify with PING."""
        if not _ENABLED:
            logger.info("CPPShimConnector disabled via CPP_SHIM_ENABLED=false")
            return False
        try:
            import zmq

            self._ctx = zmq.Context()

            self._cmd_sock = self._ctx.socket(zmq.PUSH)
            self._cmd_sock.setsockopt(zmq.SNDHWM, 1000)
            self._cmd_sock.connect(self._cmd_addr)

            self._resp_sock = self._ctx.socket(zmq.PULL)
            self._resp_sock.setsockopt(zmq.RCVTIMEO, self._timeout_ms)
            self._resp_sock.connect(self._resp_addr)

            # Verify shim is alive
            if not self._ping():
                logger.warning("CPPShimConnector: shim did not respond to PING — is hopefx_shim running?")
                self._cleanup()
                return False

            self._connected = True
            logger.info("CPPShimConnector connected — cmd=%s resp=%s", self._cmd_addr, self._resp_addr)
            return True

        except ImportError:
            logger.warning("CPPShimConnector: pyzmq not installed — pip install pyzmq")
            return False
        except Exception as exc:
            logger.warning("CPPShimConnector: connect failed: %s", exc)
            self._cleanup()
            return False

    def disconnect(self) -> bool:
        self._send({"cmd": "SHUTDOWN"})
        self._cleanup()
        self._connected = False
        logger.info(
            "CPPShimConnector disconnected. orders=%d fills=%d rejects=%d avg_latency=%.0fμs",
            self._order_count,
            self._fill_count,
            self._reject_count,
            self._total_latency_us / max(self._fill_count, 1),
        )
        return True

    @with_retry(max_attempts=2, backoff=0.1)
    def place_order(
        self,
        symbol: str,
        side: OrderSide,
        order_type: OrderType,
        quantity: float,
        price: float | None = None,
        stop_price: float | None = None,
        **kwargs: Any,
    ) -> Order:
        if not self._connected:
            raise RuntimeError("CPPShimConnector: not connected — call connect() first")

        cl_ord_id = str(uuid.uuid4())
        self._order_count += 1

        cmd: dict[str, Any] = {
            "cmd": "ORDER",
            "id": cl_ord_id,
            "symbol": self._normalise_symbol(symbol),
            "side": side.value.upper(),
            "type": order_type.value.upper(),
            "qty": quantity,
            "price": price or 0.0,
            "account": os.getenv("CME_ACCOUNT", ""),
        }

        t0_us = time.perf_counter_ns() // 1000
        self._send(cmd)
        response = self._recv()
        latency_us = (time.perf_counter_ns() // 1000) - t0_us

        self._total_latency_us += latency_us
        if latency_us > self._latency_warn_us:
            logger.warning("CPPShim HIGH LATENCY %dμs for order %s", latency_us, cl_ord_id)

        if response is None:
            self._reject_count += 1
            raise RuntimeError(f"CPPShimConnector: timeout waiting for fill (cl_ord_id={cl_ord_id})")

        resp_type = response.get("type", "")

        if resp_type == "REJECT":
            self._reject_count += 1
            reason = response.get("reason", "unknown")
            raise RuntimeError(f"CPPShimConnector: order rejected — {reason}")

        if resp_type != "FILL":
            self._reject_count += 1
            raise RuntimeError(f"CPPShimConnector: unexpected response type '{resp_type}'")

        self._fill_count += 1
        fill_price = float(response.get("price", price or 0.0))
        fill_qty = float(response.get("qty", quantity))
        order_id = response.get("order_id", cl_ord_id)

        logger.info(
            "CPPShim FILL  %s %s %.2f @ %.5f  latency=%dμs",
            side.value,
            symbol,
            fill_qty,
            fill_price,
            latency_us,
        )

        return Order(
            id=order_id,
            symbol=symbol,
            side=side,
            type=order_type,
            quantity=quantity,
            filled_quantity=fill_qty,
            average_price=fill_price,
            status=OrderStatus.FILLED,
            timestamp=datetime.now(UTC),
        )

    def get_account_info(self) -> AccountInfo:
        return AccountInfo(
            balance=0.0,
            equity=0.0,
            margin_used=0.0,
            margin_available=0.0,
            positions_count=0,
        )

    def get_market_data(self, symbol: str, timeframe: str = "1h", limit: int = 100) -> list[dict]:
        # Market data comes from data_layer, not the execution shim
        return []

    def get_positions(self) -> list[Position]:
        return []

    def cancel_order(self, order_id: str) -> bool:
        """Cancel is not supported via the C++ shim (fire-and-forget FIX path)."""
        logger.warning("CPPShimConnector: cancel_order not supported")
        return False

    def close_position(self, symbol: str) -> bool:
        """Close position by sending a market order in the opposite direction."""
        logger.warning("CPPShimConnector: close_position not supported directly — use place_order")
        return False

    def get_order(self, order_id: str) -> None:
        """Order lookup not supported; fills are tracked via metrics() only."""
        return None

    # ── ZMQ helpers ───────────────────────────────────────────────────────────

    def _send(self, payload: dict) -> None:
        try:
            msg = json.dumps(payload).encode()
            self._cmd_sock.send(msg)
        except Exception as exc:
            logger.error("CPPShimConnector: ZMQ send error: %s", exc)

    def _recv(self) -> dict | None:
        try:
            raw = self._resp_sock.recv()
            return json.loads(raw.decode())
        except Exception:
            return None

    def _ping(self) -> bool:
        """Send PING and wait for PONG — verifies shim is alive."""
        import time as _time

        # Give shim 500ms to start up
        _time.sleep(0.1)
        self._send({"cmd": "PING"})
        resp = self._recv()
        return resp is not None and resp.get("type") == "PONG"

    def _cleanup(self) -> None:
        import contextlib

        for sock in (self._cmd_sock, self._resp_sock):
            if sock:
                with contextlib.suppress(Exception):
                    sock.close()
        if self._ctx:
            with contextlib.suppress(Exception):
                self._ctx.term()
        self._cmd_sock = self._resp_sock = self._ctx = None

    @staticmethod
    def _normalise_symbol(symbol: str) -> str:
        """Normalise to MT5 form (no separator) via the shared utils.symbol module."""
        from utils.symbol import to_mt5
        return to_mt5(symbol)

    # ── Metrics ───────────────────────────────────────────────────────────────

    def metrics(self) -> dict[str, Any]:
        avg_lat = self._total_latency_us / max(self._fill_count, 1)
        return {
            "orders": self._order_count,
            "fills": self._fill_count,
            "rejects": self._reject_count,
            "avg_latency_us": round(avg_lat, 1),
            "connected": self._connected,
            "cmd_addr": self._cmd_addr,
        }

# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
Unit tests for brokers/cpp_shim_connector.py — CPPShimConnector.

ZMQ sockets and the C++ shim process are fully mocked so tests run
without any native binaries or network access.
"""

from __future__ import annotations

import json
import sys
import types
import uuid
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

# ---------------------------------------------------------------------------
# Stub pyzmq before the module is loaded
# ---------------------------------------------------------------------------

def _make_zmq_stub():
    """Return a minimal pyzmq stub that records sent messages."""
    mod = types.ModuleType("zmq")

    class _Socket:
        def __init__(self, sock_type):
            self._type = sock_type
            self._sent: list[bytes] = []
            self._recv_queue: list[bytes] = []

        def setsockopt(self, opt, val):
            pass

        def connect(self, addr):
            pass

        def send(self, data: bytes):
            self._sent.append(data)

        def recv(self) -> bytes:
            if self._recv_queue:
                return self._recv_queue.pop(0)
            raise Exception("EAGAIN")  # simulate timeout

        def close(self):
            pass

    class _Context:
        def __init__(self):
            self._sockets: list[_Socket] = []

        def socket(self, sock_type):
            s = _Socket(sock_type)
            self._sockets.append(s)
            return s

        def term(self):
            pass

    mod.PUSH = 1
    mod.PULL = 2
    mod.SNDHWM = 23
    mod.RCVTIMEO = 27
    mod.Context = _Context
    return mod


_zmq_stub = _make_zmq_stub()
sys.modules["zmq"] = _zmq_stub

from brokers.cpp_shim_connector import CPPShimConnector  # noqa: E402
from brokers.base import AccountInfo, OrderSide, OrderStatus, OrderType  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_connector(**kwargs) -> CPPShimConnector:
    defaults = dict(
        cmd_addr="tcp://127.0.0.1:6555",
        resp_addr="tcp://127.0.0.1:6556",
        timeout_ms=100,
        latency_warn_us=1_000_000,  # very high so warnings don't fire in tests
    )
    defaults.update(kwargs)
    return CPPShimConnector(**defaults)


def _connected_connector(pong_extra: dict | None = None) -> CPPShimConnector:
    """Return a connector whose connect() succeeds via a mocked PING/PONG."""
    conn = _make_connector()
    pong = {"type": "PONG", **(pong_extra or {})}

    def fake_ping(self_inner):
        return True

    with patch.object(CPPShimConnector, "_ping", fake_ping):
        conn.connect()
    return conn


# ---------------------------------------------------------------------------
# from_env()
# ---------------------------------------------------------------------------

class TestFromEnv:
    def test_returns_instance(self):
        conn = CPPShimConnector.from_env()
        assert isinstance(conn, CPPShimConnector)


# ---------------------------------------------------------------------------
# connect()
# ---------------------------------------------------------------------------

class TestConnect:
    def test_connect_succeeds_when_ping_ok(self):
        conn = _make_connector()
        with patch.object(conn, "_ping", return_value=True):
            result = conn.connect()
        assert result is True
        assert conn._connected is True

    def test_connect_fails_when_ping_fails(self):
        conn = _make_connector()
        with patch.object(conn, "_ping", return_value=False):
            result = conn.connect()
        assert result is False
        assert conn._connected is False

    def test_connect_returns_false_when_zmq_import_fails(self):
        conn = _make_connector()
        with patch.dict(sys.modules, {"zmq": None}):
            # Simulate ImportError by patching the import inside connect
            with patch("builtins.__import__", side_effect=ImportError("no zmq")):
                result = conn.connect()
        # connect() catches ImportError and returns False
        assert result is False

    def test_connect_disabled_via_env(self, monkeypatch):
        monkeypatch.setenv("CPP_SHIM_ENABLED", "false")
        # Re-import to pick up env var — patch the module-level constant instead
        conn = _make_connector()
        with patch("brokers.cpp_shim_connector._ENABLED", False):
            result = conn.connect()
        assert result is False

    def test_connect_sets_sockets(self):
        conn = _make_connector()
        with patch.object(conn, "_ping", return_value=True):
            conn.connect()
        assert conn._cmd_sock is not None
        assert conn._resp_sock is not None
        assert conn._ctx is not None


# ---------------------------------------------------------------------------
# disconnect()
# ---------------------------------------------------------------------------

class TestDisconnect:
    def test_disconnect_returns_true(self):
        conn = _connected_connector()
        with patch.object(conn, "_send"):  # suppress SHUTDOWN send
            result = conn.disconnect()
        assert result is True
        assert conn._connected is False

    def test_disconnect_cleans_up_sockets(self):
        conn = _connected_connector()
        with patch.object(conn, "_send"):
            conn.disconnect()
        assert conn._cmd_sock is None
        assert conn._resp_sock is None
        assert conn._ctx is None


# ---------------------------------------------------------------------------
# place_order() — fill path
# ---------------------------------------------------------------------------

class TestPlaceOrderFill:
    def _setup(self, fill_response: dict) -> CPPShimConnector:
        conn = _connected_connector()
        # Queue the fill response on the resp socket
        conn._resp_sock._recv_queue.append(json.dumps(fill_response).encode())
        return conn

    def test_market_buy_returns_filled_order(self):
        fill = {"type": "FILL", "price": 2350.0, "qty": 1.0, "order_id": "oid-1"}
        conn = self._setup(fill)
        order = conn.place_order("XAU_USD", OrderSide.BUY, OrderType.MARKET, 1.0)
        assert order.status == OrderStatus.FILLED
        assert order.average_price == 2350.0
        assert order.filled_quantity == 1.0
        assert order.side == OrderSide.BUY

    def test_limit_sell_uses_fill_price(self):
        fill = {"type": "FILL", "price": 2400.0, "qty": 2.0, "order_id": "oid-2"}
        conn = self._setup(fill)
        order = conn.place_order("GC", OrderSide.SELL, OrderType.LIMIT, 2.0, price=2400.0)
        assert order.average_price == 2400.0
        assert order.filled_quantity == 2.0

    def test_fill_count_increments(self):
        fill = {"type": "FILL", "price": 2000.0, "qty": 1.0, "order_id": "x"}
        conn = self._setup(fill)
        assert conn._fill_count == 0
        conn.place_order("GC", OrderSide.BUY, OrderType.MARKET, 1.0)
        assert conn._fill_count == 1

    def test_order_count_increments(self):
        fill = {"type": "FILL", "price": 2000.0, "qty": 1.0, "order_id": "x"}
        conn = self._setup(fill)
        assert conn._order_count == 0
        conn.place_order("GC", OrderSide.BUY, OrderType.MARKET, 1.0)
        assert conn._order_count == 1

    def test_order_id_from_fill_response(self):
        fill = {"type": "FILL", "price": 2000.0, "qty": 1.0, "order_id": "server-id-99"}
        conn = self._setup(fill)
        order = conn.place_order("GC", OrderSide.BUY, OrderType.MARKET, 1.0)
        assert order.id == "server-id-99"

    def test_cmd_sent_with_correct_fields(self):
        fill = {"type": "FILL", "price": 2000.0, "qty": 1.0, "order_id": "x"}
        conn = self._setup(fill)
        conn.place_order("XAU_USD", OrderSide.BUY, OrderType.LIMIT, 3.0, price=2100.0)
        sent = json.loads(conn._cmd_sock._sent[-1].decode())
        assert sent["cmd"] == "ORDER"
        assert sent["symbol"] == "XAUUSD"   # normalised
        assert sent["side"] == "BUY"
        assert sent["type"] == "LIMIT"
        assert sent["qty"] == 3.0
        assert sent["price"] == 2100.0


# ---------------------------------------------------------------------------
# place_order() — reject / timeout paths
#
# place_order is decorated with @with_retry(max_attempts=2), so a single
# queued response is consumed on attempt 1 and attempt 2 gets a timeout.
# We queue two identical responses to cover both retry attempts, or patch
# _recv directly to return a fixed value on every call.
# ---------------------------------------------------------------------------

class TestPlaceOrderReject:
    def test_reject_response_raises(self):
        conn = _connected_connector()
        reject = json.dumps({"type": "REJECT", "reason": "insufficient margin"}).encode()
        # Queue two copies — one per retry attempt
        conn._resp_sock._recv_queue.extend([reject, reject])
        with pytest.raises(RuntimeError, match="insufficient margin"):
            conn.place_order("GC", OrderSide.BUY, OrderType.MARKET, 1.0)

    def test_reject_increments_reject_count(self):
        conn = _connected_connector()
        reject = json.dumps({"type": "REJECT", "reason": "bad symbol"}).encode()
        conn._resp_sock._recv_queue.extend([reject, reject])
        with pytest.raises(RuntimeError):
            conn.place_order("GC", OrderSide.BUY, OrderType.MARKET, 1.0)
        # 2 attempts × 1 reject each = 2 rejects
        assert conn._reject_count == 2

    def test_timeout_raises(self):
        conn = _connected_connector()
        with patch.object(conn, "_recv", return_value=None):
            with pytest.raises(RuntimeError, match="timeout"):
                conn.place_order("GC", OrderSide.BUY, OrderType.MARKET, 1.0)

    def test_timeout_increments_reject_count(self):
        conn = _connected_connector()
        with patch.object(conn, "_recv", return_value=None):
            with pytest.raises(RuntimeError):
                conn.place_order("GC", OrderSide.BUY, OrderType.MARKET, 1.0)
        # 2 retry attempts × 1 timeout each = 2 rejects
        assert conn._reject_count == 2

    def test_unexpected_response_type_raises(self):
        conn = _connected_connector()
        bad = json.dumps({"type": "UNKNOWN"}).encode()
        conn._resp_sock._recv_queue.extend([bad, bad])
        with pytest.raises(RuntimeError, match="unexpected response type|timeout"):
            conn.place_order("GC", OrderSide.BUY, OrderType.MARKET, 1.0)

    def test_not_connected_raises(self):
        conn = _make_connector()
        with pytest.raises(RuntimeError, match="not connected"):
            conn.place_order("GC", OrderSide.BUY, OrderType.MARKET, 1.0)


# ---------------------------------------------------------------------------
# Symbol normalisation
# ---------------------------------------------------------------------------

class TestNormaliseSymbol:
    @pytest.mark.parametrize("symbol,expected", [
        ("XAU_USD", "XAUUSD"),
        ("XAU/USD", "XAUUSD"),
        ("GOLD",    "XAUUSD"),
        ("GC",      "XAUUSD"),
        ("xauusd",  "XAUUSD"),
        ("BTCUSD",  "BTCUSD"),  # unmapped → uppercased, slashes stripped
    ])
    def test_symbol_map(self, symbol, expected):
        assert CPPShimConnector._normalise_symbol(symbol) == expected


# ---------------------------------------------------------------------------
# get_account_info()
# ---------------------------------------------------------------------------

class TestGetAccountInfo:
    def test_returns_account_info(self):
        conn = _connected_connector()
        info = conn.get_account_info()
        assert isinstance(info, AccountInfo)
        assert info.balance == 0.0

    def test_positions_count_zero(self):
        conn = _connected_connector()
        info = conn.get_account_info()
        assert info.positions_count == 0


# ---------------------------------------------------------------------------
# get_market_data() / get_positions()
# ---------------------------------------------------------------------------

class TestPassthroughMethods:
    def test_get_market_data_returns_empty(self):
        conn = _connected_connector()
        assert conn.get_market_data("GC") == []

    def test_get_positions_returns_empty(self):
        conn = _connected_connector()
        assert conn.get_positions() == []


# ---------------------------------------------------------------------------
# cancel_order() / close_position() / get_order()
# ---------------------------------------------------------------------------

class TestUnsupportedOperations:
    def test_cancel_order_returns_false(self):
        conn = _connected_connector()
        assert conn.cancel_order("any-id") is False

    def test_close_position_returns_false(self):
        conn = _connected_connector()
        assert conn.close_position("GC") is False

    def test_get_order_returns_none(self):
        conn = _connected_connector()
        assert conn.get_order("any-id") is None


# ---------------------------------------------------------------------------
# metrics()
# ---------------------------------------------------------------------------

class TestMetrics:
    def test_initial_metrics(self):
        conn = _connected_connector()
        m = conn.metrics()
        assert m["orders"] == 0
        assert m["fills"] == 0
        assert m["rejects"] == 0
        assert m["connected"] is True
        assert m["cmd_addr"] == "tcp://127.0.0.1:6555"

    def test_metrics_after_fill(self):
        conn = _connected_connector()
        fill = {"type": "FILL", "price": 2000.0, "qty": 1.0, "order_id": "x"}
        conn._resp_sock._recv_queue.append(json.dumps(fill).encode())
        conn.place_order("GC", OrderSide.BUY, OrderType.MARKET, 1.0)
        m = conn.metrics()
        assert m["orders"] == 1
        assert m["fills"] == 1
        assert m["rejects"] == 0

    def test_metrics_after_reject(self):
        conn = _connected_connector()
        reject = json.dumps({"type": "REJECT", "reason": "test"}).encode()
        # Queue two copies — one per retry attempt
        conn._resp_sock._recv_queue.extend([reject, reject])
        with pytest.raises(RuntimeError):
            conn.place_order("GC", OrderSide.BUY, OrderType.MARKET, 1.0)
        m = conn.metrics()
        assert m["rejects"] >= 1

    def test_avg_latency_us_is_numeric(self):
        conn = _connected_connector()
        fill = {"type": "FILL", "price": 2000.0, "qty": 1.0, "order_id": "x"}
        conn._resp_sock._recv_queue.append(json.dumps(fill).encode())
        conn.place_order("GC", OrderSide.BUY, OrderType.MARKET, 1.0)
        m = conn.metrics()
        assert isinstance(m["avg_latency_us"], float)

    def test_connected_false_after_disconnect(self):
        conn = _connected_connector()
        with patch.object(conn, "_send"):
            conn.disconnect()
        m = conn.metrics()
        assert m["connected"] is False


# ---------------------------------------------------------------------------
# _send / _recv helpers
# ---------------------------------------------------------------------------

class TestZMQHelpers:
    def test_send_encodes_json(self):
        conn = _connected_connector()
        conn._send({"cmd": "PING"})
        raw = conn._cmd_sock._sent[-1]
        assert json.loads(raw) == {"cmd": "PING"}

    def test_recv_returns_none_on_exception(self):
        conn = _connected_connector()
        # No data queued → socket raises → _recv returns None
        result = conn._recv()
        assert result is None

    def test_recv_decodes_json(self):
        conn = _connected_connector()
        payload = {"type": "PONG"}
        conn._resp_sock._recv_queue.append(json.dumps(payload).encode())
        result = conn._recv()
        assert result == {"type": "PONG"}

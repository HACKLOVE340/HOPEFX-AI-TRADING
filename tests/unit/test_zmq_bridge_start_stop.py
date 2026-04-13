# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""ZMQ bridge start/stop and recv_loop coverage tests."""
from __future__ import annotations
import json
import time
from unittest.mock import MagicMock, patch
import pytest


def _zmq_mock():
    zmq_mod = MagicMock()
    zmq_mod.PUSH = 1
    zmq_mod.PULL = 2
    zmq_mod.PUB = 3
    zmq_mod.SNDTIMEO = 4
    zmq_mod.RCVTIMEO = 5
    zmq_mod.Again = type("Again", (Exception,), {})
    ctx = MagicMock()
    push_sock = MagicMock()
    pull_sock = MagicMock()
    pub_sock = MagicMock()
    ctx.socket.side_effect = [push_sock, pull_sock, pub_sock]
    zmq_mod.Context.return_value = ctx
    return zmq_mod, ctx, push_sock, pull_sock, pub_sock


def _load_bridge_mod(zmq_mod):
    import importlib
    import brokers.mt5_zmq_bridge as mod
    mod.zmq = zmq_mod
    mod._ZMQ_AVAILABLE = True
    mod.Again = zmq_mod.Again
    return mod


class TestZmqBridgeStart:
    def test_start_connected(self):
        zmq_mod, ctx, push, pull, pub = _zmq_mock()
        pull.recv_string.side_effect = Exception("stop")
        mod = _load_bridge_mod(zmq_mod)
        b = mod.MT5ZmqBridge(order_timeout_s=0.1)
        b.start()
        time.sleep(0.05)
        assert b.status == mod.BridgeStatus.CONNECTED
        b.stop()
        assert b.status == mod.BridgeStatus.STOPPED

    def test_start_noop_if_already_connected(self):
        zmq_mod, ctx, push, pull, pub = _zmq_mock()
        pull.recv_string.side_effect = Exception("stop")
        mod = _load_bridge_mod(zmq_mod)
        b = mod.MT5ZmqBridge()
        b.start()
        b.start()  # second call is no-op
        b.stop()

    def test_start_error_state_can_restart(self):
        zmq_mod, ctx, push, pull, pub = _zmq_mock()
        pull.recv_string.side_effect = Exception("stop")
        mod = _load_bridge_mod(zmq_mod)
        b = mod.MT5ZmqBridge()
        b._status = mod.BridgeStatus.ERROR
        b.start()
        assert b.status == mod.BridgeStatus.CONNECTED
        b.stop()

    def test_start_zmq_exception_sets_error(self):
        zmq_mod = MagicMock()
        zmq_mod.PUSH = 1
        zmq_mod.PULL = 2
        zmq_mod.PUB = 3
        zmq_mod.SNDTIMEO = 4
        zmq_mod.RCVTIMEO = 5
        zmq_mod.Context.side_effect = Exception("zmq init failed")
        mod = _load_bridge_mod(zmq_mod)
        b = mod.MT5ZmqBridge()
        with pytest.raises(Exception, match="zmq init failed"):
            b.start()
        assert b.status == mod.BridgeStatus.ERROR

    def test_stop_closes_sockets(self):
        zmq_mod, ctx, push, pull, pub = _zmq_mock()
        pull.recv_string.side_effect = Exception("stop")
        mod = _load_bridge_mod(zmq_mod)
        b = mod.MT5ZmqBridge()
        b.start()
        b.stop()
        push.close.assert_called()
        pull.close.assert_called()
        pub.close.assert_called()
        ctx.term.assert_called()

    def test_stop_suppresses_socket_close_exception(self):
        zmq_mod, ctx, push, pull, pub = _zmq_mock()
        pull.recv_string.side_effect = Exception("stop")
        push.close.side_effect = Exception("close error")
        mod = _load_bridge_mod(zmq_mod)
        b = mod.MT5ZmqBridge()
        b.start()
        b.stop()  # should not raise
        assert b.status == mod.BridgeStatus.STOPPED

    def test_stop_suppresses_ctx_term_exception(self):
        zmq_mod, ctx, push, pull, pub = _zmq_mock()
        pull.recv_string.side_effect = Exception("stop")
        ctx.term.side_effect = Exception("term error")
        mod = _load_bridge_mod(zmq_mod)
        b = mod.MT5ZmqBridge()
        b.start()
        b.stop()  # should not raise
        assert b.status == mod.BridgeStatus.STOPPED

    def test_context_manager(self):
        zmq_mod, ctx, push, pull, pub = _zmq_mock()
        pull.recv_string.side_effect = Exception("stop")
        mod = _load_bridge_mod(zmq_mod)
        with mod.MT5ZmqBridge(order_timeout_s=0.05) as b:
            assert b.status == mod.BridgeStatus.CONNECTED
        assert b.status == mod.BridgeStatus.STOPPED


class TestZmqBridgeRecvLoop:
    def test_dispatches_tick(self):
        zmq_mod, ctx, push, pull, pub = _zmq_mock()
        messages = [
            json.dumps({"type": "TICK", "symbol": "XAUUSD",
                        "bid": 1919.5, "ask": 1920.0, "ts": 1700000000000}),
        ]
        call_count = [0]

        def recv_side():
            if call_count[0] < len(messages):
                msg = messages[call_count[0]]
                call_count[0] += 1
                return msg
            raise Exception("done")

        pull.recv_string.side_effect = recv_side
        mod = _load_bridge_mod(zmq_mod)
        b = mod.MT5ZmqBridge(order_timeout_s=0.1)
        ticks = []
        b.register_tick_callback(lambda t: ticks.append(t))
        b.start()
        time.sleep(0.15)
        b.stop()
        assert b._stats.ticks_received >= 1

    def test_handles_zmq_again(self):
        zmq_mod, ctx, push, pull, pub = _zmq_mock()
        Again = type("Again", (Exception,), {})
        zmq_mod.Again = Again
        call_count = [0]

        def recv_side():
            call_count[0] += 1
            if call_count[0] <= 3:
                raise Again("timeout")
            raise Exception("done")

        pull.recv_string.side_effect = recv_side
        mod = _load_bridge_mod(zmq_mod)
        mod.zmq = zmq_mod
        b = mod.MT5ZmqBridge(order_timeout_s=0.1)
        b.start()
        time.sleep(0.1)
        b.stop()
        # Should complete without crashing

    def test_non_again_exception_logged(self):
        zmq_mod, ctx, push, pull, pub = _zmq_mock()
        call_count = [0]

        def recv_side():
            call_count[0] += 1
            if call_count[0] <= 2:
                raise OSError("network error")
            raise Exception("done")

        pull.recv_string.side_effect = recv_side
        mod = _load_bridge_mod(zmq_mod)
        b = mod.MT5ZmqBridge(order_timeout_s=0.1)
        b.start()
        time.sleep(0.1)
        b.stop()
        # Should complete without crashing


class TestZmqBridgeSendAndWait:
    def _connected(self, mod):
        b = mod.MT5ZmqBridge(order_timeout_s=0.1)
        b._status = mod.BridgeStatus.CONNECTED
        b._push = MagicMock()
        b._pull = MagicMock()
        b._pub = MagicMock()
        return b

    def test_send_order_with_sl_tp(self):
        zmq_mod, ctx, push, pull, pub = _zmq_mock()
        mod = _load_bridge_mod(zmq_mod)
        b = self._connected(mod)
        with pytest.raises(TimeoutError):
            b.send_order("XAUUSD", "BUY", 0.01, sl=1880.0, tp=1950.0)

    def test_close_position_with_lots(self):
        zmq_mod, ctx, push, pull, pub = _zmq_mock()
        mod = _load_bridge_mod(zmq_mod)
        b = self._connected(mod)
        with pytest.raises(TimeoutError):
            b.close_position(12345, lots=0.05)

    def test_modify_position_with_tp(self):
        zmq_mod, ctx, push, pull, pub = _zmq_mock()
        mod = _load_bridge_mod(zmq_mod)
        b = self._connected(mod)
        with pytest.raises(TimeoutError):
            b.modify_position(12345, sl=1880.0, tp=1950.0)

    def test_ping_success_path(self):
        zmq_mod, ctx, push, pull, pub = _zmq_mock()
        mod = _load_bridge_mod(zmq_mod)
        b = self._connected(mod)
        import threading
        from queue import Queue

        original_send = b._send_and_wait

        def inject_pong(cmd_id, payload, **kwargs):
            def _inject():
                time.sleep(0.01)
                with b._lock:
                    q = b._pending.get(cmd_id)
                if q:
                    q.put_nowait({"type": "PONG", "id": cmd_id, "ts": 0})
            t = threading.Thread(target=_inject, daemon=True)
            t.start()
            return original_send(cmd_id, payload, **kwargs)

        b._send_and_wait = inject_pong
        b.order_timeout_s = 2.0
        latency = b.ping()
        assert latency >= 0.0
        assert b._stats.last_heartbeat is not None

    def test_send_and_wait_push_sends_message(self):
        zmq_mod, ctx, push, pull, pub = _zmq_mock()
        mod = _load_bridge_mod(zmq_mod)
        b = self._connected(mod)
        import threading

        def inject_fill(cmd_id):
            time.sleep(0.01)
            with b._lock:
                q = b._pending.get(cmd_id)
            if q:
                q.put_nowait({
                    "type": "FILL", "id": cmd_id,
                    "ticket": 42, "symbol": "XAUUSD",
                    "side": "BUY", "lots": 0.01, "price": 1920.0,
                    "ts": int(time.time() * 1000),
                })

        original = b._send_and_wait

        def patched(cmd_id, payload, **kw):
            t = threading.Thread(target=inject_fill, args=(cmd_id,), daemon=True)
            t.start()
            return original(cmd_id, payload, **kw)

        b._send_and_wait = patched
        b.order_timeout_s = 2.0
        result = b.send_order("XAUUSD", "BUY", 0.01)
        assert result.ok is True
        assert result.ticket == 42
        assert b._stats.commands_sent >= 1

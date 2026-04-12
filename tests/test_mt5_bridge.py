# HOPEFX-AI-TRADING
# Tests for brokers/mt5_bridge.py
"""
Full branch coverage for _retry, EX5SignalExporter, and MT5Bridge.
All tests use _MT5_AVAILABLE=False (signal-export mode) — no Windows MT5 needed.
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import brokers.mt5_bridge as mt5_mod
from brokers.mt5_bridge import (
    EX5SignalExporter,
    FillStatus,
    MT5Bridge,
    MT5FillResult,
    MT5Order,
    OrderSide,
    OrderType,
    _retry,
)


# ── _retry decorator ──────────────────────────────────────────────────────────


class TestRetryDecorator:
    def test_success_on_first_attempt(self):
        calls = []

        @_retry(max_attempts=3, base_delay=0.001)
        def fn():
            calls.append(1)
            return "ok"

        assert fn() == "ok"
        assert len(calls) == 1

    def test_retries_on_failure_then_succeeds(self):
        calls = []

        @_retry(max_attempts=3, base_delay=0.001)
        def fn():
            calls.append(1)
            if len(calls) < 2:
                raise OSError("transient")
            return "ok"

        result = fn()
        assert result == "ok"
        assert len(calls) == 2

    def test_exhaustion_raises_last_exception(self):
        @_retry(max_attempts=3, base_delay=0.001)
        def fn():
            raise RuntimeError("always fails")

        with pytest.raises(RuntimeError, match="always fails"):
            fn()

    def test_backoff_doubles(self):
        wait_calls = []
        original_wait = threading.Event.wait

        def fake_wait(self, timeout=None):
            wait_calls.append(timeout)

        @_retry(max_attempts=3, base_delay=0.5)
        def fn():
            raise OSError("fail")

        with patch.object(threading.Event, "wait", fake_wait):
            with pytest.raises(OSError):
                fn()

        assert wait_calls[0] == pytest.approx(0.5)
        assert wait_calls[1] == pytest.approx(1.0)

    def test_only_catches_specified_exceptions(self):
        @_retry(max_attempts=3, base_delay=0.001)
        def fn():
            raise TypeError("not caught by retry")

        with pytest.raises(TypeError):
            fn()


# ── EX5SignalExporter ─────────────────────────────────────────────────────────


class TestEX5SignalExporter:
    def _make_order(self, symbol="XAUUSD", side=OrderSide.BUY, stop_loss=1900.0):
        return MT5Order(
            symbol=symbol,
            side=side,
            volume=0.1,
            order_type=OrderType.MARKET,
            stop_loss=stop_loss,
        )

    def test_export_creates_json_file(self, tmp_path):
        exporter = EX5SignalExporter(signal_dir=tmp_path)
        order = self._make_order()
        path = exporter.export(order)
        assert path.exists()
        data = json.loads(path.read_text())
        assert data["symbol"] == "XAUUSD"
        assert data["side"] == "BUY"
        assert data["status"] == "PENDING"

    def test_export_modify_creates_modify_file(self, tmp_path):
        exporter = EX5SignalExporter(signal_dir=tmp_path)
        path = exporter.export_modify(ticket=12345, symbol="XAUUSD", stop_loss=1950.0)
        assert path.exists()
        data = json.loads(path.read_text())
        assert data["action"] == "MODIFY"
        assert data["ticket"] == 12345
        assert data["stop_loss"] == pytest.approx(1950.0)

    def test_export_cancel_creates_cancel_file(self, tmp_path):
        exporter = EX5SignalExporter(signal_dir=tmp_path)
        path = exporter.export_cancel(ticket=99, symbol="XAUUSD")
        assert path.exists()
        data = json.loads(path.read_text())
        assert data["action"] == "CANCEL"
        assert data["ticket"] == 99

    def test_write_json_locked_atomic_rename(self, tmp_path):
        path = tmp_path / "test.json"
        EX5SignalExporter._write_json_locked(path, {"key": "value"})
        assert path.exists()
        assert json.loads(path.read_text()) == {"key": "value"}

    def test_write_json_locked_fallback_on_rename_failure(self, tmp_path):
        path = tmp_path / "test.json"
        # Simulate atomic rename failure → shutil.copy2 fallback
        with patch("pathlib.Path.replace", side_effect=OSError("rename failed")):
            EX5SignalExporter._write_json_locked(path, {"key": "fallback"})
        assert path.exists()

    def test_read_json_locked_valid_json(self, tmp_path):
        path = tmp_path / "signal.json"
        path.write_text(json.dumps({"status": "FILLED", "ticket": 1}))
        data = EX5SignalExporter._read_json_locked(path)
        assert data["status"] == "FILLED"

    def test_read_json_locked_invalid_json_returns_empty(self, tmp_path):
        path = tmp_path / "signal.json"
        path.write_text("INVALID{{{")
        data = EX5SignalExporter._read_json_locked(path)
        assert data == {}

    def test_poll_fill_returns_result_on_filled(self, tmp_path):
        exporter = EX5SignalExporter(signal_dir=tmp_path)
        order = self._make_order()
        path = exporter.export(order)

        # Simulate EA writing FILLED status
        data = json.loads(path.read_text())
        data["status"] = "FILLED"
        data["fill_price"] = 2000.0
        data["ticket"] = 12345
        path.write_text(json.dumps(data))

        result = exporter.poll_fill(path, timeout_sec=5.0)
        assert result.status == FillStatus.FILLED
        assert result.fill_price == pytest.approx(2000.0)
        assert result.ticket == 12345

    def test_poll_fill_raises_on_rejected(self, tmp_path):
        exporter = EX5SignalExporter(signal_dir=tmp_path)
        order = self._make_order()
        path = exporter.export(order)

        data = json.loads(path.read_text())
        data["status"] = "REJECTED"
        data["reject_reason"] = "insufficient margin"
        path.write_text(json.dumps(data))

        with pytest.raises(RuntimeError, match="rejected"):
            exporter.poll_fill(path, timeout_sec=5.0)

    def test_poll_fill_raises_timeout(self, tmp_path):
        exporter = EX5SignalExporter(signal_dir=tmp_path)
        order = self._make_order()
        path = exporter.export(order)
        # File stays PENDING → timeout

        with pytest.raises(TimeoutError):
            exporter.poll_fill(path, timeout_sec=0.1)

    def test_cleanup_old_signals_removes_old_files(self, tmp_path):
        exporter = EX5SignalExporter(signal_dir=tmp_path)
        old_file = tmp_path / "old_signal.json"
        old_file.write_text("{}")
        # Set mtime to 25 hours ago
        old_time = time.time() - 25 * 3600
        import os
        os.utime(old_file, (old_time, old_time))

        new_file = tmp_path / "new_signal.json"
        new_file.write_text("{}")

        removed = exporter.cleanup_old_signals(max_age_hours=24)
        assert removed == 1
        assert not old_file.exists()
        assert new_file.exists()


# ── MT5Bridge — signal-export mode (_MT5_AVAILABLE=False) ────────────────────


class TestMT5BridgeSignalExportMode:
    def _make_bridge(self, tmp_path, enforcer=None):
        bridge = MT5Bridge(
            server="test_server",
            login=12345,
            password="test_pass",
            enforcer=enforcer,
            signal_dir=tmp_path,
        )
        return bridge

    def test_connect_signal_export_mode(self, tmp_path):
        bridge = self._make_bridge(tmp_path)
        # _MT5_AVAILABLE is False in this environment
        result = bridge.connect()
        assert result is True
        assert bridge._connected is True

    def test_disconnect(self, tmp_path):
        bridge = self._make_bridge(tmp_path)
        bridge.connect()
        bridge.disconnect()
        assert bridge._connected is False

    def test_require_connected_raises_when_not_connected(self, tmp_path):
        bridge = self._make_bridge(tmp_path)
        with pytest.raises(RuntimeError, match="not connected"):
            bridge._require_connected()

    def test_require_connected_passes_when_connected(self, tmp_path):
        bridge = self._make_bridge(tmp_path)
        bridge.connect()
        bridge._require_connected()  # must not raise

    def test_send_order_no_stop_loss_raises(self, tmp_path):
        bridge = self._make_bridge(tmp_path)
        bridge.connect()
        order = MT5Order(
            symbol="XAUUSD",
            side=OrderSide.BUY,
            volume=0.1,
            stop_loss=None,
        )
        with pytest.raises(ValueError, match="stop_loss"):
            bridge.send_order(order)

    def test_send_order_zero_stop_loss_raises(self, tmp_path):
        bridge = self._make_bridge(tmp_path)
        bridge.connect()
        order = MT5Order(
            symbol="XAUUSD",
            side=OrderSide.BUY,
            volume=0.1,
            stop_loss=0.0,
        )
        with pytest.raises(ValueError, match="stop_loss"):
            bridge.send_order(order)

    def test_send_order_enforcer_blocks(self, tmp_path):
        enforcer = MagicMock()
        enforcer.before_execute.return_value = (False, "daily DD exceeded")
        bridge = self._make_bridge(tmp_path, enforcer=enforcer)
        bridge.connect()
        order = MT5Order(
            symbol="XAUUSD",
            side=OrderSide.BUY,
            volume=0.1,
            stop_loss=1900.0,
        )
        with pytest.raises(RuntimeError, match="PropEnforcer"):
            bridge.send_order(order)

    def test_send_order_signal_export_mode_writes_file(self, tmp_path):
        bridge = self._make_bridge(tmp_path)
        bridge.connect()
        order = MT5Order(
            symbol="XAUUSD",
            side=OrderSide.BUY,
            volume=0.1,
            stop_loss=1900.0,
            timeout_sec=0.1,
        )
        # poll_fill will timeout — patch it to return a result
        mock_result = MT5FillResult(
            ticket=1, status=FillStatus.FILLED,
            filled_volume=0.1, fill_price=2000.0,
            commission=0.0, swap=0.0, profit=0.0, comment="ok",
        )
        with patch.object(bridge._exporter, "poll_fill", return_value=mock_result):
            result = bridge.send_order(order)
        assert result.status == FillStatus.FILLED

    def test_send_order_enforcer_allows(self, tmp_path):
        enforcer = MagicMock()
        enforcer.before_execute.return_value = (True, "")
        bridge = self._make_bridge(tmp_path, enforcer=enforcer)
        bridge.connect()
        order = MT5Order(
            symbol="XAUUSD",
            side=OrderSide.BUY,
            volume=0.1,
            stop_loss=1900.0,
            timeout_sec=0.1,
        )
        mock_result = MT5FillResult(
            ticket=1, status=FillStatus.FILLED,
            filled_volume=0.1, fill_price=2000.0,
            commission=0.0, swap=0.0, profit=0.0, comment="ok",
        )
        with patch.object(bridge._exporter, "poll_fill", return_value=mock_result):
            result = bridge.send_order(order)
        assert result.status == FillStatus.FILLED

    def test_close_position_signal_export_mode(self, tmp_path):
        bridge = self._make_bridge(tmp_path)
        bridge.connect()
        mock_result = MT5FillResult(
            ticket=1, status=FillStatus.FILLED,
            filled_volume=0.1, fill_price=2000.0,
            commission=0.0, swap=0.0, profit=0.0, comment="close",
        )
        with patch.object(bridge._exporter, "poll_fill", return_value=mock_result):
            results = bridge.close_position("XAUUSD", volume=0.1)
        assert len(results) == 1
        assert results[0].status == FillStatus.FILLED

    def test_context_manager(self, tmp_path):
        bridge = self._make_bridge(tmp_path)
        with bridge as b:
            assert b._connected is True
        assert bridge._connected is False


# ── MT5Bridge.from_env ────────────────────────────────────────────────────────


class TestFromEnv:
    def test_from_env_success(self, monkeypatch):
        monkeypatch.setenv("MT5_LOGIN", "12345")
        monkeypatch.setenv("MT5_PASSWORD", "pass")
        monkeypatch.setenv("MT5_SERVER", "server")
        bridge = MT5Bridge.from_env()
        assert bridge.login == 12345
        assert bridge.server == "server"

    def test_from_env_no_login_raises(self, monkeypatch):
        monkeypatch.delenv("MT5_LOGIN", raising=False)
        with pytest.raises(OSError, match="MT5_LOGIN"):
            MT5Bridge.from_env()


# ── MT5Bridge async wrappers ──────────────────────────────────────────────────


class TestAsyncWrappers:
    @pytest.mark.asyncio
    async def test_async_send_order(self, tmp_path):
        bridge = MT5Bridge(
            server="s", login=1, password="p", signal_dir=tmp_path,
        )
        bridge.connect()
        order = MT5Order(
            symbol="XAUUSD", side=OrderSide.BUY, volume=0.1, stop_loss=1900.0,
            timeout_sec=0.1,
        )
        mock_result = MT5FillResult(
            ticket=1, status=FillStatus.FILLED,
            filled_volume=0.1, fill_price=2000.0,
            commission=0.0, swap=0.0, profit=0.0, comment="ok",
        )
        with patch.object(bridge._exporter, "poll_fill", return_value=mock_result):
            result = await bridge.async_send_order(order)
        assert result.status == FillStatus.FILLED

    @pytest.mark.asyncio
    async def test_async_close_position(self, tmp_path):
        bridge = MT5Bridge(
            server="s", login=1, password="p", signal_dir=tmp_path,
        )
        bridge.connect()
        mock_result = MT5FillResult(
            ticket=1, status=FillStatus.FILLED,
            filled_volume=0.1, fill_price=2000.0,
            commission=0.0, swap=0.0, profit=0.0, comment="close",
        )
        with patch.object(bridge._exporter, "poll_fill", return_value=mock_result):
            results = await bridge.async_close_position("XAUUSD", volume=0.1)
        assert len(results) == 1

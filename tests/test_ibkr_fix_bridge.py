# HOPEFX-AI-TRADING
# Tests for brokers/ibkr_fix_bridge.py
"""
Full branch coverage for IBKRFIXConfig, IBKRFIXBridge.
FIXAdapter is mocked — no FIX network required.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from brokers.ibkr_fix_bridge import IBKRFIXBridge, IBKRFIXConfig
from execution.fix_adapter import FIXExecType, FIXFillReport, FIXOrder, FIXOrdType, FIXSide


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_fill_report(cl_ord_id="test_cl_ord"):
    return FIXFillReport(
        cl_ord_id=cl_ord_id,
        order_id="ord1",
        exec_type=FIXExecType.FILL,
        symbol="XAUUSD",
        side=FIXSide.BUY,
        filled_qty=1.0,
        avg_px=2000.0,
        leaves_qty=0.0,
        cum_qty=1.0,
        latency_ms=12.5,
    )


def _make_fix_order(symbol="XAUUSD"):
    return FIXOrder(
        symbol=symbol,
        side=FIXSide.BUY,
        quantity=1.0,
        ord_type=FIXOrdType.MARKET,
    )


def _make_mock_adapter():
    adapter = MagicMock()
    adapter.circuit_breaker = MagicMock()
    adapter.circuit_breaker.check = MagicMock()
    adapter.send_order = AsyncMock(return_value=_make_fill_report())
    adapter.start = MagicMock()
    adapter.stop = MagicMock()
    return adapter


def _make_started_bridge(kill_switch=None):
    """Return a bridge that is already started with a mocked adapter."""
    bridge = IBKRFIXBridge(kill_switch=kill_switch)
    bridge._adapter = _make_mock_adapter()
    bridge._started = True
    bridge._cfg_file = "/tmp/test_ibkr_fix.cfg"
    return bridge


# ── IBKRFIXConfig ─────────────────────────────────────────────────────────────


class TestIBKRFIXConfig:
    def test_is_paper_port_4002(self):
        cfg = IBKRFIXConfig(port=4002)
        assert cfg.is_paper is True

    def test_is_paper_port_7497(self):
        cfg = IBKRFIXConfig(port=7497)
        assert cfg.is_paper is True

    def test_is_paper_port_4001_false(self):
        cfg = IBKRFIXConfig(port=4001)
        assert cfg.is_paper is False

    def test_is_paper_port_7496_false(self):
        cfg = IBKRFIXConfig(port=7496)
        assert cfg.is_paper is False

    def test_generate_quickfix_cfg_contains_required_fields(self, tmp_path):
        cfg = IBKRFIXConfig(
            sender_comp_id="HOPEFX",
            target_comp_id="IBFX",
            host="127.0.0.1",
            port=4002,
            store_path=str(tmp_path / "store"),
            log_path=str(tmp_path / "logs"),
        )
        content = cfg.generate_quickfix_cfg()
        assert "SenderCompID=HOPEFX" in content
        assert "TargetCompID=IBFX" in content
        assert "SocketConnectHost=127.0.0.1" in content
        assert "SocketConnectPort=4002" in content
        assert "BeginString=FIX.4.4" in content
        assert "ConnectionType=initiator" in content

    def test_generate_quickfix_cfg_creates_directories(self, tmp_path):
        store = tmp_path / "store"
        logs = tmp_path / "logs"
        cfg = IBKRFIXConfig(
            store_path=str(store),
            log_path=str(logs),
        )
        cfg.generate_quickfix_cfg()
        assert store.exists()
        assert logs.exists()

    def test_reset_on_logon_true(self, tmp_path):
        cfg = IBKRFIXConfig(
            reset_on_logon=True,
            store_path=str(tmp_path / "s"),
            log_path=str(tmp_path / "l"),
        )
        content = cfg.generate_quickfix_cfg()
        assert "ResetOnLogon=Y" in content

    def test_reset_on_logon_false(self, tmp_path):
        cfg = IBKRFIXConfig(
            reset_on_logon=False,
            store_path=str(tmp_path / "s"),
            log_path=str(tmp_path / "l"),
        )
        content = cfg.generate_quickfix_cfg()
        assert "ResetOnLogon=N" in content


# ── IBKRFIXBridge.from_env ────────────────────────────────────────────────────


class TestFromEnv:
    def test_from_env_returns_bridge(self):
        bridge = IBKRFIXBridge.from_env()
        assert isinstance(bridge, IBKRFIXBridge)
        assert bridge._started is False


# ── IBKRFIXBridge.start ───────────────────────────────────────────────────────


class TestStart:
    def test_start_already_started_logs_warning(self):
        bridge = _make_started_bridge()
        # Calling start() again should log warning and return without error
        bridge.start()  # should not raise
        assert bridge._started is True

    def test_start_creates_adapter_and_sets_started(self, tmp_path):
        mock_adapter = _make_mock_adapter()
        cfg = IBKRFIXConfig(
            store_path=str(tmp_path / "store"),
            log_path=str(tmp_path / "logs"),
        )
        bridge = IBKRFIXBridge(config=cfg)

        with patch("brokers.ibkr_fix_bridge.FIXAdapter", return_value=mock_adapter):
            bridge.start()

        assert bridge._started is True
        assert bridge._adapter is mock_adapter
        mock_adapter.start.assert_called_once()

    def test_start_writes_temp_config_file(self, tmp_path):
        mock_adapter = _make_mock_adapter()
        cfg = IBKRFIXConfig(
            store_path=str(tmp_path / "store"),
            log_path=str(tmp_path / "logs"),
        )
        bridge = IBKRFIXBridge(config=cfg)

        with patch("brokers.ibkr_fix_bridge.FIXAdapter", return_value=mock_adapter):
            bridge.start()

        assert bridge._cfg_file is not None
        assert Path(bridge._cfg_file).exists()
        # Cleanup
        bridge.stop()


# ── IBKRFIXBridge.stop ────────────────────────────────────────────────────────


class TestStop:
    def test_stop_calls_adapter_stop(self):
        bridge = _make_started_bridge()
        bridge.stop()
        bridge._adapter.stop.assert_called_once()
        assert bridge._started is False

    def test_stop_when_adapter_raises_logs_error(self):
        bridge = _make_started_bridge()
        bridge._adapter.stop.side_effect = RuntimeError("adapter error")
        bridge.stop()  # must not raise
        assert bridge._started is False

    def test_stop_deletes_cfg_file(self, tmp_path):
        cfg_file = tmp_path / "test.cfg"
        cfg_file.write_text("[DEFAULT]")
        bridge = _make_started_bridge()
        bridge._cfg_file = str(cfg_file)
        bridge.stop()
        assert not cfg_file.exists()

    def test_stop_no_adapter_no_error(self):
        bridge = IBKRFIXBridge()
        bridge.stop()  # must not raise


# ── IBKRFIXBridge.place_order ─────────────────────────────────────────────────


class TestPlaceOrder:
    @pytest.mark.asyncio
    async def test_place_order_success(self):
        bridge = _make_started_bridge()
        order = _make_fix_order()
        report = await bridge.place_order(order)
        assert report.filled_qty == pytest.approx(1.0)
        assert report.avg_px == pytest.approx(2000.0)

    @pytest.mark.asyncio
    async def test_place_order_not_started_raises(self):
        bridge = IBKRFIXBridge()
        order = _make_fix_order()
        with pytest.raises(RuntimeError, match="not started"):
            await bridge.place_order(order)

    @pytest.mark.asyncio
    async def test_place_order_kill_switch_active_raises(self):
        kill_switch = MagicMock()
        kill_switch.is_active.return_value = True
        kill_switch._reason = "manual kill"
        bridge = _make_started_bridge(kill_switch=kill_switch)
        order = _make_fix_order()
        with pytest.raises(RuntimeError, match="kill switch"):
            await bridge.place_order(order)

    @pytest.mark.asyncio
    async def test_place_order_kill_switch_inactive_proceeds(self):
        kill_switch = MagicMock()
        kill_switch.is_active.return_value = False
        bridge = _make_started_bridge(kill_switch=kill_switch)
        order = _make_fix_order()
        report = await bridge.place_order(order)
        assert report is not None

    @pytest.mark.asyncio
    async def test_place_order_adapter_exception_reraises(self):
        bridge = _make_started_bridge()
        bridge._adapter.send_order.side_effect = RuntimeError("FIX error")
        order = _make_fix_order()
        with pytest.raises(RuntimeError, match="FIX error"):
            await bridge.place_order(order)

    @pytest.mark.asyncio
    async def test_place_order_circuit_breaker_checked(self):
        bridge = _make_started_bridge()
        order = _make_fix_order()
        await bridge.place_order(order)
        bridge._adapter.circuit_breaker.check.assert_called_once()


# ── _map_symbol ───────────────────────────────────────────────────────────────


class TestMapSymbol:
    def test_gold_alias_maps_to_xauusd(self):
        order = _make_fix_order(symbol="GOLD")
        mapped = IBKRFIXBridge._map_symbol(order)
        assert mapped.symbol == "XAUUSD"

    def test_xau_slash_usd_maps_to_xauusd(self):
        order = _make_fix_order(symbol="XAU/USD")
        mapped = IBKRFIXBridge._map_symbol(order)
        assert mapped.symbol == "XAUUSD"

    def test_xau_underscore_usd_maps_to_xauusd(self):
        order = _make_fix_order(symbol="XAU_USD")
        mapped = IBKRFIXBridge._map_symbol(order)
        assert mapped.symbol == "XAUUSD"

    def test_xau_maps_to_xauusd(self):
        order = _make_fix_order(symbol="XAU")
        mapped = IBKRFIXBridge._map_symbol(order)
        assert mapped.symbol == "XAUUSD"

    def test_xauusd_passthrough(self):
        order = _make_fix_order(symbol="XAUUSD")
        mapped = IBKRFIXBridge._map_symbol(order)
        assert mapped.symbol == "XAUUSD"

    def test_non_alias_passthrough(self):
        order = _make_fix_order(symbol="EURUSD")
        mapped = IBKRFIXBridge._map_symbol(order)
        assert mapped.symbol == "EURUSD"

    def test_case_insensitive_gold(self):
        order = _make_fix_order(symbol="gold")
        mapped = IBKRFIXBridge._map_symbol(order)
        assert mapped.symbol == "XAUUSD"

    def test_map_returns_new_object_not_same(self):
        order = _make_fix_order(symbol="GOLD")
        mapped = IBKRFIXBridge._map_symbol(order)
        assert mapped is not order


# ── Context manager ───────────────────────────────────────────────────────────


class TestContextManager:
    def test_enter_calls_start(self, tmp_path):
        mock_adapter = _make_mock_adapter()
        cfg = IBKRFIXConfig(
            store_path=str(tmp_path / "store"),
            log_path=str(tmp_path / "logs"),
        )
        bridge = IBKRFIXBridge(config=cfg)
        with patch("brokers.ibkr_fix_bridge.FIXAdapter", return_value=mock_adapter):
            with bridge as b:
                assert b._started is True
        assert bridge._started is False

    def test_exit_calls_stop(self, tmp_path):
        mock_adapter = _make_mock_adapter()
        cfg = IBKRFIXConfig(
            store_path=str(tmp_path / "store"),
            log_path=str(tmp_path / "logs"),
        )
        bridge = IBKRFIXBridge(config=cfg)
        with patch("brokers.ibkr_fix_bridge.FIXAdapter", return_value=mock_adapter):
            with bridge:
                pass
        mock_adapter.stop.assert_called_once()

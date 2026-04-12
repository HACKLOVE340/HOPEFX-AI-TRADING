# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# AGPL-3.0 — Share all modifications
"""
Unit tests for brokers/manager.py.
Targets the 75% → 90%+ branch coverage gap.
"""
from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from brokers.base import AccountInfo, Order, OrderSide, OrderStatus, OrderType, Position
from brokers.manager import BrokerHealth, BrokerManager, _MAX_CONSECUTIVE_FAILURES


# ── Helpers ───────────────────────────────────────────────────────────────────

def _mock_broker(connected: bool = True) -> MagicMock:
    b = MagicMock()
    b.is_connected.return_value = connected
    b.connect.return_value = connected
    b.disconnect.return_value = True
    b.__class__.__name__ = "MockBroker"
    return b


def _manager_with_broker(name="paper", connected=True) -> tuple[BrokerManager, MagicMock]:
    mgr = BrokerManager(primary_broker_name=name)
    broker = _mock_broker(connected=connected)
    mgr.register(name, broker)
    mgr._active_name = name
    return mgr, broker


# ── BrokerHealth ──────────────────────────────────────────────────────────────

class TestBrokerHealth:
    def test_to_dict_has_expected_keys(self):
        h = BrokerHealth("paper", True, 0, None, True, "PAPER")
        d = h.to_dict()
        assert d["name"] == "paper"
        assert d["connected"] is True
        assert "timestamp" in d


# ── register / set_active ─────────────────────────────────────────────────────

class TestRegisterSetActive:
    def test_register_stores_broker(self):
        mgr = BrokerManager()
        b = _mock_broker()
        mgr.register("test", b)
        assert "test" in mgr._brokers

    def test_set_active_switches_broker(self):
        mgr = BrokerManager()
        b1, b2 = _mock_broker(), _mock_broker()
        mgr.register("a", b1)
        mgr.register("b", b2)
        mgr._active_name = "a"
        mgr.set_active("b")
        assert mgr._active_name == "b"

    def test_set_active_raises_for_unknown(self):
        mgr = BrokerManager()
        with pytest.raises(ValueError, match="not registered"):
            mgr.set_active("nonexistent")


# ── connect_all / disconnect_all ──────────────────────────────────────────────

class TestConnectDisconnect:
    def test_connect_all_returns_results(self):
        mgr, broker = _manager_with_broker()
        results = mgr.connect_all()
        assert "paper" in results
        assert results["paper"] is True

    def test_connect_all_handles_exception(self):
        mgr, broker = _manager_with_broker()
        broker.connect.side_effect = RuntimeError("conn failed")
        results = mgr.connect_all()
        assert results["paper"] is False

    def test_disconnect_all_calls_each_broker(self):
        mgr, broker = _manager_with_broker()
        mgr.disconnect_all()
        broker.disconnect.assert_called_once()

    def test_disconnect_all_handles_exception(self):
        mgr, broker = _manager_with_broker()
        broker.disconnect.side_effect = RuntimeError("disc failed")
        mgr.disconnect_all()  # must not raise

    def test_connect_all_starts_fix_bridge(self):
        mgr, _ = _manager_with_broker()
        mock_fix = MagicMock()
        mgr._fix_bridge = mock_fix
        mgr.connect_all()
        mock_fix.start.assert_called_once()

    def test_connect_all_handles_fix_bridge_exception(self):
        mgr, _ = _manager_with_broker()
        mock_fix = MagicMock()
        mock_fix.start.side_effect = RuntimeError("fix failed")
        mgr._fix_bridge = mock_fix
        mgr.connect_all()  # must not raise

    def test_disconnect_all_stops_fix_bridge(self):
        mgr, _ = _manager_with_broker()
        mock_fix = MagicMock()
        mgr._fix_bridge = mock_fix
        mgr.disconnect_all()
        mock_fix.stop.assert_called_once()

    def test_connect_primary_returns_true(self):
        mgr, broker = _manager_with_broker()
        assert mgr.connect_primary() is True

    def test_connect_primary_returns_false_when_no_broker(self):
        mgr = BrokerManager()
        assert mgr.connect_primary() is False

    def test_connect_primary_handles_exception(self):
        mgr, broker = _manager_with_broker()
        broker.connect.side_effect = RuntimeError("fail")
        assert mgr.connect_primary() is False


# ── place_order ───────────────────────────────────────────────────────────────

class TestPlaceOrder:
    def test_place_order_delegates_to_broker(self):
        mgr, broker = _manager_with_broker()
        mock_order = MagicMock(spec=Order)
        broker.place_order.return_value = mock_order

        result = mgr.place_order("XAUUSD", OrderSide.BUY, OrderType.MARKET, 1.0)
        assert result is mock_order

    def test_place_order_blocked_by_kill_switch(self):
        mgr, _ = _manager_with_broker()
        ks = MagicMock()
        ks.is_active.return_value = True
        ks._reason = "emergency halt"
        mgr._kill_switch = ks

        with pytest.raises(RuntimeError, match="kill switch"):
            mgr.place_order("XAUUSD", OrderSide.BUY, OrderType.MARKET, 1.0)

    def test_place_order_raises_when_not_connected(self):
        mgr, _ = _manager_with_broker(connected=False)
        with pytest.raises(RuntimeError, match="not connected"):
            mgr.place_order("XAUUSD", OrderSide.BUY, OrderType.MARKET, 1.0)

    def test_place_order_records_failure_on_exception(self):
        mgr, broker = _manager_with_broker()
        broker.place_order.side_effect = RuntimeError("order failed")

        with pytest.raises(RuntimeError):
            mgr.place_order("XAUUSD", OrderSide.BUY, OrderType.MARKET, 1.0)

        assert mgr._consecutive_failures["paper"] == 1


# ── cancel_order ──────────────────────────────────────────────────────────────

class TestCancelOrder:
    def test_cancel_order_delegates(self):
        mgr, broker = _manager_with_broker()
        broker.cancel_order.return_value = True
        assert mgr.cancel_order("order-1") is True

    def test_cancel_order_blocked_by_kill_switch(self):
        mgr, _ = _manager_with_broker()
        ks = MagicMock()
        ks.is_active.return_value = True
        mgr._kill_switch = ks
        with pytest.raises(RuntimeError, match="kill switch"):
            mgr.cancel_order("order-1")


# ── get_order ─────────────────────────────────────────────────────────────────

class TestGetOrder:
    def test_get_order_delegates(self):
        mgr, broker = _manager_with_broker()
        broker.get_order.return_value = None
        assert mgr.get_order("order-1") is None

    def test_get_order_records_failure(self):
        mgr, broker = _manager_with_broker()
        broker.get_order.side_effect = RuntimeError("fail")
        with pytest.raises(RuntimeError):
            mgr.get_order("order-1")
        assert mgr._consecutive_failures["paper"] == 1


# ── get_positions / close_position ───────────────────────────────────────────

class TestPositions:
    def test_get_positions_delegates(self):
        mgr, broker = _manager_with_broker()
        broker.get_positions.return_value = []
        assert mgr.get_positions() == []

    def test_close_position_delegates(self):
        mgr, broker = _manager_with_broker()
        broker.close_position.return_value = True
        assert mgr.close_position("XAUUSD") is True

    def test_close_all_positions_closes_each(self):
        mgr, broker = _manager_with_broker()
        pos = MagicMock(spec=Position)
        pos.symbol = "XAUUSD"
        broker.get_positions.return_value = [pos]
        broker.close_position.return_value = True

        results = mgr.close_all_positions()
        assert results["XAUUSD"] is True

    def test_close_all_positions_handles_get_positions_failure(self):
        mgr, broker = _manager_with_broker()
        broker.get_positions.side_effect = RuntimeError("fail")
        results = mgr.close_all_positions()
        assert results == {}

    def test_close_all_positions_handles_close_failure(self):
        mgr, broker = _manager_with_broker()
        pos = MagicMock(spec=Position)
        pos.symbol = "XAUUSD"
        broker.get_positions.return_value = [pos]
        broker.close_position.side_effect = RuntimeError("close failed")

        results = mgr.close_all_positions()
        assert results["XAUUSD"] is False

    def test_close_all_positions_blocked_by_kill_switch(self):
        mgr, _ = _manager_with_broker()
        ks = MagicMock()
        ks.is_active.return_value = True
        mgr._kill_switch = ks
        with pytest.raises(RuntimeError, match="kill switch"):
            mgr.close_all_positions()


# ── get_account_info / get_market_data ───────────────────────────────────────

class TestAccountAndMarket:
    def test_get_account_info_delegates(self):
        mgr, broker = _manager_with_broker()
        mock_info = MagicMock(spec=AccountInfo)
        broker.get_account_info.return_value = mock_info
        assert mgr.get_account_info() is mock_info

    def test_get_market_data_delegates(self):
        mgr, broker = _manager_with_broker()
        broker.get_market_data.return_value = [{"close": 1800.0}]
        result = mgr.get_market_data("XAUUSD")
        assert result[0]["close"] == 1800.0


# ── heartbeat ─────────────────────────────────────────────────────────────────

class TestHeartbeat:
    def test_heartbeat_returns_health_for_each_broker(self):
        mgr, broker = _manager_with_broker()
        result = mgr.heartbeat()
        assert "paper" in result
        assert isinstance(result["paper"], BrokerHealth)

    def test_heartbeat_handles_is_connected_exception(self):
        mgr, broker = _manager_with_broker()
        broker.is_connected.side_effect = RuntimeError("fail")
        result = mgr.heartbeat()
        assert result["paper"].connected is False

    def test_heartbeat_detects_paper_mode(self):
        mgr, broker = _manager_with_broker()
        # Remove _cfg so the paper_trading branch is reached
        del broker._cfg
        broker.paper_trading = True
        result = mgr.heartbeat()
        assert result["paper"].mode == "PAPER"

    def test_heartbeat_detects_live_mode(self):
        mgr, broker = _manager_with_broker()
        del broker._cfg
        broker.paper_trading = False
        result = mgr.heartbeat()
        assert result["paper"].mode == "LIVE"


# ── is_connected / get_active_broker_name ────────────────────────────────────

class TestStatus:
    def test_is_connected_true(self):
        mgr, _ = _manager_with_broker()
        assert mgr.is_connected() is True

    def test_is_connected_false_when_no_broker(self):
        mgr = BrokerManager()
        assert mgr.is_connected() is False

    def test_is_connected_handles_exception(self):
        mgr, broker = _manager_with_broker()
        broker.is_connected.side_effect = RuntimeError("fail")
        assert mgr.is_connected() is False

    def test_get_active_broker_name(self):
        mgr, _ = _manager_with_broker("paper")
        assert mgr.get_active_broker_name() == "paper"


# ── _record_failure / auto-failover ──────────────────────────────────────────

class TestFailureAndFailover:
    def test_record_failure_increments_counter(self):
        mgr, _ = _manager_with_broker()
        mgr._record_failure(RuntimeError("err"))
        assert mgr._consecutive_failures["paper"] == 1

    def test_reset_failures_clears_counter(self):
        mgr, _ = _manager_with_broker()
        mgr._consecutive_failures["paper"] = 3
        mgr._reset_failures()
        assert mgr._consecutive_failures["paper"] == 0

    def test_auto_failover_to_paper_after_max_failures(self):
        mgr = BrokerManager(primary_broker_name="ibkr")
        ibkr = _mock_broker()
        paper = _mock_broker()
        mgr.register("ibkr", ibkr)
        mgr.register("paper", paper)
        mgr._active_name = "ibkr"
        mgr._failover_chain = ["ibkr", "paper"]

        for _ in range(_MAX_CONSECUTIVE_FAILURES):
            mgr._record_failure(RuntimeError("fail"))

        assert mgr._active_name == "paper"

    def test_auto_failover_logs_when_no_target(self):
        mgr, _ = _manager_with_broker("paper")
        mgr._failover_chain = ["paper"]  # no other broker

        for _ in range(_MAX_CONSECUTIVE_FAILURES):
            mgr._record_failure(RuntimeError("fail"))

        # Should stay on paper (no other target)
        assert mgr._active_name == "paper"

    def test_build_failover_chain_order(self):
        mgr = BrokerManager(primary_broker_name="ibkr")
        mgr.register("ibkr", _mock_broker())
        mgr.register("oanda", _mock_broker())
        mgr.register("paper", _mock_broker())
        chain = mgr._build_failover_chain()
        assert chain[0] == "ibkr"
        assert chain[-1] == "paper"
        assert "oanda" in chain


# ── place_order_fix ───────────────────────────────────────────────────────────

class TestPlaceOrderFix:
    @pytest.mark.asyncio
    async def test_raises_when_fix_bridge_not_started(self):
        mgr, _ = _manager_with_broker()
        with pytest.raises(RuntimeError, match="FIX bridge not started"):
            await mgr.place_order_fix(MagicMock())

    @pytest.mark.asyncio
    async def test_delegates_to_fix_bridge_when_started(self):
        mgr, _ = _manager_with_broker()
        mock_fix = MagicMock()
        mock_fix._started = True
        mock_fix.place_order = AsyncMock(return_value={"status": "ok"})
        mgr._fix_bridge = mock_fix

        result = await mgr.place_order_fix(MagicMock())
        assert result == {"status": "ok"}


# ── Context manager ───────────────────────────────────────────────────────────

class TestContextManager:
    def test_enter_calls_connect_all(self):
        mgr, broker = _manager_with_broker()
        with mgr:
            broker.connect.assert_called()

    def test_exit_calls_disconnect_all(self):
        mgr, broker = _manager_with_broker()
        with mgr:
            pass
        broker.disconnect.assert_called()


# ── from_env ──────────────────────────────────────────────────────────────────

class TestFromEnv:
    def test_from_env_creates_manager(self):
        with patch.dict(os.environ, {"BROKER_PRIMARY": "paper", "BROKER_ENABLE_FIX": "false"}), \
             patch.object(BrokerManager, "_auto_register"):
            mgr = BrokerManager.from_env()
        assert isinstance(mgr, BrokerManager)
        assert mgr._primary_name == "paper"

    def test_from_env_enable_fix(self):
        with patch.dict(os.environ, {"BROKER_PRIMARY": "paper", "BROKER_ENABLE_FIX": "true"}), \
             patch.object(BrokerManager, "_auto_register"):
            mgr = BrokerManager.from_env()
        assert mgr._enable_fix is True

# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""Direct MT5 mode and ZMQ bridge start/stop coverage tests."""

from __future__ import annotations
from unittest.mock import MagicMock, patch
import pytest

from brokers.mt5_bridge import (
    MT5Order,
    FillStatus,
    OrderSide,
    OrderType,
)


def _mt5_mock():
    m = MagicMock()
    m.TRADE_RETCODE_DONE = 10009
    m.TRADE_ACTION_DEAL = 1
    m.TRADE_ACTION_PENDING = 5
    m.TRADE_ACTION_SLTP = 6
    m.TRADE_ACTION_REMOVE = 8
    m.ORDER_TYPE_BUY = 0
    m.ORDER_TYPE_SELL = 1
    m.ORDER_TYPE_BUY_LIMIT = 2
    m.ORDER_TYPE_SELL_LIMIT = 3
    m.ORDER_TYPE_BUY_STOP = 4
    m.ORDER_TYPE_SELL_STOP = 5
    m.ORDER_TIME_GTC = 1
    m.ORDER_FILLING_IOC = 1
    m.POSITION_TYPE_BUY = 0
    m.POSITION_TYPE_SELL = 1
    return m


@pytest.fixture(autouse=True)
def _restore_mt5_bridge_module():
    """Restore brokers.mt5_bridge module-level globals after every test.

    _bridge() mutates mod.mt5 and mod._MT5_AVAILABLE directly so that
    _send_direct() picks up the mock.  Without cleanup those mutations
    persist across tests and break TestMT5BridgeSignalMode (which relies
    on _MT5_AVAILABLE=False) when the full suite runs.
    """
    import brokers.mt5_bridge as mod

    orig_mt5 = mod.mt5
    orig_avail = mod._MT5_AVAILABLE
    yield
    mod.mt5 = orig_mt5
    mod._MT5_AVAILABLE = orig_avail


def _bridge(tmp_path, mt5):
    import brokers.mt5_bridge as mod

    # Mutate module globals so _send_direct() uses our mock.
    # The _restore_mt5_bridge_module fixture (above) undoes this after each test.
    mod.mt5 = mt5
    mod._MT5_AVAILABLE = True
    b = mod.MT5Bridge(
        server="Demo",
        login=12345678,
        password="pass",  # pragma: allowlist secret
        signal_dir=tmp_path / "signals",  # pragma: allowlist secret
    )  # pragma: allowlist secret
    b._connected = True
    return b, mod


class TestSendDirect:
    def test_market_buy(self, tmp_path):
        mt5 = _mt5_mock()
        b, mod = _bridge(tmp_path, mt5)
        mt5.symbol_info.return_value = MagicMock(visible=True)
        mt5.symbol_info_tick.return_value = MagicMock(ask=1920.0, bid=1919.5)
        mt5.order_send.return_value = MagicMock(retcode=10009, order=1, volume=0.1, price=1920.0, comment="OK")
        order = MT5Order(symbol="XAUUSD", side=OrderSide.BUY, volume=0.1, stop_loss=1880.0)
        with patch.object(mod, "_MT5_AVAILABLE", True), patch.object(mod, "mt5", mt5):
            fill = b._send_direct(order)
        assert fill.ticket == 1

    def test_market_sell(self, tmp_path):
        mt5 = _mt5_mock()
        b, mod = _bridge(tmp_path, mt5)
        mt5.symbol_info.return_value = MagicMock(visible=True)
        mt5.symbol_info_tick.return_value = MagicMock(ask=1920.0, bid=1919.5)
        mt5.order_send.return_value = MagicMock(retcode=10009, order=2, volume=0.1, price=1919.5, comment="OK")
        order = MT5Order(symbol="XAUUSD", side=OrderSide.SELL, volume=0.1, stop_loss=1960.0)
        with patch.object(mod, "_MT5_AVAILABLE", True), patch.object(mod, "mt5", mt5):
            fill = b._send_direct(order)
        assert fill.ticket == 2

    def test_limit_buy(self, tmp_path):
        mt5 = _mt5_mock()
        b, mod = _bridge(tmp_path, mt5)
        mt5.symbol_info.return_value = MagicMock(visible=True)
        mt5.order_send.return_value = MagicMock(retcode=10009, order=3, volume=0.1, price=1900.0, comment="OK")
        order = MT5Order(
            symbol="XAUUSD", side=OrderSide.BUY, volume=0.1, order_type=OrderType.LIMIT, price=1900.0, stop_loss=1880.0
        )
        with patch.object(mod, "_MT5_AVAILABLE", True), patch.object(mod, "mt5", mt5):
            fill = b._send_direct(order)
        assert fill.ticket == 3

    def test_limit_no_price_raises(self, tmp_path):
        mt5 = _mt5_mock()
        b, mod = _bridge(tmp_path, mt5)
        mt5.symbol_info.return_value = MagicMock(visible=True)
        mt5.symbol_info_tick.return_value = MagicMock(ask=1920.0, bid=1919.5)
        order = MT5Order(
            symbol="XAUUSD", side=OrderSide.BUY, volume=0.1, order_type=OrderType.LIMIT, price=None, stop_loss=1880.0
        )
        with patch.object(mod, "_MT5_AVAILABLE", True), patch.object(mod, "mt5", mt5):
            with pytest.raises(ValueError, match="LIMIT"):
                b._send_direct(order)

    def test_stop_sell(self, tmp_path):
        mt5 = _mt5_mock()
        b, mod = _bridge(tmp_path, mt5)
        mt5.symbol_info.return_value = MagicMock(visible=True)
        mt5.order_send.return_value = MagicMock(retcode=10009, order=4, volume=0.1, price=1880.0, comment="OK")
        order = MT5Order(
            symbol="XAUUSD", side=OrderSide.SELL, volume=0.1, order_type=OrderType.STOP, price=1880.0, stop_loss=1900.0
        )
        with patch.object(mod, "_MT5_AVAILABLE", True), patch.object(mod, "mt5", mt5):
            fill = b._send_direct(order)
        assert fill.ticket == 4

    def test_stop_no_price_raises(self, tmp_path):
        mt5 = _mt5_mock()
        b, mod = _bridge(tmp_path, mt5)
        mt5.symbol_info.return_value = MagicMock(visible=True)
        order = MT5Order(
            symbol="XAUUSD", side=OrderSide.BUY, volume=0.1, order_type=OrderType.STOP, price=None, stop_loss=1880.0
        )
        with patch.object(mod, "_MT5_AVAILABLE", True), patch.object(mod, "mt5", mt5):
            with pytest.raises(ValueError, match="STOP"):
                b._send_direct(order)

    def test_symbol_not_found(self, tmp_path):
        mt5 = _mt5_mock()
        b, mod = _bridge(tmp_path, mt5)
        mt5.symbol_info.return_value = None
        order = MT5Order(symbol="INVALID", side=OrderSide.BUY, volume=0.1, stop_loss=1880.0)
        with patch.object(mod, "_MT5_AVAILABLE", True), patch.object(mod, "mt5", mt5):
            with pytest.raises(ValueError, match="not found"):
                b._send_direct(order)

    def test_symbol_select_fails(self, tmp_path):
        mt5 = _mt5_mock()
        b, mod = _bridge(tmp_path, mt5)
        mt5.symbol_info.return_value = MagicMock(visible=False)
        mt5.symbol_select.return_value = False
        order = MT5Order(symbol="XAUUSD", side=OrderSide.BUY, volume=0.1, stop_loss=1880.0)
        with patch.object(mod, "_MT5_AVAILABLE", True), patch.object(mod, "mt5", mt5):
            with pytest.raises(RuntimeError, match="Cannot select"):
                b._send_direct(order)

    def test_no_tick(self, tmp_path):
        mt5 = _mt5_mock()
        b, mod = _bridge(tmp_path, mt5)
        mt5.symbol_info.return_value = MagicMock(visible=True)
        mt5.symbol_info_tick.return_value = None
        order = MT5Order(symbol="XAUUSD", side=OrderSide.BUY, volume=0.1, stop_loss=1880.0)
        with patch.object(mod, "_MT5_AVAILABLE", True), patch.object(mod, "mt5", mt5):
            with pytest.raises(RuntimeError, match="No tick"):
                b._send_direct(order)

    def test_order_rejected(self, tmp_path):
        mt5 = _mt5_mock()
        b, mod = _bridge(tmp_path, mt5)
        mt5.symbol_info.return_value = MagicMock(visible=True)
        mt5.symbol_info_tick.return_value = MagicMock(ask=1920.0, bid=1919.5)
        mt5.order_send.return_value = MagicMock(retcode=10006, comment="Rejected")
        order = MT5Order(symbol="XAUUSD", side=OrderSide.BUY, volume=0.1, stop_loss=1880.0)
        with patch.object(mod, "_MT5_AVAILABLE", True), patch.object(mod, "mt5", mt5):
            with pytest.raises(RuntimeError, match="rejected"):
                b._send_direct(order)

    def test_order_send_none(self, tmp_path):
        mt5 = _mt5_mock()
        b, mod = _bridge(tmp_path, mt5)
        mt5.symbol_info.return_value = MagicMock(visible=True)
        mt5.symbol_info_tick.return_value = MagicMock(ask=1920.0, bid=1919.5)
        mt5.order_send.return_value = None
        order = MT5Order(symbol="XAUUSD", side=OrderSide.BUY, volume=0.1, stop_loss=1880.0)
        with patch.object(mod, "_MT5_AVAILABLE", True), patch.object(mod, "mt5", mt5):
            with pytest.raises(RuntimeError):
                b._send_direct(order)

    def test_with_take_profit(self, tmp_path):
        mt5 = _mt5_mock()
        b, mod = _bridge(tmp_path, mt5)
        mt5.symbol_info.return_value = MagicMock(visible=True)
        mt5.symbol_info_tick.return_value = MagicMock(ask=1920.0, bid=1919.5)
        mt5.order_send.return_value = MagicMock(retcode=10009, order=5, volume=0.1, price=1920.0, comment="OK")
        order = MT5Order(symbol="XAUUSD", side=OrderSide.BUY, volume=0.1, stop_loss=1880.0, take_profit=1960.0)
        with patch.object(mod, "_MT5_AVAILABLE", True), patch.object(mod, "mt5", mt5):
            fill = b._send_direct(order)
        assert fill.ticket == 5
        req = mt5.order_send.call_args[0][0]
        assert "tp" in req


class TestClosePositionDirect:
    def test_no_positions(self, tmp_path):
        mt5 = _mt5_mock()
        b, mod = _bridge(tmp_path, mt5)
        mt5.positions_get.return_value = []
        with patch.object(mod, "_MT5_AVAILABLE", True), patch.object(mod, "mt5", mt5):
            result = b.close_position("XAUUSD")
        assert result == []

    def test_success_buy(self, tmp_path):
        mt5 = _mt5_mock()
        b, mod = _bridge(tmp_path, mt5)
        pos = MagicMock(type=0, volume=0.1, ticket=1001)
        mt5.positions_get.return_value = [pos]
        mt5.symbol_info_tick.return_value = MagicMock(bid=1919.5, ask=1920.0)
        mt5.order_send.return_value = MagicMock(retcode=10009, order=2001, volume=0.1, price=1919.5, comment="OK")
        with patch.object(mod, "_MT5_AVAILABLE", True), patch.object(mod, "mt5", mt5):
            results = b.close_position("XAUUSD")
        assert len(results) == 1
        assert results[0].ticket == 2001

    def test_success_sell(self, tmp_path):
        mt5 = _mt5_mock()
        b, mod = _bridge(tmp_path, mt5)
        pos = MagicMock(type=1, volume=0.1, ticket=1002)
        mt5.positions_get.return_value = [pos]
        mt5.symbol_info_tick.return_value = MagicMock(bid=1919.5, ask=1920.0)
        mt5.order_send.return_value = MagicMock(retcode=10009, order=2002, volume=0.1, price=1920.0, comment="OK")
        with patch.object(mod, "_MT5_AVAILABLE", True), patch.object(mod, "mt5", mt5):
            results = b.close_position("XAUUSD")
        assert len(results) == 1

    def test_no_tick_skips(self, tmp_path):
        mt5 = _mt5_mock()
        b, mod = _bridge(tmp_path, mt5)
        pos = MagicMock(type=0, volume=0.1, ticket=1001)
        mt5.positions_get.return_value = [pos]
        mt5.symbol_info_tick.return_value = None
        with patch.object(mod, "_MT5_AVAILABLE", True), patch.object(mod, "mt5", mt5):
            results = b.close_position("XAUUSD")
        assert results == []

    def test_order_fails_skips(self, tmp_path):
        mt5 = _mt5_mock()
        b, mod = _bridge(tmp_path, mt5)
        pos = MagicMock(type=0, volume=0.1, ticket=1001)
        mt5.positions_get.return_value = [pos]
        mt5.symbol_info_tick.return_value = MagicMock(bid=1919.5, ask=1920.0)
        mt5.order_send.return_value = MagicMock(retcode=10006, comment="Rejected")
        with patch.object(mod, "_MT5_AVAILABLE", True), patch.object(mod, "mt5", mt5):
            results = b.close_position("XAUUSD")
        assert results == []

    def test_partial_close(self, tmp_path):
        mt5 = _mt5_mock()
        b, mod = _bridge(tmp_path, mt5)
        pos = MagicMock(type=0, volume=0.2, ticket=1001)
        mt5.positions_get.return_value = [pos]
        mt5.symbol_info_tick.return_value = MagicMock(bid=1919.5, ask=1920.0)
        mt5.order_send.return_value = MagicMock(retcode=10009, order=2003, volume=0.1, price=1919.5, comment="OK")
        with patch.object(mod, "_MT5_AVAILABLE", True), patch.object(mod, "mt5", mt5):
            results = b.close_position("XAUUSD", volume=0.1)
        assert len(results) == 1


class TestGetAccountDirect:
    def test_success(self, tmp_path):
        mt5 = _mt5_mock()
        b, mod = _bridge(tmp_path, mt5)
        info = MagicMock(
            login=12345678,
            server="Demo",
            balance=10000.0,
            equity=10100.0,
            margin=500.0,
            margin_free=9600.0,
            margin_level=2020.0,
            leverage=100,
            currency="USD",
        )
        mt5.account_info.return_value = info
        with patch.object(mod, "_MT5_AVAILABLE", True), patch.object(mod, "mt5", mt5):
            result = b.get_account()
        assert result["balance"] == 10000.0
        assert result["currency"] == "USD"

    def test_none_raises(self, tmp_path):
        mt5 = _mt5_mock()
        b, mod = _bridge(tmp_path, mt5)
        mt5.account_info.return_value = None
        mt5.last_error.return_value = (1, "err")
        with patch.object(mod, "_MT5_AVAILABLE", True), patch.object(mod, "mt5", mt5):
            with pytest.raises(RuntimeError):
                b.get_account()


class TestGetPositionDirect:
    def test_long(self, tmp_path):
        mt5 = _mt5_mock()
        b, mod = _bridge(tmp_path, mt5)
        pos = MagicMock(type=0, volume=0.1, price_open=1900.0, profit=100.0, ticket=1001)
        mt5.positions_get.return_value = [pos]
        with patch.object(mod, "_MT5_AVAILABLE", True), patch.object(mod, "mt5", mt5):
            result = b.get_position("XAUUSD")
        assert result["side"] == "LONG"

    def test_short(self, tmp_path):
        mt5 = _mt5_mock()
        b, mod = _bridge(tmp_path, mt5)
        pos = MagicMock(type=1, volume=0.05, price_open=1920.0, profit=-50.0, ticket=1002)
        mt5.positions_get.return_value = [pos]
        with patch.object(mod, "_MT5_AVAILABLE", True), patch.object(mod, "mt5", mt5):
            result = b.get_position("XAUUSD")
        assert result["side"] == "SHORT"

    def test_empty(self, tmp_path):
        mt5 = _mt5_mock()
        b, mod = _bridge(tmp_path, mt5)
        mt5.positions_get.return_value = []
        with patch.object(mod, "_MT5_AVAILABLE", True), patch.object(mod, "mt5", mt5):
            result = b.get_position("XAUUSD")
        assert result == {}


class TestModifyOrderDirect:
    def test_success(self, tmp_path):
        mt5 = _mt5_mock()
        b, mod = _bridge(tmp_path, mt5)
        mt5.order_send.return_value = MagicMock(retcode=10009)
        with patch.object(mod, "_MT5_AVAILABLE", True), patch.object(mod, "mt5", mt5):
            result = b.modify_order(1001, "XAUUSD", stop_loss=1880.0, take_profit=1960.0)
        assert result is True

    def test_only_sl(self, tmp_path):
        mt5 = _mt5_mock()
        b, mod = _bridge(tmp_path, mt5)
        mt5.order_send.return_value = MagicMock(retcode=10009)
        with patch.object(mod, "_MT5_AVAILABLE", True), patch.object(mod, "mt5", mt5):
            result = b.modify_order(1001, "XAUUSD", stop_loss=1880.0)
        assert result is True

    def test_fails(self, tmp_path):
        mt5 = _mt5_mock()
        b, mod = _bridge(tmp_path, mt5)
        mt5.order_send.return_value = MagicMock(retcode=10006)
        with patch.object(mod, "_MT5_AVAILABLE", True), patch.object(mod, "mt5", mt5):
            with pytest.raises(RuntimeError, match="modify_order failed"):
                b.modify_order(1001, "XAUUSD", stop_loss=1880.0)

    def test_send_none(self, tmp_path):
        mt5 = _mt5_mock()
        b, mod = _bridge(tmp_path, mt5)
        mt5.order_send.return_value = None
        with patch.object(mod, "_MT5_AVAILABLE", True), patch.object(mod, "mt5", mt5):
            with pytest.raises(RuntimeError):
                b.modify_order(1001, "XAUUSD")


class TestCancelOrderDirect:
    def test_success(self, tmp_path):
        mt5 = _mt5_mock()
        b, mod = _bridge(tmp_path, mt5)
        mt5.order_send.return_value = MagicMock(retcode=10009)
        with patch.object(mod, "_MT5_AVAILABLE", True), patch.object(mod, "mt5", mt5):
            result = b.cancel_order(1001, "XAUUSD")
        assert result is True

    def test_fails(self, tmp_path):
        mt5 = _mt5_mock()
        b, mod = _bridge(tmp_path, mt5)
        mt5.order_send.return_value = MagicMock(retcode=10006)
        with patch.object(mod, "_MT5_AVAILABLE", True), patch.object(mod, "mt5", mt5):
            with pytest.raises(RuntimeError, match="cancel_order failed"):
                b.cancel_order(1001)

    def test_send_none(self, tmp_path):
        mt5 = _mt5_mock()
        b, mod = _bridge(tmp_path, mt5)
        mt5.order_send.return_value = None
        with patch.object(mod, "_MT5_AVAILABLE", True), patch.object(mod, "mt5", mt5):
            with pytest.raises(RuntimeError):
                b.cancel_order(1001)


class TestMonitorFillDirect:
    def test_timeout(self, tmp_path):
        mt5 = _mt5_mock()
        b, mod = _bridge(tmp_path, mt5)
        mt5.orders_get.return_value = []
        mt5.history_deals_get.return_value = []
        with patch.object(mod, "_MT5_AVAILABLE", True), patch.object(mod, "mt5", mt5):
            with pytest.raises(TimeoutError):
                b.monitor_fill(1001, poll_interval=0.01, timeout_sec=0.05)

    def test_found_in_history(self, tmp_path):
        mt5 = _mt5_mock()
        b, mod = _bridge(tmp_path, mt5)
        mt5.orders_get.return_value = []
        deal = MagicMock(order=1001, volume=0.1, price=1920.0, commission=-2.5, swap=0.0, profit=50.0, comment="OK")
        mt5.history_deals_get.return_value = [deal]
        with patch.object(mod, "_MT5_AVAILABLE", True), patch.object(mod, "mt5", mt5):
            result = b.monitor_fill(1001, poll_interval=0.01, timeout_sec=2.0)
        assert result.ticket == 1001
        assert result.status == FillStatus.FILLED

    def test_pending_then_filled(self, tmp_path):
        mt5 = _mt5_mock()
        b, mod = _bridge(tmp_path, mt5)
        calls = [0]
        deal = MagicMock(order=1001, volume=0.1, price=1920.0, commission=0.0, swap=0.0, profit=0.0, comment="")

        def orders_side(**kw):
            calls[0] += 1
            return [MagicMock()] if calls[0] <= 1 else []

        mt5.orders_get.side_effect = orders_side
        mt5.history_deals_get.return_value = [deal]
        with patch.object(mod, "_MT5_AVAILABLE", True), patch.object(mod, "mt5", mt5), patch("time.sleep"):
            result = b.monitor_fill(1001, poll_interval=0.01, timeout_sec=2.0)
        assert result.ticket == 1001

    def test_deal_not_matching_ticket(self, tmp_path):
        mt5 = _mt5_mock()
        b, mod = _bridge(tmp_path, mt5)
        mt5.orders_get.return_value = []
        deal = MagicMock(order=9999)  # different ticket
        mt5.history_deals_get.return_value = [deal]
        with patch.object(mod, "_MT5_AVAILABLE", True), patch.object(mod, "mt5", mt5):
            with pytest.raises(TimeoutError):
                b.monitor_fill(1001, poll_interval=0.01, timeout_sec=0.05)


class TestConnectDirectMode:
    def test_connect_success(self, tmp_path):
        mt5 = _mt5_mock()
        b, mod = _bridge(tmp_path, mt5)
        b._connected = False
        mt5.initialize.return_value = True
        mt5.login.return_value = True
        mt5.account_info.return_value = MagicMock(balance=10000.0, currency="USD")
        with patch.object(mod, "_MT5_AVAILABLE", True), patch.object(mod, "mt5", mt5):
            result = b.connect()
        assert result is True

    def test_connect_with_path(self, tmp_path):
        mt5 = _mt5_mock()
        b, mod = _bridge(tmp_path, mt5)
        b._connected = False
        b.path = "/path/to/terminal"
        mt5.initialize.return_value = True
        mt5.login.return_value = True
        mt5.account_info.return_value = MagicMock(balance=0.0, currency="USD")
        with patch.object(mod, "_MT5_AVAILABLE", True), patch.object(mod, "mt5", mt5):
            result = b.connect()
        assert result is True
        assert "path" in mt5.initialize.call_args[1]

    def test_connect_init_fails(self, tmp_path):
        mt5 = _mt5_mock()
        b, mod = _bridge(tmp_path, mt5)
        b._connected = False
        mt5.initialize.return_value = False
        mt5.last_error.return_value = (1, "err")
        with patch.object(mod, "_MT5_AVAILABLE", True), patch.object(mod, "mt5", mt5):
            with pytest.raises(ConnectionError):
                b.connect()

    def test_connect_login_fails(self, tmp_path):
        mt5 = _mt5_mock()
        b, mod = _bridge(tmp_path, mt5)
        b._connected = False
        mt5.initialize.return_value = True
        mt5.login.return_value = False
        mt5.last_error.return_value = (2, "login err")
        with patch.object(mod, "_MT5_AVAILABLE", True), patch.object(mod, "mt5", mt5):
            with pytest.raises(ConnectionError):
                b.connect()

    def test_disconnect(self, tmp_path):
        mt5 = _mt5_mock()
        b, mod = _bridge(tmp_path, mt5)
        with patch.object(mod, "_MT5_AVAILABLE", True), patch.object(mod, "mt5", mt5):
            b.disconnect()
        assert b._connected is False
        mt5.shutdown.assert_called_once()

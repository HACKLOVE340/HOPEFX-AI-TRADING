# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
tests/test_ibkr_broker.py

Unit tests for IBKR broker integration — IBKRConfig, IBKRConnector,
IBKRFIXBridge, BrokerManager.

All IBKR network calls are mocked — no live TWS/Gateway required.
ib_insync is not installed in CI; tests patch the module-level IB_AVAILABLE
flag and inject a mock IB class directly into the module namespace.
"""

from unittest.mock import MagicMock, patch

import pytest

import brokers.ibkr_connector as _ibkr_mod
from brokers.base import AccountInfo, Order, OrderSide, OrderType
from brokers.ibkr_connector import IBKRConfig, IBKRConnector

# ---------------------------------------------------------------------------
# IBKRConfig
# ---------------------------------------------------------------------------


class TestIBKRConfig:
    def test_valid_paper_port(self):
        cfg = IBKRConfig(host="127.0.0.1", port=7497, client_id=1)
        assert cfg.is_paper is True
        assert cfg.mode_label == "PAPER"

    def test_valid_live_port(self):
        cfg = IBKRConfig(host="127.0.0.1", port=7496, client_id=1)
        assert cfg.is_paper is False
        assert cfg.mode_label == "LIVE"

    def test_valid_gateway_paper_port(self):
        cfg = IBKRConfig(host="127.0.0.1", port=4002, client_id=1)
        assert cfg.is_paper is True

    def test_valid_gateway_live_port(self):
        cfg = IBKRConfig(host="127.0.0.1", port=4001, client_id=1)
        assert cfg.is_paper is False

    def test_invalid_port_raises(self):
        with pytest.raises(ValueError, match="not a recognised"):
            IBKRConfig(host="127.0.0.1", port=9999, client_id=1)

    def test_invalid_port_8080_raises(self):
        with pytest.raises(ValueError):
            IBKRConfig(port=8080)


# ---------------------------------------------------------------------------
# IBKRConnector — mocked IB
# ---------------------------------------------------------------------------


def _make_mock_ib():
    """Build a mock ib_insync.IB instance."""
    ib = MagicMock()
    ib.isConnected.return_value = True
    ib.managedAccounts.return_value = ["DU123456"]
    ib.accountValues.return_value = [
        MagicMock(tag="TotalCashValue", value="100000.0", currency="USD"),
        MagicMock(tag="NetLiquidation", value="105000.0", currency="USD"),
        MagicMock(tag="MaintMarginReq", value="5000.0", currency="USD"),
        MagicMock(tag="AvailableFunds", value="95000.0", currency="USD"),
    ]
    ib.positions.return_value = []
    ib.trades.return_value = []
    return ib


import contextlib
from contextlib import contextmanager

_MISSING = object()  # sentinel


@contextmanager
def _patch_ib(mock_ib_instance):
    """
    Inject mock ib_insync symbols into the connector module namespace.
    Works regardless of whether ib_insync is installed in the test env.
    Also patches _start_heartbeat to a no-op so tests don't hang on
    the 30-second heartbeat sleep.
    """
    MockIBClass = MagicMock(return_value=mock_ib_instance)
    _attrs = {
        "IB_AVAILABLE": True,
        "IB": MockIBClass,
        "MarketOrder": MagicMock(return_value=MagicMock()),
        "LimitOrder": MagicMock(return_value=MagicMock()),
        "StopOrder": MagicMock(return_value=MagicMock()),
        "Commodity": MagicMock(return_value=MagicMock()),
        "CFD": MagicMock(return_value=MagicMock()),
        "Future": MagicMock(return_value=MagicMock()),
    }
    _originals = {k: getattr(_ibkr_mod, k, _MISSING) for k in _attrs}
    try:
        for k, v in _attrs.items():
            setattr(_ibkr_mod, k, v)
        # Suppress heartbeat thread so tests don't block
        with patch.object(IBKRConnector, "_start_heartbeat", return_value=None):
            yield MockIBClass
    finally:
        for k, orig in _originals.items():
            if orig is _MISSING:
                with contextlib.suppress(AttributeError):
                    delattr(_ibkr_mod, k)
            else:
                setattr(_ibkr_mod, k, orig)


class TestIBKRConnectorConnect:
    def test_connect_success(self):
        mock_ib = _make_mock_ib()
        with _patch_ib(mock_ib):
            cfg = IBKRConfig(host="127.0.0.1", port=7497, client_id=1)
            connector = IBKRConnector(config=cfg)
            result = connector.connect()

        assert result is True
        assert connector.connected is True
        assert connector._account_id == "DU123456"

    def test_connect_failure_returns_false(self):
        mock_ib = MagicMock()
        mock_ib.connect.side_effect = ConnectionRefusedError("TWS not running")
        with _patch_ib(mock_ib), patch("brokers.ibkr_connector.time.sleep", return_value=None):
            # Suppress retry sleep so test completes instantly
            cfg = IBKRConfig(host="127.0.0.1", port=7497, client_id=1)
            connector = IBKRConnector(config=cfg)
            result = connector.connect()

        assert result is False
        assert connector.connected is False

    def test_connect_without_ib_insync_raises_import_error(self):
        with patch.object(_ibkr_mod, "IB_AVAILABLE", False):
            cfg = IBKRConfig(host="127.0.0.1", port=7497, client_id=1)
            with pytest.raises(ImportError):
                IBKRConnector(config=cfg)


class TestIBKRConnectorAccountInfo:
    def test_get_account_info(self):
        mock_ib = _make_mock_ib()
        with _patch_ib(mock_ib):
            cfg = IBKRConfig(host="127.0.0.1", port=7497, client_id=1)
            connector = IBKRConnector(config=cfg)
            connector.connect()
            info = connector.get_account_info()

        assert isinstance(info, AccountInfo)
        assert info.balance == pytest.approx(100_000.0)
        assert info.equity == pytest.approx(105_000.0)
        assert info.margin_used == pytest.approx(5_000.0)
        assert info.margin_available == pytest.approx(95_000.0)

    def test_get_account_info_not_connected_raises(self):
        with patch.object(_ibkr_mod, "IB_AVAILABLE", True):
            cfg = IBKRConfig(host="127.0.0.1", port=7497, client_id=1)
            connector = IBKRConnector(config=cfg)
            connector.connected = False
            with pytest.raises(RuntimeError, match="not connected"):
                connector.get_account_info()


class TestIBKRConnectorPlaceOrder:
    def test_place_market_order(self):
        mock_ib = _make_mock_ib()
        mock_trade = MagicMock()
        mock_trade.order.orderId = 101
        mock_trade.orderStatus.status = "Submitted"
        mock_trade.orderStatus.avgFillPrice = 0.0
        mock_trade.orderStatus.filled = 0.0
        mock_ib.placeOrder.return_value = mock_trade
        mock_ib.qualifyContracts.return_value = None

        with _patch_ib(mock_ib):
            cfg = IBKRConfig(host="127.0.0.1", port=7497, client_id=1)
            connector = IBKRConnector(config=cfg)
            connector.connect()
            order = connector.place_order(
                symbol="XAUUSD",
                side=OrderSide.BUY,
                order_type=OrderType.MARKET,
                quantity=1.0,
            )

        assert isinstance(order, Order)
        assert order.id == "101"
        assert order.symbol == "XAUUSD"
        assert order.side == OrderSide.BUY

    def test_limit_order_requires_price(self):
        mock_ib = _make_mock_ib()
        with _patch_ib(mock_ib):
            cfg = IBKRConfig(host="127.0.0.1", port=7497, client_id=1)
            connector = IBKRConnector(config=cfg)
            connector.connect()
            with pytest.raises(ValueError, match="price is required"):
                connector.place_order(
                    symbol="XAUUSD",
                    side=OrderSide.BUY,
                    order_type=OrderType.LIMIT,
                    quantity=1.0,
                    price=None,
                )

    def test_kill_switch_blocks_order(self):
        mock_ib = _make_mock_ib()
        ks = MagicMock()
        ks.is_active.return_value = True
        ks._reason = "emergency halt"

        with _patch_ib(mock_ib):
            cfg = IBKRConfig(host="127.0.0.1", port=7497, client_id=1)
            connector = IBKRConnector(config=cfg, kill_switch=ks)
            connector.connect()
            with pytest.raises(RuntimeError, match="kill switch"):
                connector.place_order(
                    symbol="XAUUSD",
                    side=OrderSide.BUY,
                    order_type=OrderType.MARKET,
                    quantity=1.0,
                )


class TestIBKRConnectorPositions:
    def test_get_positions_empty(self):
        mock_ib = _make_mock_ib()
        mock_ib.positions.return_value = []
        with _patch_ib(mock_ib):
            cfg = IBKRConfig(host="127.0.0.1", port=7497, client_id=1)
            connector = IBKRConnector(config=cfg)
            connector.connect()
            positions = connector.get_positions()
        assert positions == []

    def test_get_positions_not_connected_returns_empty(self):
        with patch.object(_ibkr_mod, "IB_AVAILABLE", True):
            cfg = IBKRConfig(host="127.0.0.1", port=7497, client_id=1)
            connector = IBKRConnector(config=cfg)
            connector.connected = False
            assert connector.get_positions() == []


# ---------------------------------------------------------------------------
# BrokerManager
# ---------------------------------------------------------------------------


class TestBrokerManager:
    def test_register_and_get_active(self):
        from brokers.manager import BrokerManager

        mgr = BrokerManager(primary_broker_name="paper")

        mock_broker = MagicMock()
        mock_broker.is_connected.return_value = True
        mgr.register("paper", mock_broker)
        mgr.set_active("paper")

        assert mgr.get_active_broker_name() == "paper"
        assert mgr.is_connected() is True

    def test_set_active_unknown_raises(self):
        from brokers.manager import BrokerManager

        mgr = BrokerManager()
        with pytest.raises(ValueError, match="not registered"):
            mgr.set_active("nonexistent")

    def test_kill_switch_blocks_place_order(self):
        from brokers.manager import BrokerManager

        ks = MagicMock()
        ks.is_active.return_value = True
        ks._reason = "halt"

        mgr = BrokerManager(kill_switch=ks)
        mock_broker = MagicMock()
        mock_broker.is_connected.return_value = True
        mgr.register("paper", mock_broker)
        mgr.set_active("paper")

        with pytest.raises(RuntimeError, match="kill switch"):
            mgr.place_order(
                symbol="XAUUSD",
                side=OrderSide.BUY,
                order_type=OrderType.MARKET,
                quantity=1.0,
            )

    def test_auto_failover_to_paper_after_failures(self):
        from brokers.manager import _MAX_CONSECUTIVE_FAILURES, BrokerManager

        mgr = BrokerManager(primary_broker_name="ibkr")

        mock_ibkr = MagicMock()
        mock_ibkr.is_connected.return_value = True
        mock_ibkr.place_order.side_effect = RuntimeError("IBKR down")

        mock_paper = MagicMock()
        mock_paper.is_connected.return_value = True
        mock_paper.place_order.return_value = MagicMock(spec=Order)

        mgr.register("ibkr", mock_ibkr)
        mgr.register("paper", mock_paper)
        mgr.set_active("ibkr")

        # Trigger failures up to threshold
        for _ in range(_MAX_CONSECUTIVE_FAILURES):
            with contextlib.suppress(RuntimeError):
                mgr.place_order("XAUUSD", OrderSide.BUY, OrderType.MARKET, 1.0)

        # After threshold, should have failed over to paper
        assert mgr.get_active_broker_name() == "paper"

    def test_heartbeat_returns_health_per_broker(self):
        from brokers.manager import BrokerManager

        mgr = BrokerManager()

        mock_broker = MagicMock()
        mock_broker.is_connected.return_value = True
        mgr.register("paper", mock_broker)
        mgr.set_active("paper")

        health = mgr.heartbeat()
        assert "paper" in health
        assert health["paper"].connected is True
        assert health["paper"].is_primary is True

    def test_connect_all_calls_each_broker(self):
        from brokers.manager import BrokerManager

        mgr = BrokerManager()

        b1 = MagicMock()
        b1.connect.return_value = True
        b1.is_connected.return_value = True
        b2 = MagicMock()
        b2.connect.return_value = True
        b2.is_connected.return_value = True

        mgr.register("b1", b1)
        mgr.register("b2", b2)
        results = mgr.connect_all()

        assert results["b1"] is True
        assert results["b2"] is True
        b1.connect.assert_called_once()
        b2.connect.assert_called_once()

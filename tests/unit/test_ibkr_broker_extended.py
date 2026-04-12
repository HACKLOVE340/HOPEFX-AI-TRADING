# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# AGPL-3.0 — Share all modifications
"""
Extended unit tests for brokers/ibkr.py covering gaps not reached by
tests/test_ibkr_broker.py: reconnect, cancel_order, ping, callbacks,
forbidden market-data methods, metrics, and aliases.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from brokers.ibkr import (
    IBKRBroker,
    IBKRConnector,
    InteractiveBrokers,
    MarketDataForbiddenError,
)


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_broker(connected: bool = True) -> IBKRBroker:
    broker = IBKRBroker(config={"server": "paper"})
    broker.connected = connected
    broker._ib = MagicMock()
    return broker


def _make_trade(status: str = "Filled", avg_price: float = 1800.0, filled: float = 1.0) -> MagicMock:
    trade = MagicMock()
    trade.orderStatus.status = status
    trade.orderStatus.avgFillPrice = avg_price
    trade.orderStatus.filled = filled
    trade.order.action = "BUY"
    trade.order.orderId = 42
    return trade


# ── MarketDataForbiddenError ──────────────────────────────────────────────────


class TestMarketDataForbiddenError:
    def test_message_contains_method_name(self):
        err = MarketDataForbiddenError("get_market_data")
        assert "get_market_data" in str(err)
        assert "ARCHITECTURAL VIOLATION" in str(err)


# ── IBKRConfig ────────────────────────────────────────────────────────────────


class TestIBKRConfigDefaults:
    def test_paper_mode_uses_paper_port(self):
        broker = IBKRBroker(config={"server": "paper"})
        assert broker._cfg.paper is True
        assert broker._cfg.port == 7497

    def test_live_mode_uses_live_port(self):
        broker = IBKRBroker(config={"server": "live"})
        assert broker._cfg.paper is False
        assert broker._cfg.port == 7496

    def test_custom_host_and_client_id(self):
        broker = IBKRBroker(config={"host": "192.168.1.1", "client_id": 5})
        assert broker._cfg.host == "192.168.1.1"
        assert broker._cfg.client_id == 5

    def test_default_config_when_none(self):
        broker = IBKRBroker()
        assert broker._cfg is not None


# ── connect ───────────────────────────────────────────────────────────────────


class TestConnect:
    @pytest.mark.asyncio
    async def test_returns_false_when_ib_insync_unavailable(self):
        broker = IBKRBroker()
        with patch("brokers.ibkr._IB_AVAILABLE", False):
            result = await broker.connect()
        assert result is False

    @pytest.mark.asyncio
    async def test_returns_true_when_already_connected(self):
        broker = _make_broker(connected=True)
        result = await broker.connect()
        assert result is True

    @pytest.mark.asyncio
    async def test_returns_false_on_timeout(self):
        broker = IBKRBroker()
        broker.connected = False

        mock_ib = MagicMock()
        mock_ib.connectAsync = MagicMock(return_value=asyncio.sleep(999))

        with (
            patch("brokers.ibkr._IB_AVAILABLE", True),
            patch("brokers.ibkr.IB", return_value=mock_ib),
            patch("brokers.ibkr._CONNECT_TIMEOUT", 0.01),
        ):
            result = await broker.connect()
        assert result is False

    @pytest.mark.asyncio
    async def test_returns_false_on_exception(self):
        broker = IBKRBroker()
        broker.connected = False

        mock_ib = MagicMock()
        mock_ib.connectAsync = MagicMock(side_effect=RuntimeError("refused"))

        with patch("brokers.ibkr._IB_AVAILABLE", True), patch("brokers.ibkr.IB", return_value=mock_ib):
            result = await broker.connect()
        assert result is False


# ── disconnect ────────────────────────────────────────────────────────────────


class TestDisconnect:
    @pytest.mark.asyncio
    async def test_disconnect_calls_ib_disconnect(self):
        broker = _make_broker(connected=True)
        await broker.disconnect()
        broker._ib.disconnect.assert_called_once()
        assert broker.connected is False

    @pytest.mark.asyncio
    async def test_disconnect_when_not_connected_is_safe(self):
        broker = _make_broker(connected=False)
        broker._ib = None
        await broker.disconnect()  # must not raise
        assert broker.connected is False


# ── reconnect ─────────────────────────────────────────────────────────────────


class TestReconnect:
    @pytest.mark.asyncio
    async def test_reconnect_succeeds_on_first_attempt(self):
        broker = IBKRBroker()
        with (
            patch.object(broker, "connect", new_callable=AsyncMock, return_value=True),
            patch("brokers.ibkr._RECONNECT_DELAY", 0.0),
        ):
            result = await broker.reconnect()
        assert result is True

    @pytest.mark.asyncio
    async def test_reconnect_exhausts_attempts_and_returns_false(self):
        broker = IBKRBroker()
        with (
            patch.object(broker, "connect", new_callable=AsyncMock, return_value=False),
            patch("brokers.ibkr._RECONNECT_DELAY", 0.0),
            patch("brokers.ibkr._MAX_RECONNECTS", 2),
        ):
            result = await broker.reconnect()
        assert result is False


# ── get_account_info ──────────────────────────────────────────────────────────


class TestGetAccountInfo:
    @pytest.mark.asyncio
    async def test_returns_none_when_not_connected(self):
        broker = _make_broker(connected=False)
        result = await broker.get_account_info()
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_account_info_when_connected(self):
        broker = _make_broker(connected=True)
        broker._ib.accountValues.return_value = [
            MagicMock(tag="CashBalance", value="50000"),
            MagicMock(tag="NetLiquidation", value="55000"),
            MagicMock(tag="UnrealizedPnL", value="500"),
            MagicMock(tag="BuyingPower", value="100000"),
            MagicMock(tag="MaintMarginReq", value="1000"),
            MagicMock(tag="Currency", value="USD"),
        ]
        broker._ib.managedAccounts.return_value = ["DU123456"]

        from brokers.ibkr import AccountInfo

        result = await broker.get_account_info()
        assert isinstance(result, AccountInfo)
        assert result.balance == 50000.0
        assert result.account_id == "DU123456"

    @pytest.mark.asyncio
    async def test_returns_none_on_exception(self):
        broker = _make_broker(connected=True)
        broker._ib.accountValues.side_effect = RuntimeError("IB error")
        result = await broker.get_account_info()
        assert result is None


# ── place_order ───────────────────────────────────────────────────────────────


class TestPlaceOrder:
    @pytest.mark.asyncio
    async def test_rejected_when_not_connected(self):
        broker = _make_broker(connected=False)
        result = await broker.place_order({"symbol": "XAUUSD", "direction": "long", "quantity": 1.0})
        assert result["status"] == "rejected"
        assert result["reason"] == "not_connected"

    @pytest.mark.asyncio
    async def test_rejected_when_zero_quantity(self):
        broker = _make_broker(connected=True)
        result = await broker.place_order({"symbol": "XAUUSD", "direction": "long", "quantity": 0.0})
        assert result["status"] == "rejected"
        assert result["reason"] == "zero_quantity"

    @pytest.mark.asyncio
    async def test_filled_market_order(self):
        broker = _make_broker(connected=True)
        trade = _make_trade(status="Filled", avg_price=1800.0, filled=1.0)
        broker._ib.placeOrder.return_value = trade

        with (
            patch("brokers.ibkr._IB_AVAILABLE", True),
            patch.object(broker, "_build_gold_contract", return_value=MagicMock()),
            patch.object(broker, "_build_ib_order", return_value=MagicMock()),
            patch.object(
                broker,
                "_wait_for_fill",
                new_callable=AsyncMock,
                return_value={
                    "status": "filled",
                    "fill_price": 1800.0,
                    "quantity": 1.0,
                    "direction": "long",
                    "order_id": "42",
                    "client_ref": "ref",
                    "broker": "ibkr",
                },
            ),
        ):
            result = await broker.place_order({"symbol": "XAUUSD", "direction": "long", "quantity": 1.0})

        assert result["status"] == "filled"
        assert result["fill_price"] == 1800.0
        assert broker._total_fills == 1

    @pytest.mark.asyncio
    async def test_sell_direction_maps_correctly(self):
        broker = _make_broker(connected=True)
        with (
            patch("brokers.ibkr._IB_AVAILABLE", True),
            patch.object(broker, "_build_gold_contract", return_value=MagicMock()),
            patch.object(broker, "_build_ib_order", return_value=MagicMock()) as mock_build,
            patch.object(
                broker,
                "_wait_for_fill",
                new_callable=AsyncMock,
                return_value={
                    "status": "filled",
                    "fill_price": 1800.0,
                    "quantity": 1.0,
                    "direction": "short",
                    "order_id": "1",
                    "client_ref": "x",
                    "broker": "ibkr",
                },
            ),
        ):
            broker._ib.placeOrder.return_value = MagicMock()
            await broker.place_order({"symbol": "XAUUSD", "direction": "short", "quantity": 1.0})
        mock_build.assert_called_once()
        assert mock_build.call_args[0][0] == "SELL"

    @pytest.mark.asyncio
    async def test_returns_rejected_on_exception(self):
        broker = _make_broker(connected=True)
        with (
            patch("brokers.ibkr._IB_AVAILABLE", True),
            patch.object(broker, "_build_gold_contract", side_effect=RuntimeError("contract error")),
        ):
            result = await broker.place_order({"symbol": "XAUUSD", "direction": "long", "quantity": 1.0})
        assert result["status"] == "rejected"


# ── _wait_for_fill ────────────────────────────────────────────────────────────


class TestWaitForFill:
    @pytest.mark.asyncio
    async def test_returns_filled_on_filled_status(self):
        broker = _make_broker()
        trade = _make_trade(status="Filled", avg_price=1800.0, filled=1.0)
        result = await broker._wait_for_fill(trade, "ref-1")
        assert result["status"] == "filled"
        assert result["fill_price"] == 1800.0

    @pytest.mark.asyncio
    async def test_returns_rejected_on_cancelled_status(self):
        broker = _make_broker()
        trade = _make_trade(status="Cancelled")
        result = await broker._wait_for_fill(trade, "ref-1")
        assert result["status"] == "rejected"
        assert "ibkr_status" in result["reason"]

    @pytest.mark.asyncio
    async def test_returns_rejected_on_api_cancelled(self):
        broker = _make_broker()
        trade = _make_trade(status="ApiCancelled")
        result = await broker._wait_for_fill(trade, "ref-1")
        assert result["status"] == "rejected"

    @pytest.mark.asyncio
    async def test_times_out_and_cancels_order(self):
        broker = _make_broker()
        trade = _make_trade(status="Submitted")  # never fills

        with patch("brokers.ibkr._ORDER_TIMEOUT", 0.05):
            result = await broker._wait_for_fill(trade, "ref-1")

        assert result["status"] == "rejected"
        assert result["reason"] == "fill_timeout"
        broker._ib.cancelOrder.assert_called_once()

    @pytest.mark.asyncio
    async def test_cancel_exception_suppressed_on_timeout(self):
        broker = _make_broker()
        trade = _make_trade(status="Submitted")
        broker._ib.cancelOrder.side_effect = RuntimeError("cancel failed")

        with patch("brokers.ibkr._ORDER_TIMEOUT", 0.05):
            result = await broker._wait_for_fill(trade, "ref-1")

        assert result["status"] == "rejected"  # exception suppressed, not raised


# ── cancel_order ──────────────────────────────────────────────────────────────


class TestCancelOrder:
    @pytest.mark.asyncio
    async def test_returns_false_when_not_connected(self):
        broker = _make_broker(connected=False)
        result = await broker.cancel_order(42)
        assert result is False

    @pytest.mark.asyncio
    async def test_cancels_matching_order(self):
        broker = _make_broker(connected=True)
        trade = MagicMock()
        trade.order.orderId = 42
        broker._ib.openTrades.return_value = [trade]
        result = await broker.cancel_order(42)
        assert result is True
        broker._ib.cancelOrder.assert_called_once_with(trade.order)

    @pytest.mark.asyncio
    async def test_returns_false_when_order_not_found(self):
        broker = _make_broker(connected=True)
        trade = MagicMock()
        trade.order.orderId = 99
        broker._ib.openTrades.return_value = [trade]
        result = await broker.cancel_order(42)
        assert result is False

    @pytest.mark.asyncio
    async def test_returns_false_on_exception(self):
        broker = _make_broker(connected=True)
        broker._ib.openTrades.side_effect = RuntimeError("IB error")
        result = await broker.cancel_order(42)
        assert result is False


# ── get_open_positions ────────────────────────────────────────────────────────


class TestGetOpenPositions:
    @pytest.mark.asyncio
    async def test_returns_empty_when_not_connected(self):
        broker = _make_broker(connected=False)
        result = await broker.get_open_positions()
        assert result == []

    @pytest.mark.asyncio
    async def test_returns_positions(self):
        broker = _make_broker(connected=True)
        pos = MagicMock()
        pos.contract.symbol = "XAUUSD"
        pos.position = 2.0
        pos.avgCost = 1800.0
        broker._ib.positions.return_value = [pos]
        result = await broker.get_open_positions()
        assert len(result) == 1
        assert result[0]["symbol"] == "XAUUSD"
        assert result[0]["direction"] == "long"

    @pytest.mark.asyncio
    async def test_skips_zero_positions(self):
        broker = _make_broker(connected=True)
        pos = MagicMock()
        pos.position = 0.0
        broker._ib.positions.return_value = [pos]
        result = await broker.get_open_positions()
        assert result == []

    @pytest.mark.asyncio
    async def test_short_position_direction(self):
        broker = _make_broker(connected=True)
        pos = MagicMock()
        pos.contract.symbol = "XAUUSD"
        pos.position = -1.0
        pos.avgCost = 1800.0
        broker._ib.positions.return_value = [pos]
        result = await broker.get_open_positions()
        assert result[0]["direction"] == "short"

    @pytest.mark.asyncio
    async def test_returns_empty_on_exception(self):
        broker = _make_broker(connected=True)
        broker._ib.positions.side_effect = RuntimeError("IB error")
        result = await broker.get_open_positions()
        assert result == []


# ── ping ──────────────────────────────────────────────────────────────────────


class TestPing:
    @pytest.mark.asyncio
    async def test_returns_high_latency_when_not_connected(self):
        broker = _make_broker(connected=False)
        result = await broker.ping()
        assert result == 9999.0

    @pytest.mark.asyncio
    async def test_returns_latency_ms_when_connected(self):
        broker = _make_broker(connected=True)
        broker._ib.reqCurrentTimeAsync = AsyncMock(return_value=None)
        result = await broker.ping()
        assert isinstance(result, float)
        assert result < 9999.0

    @pytest.mark.asyncio
    async def test_returns_high_latency_on_exception(self):
        broker = _make_broker(connected=True)
        broker._ib.reqCurrentTimeAsync = AsyncMock(side_effect=RuntimeError("timeout"))
        result = await broker.ping()
        assert result == 9999.0


# ── IB event callbacks ────────────────────────────────────────────────────────


class TestCallbacks:
    def test_on_order_status_logs_without_raising(self):
        broker = _make_broker()
        trade = _make_trade()
        broker._on_order_status(trade)  # must not raise

    def test_on_exec_details_calls_fill_callbacks(self):
        broker = _make_broker()
        cb = MagicMock()
        broker.register_fill_callback(cb)

        trade = _make_trade()
        fill = MagicMock()
        fill.execution.price = 1800.0
        fill.execution.shares = 1.0

        broker._on_exec_details(trade, fill)
        cb.assert_called_once_with(trade, fill)

    def test_on_exec_details_suppresses_callback_exception(self):
        broker = _make_broker()
        bad_cb = MagicMock(side_effect=RuntimeError("cb error"))
        broker.register_fill_callback(bad_cb)

        trade = _make_trade()
        fill = MagicMock()
        fill.execution.price = 1800.0
        fill.execution.shares = 1.0

        broker._on_exec_details(trade, fill)  # must not raise

    def test_on_error_ignores_informational_codes(self):
        broker = _make_broker()
        for code in (2104, 2106, 2158):
            broker._on_error(0, code, "info", None)  # must not raise

    def test_on_error_logs_real_errors(self):
        broker = _make_broker()
        broker._on_error(1, 502, "Couldn't connect", None)  # must not raise


# ── Forbidden market-data methods ────────────────────────────────────────────


class TestForbiddenMethods:
    def test_get_market_data_raises(self):
        broker = _make_broker()
        with pytest.raises(MarketDataForbiddenError):
            broker.get_market_data("XAUUSD")

    def test_subscribe_ticks_raises(self):
        broker = _make_broker()
        with pytest.raises(MarketDataForbiddenError):
            broker.subscribe_ticks("XAUUSD")

    @pytest.mark.asyncio
    async def test_req_mkt_data_raises(self):
        broker = _make_broker()
        with pytest.raises(MarketDataForbiddenError):
            await broker.reqMktData()

    @pytest.mark.asyncio
    async def test_req_historical_data_raises(self):
        broker = _make_broker()
        with pytest.raises(MarketDataForbiddenError):
            await broker.reqHistoricalData()

    @pytest.mark.asyncio
    async def test_get_ohlcv_raises(self):
        broker = _make_broker()
        with pytest.raises(MarketDataForbiddenError):
            await broker.get_ohlcv()

    @pytest.mark.asyncio
    async def test_get_current_price_raises(self):
        broker = _make_broker()
        with pytest.raises(MarketDataForbiddenError):
            await broker.get_current_price()

    @pytest.mark.asyncio
    async def test_stream_prices_raises(self):
        broker = _make_broker()
        with pytest.raises(MarketDataForbiddenError):
            await broker.stream_prices()


# ── metrics ───────────────────────────────────────────────────────────────────


class TestMetrics:
    def test_metrics_returns_expected_keys(self):
        broker = _make_broker()
        broker._total_orders = 10
        broker._total_fills = 8
        m = broker.metrics()
        assert m["broker"] == "ibkr"
        assert m["connected"] is True
        assert m["total_orders"] == 10
        assert m["total_fills"] == 8
        assert m["fill_rate"] == pytest.approx(0.8)

    def test_fill_rate_zero_when_no_orders(self):
        broker = _make_broker()
        m = broker.metrics()
        assert m["fill_rate"] == pytest.approx(0.0)


# ── Backward-compat aliases ───────────────────────────────────────────────────


class TestAliases:
    def test_ibkr_connector_is_ibkr_broker(self):
        assert IBKRConnector is IBKRBroker

    def test_interactive_brokers_is_ibkr_broker(self):
        assert InteractiveBrokers is IBKRBroker


# ── _build_gold_contract / _build_ib_order ────────────────────────────────────


class TestBuildHelpers:
    def test_build_gold_contract_raises_without_ib_insync(self):
        broker = _make_broker()
        with patch("brokers.ibkr._IB_AVAILABLE", False):
            with pytest.raises(RuntimeError, match="ib_insync not available"):
                broker._build_gold_contract("XAUUSD")

    def test_build_ib_order_raises_without_ib_insync(self):
        broker = _make_broker()
        with patch("brokers.ibkr._IB_AVAILABLE", False):
            with pytest.raises(RuntimeError, match="ib_insync not available"):
                broker._build_ib_order("BUY", 1.0, "MARKET", {})

    def test_build_ib_order_market(self):
        broker = _make_broker()
        mock_market_order = MagicMock()
        with (
            patch("brokers.ibkr._IB_AVAILABLE", True),
            patch("brokers.ibkr.MarketOrder", return_value=mock_market_order) as mock_mo,
        ):
            broker._build_ib_order("BUY", 1.0, "MARKET", {})
        mock_mo.assert_called_once_with("BUY", 1.0)

    def test_build_ib_order_limit(self):
        broker = _make_broker()
        with patch("brokers.ibkr._IB_AVAILABLE", True), patch("brokers.ibkr.LimitOrder") as mock_lo:
            broker._build_ib_order("BUY", 1.0, "LIMIT", {"mid_price": 1800.0})
        mock_lo.assert_called_once_with("BUY", 1.0, 1800.0)

    def test_build_ib_order_stop(self):
        broker = _make_broker()
        with patch("brokers.ibkr._IB_AVAILABLE", True), patch("brokers.ibkr.StopOrder") as mock_so:
            broker._build_ib_order("SELL", 1.0, "STOP", {"stop_price": 1790.0})
        mock_so.assert_called_once_with("SELL", 1.0, 1790.0)

    def test_build_ib_order_stop_limit(self):
        broker = _make_broker()
        with patch("brokers.ibkr._IB_AVAILABLE", True), patch("brokers.ibkr.StopLimitOrder") as mock_slo:
            broker._build_ib_order("BUY", 1.0, "STOP_LIMIT", {"mid_price": 1800.0, "stop_price": 1790.0})
        mock_slo.assert_called_once_with("BUY", 1.0, 1800.0, 1790.0)

    def test_build_ib_order_unknown_type_falls_back_to_market(self):
        broker = _make_broker()
        with patch("brokers.ibkr._IB_AVAILABLE", True), patch("brokers.ibkr.MarketOrder") as mock_mo:
            broker._build_ib_order("BUY", 1.0, "UNKNOWN_TYPE", {})
        mock_mo.assert_called_once()

    def test_build_gold_contract_futures(self):
        broker = _make_broker()
        with patch("brokers.ibkr._IB_AVAILABLE", True), patch("brokers.ibkr.Future") as mock_future:
            broker._build_gold_contract("XAUUSD", use_futures=True)
        mock_future.assert_called_once_with(symbol="GC", exchange="NYMEX", currency="USD")

    def test_build_gold_contract_spot(self):
        broker = _make_broker()
        with patch("brokers.ibkr._IB_AVAILABLE", True), patch("brokers.ibkr.Commodity") as mock_commodity:
            broker._build_gold_contract("XAUUSD", use_futures=False)
        mock_commodity.assert_called_once_with("XAUUSD", "SMART", "USD")

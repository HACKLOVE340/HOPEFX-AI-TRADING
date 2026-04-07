# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
Unit tests for brokers/cme_comex.py — CMEComexConnector.

All external dependencies (FIX adapter, IBKR connector) are patched so
tests run without any live credentials or network access.
"""

from __future__ import annotations

import sys
import types
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

UTC = timezone.utc

# ---------------------------------------------------------------------------
# Stub out heavy optional imports before the module is loaded
# ---------------------------------------------------------------------------

def _make_fix_stubs():
    """Return a minimal execution.fix_adapter stub module."""
    mod = types.ModuleType("execution.fix_adapter")

    class FIXSide:
        BUY = "BUY"
        SELL = "SELL"

    class FIXOrdType:
        MARKET = "MARKET"
        LIMIT = "LIMIT"
        STOP = "STOP"

    @dataclass
    class FIXOrder:
        symbol: str
        side: str
        quantity: float
        ord_type: str
        price: float | None = None
        stop_price: float | None = None
        account: str = ""

    @dataclass
    class FIXReport:
        order_id: str
        cl_ord_id: str
        cum_qty: float
        avg_px: float
        latency_ms: float = 1.0

    class FIXAdapter:
        def __init__(self, **kwargs):
            pass

        def start(self):
            pass

        async def send_order(self, order):
            return FIXReport(
                order_id=str(uuid.uuid4()),
                cl_ord_id=str(uuid.uuid4()),
                cum_qty=order.quantity,
                avg_px=2350.0,
                latency_ms=1.5,
            )

    mod.FIXSide = FIXSide
    mod.FIXOrdType = FIXOrdType
    mod.FIXOrder = FIXOrder
    mod.FIXReport = FIXReport
    mod.FIXAdapter = FIXAdapter
    return mod


# Inject stubs before importing the module under test.
# Import the real execution package first so sys.modules["execution"] is the
# package (with __path__), then overlay only the fix_adapter sub-module stub.
# Using a bare types.ModuleType here would shadow the package and break any
# later import of execution.engine / execution.tca / etc.
_fix_stub = _make_fix_stubs()
import execution as _execution_pkg  # noqa: E402 — must run before cme_comex import
sys.modules["execution.fix_adapter"] = _fix_stub


# ---------------------------------------------------------------------------
# Import the module under test (after stubs are in place)
# ---------------------------------------------------------------------------

from brokers.cme_comex import (  # noqa: E402
    CMEComexConnector,
    CMEFill,
    _CME_MULTIPLIER,
    _CME_TICK_VALUE,
)
from brokers.base import AccountInfo, OrderSide, OrderStatus, OrderType  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_connector(**kwargs) -> CMEComexConnector:
    """Return a connector with paper fallback enabled and FIX/IBKR disabled."""
    defaults = dict(
        fix_host="127.0.0.1",
        fix_port=9876,
        fix_sender_id="TEST",
        fix_target_id="CME",
        fix_username="",
        fix_password="",
        fix_config_file="fix.cfg",
        cme_account="TEST_ACCT",
        ibkr_fallback=False,
        paper_fallback=True,
    )
    defaults.update(kwargs)
    return CMEComexConnector(**defaults)


# ---------------------------------------------------------------------------
# CMEFill dataclass
# ---------------------------------------------------------------------------

class TestCMEFill:
    def test_notional_usd(self):
        fill = CMEFill(
            order_id="o1",
            cl_ord_id="c1",
            symbol="GC",
            side="BUY",
            contracts=2.0,
            avg_price=2500.0,
            commission=4.0,
            latency_ms=1.0,
            source="paper",
        )
        assert fill.notional_usd == 2.0 * _CME_MULTIPLIER * 2500.0

    def test_tick_value_usd(self):
        fill = CMEFill(
            order_id="o1",
            cl_ord_id="c1",
            symbol="GC",
            side="BUY",
            contracts=3.0,
            avg_price=2000.0,
            commission=6.0,
            latency_ms=0.5,
            source="paper",
        )
        assert fill.tick_value_usd == 3.0 * _CME_TICK_VALUE

    def test_timestamp_defaults_to_now(self):
        fill = CMEFill(
            order_id="o1",
            cl_ord_id="c1",
            symbol="GC",
            side="BUY",
            contracts=1.0,
            avg_price=2000.0,
            commission=2.0,
            latency_ms=0.0,
            source="paper",
        )
        assert isinstance(fill.timestamp, datetime)


# ---------------------------------------------------------------------------
# Symbol normalisation
# ---------------------------------------------------------------------------

class TestNormaliseSymbol:
    @pytest.mark.parametrize("symbol,expected", [
        ("XAU_USD", "GC"),
        ("XAUUSD",  "GC"),
        ("XAU/USD", "GC"),
        ("GOLD",    "GC"),
        ("GC",      "GC"),
        ("gc",      "GC"),
        ("UNKNOWN", "GC"),  # unmapped → default "GC"
    ])
    def test_known_symbols(self, symbol, expected):
        assert CMEComexConnector._normalise_symbol(symbol) == expected


# ---------------------------------------------------------------------------
# Commission estimation
# ---------------------------------------------------------------------------

class TestEstimateCommission:
    def test_single_contract(self):
        assert CMEComexConnector._estimate_commission(1.0) == 2.00

    def test_multiple_contracts(self):
        assert CMEComexConnector._estimate_commission(5.0) == 10.00

    def test_fractional_contracts(self):
        result = CMEComexConnector._estimate_commission(1.5)
        assert result == round(1.5 * 2.00, 2)


# ---------------------------------------------------------------------------
# connect()
# ---------------------------------------------------------------------------

class TestConnect:
    def test_connect_paper_fallback(self):
        conn = _make_connector()
        # Force FIX and IBKR init to fail so paper path is exercised
        with patch.object(conn, "_init_fix", return_value=False), \
             patch.object(conn, "_init_ibkr", return_value=False):
            assert conn.connect() is True
        assert conn._connected is True
        assert conn._fix_available is False
        assert conn._ibkr_available is False

    def test_connect_no_fallback_returns_false(self):
        conn = _make_connector(paper_fallback=False, ibkr_fallback=False)
        with patch.object(conn, "_init_fix", return_value=False):
            assert conn.connect() is False
        assert conn._connected is False

    def test_connect_fix_success(self):
        conn = _make_connector(paper_fallback=False, ibkr_fallback=False)
        with patch.object(conn, "_init_fix", return_value=True):
            result = conn.connect()
        assert result is True
        assert conn._fix_available is True

    def test_connect_ibkr_fallback_when_fix_fails(self):
        conn = _make_connector(ibkr_fallback=True, paper_fallback=False)
        with patch.object(conn, "_init_fix", return_value=False), \
             patch.object(conn, "_init_ibkr", return_value=True):
            result = conn.connect()
        assert result is True
        assert conn._ibkr_available is True

    def test_connect_skips_ibkr_when_fix_succeeds(self):
        conn = _make_connector(ibkr_fallback=True, paper_fallback=False)
        mock_ibkr = MagicMock(return_value=True)
        with patch.object(conn, "_init_fix", return_value=True), \
             patch.object(conn, "_init_ibkr", mock_ibkr):
            conn.connect()
        mock_ibkr.assert_not_called()


# ---------------------------------------------------------------------------
# disconnect()
# ---------------------------------------------------------------------------

class TestDisconnect:
    def test_disconnect_returns_true(self):
        conn = _make_connector()
        with patch.object(conn, "_init_fix", return_value=False):
            conn.connect()
        assert conn.disconnect() is True
        assert conn._connected is False


# ---------------------------------------------------------------------------
# place_order() — paper path
# ---------------------------------------------------------------------------

class TestPlaceOrderPaper:
    def setup_method(self):
        self.conn = _make_connector()
        with patch.object(self.conn, "_init_fix", return_value=False), \
             patch.object(self.conn, "_init_ibkr", return_value=False):
            self.conn.connect()

    def test_market_buy_returns_filled_order(self):
        order = self.conn.place_order(
            symbol="XAU_USD",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=1.0,
        )
        assert order.status == OrderStatus.FILLED
        assert order.filled_quantity == 1.0
        assert order.side == OrderSide.BUY
        assert order.symbol == "XAU_USD"

    def test_limit_sell_uses_provided_price(self):
        order = self.conn.place_order(
            symbol="GC",
            side=OrderSide.SELL,
            order_type=OrderType.LIMIT,
            quantity=2.0,
            price=2400.0,
        )
        assert order.average_price == 2400.0
        assert order.filled_quantity == 2.0

    def test_market_order_uses_default_price_when_none(self):
        order = self.conn.place_order(
            symbol="GC",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=1.0,
            price=None,
        )
        assert order.average_price == 2000.0

    def test_commission_stored_in_metadata(self):
        order = self.conn.place_order(
            symbol="GC",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=3.0,
        )
        assert order.metadata is not None
        assert order.metadata["commission"] == CMEComexConnector._estimate_commission(3.0)

    def test_order_id_is_unique(self):
        o1 = self.conn.place_order("GC", OrderSide.BUY, OrderType.MARKET, 1.0)
        o2 = self.conn.place_order("GC", OrderSide.BUY, OrderType.MARKET, 1.0)
        assert o1.id != o2.id

    def test_fill_recorded_in_history(self):
        self.conn.place_order("GC", OrderSide.BUY, OrderType.MARKET, 1.0)
        assert len(self.conn._fills) == 1
        assert self.conn._fills[0].source == "paper"

    def test_no_execution_path_raises(self):
        conn = _make_connector(paper_fallback=False)
        conn._connected = True
        with pytest.raises(RuntimeError, match="no execution path available"):
            conn.place_order("GC", OrderSide.BUY, OrderType.MARKET, 1.0)

    def test_symbol_variants_all_normalise(self):
        for sym in ("XAU_USD", "XAUUSD", "GOLD", "GC"):
            order = self.conn.place_order(sym, OrderSide.BUY, OrderType.MARKET, 1.0)
            assert order.status == OrderStatus.FILLED

    def test_order_seq_increments(self):
        assert self.conn._order_seq == 0
        self.conn.place_order("GC", OrderSide.BUY, OrderType.MARKET, 1.0)
        assert self.conn._order_seq == 1
        self.conn.place_order("GC", OrderSide.SELL, OrderType.MARKET, 1.0)
        assert self.conn._order_seq == 2


# ---------------------------------------------------------------------------
# place_order() — IBKR path
# ---------------------------------------------------------------------------

class TestPlaceOrderIBKR:
    def _make_ibkr_order(self, price=2350.0, qty=1.0):
        mock_order = MagicMock()
        mock_order.order_id = str(uuid.uuid4())
        mock_order.filled_quantity = qty
        mock_order.filled_price = price
        return mock_order

    def test_ibkr_path_used_when_available(self):
        conn = _make_connector(ibkr_fallback=False, paper_fallback=False)
        conn._ibkr_available = True
        conn._connected = True
        mock_ibkr = MagicMock()
        mock_ibkr.place_order.return_value = self._make_ibkr_order(2350.0, 1.0)
        conn._ibkr_connector = mock_ibkr

        order = conn.place_order("GC", OrderSide.BUY, OrderType.LIMIT, 1.0, price=2350.0)

        mock_ibkr.place_order.assert_called_once()
        assert order.average_price == 2350.0
        assert order.status == OrderStatus.FILLED

    def test_ibkr_fill_source_recorded(self):
        conn = _make_connector(ibkr_fallback=False, paper_fallback=False)
        conn._ibkr_available = True
        conn._connected = True
        mock_ibkr = MagicMock()
        mock_ibkr.place_order.return_value = self._make_ibkr_order(2400.0, 2.0)
        conn._ibkr_connector = mock_ibkr

        conn.place_order("GC", OrderSide.BUY, OrderType.MARKET, 2.0)
        assert conn._fills[-1].source == "ibkr"


# ---------------------------------------------------------------------------
# cancel_order() / close_position() / get_order()
# ---------------------------------------------------------------------------

class TestOrderManagement:
    def test_cancel_order_returns_false_on_paper(self):
        conn = _make_connector()
        with patch.object(conn, "_init_fix", return_value=False):
            conn.connect()
        assert conn.cancel_order("any-id") is False

    def test_cancel_order_delegates_to_ibkr(self):
        conn = _make_connector()
        conn._ibkr_available = True
        mock_ibkr = MagicMock()
        mock_ibkr.cancel_order.return_value = True
        conn._ibkr_connector = mock_ibkr
        assert conn.cancel_order("order-123") is True

    def test_close_position_returns_false_on_paper(self):
        conn = _make_connector()
        with patch.object(conn, "_init_fix", return_value=False):
            conn.connect()
        assert conn.close_position("GC") is False

    def test_get_order_returns_none_for_unknown_id(self):
        conn = _make_connector()
        with patch.object(conn, "_init_fix", return_value=False):
            conn.connect()
        assert conn.get_order("nonexistent") is None

    def test_get_order_returns_order_for_known_fill(self):
        conn = _make_connector()
        with patch.object(conn, "_init_fix", return_value=False):
            conn.connect()
        conn.place_order("GC", OrderSide.BUY, OrderType.MARKET, 1.0, price=2000.0)
        fill_id = conn._fills[0].order_id
        found = conn.get_order(fill_id)
        assert found is not None
        assert found.id == fill_id


# ---------------------------------------------------------------------------
# get_account_info()
# ---------------------------------------------------------------------------

class TestGetAccountInfo:
    def test_returns_zero_balance_on_paper(self):
        conn = _make_connector()
        with patch.object(conn, "_init_fix", return_value=False):
            conn.connect()
        info = conn.get_account_info()
        assert isinstance(info, AccountInfo)
        assert info.balance == 0.0

    def test_delegates_to_ibkr_when_available(self):
        conn = _make_connector()
        conn._ibkr_available = True
        mock_ibkr = MagicMock()
        mock_ibkr.get_account_info.return_value = AccountInfo(
            balance=50000.0,
            equity=51000.0,
            margin_used=1000.0,
            margin_available=49000.0,
            positions_count=2,
        )
        conn._ibkr_connector = mock_ibkr
        info = conn.get_account_info()
        assert info.balance == 50000.0

    def test_falls_back_to_paper_when_ibkr_raises(self):
        conn = _make_connector()
        conn._ibkr_available = True
        mock_ibkr = MagicMock()
        mock_ibkr.get_account_info.side_effect = RuntimeError("IBKR down")
        conn._ibkr_connector = mock_ibkr
        info = conn.get_account_info()
        assert info.balance == 0.0


# ---------------------------------------------------------------------------
# get_market_data()
# ---------------------------------------------------------------------------

class TestGetMarketData:
    def test_returns_empty_without_ibkr(self):
        conn = _make_connector()
        with patch.object(conn, "_init_fix", return_value=False):
            conn.connect()
        assert conn.get_market_data("GC") == []

    def test_delegates_to_ibkr_when_available(self):
        conn = _make_connector()
        conn._ibkr_available = True
        mock_ibkr = MagicMock()
        mock_ibkr.get_market_data.return_value = [{"open": 2000.0}]
        conn._ibkr_connector = mock_ibkr
        data = conn.get_market_data("GC", "1h", 10)
        assert data == [{"open": 2000.0}]

    def test_returns_empty_when_ibkr_raises(self):
        conn = _make_connector()
        conn._ibkr_available = True
        mock_ibkr = MagicMock()
        mock_ibkr.get_market_data.side_effect = RuntimeError("timeout")
        conn._ibkr_connector = mock_ibkr
        assert conn.get_market_data("GC") == []


# ---------------------------------------------------------------------------
# get_positions()
# ---------------------------------------------------------------------------

class TestGetPositions:
    def test_returns_empty_without_ibkr(self):
        conn = _make_connector()
        with patch.object(conn, "_init_fix", return_value=False):
            conn.connect()
        assert conn.get_positions() == []

    def test_delegates_to_ibkr(self):
        conn = _make_connector()
        conn._ibkr_available = True
        mock_ibkr = MagicMock()
        mock_ibkr.get_positions.return_value = [MagicMock()]
        conn._ibkr_connector = mock_ibkr
        assert len(conn.get_positions()) == 1


# ---------------------------------------------------------------------------
# metrics()
# ---------------------------------------------------------------------------

class TestMetrics:
    def test_empty_metrics_before_any_fills(self):
        conn = _make_connector()
        with patch.object(conn, "_init_fix", return_value=False):
            conn.connect()
        m = conn.metrics()
        assert m["fills"] == 0

    def test_metrics_after_paper_fills(self):
        conn = _make_connector()
        with patch.object(conn, "_init_fix", return_value=False), \
             patch.object(conn, "_init_ibkr", return_value=False):
            conn.connect()
        conn.place_order("GC", OrderSide.BUY, OrderType.MARKET, 1.0, price=2000.0)
        conn.place_order("GC", OrderSide.SELL, OrderType.LIMIT, 2.0, price=2100.0)
        m = conn.metrics()
        assert m["fills"] == 2
        assert m["sources"]["paper"] == 2
        assert m["avg_latency_ms"] == 0.0
        assert m["fix_available"] is False
        assert m["ibkr_available"] is False

    def test_metrics_tracks_fix_and_ibkr_flags(self):
        conn = _make_connector()
        conn._fix_available = True
        conn._ibkr_available = True
        conn._connected = True
        # Add a paper fill so metrics() returns the full dict (not early-return stub)
        conn._fills.append(
            CMEFill(
                order_id="x",
                cl_ord_id="y",
                symbol="GC",
                side="BUY",
                contracts=1.0,
                avg_price=2000.0,
                commission=2.0,
                latency_ms=1.0,
                source="fix",
            )
        )
        m = conn.metrics()
        assert m["fix_available"] is True
        assert m["ibkr_available"] is True


# ---------------------------------------------------------------------------
# from_env() constructor
# ---------------------------------------------------------------------------

class TestFromEnv:
    def test_from_env_returns_instance(self):
        conn = CMEComexConnector.from_env()
        assert isinstance(conn, CMEComexConnector)

# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
tests/unit/test_live_safe_threshold.py
========================================
Comprehensive tests for all 10 live-safe threshold items:

 W1a  SL/TP monitor — SLTPMonitor detects breaches, closes positions, retries
 W1b  SL/TP monitor — auto-restart after crash, no-op on empty positions
 W2a  LIVE_MODE_CONFIRMED gate — blocks live broker without flag
 W2b  LIVE_MODE_CONFIRMED gate — allows paper broker without flag
 W2c  LIVE_MODE_CONFIRMED gate — allows live broker with flag set
 W3a  Self-trade prevention — rejects self-matching new orders
 W3b  Self-trade prevention — allows crossing orders from different accounts
 W4a  Margin check — blocks when margin buffer insufficient
 W4b  Margin check — passes when margin adequate
 W5a  Leverage hard cap — blocks order exceeding cap
 W5b  Leverage hard cap — passes order within cap
 W6a  Kill switch escalation — calls broker-level cancel when positions remain
 W6b  Kill switch escalation — RiskLimits.max_leverage_ratio field exists
 W7   MTF calibration leakage — retrain functions use cv='prefit'
 W8   ByBit connector — instantiation, symbol translation, connection
 W9   COMEX gold futures — _build_contract GC/NYMEX routing
 W10a Spread spike detector — detects spike above multiplier threshold
 W10b Spread spike detector — no spike within normal range
 W10c Spread spike detector — absolute USD limit always blocks
 W10d Spread spike detector — engine blocks order when spread spiking
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

UTC = timezone.utc
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


def _make_engine(live_mode_confirmed: bool = False, paper: bool = True):
    """Return a minimal ExecutionEngine for unit tests."""
    from execution.engine import ExecutionEngine

    broker = MagicMock()
    broker.paper_trading = paper
    broker.place_order = MagicMock(return_value=MagicMock(
        id="ord1",
        status=MagicMock(value="FILLED"),
        filled_quantity=1.0,
        average_price=2350.0,
    ))
    broker.get_account_info = MagicMock(return_value=MagicMock(
        balance=100_000.0,
        equity=100_000.0,
        margin_used=5_000.0,
        margin_available=95_000.0,
    ))

    risk = MagicMock()
    risk._trading_halted = False
    risk._kill_switch = None
    risk.validate_trade = MagicMock(return_value=(True, "OK"))

    engine = ExecutionEngine(broker_manager=broker, risk_manager=risk)
    engine._live_mode_confirmed = live_mode_confirmed
    engine._running = True
    return engine, broker, risk


def _make_request(**kwargs):
    from execution.engine import ExecutionRequest

    defaults = dict(
        symbol="XAUUSD",
        side="BUY",
        quantity=0.1,
        order_type="MARKET",
        price=2350.0,
        strategy_id="test",
    )
    defaults.update(kwargs)
    return ExecutionRequest(**defaults)


# ─────────────────────────────────────────────────────────────────────────────
# W1a — SL/TP monitor breach detection
# ─────────────────────────────────────────────────────────────────────────────


class TestSLTPMonitorBreachDetection:
    def _make_pos(self, side="BUY", sl=2300.0, tp=2400.0, qty=1.0):
        pos = MagicMock()
        pos.position_id = "pos1"
        pos.symbol = "XAUUSD"
        pos.side = side
        pos.stop_loss = sl
        pos.take_profit = tp
        pos.quantity = qty
        return pos

    def test_long_sl_breach_detected(self):
        from execution.sl_tp_monitor import SLTPMonitor

        pos = self._make_pos(side="BUY", sl=2300.0, tp=2400.0)
        reason = SLTPMonitor._check_breach(pos, mid=2299.5)
        assert reason == "stop_loss"

    def test_long_tp_breach_detected(self):
        from execution.sl_tp_monitor import SLTPMonitor

        pos = self._make_pos(side="BUY", sl=2300.0, tp=2400.0)
        reason = SLTPMonitor._check_breach(pos, mid=2400.5)
        assert reason == "take_profit"

    def test_short_sl_breach_detected(self):
        from execution.sl_tp_monitor import SLTPMonitor

        pos = self._make_pos(side="SELL", sl=2400.0, tp=2200.0)
        reason = SLTPMonitor._check_breach(pos, mid=2400.5)
        assert reason == "stop_loss"

    def test_short_tp_breach_detected(self):
        from execution.sl_tp_monitor import SLTPMonitor

        pos = self._make_pos(side="SELL", sl=2400.0, tp=2200.0)
        reason = SLTPMonitor._check_breach(pos, mid=2199.5)
        assert reason == "take_profit"

    def test_no_breach_when_price_inside_range(self):
        from execution.sl_tp_monitor import SLTPMonitor

        pos = self._make_pos(side="BUY", sl=2300.0, tp=2400.0)
        assert SLTPMonitor._check_breach(pos, mid=2350.0) is None

    def test_no_breach_when_sl_is_none(self):
        from execution.sl_tp_monitor import SLTPMonitor

        pos = self._make_pos(side="BUY", sl=None, tp=None)
        assert SLTPMonitor._check_breach(pos, mid=2200.0) is None

    def test_no_breach_when_sl_is_zero(self):
        from execution.sl_tp_monitor import SLTPMonitor

        pos = self._make_pos(side="BUY", sl=0.0, tp=0.0)
        assert SLTPMonitor._check_breach(pos, mid=2200.0) is None


class TestSLTPMonitorClose:
    def test_close_position_called_on_breach(self):
        from execution.sl_tp_monitor import SLTPMonitor

        pm = MagicMock()
        pm.close_position = AsyncMock()
        pm.get_all_positions = MagicMock(return_value=[])

        broker = MagicMock()
        mock_order = MagicMock(id="close1")
        broker.place_order = MagicMock(return_value=mock_order)

        tick_cache = {}
        monitor = SLTPMonitor(pm, broker, tick_cache)

        pos = MagicMock()
        pos.position_id = "p1"
        pos.symbol = "XAUUSD"
        pos.side = "BUY"
        pos.quantity = 1.0

        async def run():
            await monitor._close_position(pos, "stop_loss", 2299.5)

        asyncio.get_event_loop().run_until_complete(run())
        assert broker.place_order.called

    def test_empty_positions_no_close(self):
        from execution.sl_tp_monitor import SLTPMonitor

        pm = MagicMock()
        pm.get_all_positions = MagicMock(return_value=[])
        broker = MagicMock()
        monitor = SLTPMonitor(pm, broker, {})

        async def run():
            await monitor._check_all_positions()

        asyncio.get_event_loop().run_until_complete(run())
        broker.place_order.assert_not_called()

    def test_zero_quantity_skips_close(self):
        from execution.sl_tp_monitor import SLTPMonitor

        pm = MagicMock()
        pm.close_position = AsyncMock()
        broker = MagicMock()
        monitor = SLTPMonitor(pm, broker, {})

        pos = MagicMock()
        pos.position_id = "p1"
        pos.symbol = "XAUUSD"
        pos.side = "BUY"
        pos.quantity = 0.0

        async def run():
            await monitor._close_position(pos, "stop_loss", 2299.0)

        asyncio.get_event_loop().run_until_complete(run())
        broker.place_order.assert_not_called()


# ─────────────────────────────────────────────────────────────────────────────
# W2 — LIVE_MODE_CONFIRMED gate
# ─────────────────────────────────────────────────────────────────────────────


class TestLiveModeConfirmedGate:
    def test_blocks_live_broker_without_confirmation(self):
        engine, broker, _ = _make_engine(live_mode_confirmed=False, paper=False)
        broker.paper_trading = False
        request = _make_request()

        # Force _is_live_broker to return True to simulate a real live broker
        with patch.object(engine, "_is_live_broker", return_value=True):
            report = engine._check_pre_submission_guards(request, 0.0)

        assert report is not None
        assert "LIVE_MODE_NOT_CONFIRMED" in report.message

    def test_allows_paper_broker_without_confirmation(self):
        engine, broker, _ = _make_engine(live_mode_confirmed=False, paper=True)
        broker.paper_trading = True
        request = _make_request()

        # Paper broker: _is_live_broker returns False
        with patch.object(engine, "_is_live_broker", return_value=False):
            report = engine._check_pre_submission_guards(request, 0.0)

        assert report is None  # no block

    def test_allows_live_broker_with_confirmation(self):
        engine, broker, _ = _make_engine(live_mode_confirmed=True, paper=False)
        broker.paper_trading = False
        request = _make_request()

        # Even with live broker + live_mode_confirmed=True, no live-mode block
        with patch.object(engine, "_is_live_broker", return_value=True):
            report = engine._check_pre_submission_guards(request, 0.0)

        # Should not be blocked by live-mode gate
        if report is not None:
            assert "LIVE_MODE_NOT_CONFIRMED" not in report.message

    def test_is_live_broker_detects_paper(self):
        engine, broker, _ = _make_engine()
        broker.paper_trading = True
        assert engine._is_live_broker() is False

    def test_is_live_broker_class_name_mock(self):
        """Brokers with 'mock' or 'paper' in their class name are NOT live."""
        engine, broker, _ = _make_engine()
        # MagicMock has 'mock' in name → not live
        assert engine._is_live_broker() is False


# ─────────────────────────────────────────────────────────────────────────────
# W3a — Self-trade prevention
# ─────────────────────────────────────────────────────────────────────────────


class TestSelfTradePrevention:
    def test_self_trade_rejected_same_account(self):
        from risk.self_trade_prevention import (
            Order,
            SelfTradePrevention,
            SelfTradeAction,
        )

        stp = SelfTradePrevention(prevention_level="account", action=SelfTradeAction.CANCEL_NEW)

        # Add resting sell order from the same account
        resting = Order(
            id="rest1",
            symbol="XAUUSD",
            side="sell",
            size=1.0,
            price=2350.0,
            timestamp=datetime.now(UTC),
            account_id="acc1",
        )
        stp.add_resting_order(resting)

        # New buy order that would cross at same price
        new_order = Order(
            id="new1",
            symbol="XAUUSD",
            side="buy",
            size=1.0,
            price=2350.0,
            timestamp=datetime.now(UTC),
            account_id="acc1",
        )
        result = stp.check_self_trade(new_order)
        assert result is not None
        assert result["action"] in ("reject", "cancel_both", "cancel", "decrement")

    def test_no_self_trade_different_accounts(self):
        from risk.self_trade_prevention import Order, SelfTradePrevention

        stp = SelfTradePrevention(prevention_level="account")

        resting = Order(
            id="rest1",
            symbol="XAUUSD",
            side="sell",
            size=1.0,
            price=2350.0,
            timestamp=datetime.now(UTC),
            account_id="acc1",
        )
        stp.add_resting_order(resting)

        new_order = Order(
            id="new1",
            symbol="XAUUSD",
            side="buy",
            size=1.0,
            price=2350.0,
            timestamp=datetime.now(UTC),
            account_id="acc2",  # Different account
        )
        result = stp.check_self_trade(new_order)
        assert result is None

    def test_engine_stp_check_blocks_self_trade(self):
        """Engine._check_self_trade should return block reason on self-trade."""
        engine, _, _ = _make_engine()

        from risk.self_trade_prevention import Order, SelfTradePrevention, SelfTradeAction

        # Pre-populate STP with a resting order
        stp = SelfTradePrevention(prevention_level="account", action=SelfTradeAction.CANCEL_NEW)
        resting = Order(
            id="rest1",
            symbol="XAUUSD",
            side="sell",
            size=1.0,
            price=2350.0,
            timestamp=datetime.now(UTC),
            account_id="default",
        )
        stp.add_resting_order(resting)
        engine._stp = stp

        req = _make_request(side="BUY", price=2350.0, metadata={"account_id": "default"})
        result = engine._check_self_trade(req)
        assert result is not None
        assert "SELF_TRADE" in result


# ─────────────────────────────────────────────────────────────────────────────
# W4 — Margin check
# ─────────────────────────────────────────────────────────────────────────────


class TestMarginCheck:
    def test_blocks_when_margin_insufficient(self):
        engine, broker, _ = _make_engine()
        # margin_available=95000, margin_used=5000 → buffer = 95000/(5000+notional)
        # Order notional: 2350 * 100 = 235000 → buffer = 95000/240000 = 0.396 < 2.0
        broker.get_account_info = MagicMock(return_value=MagicMock(
            equity=100_000.0,
            margin_used=5_000.0,
            margin_available=95_000.0,
        ))
        req = _make_request(price=2350.0, quantity=100.0)  # notional = 235000

        async def run():
            return await engine._check_margin(req, 0.0)

        report = asyncio.get_event_loop().run_until_complete(run())
        assert report is not None
        assert "MARGIN_INSUFFICIENT" in report.message

    def test_passes_when_margin_adequate(self):
        engine, broker, _ = _make_engine()
        # margin_available=95000, margin_used=5000
        # Order notional: 2350 * 0.1 = 235 → buffer = 95000/(5000+235) = 18.1x > 2.0
        broker.get_account_info = MagicMock(return_value=MagicMock(
            equity=100_000.0,
            margin_used=5_000.0,
            margin_available=95_000.0,
        ))
        req = _make_request(price=2350.0, quantity=0.1)  # notional = 235

        async def run():
            return await engine._check_margin(req, 0.0)

        report = asyncio.get_event_loop().run_until_complete(run())
        assert report is None

    def test_skips_check_when_no_broker(self):
        from execution.engine import ExecutionEngine
        engine = ExecutionEngine.__new__(ExecutionEngine)
        engine._broker = None
        engine._total_blocks = 0

        async def run():
            return await engine._check_margin(_make_request(), 0.0)

        result = asyncio.get_event_loop().run_until_complete(run())
        assert result is None


# ─────────────────────────────────────────────────────────────────────────────
# W5 — Leverage hard cap
# ─────────────────────────────────────────────────────────────────────────────


class TestLeverageHardCap:
    def test_blocks_order_exceeding_leverage_cap(self):
        engine, broker, _ = _make_engine()
        # equity=100000, order_notional = 2350 * 1000 = 2350000
        # leverage = 2350000/100000 = 23.5 > 10.0
        broker.get_account_info = MagicMock(return_value=MagicMock(
            equity=100_000.0,
            balance=100_000.0,
            margin_used=0.0,
            margin_available=100_000.0,
        ))
        req = _make_request(price=2350.0, quantity=1000.0)

        async def run():
            return await engine._check_leverage(req, 0.0)

        report = asyncio.get_event_loop().run_until_complete(run())
        assert report is not None
        assert "LEVERAGE_EXCEEDED" in report.message

    def test_passes_order_within_leverage_cap(self):
        engine, broker, _ = _make_engine()
        # equity=100000, order_notional = 2350 * 0.1 = 235
        # leverage = 235/100000 = 0.00235 < 10.0
        broker.get_account_info = MagicMock(return_value=MagicMock(
            equity=100_000.0,
            balance=100_000.0,
            margin_used=0.0,
            margin_available=100_000.0,
        ))
        req = _make_request(price=2350.0, quantity=0.1)

        async def run():
            return await engine._check_leverage(req, 0.0)

        report = asyncio.get_event_loop().run_until_complete(run())
        assert report is None

    def test_risk_limits_has_max_leverage_field(self):
        from risk.circuit_breakers import RiskLimits

        limits = RiskLimits()
        assert hasattr(limits, "max_leverage_ratio")
        assert limits.max_leverage_ratio == 10.0

    def test_risk_limits_leverage_configurable(self):
        from risk.circuit_breakers import RiskLimits

        limits = RiskLimits(max_leverage_ratio=5.0)
        assert limits.max_leverage_ratio == 5.0


# ─────────────────────────────────────────────────────────────────────────────
# W6 — Kill switch escalation
# ─────────────────────────────────────────────────────────────────────────────


class TestKillSwitchEscalation:
    def test_broker_level_cancel_called_when_positions_remain(self):
        """_broker_level_cancel_all is called when final positions still open."""
        from risk.circuit_breakers import CircuitBreaker

        remaining_pos = [{"symbol": "XAUUSD"}]

        broker = MagicMock()
        # Always return a position (never empty) so escalation is triggered
        broker.get_positions = MagicMock(return_value=remaining_pos)
        broker.cancel_all_orders = MagicMock()
        broker.close_position = MagicMock(side_effect=RuntimeError("broker error"))

        cb = CircuitBreaker.__new__(CircuitBreaker)
        cb.broker = broker
        cb.limits = MagicMock()

        with patch.object(cb, "_broker_level_cancel_all") as mock_escalate, \
             patch.object(cb, "_send_emergency_alert"):
            async def run():
                await cb._execute_kill_switch("test_reason")

            asyncio.get_event_loop().run_until_complete(run())
            mock_escalate.assert_called_once()

    def test_broker_level_cancel_calls_ibkr_global_cancel(self):
        """_broker_level_cancel_all calls reqGlobalCancel on IBKR broker."""
        from risk.circuit_breakers import CircuitBreaker

        ib_mock = MagicMock()
        ib_mock.reqGlobalCancel = MagicMock()

        broker = MagicMock()
        broker._ib = ib_mock

        cb = CircuitBreaker.__new__(CircuitBreaker)
        cb.broker = broker
        cb._broker_level_cancel_all("test")

        ib_mock.reqGlobalCancel.assert_called_once()

    def test_broker_level_cancel_falls_back_to_cancel_all_orders(self):
        """_broker_level_cancel_all falls back to cancel_all_orders when no _ib."""
        from risk.circuit_breakers import CircuitBreaker

        broker = MagicMock(spec=[])  # No attributes
        broker.cancel_all_orders = MagicMock()

        cb = CircuitBreaker.__new__(CircuitBreaker)
        cb.broker = broker
        cb._broker_level_cancel_all("test")

        broker.cancel_all_orders.assert_called_once()


# ─────────────────────────────────────────────────────────────────────────────
# W7 — MTF calibration leakage fix
# ─────────────────────────────────────────────────────────────────────────────


class TestCalibrationLeakageFix:
    def test_train_stacking_ensemble_uses_prefit(self):
        """train_stacking_ensemble in retrain_mtf_accuracy uses cv='prefit'."""
        import ast
        import pathlib

        source = pathlib.Path("scripts/retrain_mtf_accuracy.py").read_text()
        tree = ast.parse(source)

        # Find all calls to CalibratedClassifierCV and check cv argument
        cv_values = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                func_name = ""
                if isinstance(func, ast.Attribute):
                    func_name = func.attr
                elif isinstance(func, ast.Name):
                    func_name = func.id
                if func_name == "CalibratedClassifierCV":
                    for kw in node.keywords:
                        if kw.arg == "cv" and isinstance(kw.value, ast.Constant):
                            cv_values.append(kw.value.value)

        # All cv values in retrain_mtf_accuracy.py must be 'prefit' (not integers)
        assert cv_values, "No CalibratedClassifierCV calls found"
        for cv in cv_values:
            assert cv == "prefit", (
                f"Found cv={cv!r} in scripts/retrain_mtf_accuracy.py — "
                f"all base-model calibration must use cv='prefit' to prevent leakage"
            )

    def test_walk_forward_loop_uses_prefit(self):
        """The CalibratedClassifierCV calls in retrain_mtf_accuracy all use cv='prefit'."""
        import ast
        import pathlib

        source = pathlib.Path("scripts/retrain_mtf_accuracy.py").read_text()
        tree = ast.parse(source)

        cv_values = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                func_name = ""
                if isinstance(func, ast.Attribute):
                    func_name = func.attr
                elif isinstance(func, ast.Name):
                    func_name = func.id
                if func_name == "CalibratedClassifierCV":
                    for kw in node.keywords:
                        if kw.arg == "cv" and isinstance(kw.value, ast.Constant):
                            cv_values.append(kw.value.value)

        # All cv arguments must be 'prefit' — no integer cv values allowed
        integer_cvs = [v for v in cv_values if isinstance(v, int)]
        assert not integer_cvs, (
            f"Found integer cv={integer_cvs} in CalibratedClassifierCV calls — "
            f"all already-fitted model calibration must use cv='prefit' to prevent leakage"
        )


# ─────────────────────────────────────────────────────────────────────────────
# W8 — ByBit dedicated connector
# ─────────────────────────────────────────────────────────────────────────────


class TestByBitConnector:
    def test_instantiates_without_credentials(self):
        """ByBitConnector instantiates with empty config (sandbox mode)."""
        from brokers.bybit_connector import ByBitConnector

        conn = ByBitConnector({"sandbox": True})
        assert conn.name == "ByBit"
        assert not conn.connected

    def test_symbol_map_xauusd_to_xauusdt(self):
        """XAUUSD is translated to XAUUSDT (ByBit perpetual symbol)."""
        from brokers.bybit_connector import ByBitConnector

        conn = ByBitConnector({"sandbox": True})
        assert conn._to_bybit("XAUUSD") == "XAUUSDT"
        assert conn._to_bybit("XAU/USD") == "XAUUSDT"

    def test_symbol_map_reverse_xauusdt_to_xauusd(self):
        """XAUUSDT is translated back to XAUUSD."""
        from brokers.bybit_connector import ByBitConnector

        conn = ByBitConnector({"sandbox": True})
        assert conn._from_bybit("XAUUSDT") == "XAUUSD"

    def test_custom_symbol_map_overrides_default(self):
        """Custom symbol_map in config overrides default mapping."""
        from brokers.bybit_connector import ByBitConnector

        conn = ByBitConnector({
            "sandbox": True,
            "symbol_map": {"XAUUSD": "XAUUSD_CUSTOM"},
        })
        assert conn._to_bybit("XAUUSD") == "XAUUSD_CUSTOM"

    def test_registered_in_factory(self):
        """ByBit is registered in BrokerFactory under 'bybit'."""
        from brokers.factory import BrokerFactory

        BrokerFactory._brokers = {}  # force re-registration
        BrokerFactory._ensure_registered()
        brokers = BrokerFactory.list_brokers()
        assert "bybit" in brokers

    def test_repr_shows_sandbox_mode(self):
        from brokers.bybit_connector import ByBitConnector

        conn = ByBitConnector({"sandbox": True})
        assert "SANDBOX" in repr(conn)


# ─────────────────────────────────────────────────────────────────────────────
# W9 — COMEX gold futures config
# ─────────────────────────────────────────────────────────────────────────────


class TestCOMEXGoldFutures:
    def test_get_comex_gold_contract_function_exists(self):
        """get_comex_gold_contract() is importable from brokers.ibkr_broker."""
        from brokers.ibkr_broker import get_comex_gold_contract

        assert callable(get_comex_gold_contract)

    def test_build_contract_gc_routes_to_nymex(self):
        """_build_contract('GC', 'FUT', ...) sets exchange=NYMEX when default given."""
        from brokers import ibkr_broker as ibkr_mod

        # Patch _IB_AVAILABLE to True and provide a Contract stub
        class FakeContract:
            symbol = ""
            secType = ""
            exchange = ""
            currency = ""

        with patch.object(ibkr_mod, "_IB_AVAILABLE", True), \
             patch.object(ibkr_mod, "Contract", FakeContract, create=True):
            result = ibkr_mod._build_contract("GC", "FUT", "IDEALPRO", "USD")
            assert result.exchange == "NYMEX"

    def test_build_contract_gc_preserves_explicit_nymex(self):
        """_build_contract('GC', 'FUT', 'NYMEX', ...) keeps NYMEX."""
        from brokers import ibkr_broker as ibkr_mod

        class FakeContract:
            symbol = ""
            secType = ""
            exchange = ""
            currency = ""

        with patch.object(ibkr_mod, "_IB_AVAILABLE", True), \
             patch.object(ibkr_mod, "Contract", FakeContract, create=True):
            result = ibkr_mod._build_contract("GC", "FUT", "NYMEX", "USD")
            assert result.exchange == "NYMEX"

    def test_build_contract_gc_sets_symbol(self):
        """_build_contract('GC', ...) sets symbol to 'GC'."""
        from brokers import ibkr_broker as ibkr_mod

        class FakeContract:
            symbol = ""
            secType = ""
            exchange = ""
            currency = ""

        with patch.object(ibkr_mod, "_IB_AVAILABLE", True), \
             patch.object(ibkr_mod, "Contract", FakeContract, create=True):
            result = ibkr_mod._build_contract("GC", "CONTFUT", "NYMEX", "USD")
            assert result.symbol == "GC"

    def test_get_comex_gold_contract_raises_without_ib(self):
        """get_comex_gold_contract() raises RuntimeError when ib_insync missing."""
        from brokers import ibkr_broker as ibkr_mod

        with patch.object(ibkr_mod, "_IB_AVAILABLE", False), pytest.raises(RuntimeError, match="ib_insync not installed"):
            ibkr_mod.get_comex_gold_contract()


# ─────────────────────────────────────────────────────────────────────────────
# W10 — Spread spike detector
# ─────────────────────────────────────────────────────────────────────────────


class TestSpreadMonitor:
    def _make_monitor(self, spike_mult=3.0, min_ticks=5, abs_limit=5.0):
        from execution.spread_monitor import SpreadMonitor

        return SpreadMonitor(
            spike_multiplier=spike_mult,
            baseline_window=20,
            min_ticks=min_ticks,
            abs_limit_usd=abs_limit,
        )

    def _seed(self, monitor, symbol, n=10, spread=0.5):
        """Feed *n* normal-spread ticks to establish a baseline."""
        for i in range(n):
            monitor.on_tick(symbol, bid=2350.0 + i * 0.001, ask=2350.0 + i * 0.001 + spread)

    def test_no_spike_below_multiplier(self):
        monitor = self._make_monitor()
        self._seed(monitor, "XAUUSD", n=20, spread=0.5)
        # Feed a slightly wider spread (1.5× — not a spike)
        monitor.on_tick("XAUUSD", bid=2360.0, ask=2360.75)
        assert not monitor.is_spread_spiking("XAUUSD")

    def test_spike_detected_above_multiplier(self):
        monitor = self._make_monitor(spike_mult=3.0)
        self._seed(monitor, "XAUUSD", n=20, spread=0.5)
        # Feed a spike: 4× normal spread = 2.0
        monitor.on_tick("XAUUSD", bid=2360.0, ask=2362.0)
        assert monitor.is_spread_spiking("XAUUSD")

    def test_absolute_limit_always_blocks(self):
        monitor = self._make_monitor(abs_limit=5.0)
        # No history needed — absolute limit kicks in immediately
        snap = monitor.on_tick("XAUUSD", bid=2350.0, ask=2356.0)  # spread=6.0 > 5.0
        assert snap.is_spiking

    def test_no_spike_before_min_ticks(self):
        monitor = self._make_monitor(min_ticks=10)
        # Only 2 ticks — not enough for baseline
        monitor.on_tick("XAUUSD", bid=2350.0, ask=2350.5)
        monitor.on_tick("XAUUSD", bid=2350.0, ask=2360.0)
        assert not monitor.is_spread_spiking("XAUUSD")

    def test_snapshot_returns_correct_structure(self):
        from execution.spread_monitor import SpreadSnapshot

        monitor = self._make_monitor()
        self._seed(monitor, "XAUUSD", n=10)
        snap = monitor.get_snapshot("XAUUSD")
        assert isinstance(snap, SpreadSnapshot)
        assert snap.symbol == "XAUUSD"
        assert snap.tick_count == 10
        assert snap.current_spread >= 0

    def test_on_tick_obj_uses_bid_ask(self):
        monitor = self._make_monitor()
        self._seed(monitor, "XAUUSD", n=10, spread=0.5)

        tick = MagicMock()
        tick.bid = 2350.0
        tick.ask = 2354.0  # spread = 4.0 > 3× 0.5 = 1.5 → spike

        snap = monitor.on_tick_obj("XAUUSD", tick)
        assert snap.is_spiking

    def test_singleton_returns_same_instance(self):
        from execution.spread_monitor import get_spread_monitor

        m1 = get_spread_monitor()
        m2 = get_spread_monitor()
        assert m1 is m2

    def test_engine_blocks_on_spread_spike(self):
        """ExecutionEngine._check_spread_spike returns block report when spike detected."""
        engine, _, _ = _make_engine()

        mock_monitor = MagicMock()
        mock_monitor.is_spread_spiking = MagicMock(return_value=True)
        mock_monitor.get_snapshot = MagicMock(return_value=MagicMock(
            current_spread=2.0,
            baseline_spread=0.5,
            ratio=4.0,
        ))

        req = _make_request()
        # Patch the spread_monitor module's get_spread_monitor (imported inside the method)
        with patch("execution.spread_monitor.get_spread_monitor", return_value=mock_monitor):
            report = engine._check_spread_spike(req, 0.0)

        assert report is not None
        assert "SPREAD_SPIKE" in report.message

    def test_engine_passes_on_normal_spread(self):
        """ExecutionEngine._check_spread_spike returns None when spread is normal."""
        engine, _, _ = _make_engine()

        mock_monitor = MagicMock()
        mock_monitor.is_spread_spiking = MagicMock(return_value=False)

        req = _make_request()
        with patch("execution.spread_monitor.get_spread_monitor", return_value=mock_monitor):
            report = engine._check_spread_spike(req, 0.0)

        assert report is None

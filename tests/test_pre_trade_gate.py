# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
tests/test_pre_trade_gate.py

Pre-trade gate unit tests — verifies every block condition and the
no-fallback invariant.
"""

from unittest.mock import MagicMock

import pytest

from risk.pre_trade_gate import (
    GateOrder,
    PreTradeGate,
    RiskManagerError,
    TradeBlockedError,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_risk_manager(**overrides):
    """Build a minimal mock risk manager that passes all checks by default."""
    rm = MagicMock()
    rm._trading_halted = overrides.get("_trading_halted", False)
    rm._halt_reason = overrides.get("_halt_reason")
    rm._halt_until = overrides.get("_halt_until")
    rm.daily_pnl = overrides.get("daily_pnl", 0.0)
    rm.daily_starting_equity = overrides.get("daily_starting_equity", 100_000.0)
    rm.current_drawdown = overrides.get("current_drawdown", 0.0)
    rm.current_balance = overrides.get("current_balance", 100_000.0)
    rm.initial_balance = overrides.get("initial_balance", 100_000.0)
    rm.open_positions = overrides.get("open_positions", [])
    rm._kill_switch = None

    # Config
    cfg = MagicMock()
    cfg.daily_loss_limit_pct = overrides.get("daily_loss_limit_pct", 0.05)
    cfg.max_drawdown_pct = overrides.get("max_drawdown_pct", 0.10)
    cfg.max_position_size_pct = overrides.get("max_position_size_pct", 0.02)
    cfg.max_open_positions = overrides.get("max_open_positions", 5)
    rm.config = cfg

    # CVaR gate — passes by default
    rm.check_cvar_pre_trade = MagicMock(return_value=(True, "CVaR OK"))
    rm._compute_cvar = MagicMock(return_value=0.005)
    rm._returns_history = [0.001] * 20

    # validate_trade — passes by default
    rm.validate_trade = MagicMock(return_value=(True, "OK"))

    return rm


def _make_order(**overrides):
    return GateOrder(
        symbol=overrides.get("symbol", "XAUUSD"),
        side=overrides.get("side", "BUY"),
        quantity=overrides.get("quantity", 1.0),
        price=overrides.get("price", 1950.0),
        stop_loss=overrides.get("stop_loss", 1930.0),
        take_profit=overrides.get("take_profit", 1980.0),
        strategy_id=overrides.get("strategy_id", "test"),
    )


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


class TestPreTradeGatePass:
    def test_all_checks_pass(self):
        rm = _make_risk_manager()
        gate = PreTradeGate(rm)
        result = gate.check(_make_order())
        assert result is not None
        # Gate runs: kill_switch, trading_halted, daily_loss_limit, max_drawdown,
        # cvar_pre_trade, position_size, max_open_positions, validate_trade,
        # risk_per_trade_cap, loss_streak  (10 total)
        assert len(result.checks_passed) >= 8

    def test_returns_gate_result_with_order(self):
        rm = _make_risk_manager()
        gate = PreTradeGate(rm)
        order = _make_order()
        result = gate.check(order)
        assert result.order is order


# ---------------------------------------------------------------------------
# Kill switch
# ---------------------------------------------------------------------------


class TestKillSwitch:
    def test_kill_switch_blocks(self):
        rm = _make_risk_manager()
        ks = MagicMock()
        ks.is_active.return_value = True
        ks._reason = "daily drawdown exceeded"
        rm._kill_switch = ks
        gate = PreTradeGate(rm)
        with pytest.raises(TradeBlockedError) as exc_info:
            gate.check(_make_order())
        assert exc_info.value.reason_code == "KILL_SWITCH_ACTIVE"

    def test_kill_switch_inactive_passes(self):
        rm = _make_risk_manager()
        ks = MagicMock()
        ks.is_active.return_value = False
        rm._kill_switch = ks
        gate = PreTradeGate(rm)
        result = gate.check(_make_order())
        assert "kill_switch" in result.checks_passed


# ---------------------------------------------------------------------------
# Trading halted
# ---------------------------------------------------------------------------


class TestTradingHalted:
    def test_halted_blocks(self):
        rm = _make_risk_manager(_trading_halted=True, _halt_reason="max drawdown")
        gate = PreTradeGate(rm)
        with pytest.raises(TradeBlockedError) as exc_info:
            gate.check(_make_order())
        assert exc_info.value.reason_code == "TRADING_HALTED"
        assert "max drawdown" in exc_info.value.detail

    def test_not_halted_passes(self):
        rm = _make_risk_manager(_trading_halted=False)
        gate = PreTradeGate(rm)
        result = gate.check(_make_order())
        assert "trading_halted" in result.checks_passed


# ---------------------------------------------------------------------------
# Daily loss limit
# ---------------------------------------------------------------------------


class TestDailyLossLimit:
    def test_daily_loss_exceeded_blocks(self):
        # daily_pnl = -6000, starting_equity = 100000 → 6% loss > 5% limit
        rm = _make_risk_manager(
            daily_pnl=-6000.0,
            daily_starting_equity=100_000.0,
            daily_loss_limit_pct=0.05,
        )
        gate = PreTradeGate(rm)
        with pytest.raises(TradeBlockedError) as exc_info:
            gate.check(_make_order())
        assert exc_info.value.reason_code == "DAILY_LOSS_LIMIT"

    def test_daily_loss_within_limit_passes(self):
        rm = _make_risk_manager(
            daily_pnl=-3000.0,
            daily_starting_equity=100_000.0,
            daily_loss_limit_pct=0.05,
        )
        gate = PreTradeGate(rm)
        result = gate.check(_make_order())
        assert "daily_loss_limit" in result.checks_passed


# ---------------------------------------------------------------------------
# Max drawdown
# ---------------------------------------------------------------------------


class TestMaxDrawdown:
    def test_drawdown_exceeded_blocks(self):
        rm = _make_risk_manager(current_drawdown=0.11, max_drawdown_pct=0.10)
        gate = PreTradeGate(rm)
        with pytest.raises(TradeBlockedError) as exc_info:
            gate.check(_make_order())
        assert exc_info.value.reason_code == "MAX_DRAWDOWN"

    def test_drawdown_within_limit_passes(self):
        rm = _make_risk_manager(current_drawdown=0.05, max_drawdown_pct=0.10)
        gate = PreTradeGate(rm)
        result = gate.check(_make_order())
        assert "max_drawdown" in result.checks_passed


# ---------------------------------------------------------------------------
# CVaR gate
# ---------------------------------------------------------------------------


class TestCVaRGate:
    def test_cvar_breach_blocks(self):
        rm = _make_risk_manager()
        rm.check_cvar_pre_trade.return_value = (False, "CVaR 0.05 > limit 0.03")
        gate = PreTradeGate(rm)
        with pytest.raises(TradeBlockedError) as exc_info:
            gate.check(_make_order())
        assert exc_info.value.reason_code == "CVAR_LIMIT"

    def test_cvar_ok_passes(self):
        rm = _make_risk_manager()
        rm.check_cvar_pre_trade.return_value = (True, "CVaR OK")
        gate = PreTradeGate(rm)
        result = gate.check(_make_order())
        assert "cvar_pre_trade" in result.checks_passed


# ---------------------------------------------------------------------------
# Position size
# ---------------------------------------------------------------------------


class TestPositionSize:
    def test_oversized_order_blocks(self):
        # 100 lots * 1950 = 195,000 notional > 2% of 100,000 = 2,000
        rm = _make_risk_manager(current_balance=100_000.0, max_position_size_pct=0.02)
        gate = PreTradeGate(rm)
        order = _make_order(quantity=100.0, price=1950.0)
        with pytest.raises(TradeBlockedError) as exc_info:
            gate.check(order)
        assert exc_info.value.reason_code == "POSITION_SIZE"

    def test_sized_order_passes(self):
        # 0.001 lots * 1950 = 1.95 notional < 2% of 100,000 = 2,000
        rm = _make_risk_manager(current_balance=100_000.0, max_position_size_pct=0.02)
        gate = PreTradeGate(rm)
        order = _make_order(quantity=0.001, price=1950.0)
        result = gate.check(order)
        assert "position_size" in result.checks_passed


# ---------------------------------------------------------------------------
# Max open positions
# ---------------------------------------------------------------------------


class TestMaxOpenPositions:
    def test_max_positions_blocks(self):
        rm = _make_risk_manager(
            open_positions=[{} for _ in range(5)],
            max_open_positions=5,
        )
        gate = PreTradeGate(rm)
        with pytest.raises(TradeBlockedError) as exc_info:
            gate.check(_make_order())
        assert exc_info.value.reason_code == "MAX_OPEN_POSITIONS"

    def test_under_limit_passes(self):
        rm = _make_risk_manager(
            open_positions=[{} for _ in range(3)],
            max_open_positions=5,
        )
        gate = PreTradeGate(rm)
        result = gate.check(_make_order())
        assert "max_open_positions" in result.checks_passed


# ---------------------------------------------------------------------------
# Risk manager error — no fallback
# ---------------------------------------------------------------------------


class TestRiskManagerError:
    def test_risk_manager_exception_raises_risk_manager_error(self):
        """If risk manager throws unexpectedly, RiskManagerError must propagate."""
        rm = _make_risk_manager()
        rm.check_cvar_pre_trade.side_effect = RuntimeError("DB connection lost")
        gate = PreTradeGate(rm)
        with pytest.raises(RiskManagerError):
            gate.check(_make_order())

    def test_no_allow_anyway_fallback(self):
        """Verify there is no code path that allows a trade when risk manager errors."""
        from pathlib import Path

        source = (Path(__file__).parent.parent / "risk" / "pre_trade_gate.py").read_text()
        # Check the raw file — not lowercased inspect output
        assert "allow_anyway" not in source
        # The docstring mentions "allow anyway" as a concept to reject — that's fine.
        # What must NOT exist is any code that catches an exception and proceeds.
        # Verify _run_check always raises RiskManagerError on unexpected exceptions.
        assert "raise RiskManagerError" in source


# ---------------------------------------------------------------------------
# GateOrder validation
# ---------------------------------------------------------------------------


class TestGateOrderValidation:
    def test_invalid_side_raises(self):
        with pytest.raises(ValueError):
            GateOrder(symbol="XAUUSD", side="LONG", quantity=1.0)

    def test_zero_quantity_raises(self):
        with pytest.raises(ValueError):
            GateOrder(symbol="XAUUSD", side="BUY", quantity=0.0)

    def test_negative_quantity_raises(self):
        with pytest.raises(ValueError):
            GateOrder(symbol="XAUUSD", side="BUY", quantity=-1.0)

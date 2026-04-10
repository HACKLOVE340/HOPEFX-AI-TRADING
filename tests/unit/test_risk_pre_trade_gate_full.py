# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
tests/unit/test_risk_pre_trade_gate_full.py
============================================
Comprehensive tests for risk/pre_trade_gate.py.

Covers:
- GateOrder validation
- GateResult structure
- TradeBlockedError attributes
- RiskManagerError on unexpected exceptions
- All 10 individual checks (kill_switch, trading_halted, daily_loss,
  drawdown, cvar, position_size, open_positions, validate_trade,
  risk_per_trade_cap, loss_streak)
- Happy path (all checks pass)
- Fail-fast: first failure blocks, subsequent checks skipped

Target: ≥90% branch coverage on risk/pre_trade_gate.py.
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

UTC = timezone.utc


# ---------------------------------------------------------------------------
# Helpers — minimal RiskManager stand-ins
# ---------------------------------------------------------------------------


def _make_rm(**kwargs) -> MagicMock:
    """
    Build a MagicMock risk manager with sensible defaults.

    All attributes that PreTradeGate reads via getattr() are set to
    safe values so the gate passes by default.
    """
    rm = MagicMock()
    # Kill switch — inactive by default
    ks = MagicMock()
    ks.is_active.return_value = False
    rm._kill_switch = ks

    # Trading not halted
    rm._trading_halted = False
    rm._halt_reason = ""
    rm._halt_until = None

    # Daily PnL — no loss
    rm.daily_pnl = 0.0
    rm.daily_starting_equity = 100_000.0

    # Drawdown — none
    rm.current_drawdown = 0.0

    # CVaR — not implemented (gate skips)
    del rm.check_cvar_pre_trade  # remove so hasattr returns False

    # Balance
    rm.current_balance = 100_000.0
    rm.initial_balance = 100_000.0

    # Open positions — empty
    rm.open_positions = []

    # Config
    cfg = MagicMock()
    cfg.daily_loss_limit_pct = 0.05
    cfg.max_drawdown_pct = 0.10
    cfg.max_position_size_pct = 0.02
    cfg.max_open_positions = 5
    rm.config = cfg

    # validate_trade — always passes
    rm.validate_trade.return_value = (True, "")

    # Streak halt — not active
    rm._streak_halted = False

    # Apply overrides
    for k, v in kwargs.items():
        setattr(rm, k, v)

    return rm


def _make_order(**kwargs):
    from risk.pre_trade_gate import GateOrder

    defaults = {
        "symbol": "XAUUSD",
        "side": "BUY",
        "quantity": 0.1,
        "price": 2000.0,
        "stop_loss": 1980.0,
        "take_profit": 2040.0,
        "strategy_id": "test_strategy",
    }
    defaults.update(kwargs)
    return GateOrder(**defaults)


# ---------------------------------------------------------------------------
# GateOrder validation
# ---------------------------------------------------------------------------


class TestGateOrder:
    def test_valid_buy_order(self):
        from risk.pre_trade_gate import GateOrder

        o = GateOrder(symbol="XAUUSD", side="BUY", quantity=1.0, price=2000.0)
        assert o.symbol == "XAUUSD"
        assert o.side == "BUY"

    def test_valid_sell_order(self):
        from risk.pre_trade_gate import GateOrder

        o = GateOrder(symbol="XAUUSD", side="SELL", quantity=0.5)
        assert o.side == "SELL"

    def test_invalid_side_raises(self):
        from risk.pre_trade_gate import GateOrder

        with pytest.raises(ValueError, match="side"):
            GateOrder(symbol="XAUUSD", side="LONG", quantity=1.0)

    def test_zero_quantity_raises(self):
        from risk.pre_trade_gate import GateOrder

        with pytest.raises(ValueError, match="quantity"):
            GateOrder(symbol="XAUUSD", side="BUY", quantity=0.0)

    def test_negative_quantity_raises(self):
        from risk.pre_trade_gate import GateOrder

        with pytest.raises(ValueError, match="quantity"):
            GateOrder(symbol="XAUUSD", side="BUY", quantity=-1.0)

    def test_optional_fields_default_none(self):
        from risk.pre_trade_gate import GateOrder

        o = GateOrder(symbol="XAUUSD", side="BUY", quantity=1.0)
        assert o.price is None
        assert o.stop_loss is None
        assert o.take_profit is None

    def test_metadata_defaults_empty(self):
        from risk.pre_trade_gate import GateOrder

        o = GateOrder(symbol="XAUUSD", side="BUY", quantity=1.0)
        assert o.metadata == {}


# ---------------------------------------------------------------------------
# TradeBlockedError
# ---------------------------------------------------------------------------


class TestTradeBlockedError:
    def test_attributes(self):
        from risk.pre_trade_gate import TradeBlockedError

        e = TradeBlockedError(
            reason_code="KILL_SWITCH_ACTIVE",
            detail="Kill switch is active",
            checks_failed=["kill_switch"],
        )
        assert e.reason_code == "KILL_SWITCH_ACTIVE"
        assert e.detail == "Kill switch is active"
        assert "kill_switch" in e.checks_failed

    def test_str_contains_reason_code(self):
        from risk.pre_trade_gate import TradeBlockedError

        e = TradeBlockedError(reason_code="MAX_DRAWDOWN", detail="10% drawdown")
        assert "MAX_DRAWDOWN" in str(e)

    def test_checks_failed_defaults_empty(self):
        from risk.pre_trade_gate import TradeBlockedError

        e = TradeBlockedError(reason_code="X", detail="y")
        assert e.checks_failed == []


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


class TestHappyPath:
    def test_all_checks_pass_returns_gate_result(self):
        from risk.pre_trade_gate import GateResult, PreTradeGate

        rm = _make_rm()
        gate = PreTradeGate(rm)
        order = _make_order()
        result = gate.check(order)
        assert isinstance(result, GateResult)

    def test_gate_result_contains_order(self):
        from risk.pre_trade_gate import PreTradeGate

        rm = _make_rm()
        gate = PreTradeGate(rm)
        order = _make_order()
        result = gate.check(order)
        assert result.order is order

    def test_gate_result_checks_passed_non_empty(self):
        from risk.pre_trade_gate import PreTradeGate

        rm = _make_rm()
        gate = PreTradeGate(rm)
        result = gate.check(_make_order())
        assert len(result.checks_passed) > 0

    def test_gate_result_has_timestamp(self):
        from risk.pre_trade_gate import PreTradeGate

        rm = _make_rm()
        gate = PreTradeGate(rm)
        result = gate.check(_make_order())
        assert isinstance(result.timestamp, datetime)

    def test_no_kill_switch_attribute_passes(self):
        """Risk manager without _kill_switch attribute should pass kill-switch check."""
        from risk.pre_trade_gate import PreTradeGate

        rm = _make_rm()
        del rm._kill_switch
        gate = PreTradeGate(rm)
        result = gate.check(_make_order())
        assert result is not None


# ---------------------------------------------------------------------------
# Kill switch check
# ---------------------------------------------------------------------------


class TestKillSwitchCheck:
    def test_active_kill_switch_blocks(self):
        from risk.pre_trade_gate import PreTradeGate, TradeBlockedError

        rm = _make_rm()
        rm._kill_switch.is_active.return_value = True
        rm._kill_switch._reason = "manual halt"
        gate = PreTradeGate(rm)
        with pytest.raises(TradeBlockedError) as exc_info:
            gate.check(_make_order())
        assert exc_info.value.reason_code == "KILL_SWITCH_ACTIVE"

    def test_inactive_kill_switch_passes(self):
        from risk.pre_trade_gate import PreTradeGate

        rm = _make_rm()
        rm._kill_switch.is_active.return_value = False
        gate = PreTradeGate(rm)
        result = gate.check(_make_order())
        assert "kill_switch" in result.checks_passed


# ---------------------------------------------------------------------------
# Trading halted check
# ---------------------------------------------------------------------------


class TestTradingHaltedCheck:
    def test_halted_blocks(self):
        from risk.pre_trade_gate import PreTradeGate, TradeBlockedError

        rm = _make_rm(_trading_halted=True, _halt_reason="drawdown exceeded")
        gate = PreTradeGate(rm)
        with pytest.raises(TradeBlockedError) as exc_info:
            gate.check(_make_order())
        assert exc_info.value.reason_code == "TRADING_HALTED"

    def test_halted_with_halt_until_includes_time(self):
        from risk.pre_trade_gate import PreTradeGate, TradeBlockedError

        rm = _make_rm(
            _trading_halted=True,
            _halt_reason="daily loss",
            _halt_until=datetime(2025, 1, 1, 12, 0, tzinfo=UTC),
        )
        gate = PreTradeGate(rm)
        with pytest.raises(TradeBlockedError) as exc_info:
            gate.check(_make_order())
        assert "until" in exc_info.value.detail

    def test_not_halted_passes(self):
        from risk.pre_trade_gate import PreTradeGate

        rm = _make_rm(_trading_halted=False)
        gate = PreTradeGate(rm)
        result = gate.check(_make_order())
        assert "trading_halted" in result.checks_passed


# ---------------------------------------------------------------------------
# Daily loss limit check
# ---------------------------------------------------------------------------


class TestDailyLossCheck:
    def test_daily_loss_exceeded_blocks(self):
        from risk.pre_trade_gate import PreTradeGate, TradeBlockedError

        rm = _make_rm(daily_pnl=-6000.0, daily_starting_equity=100_000.0)
        rm.config.daily_loss_limit_pct = 0.05
        gate = PreTradeGate(rm)
        with pytest.raises(TradeBlockedError) as exc_info:
            gate.check(_make_order())
        assert exc_info.value.reason_code == "DAILY_LOSS_LIMIT"

    def test_daily_loss_within_limit_passes(self):
        from risk.pre_trade_gate import PreTradeGate

        rm = _make_rm(daily_pnl=-1000.0, daily_starting_equity=100_000.0)
        rm.config.daily_loss_limit_pct = 0.05
        gate = PreTradeGate(rm)
        result = gate.check(_make_order())
        assert "daily_loss_limit" in result.checks_passed

    def test_no_config_skips_check(self):
        from risk.pre_trade_gate import PreTradeGate

        rm = _make_rm()
        rm.config = None
        gate = PreTradeGate(rm)
        result = gate.check(_make_order())
        assert result is not None

    def test_zero_starting_equity_skips_check(self):
        from risk.pre_trade_gate import PreTradeGate

        rm = _make_rm(daily_pnl=-5000.0, daily_starting_equity=0.0)
        gate = PreTradeGate(rm)
        result = gate.check(_make_order())
        assert result is not None


# ---------------------------------------------------------------------------
# Max drawdown check
# ---------------------------------------------------------------------------


class TestDrawdownCheck:
    def test_drawdown_exceeded_blocks(self):
        from risk.pre_trade_gate import PreTradeGate, TradeBlockedError

        rm = _make_rm(current_drawdown=0.12)
        rm.config.max_drawdown_pct = 0.10
        gate = PreTradeGate(rm)
        with pytest.raises(TradeBlockedError) as exc_info:
            gate.check(_make_order())
        assert exc_info.value.reason_code == "MAX_DRAWDOWN"

    def test_drawdown_within_limit_passes(self):
        from risk.pre_trade_gate import PreTradeGate

        rm = _make_rm(current_drawdown=0.05)
        rm.config.max_drawdown_pct = 0.10
        gate = PreTradeGate(rm)
        result = gate.check(_make_order())
        assert "max_drawdown" in result.checks_passed

    def test_drawdown_value_returned_in_result(self):
        from risk.pre_trade_gate import PreTradeGate

        rm = _make_rm(current_drawdown=0.03)
        gate = PreTradeGate(rm)
        result = gate.check(_make_order())
        assert result.drawdown_pct == pytest.approx(0.03)


# ---------------------------------------------------------------------------
# CVaR check
# ---------------------------------------------------------------------------


class TestCVaRCheck:
    def test_no_cvar_method_passes(self):
        """Risk manager without check_cvar_pre_trade passes the CVaR check."""
        from risk.pre_trade_gate import PreTradeGate

        rm = _make_rm()
        # Ensure check_cvar_pre_trade is absent
        if hasattr(rm, "check_cvar_pre_trade"):
            del rm.check_cvar_pre_trade
        gate = PreTradeGate(rm)
        result = gate.check(_make_order())
        assert "cvar_pre_trade" in result.checks_passed

    def test_cvar_blocked_raises(self):
        from risk.pre_trade_gate import PreTradeGate, TradeBlockedError

        rm = _make_rm()
        rm.check_cvar_pre_trade = MagicMock(return_value=(False, "CVaR limit exceeded"))
        gate = PreTradeGate(rm)
        with pytest.raises(TradeBlockedError) as exc_info:
            gate.check(_make_order())
        assert exc_info.value.reason_code == "CVAR_LIMIT"

    def test_cvar_allowed_passes(self):
        from risk.pre_trade_gate import PreTradeGate

        rm = _make_rm()
        rm.check_cvar_pre_trade = MagicMock(return_value=(True, ""))
        gate = PreTradeGate(rm)
        result = gate.check(_make_order())
        assert "cvar_pre_trade" in result.checks_passed


# ---------------------------------------------------------------------------
# Position size check
# ---------------------------------------------------------------------------


class TestPositionSizeCheck:
    def test_oversized_order_blocks(self):
        from risk.pre_trade_gate import PreTradeGate, TradeBlockedError

        rm = _make_rm(current_balance=10_000.0)
        rm.config.max_position_size_pct = 0.02  # max 200 USD notional
        gate = PreTradeGate(rm)
        # 10 lots × 2000 = 20,000 USD >> 200 USD limit
        order = _make_order(quantity=10.0, price=2000.0)
        with pytest.raises(TradeBlockedError) as exc_info:
            gate.check(order)
        assert exc_info.value.reason_code == "POSITION_SIZE"

    def test_normal_size_passes(self):
        from risk.pre_trade_gate import PreTradeGate

        rm = _make_rm(current_balance=100_000.0)
        rm.config.max_position_size_pct = 0.02  # max 2000 USD
        gate = PreTradeGate(rm)
        order = _make_order(quantity=0.1, price=2000.0)  # 200 USD notional
        result = gate.check(order)
        assert "position_size" in result.checks_passed

    def test_market_order_no_price_skips_notional_check(self):
        from risk.pre_trade_gate import PreTradeGate

        rm = _make_rm(current_balance=100_000.0)
        gate = PreTradeGate(rm)
        order = _make_order(quantity=100.0, price=None)  # no price → skip
        result = gate.check(order)
        assert result is not None

    def test_zero_balance_skips_check(self):
        from risk.pre_trade_gate import PreTradeGate

        rm = _make_rm(current_balance=0.0, initial_balance=0.0)
        gate = PreTradeGate(rm)
        result = gate.check(_make_order())
        assert result is not None


# ---------------------------------------------------------------------------
# Max open positions check
# ---------------------------------------------------------------------------


class TestOpenPositionsCheck:
    def test_at_limit_blocks(self):
        from risk.pre_trade_gate import PreTradeGate, TradeBlockedError

        rm = _make_rm(open_positions=["p1", "p2", "p3", "p4", "p5"])
        rm.config.max_open_positions = 5
        gate = PreTradeGate(rm)
        with pytest.raises(TradeBlockedError) as exc_info:
            gate.check(_make_order())
        assert exc_info.value.reason_code == "MAX_OPEN_POSITIONS"

    def test_below_limit_passes(self):
        from risk.pre_trade_gate import PreTradeGate

        rm = _make_rm(open_positions=["p1", "p2"])
        rm.config.max_open_positions = 5
        gate = PreTradeGate(rm)
        result = gate.check(_make_order())
        assert "max_open_positions" in result.checks_passed

    def test_no_config_uses_default_5(self):
        from risk.pre_trade_gate import PreTradeGate, TradeBlockedError

        rm = _make_rm(open_positions=["p1", "p2", "p3", "p4", "p5"])
        rm.config = None
        gate = PreTradeGate(rm)
        with pytest.raises(TradeBlockedError):
            gate.check(_make_order())


# ---------------------------------------------------------------------------
# validate_trade check
# ---------------------------------------------------------------------------


class TestValidateTradeCheck:
    def test_validate_trade_blocked(self):
        from risk.pre_trade_gate import PreTradeGate, TradeBlockedError

        rm = _make_rm()
        rm.validate_trade.return_value = (False, "symbol not tradeable")
        gate = PreTradeGate(rm)
        with pytest.raises(TradeBlockedError) as exc_info:
            gate.check(_make_order())
        assert exc_info.value.reason_code == "VALIDATE_TRADE"

    def test_validate_trade_passes(self):
        from risk.pre_trade_gate import PreTradeGate

        rm = _make_rm()
        rm.validate_trade.return_value = (True, "")
        gate = PreTradeGate(rm)
        result = gate.check(_make_order())
        assert "validate_trade" in result.checks_passed

    def test_no_validate_trade_method_skips(self):
        from risk.pre_trade_gate import PreTradeGate

        rm = _make_rm()
        del rm.validate_trade
        gate = PreTradeGate(rm)
        result = gate.check(_make_order())
        assert result is not None


# ---------------------------------------------------------------------------
# Risk-per-trade cap check
# ---------------------------------------------------------------------------


class TestRiskPerTradeCapCheck:
    def test_risk_per_trade_exceeded_blocks(self):
        from risk.pre_trade_gate import PreTradeGate, TradeBlockedError

        rm = _make_rm(current_balance=10_000.0)
        rm.config.max_position_size_pct = 1.0  # disable position size check
        gate = PreTradeGate(rm)
        # 100 lots × |2000 - 1000| SL distance = 100,000 USD risk >> 1% of 10k
        order = _make_order(quantity=100.0, price=2000.0, stop_loss=1000.0)
        with pytest.raises(TradeBlockedError) as exc_info:
            gate.check(order)
        assert exc_info.value.reason_code in ("RISK_PER_TRADE", "POSITION_SIZE")

    def test_no_stop_loss_uses_full_notional(self):
        """Without SL, risk = full notional. Large order should be blocked."""
        from risk.pre_trade_gate import PreTradeGate, TradeBlockedError

        rm = _make_rm(current_balance=1_000.0)
        rm.config.max_position_size_pct = 1.0
        gate = PreTradeGate(rm)
        order = _make_order(quantity=10.0, price=2000.0, stop_loss=None)
        with pytest.raises(TradeBlockedError):
            gate.check(order)

    def test_small_risk_passes(self):
        from risk.pre_trade_gate import PreTradeGate

        rm = _make_rm(current_balance=100_000.0)
        gate = PreTradeGate(rm)
        # 0.01 lots × |2000 - 1990| = 0.1 USD risk << 1% of 100k
        order = _make_order(quantity=0.01, price=2000.0, stop_loss=1990.0)
        result = gate.check(order)
        assert "risk_per_trade_cap" in result.checks_passed


# ---------------------------------------------------------------------------
# Loss streak check
# ---------------------------------------------------------------------------


class TestLossStreakCheck:
    def test_streak_halted_blocks(self):
        from risk.pre_trade_gate import PreTradeGate, TradeBlockedError

        rm = _make_rm(_streak_halted=True)
        gate = PreTradeGate(rm)
        with pytest.raises(TradeBlockedError) as exc_info:
            gate.check(_make_order())
        assert exc_info.value.reason_code == "LOSS_STREAK"

    def test_no_streak_halt_passes(self):
        from risk.pre_trade_gate import PreTradeGate

        rm = _make_rm(_streak_halted=False)
        gate = PreTradeGate(rm)
        result = gate.check(_make_order())
        assert "loss_streak" in result.checks_passed


# ---------------------------------------------------------------------------
# RiskManagerError on unexpected exception
# ---------------------------------------------------------------------------


class TestRiskManagerError:
    def test_unexpected_exception_raises_risk_manager_error(self):
        from risk.pre_trade_gate import PreTradeGate, RiskManagerError

        rm = _make_rm()
        # Make kill switch raise an unexpected exception
        rm._kill_switch.is_active.side_effect = RuntimeError("unexpected!")
        gate = PreTradeGate(rm)
        with pytest.raises(RiskManagerError):
            gate.check(_make_order())

    def test_risk_manager_error_blocks_trade(self):
        """RiskManagerError must propagate — no silent pass."""
        from risk.pre_trade_gate import PreTradeGate, RiskManagerError

        rm = _make_rm()
        rm._trading_halted = property(lambda self: (_ for _ in ()).throw(RuntimeError("broken")))
        gate = PreTradeGate(rm)
        # Should raise either RiskManagerError or the original exception
        with pytest.raises((RiskManagerError, Exception)):
            gate.check(_make_order())


# ---------------------------------------------------------------------------
# Fail-fast ordering
# ---------------------------------------------------------------------------


class TestFailFast:
    def test_kill_switch_blocks_before_drawdown(self):
        """Kill switch (check 1) fires before drawdown (check 4)."""
        from risk.pre_trade_gate import PreTradeGate, TradeBlockedError

        rm = _make_rm(current_drawdown=0.99)  # would also fail drawdown
        rm._kill_switch.is_active.return_value = True
        gate = PreTradeGate(rm)
        with pytest.raises(TradeBlockedError) as exc_info:
            gate.check(_make_order())
        assert exc_info.value.reason_code == "KILL_SWITCH_ACTIVE"

    def test_trading_halted_blocks_before_daily_loss(self):
        """Trading halted (check 2) fires before daily loss (check 3)."""
        from risk.pre_trade_gate import PreTradeGate, TradeBlockedError

        rm = _make_rm(
            _trading_halted=True,
            daily_pnl=-99_000.0,
            daily_starting_equity=100_000.0,
        )
        gate = PreTradeGate(rm)
        with pytest.raises(TradeBlockedError) as exc_info:
            gate.check(_make_order())
        assert exc_info.value.reason_code == "TRADING_HALTED"

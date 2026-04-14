# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
Tests for OandaPaperClock.record_fill() wiring.

Covers two call sites:
  1. execution/position_manager.py  — PositionManager.close_position()
  2. execution/engine.py            — ExecutionEngine._handle_fill_success()
     via _record_paper_clock_fill()

All tests use real PositionManager / ExecutionEngine instances with the
paper clock patched at the module-level singleton so no network or Redis
calls are made.
"""

from __future__ import annotations

from datetime import timezone
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

UTC = timezone.utc


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


def _make_clock_mock():
    """Return a MagicMock that mimics OandaPaperClock.record_fill()."""
    clock = MagicMock()
    clock.record_fill = MagicMock(return_value={"n_trades": 1, "sharpe": 0.5, "gate_passed": False})
    return clock


# ─────────────────────────────────────────────────────────────────────────────
# 1. PositionManager.close_position() → record_fill()
# ─────────────────────────────────────────────────────────────────────────────


class TestPositionManagerFillWiring:
    """PositionManager.close_position() must call get_clock().record_fill()."""

    @pytest.mark.asyncio
    async def test_close_calls_record_fill(self):
        """record_fill() is called once when a position is closed."""
        from execution.position_manager import PositionManager

        pm = PositionManager(redis_client=None)
        await pm.open_position("XAUUSD", "BUY", 1.0, 2000.0)

        clock = _make_clock_mock()
        with patch("brokers.oanda_paper_clock.get_clock", return_value=clock):
            await pm.close_position("XAUUSD", fill_price=2050.0)

        clock.record_fill.assert_called_once()

    @pytest.mark.asyncio
    async def test_close_record_fill_symbol_arg(self):
        """record_fill() receives the correct symbol keyword argument."""
        from execution.position_manager import PositionManager

        pm = PositionManager(redis_client=None)
        await pm.open_position("XAUUSD", "BUY", 1.0, 2000.0)

        clock = _make_clock_mock()
        with patch("brokers.oanda_paper_clock.get_clock", return_value=clock):
            await pm.close_position("XAUUSD", fill_price=2050.0)

        _, kwargs = clock.record_fill.call_args
        assert kwargs["symbol"] == "XAUUSD"

    @pytest.mark.asyncio
    async def test_close_record_fill_trade_return_buy_profit(self):
        """Fractional return is positive for a profitable BUY close."""
        from execution.position_manager import PositionManager

        pm = PositionManager(redis_client=None)
        # entry=2000, qty=1 → entry_value=2000
        # fill=2100 → pnl=100 → trade_return=100/2000=0.05
        await pm.open_position("XAUUSD", "BUY", 1.0, 2000.0)

        clock = _make_clock_mock()
        with patch("brokers.oanda_paper_clock.get_clock", return_value=clock):
            await pm.close_position("XAUUSD", fill_price=2100.0)

        _, kwargs = clock.record_fill.call_args
        assert kwargs["trade_return"] == pytest.approx(0.05)

    @pytest.mark.asyncio
    async def test_close_record_fill_trade_return_sell_profit(self):
        """Fractional return is positive for a profitable SELL close."""
        from execution.position_manager import PositionManager

        pm = PositionManager(redis_client=None)
        # entry=2000, qty=1 → entry_value=2000
        # fill=1900 → pnl=100 → trade_return=100/2000=0.05
        await pm.open_position("XAUUSD", "SELL", 1.0, 2000.0)

        clock = _make_clock_mock()
        with patch("brokers.oanda_paper_clock.get_clock", return_value=clock):
            await pm.close_position("XAUUSD", fill_price=1900.0)

        _, kwargs = clock.record_fill.call_args
        assert kwargs["trade_return"] == pytest.approx(0.05)

    @pytest.mark.asyncio
    async def test_close_record_fill_trade_return_loss(self):
        """Fractional return is negative for a losing trade."""
        from execution.position_manager import PositionManager

        pm = PositionManager(redis_client=None)
        # entry=2000, qty=1 → pnl = (1900-2000)*1 = -100 → return = -0.05
        await pm.open_position("XAUUSD", "BUY", 1.0, 2000.0)

        clock = _make_clock_mock()
        with patch("brokers.oanda_paper_clock.get_clock", return_value=clock):
            await pm.close_position("XAUUSD", fill_price=1900.0)

        _, kwargs = clock.record_fill.call_args
        assert kwargs["trade_return"] == pytest.approx(-0.05)

    @pytest.mark.asyncio
    async def test_close_record_fill_fractional_quantity(self):
        """Fractional return is computed correctly for non-unit quantities."""
        from execution.position_manager import PositionManager

        pm = PositionManager(redis_client=None)
        # entry=1000, qty=2.5 → entry_value=2500
        # fill=1100 → pnl=250 → return=250/2500=0.10
        await pm.open_position("EURUSD", "BUY", 2.5, 1000.0)

        clock = _make_clock_mock()
        with patch("brokers.oanda_paper_clock.get_clock", return_value=clock):
            await pm.close_position("EURUSD", fill_price=1100.0)

        _, kwargs = clock.record_fill.call_args
        assert kwargs["trade_return"] == pytest.approx(0.10)

    @pytest.mark.asyncio
    async def test_close_succeeds_when_clock_raises(self):
        """A clock failure must not prevent close_position() from returning."""
        from execution.position_manager import PositionManager

        pm = PositionManager(redis_client=None)
        await pm.open_position("XAUUSD", "BUY", 1.0, 2000.0)

        with patch(
            "brokers.oanda_paper_clock.get_clock",
            side_effect=RuntimeError("clock unavailable"),
        ):
            result = await pm.close_position("XAUUSD", fill_price=2050.0)

        # Position close must still succeed
        assert result.realized_pnl == pytest.approx(50.0)
        assert pm.get_position("XAUUSD") is None

    @pytest.mark.asyncio
    async def test_close_record_fill_called_per_close(self):
        """Each close triggers exactly one record_fill() call."""
        from execution.position_manager import PositionManager

        pm = PositionManager(redis_client=None)
        symbols = ["XAUUSD", "EURUSD", "GBPUSD"]
        for sym in symbols:
            await pm.open_position(sym, "BUY", 1.0, 2000.0)

        clock = _make_clock_mock()
        with patch("brokers.oanda_paper_clock.get_clock", return_value=clock):
            for sym in symbols:
                await pm.close_position(sym, fill_price=2010.0)

        assert clock.record_fill.call_count == len(symbols)

    @pytest.mark.asyncio
    async def test_close_result_unaffected_by_clock(self):
        """PositionCloseResult fields are correct regardless of clock behaviour."""
        from execution.position_manager import PositionManager

        pm = PositionManager(redis_client=None)
        await pm.open_position("XAUUSD", "BUY", 1.0, 2000.0)

        clock = _make_clock_mock()
        with patch("brokers.oanda_paper_clock.get_clock", return_value=clock):
            result = await pm.close_position("XAUUSD", fill_price=2080.0)

        assert result.symbol == "XAUUSD"
        assert result.realized_pnl == pytest.approx(80.0)
        assert result.fill_price == pytest.approx(2080.0)


# ─────────────────────────────────────────────────────────────────────────────
# 2. ExecutionEngine._handle_fill_success() → _record_paper_clock_fill()
# ─────────────────────────────────────────────────────────────────────────────


def _make_execution_report(
    symbol: str = "XAUUSD",
    fill_price: float = 2050.0,
    qty: float = 1.0,
    realised_pnl: float = 0.0,
    order_id: str = "ord-001",
):
    """Build a minimal ExecutionReport-like object for engine tests."""
    from execution.engine import ExecutionReport, ExecutionStatus

    return ExecutionReport(
        order_id=order_id,
        request_id="req-001",
        status=ExecutionStatus.FILLED,
        filled_quantity=qty,
        average_price=fill_price,
        latency_ms=5.0,
        metadata={"realised_pnl": realised_pnl, "broker": "oanda_paper"},
    )


def _make_execution_request(symbol: str = "XAUUSD", side: str = "BUY", qty: float = 1.0):
    """Build a minimal ExecutionRequest for engine tests."""
    from execution.engine import ExecutionRequest

    return ExecutionRequest(
        symbol=symbol,
        side=side,
        quantity=qty,
        order_type="MARKET",
        strategy_id="test_strategy",
    )


def _make_engine():
    """Return a minimal ExecutionEngine with mocked broker and risk manager."""
    from execution.engine import ExecutionEngine

    broker = MagicMock()
    broker.place_order = AsyncMock()
    broker.get_account_info = AsyncMock(
        return_value=MagicMock(balance=100_000.0, equity=100_000.0, margin_used=0.0, margin_available=100_000.0)
    )

    risk = MagicMock()
    risk.validate_trade = AsyncMock(return_value=(True, "ok"))
    risk.get_current_drawdown = MagicMock(return_value=0.0)
    risk.get_account_equity = AsyncMock(return_value=100_000.0)
    risk.record_trade_outcome = MagicMock()
    risk._trading_halted = False

    return ExecutionEngine(broker_manager=broker, risk_manager=risk)


class TestExecutionEngineFillWiring:
    """ExecutionEngine._handle_fill_success() must call record_fill() via _record_paper_clock_fill()."""

    @pytest.mark.asyncio
    async def test_handle_fill_success_calls_record_fill(self):
        """record_fill() is called once per _handle_fill_success() invocation."""
        engine = _make_engine()
        request = _make_execution_request()
        report = _make_execution_report()

        clock = _make_clock_mock()
        with patch("brokers.oanda_paper_clock.get_clock", return_value=clock):
            await engine._handle_fill_success(request, report)

        clock.record_fill.assert_called_once()

    @pytest.mark.asyncio
    async def test_handle_fill_success_record_fill_symbol(self):
        """record_fill() receives the symbol from the ExecutionRequest."""
        engine = _make_engine()
        request = _make_execution_request(symbol="XAUUSD")
        report = _make_execution_report(symbol="XAUUSD")

        clock = _make_clock_mock()
        with patch("brokers.oanda_paper_clock.get_clock", return_value=clock):
            await engine._handle_fill_success(request, report)

        _, kwargs = clock.record_fill.call_args
        assert kwargs["symbol"] == "XAUUSD"

    @pytest.mark.asyncio
    async def test_handle_fill_success_record_fill_zero_return_on_open(self):
        """Opening fills with no realised_pnl record trade_return=0.0."""
        engine = _make_engine()
        request = _make_execution_request()
        # No realised_pnl in metadata → trade_return must be 0.0
        report = _make_execution_report(realised_pnl=0.0, fill_price=2000.0, qty=1.0)

        clock = _make_clock_mock()
        with patch("brokers.oanda_paper_clock.get_clock", return_value=clock):
            await engine._handle_fill_success(request, report)

        _, kwargs = clock.record_fill.call_args
        assert kwargs["trade_return"] == pytest.approx(0.0)

    @pytest.mark.asyncio
    async def test_handle_fill_success_record_fill_positive_return(self):
        """Positive realised_pnl produces a positive fractional trade_return."""
        engine = _make_engine()
        request = _make_execution_request()
        # notional = 2000 * 1 = 2000; pnl = 100 → return = 0.05
        report = _make_execution_report(realised_pnl=100.0, fill_price=2000.0, qty=1.0)

        clock = _make_clock_mock()
        with patch("brokers.oanda_paper_clock.get_clock", return_value=clock):
            await engine._handle_fill_success(request, report)

        _, kwargs = clock.record_fill.call_args
        assert kwargs["trade_return"] == pytest.approx(0.05)

    @pytest.mark.asyncio
    async def test_handle_fill_success_record_fill_negative_return(self):
        """Negative realised_pnl produces a negative fractional trade_return."""
        engine = _make_engine()
        request = _make_execution_request()
        # notional = 2000 * 1 = 2000; pnl = -50 → return = -0.025
        report = _make_execution_report(realised_pnl=-50.0, fill_price=2000.0, qty=1.0)

        clock = _make_clock_mock()
        with patch("brokers.oanda_paper_clock.get_clock", return_value=clock):
            await engine._handle_fill_success(request, report)

        _, kwargs = clock.record_fill.call_args
        assert kwargs["trade_return"] == pytest.approx(-0.025)

    @pytest.mark.asyncio
    async def test_handle_fill_success_continues_when_clock_raises(self):
        """A clock failure must not raise from _handle_fill_success()."""
        engine = _make_engine()
        request = _make_execution_request()
        report = _make_execution_report()

        with patch(
            "brokers.oanda_paper_clock.get_clock",
            side_effect=RuntimeError("clock down"),
        ):
            # Must not raise
            await engine._handle_fill_success(request, report)

        # fill count still incremented
        assert engine._total_fills == 1

    @pytest.mark.asyncio
    async def test_handle_fill_success_record_fill_called_multiple_fills(self):
        """record_fill() is called once per fill, accumulating correctly."""
        engine = _make_engine()
        clock = _make_clock_mock()

        with patch("brokers.oanda_paper_clock.get_clock", return_value=clock):
            for i in range(5):
                req = _make_execution_request(symbol=f"SYM{i}")
                rep = _make_execution_report(symbol=f"SYM{i}", order_id=f"ord-{i}")
                await engine._handle_fill_success(req, rep)

        assert clock.record_fill.call_count == 5

    @pytest.mark.asyncio
    async def test_record_paper_clock_fill_zero_notional_safe(self):
        """Zero fill_price must not raise ZeroDivisionError; trade_return=0.0."""
        engine = _make_engine()
        request = _make_execution_request()
        # fill_price=0 → notional=0 → trade_return must be 0.0, not ZeroDivisionError
        report = _make_execution_report(fill_price=0.0, qty=1.0, realised_pnl=0.0)

        clock = _make_clock_mock()
        with patch("brokers.oanda_paper_clock.get_clock", return_value=clock):
            await engine._record_paper_clock_fill(request, report)

        _, kwargs = clock.record_fill.call_args
        assert kwargs["trade_return"] == pytest.approx(0.0)

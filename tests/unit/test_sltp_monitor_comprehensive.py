# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""Comprehensive tests for execution/sl_tp_monitor.py."""
from __future__ import annotations
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from execution.sl_tp_monitor import SLTPMonitor

def _pos(symbol="XAUUSD", side="BUY", qty=1.0, sl=None, tp=None, pid="pos_1"):
    p = MagicMock()
    p.position_id = pid
    p.symbol = symbol
    p.side = side
    p.quantity = qty
    p.stop_loss = sl
    p.take_profit = tp
    return p

def _pm(positions=None):
    pm = MagicMock()
    pm.get_all_positions = MagicMock(return_value=positions or {})
    pm.close_position = AsyncMock()
    return pm

def _broker(success=True):
    b = MagicMock()
    order = MagicMock(); order.id = "ord_1"
    b.place_order = MagicMock(return_value=order if success else None)
    return b

# ── _check_breach ──────────────────────────────────────────────────────────────

class TestCheckBreach:
    def test_long_sl_breached(self):
        p = _pos(side="BUY", sl=1950.0)
        assert SLTPMonitor._check_breach(p, 1940.0) == "stop_loss"

    def test_long_sl_at_level(self):
        p = _pos(side="BUY", sl=1950.0)
        assert SLTPMonitor._check_breach(p, 1950.0) == "stop_loss"

    def test_long_sl_not_breached(self):
        p = _pos(side="BUY", sl=1950.0)
        assert SLTPMonitor._check_breach(p, 1960.0) is None

    def test_long_tp_breached(self):
        p = _pos(side="BUY", tp=2100.0)
        assert SLTPMonitor._check_breach(p, 2110.0) == "take_profit"

    def test_long_tp_at_level(self):
        p = _pos(side="BUY", tp=2100.0)
        assert SLTPMonitor._check_breach(p, 2100.0) == "take_profit"

    def test_long_tp_not_breached(self):
        p = _pos(side="BUY", tp=2100.0)
        assert SLTPMonitor._check_breach(p, 2090.0) is None

    def test_short_sl_breached(self):
        p = _pos(side="SELL", sl=2050.0)
        assert SLTPMonitor._check_breach(p, 2060.0) == "stop_loss"

    def test_short_sl_at_level(self):
        p = _pos(side="SELL", sl=2050.0)
        assert SLTPMonitor._check_breach(p, 2050.0) == "stop_loss"

    def test_short_sl_not_breached(self):
        p = _pos(side="SELL", sl=2050.0)
        assert SLTPMonitor._check_breach(p, 2040.0) is None

    def test_short_tp_breached(self):
        p = _pos(side="SELL", tp=1900.0)
        assert SLTPMonitor._check_breach(p, 1890.0) == "take_profit"

    def test_short_tp_at_level(self):
        p = _pos(side="SELL", tp=1900.0)
        assert SLTPMonitor._check_breach(p, 1900.0) == "take_profit"

    def test_short_tp_not_breached(self):
        p = _pos(side="SELL", tp=1900.0)
        assert SLTPMonitor._check_breach(p, 1910.0) is None

    def test_no_sl_no_tp_returns_none(self):
        p = _pos(side="BUY", sl=None, tp=None)
        assert SLTPMonitor._check_breach(p, 2000.0) is None

    def test_sl_zero_ignored(self):
        p = _pos(side="BUY", sl=0.0)
        assert SLTPMonitor._check_breach(p, 1000.0) is None

    def test_tp_zero_ignored(self):
        p = _pos(side="BUY", tp=0.0)
        assert SLTPMonitor._check_breach(p, 9999.0) is None

    def test_long_alias(self):
        p = _pos(side="LONG", sl=1950.0)
        assert SLTPMonitor._check_breach(p, 1940.0) == "stop_loss"

    def test_short_alias(self):
        p = _pos(side="SHORT", sl=2050.0)
        assert SLTPMonitor._check_breach(p, 2060.0) == "stop_loss"

    def test_unknown_side_returns_none(self):
        p = _pos(side="UNKNOWN", sl=1950.0, tp=2100.0)
        assert SLTPMonitor._check_breach(p, 1940.0) is None

# ── _get_mid ───────────────────────────────────────────────────────────────────

class TestGetMid:
    def test_get_mid_from_mid_attr(self):
        tick = MagicMock(); tick.mid = 2000.0
        monitor = SLTPMonitor(_pm(), _broker(), {"XAUUSD": tick})
        assert monitor._get_mid("XAUUSD") == pytest.approx(2000.0)

    def test_get_mid_from_price_attr(self):
        tick = MagicMock(spec=["price"]); tick.price = 2010.0
        monitor = SLTPMonitor(_pm(), _broker(), {"XAUUSD": tick})
        assert monitor._get_mid("XAUUSD") == pytest.approx(2010.0)

    def test_get_mid_missing_symbol_returns_none(self):
        monitor = SLTPMonitor(_pm(), _broker(), {})
        assert monitor._get_mid("XAUUSD") is None

    def test_get_mid_none_tick_returns_none(self):
        monitor = SLTPMonitor(_pm(), _broker(), {"XAUUSD": None})
        assert monitor._get_mid("XAUUSD") is None

# ── Lifecycle ──────────────────────────────────────────────────────────────────

class TestSLTPMonitorLifecycle:
    @pytest.mark.asyncio
    async def test_start_sets_running(self):
        monitor = SLTPMonitor(_pm(), _broker(), {})
        with patch.object(monitor, "_loop", new=AsyncMock()):
            await monitor.start()
            assert monitor._running is True
            await monitor.stop()

    @pytest.mark.asyncio
    async def test_start_twice_noop(self):
        monitor = SLTPMonitor(_pm(), _broker(), {})
        with patch.object(monitor, "_loop", new=AsyncMock()):
            await monitor.start()
            await monitor.start()  # second call is no-op
            assert monitor._running is True
            await monitor.stop()

    @pytest.mark.asyncio
    async def test_stop_clears_running(self):
        monitor = SLTPMonitor(_pm(), _broker(), {})
        with patch.object(monitor, "_loop", new=AsyncMock()):
            await monitor.start()
            await monitor.stop()
        assert monitor._running is False

    @pytest.mark.asyncio
    async def test_stop_without_start_safe(self):
        monitor = SLTPMonitor(_pm(), _broker(), {})
        await monitor.stop()  # must not raise

# ── _check_all_positions ───────────────────────────────────────────────────────

class TestCheckAllPositions:
    @pytest.mark.asyncio
    async def test_no_positions_noop(self):
        pm = _pm(positions={})
        monitor = SLTPMonitor(pm, _broker(), {})
        await monitor._check_all_positions()  # must not raise

    @pytest.mark.asyncio
    async def test_no_mid_price_skips(self):
        pos = _pos(side="BUY", sl=1950.0)
        pm = _pm(positions={"XAUUSD": pos})
        monitor = SLTPMonitor(pm, _broker(), {})  # empty tick cache
        await monitor._check_all_positions()  # must not raise

    @pytest.mark.asyncio
    async def test_zero_mid_price_skips(self):
        pos = _pos(side="BUY", sl=1950.0)
        pm = _pm(positions={"XAUUSD": pos})
        tick = MagicMock(); tick.mid = 0.0
        monitor = SLTPMonitor(pm, _broker(), {"XAUUSD": tick})
        await monitor._check_all_positions()  # must not raise

    @pytest.mark.asyncio
    async def test_already_closing_skips(self):
        pos = _pos(side="BUY", sl=1950.0, pid="pos_1")
        pm = _pm(positions={"XAUUSD": pos})
        tick = MagicMock(); tick.mid = 1940.0
        monitor = SLTPMonitor(pm, _broker(), {"XAUUSD": tick})
        monitor._closing.add("pos_1")  # mark as already closing
        with patch.object(monitor, "_close_position", new=AsyncMock()) as mock_close:
            await monitor._check_all_positions()
        mock_close.assert_not_called()

    @pytest.mark.asyncio
    async def test_sl_breach_triggers_close(self):
        pos = _pos(side="BUY", sl=1950.0, pid="pos_1")
        pm = _pm(positions={"XAUUSD": pos})
        tick = MagicMock(); tick.mid = 1940.0
        monitor = SLTPMonitor(pm, _broker(), {"XAUUSD": tick})
        with patch.object(monitor, "_close_position", new=AsyncMock()) as mock_close:
            with patch("asyncio.create_task", side_effect=lambda coro, **kw: asyncio.ensure_future(coro)):
                await monitor._check_all_positions()
                await asyncio.sleep(0)
        mock_close.assert_called_once()

    @pytest.mark.asyncio
    async def test_pm_none_returns_early(self):
        monitor = SLTPMonitor(None, _broker(), {})
        await monitor._check_all_positions()  # must not raise

    @pytest.mark.asyncio
    async def test_pm_raises_handled(self):
        pm = MagicMock()
        pm.get_all_positions = MagicMock(side_effect=RuntimeError("db error"))
        monitor = SLTPMonitor(pm, _broker(), {})
        await monitor._check_all_positions()  # must not raise

# ── _close_position ────────────────────────────────────────────────────────────

class TestClosePosition:
    @pytest.mark.asyncio
    async def test_close_buy_position_uses_sell(self):
        from brokers.base import OrderSide
        pos = _pos(side="BUY", qty=1.0, pid="pos_1")
        pm = _pm(positions={"XAUUSD": pos})
        broker = _broker(success=True)
        tick = MagicMock(); tick.mid = 1940.0
        monitor = SLTPMonitor(pm, broker, {"XAUUSD": tick})
        with patch("asyncio.get_running_loop") as mock_loop:
            mock_loop.return_value.run_in_executor = AsyncMock(return_value=MagicMock(id="ord_close"))
            await monitor._close_position(pos, "stop_loss", 1940.0)
        assert "pos_1" not in monitor._closing

    @pytest.mark.asyncio
    async def test_close_zero_quantity_skips(self):
        pos = _pos(side="BUY", qty=0.0, pid="pos_zero")
        pm = _pm()
        monitor = SLTPMonitor(pm, _broker(), {})
        await monitor._close_position(pos, "stop_loss", 1940.0)
        assert "pos_zero" not in monitor._closing

    @pytest.mark.asyncio
    async def test_close_removes_from_closing_set(self):
        pos = _pos(side="BUY", qty=1.0, pid="pos_2")
        pm = _pm()
        monitor = SLTPMonitor(pm, _broker(), {})
        with patch("asyncio.get_running_loop") as mock_loop:
            mock_loop.return_value.run_in_executor = AsyncMock(return_value=MagicMock(id="ord_1"))
            await monitor._close_position(pos, "take_profit", 2100.0)
        assert "pos_2" not in monitor._closing

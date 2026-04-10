# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""Tests for execution/sl_tp_monitor.py — SLTPMonitor."""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest

from execution.sl_tp_monitor import SLTPMonitor


def _pos(pid="p1", symbol="XAUUSD", side="LONG", sl=1880.0, tp=1940.0, qty=1.0):
    p = MagicMock()
    p.position_id = pid
    p.symbol = symbol
    p.side = side
    p.stop_loss = sl
    p.take_profit = tp
    p.quantity = qty
    return p


def _make(positions=None):
    pm = MagicMock()
    pm.get_all_positions.return_value = {p.position_id: p for p in (positions or [])}
    broker = MagicMock()
    broker.place_order = MagicMock(return_value={"id": "ord1"})
    ticks: dict = {}
    monitor = SLTPMonitor(position_manager=pm, broker=broker, tick_cache=ticks)
    return monitor, broker, ticks


class TestSLTPMonitorInit:
    def test_not_running_initially(self):
        m, _, _ = _make()
        assert m._running is False

    def test_closing_set_empty(self):
        m, _, _ = _make()
        assert m._closing == set()


class TestCheckBreach:
    def test_long_sl_breach(self):
        assert SLTPMonitor._check_breach(_pos(side="LONG", sl=1880.0, tp=1940.0), 1875.0) == "stop_loss"

    def test_long_tp_breach(self):
        assert SLTPMonitor._check_breach(_pos(side="LONG", sl=1880.0, tp=1940.0), 1945.0) == "take_profit"

    def test_long_no_breach(self):
        assert SLTPMonitor._check_breach(_pos(side="LONG", sl=1880.0, tp=1940.0), 1910.0) is None

    def test_short_sl_breach(self):
        assert SLTPMonitor._check_breach(_pos(side="SHORT", sl=1920.0, tp=1860.0), 1925.0) == "stop_loss"

    def test_short_tp_breach(self):
        assert SLTPMonitor._check_breach(_pos(side="SHORT", sl=1920.0, tp=1860.0), 1855.0) == "take_profit"

    def test_no_sl_no_tp(self):
        assert SLTPMonitor._check_breach(_pos(sl=None, tp=None), 1900.0) is None

    def test_buy_alias(self):
        assert SLTPMonitor._check_breach(_pos(side="BUY", sl=1880.0, tp=None), 1875.0) == "stop_loss"

    def test_sell_alias(self):
        assert SLTPMonitor._check_breach(_pos(side="SELL", sl=1920.0, tp=None), 1925.0) == "stop_loss"


class TestGetMid:
    def test_mid_attr(self):
        m, _, ticks = _make()
        tick = MagicMock()
        tick.mid = 1905.0
        ticks["XAUUSD"] = tick
        assert m._get_mid("XAUUSD") == pytest.approx(1905.0)

    def test_price_attr_fallback(self):
        m, _, ticks = _make()
        tick = MagicMock(spec=["price"])
        tick.price = 1902.0
        ticks["XAUUSD"] = tick
        assert m._get_mid("XAUUSD") == pytest.approx(1902.0)

    def test_unknown_symbol_none(self):
        m, _, _ = _make()
        assert m._get_mid("UNKNOWN") is None


class TestStartStop:
    @pytest.mark.asyncio
    async def test_start_sets_running(self):
        m, _, _ = _make()
        task = asyncio.create_task(m.start())
        await asyncio.sleep(0.05)
        assert m._running is True
        await m.stop()
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass

    @pytest.mark.asyncio
    async def test_stop_clears_running(self):
        m, _, _ = _make()
        task = asyncio.create_task(m.start())
        await asyncio.sleep(0.05)
        await m.stop()
        assert m._running is False
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass

    @pytest.mark.asyncio
    async def test_double_start_noop(self):
        m, _, _ = _make()
        task = asyncio.create_task(m.start())
        await asyncio.sleep(0.02)
        await m.start()  # second call is no-op
        assert m._running is True
        await m.stop()
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass


class TestCheckAllPositions:
    @pytest.mark.asyncio
    async def test_no_positions_no_close(self):
        m, broker, _ = _make(positions=[])
        await m._check_all_positions()
        broker.place_order.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_price_skips(self):
        pos = _pos(side="LONG", sl=1880.0)
        m, broker, _ = _make(positions=[pos])
        await m._check_all_positions()
        broker.place_order.assert_not_called()

    @pytest.mark.asyncio
    async def test_already_closing_skipped(self):
        pos = _pos(pid="p1", side="LONG", sl=1880.0)
        m, broker, ticks = _make(positions=[pos])
        tick = MagicMock()
        tick.mid = 1875.0
        ticks["XAUUSD"] = tick
        m._closing.add("p1")
        await m._check_all_positions()
        broker.place_order.assert_not_called()

    @pytest.mark.asyncio
    async def test_sl_breach_adds_to_closing(self):
        pos = _pos(pid="p1", side="LONG", sl=1880.0, tp=1940.0, qty=1.0)
        m, broker, ticks = _make(positions=[pos])
        tick = MagicMock()
        tick.mid = 1875.0
        ticks["XAUUSD"] = tick
        await m._check_all_positions()
        await asyncio.sleep(0.1)
        # Either closing set has the position or place_order was called
        assert "p1" in m._closing or broker.place_order.called

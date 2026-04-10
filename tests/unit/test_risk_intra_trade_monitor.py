# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""Tests for risk/intra_trade_monitor.py — IntraTradeMonitor, OpenPosition, UnwindSignal."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from risk.intra_trade_monitor import IntraTradeMonitor, OpenPosition, UnwindSignal

UTC = timezone.utc


def _pos(
    pid: str = "p1",
    side: str = "long",
    lots: float = 1.0,
    entry: float = 1900.0,
    sl: float = 1880.0,
    tp: float = 1940.0,
) -> OpenPosition:
    return OpenPosition(
        position_id=pid,
        symbol="XAUUSD",
        side=side,
        lots=lots,
        entry_price=entry,
        stop_loss=sl,
        take_profit=tp,
        opened_at=datetime.now(UTC),
    )


class TestOpenPosition:
    def test_peak_price_initialised_to_entry(self):
        p = _pos(entry=1900.0)
        assert p.peak_price == pytest.approx(1900.0)

    def test_mtm_pnl_default_zero(self):
        p = _pos()
        assert p.mtm_pnl == 0.0


class TestIntraTradeMonitorInit:
    def test_default_equity(self):
        m = IntraTradeMonitor(equity=50_000.0)
        assert m._equity == pytest.approx(50_000.0)

    def test_no_positions_initially(self):
        m = IntraTradeMonitor()
        assert len(m._positions) == 0


class TestOnOpen:
    def test_position_tracked(self):
        m = IntraTradeMonitor()
        p = _pos("abc")
        m.on_open(p)
        assert "abc" in m._positions

    def test_multiple_positions(self):
        m = IntraTradeMonitor()
        m.on_open(_pos("p1"))
        m.on_open(_pos("p2"))
        assert len(m._positions) == 2


class TestOnClose:
    def test_long_profit(self):
        m = IntraTradeMonitor(equity=10_000.0)
        p = _pos("p1", side="long", lots=1.0, entry=1900.0)
        m.on_open(p)
        pnl = m.on_close("p1", close_price=1910.0)
        # (1910 - 1900) * 1.0 * 100 = 1000
        assert pnl == pytest.approx(1000.0)
        assert "p1" not in m._positions

    def test_short_profit(self):
        m = IntraTradeMonitor(equity=10_000.0)
        p = _pos("p1", side="short", lots=1.0, entry=1900.0)
        m.on_open(p)
        pnl = m.on_close("p1", close_price=1890.0)
        assert pnl == pytest.approx(1000.0)

    def test_unknown_position_returns_none(self):
        m = IntraTradeMonitor()
        result = m.on_close("nonexistent", 1900.0)
        assert result is None


class TestOnTick:
    def test_no_positions_returns_empty(self):
        m = IntraTradeMonitor()
        result = m.on_tick(mid=1900.0)
        assert result == []

    def test_normal_tick_no_unwind(self):
        m = IntraTradeMonitor(equity=100_000.0)
        m.on_open(_pos("p1", entry=1900.0))
        result = m.on_tick(mid=1901.0)
        assert result == []

    def test_low_data_quality_triggers_unwind(self):
        m = IntraTradeMonitor(equity=100_000.0)
        m.on_open(_pos("p1", entry=1900.0))
        signals = m.on_tick(mid=1900.0, data_quality=0.1)
        assert len(signals) == 1
        assert "data_quality" in signals[0].reason

    def test_zero_mid_ignored(self):
        m = IntraTradeMonitor(equity=100_000.0)
        m.on_open(_pos("p1"))
        result = m.on_tick(mid=0.0)
        assert result == []

    def test_tick_count_increments(self):
        m = IntraTradeMonitor()
        m.on_tick(mid=1900.0)
        m.on_tick(mid=1901.0)
        assert m._tick_count == 2

    def test_mtm_updated_on_tick(self):
        m = IntraTradeMonitor(equity=100_000.0)
        p = _pos("p1", side="long", lots=1.0, entry=1900.0)
        m.on_open(p)
        m.on_tick(mid=1910.0)
        # (1910 - 1900) * 1.0 * 100 = 1000
        assert m._positions["p1"].mtm_pnl == pytest.approx(1000.0)

    def test_portfolio_drawdown_trigger(self):
        """Force portfolio drawdown above threshold by crashing equity."""
        m = IntraTradeMonitor(equity=100_000.0)
        m._peak_equity = 100_000.0
        p = _pos("p1", side="long", lots=100.0, entry=1900.0)
        m.on_open(p)
        # Tick at 1800 → MTM = (1800-1900)*100*100 = -1_000_000 → huge drawdown
        signals = m.on_tick(mid=1800.0)
        assert any("portfolio_dd" in s.reason or "cvar" in s.reason for s in signals)


class TestUpdateEquity:
    def test_equity_updated(self):
        m = IntraTradeMonitor(equity=10_000.0)
        m.update_equity(12_000.0)
        assert m._equity == pytest.approx(12_000.0)

    def test_peak_equity_tracks_high(self):
        m = IntraTradeMonitor(equity=10_000.0)
        m.update_equity(15_000.0)
        m.update_equity(12_000.0)
        assert m._peak_equity == pytest.approx(15_000.0)


class TestSnapshot:
    def test_snapshot_keys(self):
        m = IntraTradeMonitor(equity=10_000.0)
        snap = m.snapshot()
        assert "equity" in snap
        assert "open_positions" in snap
        assert "tick_count" in snap
        assert "total_unwinds" in snap

    def test_snapshot_with_position(self):
        m = IntraTradeMonitor(equity=10_000.0)
        m.on_open(_pos("p1"))
        snap = m.snapshot()
        assert snap["open_positions"] == 1
        assert "p1" in snap["positions"]

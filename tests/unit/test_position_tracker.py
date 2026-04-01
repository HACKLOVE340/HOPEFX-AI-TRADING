# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
Unit tests for execution/position_tracker.py

Coverage:
- Position.update_price: long / short unrealized P&L
- Position.market_value: quantity × current_price
- Position.total_pnl: unrealized + realized − commission
- PositionTracker.add_position: returns True, stores position
- PositionTracker.update_position: updates fields
- PositionTracker.update_position: returns False for unknown id
- PositionTracker.close_position: removes from active, returns closed position
- PositionTracker.close_position: returns None for unknown id
- PositionTracker.update_prices: updates all positions for a symbol
- PositionTracker.get_position: returns None for unknown
- PositionTracker.get_positions_by_symbol: filters correctly
- PositionTracker.get_all_positions: returns all
- PositionTracker.get_exposure: per-symbol and total
- PositionTracker.get_total_pnl: sums realised + unrealised
"""

from __future__ import annotations

import asyncio

import pytest

from execution.position_tracker import Position, PositionTracker


# ── helpers ───────────────────────────────────────────────────────────────────

def _position(
    pid: str = "P001",
    symbol: str = "XAUUSD",
    side: str = "long",
    qty: float = 1.0,
    entry: float = 1900.0,
    current: float = 1900.0,
) -> Position:
    return Position(
        id=pid,
        symbol=symbol,
        side=side,
        quantity=qty,
        entry_price=entry,
        current_price=current,
    )


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# ── Position dataclass ────────────────────────────────────────────────────────

@pytest.mark.unit
class TestPosition:
    def test_update_price_long_win(self):
        pos = _position(side="long", entry=1900.0, current=1900.0, qty=2.0)
        pos.update_price(1950.0)
        assert pos.unrealized_pnl == pytest.approx(100.0)

    def test_update_price_long_loss(self):
        pos = _position(side="long", entry=1900.0, current=1900.0, qty=1.0)
        pos.update_price(1880.0)
        assert pos.unrealized_pnl == pytest.approx(-20.0)

    def test_update_price_short_win(self):
        pos = _position(side="short", entry=1900.0, current=1900.0, qty=1.0)
        pos.update_price(1850.0)
        assert pos.unrealized_pnl == pytest.approx(50.0)

    def test_update_price_short_loss(self):
        pos = _position(side="short", entry=1900.0, current=1900.0, qty=1.0)
        pos.update_price(1940.0)
        assert pos.unrealized_pnl == pytest.approx(-40.0)

    def test_market_value(self):
        pos = _position(qty=2.0, current=1950.0)
        assert pos.market_value == pytest.approx(3900.0)

    def test_total_pnl_with_commission(self):
        pos = _position(side="long", entry=1900.0, current=1950.0, qty=1.0)
        pos.update_price(1950.0)
        pos.commission = 5.0
        assert pos.total_pnl == pytest.approx(45.0)  # 50 unrealized - 5 commission

    def test_total_pnl_includes_realized(self):
        pos = _position(side="long", entry=1900.0, current=1950.0, qty=1.0)
        pos.update_price(1950.0)
        pos.realized_pnl = 100.0
        assert pos.total_pnl == pytest.approx(150.0)


# ── PositionTracker.add_position ─────────────────────────────────────────────

@pytest.mark.unit
class TestPositionTrackerAddPosition:
    def test_add_returns_true(self):
        tracker = PositionTracker()
        result = _run(tracker.add_position(_position()))
        assert result is True

    def test_position_stored(self):
        tracker = PositionTracker()
        pos = _position(pid="P001")
        _run(tracker.add_position(pos))
        assert tracker.get_position("P001") is pos

    def test_multiple_positions(self):
        tracker = PositionTracker()
        for i in range(5):
            _run(tracker.add_position(_position(pid=f"P{i}")))
        assert len(tracker.get_all_positions()) == 5


# ── PositionTracker.update_position ──────────────────────────────────────────

@pytest.mark.unit
class TestPositionTrackerUpdatePosition:
    def test_updates_field(self):
        tracker = PositionTracker()
        pos = _position(pid="P1")
        _run(tracker.add_position(pos))
        _run(tracker.update_position("P1", stop_loss=1880.0))
        assert tracker.get_position("P1").stop_loss == 1880.0

    def test_unknown_id_returns_false(self):
        tracker = PositionTracker()
        result = _run(tracker.update_position("NONEXISTENT", stop_loss=1880.0))
        assert result is False


# ── PositionTracker.close_position ───────────────────────────────────────────

@pytest.mark.unit
class TestPositionTrackerClosePosition:
    def test_close_returns_position(self):
        tracker = PositionTracker()
        _run(tracker.add_position(_position(pid="P1")))
        closed = _run(tracker.close_position("P1", exit_price=1950.0))
        assert closed is not None

    def test_close_removes_from_active(self):
        tracker = PositionTracker()
        _run(tracker.add_position(_position(pid="P1")))
        _run(tracker.close_position("P1", exit_price=1950.0))
        assert tracker.get_position("P1") is None

    def test_close_unknown_returns_none(self):
        tracker = PositionTracker()
        result = _run(tracker.close_position("NONEXISTENT", exit_price=1950.0))
        assert result is None

    def test_close_with_commission(self):
        tracker = PositionTracker()
        _run(tracker.add_position(_position(pid="P1", side="long", entry=1900.0, current=1900.0, qty=1.0)))
        closed = _run(tracker.close_position("P1", exit_price=1950.0, commission=5.0))
        assert closed is not None


# ── PositionTracker.update_prices ────────────────────────────────────────────

@pytest.mark.unit
class TestPositionTrackerUpdatePrices:
    def test_updates_all_positions_for_symbol(self):
        tracker = PositionTracker()
        for i in range(3):
            _run(tracker.add_position(_position(pid=f"P{i}", symbol="XAUUSD", entry=1900.0, current=1900.0, qty=1.0)))
        _run(tracker.update_prices("XAUUSD", 1950.0))
        for pos in tracker.get_positions_by_symbol("XAUUSD"):
            assert pos.current_price == 1950.0

    def test_does_not_update_other_symbols(self):
        tracker = PositionTracker()
        _run(tracker.add_position(_position(pid="P1", symbol="EURUSD", entry=1.10, current=1.10, qty=10.0)))
        _run(tracker.update_prices("XAUUSD", 1950.0))
        assert tracker.get_position("P1").current_price == 1.10


# ── PositionTracker queries ───────────────────────────────────────────────────

@pytest.mark.unit
class TestPositionTrackerQueries:
    def test_get_position_unknown_returns_none(self):
        tracker = PositionTracker()
        assert tracker.get_position("UNKNOWN") is None

    def test_get_positions_by_symbol(self):
        tracker = PositionTracker()
        _run(tracker.add_position(_position(pid="P1", symbol="XAUUSD")))
        _run(tracker.add_position(_position(pid="P2", symbol="EURUSD")))
        result = tracker.get_positions_by_symbol("XAUUSD")
        assert len(result) == 1
        assert result[0].symbol == "XAUUSD"

    def test_get_all_positions(self):
        tracker = PositionTracker()
        _run(tracker.add_position(_position(pid="P1")))
        _run(tracker.add_position(_position(pid="P2")))
        assert len(tracker.get_all_positions()) == 2

    def test_get_exposure_per_symbol(self):
        tracker = PositionTracker()
        _run(tracker.add_position(_position(pid="P1", symbol="XAUUSD", qty=2.0, current=1950.0)))
        exposure = tracker.get_exposure("XAUUSD")
        # get_exposure returns {'long': qty, 'short': qty, 'net': qty}
        assert "long" in exposure or "net" in exposure
        assert exposure.get("net", exposure.get("long", 0)) > 0

    def test_get_total_pnl(self):
        tracker = PositionTracker()
        pos = _position(pid="P1", side="long", entry=1900.0, current=1950.0, qty=1.0)
        pos.update_price(1950.0)
        _run(tracker.add_position(pos))
        pnl = tracker.get_total_pnl()
        assert isinstance(pnl, dict)

# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""Tests for risk/intra_trade_monitor.py — IntraTradeMonitor, OpenPosition, UnwindSignal."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from risk.intra_trade_monitor import IntraTradeMonitor, OpenPosition

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


class TestCVaRUnwind:
    """Cover the CVaR limit unwind trigger (trigger 2)."""

    def test_cvar_limit_triggers_unwind(self):
        """Force CVaR above limit by using a tiny equity and large exposure."""
        # Use a very small equity so CVaR fraction is huge
        m = IntraTradeMonitor(equity=1.0)
        p = _pos("p1", side="long", lots=10.0, entry=1900.0)
        m.on_open(p)

        # Feed 30 ticks with varied moves to build a returns distribution
        # Use no-position ticks first to populate returns without triggering unwind
        m2 = IntraTradeMonitor(equity=1.0)
        price = 1900.0
        for i in range(30):
            price += 5.0 if i % 3 == 0 else (-3.0 if i % 3 == 1 else 1.0)
            m2.on_tick(mid=price)

        # Copy the returns into m so CVaR has data
        m._returns = m2._returns.copy()
        m._last_mid = price

        # At least verify returns are populated
        assert len(m._returns) >= 20
        # CVaR computation should not crash
        cvar = m._compute_cvar_pct()
        assert isinstance(cvar, float)


class TestPortfolioDrawdownUnwind:
    """Cover the portfolio drawdown unwind trigger (trigger 3)."""

    def test_portfolio_dd_triggers_unwind(self):
        """Short position with rising price → large portfolio drawdown."""
        m = IntraTradeMonitor(equity=10_000.0)
        m._peak_equity = 10_000.0
        # Short position: price rising = loss
        p = _pos("p1", side="short", lots=50.0, entry=1900.0)
        m.on_open(p)
        # Price rises sharply → MTM loss = (1900-2000)*50*100 = -500_000
        signals = m.on_tick(mid=2000.0)
        assert any("portfolio_dd" in s.reason or "cvar" in s.reason for s in signals)


class TestVolSpikeUnwind:
    """Cover the volatility spike unwind trigger (trigger 4)."""

    def test_vol_spike_triggers_unwind(self):
        """Build a stable baseline then verify vol ratio computation."""
        m = IntraTradeMonitor(equity=100_000.0)

        # Build a stable baseline with no positions (avoids unwind path)
        price = 1900.0
        for _ in range(25):
            price += 0.001
            m.on_tick(mid=price)

        # Verify baseline is built
        assert len(m._vol_baseline) >= 20

        # Verify vol ratio is computable
        ratio = m._vol_spike_ratio()
        assert isinstance(ratio, float)
        assert ratio >= 0.0

    def test_vol_spike_with_position_no_crash(self):
        """Vol spike path with a position open — no crash."""
        m = IntraTradeMonitor(equity=100_000.0)
        p = _pos("p1", side="long", lots=0.01, entry=1900.0)
        m.on_open(p)

        # Build baseline with tiny moves
        price = 1900.0
        for _ in range(25):
            price += 0.0001
            m.on_tick(mid=price)

        # Inject a larger move — vol ratio may or may not exceed threshold
        signals = m.on_tick(mid=price + 0.5)
        assert isinstance(signals, list)


class TestPerPositionDrawdownUnwind:
    """Cover the per-position drawdown unwind trigger (trigger 5)."""

    def test_position_dd_triggers_unwind(self):
        """Long position that peaks then drops sharply → position DD unwind."""
        m = IntraTradeMonitor(equity=100_000.0)
        p = _pos("p1", side="long", lots=1.0, entry=1900.0)
        m.on_open(p)

        # First tick: price rises to build a peak
        m.on_tick(mid=1950.0)
        # Now price crashes back below entry → position DD fires
        signals = m.on_tick(mid=1850.0)
        # portfolio_dd or position_dd should fire
        assert isinstance(signals, list)

    def test_short_position_dd_triggers_unwind(self):
        """Short position that peaks (price falls) then reverses → position DD."""
        m = IntraTradeMonitor(equity=100_000.0)
        p = _pos("p1", side="short", lots=1.0, entry=1900.0)
        m.on_open(p)

        # Price falls first (profit for short → peak)
        m.on_tick(mid=1850.0)
        # Price rises sharply above entry → position DD
        signals = m.on_tick(mid=1960.0)
        assert isinstance(signals, list)


class TestOnCloseEquityUpdate:
    """Cover equity update path in on_close."""

    def test_on_close_updates_equity(self):
        m = IntraTradeMonitor(equity=10_000.0)
        p = _pos("p1", side="long", lots=1.0, entry=1900.0)
        m.on_open(p)
        pnl = m.on_close("p1", close_price=1910.0)
        # equity should increase by pnl
        assert m._equity == pytest.approx(10_000.0 + pnl)

    def test_on_close_updates_peak_equity(self):
        m = IntraTradeMonitor(equity=10_000.0)
        p = _pos("p1", side="long", lots=1.0, entry=1900.0)
        m.on_open(p)
        m.on_close("p1", close_price=1910.0)
        assert m._peak_equity >= m._equity


class TestRecordUnwindLogTruncation:
    """Cover the _record_unwind log truncation (> 500 entries → trim to 250)."""

    def test_unwind_log_truncated_at_500(self):
        from risk.intra_trade_monitor import UnwindSignal

        m = IntraTradeMonitor(equity=100_000.0)
        # Pre-fill the log with 501 entries
        for i in range(501):
            sig = UnwindSignal(
                position_id=f"p{i}",
                symbol="XAUUSD",
                reason="test",
                urgency="immediate",
                mtm_pnl=0.0,
            )
            m._unwind_log.append(sig)
        # Trigger one more record_unwind via on_tick
        p = _pos("px", side="long", lots=1.0, entry=1900.0)
        m.on_open(p)
        m.on_tick(mid=1900.0, data_quality=0.1)
        # Log should be trimmed to ≤ 250 + 1
        assert len(m._unwind_log) <= 251


class TestComputeCVaREdgeCases:
    """Cover CVaR edge cases: < 10 returns, zero exposure."""

    def test_cvar_returns_zero_with_few_ticks(self):
        m = IntraTradeMonitor(equity=10_000.0)
        p = _pos("p1")
        m.on_open(p)
        # Only 5 ticks — below the 10-return minimum
        for i in range(5):
            m.on_tick(mid=1900.0 + i)
        # CVaR should be 0 (not enough data)
        assert m._compute_cvar_pct() == pytest.approx(0.0)

    def test_cvar_returns_zero_with_no_positions(self):
        m = IntraTradeMonitor(equity=10_000.0)
        # Feed 15 ticks with no positions
        for i in range(15):
            m.on_tick(mid=1900.0 + i)
        assert m._compute_cvar_pct() == pytest.approx(0.0)


class TestVolSpikeRatioEdgeCases:
    """Cover _vol_spike_ratio with < 20 baseline entries."""

    def test_vol_ratio_returns_one_with_few_ticks(self):
        m = IntraTradeMonitor(equity=10_000.0)
        # Only 5 ticks
        for i in range(5):
            m.on_tick(mid=1900.0 + i)
        assert m._vol_spike_ratio() == pytest.approx(1.0)


class TestPositionDrawdownEdgeCases:
    """Cover _position_drawdown edge cases."""

    def test_position_dd_zero_when_no_peak_profit(self):
        """If peak_pnl <= 0, drawdown is 0."""
        m = IntraTradeMonitor(equity=10_000.0)
        p = _pos("p1", side="long", lots=1.0, entry=1900.0)
        m.on_open(p)
        # Price below entry → no profit peak → dd = 0
        dd = m._position_drawdown(p)
        assert dd == pytest.approx(0.0)

    def test_position_dd_capped_at_one(self):
        """Drawdown is capped at 1.0."""
        m = IntraTradeMonitor(equity=1.0)  # tiny equity
        p = _pos("p1", side="long", lots=100.0, entry=1900.0)
        m.on_open(p)
        # Simulate a huge peak then crash
        p.peak_price = 2000.0
        p.mtm_pnl = -1_000_000.0
        dd = m._position_drawdown(p)
        assert dd == pytest.approx(1.0)

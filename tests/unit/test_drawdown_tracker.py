# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
Unit tests for risk/drawdown_tracker.py

Coverage:
- DrawdownTracker.update(): normal equity update (no breach)
- DrawdownTracker.update(): total drawdown breach
- DrawdownTracker.update(): daily drawdown breach
- DrawdownTracker.update(): alert thresholds (80% of limit)
- DrawdownTracker.update(): HWM only increases, never decreases
- DrawdownTracker.update(): "balance" mode uses balance, not equity
- DrawdownTracker.update(): day rollover resets daily_open
- DrawdownTracker.record_fill(): accumulates realised PnL
- DrawdownTracker.check_modify(): allows OK modification
- DrawdownTracker.check_modify(): rejects modification when SL too wide
- DrawdownTracker.check_modify(): rejects when daily breach already active
- DrawdownTracker.check_modify(): rejects invalid account balance
- DrawdownTracker.status(): returns correct dict keys
- DrawdownTracker properties: total_hwm, daily_open, daily_realised_pnl
- DrawdownResult dataclass fields
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from risk.drawdown_tracker import DrawdownResult, DrawdownTracker

UTC = timezone.utc


# ── helpers ───────────────────────────────────────────────────────────────────

def _make_tracker(
    initial_balance: float = 100_000.0,
    max_total_dd_pct: float = 0.10,
    max_daily_dd_pct: float = 0.05,
    mode: str = "equity",
) -> DrawdownTracker:
    return DrawdownTracker(
        initial_balance=initial_balance,
        max_total_dd_pct=max_total_dd_pct,
        max_daily_dd_pct=max_daily_dd_pct,
        drawdown_mode=mode,
        alert_pct_of_limit=0.80,
    )


# ── DrawdownResult ────────────────────────────────────────────────────────────

@pytest.mark.unit
class TestDrawdownResult:
    def test_fields_are_populated(self):
        result = DrawdownResult(
            equity=99_000.0,
            balance=99_500.0,
            total_drawdown_pct=0.01,
            total_hwm=100_000.0,
            total_breach=False,
            total_alert=False,
            daily_drawdown_pct=0.005,
            daily_open=100_000.0,
            daily_breach=False,
            daily_alert=False,
            drawdown_mode="equity",
        )
        assert result.equity == 99_000.0
        assert result.drawdown_mode == "equity"
        assert isinstance(result.timestamp, str)


# ── Normal update (no breach) ─────────────────────────────────────────────────

@pytest.mark.unit
class TestDrawdownTrackerNormal:
    def test_initial_update_no_breach(self):
        tracker = _make_tracker()
        result = tracker.update(equity=100_000.0, balance=100_000.0)
        assert result.total_breach is False
        assert result.daily_breach is False
        assert result.total_drawdown_pct == 0.0
        assert result.daily_drawdown_pct == 0.0

    def test_small_drawdown_no_breach(self):
        tracker = _make_tracker(max_total_dd_pct=0.10)
        result = tracker.update(equity=95_000.0, balance=95_000.0)
        assert result.total_breach is False
        assert abs(result.total_drawdown_pct - 0.05) < 0.001

    def test_equity_above_initial_sets_hwm(self):
        tracker = _make_tracker(initial_balance=100_000.0)
        tracker.update(equity=110_000.0, balance=110_000.0)
        assert tracker.total_hwm == 110_000.0

    def test_hwm_never_decreases(self):
        tracker = _make_tracker()
        tracker.update(equity=110_000.0, balance=110_000.0)
        tracker.update(equity=90_000.0, balance=90_000.0)
        assert tracker.total_hwm == 110_000.0

    def test_total_drawdown_measured_from_hwm(self):
        tracker = _make_tracker()
        tracker.update(equity=110_000.0, balance=110_000.0)
        result = tracker.update(equity=99_000.0, balance=99_000.0)
        # 11_000 / 110_000 = 10%
        assert abs(result.total_drawdown_pct - 0.10) < 0.001

    def test_status_returns_dict(self):
        tracker = _make_tracker()
        tracker.update(equity=100_000.0, balance=100_000.0)
        status = tracker.status()
        assert "total_hwm" in status
        assert "total_drawdown_pct" in status
        assert "daily_drawdown_pct" in status
        assert "drawdown_mode" in status


# ── Total drawdown breach ─────────────────────────────────────────────────────

@pytest.mark.unit
class TestTotalDrawdownBreach:
    def test_breach_triggered_at_threshold(self):
        tracker = _make_tracker(max_total_dd_pct=0.10)
        result = tracker.update(equity=89_000.0, balance=89_000.0)
        assert result.total_breach is True

    def test_exactly_at_threshold_is_breach(self):
        tracker = _make_tracker(max_total_dd_pct=0.10)
        result = tracker.update(equity=90_000.0, balance=90_000.0)
        assert result.total_breach is True  # 10_000/100_000 = 10% >= 10%

    def test_alert_before_breach(self):
        """Alert triggers at 80% of limit (e.g. 9% drawdown when limit=10% → 90% of limit)."""
        tracker = _make_tracker(max_total_dd_pct=0.10)
        # 9% drawdown = 90% of 10% limit → above 80% alert threshold, below breach
        result = tracker.update(equity=91_000.0, balance=91_000.0)
        assert result.total_alert is True
        assert result.total_breach is False

    def test_no_alert_below_threshold(self):
        tracker = _make_tracker(max_total_dd_pct=0.10)
        result = tracker.update(equity=98_000.0, balance=98_000.0)
        assert result.total_alert is False
        assert result.total_breach is False


# ── Daily drawdown breach ─────────────────────────────────────────────────────

@pytest.mark.unit
class TestDailyDrawdownBreach:
    def test_daily_breach_equity_mode(self):
        tracker = _make_tracker(max_daily_dd_pct=0.05)
        # 5% daily drawdown from 100_000 = 95_000
        result = tracker.update(equity=95_000.0, balance=95_000.0)
        assert result.daily_breach is True

    def test_daily_alert_before_breach(self):
        tracker = _make_tracker(max_daily_dd_pct=0.05)
        # 4.5% drawdown = 90% of 5% limit → clearly above 80% alert threshold, below breach
        result = tracker.update(equity=95_500.0, balance=95_500.0)
        assert result.daily_alert is True
        assert result.daily_breach is False

    def test_daily_mode_balance_uses_balance(self):
        tracker = _make_tracker(max_daily_dd_pct=0.05, mode="balance")
        # equity is OK but balance is at 5% drawdown
        result = tracker.update(equity=100_000.0, balance=95_000.0)
        assert result.daily_breach is True

    def test_daily_mode_equity_ignores_balance(self):
        tracker = _make_tracker(max_daily_dd_pct=0.05, mode="equity")
        # balance drops but equity doesn't
        result = tracker.update(equity=100_000.0, balance=90_000.0)
        assert result.daily_breach is False


# ── Day rollover ──────────────────────────────────────────────────────────────

@pytest.mark.unit
class TestDayRollover:
    def test_day_rollover_resets_daily_open(self):
        tracker = _make_tracker()
        # Set equity at end of day 1
        tracker.update(equity=105_000.0, balance=105_000.0)

        # Simulate tomorrow's first update
        tomorrow = datetime.now(UTC) + timedelta(days=1)
        with patch("risk.drawdown_tracker.datetime") as mock_dt:
            mock_dt.now.return_value = tomorrow
            result = tracker.update(equity=104_000.0, balance=104_000.0)
        # Daily drawdown should be from new 104_000 anchor, not 100_000
        assert result.daily_drawdown_pct == 0.0  # starts fresh


# ── record_fill ───────────────────────────────────────────────────────────────

@pytest.mark.unit
class TestRecordFill:
    def test_record_fill_accumulates_pnl(self):
        tracker = _make_tracker()
        tracker.record_fill(pnl=-500.0)
        tracker.record_fill(pnl=-300.0)
        assert tracker.daily_realised_pnl == -800.0

    def test_record_fill_with_balance_after(self):
        tracker = _make_tracker()
        tracker.record_fill(pnl=-500.0, balance_after=99_500.0)
        assert tracker.daily_realised_pnl == -500.0


# ── check_modify ──────────────────────────────────────────────────────────────

@pytest.mark.unit
class TestCheckModify:
    def test_ok_modification(self):
        tracker = _make_tracker()
        ok, reason = tracker.check_modify(
            current_equity=100_000.0,
            new_stop_loss_distance=0.001,
            lots=0.1,
            account_balance=100_000.0,
        )
        assert ok is True
        assert reason == "OK"

    def test_rejects_excessive_risk(self):
        tracker = _make_tracker()
        # stop=100 × lots=100 × pip_value=1.0 = 10_000 risk on 100_000 = 10% > 5% limit
        ok, reason = tracker.check_modify(
            current_equity=100_000.0,
            new_stop_loss_distance=100.0,
            lots=100.0,
            account_balance=100_000.0,
        )
        assert ok is False
        assert "risk" in reason.lower() or "max" in reason.lower()

    def test_rejects_invalid_balance(self):
        tracker = _make_tracker()
        ok, reason = tracker.check_modify(
            current_equity=100_000.0,
            new_stop_loss_distance=0.001,
            lots=0.1,
            account_balance=0.0,
        )
        assert ok is False
        assert "balance" in reason.lower() or "invalid" in reason.lower()

    def test_rejects_when_already_in_daily_breach(self):
        tracker = _make_tracker(max_daily_dd_pct=0.05)
        # Drive into daily breach first
        tracker.update(equity=90_000.0, balance=90_000.0)
        ok, reason = tracker.check_modify(
            current_equity=90_000.0,
            new_stop_loss_distance=0.001,
            lots=0.01,
            account_balance=90_000.0,
        )
        assert ok is False


# ── Properties ────────────────────────────────────────────────────────────────

@pytest.mark.unit
class TestDrawdownTrackerProperties:
    def test_total_hwm_property(self):
        tracker = _make_tracker(initial_balance=100_000.0)
        tracker.update(equity=120_000.0, balance=120_000.0)
        assert tracker.total_hwm == 120_000.0

    def test_daily_open_property(self):
        tracker = _make_tracker(initial_balance=100_000.0)
        assert tracker.daily_open == 100_000.0

    def test_current_daily_dd_property(self):
        tracker = _make_tracker()
        tracker.update(equity=98_000.0, balance=98_000.0)
        assert abs(tracker.current_daily_dd - 0.02) < 0.001

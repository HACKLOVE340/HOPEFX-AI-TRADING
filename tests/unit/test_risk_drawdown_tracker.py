# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""Tests for risk/drawdown_tracker.py — DrawdownTracker, DrawdownResult."""

from __future__ import annotations

import pytest

from risk.drawdown_tracker import DrawdownResult, DrawdownTracker


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _tracker(
    initial_balance: float = 100_000.0,
    max_total_dd_pct: float = 0.10,
    max_daily_dd_pct: float = 0.05,
    drawdown_mode: str = "equity",
    alert_pct_of_limit: float = 0.80,
) -> DrawdownTracker:
    return DrawdownTracker(
        initial_balance=initial_balance,
        max_total_dd_pct=max_total_dd_pct,
        max_daily_dd_pct=max_daily_dd_pct,
        drawdown_mode=drawdown_mode,
        alert_pct_of_limit=alert_pct_of_limit,
    )


# ---------------------------------------------------------------------------
# DrawdownResult dataclass
# ---------------------------------------------------------------------------


class TestDrawdownResult:
    def test_fields(self):
        r = DrawdownResult(
            equity=99_000.0,
            balance=99_000.0,
            total_drawdown_pct=0.01,
            total_hwm=100_000.0,
            total_breach=False,
            total_alert=False,
            daily_drawdown_pct=0.01,
            daily_open=100_000.0,
            daily_breach=False,
            daily_alert=False,
            drawdown_mode="equity",
        )
        assert r.equity == pytest.approx(99_000.0)
        assert r.total_breach is False
        assert r.drawdown_mode == "equity"

    def test_timestamp_auto_set(self):
        r = DrawdownResult(
            equity=100_000.0,
            balance=100_000.0,
            total_drawdown_pct=0.0,
            total_hwm=100_000.0,
            total_breach=False,
            total_alert=False,
            daily_drawdown_pct=0.0,
            daily_open=100_000.0,
            daily_breach=False,
            daily_alert=False,
            drawdown_mode="equity",
        )
        assert r.timestamp != ""


# ---------------------------------------------------------------------------
# DrawdownTracker construction
# ---------------------------------------------------------------------------


class TestDrawdownTrackerInit:
    def test_defaults(self):
        t = _tracker()
        assert t.max_total_dd_pct == pytest.approx(0.10)
        assert t.max_daily_dd_pct == pytest.approx(0.05)
        assert t.drawdown_mode == "equity"
        assert t.alert_pct_of_limit == pytest.approx(0.80)

    def test_initial_hwm(self):
        t = _tracker(initial_balance=50_000.0)
        assert t.total_hwm == pytest.approx(50_000.0)

    def test_initial_daily_open(self):
        t = _tracker(initial_balance=50_000.0)
        assert t.daily_open == pytest.approx(50_000.0)

    def test_balance_mode(self):
        t = _tracker(drawdown_mode="balance")
        assert t.drawdown_mode == "balance"


# ---------------------------------------------------------------------------
# update() — basic behavior
# ---------------------------------------------------------------------------


class TestUpdate:
    def test_returns_drawdown_result(self):
        t = _tracker()
        result = t.update(equity=100_000.0)
        assert isinstance(result, DrawdownResult)

    def test_no_drawdown_at_start(self):
        t = _tracker()
        result = t.update(equity=100_000.0)
        assert result.total_drawdown_pct == pytest.approx(0.0)
        assert result.daily_drawdown_pct == pytest.approx(0.0)
        assert result.total_breach is False
        assert result.daily_breach is False

    def test_balance_defaults_to_equity(self):
        t = _tracker()
        result = t.update(equity=99_000.0)
        assert result.balance == pytest.approx(99_000.0)

    def test_hwm_tracks_peak(self):
        t = _tracker()
        t.update(equity=110_000.0)
        t.update(equity=105_000.0)
        assert t.total_hwm == pytest.approx(110_000.0)

    def test_total_drawdown_computed(self):
        t = _tracker(max_total_dd_pct=0.20)  # high limit so no breach
        t.update(equity=110_000.0)  # raise HWM
        result = t.update(equity=99_000.0)  # ~9.1% below HWM
        assert result.total_drawdown_pct == pytest.approx(11_000 / 110_000, rel=1e-4)

    def test_daily_drawdown_computed(self):
        t = _tracker(max_daily_dd_pct=0.05)
        result = t.update(equity=96_000.0)  # 4% below daily open of 100k
        assert result.daily_drawdown_pct == pytest.approx(0.04, rel=1e-4)

    def test_total_breach_triggered(self):
        t = _tracker(max_total_dd_pct=0.10)
        result = t.update(equity=89_000.0)  # 11% below HWM
        assert result.total_breach is True

    def test_daily_breach_triggered(self):
        t = _tracker(max_daily_dd_pct=0.05)
        result = t.update(equity=94_000.0)  # 6% below daily open
        assert result.daily_breach is True

    def test_total_alert_triggered(self):
        # Alert at 80% of 10% limit = 8%
        t = _tracker(max_total_dd_pct=0.10, alert_pct_of_limit=0.80)
        result = t.update(equity=91_500.0)  # 8.5% below HWM → alert
        assert result.total_alert is True
        assert result.total_breach is False

    def test_daily_alert_triggered(self):
        # Alert at 80% of 5% limit = 4%
        t = _tracker(max_daily_dd_pct=0.05, alert_pct_of_limit=0.80)
        result = t.update(equity=95_500.0)  # 4.5% below daily open → alert
        assert result.daily_alert is True
        assert result.daily_breach is False

    def test_no_alert_when_breach(self):
        t = _tracker(max_total_dd_pct=0.10)
        result = t.update(equity=88_000.0)  # 12% → breach, not alert
        assert result.total_breach is True
        assert result.total_alert is False

    def test_equity_mode_uses_equity_for_daily(self):
        t = _tracker(drawdown_mode="equity")
        result = t.update(equity=95_000.0, balance=98_000.0)
        # Daily DD measured on equity (95k), not balance (98k)
        assert result.daily_drawdown_pct == pytest.approx(0.05, rel=1e-4)

    def test_balance_mode_uses_balance_for_daily(self):
        t = _tracker(drawdown_mode="balance")
        result = t.update(equity=95_000.0, balance=98_000.0)
        # Daily DD measured on balance (98k), not equity (95k)
        assert result.daily_drawdown_pct == pytest.approx(0.02, rel=1e-4)

    def test_drawdown_mode_in_result(self):
        t = _tracker(drawdown_mode="balance")
        result = t.update(equity=100_000.0)
        assert result.drawdown_mode == "balance"


# ---------------------------------------------------------------------------
# update() — day rollover (simulated by manipulating _day)
# ---------------------------------------------------------------------------


class TestDayRollover:
    def test_day_rollover_resets_daily_open_equity_mode(self):
        t = _tracker(drawdown_mode="equity")
        t.update(equity=95_000.0)  # daily open stays at 100k
        # Simulate day change
        t._day = t._day - 1  # force rollover on next update
        result = t.update(equity=95_000.0, balance=95_000.0)
        # After rollover, daily_open = equity = 95k → daily_dd = 0
        assert result.daily_drawdown_pct == pytest.approx(0.0, abs=1e-6)

    def test_day_rollover_resets_daily_open_balance_mode(self):
        t = _tracker(drawdown_mode="balance")
        t._day = t._day - 1  # force rollover
        result = t.update(equity=95_000.0, balance=93_000.0)
        # After rollover in balance mode, daily_open = balance = 93k → daily_dd = 0
        assert result.daily_drawdown_pct == pytest.approx(0.0, abs=1e-6)

    def test_day_rollover_resets_daily_realised_pnl(self):
        t = _tracker()
        t.record_fill(pnl=-500.0)
        assert t.daily_realised_pnl == pytest.approx(-500.0)
        t._day = t._day - 1
        t.update(equity=100_000.0)
        assert t.daily_realised_pnl == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# record_fill()
# ---------------------------------------------------------------------------


class TestRecordFill:
    def test_accumulates_pnl(self):
        t = _tracker()
        t.record_fill(pnl=-200.0)
        t.record_fill(pnl=-300.0)
        assert t.daily_realised_pnl == pytest.approx(-500.0)

    def test_positive_pnl(self):
        t = _tracker()
        t.record_fill(pnl=500.0)
        assert t.daily_realised_pnl == pytest.approx(500.0)

    def test_balance_after_updates_last_balance(self):
        t = _tracker()
        t.record_fill(pnl=-100.0, balance_after=99_900.0)
        assert t._last_balance == pytest.approx(99_900.0)

    def test_balance_after_none_does_not_update(self):
        t = _tracker()
        t.update(equity=100_000.0)
        original_balance = t._last_balance
        t.record_fill(pnl=-100.0, balance_after=None)
        assert t._last_balance == pytest.approx(original_balance)


# ---------------------------------------------------------------------------
# check_modify()
# ---------------------------------------------------------------------------


class TestCheckModify:
    def test_allows_valid_modify(self):
        t = _tracker()
        ok, reason = t.check_modify(
            current_equity=100_000.0,
            new_stop_loss_distance=10.0,
            lots=0.1,
            account_balance=100_000.0,
        )
        assert ok is True
        assert reason == "OK"

    def test_blocks_zero_account_balance(self):
        t = _tracker()
        ok, reason = t.check_modify(
            current_equity=100_000.0,
            new_stop_loss_distance=10.0,
            lots=1.0,
            account_balance=0.0,
        )
        assert ok is False
        assert "balance" in reason.lower()

    def test_blocks_negative_account_balance(self):
        t = _tracker()
        ok, reason = t.check_modify(
            current_equity=100_000.0,
            new_stop_loss_distance=10.0,
            lots=1.0,
            account_balance=-1.0,
        )
        assert ok is False

    def test_blocks_excessive_risk(self):
        t = _tracker()
        # risk_pct = 10_000 * 100 * 1.0 / 100_000 = 10_000% >> 5% max
        ok, reason = t.check_modify(
            current_equity=100_000.0,
            new_stop_loss_distance=10_000.0,
            lots=100.0,
            account_balance=100_000.0,
        )
        assert ok is False
        assert "risk" in reason.lower() or "max" in reason.lower()

    def test_blocks_when_daily_breach(self):
        t = _tracker(max_daily_dd_pct=0.05)
        # Drop 6% to trigger daily breach
        ok, reason = t.check_modify(
            current_equity=93_000.0,
            new_stop_loss_distance=1.0,
            lots=0.01,
            account_balance=100_000.0,
        )
        assert ok is False
        assert "daily" in reason.lower()

    def test_blocks_when_total_breach(self):
        t = _tracker(max_total_dd_pct=0.10, max_daily_dd_pct=0.99)
        # Drop 11% to trigger total breach (daily limit set very high)
        ok, reason = t.check_modify(
            current_equity=89_000.0,
            new_stop_loss_distance=1.0,
            lots=0.01,
            account_balance=100_000.0,
        )
        assert ok is False
        assert "total" in reason.lower()

    def test_pip_value_affects_risk(self):
        t = _tracker()
        # With pip_value=10: risk = 1 * 1 * 10 / 100_000 = 0.01% → OK
        ok, reason = t.check_modify(
            current_equity=100_000.0,
            new_stop_loss_distance=1.0,
            lots=1.0,
            account_balance=100_000.0,
            pip_value=10.0,
        )
        # 10/100000 = 0.01% < 5% max → allowed
        assert ok is True


# ---------------------------------------------------------------------------
# Properties
# ---------------------------------------------------------------------------


class TestProperties:
    def test_total_hwm_property(self):
        t = _tracker(initial_balance=100_000.0)
        t.update(equity=110_000.0)
        assert t.total_hwm == pytest.approx(110_000.0)

    def test_daily_open_property(self):
        t = _tracker(initial_balance=100_000.0)
        assert t.daily_open == pytest.approx(100_000.0)

    def test_daily_realised_pnl_property(self):
        t = _tracker()
        t.record_fill(pnl=-250.0)
        assert t.daily_realised_pnl == pytest.approx(-250.0)

    def test_current_total_dd_zero_at_hwm(self):
        t = _tracker()
        t.update(equity=100_000.0)
        assert t.current_total_dd == pytest.approx(0.0)

    def test_current_total_dd_positive_below_hwm(self):
        t = _tracker()
        t.update(equity=110_000.0)
        t.update(equity=99_000.0)
        assert t.current_total_dd == pytest.approx(11_000 / 110_000, rel=1e-4)

    def test_current_total_dd_zero_when_hwm_zero(self):
        t = _tracker()
        t._total_hwm = 0.0
        assert t.current_total_dd == pytest.approx(0.0)

    def test_current_daily_dd_equity_mode(self):
        t = _tracker(drawdown_mode="equity")
        t.update(equity=95_000.0)
        assert t.current_daily_dd == pytest.approx(0.05, rel=1e-4)

    def test_current_daily_dd_balance_mode(self):
        t = _tracker(drawdown_mode="balance")
        t.update(equity=95_000.0, balance=98_000.0)
        assert t.current_daily_dd == pytest.approx(0.02, rel=1e-4)

    def test_current_daily_dd_zero_when_anchor_zero(self):
        t = _tracker()
        t._daily_open = 0.0
        assert t.current_daily_dd == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# status()
# ---------------------------------------------------------------------------


class TestStatus:
    def test_status_keys(self):
        t = _tracker()
        s = t.status()
        assert "total_hwm" in s
        assert "total_drawdown_pct" in s
        assert "max_total_dd_pct" in s
        assert "daily_open" in s
        assert "daily_drawdown_pct" in s
        assert "max_daily_dd_pct" in s
        assert "daily_realised_pnl" in s
        assert "drawdown_mode" in s
        assert "last_equity" in s
        assert "last_balance" in s

    def test_status_values(self):
        t = _tracker(initial_balance=100_000.0)
        t.update(equity=95_000.0)
        s = t.status()
        assert s["last_equity"] == pytest.approx(95_000.0)
        assert s["total_hwm"] == pytest.approx(100_000.0)
        assert s["drawdown_mode"] == "equity"

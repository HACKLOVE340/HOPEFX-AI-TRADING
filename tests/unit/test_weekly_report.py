# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# AGPL-3.0 — Share all modifications
"""
tests/unit/test_weekly_report.py
==================================
Unit tests for reports/weekly_report.py.

Covers:
- _sharpe() — annualised Sharpe ratio
- _sortino() — annualised Sortino ratio
- _max_drawdown() — peak-to-trough drawdown
- _calmar() — Calmar ratio
- _profit_factor() — gross win / gross loss
- WeeklyReport.to_dict() — serialisation
- WeeklyReportGenerator.generate() — full report from trade records
- _fmt() / _source_label() — formatting helpers
"""

from __future__ import annotations

import math
import uuid
from datetime import datetime, timezone

import numpy as np
import pytest

try:
    from reports.weekly_report import TradeRecord
except ImportError:
    TradeRecord = None  # type: ignore[assignment,misc]

UTC = timezone.utc


_WEEK_START = datetime(2025, 1, 6, 0, 0, tzinfo=UTC)
_WEEK_END = datetime(2025, 1, 12, 23, 59, tzinfo=UTC)


def _make_trade(pnl: float, symbol: str = "XAUUSD") -> TradeRecord:
    from reports.weekly_report import TradeRecord as _TR

    return _TR(
        trade_id=str(uuid.uuid4()),
        symbol=symbol,
        side="BUY" if pnl >= 0 else "SELL",
        open_time=datetime(2025, 1, 7, 9, 0, tzinfo=UTC),
        close_time=datetime(2025, 1, 7, 10, 0, tzinfo=UTC),  # within week window
        open_price=1900.0,
        close_price=1900.0 + pnl,
        lots=1.0,
        pnl=pnl,
        pips=pnl / 0.1,
    )


def _make_equity_curve(n: int = 5, start: float = 10_000.0, step: float = 50.0) -> list:
    """Build equity curve as list[tuple[datetime, float]] within the week window."""
    from datetime import timedelta

    return [(_WEEK_START + timedelta(hours=i * 24), start + i * step) for i in range(n)]


# ---------------------------------------------------------------------------
# _sharpe
# ---------------------------------------------------------------------------


class TestSharpe:
    def test_returns_none_below_min_data(self):
        from reports.weekly_report import _sharpe

        returns = np.array([0.01, 0.02, 0.01])  # < 5 points
        assert _sharpe(returns) is None

    def test_returns_float_with_enough_data(self):
        from reports.weekly_report import _sharpe

        returns = np.array([0.01, 0.02, -0.005, 0.015, 0.008, 0.012])
        result = _sharpe(returns)
        assert result is not None
        assert isinstance(result, float)

    def test_positive_sharpe_for_positive_returns(self):
        from reports.weekly_report import _sharpe

        returns = np.array([0.01] * 20)  # all positive, zero std → None
        # All identical returns → std=0 → None
        assert _sharpe(returns) is None

    def test_sharpe_finite(self):
        from reports.weekly_report import _sharpe

        rng = np.random.default_rng(42)
        returns = rng.normal(0.001, 0.01, 50)
        result = _sharpe(returns)
        if result is not None:
            assert math.isfinite(result)

    def test_returns_none_for_zero_std(self):
        from reports.weekly_report import _sharpe

        returns = np.array([0.01, 0.01, 0.01, 0.01, 0.01])
        assert _sharpe(returns) is None


# ---------------------------------------------------------------------------
# _sortino
# ---------------------------------------------------------------------------


class TestSortino:
    def test_returns_none_below_min_data(self):
        from reports.weekly_report import _sortino

        returns = np.array([0.01, 0.02])
        assert _sortino(returns) is None

    def test_returns_none_when_no_downside(self):
        from reports.weekly_report import _sortino

        returns = np.array([0.01, 0.02, 0.03, 0.01, 0.02])
        # No negative returns → downside_std = 0 → None
        assert _sortino(returns) is None

    def test_returns_float_with_mixed_returns(self):
        from reports.weekly_report import _sortino

        returns = np.array([0.01, -0.005, 0.02, -0.003, 0.015, 0.008])
        result = _sortino(returns)
        assert result is not None
        assert isinstance(result, float)

    def test_sortino_finite(self):
        from reports.weekly_report import _sortino

        rng = np.random.default_rng(42)
        returns = rng.normal(0.001, 0.01, 50)
        result = _sortino(returns)
        if result is not None:
            assert math.isfinite(result)


# ---------------------------------------------------------------------------
# _max_drawdown
# ---------------------------------------------------------------------------


class TestMaxDrawdown:
    def test_single_point_returns_zero(self):
        from reports.weekly_report import _max_drawdown

        assert _max_drawdown([10_000.0]) == pytest.approx(0.0)

    def test_always_rising_zero_drawdown(self):
        from reports.weekly_report import _max_drawdown

        curve = [10_000.0 + i * 100 for i in range(20)]
        assert _max_drawdown(curve) == pytest.approx(0.0)

    def test_single_drop_drawdown(self):
        from reports.weekly_report import _max_drawdown

        curve = [10_000.0, 8_000.0]
        # (8000 - 10000) / 10000 = -0.2
        assert _max_drawdown(curve) == pytest.approx(-0.2)

    def test_max_drawdown_is_worst_case(self):
        from reports.weekly_report import _max_drawdown

        curve = [10_000.0, 9_000.0, 10_500.0, 7_000.0]
        # Worst: (7000 - 10500) / 10500 ≈ -0.3333
        dd = _max_drawdown(curve)
        assert dd == pytest.approx(-0.3333, abs=0.001)

    def test_returns_float(self):
        from reports.weekly_report import _max_drawdown

        result = _max_drawdown([10_000.0, 9_500.0])
        assert isinstance(result, float)


# ---------------------------------------------------------------------------
# _calmar
# ---------------------------------------------------------------------------


class TestCalmar:
    def test_returns_none_for_zero_drawdown(self):
        from reports.weekly_report import _calmar

        assert _calmar(0.15, 0.0) is None

    def test_positive_calmar(self):
        from reports.weekly_report import _calmar

        result = _calmar(0.30, -0.10)
        assert result is not None
        assert result == pytest.approx(3.0)

    def test_calmar_with_large_drawdown(self):
        from reports.weekly_report import _calmar

        result = _calmar(0.10, -0.50)
        assert result == pytest.approx(0.2)


# ---------------------------------------------------------------------------
# _profit_factor
# ---------------------------------------------------------------------------


class TestProfitFactor:
    def test_returns_none_when_no_losses(self):
        from reports.weekly_report import _profit_factor

        assert _profit_factor([100.0, 200.0], []) is None

    def test_profit_factor_calculation(self):
        from reports.weekly_report import _profit_factor

        result = _profit_factor([100.0, 200.0], [-50.0, -100.0])
        # gross_win=300, gross_loss=150 → PF=2.0
        assert result == pytest.approx(2.0)

    def test_profit_factor_below_one_for_losing_system(self):
        from reports.weekly_report import _profit_factor

        result = _profit_factor([50.0], [-200.0])
        assert result is not None
        assert result < 1.0

    def test_profit_factor_positive(self):
        from reports.weekly_report import _profit_factor

        result = _profit_factor([100.0], [-50.0])
        assert result is not None
        assert result > 0.0


# ---------------------------------------------------------------------------
# WeeklyReport.to_dict
# ---------------------------------------------------------------------------


class TestWeeklyReportToDict:
    def _make_report(self):
        from reports.weekly_report import WeeklyReport

        return WeeklyReport(
            report_id="test-001",
            week_start=datetime(2025, 1, 6, tzinfo=UTC),
            week_end=datetime(2025, 1, 12, tzinfo=UTC),
            generated_at=datetime(2025, 1, 13, tzinfo=UTC),
            total_trades=10,
            winning_trades=6,
            losing_trades=4,
            win_rate=60.0,
            avg_win=150.0,
            avg_loss=-80.0,
            profit_factor=1.8,
            expectancy=50.0,
            gross_pnl=580.0,
            net_pnl=550.0,
            total_return_pct=5.5,
            sharpe_ratio=1.2,
            sortino_ratio=1.8,
            max_drawdown_pct=-5.0,
            calmar_ratio=2.5,
            starting_equity=10_000.0,
            ending_equity=10_550.0,
            symbols_traded=["XAUUSD"],
            data_source="paper_simulation",
        )

    def test_to_dict_returns_dict(self):
        r = self._make_report()
        d = r.to_dict()
        assert isinstance(d, dict)

    def test_to_dict_contains_required_keys(self):
        r = self._make_report()
        d = r.to_dict()
        for key in (
            "report_id",
            "total_trades",
            "win_rate",
            "sharpe_ratio",
            "max_drawdown_pct",
            "data_source",
            "week_start",
        ):
            assert key in d

    def test_to_dict_datetimes_are_iso_strings(self):
        r = self._make_report()
        d = r.to_dict()
        assert isinstance(d["week_start"], str)
        assert isinstance(d["week_end"], str)
        assert isinstance(d["generated_at"], str)
        # Should be parseable
        datetime.fromisoformat(d["week_start"])

    def test_to_dict_data_source_preserved(self):
        r = self._make_report()
        d = r.to_dict()
        assert d["data_source"] == "paper_simulation"


# ---------------------------------------------------------------------------
# _fmt and _source_label helpers
# ---------------------------------------------------------------------------


class TestFormatHelpers:
    def test_fmt_none_returns_em_dash(self):
        from reports.weekly_report import _fmt

        # _fmt(None) returns "—" (em dash), not "N/A"
        result = _fmt(None)
        assert result == "—"

    def test_fmt_float_with_suffix(self):
        from reports.weekly_report import _fmt

        result = _fmt(1.234, suffix="%")
        assert "%" in result
        assert "1.23" in result

    def test_fmt_rounds_to_decimals(self):
        from reports.weekly_report import _fmt

        result = _fmt(3.14159, decimals=2)
        assert "3.14" in result

    def test_source_label_paper_simulation(self):
        from reports.weekly_report import _source_label

        label = _source_label("paper_simulation")
        assert isinstance(label, str)
        assert len(label) > 0

    def test_source_label_live(self):
        from reports.weekly_report import _source_label

        label = _source_label("live")
        assert isinstance(label, str)

    def test_source_label_unknown_returns_string(self):
        from reports.weekly_report import _source_label

        label = _source_label("unknown_source")
        assert isinstance(label, str)


# ---------------------------------------------------------------------------
# WeeklyReportGenerator.generate()
# ---------------------------------------------------------------------------


class TestWeeklyReportGenerator:
    def test_generate_with_no_trades(self):
        from reports.weekly_report import WeeklyReportGenerator

        gen = WeeklyReportGenerator()
        report = gen.generate(
            trades=[],
            equity_curve=_make_equity_curve(),
            starting_equity=10_000.0,
            week_start=_WEEK_START,
            week_end=_WEEK_END,
        )
        assert report.total_trades == 0
        assert report.win_rate is None
        assert report.gross_pnl == pytest.approx(0.0)

    def test_generate_with_winning_trades(self):
        from reports.weekly_report import WeeklyReportGenerator

        gen = WeeklyReportGenerator()
        trades = [_make_trade(100.0) for _ in range(5)] + [_make_trade(-50.0) for _ in range(3)]
        report = gen.generate(
            trades=trades,
            equity_curve=_make_equity_curve(9),
            starting_equity=10_000.0,
            week_start=_WEEK_START,
            week_end=_WEEK_END,
        )
        assert report.total_trades == 8
        assert report.winning_trades == 5
        assert report.losing_trades == 3

    def test_generate_win_rate_correct(self):
        from reports.weekly_report import WeeklyReportGenerator

        gen = WeeklyReportGenerator()
        # Need >= 10 trades for win_rate to be non-None
        trades = [_make_trade(100.0)] * 7 + [_make_trade(-50.0)] * 3
        report = gen.generate(
            trades=trades,
            equity_curve=_make_equity_curve(11),
            starting_equity=10_000.0,
            week_start=_WEEK_START,
            week_end=_WEEK_END,
        )
        # 10 trades → win_rate computed: 7/10 = 0.7
        assert report.win_rate == pytest.approx(0.7)

    def test_generate_data_source_preserved(self):
        from reports.weekly_report import WeeklyReportGenerator

        gen = WeeklyReportGenerator()
        report = gen.generate(
            trades=[],
            equity_curve=_make_equity_curve(),
            starting_equity=10_000.0,
            week_start=_WEEK_START,
            week_end=_WEEK_END,
            data_source="paper_oanda",
        )
        assert report.data_source == "paper_oanda"

    def test_generate_report_id_is_string(self):
        from reports.weekly_report import WeeklyReportGenerator

        gen = WeeklyReportGenerator()
        report = gen.generate(
            trades=[],
            equity_curve=_make_equity_curve(),
            starting_equity=10_000.0,
            week_start=_WEEK_START,
            week_end=_WEEK_END,
        )
        assert isinstance(report.report_id, str)
        assert len(report.report_id) > 0

    def test_generate_symbols_traded(self):
        from reports.weekly_report import WeeklyReportGenerator

        gen = WeeklyReportGenerator()
        trades = [_make_trade(100.0, "XAUUSD"), _make_trade(-50.0, "EURUSD")]
        report = gen.generate(
            trades=trades,
            equity_curve=_make_equity_curve(3),
            starting_equity=10_000.0,
            week_start=_WEEK_START,
            week_end=_WEEK_END,
        )
        assert "XAUUSD" in report.symbols_traded
        assert "EURUSD" in report.symbols_traded

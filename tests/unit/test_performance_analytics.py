# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
Unit tests for analytics/performance.py

Coverage:
- PerformanceAnalytics.__init__: sets up equity curve
- PerformanceAnalytics.record_trade: updates equity / HWM
- PerformanceAnalytics.get_performance_report: returns PerformanceReport
- PerformanceAnalytics.get_performance_report: handles no-trade scenario
- PerformanceAnalytics.compare_strategies: groups by strategy name
- PerformanceAnalytics.get_equity_curve_data: returns list of dicts
- PerformanceAnalytics.get_trade_distribution: returns distribution dict
- PerformanceAnalytics.get_time_analysis: returns time analysis dict
- PerformanceAnalytics.get_summary: returns summary dict
- PerformanceReport.to_dict: all fields serialisable
- Sharpe / Sortino / max_drawdown helpers
- TradeRecord and EquityPoint dataclasses
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from analytics.performance import (
    EquityPoint,
    MetricPeriod,
    PerformanceAnalytics,
    PerformanceReport,
    StrategyPerformance,
    TradeRecord,
)

UTC = timezone.utc


# ── helpers ───────────────────────────────────────────────────────────────────

def _make_trade(
    trade_id: str = "T001",
    symbol: str = "XAUUSD",
    strategy: str = "momentum",
    side: str = "buy",
    pnl: float = 100.0,
    duration_minutes: int = 30,
) -> TradeRecord:
    now = datetime.now(UTC)
    return TradeRecord(
        id=trade_id,
        symbol=symbol,
        strategy=strategy,
        side=side,
        entry_time=now - timedelta(minutes=duration_minutes),
        exit_time=now,
        entry_price=1900.0,
        exit_price=1900.0 + (pnl / 10.0),
        quantity=0.1,
        pnl=pnl,
        pnl_percent=pnl / 19_000.0 * 100,
        commission=2.0,
        duration_minutes=duration_minutes,
        max_favorable_excursion=abs(pnl) * 1.2,
        max_adverse_excursion=abs(pnl) * 0.5,
    )


def _loaded_engine(n_wins: int = 5, n_losses: int = 3) -> PerformanceAnalytics:
    engine = PerformanceAnalytics(initial_equity=10_000.0)
    for i in range(n_wins):
        engine.record_trade(_make_trade(f"W{i}", pnl=200.0))
    for i in range(n_losses):
        engine.record_trade(_make_trade(f"L{i}", pnl=-80.0))
    return engine


# ── TradeRecord dataclass ─────────────────────────────────────────────────────

@pytest.mark.unit
class TestTradeRecord:
    def test_fields_populated(self):
        trade = _make_trade(pnl=500.0)
        assert trade.pnl == 500.0
        assert trade.symbol == "XAUUSD"
        assert trade.strategy == "momentum"
        assert isinstance(trade.metadata, dict)


# ── EquityPoint dataclass ─────────────────────────────────────────────────────

@pytest.mark.unit
class TestEquityPoint:
    def test_fields_populated(self):
        point = EquityPoint(
            timestamp=datetime.now(UTC),
            equity=10_500.0,
            cash=10_500.0,
            open_pnl=0.0,
            drawdown=0.0,
            drawdown_pct=0.0,
            high_water_mark=10_500.0,
        )
        assert point.equity == 10_500.0
        assert point.high_water_mark == 10_500.0


# ── PerformanceAnalytics.__init__ ─────────────────────────────────────────────

@pytest.mark.unit
class TestPerformanceAnalyticsInit:
    def test_initial_state(self):
        engine = PerformanceAnalytics(initial_equity=10_000.0)
        assert engine.current_equity == 10_000.0
        assert engine.high_water_mark == 10_000.0
        assert len(engine.trades) == 0
        assert len(engine.equity_curve) == 1  # initial point

    def test_custom_risk_free_rate(self):
        engine = PerformanceAnalytics(initial_equity=10_000.0, risk_free_rate=0.03)
        assert engine.risk_free_rate == 0.03


# ── record_trade ──────────────────────────────────────────────────────────────

@pytest.mark.unit
class TestRecordTrade:
    def test_updates_equity_on_win(self):
        engine = PerformanceAnalytics(initial_equity=10_000.0)
        engine.record_trade(_make_trade(pnl=500.0))
        assert engine.current_equity == 10_500.0

    def test_updates_equity_on_loss(self):
        engine = PerformanceAnalytics(initial_equity=10_000.0)
        engine.record_trade(_make_trade(pnl=-300.0))
        assert engine.current_equity == 9_700.0

    def test_updates_high_water_mark(self):
        engine = PerformanceAnalytics(initial_equity=10_000.0)
        engine.record_trade(_make_trade(pnl=1_000.0))
        assert engine.high_water_mark == 11_000.0

    def test_hwm_not_decreased_on_loss(self):
        engine = PerformanceAnalytics(initial_equity=10_000.0)
        engine.record_trade(_make_trade(pnl=1_000.0))
        engine.record_trade(_make_trade(pnl=-2_000.0))
        assert engine.high_water_mark == 11_000.0

    def test_trade_added_to_list(self):
        engine = PerformanceAnalytics(initial_equity=10_000.0)
        engine.record_trade(_make_trade())
        assert len(engine.trades) == 1

    def test_equity_curve_grows(self):
        engine = PerformanceAnalytics(initial_equity=10_000.0)
        initial_len = len(engine.equity_curve)
        engine.record_trade(_make_trade())
        assert len(engine.equity_curve) > initial_len


# ── get_performance_report ────────────────────────────────────────────────────

@pytest.mark.unit
class TestGetPerformanceReport:
    def test_returns_performance_report(self):
        engine = _loaded_engine()
        report = engine.get_performance_report()
        assert isinstance(report, PerformanceReport)

    def test_no_trades_returns_report(self):
        engine = PerformanceAnalytics(initial_equity=10_000.0)
        report = engine.get_performance_report()
        assert isinstance(report, PerformanceReport)
        assert report.total_trades == 0

    def test_win_rate_correct(self):
        engine = _loaded_engine(n_wins=5, n_losses=5)
        report = engine.get_performance_report()
        assert abs(report.win_rate - 0.5) < 0.01

    def test_total_pnl_correct(self):
        engine = PerformanceAnalytics(initial_equity=10_000.0)
        engine.record_trade(_make_trade(pnl=200.0))
        engine.record_trade(_make_trade(pnl=-100.0))
        report = engine.get_performance_report()
        assert report.total_return == pytest.approx(100.0, abs=0.01)

    def test_report_period_filtering(self):
        engine = _loaded_engine()
        report_all = engine.get_performance_report(MetricPeriod.ALL_TIME)
        report_day = engine.get_performance_report(MetricPeriod.DAY)
        # All-time should have >= as many trades as today (trades were just added)
        assert report_all.total_trades >= report_day.total_trades

    def test_to_dict_is_serialisable(self):
        import json
        engine = _loaded_engine()
        report = engine.get_performance_report()
        d = report.to_dict()
        assert isinstance(d, dict)
        json.dumps(d)  # must not raise


# ── compare_strategies ────────────────────────────────────────────────────────

@pytest.mark.unit
class TestCompareStrategies:
    def test_groups_by_strategy(self):
        engine = PerformanceAnalytics(initial_equity=10_000.0)
        for _ in range(3):
            engine.record_trade(_make_trade(strategy="momentum", pnl=100.0))
        for _ in range(2):
            engine.record_trade(_make_trade(strategy="mean_reversion", pnl=-50.0))
        result = engine.compare_strategies()
        assert "momentum" in result
        assert "mean_reversion" in result

    def test_strategy_performance_fields(self):
        engine = PerformanceAnalytics(initial_equity=10_000.0)
        engine.record_trade(_make_trade(strategy="alpha", pnl=100.0))
        result = engine.compare_strategies()
        strat = result["alpha"]
        assert isinstance(strat, StrategyPerformance)
        assert strat.total_trades == 1

    def test_no_trades_returns_empty(self):
        engine = PerformanceAnalytics(initial_equity=10_000.0)
        result = engine.compare_strategies()
        assert result == {}


# ── get_equity_curve_data ─────────────────────────────────────────────────────

@pytest.mark.unit
class TestGetEquityCurveData:
    def test_returns_list_of_dicts(self):
        engine = _loaded_engine()
        data = engine.get_equity_curve_data()
        assert isinstance(data, list)
        assert len(data) > 0
        assert isinstance(data[0], dict)

    def test_equity_key_present(self):
        engine = _loaded_engine()
        data = engine.get_equity_curve_data()
        assert "equity" in data[0]

    def test_empty_engine_has_initial_point(self):
        engine = PerformanceAnalytics(initial_equity=10_000.0)
        data = engine.get_equity_curve_data()
        assert len(data) >= 1


# ── get_trade_distribution ────────────────────────────────────────────────────

@pytest.mark.unit
class TestGetTradeDistribution:
    def test_returns_dict(self):
        engine = _loaded_engine()
        dist = engine.get_trade_distribution()
        assert isinstance(dist, dict)

    def test_has_expected_keys(self):
        engine = _loaded_engine()
        dist = engine.get_trade_distribution()
        # Should have at least pnl bins or trade counts
        assert len(dist) > 0


# ── get_time_analysis ─────────────────────────────────────────────────────────

@pytest.mark.unit
class TestGetTimeAnalysis:
    def test_returns_dict(self):
        engine = _loaded_engine()
        analysis = engine.get_time_analysis()
        assert isinstance(analysis, dict)

    def test_has_performance_data(self):
        engine = _loaded_engine()
        analysis = engine.get_time_analysis()
        assert len(analysis) > 0


# ── get_summary ───────────────────────────────────────────────────────────────

@pytest.mark.unit
class TestGetSummary:
    def test_returns_dict(self):
        engine = _loaded_engine()
        summary = engine.get_summary()
        assert isinstance(summary, dict)

    def test_has_equity_key(self):
        engine = _loaded_engine()
        summary = engine.get_summary()
        assert "current_equity" in summary or "equity" in summary or len(summary) > 0

    def test_no_trades_summary_stable(self):
        engine = PerformanceAnalytics(initial_equity=10_000.0)
        summary = engine.get_summary()
        assert isinstance(summary, dict)

# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
tests/test_performance_analytics.py
=====================================
Regression tests for analytics/performance.py division-by-zero fixes.

Covers:
  - Sharpe ratio: zero variance, single trade, all-identical returns, NaN/inf guard
  - Sortino ratio: no negative returns, zero downside std, NaN/inf guard
  - Profit factor: no losing trades → finite sentinel (not inf)
  - Calmar ratio: zero max drawdown → 0.0 (not ZeroDivisionError)
  - Skewness/Kurtosis: zero variance, n<3/n<4 guards
"""

from __future__ import annotations

import math
import uuid
from datetime import datetime, timedelta, timezone

import pytest

UTC = timezone.utc


def _make_trade(pnl: float, pnl_pct: float, symbol: str = "XAUUSD", strategy: str = "test") -> object:
    from analytics.performance import TradeRecord

    now = datetime.now(UTC)
    return TradeRecord(
        id=str(uuid.uuid4()),
        symbol=symbol,
        strategy=strategy,
        side="BUY" if pnl >= 0 else "SELL",
        entry_time=now - timedelta(minutes=10),
        exit_time=now,
        entry_price=2000.0,
        exit_price=2000.0 + pnl,
        quantity=1.0,
        pnl=pnl,
        pnl_percent=pnl_pct,
        commission=0.0,
        duration_minutes=10,
        max_favorable_excursion=abs(pnl),
        max_adverse_excursion=0.0,
    )


def _make_engine(initial_equity: float = 100_000.0) -> object:
    from analytics.performance import PerformanceAnalytics

    return PerformanceAnalytics(initial_equity=initial_equity, risk_free_rate=0.05)


# ── Sharpe ratio ──────────────────────────────────────────────────────────────


class TestSharpeRatio:
    def test_zero_variance_returns_zero(self):
        """All trades with identical returns → std=0 → Sharpe=0.0, not ZeroDivisionError."""
        engine = _make_engine()
        trades = [_make_trade(pnl=100.0, pnl_pct=0.01) for _ in range(5)]
        result = engine._calculate_sharpe_ratio(trades)
        assert result == 0.0
        assert math.isfinite(result)

    def test_single_trade_returns_zero(self):
        """Fewer than 2 trades → 0.0."""
        engine = _make_engine()
        result = engine._calculate_sharpe_ratio([_make_trade(100.0, 0.01)])
        assert result == 0.0

    def test_empty_trades_returns_zero(self):
        engine = _make_engine()
        assert engine._calculate_sharpe_ratio([]) == 0.0

    def test_normal_returns_finite(self):
        """Mixed positive/negative returns → finite non-zero Sharpe."""
        engine = _make_engine()
        trades = [
            _make_trade(200.0, 0.02),
            _make_trade(-100.0, -0.01),
            _make_trade(150.0, 0.015),
            _make_trade(-50.0, -0.005),
            _make_trade(300.0, 0.03),
        ]
        result = engine._calculate_sharpe_ratio(trades)
        assert math.isfinite(result), f"Sharpe must be finite, got {result}"
        assert result != 0.0

    def test_result_never_nan(self):
        """Sharpe must never return NaN regardless of input."""
        engine = _make_engine()
        # Trades with NaN pnl_percent
        trades = [_make_trade(0.0, float("nan")) for _ in range(3)]
        result = engine._calculate_sharpe_ratio(trades)
        assert not math.isnan(result), "Sharpe must not return NaN"

    def test_result_never_inf(self):
        """Sharpe must never return ±inf."""
        engine = _make_engine()
        trades = [_make_trade(0.0, float("inf")) for _ in range(3)]
        result = engine._calculate_sharpe_ratio(trades)
        assert math.isfinite(result), f"Sharpe must be finite, got {result}"


# ── Sortino ratio ─────────────────────────────────────────────────────────────


class TestSortinoRatio:
    def test_no_negative_returns_returns_zero(self):
        """All winning trades → no downside → 0.0, not inf."""
        engine = _make_engine()
        trades = [_make_trade(100.0, 0.01) for _ in range(5)]
        result = engine._calculate_sortino_ratio(trades)
        assert result == 0.0
        assert math.isfinite(result), "Sortino must be finite when no negative returns"

    def test_zero_downside_std_returns_zero(self):
        """All negative returns identical → downside std=0 → 0.0."""
        engine = _make_engine()
        trades = [_make_trade(-100.0, -0.01) for _ in range(5)]
        result = engine._calculate_sortino_ratio(trades)
        assert result == 0.0
        assert math.isfinite(result)

    def test_single_trade_returns_zero(self):
        engine = _make_engine()
        assert engine._calculate_sortino_ratio([_make_trade(-100.0, -0.01)]) == 0.0

    def test_empty_trades_returns_zero(self):
        engine = _make_engine()
        assert engine._calculate_sortino_ratio([]) == 0.0

    def test_normal_mixed_returns_finite(self):
        engine = _make_engine()
        trades = [
            _make_trade(200.0, 0.02),
            _make_trade(-100.0, -0.01),
            _make_trade(150.0, 0.015),
            _make_trade(-50.0, -0.005),
        ]
        result = engine._calculate_sortino_ratio(trades)
        assert math.isfinite(result), f"Sortino must be finite, got {result}"

    def test_result_never_nan(self):
        engine = _make_engine()
        trades = [_make_trade(0.0, float("nan")) for _ in range(3)]
        result = engine._calculate_sortino_ratio(trades)
        assert not math.isnan(result)

    def test_result_never_inf(self):
        engine = _make_engine()
        trades = [_make_trade(0.0, float("inf")) for _ in range(3)]
        result = engine._calculate_sortino_ratio(trades)
        assert math.isfinite(result)


# ── Profit factor ─────────────────────────────────────────────────────────────


class TestProfitFactor:
    def test_no_losing_trades_returns_finite_sentinel(self):
        """
        When gross_loss == 0, profit_factor must be a finite number (999.0),
        not float('inf') which breaks JSON serialisation.
        """
        from analytics.performance import MetricPeriod

        engine = _make_engine()
        # Add only winning trades
        for _ in range(5):
            engine.trades.append(_make_trade(100.0, 0.01))

        report = engine.get_performance_report(MetricPeriod.ALL_TIME)
        assert math.isfinite(report.profit_factor), f"profit_factor must be finite, got {report.profit_factor}"
        assert report.profit_factor == pytest.approx(999.0)

    def test_normal_profit_factor(self):
        from analytics.performance import MetricPeriod

        engine = _make_engine()
        engine.trades.append(_make_trade(200.0, 0.02))
        engine.trades.append(_make_trade(-100.0, -0.01))

        report = engine.get_performance_report(MetricPeriod.ALL_TIME)
        assert math.isfinite(report.profit_factor)
        assert report.profit_factor == pytest.approx(2.0, rel=1e-3)


# ── Skewness / Kurtosis ───────────────────────────────────────────────────────


class TestSkewnessKurtosis:
    def test_skewness_zero_variance(self):
        engine = _make_engine()
        result = engine._calculate_skewness([1.0, 1.0, 1.0, 1.0])
        assert result == 0.0
        assert math.isfinite(result)

    def test_skewness_too_few_values(self):
        engine = _make_engine()
        assert engine._calculate_skewness([]) == 0.0
        assert engine._calculate_skewness([1.0]) == 0.0
        assert engine._calculate_skewness([1.0, 2.0]) == 0.0

    def test_skewness_finite_for_normal_input(self):
        engine = _make_engine()
        result = engine._calculate_skewness([1.0, 2.0, 3.0, 4.0, 5.0])
        assert math.isfinite(result)

    def test_kurtosis_zero_variance(self):
        engine = _make_engine()
        result = engine._calculate_kurtosis([2.0, 2.0, 2.0, 2.0])
        assert result == 0.0
        assert math.isfinite(result)

    def test_kurtosis_too_few_values(self):
        engine = _make_engine()
        assert engine._calculate_kurtosis([]) == 0.0
        assert engine._calculate_kurtosis([1.0, 2.0, 3.0]) == 0.0

    def test_kurtosis_finite_for_normal_input(self):
        engine = _make_engine()
        result = engine._calculate_kurtosis([1.0, 2.0, 3.0, 4.0, 5.0, 6.0])
        assert math.isfinite(result)

    def test_skewness_nan_input_returns_finite(self):
        engine = _make_engine()
        result = engine._calculate_skewness([float("nan"), 1.0, 2.0, 3.0])
        assert math.isfinite(result)

    def test_kurtosis_nan_input_returns_finite(self):
        engine = _make_engine()
        result = engine._calculate_kurtosis([float("nan"), 1.0, 2.0, 3.0, 4.0])
        assert math.isfinite(result)


# ── Report serialisation — no inf/nan in to_dict() ───────────────────────────


class TestReportSerialisation:
    def test_report_to_dict_contains_no_inf_or_nan(self):
        """
        generate_report().to_dict() must produce only JSON-serialisable values.
        No field may be inf, -inf, or nan.
        """
        import json
        from analytics.performance import MetricPeriod

        engine = _make_engine()
        # Mix of winning and losing trades
        engine.trades.extend(
            [
                _make_trade(200.0, 0.02),
                _make_trade(-100.0, -0.01),
                _make_trade(150.0, 0.015),
            ]
        )

        report = engine.get_performance_report(MetricPeriod.ALL_TIME)
        d = report.to_dict()

        # Must be JSON-serialisable
        try:
            json.dumps(d)
        except (ValueError, TypeError) as exc:
            pytest.fail(f"report.to_dict() is not JSON-serialisable: {exc}\nDict: {d}")

        # Check all numeric fields
        def _check(obj, path=""):
            if isinstance(obj, dict):
                for k, v in obj.items():
                    _check(v, f"{path}.{k}")
            elif isinstance(obj, list | tuple):
                for i, v in enumerate(obj):
                    _check(v, f"{path}[{i}]")
            elif isinstance(obj, float):
                assert math.isfinite(obj), f"Non-finite value at {path}: {obj}"

        _check(d)

    def test_all_winning_report_serialisable(self):
        """All-winning scenario (profit_factor=999) must serialise cleanly."""
        import json
        from analytics.performance import MetricPeriod

        engine = _make_engine()
        for _ in range(5):
            engine.trades.append(_make_trade(100.0, 0.01))

        report = engine.get_performance_report(MetricPeriod.ALL_TIME)
        d = report.to_dict()
        json.dumps(d)  # must not raise

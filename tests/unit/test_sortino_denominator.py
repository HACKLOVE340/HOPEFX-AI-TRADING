# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""One Sortino denominator, everywhere (F120 completion).

F120 replaced ``returns[returns < 0].std()`` — the dispersion *among* the
losses, about the mean loss, over only the losing periods — with the textbook
downside deviation: RMS shortfall below the target over ALL periods. The fix
landed in ``backtesting/engine_config.py`` and ``backtesting/metrics.py`` and
nowhere else, so five other modules kept computing a statistic that is not
Sortino.

The witness these tests use is a steadily-losing series with *identical*
losses. Identical numbers have a standard deviation of zero, so the old form's
denominator vanishes for exactly the return shape a downside measure exists to
penalise, and the ratio is reported as +inf — "flawless" — for a strategy that
loses on half its bars.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

# 40 gains of +2%, then 40 identical losses of -1%. Mean is positive, so every
# implementation returns a positive Sortino; only the denominator differs.
STEADY_LOSSES = np.array([0.02] * 40 + [-0.01] * 40, dtype=float)

# The textbook denominator for STEADY_LOSSES: sqrt(mean(min(r, 0)**2))
#   = sqrt((40 * 0.01**2) / 80) = 0.01 / sqrt(2)
EXPECTED_DOWNSIDE_DEVIATION = 0.01 / math.sqrt(2.0)


def test_canonical_helper_is_importable_from_a_neutral_module() -> None:
    """The one definition lives outside any single engine's module."""
    from analytics.ratios import downside_deviation

    assert downside_deviation(STEADY_LOSSES) == pytest.approx(EXPECTED_DOWNSIDE_DEVIATION, rel=1e-12)


def test_backtest_engine_helper_delegates_to_the_canonical_one() -> None:
    """The F120 fix site keeps its name and now shares the single definition."""
    from analytics.ratios import downside_deviation
    from backtesting.engine_config import BacktestEngine

    assert BacktestEngine._downside_deviation(STEADY_LOSSES) == pytest.approx(
        downside_deviation(STEADY_LOSSES), rel=1e-12
    )


def test_enhanced_engine_sortino_is_finite_on_identical_losses() -> None:
    """backtesting/enhanced_engine.py used np.std over the losses only."""
    from backtesting.enhanced_engine import _calculate_sortino

    ratio = _calculate_sortino(STEADY_LOSSES)
    assert math.isfinite(ratio)
    assert ratio == pytest.approx(float(np.mean(STEADY_LOSSES)) / EXPECTED_DOWNSIDE_DEVIATION, rel=1e-9)


def test_advanced_analytics_sortino_is_finite_on_identical_losses() -> None:
    """risk/advanced_analytics.py returned float('inf') by construction."""
    from risk.advanced_analytics import AdvancedRiskAnalytics

    analytics = AdvancedRiskAnalytics()
    ratio = analytics.calculate_sortino_ratio(STEADY_LOSSES)
    assert math.isfinite(ratio), "Sortino must never be inf — it is serialised to JSON and written to the DB"

    target = analytics.risk_free_rate / 252.0
    from analytics.ratios import downside_deviation

    expected = (
        math.sqrt(252.0) * float(np.mean(STEADY_LOSSES - target)) / downside_deviation(STEADY_LOSSES, target=target)
    )
    assert ratio == pytest.approx(expected, rel=1e-9)


def test_performance_analytics_sortino_matches_the_canonical_denominator() -> None:
    """analytics/performance.py used np.std(negative_returns, ddof=0)."""
    from analytics.performance import PerformanceAnalytics
    from analytics.ratios import downside_deviation

    analytics = PerformanceAnalytics()
    trades = [_trade(r) for r in STEADY_LOSSES]

    ratio = analytics._calculate_sortino_ratio(trades)
    target = analytics.risk_free_rate / 252.0
    expected = (
        math.sqrt(252.0) * (float(np.mean(STEADY_LOSSES)) - target) / downside_deviation(STEADY_LOSSES, target=target)
    )
    assert math.isfinite(ratio)
    assert ratio == pytest.approx(expected, rel=1e-9)


def _trade(pnl_percent: float):
    """A TradeRecord carrying one return, with everything else neutral."""
    from datetime import UTC, datetime, timedelta

    from analytics.performance import TradeRecord

    entry = datetime.now(UTC) - timedelta(hours=1)
    return TradeRecord(
        id=f"t{pnl_percent}",
        symbol="XAUUSD",
        side="buy",
        entry_price=1000.0,
        exit_price=1000.0 * (1.0 + pnl_percent),
        quantity=1.0,
        entry_time=entry,
        exit_time=entry + timedelta(minutes=1),
        pnl=1000.0 * pnl_percent,
        pnl_percent=pnl_percent,
        strategy="test",
        commission=0.0,
        duration_minutes=1,
        max_favorable_excursion=0.0,
        max_adverse_excursion=0.0,
    )

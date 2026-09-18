# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
Two reported metrics that are not the metric they are labelled.

**F119 — annualised return treats a bar count as a day count.**

    backtesting/engine_config.py:1026
        annual_return = (1 + total_return) ** (252.0 / max(len(equity_values), 1)) - 1
        calmar        = annual_return / max_drawdown

`equity_values` holds one entry per BAR and the engine runs on hourly bars
(`bars_per_day: float = 24.0`). Computed from the real formula:

    1 year, +100%   bars=6048   reported= 2.930%   correct=100.000%   34.1x low
    1 year, +30%    bars=6048   reported= 1.099%   correct= 30.000%   27.3x low
    2 years, +50%   bars=12096  reported= 0.848%   correct= 22.474%   26.5x low

A strategy that doubled capital in a year is reported as returning 2.93%, and
Calmar carries the identical error. What makes it a slip rather than a
convention: the same function divides by `bars_per_day` correctly at :990,
:1008 and :1009. Line 1026 is the one place the divisor was omitted. The error
is conservative, which is very likely why nobody questioned it.

**F120 — the Sortino denominator is the wrong statistic, in both engines.**

    returns[returns < 0].std()

is the dispersion *among the losses* — deviation about the mean loss, over only
the losing periods. Downside deviation is `sqrt(mean(min(r - target, 0)**2))`:
about the **target**, over **all** periods. Different centre, different N.
Measured against the textbook definition, the bias flips sign with the shape of
the distribution (1.13x high on symmetric returns, 0.71x low on the negatively
skewed shape strategies actually produce), so the number is not Sortino at all
rather than wrong in one direction.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

pytestmark = pytest.mark.unit


# ── F119 ─────────────────────────────────────────────────────────────────────


def _engine(bars_per_day: float):
    """A real BacktestConfig on a bare engine.

    `_annualised_return` reads only `self.config.bars_per_day`, but the config is
    built for real rather than stubbed: a namespace that happens to expose the
    one attribute would keep passing if the field were renamed or moved (F242).
    """
    from datetime import datetime

    from backtesting.engine_config import BacktestConfig, BacktestEngine

    engine = BacktestEngine.__new__(BacktestEngine)
    engine.config = BacktestConfig(
        start_date=datetime(2025, 1, 1),
        end_date=datetime(2026, 1, 1),
        symbols=["XAUUSD"],
        bars_per_day=bars_per_day,
    )
    return engine


def _annualised(total_return: float, n_bars: int, bars_per_day: float) -> float:
    """The correct formula, stated once."""
    days = n_bars / bars_per_day
    return (1 + total_return) ** (252.0 / max(days, 1e-9)) - 1


@pytest.mark.parametrize(
    "total_return, n_bars, bars_per_day, expected",
    [
        (1.00, 6048, 24.0, 1.00),  # one year of hourly bars, +100%
        (0.30, 6048, 24.0, 0.30),  # one year of hourly bars, +30%
        (0.50, 12096, 24.0, 0.2247),  # two years, +50%
        (0.30, 252, 1.0, 0.30),  # daily bars: unchanged by the fix
    ],
)
def test_annualised_return_uses_days_not_bars(total_return, n_bars, bars_per_day, expected):
    got = _engine(bars_per_day)._annualised_return(total_return, n_bars)
    assert got == pytest.approx(expected, rel=1e-3), (
        f"{total_return:+.0%} over {n_bars} bars at {bars_per_day}/day reported as {got:.3%}"
    )


def test_a_doubling_year_is_not_reported_as_three_percent():
    """The headline case from the finding."""
    assert _engine(24.0)._annualised_return(1.0, 6048) > 0.9


def test_calmar_uses_the_corrected_annual_return():
    engine = _engine(24.0)
    annual = engine._annualised_return(1.0, 6048)
    assert engine._calmar(annual, max_drawdown=0.25) == pytest.approx(annual / 0.25)
    assert engine._calmar(annual, max_drawdown=0.0) == 0.0


# ── F120 ─────────────────────────────────────────────────────────────────────


def _downside_deviation(returns, target: float = 0.0) -> float:
    """The textbook definition, stated once: RMS of the shortfall below the
    target, over ALL periods."""
    arr = np.asarray(returns, dtype=float)
    return float(np.sqrt(np.mean(np.minimum(arr - target, 0.0) ** 2)))


def test_downside_deviation_is_computed_over_all_periods():
    """A fixed series with the arithmetic done by hand.

    returns          = [0.10, 0.10, 0.10, -0.02, -0.06]
    shortfalls       = [0, 0, 0, -0.02, -0.06]
    mean of squares  = (0.0004 + 0.0036) / 5 = 0.0008
    downside dev     = sqrt(0.0008) = 0.0282842712...

    The old denominator, `std([-0.02, -0.06])`, is 0.02 — the spread between the
    two losses, which has nothing to do with the size of the shortfall.
    """
    from backtesting.engine_config import BacktestEngine

    returns = [0.10, 0.10, 0.10, -0.02, -0.06]
    assert _downside_deviation(returns) == pytest.approx(0.0282842712, rel=1e-6)
    assert BacktestEngine._downside_deviation(np.array(returns)) == pytest.approx(0.0282842712, rel=1e-6)


def test_the_two_engines_agree():
    """`backtesting/metrics.py` and `backtesting/engine_config.py` both report a
    Sortino. They must not report different numbers for the same returns."""
    from backtesting.engine_config import BacktestEngine
    from backtesting.metrics import PerformanceMetrics

    rng = np.random.default_rng(11)
    bar_returns = rng.normal(0.0004, 0.01, 500)

    equity = 100_000 * np.cumprod(1 + bar_returns)
    curve = pd.DataFrame({"equity": np.concatenate([[100_000.0], equity])})
    pm = PerformanceMetrics(
        equity_curve=curve,
        trade_history=pd.DataFrame(),
        initial_capital=100_000.0,
        risk_free_rate=0.0,
    )

    from_metrics = pm.calculate_sortino_ratio()
    realised = curve["equity"].pct_change().dropna().to_numpy()
    from_engine = float(np.mean(realised) / BacktestEngine._downside_deviation(realised) * np.sqrt(252.0))

    assert from_metrics == pytest.approx(from_engine, rel=1e-6), (
        f"the two engines report {from_metrics:.4f} and {from_engine:.4f} for the same returns"
    )


def test_no_losing_period_does_not_divide_by_zero():
    from backtesting.engine_config import BacktestEngine
    from backtesting.metrics import PerformanceMetrics

    assert BacktestEngine._downside_deviation(np.array([0.01, 0.02, 0.03])) == 0.0

    curve = pd.DataFrame({"equity": [100.0, 101.0, 102.0, 103.0]})
    pm = PerformanceMetrics(
        equity_curve=curve,
        trade_history=pd.DataFrame(),
        initial_capital=100.0,
        risk_free_rate=0.0,
    )
    assert pm.calculate_sortino_ratio() == 0.0


def test_the_denominator_is_not_the_spread_among_losses():
    """A series whose losses are all identical: their std is 0, but the downside
    deviation is not — they are real shortfalls. The old code returned 0.0
    (or divided by 1e-9) for a strategy that loses steadily."""
    from backtesting.engine_config import BacktestEngine

    returns = np.array([0.05, 0.05, -0.03, -0.03, -0.03])
    assert float(np.std(returns[returns < 0])) == 0.0
    assert BacktestEngine._downside_deviation(returns) == pytest.approx(np.sqrt(3 * 0.0009 / 5), rel=1e-9)

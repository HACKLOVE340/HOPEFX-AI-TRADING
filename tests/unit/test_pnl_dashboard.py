# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# AGPL-3.0 — Share all modifications
"""
tests/unit/test_pnl_dashboard.py
==================================
Unit tests for api/pnl_dashboard.py pure computation helpers.

Covers:
- _compute_drawdown_series() — drawdown % from equity curve
- _compute_sharpe() — annualised Sharpe ratio
- _compute_max_drawdown() — peak-to-trough max drawdown
- _compute_current_drawdown() — current drawdown from peak
- _build_equity_series() — equity curve from engine fill history
"""

from __future__ import annotations

import math
import time
import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _eq(ts_offset: int, value: float) -> tuple[float, float]:
    """Build an equity point (timestamp, value)."""
    return (float(time.time() + ts_offset), value)


# ---------------------------------------------------------------------------
# _compute_drawdown_series
# ---------------------------------------------------------------------------


class TestComputeDrawdownSeries:
    def test_empty_series_returns_empty(self):
        from api.pnl_dashboard import _compute_drawdown_series

        assert _compute_drawdown_series([]) == []

    def test_flat_equity_zero_drawdown(self):
        from api.pnl_dashboard import _compute_drawdown_series

        series = [_eq(i, 10_000.0) for i in range(5)]
        result = _compute_drawdown_series(series)
        assert all(dd == pytest.approx(0.0) for _, dd in result)

    def test_drawdown_after_drop(self):
        from api.pnl_dashboard import _compute_drawdown_series

        series = [_eq(0, 10_000.0), _eq(1, 9_000.0)]
        result = _compute_drawdown_series(series)
        # After drop from 10k to 9k: drawdown = 10%
        assert result[1][1] == pytest.approx(10.0)

    def test_drawdown_recovers_to_zero_at_new_peak(self):
        from api.pnl_dashboard import _compute_drawdown_series

        series = [_eq(0, 10_000.0), _eq(1, 9_000.0), _eq(2, 11_000.0)]
        result = _compute_drawdown_series(series)
        # At new peak, drawdown = 0
        assert result[2][1] == pytest.approx(0.0)

    def test_length_matches_input(self):
        from api.pnl_dashboard import _compute_drawdown_series

        series = [_eq(i, 10_000.0 + i * 100) for i in range(10)]
        result = _compute_drawdown_series(series)
        assert len(result) == 10

    def test_drawdown_never_negative(self):
        from api.pnl_dashboard import _compute_drawdown_series

        series = [_eq(i, 10_000.0 + i * 50) for i in range(20)]
        result = _compute_drawdown_series(series)
        assert all(dd >= 0.0 for _, dd in result)


# ---------------------------------------------------------------------------
# _compute_max_drawdown
# ---------------------------------------------------------------------------


class TestComputeMaxDrawdown:
    def test_empty_series_returns_zero(self):
        from api.pnl_dashboard import _compute_max_drawdown

        assert _compute_max_drawdown([]) == pytest.approx(0.0)

    def test_flat_equity_zero_max_drawdown(self):
        from api.pnl_dashboard import _compute_max_drawdown

        series = [_eq(i, 10_000.0) for i in range(5)]
        assert _compute_max_drawdown(series) == pytest.approx(0.0)

    def test_single_drop_max_drawdown(self):
        from api.pnl_dashboard import _compute_max_drawdown

        series = [_eq(0, 10_000.0), _eq(1, 8_000.0)]
        # 20% drawdown
        assert _compute_max_drawdown(series) == pytest.approx(20.0)

    def test_max_drawdown_is_worst_case(self):
        from api.pnl_dashboard import _compute_max_drawdown

        # Peak 10k, drops to 9k (10%), recovers to 10.5k, drops to 7k (33%)
        series = [
            _eq(0, 10_000.0),
            _eq(1, 9_000.0),
            _eq(2, 10_500.0),
            _eq(3, 7_000.0),
        ]
        dd = _compute_max_drawdown(series)
        # Max drawdown = (10500 - 7000) / 10500 * 100 ≈ 33.33%
        assert dd == pytest.approx(33.3333, abs=0.01)

    def test_always_rising_zero_drawdown(self):
        from api.pnl_dashboard import _compute_max_drawdown

        series = [_eq(i, 10_000.0 + i * 100) for i in range(20)]
        assert _compute_max_drawdown(series) == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# _compute_current_drawdown
# ---------------------------------------------------------------------------


class TestComputeCurrentDrawdown:
    def test_empty_series_returns_zero(self):
        from api.pnl_dashboard import _compute_current_drawdown

        assert _compute_current_drawdown([]) == pytest.approx(0.0)

    def test_at_peak_zero_drawdown(self):
        from api.pnl_dashboard import _compute_current_drawdown

        series = [_eq(0, 10_000.0), _eq(1, 11_000.0)]
        assert _compute_current_drawdown(series) == pytest.approx(0.0)

    def test_below_peak_positive_drawdown(self):
        from api.pnl_dashboard import _compute_current_drawdown

        series = [_eq(0, 10_000.0), _eq(1, 11_000.0), _eq(2, 9_900.0)]
        # Current 9900, peak 11000 → (11000-9900)/11000 * 100 ≈ 10%
        dd = _compute_current_drawdown(series)
        assert dd == pytest.approx(10.0, abs=0.01)

    def test_single_point_zero_drawdown(self):
        from api.pnl_dashboard import _compute_current_drawdown

        series = [_eq(0, 10_000.0)]
        assert _compute_current_drawdown(series) == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# _compute_sharpe
# ---------------------------------------------------------------------------


class TestComputeSharpe:
    def test_returns_none_below_min_fills(self):
        from api.pnl_dashboard import _compute_sharpe, _MIN_FILLS_FOR_SHARPE

        series = [_eq(i, 10_000.0 + i * 10) for i in range(_MIN_FILLS_FOR_SHARPE - 1)]
        assert _compute_sharpe(series) is None

    def test_returns_float_with_enough_data(self):
        from api.pnl_dashboard import _compute_sharpe, _MIN_FILLS_FOR_SHARPE

        # Steadily rising equity → positive Sharpe
        series = [_eq(i, 10_000.0 + i * 10) for i in range(_MIN_FILLS_FOR_SHARPE + 10)]
        result = _compute_sharpe(series)
        assert result is not None
        assert isinstance(result, float)

    def test_positive_sharpe_for_rising_equity(self):
        from api.pnl_dashboard import _compute_sharpe, _MIN_FILLS_FOR_SHARPE

        series = [_eq(i, 10_000.0 + i * 50) for i in range(_MIN_FILLS_FOR_SHARPE + 20)]
        sharpe = _compute_sharpe(series)
        assert sharpe is not None
        assert sharpe > 0.0

    def test_returns_none_for_flat_equity(self):
        from api.pnl_dashboard import _compute_sharpe, _MIN_FILLS_FOR_SHARPE

        # Flat equity → std_r = 0 → Sharpe undefined
        series = [_eq(i, 10_000.0) for i in range(_MIN_FILLS_FOR_SHARPE + 10)]
        result = _compute_sharpe(series)
        assert result is None

    def test_sharpe_is_finite(self):
        from api.pnl_dashboard import _compute_sharpe, _MIN_FILLS_FOR_SHARPE
        import random

        rng = random.Random(42)
        equity = 10_000.0
        series = []
        for i in range(_MIN_FILLS_FOR_SHARPE + 20):
            equity += rng.gauss(10, 50)
            series.append(_eq(i, max(equity, 1.0)))
        result = _compute_sharpe(series)
        if result is not None:
            assert math.isfinite(result)


# ---------------------------------------------------------------------------
# _build_equity_series
# ---------------------------------------------------------------------------


class TestBuildEquitySeries:
    def test_empty_fill_history_returns_empty(self):
        from api.pnl_dashboard import _build_equity_series

        class FakeEngine:
            _starting_equity = 10_000.0
            _fill_history = []

        assert _build_equity_series(FakeEngine()) == []

    def test_single_fill_builds_series(self):
        from api.pnl_dashboard import _build_equity_series
        from datetime import datetime, timezone

        class FakeFill:
            fill_id = "fill_001"
            filled_at = datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc)

        class FakeEngine:
            _starting_equity = 10_000.0
            _fill_history = [FakeFill()]

        result = _build_equity_series(FakeEngine())
        assert len(result) == 1
        ts, equity = result[0]
        assert equity == pytest.approx(10_000.0)  # no P&L data → 0 pnl

    def test_equity_accumulates_pnl(self):
        from api.pnl_dashboard import _build_equity_series
        from datetime import datetime, timezone

        class FakeFill:
            def __init__(self, fill_id, ts):
                self.fill_id = fill_id
                self.filled_at = ts

        class FakePostAnalyzer:
            _trade_pnls = {"fill_001": 500.0, "fill_002": -200.0}

        class FakeEngine:
            _starting_equity = 10_000.0
            _fill_history = [
                FakeFill("fill_001", datetime(2025, 1, 1, 12, 0, tzinfo=timezone.utc)),
                FakeFill("fill_002", datetime(2025, 1, 1, 13, 0, tzinfo=timezone.utc)),
            ]
            _post_analyzer = FakePostAnalyzer()

        result = _build_equity_series(FakeEngine())
        assert len(result) == 2
        assert result[0][1] == pytest.approx(10_500.0)  # 10000 + 500
        assert result[1][1] == pytest.approx(10_300.0)  # 10500 - 200

    def test_fills_sorted_by_timestamp(self):
        from api.pnl_dashboard import _build_equity_series
        from datetime import datetime, timezone

        class FakeFill:
            def __init__(self, fill_id, ts):
                self.fill_id = fill_id
                self.filled_at = ts

        class FakeEngine:
            _starting_equity = 10_000.0
            _fill_history = [
                FakeFill("fill_002", datetime(2025, 1, 1, 13, 0, tzinfo=timezone.utc)),
                FakeFill("fill_001", datetime(2025, 1, 1, 12, 0, tzinfo=timezone.utc)),
            ]

        result = _build_equity_series(FakeEngine())
        # Should be sorted: fill_001 (12:00) before fill_002 (13:00)
        assert result[0][0] < result[1][0]

    def test_uses_fallback_starting_equity(self):
        from api.pnl_dashboard import _build_equity_series
        from datetime import datetime, timezone

        class FakeFill:
            fill_id = "fill_001"
            filled_at = datetime(2025, 1, 1, 12, 0, tzinfo=timezone.utc)

        class FakeEngine:
            # No _starting_equity → fallback to 10_000
            _fill_history = [FakeFill()]

        result = _build_equity_series(FakeEngine())
        assert result[0][1] == pytest.approx(10_000.0)

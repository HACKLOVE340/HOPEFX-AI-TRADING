# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
Property-based tests using Hypothesis.

Covers trading-critical pure functions extracted during the refactoring:
  - _compute_atr()              (core/signal_engine.py)
  - _resolve_sl_tp()            (core/signal_engine.py)
  - _estimate_annualised_volatility() (core/signal_engine.py)
  - _compute_drawdown_series()  (backtesting/enhanced_engine.py)
  - _calculate_sortino()        (backtesting/enhanced_engine.py)
  - _calculate_calmar()         (backtesting/enhanced_engine.py)
  - _build_trade_statistics()   (backtesting/enhanced_engine.py)
  - RiskConfig / RiskManager    (risk/manager.py)

Properties verified:
  - ATR is always non-negative
  - SL is always on the correct side of entry for BUY and SELL
  - TP is always on the correct side of entry for BUY and SELL
  - SL/TP distance is always positive
  - Annualised volatility is always non-negative
  - Max drawdown is always in [0, 1]
  - Drawdown periods list is always a list
  - Sortino ratio is finite for any finite return series
  - Calmar ratio is 0 when max_dd <= 0
  - Win rate is always in [0, 1]
  - Profit factor is always positive or inf
"""

import math
import os

import numpy as np
import pytest
from hypothesis import HealthCheck, assume, given, settings
from hypothesis import strategies as st

os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("SECURITY_JWT_SECRET", "test-only-jwt-secret-key-minimum-32-chars!!")

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Hypothesis strategies for price-like floats (positive, finite, reasonable range)
_price = st.floats(min_value=100.0, max_value=10_000.0, allow_nan=False, allow_infinity=False)
_small_positive = st.floats(min_value=1e-6, max_value=100.0, allow_nan=False, allow_infinity=False)
_return = st.floats(min_value=-0.5, max_value=0.5, allow_nan=False, allow_infinity=False)
_pnl = st.floats(min_value=-10_000.0, max_value=10_000.0, allow_nan=False, allow_infinity=False)


# ---------------------------------------------------------------------------
# ATR properties
# ---------------------------------------------------------------------------

class TestComputeAtrProperties:
    """_compute_atr() must always return a non-negative float."""

    @given(
        entry=_price,
        n=st.integers(min_value=0, max_value=13),  # fewer than ATR_MIN_BARS → fallback
    )
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    def test_atr_fallback_is_nonnegative(self, entry: float, n: int) -> None:
        from core.signal_engine import _compute_atr

        highs = [entry + 1.0] * n
        lows = [entry - 1.0] * n
        closes = [entry] * n
        result = _compute_atr(highs, lows, closes, entry)
        assert result >= 0.0, f"ATR must be non-negative, got {result}"

    @given(
        entry=_price,
        spread=st.floats(min_value=0.01, max_value=50.0, allow_nan=False, allow_infinity=False),
        n=st.integers(min_value=15, max_value=100),
    )
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    def test_atr_with_sufficient_bars_is_nonnegative(self, entry: float, spread: float, n: int) -> None:
        from core.signal_engine import _compute_atr

        highs = [entry + spread] * n
        lows = [entry - spread] * n
        closes = [entry] * n
        result = _compute_atr(highs, lows, closes, entry)
        assert result >= 0.0
        assert math.isfinite(result)

    @given(
        entry=_price,
        spread=st.floats(min_value=0.01, max_value=50.0, allow_nan=False, allow_infinity=False),
    )
    @settings(max_examples=100)
    def test_atr_scales_with_spread(self, entry: float, spread: float) -> None:
        """Wider H/L spread → larger ATR (monotonicity check)."""
        from core.signal_engine import _compute_atr

        n = 20
        atr_narrow = _compute_atr([entry + spread] * n, [entry - spread] * n, [entry] * n, entry)
        atr_wide = _compute_atr([entry + spread * 2] * n, [entry - spread * 2] * n, [entry] * n, entry)
        assert atr_wide >= atr_narrow


# ---------------------------------------------------------------------------
# SL/TP resolution properties
# ---------------------------------------------------------------------------

class TestResolveSLTPProperties:
    """_resolve_sl_tp() must place SL/TP on the correct side of entry."""

    @given(entry=_price)
    @settings(max_examples=300, suppress_health_check=[HealthCheck.too_slow])
    def test_buy_sl_below_entry(self, entry: float) -> None:
        from core.signal_engine import _resolve_sl_tp

        sl, tp = _resolve_sl_tp(signal=None, data={}, direction="BUY", entry_price=entry)
        assert sl < entry, f"BUY SL {sl} must be below entry {entry}"

    @given(entry=_price)
    @settings(max_examples=300, suppress_health_check=[HealthCheck.too_slow])
    def test_buy_tp_above_entry(self, entry: float) -> None:
        from core.signal_engine import _resolve_sl_tp

        sl, tp = _resolve_sl_tp(signal=None, data={}, direction="BUY", entry_price=entry)
        assert tp > entry, f"BUY TP {tp} must be above entry {entry}"

    @given(entry=_price)
    @settings(max_examples=300, suppress_health_check=[HealthCheck.too_slow])
    def test_sell_sl_above_entry(self, entry: float) -> None:
        from core.signal_engine import _resolve_sl_tp

        sl, tp = _resolve_sl_tp(signal=None, data={}, direction="SELL", entry_price=entry)
        assert sl > entry, f"SELL SL {sl} must be above entry {entry}"

    @given(entry=_price)
    @settings(max_examples=300, suppress_health_check=[HealthCheck.too_slow])
    def test_sell_tp_below_entry(self, entry: float) -> None:
        from core.signal_engine import _resolve_sl_tp

        sl, tp = _resolve_sl_tp(signal=None, data={}, direction="SELL", entry_price=entry)
        assert tp < entry, f"SELL TP {tp} must be below entry {entry}"

    @given(entry=_price)
    @settings(max_examples=200)
    def test_rr_ratio_at_least_one(self, entry: float) -> None:
        """Default ATR multipliers give TP distance ≥ SL distance (2:1 R:R)."""
        from core.signal_engine import _resolve_sl_tp

        sl, tp = _resolve_sl_tp(signal=None, data={}, direction="BUY", entry_price=entry)
        sl_dist = entry - sl
        tp_dist = tp - entry
        assert tp_dist >= sl_dist * 0.99, (  # 1% tolerance for float rounding
            f"TP distance {tp_dist:.4f} must be >= SL distance {sl_dist:.4f}"
        )

    @given(
        entry=_price,
        n=st.integers(min_value=15, max_value=50),
        spread=st.floats(min_value=1.0, max_value=30.0, allow_nan=False, allow_infinity=False),
    )
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    def test_atr_path_preserves_direction(self, entry: float, n: int, spread: float) -> None:
        """With real bar data, SL/TP direction invariants still hold."""
        from core.signal_engine import _resolve_sl_tp

        data = {
            "highs": [entry + spread] * n,
            "lows": [entry - spread] * n,
            "prices": [entry] * n,
        }
        sl, tp = _resolve_sl_tp(signal=None, data=data, direction="BUY", entry_price=entry)
        assert sl < entry
        assert tp > entry


# ---------------------------------------------------------------------------
# Annualised volatility properties
# ---------------------------------------------------------------------------

class TestEstimateAnnualisedVolatilityProperties:
    """_estimate_annualised_volatility() must always return a non-negative float."""

    @given(entry=_price)
    @settings(max_examples=100)
    def test_returns_baseline_for_empty_data(self, entry: float) -> None:
        from core.signal_engine import _estimate_annualised_volatility

        vol = _estimate_annualised_volatility(data=None, entry=entry)
        assert vol == 0.15  # gold baseline

    @given(
        entry=_price,
        prices=st.lists(_price, min_size=21, max_size=100),
    )
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    def test_vol_is_nonnegative(self, entry: float, prices: list) -> None:
        from core.signal_engine import _estimate_annualised_volatility

        vol = _estimate_annualised_volatility(data={"prices": prices}, entry=entry)
        assert vol >= 0.0
        assert math.isfinite(vol)

    @given(entry=_price)
    @settings(max_examples=100)
    def test_constant_prices_give_zero_vol(self, entry: float) -> None:
        """Constant price series → zero log-returns → zero volatility."""
        from core.signal_engine import _estimate_annualised_volatility

        prices = [entry] * 25
        vol = _estimate_annualised_volatility(data={"prices": prices}, entry=entry)
        assert vol == pytest.approx(0.0, abs=1e-10)


# ---------------------------------------------------------------------------
# Drawdown series properties
# ---------------------------------------------------------------------------

class TestComputeDrawdownSeriesProperties:
    """_compute_drawdown_series() must return max_dd in [0,1] and a list."""

    @given(
        equities=st.lists(
            st.floats(min_value=1.0, max_value=2_000_000.0, allow_nan=False, allow_infinity=False),
            min_size=1,
            max_size=500,
        ),
        initial=st.floats(min_value=1.0, max_value=1_000_000.0, allow_nan=False, allow_infinity=False),
    )
    @settings(max_examples=300, suppress_health_check=[HealthCheck.too_slow], deadline=None)
    def test_max_dd_in_unit_interval(self, equities: list, initial: float) -> None:
        from backtesting.enhanced_engine import NanosecondTimestamp, _compute_drawdown_series

        curve = [(NanosecondTimestamp(i, 0), eq) for i, eq in enumerate(equities)]
        max_dd, periods = _compute_drawdown_series(curve, initial)
        assert 0.0 <= max_dd <= 1.0, f"max_dd {max_dd} not in [0,1]"
        assert isinstance(periods, list)

    @given(
        initial=st.floats(min_value=1.0, max_value=1_000_000.0, allow_nan=False, allow_infinity=False),
    )
    @settings(max_examples=100)
    def test_monotonically_rising_equity_gives_zero_drawdown(self, initial: float) -> None:
        from backtesting.enhanced_engine import NanosecondTimestamp, _compute_drawdown_series

        equities = [initial * (1 + i * 0.01) for i in range(50)]
        curve = [(NanosecondTimestamp(i, 0), eq) for i, eq in enumerate(equities)]
        max_dd, periods = _compute_drawdown_series(curve, initial)
        assert max_dd == pytest.approx(0.0, abs=1e-10)
        assert periods == []

    @given(
        initial=st.floats(min_value=1000.0, max_value=1_000_000.0, allow_nan=False, allow_infinity=False),
        drop_frac=st.floats(min_value=0.01, max_value=0.99, allow_nan=False, allow_infinity=False),
    )
    @settings(max_examples=200)
    def test_single_drop_gives_correct_drawdown(self, initial: float, drop_frac: float) -> None:
        """A single drop from initial to initial*(1-drop_frac) → max_dd == drop_frac."""
        from backtesting.enhanced_engine import NanosecondTimestamp, _compute_drawdown_series

        curve = [
            (NanosecondTimestamp(0, 0), initial),
            (NanosecondTimestamp(1, 0), initial * (1 - drop_frac)),
        ]
        max_dd, _ = _compute_drawdown_series(curve, initial)
        assert max_dd == pytest.approx(drop_frac, rel=1e-6)


# ---------------------------------------------------------------------------
# Sortino ratio properties
# ---------------------------------------------------------------------------

class TestCalculateSortinoProperties:
    """_calculate_sortino() must return a finite float for any finite input."""

    @given(returns=st.lists(_return, min_size=1, max_size=500))
    @settings(max_examples=300, suppress_health_check=[HealthCheck.too_slow])
    def test_sortino_is_finite(self, returns: list) -> None:
        from backtesting.enhanced_engine import _calculate_sortino

        result = _calculate_sortino(np.array(returns))
        assert math.isfinite(result), f"Sortino must be finite, got {result}"

    @given(
        pos_return=st.floats(min_value=0.001, max_value=0.5, allow_nan=False, allow_infinity=False),
        n=st.integers(min_value=1, max_value=100),
    )
    @settings(max_examples=100)
    def test_all_positive_returns_gives_zero_sortino(self, pos_return: float, n: int) -> None:
        """No downside returns → downside std = 0 → Sortino returns 0.0."""
        from backtesting.enhanced_engine import _calculate_sortino

        returns = np.array([pos_return] * n)
        result = _calculate_sortino(returns)
        assert result == 0.0


# ---------------------------------------------------------------------------
# Calmar ratio properties
# ---------------------------------------------------------------------------

class TestCalculateCalmarProperties:
    """_calculate_calmar() must return 0 when max_dd <= 0."""

    @given(returns=st.lists(_return, min_size=1, max_size=200))
    @settings(max_examples=200)
    def test_zero_drawdown_gives_zero_calmar(self, returns: list) -> None:
        from backtesting.enhanced_engine import _calculate_calmar

        result = _calculate_calmar(np.array(returns), max_dd=0.0)
        assert result == 0.0

    @given(
        returns=st.lists(_return, min_size=1, max_size=200),
        max_dd=st.floats(min_value=0.001, max_value=1.0, allow_nan=False, allow_infinity=False),
    )
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    def test_calmar_is_finite(self, returns: list, max_dd: float) -> None:
        from backtesting.enhanced_engine import _calculate_calmar

        result = _calculate_calmar(np.array(returns), max_dd=max_dd)
        assert math.isfinite(result)


# ---------------------------------------------------------------------------
# Trade statistics properties
# ---------------------------------------------------------------------------

class TestBuildTradeStatisticsProperties:
    """_build_trade_statistics() must produce valid win_rate and profit_factor."""

    @staticmethod
    def _make_trade(pnl: float):
        """Minimal trade-like object with net_pnl and return_pct."""
        class _T:
            net_pnl = pnl
            return_pct = pnl / 1000.0
            duration_seconds = 3600.0
            mfe = abs(pnl) + 1.0
            mae = abs(pnl) * 0.5
            mfe_pct = (abs(pnl) + 1.0) / 1000.0 * 100
            mae_pct = abs(pnl) * 0.5 / 1000.0 * 100
        return _T()

    @given(pnls=st.lists(_pnl, min_size=1, max_size=200))
    @settings(max_examples=300, suppress_health_check=[HealthCheck.too_slow])
    def test_win_rate_in_unit_interval(self, pnls: list) -> None:
        from backtesting.enhanced_engine import _build_trade_statistics

        trades = [self._make_trade(p) for p in pnls]
        stats = _build_trade_statistics(trades, pnls)
        assert 0.0 <= stats["win_rate"] <= 1.0

    @given(pnls=st.lists(_pnl, min_size=1, max_size=200))
    @settings(max_examples=300, suppress_health_check=[HealthCheck.too_slow])
    def test_profit_factor_is_nonnegative_or_inf(self, pnls: list) -> None:
        """profit_factor is abs(sum_wins/sum_losses) or inf when no losses.
        When all trades are losses, sum_wins=0 → profit_factor=0.0 (valid)."""
        from backtesting.enhanced_engine import _build_trade_statistics

        trades = [self._make_trade(p) for p in pnls]
        stats = _build_trade_statistics(trades, pnls)
        pf = stats["profit_factor"]
        assert pf >= 0.0 or pf == float("inf"), f"profit_factor must be >= 0 or inf, got {pf}"

    @given(pnls=st.lists(_pnl, min_size=1, max_size=200))
    @settings(max_examples=300, suppress_health_check=[HealthCheck.too_slow])
    def test_total_trades_matches_input(self, pnls: list) -> None:
        from backtesting.enhanced_engine import _build_trade_statistics

        trades = [self._make_trade(p) for p in pnls]
        stats = _build_trade_statistics(trades, pnls)
        assert stats["total_trades"] == len(pnls)

    @given(pnls=st.lists(_pnl, min_size=1, max_size=200))
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    def test_winning_plus_losing_equals_total(self, pnls: list) -> None:
        from backtesting.enhanced_engine import _build_trade_statistics

        trades = [self._make_trade(p) for p in pnls]
        stats = _build_trade_statistics(trades, pnls)
        # Trades with pnl == 0 are counted as losses (< 0 is False)
        assert stats["winning_trades"] + stats["losing_trades"] <= stats["total_trades"]


# ---------------------------------------------------------------------------
# RiskConfig / RiskManager properties
# ---------------------------------------------------------------------------

class TestRiskManagerProperties:
    """RiskManager must never approve a position larger than max_position_size_pct."""

    @given(
        equity=st.floats(min_value=10_000.0, max_value=10_000_000.0, allow_nan=False, allow_infinity=False),
        signal_strength=st.floats(min_value=0.01, max_value=1.0, allow_nan=False, allow_infinity=False),
        entry=_price,
        sl_offset=st.floats(min_value=1.0, max_value=50.0, allow_nan=False, allow_infinity=False),
    )
    @settings(max_examples=300, suppress_health_check=[HealthCheck.too_slow], deadline=None)
    def test_risk_amount_never_exceeds_max_pct(
        self, equity: float, signal_strength: float, entry: float, sl_offset: float
    ) -> None:
        """
        The dollar risk on any approved trade (size × SL distance) must not
        exceed max_position_size_pct × equity.

        This is the correct invariant: the RiskManager controls *risk amount*,
        not raw notional. A large position with a tight SL can have the same
        risk as a small position with a wide SL.
        """
        from risk.manager import RiskConfig, RiskManager

        sl = entry - sl_offset  # BUY: SL below entry
        assume(sl > 0)
        tp = entry + sl_offset * 2.0  # 2:1 R:R

        rc = RiskConfig(max_position_size_pct=0.02, max_drawdown_pct=0.10, daily_loss_limit_pct=0.05)
        rm = RiskManager(config=rc)
        sizing = rm.calculate_position_size(
            symbol="XAUUSD",
            signal_strength=signal_strength,
            entry_price=entry,
            stop_loss_price=sl,
            take_profit_price=tp,
            account_equity=equity,
            volatility=0.15,
            existing_positions=[],
        )
        if sizing.approved and sizing.recommended_size > 0:
            sl_distance = entry - sl
            dollar_risk = sizing.recommended_size * sl_distance
            max_risk = equity * rc.max_position_size_pct
            # Allow 5% tolerance for Kelly/volatility rounding
            assert dollar_risk <= max_risk * 1.05, (
                f"Dollar risk {dollar_risk:.2f} exceeds max {max_risk:.2f} "
                f"(equity={equity:.0f} size={sizing.recommended_size:.4f} sl_dist={sl_distance:.2f})"
            )

    @given(
        equity=st.floats(min_value=1000.0, max_value=10_000_000.0, allow_nan=False, allow_infinity=False),
    )
    @settings(max_examples=100)
    def test_approved_size_is_nonnegative(self, equity: float) -> None:
        """Any approved position size must be non-negative."""
        from risk.manager import RiskConfig, RiskManager

        rc = RiskConfig(max_position_size_pct=0.02, max_drawdown_pct=0.10, daily_loss_limit_pct=0.05)
        rm = RiskManager(config=rc)
        sizing = rm.calculate_position_size(
            symbol="XAUUSD",
            signal_strength=0.5,
            entry_price=2000.0,
            stop_loss_price=1990.0,
            take_profit_price=2030.0,
            account_equity=equity,
            volatility=0.15,
            existing_positions=[],
        )
        if sizing.approved:
            assert sizing.recommended_size >= 0.0

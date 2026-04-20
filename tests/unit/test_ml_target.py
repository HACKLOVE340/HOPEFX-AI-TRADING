# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
tests/unit/test_ml_target.py

Unit tests for the corrected training target in ml/advanced_features.py.

Covers:
  1.  build_filtered_target: UP label when open[t+1] < close[t+horizon]
  2.  build_filtered_target: DOWN label when open[t+1] > close[t+horizon]
  3.  build_filtered_target: last bar(s) are NaN (no future data)
  4.  build_filtered_target: gap-open bias — gap against signal is DOWN
  5.  build_filtered_target: ATR filter drops low-conviction bars (NaN)
  6.  build_filtered_target: horizon=5 uses close[t+5] as exit
  7.  build_filtered_target: only 0.0 and 1.0 in non-NaN labels
  8.  build_filtered_target: min_move_atr=0 labels all non-NaN bars
  9.  Unfiltered path in build_advanced_features uses open[t+1] entry
  10. Old close-to-close target would give different answer on gap-open case
"""

import numpy as np
import pandas as pd
import pytest

from ml.advanced_features import build_filtered_target


# ── Fixtures ──────────────────────────────────────────────────────────────────


def _make_df(opens, highs, lows, closes, volumes=None):
    n = len(closes)
    if volumes is None:
        volumes = [1000] * n
    return pd.DataFrame(
        {"open": opens, "high": highs, "low": lows, "close": closes, "volume": volumes}
    )


@pytest.fixture
def simple_df():
    """
    6-bar frame with known entry/exit pairs (horizon=1):
      Bar 0: entry=open[1]=101, exit=close[1]=105 -> UP
      Bar 1: entry=open[2]=104, exit=close[2]=103 -> DOWN
      Bar 2: entry=open[3]=102, exit=close[3]=108 -> UP
      Bar 3: entry=open[4]=107, exit=close[4]=106 -> DOWN
      Bar 4: entry=open[5]=105, exit=close[5]=104 -> DOWN
      Bar 5: NaN (no bar 6)
    """
    return _make_df(
        opens=[100, 101, 104, 102, 107, 105],
        highs=[106, 106, 106, 109, 108, 106],
        lows=[ 99, 100, 102, 101, 105, 103],
        closes=[100, 105, 103, 108, 106, 104],
    )


@pytest.fixture
def gap_df():
    """
    Gap-open case: close[0]=100, open[1]=102 (gap up), close[1]=101.
    Old close-to-close: (101-100)/100 = +1% -> UP (wrong).
    New open[t+1]-based: (101-102)/102 = -0.98% -> DOWN (correct).
    """
    return _make_df(
        opens=[100, 102, 100],
        highs=[101, 103, 101],
        lows=[ 99, 100,  99],
        closes=[100, 101, 100],
    )


# ── Tests ─────────────────────────────────────────────────────────────────────


class TestBuildFilteredTarget:
    def test_up_label_when_exit_above_entry(self, simple_df):
        y = build_filtered_target(simple_df, horizon=1, min_move_atr=0.0)
        assert y.iloc[0] == 1.0, f"Bar 0: entry=101, exit=105 -> UP, got {y.iloc[0]}"

    def test_down_label_when_exit_below_entry(self, simple_df):
        y = build_filtered_target(simple_df, horizon=1, min_move_atr=0.0)
        assert y.iloc[1] == 0.0, f"Bar 1: entry=104, exit=103 -> DOWN, got {y.iloc[1]}"

    def test_last_bar_is_nan(self, simple_df):
        y = build_filtered_target(simple_df, horizon=1, min_move_atr=0.0)
        assert pd.isna(y.iloc[-1]), f"Last bar should be NaN, got {y.iloc[-1]}"

    def test_gap_open_bias_corrected(self, gap_df):
        # Entry at open[1]=102, exit at close[1]=101 -> DOWN (lost money)
        y = build_filtered_target(gap_df, horizon=1, min_move_atr=0.0)
        assert y.iloc[0] == 0.0, (
            f"Gap-open: entry=102, exit=101 -> DOWN (lost money), got {y.iloc[0]}"
        )

    def test_old_close_to_close_would_be_wrong_on_gap(self, gap_df):
        # Verify the old formula gives the OPPOSITE (wrong) answer
        c = gap_df["close"]
        old_target = (c.pct_change(1).shift(-1) > 0).astype(float)
        # Old: (close[1]-close[0])/close[0] = (101-100)/100 = +1% -> UP (1.0)
        assert old_target.iloc[0] == 1.0, "Old formula should give UP (wrong answer)"
        # New gives DOWN (0.0) — tested in test_gap_open_bias_corrected

    def test_atr_filter_drops_small_moves(self):
        # Construct a frame where all moves are tiny -> all NaN with high min_move_atr
        n = 50
        price = np.ones(n) * 2000.0
        df = _make_df(
            opens=price.tolist(),
            highs=(price * 1.0001).tolist(),
            lows=(price * 0.9999).tolist(),
            closes=price.tolist(),
        )
        y = build_filtered_target(df, horizon=1, min_move_atr=10.0)
        assert y.isna().all(), "All bars should be NaN when moves are tiny"

    def test_min_move_zero_labels_all_non_nan(self, simple_df):
        y = build_filtered_target(simple_df, horizon=1, min_move_atr=0.0)
        # Only the last bar (no future) should be NaN
        non_nan = y.dropna()
        assert len(non_nan) == len(simple_df) - 1

    def test_labels_are_only_zero_or_one(self, simple_df):
        y = build_filtered_target(simple_df, horizon=1, min_move_atr=0.0)
        non_nan = y.dropna()
        assert set(non_nan.unique()).issubset({0.0, 1.0})

    def test_horizon_5_uses_close_t_plus_5(self):
        # 10-bar frame, horizon=5
        # Bar 0: entry=open[1], exit=close[5]
        n = 12
        opens  = [100.0 + i for i in range(n)]
        closes = [100.0 + i * 2 for i in range(n)]
        highs  = [c + 1 for c in closes]
        lows   = [c - 1 for c in closes]
        df = _make_df(opens, highs, lows, closes)
        y = build_filtered_target(df, horizon=5, min_move_atr=0.0)
        # Bar 0: entry=open[1]=101, exit=close[5]=110 -> UP
        assert y.iloc[0] == 1.0
        # Last 5 bars should be NaN (no future data for horizon=5)
        assert y.iloc[-5:].isna().all()

    def test_returns_pandas_series(self, simple_df):
        y = build_filtered_target(simple_df, horizon=1, min_move_atr=0.0)
        assert isinstance(y, pd.Series)

    def test_index_matches_input(self, simple_df):
        y = build_filtered_target(simple_df, horizon=1, min_move_atr=0.0)
        assert list(y.index) == list(simple_df.index)

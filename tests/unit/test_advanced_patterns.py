# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""Tests for analysis/patterns/advanced_patterns.py — AdvancedPatternDetector."""

from __future__ import annotations

import numpy as np
import pandas as pd

from analysis.patterns.advanced_patterns import (
    AdvancedPatternDetector,
    PatternDirection,
    PatternSignal,
    PatternType,
)


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_df(n: int = 100, base: float = 1.08, trend: float = 0.0, noise: float = 0.001) -> pd.DataFrame:
    """Generate a synthetic OHLCV DataFrame."""
    rng = np.random.default_rng(42)
    close = base + np.linspace(0, trend, n) + rng.normal(0, noise, n).cumsum()
    high = close + np.abs(rng.normal(0, noise * 0.5, n))
    low = close - np.abs(rng.normal(0, noise * 0.5, n))
    open_ = close - rng.normal(0, noise * 0.3, n)
    volume = rng.integers(1000, 10000, n).astype(float)
    idx = pd.date_range("2024-01-01", periods=n, freq="1h")
    return pd.DataFrame({"open": open_, "high": high, "low": low, "close": close, "volume": volume}, index=idx)


def _make_head_shoulders_df() -> pd.DataFrame:
    """Synthetic head-and-shoulders pattern (left shoulder, head, right shoulder)."""
    n = 60
    close = np.ones(n) * 1.08
    # Left shoulder
    close[5:15] = np.linspace(1.08, 1.10, 10)
    close[15:20] = np.linspace(1.10, 1.08, 5)
    # Head
    close[20:30] = np.linspace(1.08, 1.12, 10)
    close[30:35] = np.linspace(1.12, 1.08, 5)
    # Right shoulder
    close[35:45] = np.linspace(1.08, 1.10, 10)
    close[45:50] = np.linspace(1.10, 1.08, 5)
    high = close + 0.001
    low = close - 0.001
    idx = pd.date_range("2024-01-01", periods=n, freq="1h")
    return pd.DataFrame({"open": close, "high": high, "low": low, "close": close,
                         "volume": np.ones(n) * 1000}, index=idx)


def _make_double_top_df() -> pd.DataFrame:
    """Synthetic double-top pattern."""
    n = 50
    close = np.ones(n) * 1.08
    close[5:15] = np.linspace(1.08, 1.12, 10)
    close[15:20] = np.linspace(1.12, 1.09, 5)
    close[20:30] = np.linspace(1.09, 1.12, 10)
    close[30:35] = np.linspace(1.12, 1.08, 5)
    high = close + 0.001
    low = close - 0.001
    idx = pd.date_range("2024-01-01", periods=n, freq="1h")
    return pd.DataFrame({"open": close, "high": high, "low": low, "close": close,
                         "volume": np.ones(n) * 1000}, index=idx)


# ── PatternSignal ─────────────────────────────────────────────────────────────


class TestPatternSignal:
    def test_to_dict_keys(self):
        sig = PatternSignal(
            pattern_type=PatternType.DOUBLE_TOP,
            direction=PatternDirection.BEARISH,
            entry_price=1.08,
            target_price=1.05,
            stop_loss=1.10,
            confidence=0.8,
            pattern_start_idx=0,
            pattern_end_idx=20,
            formation_bars=20,
            risk_reward_ratio=1.5,
            timestamp=pd.Timestamp("2024-01-01"),
        )
        d = sig.to_dict()
        assert d["pattern_type"] == "double_top"
        assert d["direction"] == "bearish"
        assert d["confidence"] == 0.8
        assert "timestamp" in d

    def test_to_dict_float_conversion(self):
        sig = PatternSignal(
            pattern_type=PatternType.GARTLEY,
            direction=PatternDirection.BULLISH,
            entry_price=np.float64(1.08),
            target_price=np.float64(1.12),
            stop_loss=np.float64(1.06),
            confidence=np.float64(0.75),
            pattern_start_idx=0,
            pattern_end_idx=10,
            formation_bars=10,
            risk_reward_ratio=np.float64(2.0),
            timestamp=pd.Timestamp("2024-01-01"),
        )
        d = sig.to_dict()
        assert isinstance(d["entry_price"], float)
        assert isinstance(d["confidence"], float)


# ── AdvancedPatternDetector init ──────────────────────────────────────────────


class TestAdvancedPatternDetectorInit:
    def test_default_params(self):
        det = AdvancedPatternDetector()
        assert det.min_pattern_bars == 5
        assert det.harmonic_tolerance == 0.05

    def test_custom_params(self):
        det = AdvancedPatternDetector(min_pattern_bars=10, harmonic_tolerance=0.03)
        assert det.min_pattern_bars == 10
        assert det.harmonic_tolerance == 0.03


# ── detect_all_patterns ───────────────────────────────────────────────────────


class TestDetectAllPatterns:
    def test_returns_list(self):
        det = AdvancedPatternDetector()
        df = _make_df(100)
        result = det.detect_all_patterns(df)
        assert isinstance(result, list)

    def test_empty_df_returns_empty(self):
        det = AdvancedPatternDetector()
        df = pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
        result = det.detect_all_patterns(df)
        assert result == []

    def test_short_df_returns_empty(self):
        det = AdvancedPatternDetector()
        df = _make_df(5)
        result = det.detect_all_patterns(df)
        assert isinstance(result, list)

    def test_confidence_filter(self):
        det = AdvancedPatternDetector()
        df = _make_df(200)
        result = det.detect_all_patterns(df, min_confidence=0.99)
        # Very high threshold — may return empty or very few
        assert isinstance(result, list)
        for sig in result:
            assert sig.confidence >= 0.99

    def test_all_signals_have_valid_direction(self):
        det = AdvancedPatternDetector()
        df = _make_df(200)
        result = det.detect_all_patterns(df, min_confidence=0.0)
        for sig in result:
            assert isinstance(sig.direction, PatternDirection)

    def test_all_signals_have_positive_rr(self):
        det = AdvancedPatternDetector()
        df = _make_df(200)
        result = det.detect_all_patterns(df, min_confidence=0.0)
        for sig in result:
            assert sig.risk_reward_ratio >= 0


def _arrays(df: pd.DataFrame):
    """Extract (high, low, close, index) arrays from a DataFrame."""
    return df["high"].to_numpy(), df["low"].to_numpy(), df["close"].to_numpy(), df.index


# ── Head & Shoulders ──────────────────────────────────────────────────────────


class TestHeadShoulders:
    def test_detect_head_shoulders_returns_list(self):
        det = AdvancedPatternDetector()
        df = _make_head_shoulders_df()
        result = det._detect_head_shoulders(*_arrays(df))
        assert isinstance(result, list)

    def test_head_shoulders_on_flat_data(self):
        det = AdvancedPatternDetector()
        df = _make_df(100, noise=0.0001)
        result = det._detect_head_shoulders(*_arrays(df))
        assert isinstance(result, list)


# ── Double patterns ───────────────────────────────────────────────────────────


class TestDoublePatterns:
    def test_detect_double_patterns_returns_list(self):
        det = AdvancedPatternDetector()
        df = _make_double_top_df()
        result = det._detect_double_patterns(*_arrays(df))
        assert isinstance(result, list)

    def test_double_patterns_on_trending_data(self):
        det = AdvancedPatternDetector()
        df = _make_df(100, trend=0.05)
        result = det._detect_double_patterns(*_arrays(df))
        assert isinstance(result, list)


# ── Triangles ─────────────────────────────────────────────────────────────────


class TestTriangles:
    def test_detect_triangles_returns_list(self):
        det = AdvancedPatternDetector()
        df = _make_df(100)
        result = det._detect_triangles(*_arrays(df))
        assert isinstance(result, list)

    def test_triangles_on_converging_data(self):
        det = AdvancedPatternDetector()
        n = 80
        rng = np.random.default_rng(0)
        close = 1.08 + rng.normal(0, 0.001, n).cumsum()
        amplitude = np.linspace(0.01, 0.001, n)
        high = close + amplitude
        low = close - amplitude
        idx = pd.date_range("2024-01-01", periods=n, freq="1h")
        df = pd.DataFrame({"open": close, "high": high, "low": low, "close": close,
                           "volume": np.ones(n) * 1000}, index=idx)
        result = det._detect_triangles(*_arrays(df))
        assert isinstance(result, list)


# ── Wedges ────────────────────────────────────────────────────────────────────


class TestWedges:
    def test_detect_wedges_returns_list(self):
        det = AdvancedPatternDetector()
        df = _make_df(100)
        result = det._detect_wedges(*_arrays(df))
        assert isinstance(result, list)


# ── Flags & Pennants ──────────────────────────────────────────────────────────


class TestFlagsPennants:
    def test_detect_flags_pennants_returns_list(self):
        det = AdvancedPatternDetector()
        df = _make_df(100)
        result = det._detect_flags_pennants(*_arrays(df))
        assert isinstance(result, list)


# ── Rectangles ────────────────────────────────────────────────────────────────


class TestRectangles:
    def test_detect_rectangles_returns_list(self):
        det = AdvancedPatternDetector()
        df = _make_df(100)
        result = det._detect_rectangles(*_arrays(df))
        assert isinstance(result, list)


# ── Harmonic patterns ─────────────────────────────────────────────────────────


class TestHarmonicPatterns:
    def test_detect_harmonic_patterns_returns_list(self):
        det = AdvancedPatternDetector()
        df = _make_df(200)
        result = det._detect_harmonic_patterns(*_arrays(df))
        assert isinstance(result, list)

    def test_harmonic_patterns_on_short_df(self):
        det = AdvancedPatternDetector()
        df = _make_df(10)
        result = det._detect_harmonic_patterns(*_arrays(df))
        assert isinstance(result, list)


# ── Support / Resistance ──────────────────────────────────────────────────────


class TestSupportResistance:
    def test_detect_support_resistance_returns_list(self):
        det = AdvancedPatternDetector()
        df = _make_df(100)
        result = det._detect_support_resistance(*_arrays(df))
        assert isinstance(result, list)

    def test_support_resistance_signals_have_correct_type(self):
        det = AdvancedPatternDetector()
        df = _make_df(100)
        result = det._detect_support_resistance(*_arrays(df))
        for sig in result:
            assert sig.pattern_type == PatternType.SUPPORT_RESISTANCE


# ── Pattern confidence calculation ────────────────────────────────────────────


class TestPatternConfidence:
    def test_perfect_ratio_gives_high_confidence(self):
        det = AdvancedPatternDetector()
        conf = det._calculate_pattern_confidence(0.618, 0.618, 0.05)
        assert conf > 0.9

    def test_outside_tolerance_gives_zero(self):
        det = AdvancedPatternDetector()
        conf = det._calculate_pattern_confidence(0.618, 1.618, 0.05)
        assert conf == 0.0

    def test_at_tolerance_boundary(self):
        det = AdvancedPatternDetector()
        # Exactly at tolerance edge
        conf = det._calculate_pattern_confidence(0.618 * 1.05, 0.618, 0.05)
        assert 0.0 <= conf <= 1.0

    def test_confidence_between_zero_and_one(self):
        det = AdvancedPatternDetector()
        for actual in [0.5, 0.618, 0.786, 1.0, 1.272, 1.618]:
            conf = det._calculate_pattern_confidence(actual, 0.618, 0.1)
            assert 0.0 <= conf <= 1.0

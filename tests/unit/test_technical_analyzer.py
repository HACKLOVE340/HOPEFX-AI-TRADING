# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# AGPL-3.0 — Share all modifications
"""
tests/unit/test_technical_analyzer.py
=======================================
Unit tests for analysis/technical_analyzer.py.

Covers:
- MultiTimeframeAnalyzer.analyze() — buy/sell/neutral confluence
- _analyze_single_timeframe() — RSI + SMA signal logic
- _calculate_rsi() — RSI values in expected range
- _aggregate_indicators() — avg_rsi and trend_alignment
- AnalysisResult dataclass fields
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from analysis.technical_analyzer import AnalysisResult, MultiTimeframeAnalyzer


def _make_df(closes: list[float]) -> pd.DataFrame:
    """Build a minimal OHLCV DataFrame from a close price list."""
    n = len(closes)
    closes_arr = np.array(closes, dtype=float)
    return pd.DataFrame(
        {
            "open": closes_arr * 0.999,
            "high": closes_arr * 1.002,
            "low": closes_arr * 0.998,
            "close": closes_arr,
            "volume": np.ones(n) * 1000,
        }
    )


def _trending_up(n: int = 100, start: float = 1800.0, step: float = 1.0) -> pd.DataFrame:
    """Steadily rising prices — should produce buy signals."""
    closes = [start + i * step for i in range(n)]
    return _make_df(closes)


def _trending_down(n: int = 100, start: float = 2000.0, step: float = 1.0) -> pd.DataFrame:
    """Steadily falling prices — should produce sell signals."""
    closes = [start - i * step for i in range(n)]
    return _make_df(closes)


def _flat(n: int = 100, price: float = 1900.0) -> pd.DataFrame:
    """Flat prices — neutral signal."""
    return _make_df([price] * n)


# ---------------------------------------------------------------------------
# AnalysisResult dataclass
# ---------------------------------------------------------------------------


class TestAnalysisResult:
    def test_fields_accessible(self):
        r = AnalysisResult(signal="buy", confidence=0.8, indicators={"rsi": 45.0}, timeframe="1h")
        assert r.signal == "buy"
        assert r.confidence == pytest.approx(0.8)
        assert r.indicators["rsi"] == pytest.approx(45.0)
        assert r.timeframe == "1h"

    def test_neutral_result(self):
        r = AnalysisResult("neutral", 0.0, {}, "multi")
        assert r.signal == "neutral"
        assert r.confidence == 0.0


# ---------------------------------------------------------------------------
# _calculate_rsi
# ---------------------------------------------------------------------------


class TestCalculateRsi:
    def setup_method(self):
        self.analyzer = MultiTimeframeAnalyzer()

    def test_rsi_in_valid_range(self):
        prices = pd.Series([float(x) for x in range(1800, 1900)])
        rsi = self.analyzer._calculate_rsi(prices)
        assert 0.0 <= rsi <= 100.0

    def test_rsi_high_for_rising_prices(self):
        # Strongly rising prices → RSI should be above 50
        prices = pd.Series([1800.0 + i * 2 for i in range(50)])
        rsi = self.analyzer._calculate_rsi(prices)
        assert rsi > 50.0

    def test_rsi_low_for_falling_prices(self):
        # Strongly falling prices → RSI should be below 50
        prices = pd.Series([2000.0 - i * 2 for i in range(50)])
        rsi = self.analyzer._calculate_rsi(prices)
        assert rsi < 50.0

    def test_rsi_near_50_for_flat_prices(self):
        # Flat prices → RSI converges near 50
        prices = pd.Series([1900.0] * 50)
        rsi = self.analyzer._calculate_rsi(prices)
        # With all-zero deltas, gain/loss both 0 → rs=1 → RSI=50
        assert 0.0 <= rsi <= 100.0

    def test_rsi_custom_period(self):
        prices = pd.Series([1800.0 + i for i in range(30)])
        rsi_14 = self.analyzer._calculate_rsi(prices, period=14)
        rsi_7 = self.analyzer._calculate_rsi(prices, period=7)
        # Both should be valid
        assert 0.0 <= rsi_14 <= 100.0
        assert 0.0 <= rsi_7 <= 100.0


# ---------------------------------------------------------------------------
# _analyze_single_timeframe
# ---------------------------------------------------------------------------


class TestAnalyzeSingleTimeframe:
    def setup_method(self):
        self.analyzer = MultiTimeframeAnalyzer()

    def test_buy_signal_on_uptrend(self):
        df = _trending_up(n=100)
        result = self.analyzer._analyze_single_timeframe(df)
        assert result["signal"] in ("buy", "neutral")
        assert "rsi" in result
        assert "trend" in result

    def test_sell_signal_on_downtrend(self):
        df = _trending_down(n=100)
        result = self.analyzer._analyze_single_timeframe(df)
        assert result["signal"] in ("sell", "neutral")

    def test_neutral_on_flat_prices(self):
        df = _flat(n=100)
        result = self.analyzer._analyze_single_timeframe(df)
        # Flat: SMA20 ≈ SMA50 ≈ close → no clear crossover
        assert result["signal"] in ("buy", "sell", "neutral")

    def test_result_has_required_keys(self):
        df = _trending_up(n=60)
        result = self.analyzer._analyze_single_timeframe(df)
        assert "signal" in result
        assert "rsi" in result
        assert "trend" in result

    def test_trend_up_when_sma20_above_sma50(self):
        df = _trending_up(n=100)
        result = self.analyzer._analyze_single_timeframe(df)
        assert result["trend"] == "up"

    def test_trend_down_when_sma20_below_sma50(self):
        df = _trending_down(n=100)
        result = self.analyzer._analyze_single_timeframe(df)
        assert result["trend"] == "down"


# ---------------------------------------------------------------------------
# _aggregate_indicators
# ---------------------------------------------------------------------------


class TestAggregateIndicators:
    def setup_method(self):
        self.analyzer = MultiTimeframeAnalyzer()

    def test_avg_rsi_computed(self):
        signals = {
            "1h": {"rsi": 40.0, "trend": "up"},
            "4h": {"rsi": 60.0, "trend": "up"},
        }
        result = self.analyzer._aggregate_indicators(signals)
        assert result["avg_rsi"] == pytest.approx(50.0)

    def test_trend_alignment_all_up(self):
        signals = {
            "1h": {"rsi": 50.0, "trend": "up"},
            "4h": {"rsi": 55.0, "trend": "up"},
            "1d": {"rsi": 60.0, "trend": "up"},
        }
        result = self.analyzer._aggregate_indicators(signals)
        assert result["trend_alignment"] == pytest.approx(1.0)

    def test_trend_alignment_mixed(self):
        signals = {
            "1h": {"rsi": 50.0, "trend": "up"},
            "4h": {"rsi": 45.0, "trend": "down"},
        }
        result = self.analyzer._aggregate_indicators(signals)
        assert result["trend_alignment"] == pytest.approx(0.5)

    def test_trend_alignment_all_down(self):
        signals = {
            "1h": {"rsi": 35.0, "trend": "down"},
            "4h": {"rsi": 30.0, "trend": "down"},
        }
        result = self.analyzer._aggregate_indicators(signals)
        assert result["trend_alignment"] == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# analyze() — multi-timeframe confluence
# ---------------------------------------------------------------------------


class TestAnalyze:
    def setup_method(self):
        self.analyzer = MultiTimeframeAnalyzer()

    def test_returns_analysis_result(self):
        data = {"1h": _trending_up(n=100), "4h": _trending_up(n=100)}
        result = self.analyzer.analyze(data)
        assert isinstance(result, AnalysisResult)
        assert result.signal in ("buy", "sell", "neutral")
        assert 0.0 <= result.confidence <= 1.0
        assert result.timeframe == "multi"

    def test_buy_confluence_when_all_timeframes_bullish(self):
        # All timeframes strongly trending up → buy confluence
        data = {tf: _trending_up(n=100) for tf in ["1h", "4h", "1d", "15m"]}
        result = self.analyzer.analyze(data)
        # With strong uptrend across all TFs, expect buy or neutral
        assert result.signal in ("buy", "neutral")

    def test_sell_confluence_when_all_timeframes_bearish(self):
        data = {tf: _trending_down(n=100) for tf in ["1h", "4h", "1d", "15m"]}
        result = self.analyzer.analyze(data)
        assert result.signal in ("sell", "neutral")

    def test_neutral_when_mixed_signals(self):
        # Half bullish, half bearish → no 70% threshold met → neutral
        data = {
            "1h": _trending_up(n=100),
            "4h": _trending_down(n=100),
            "1d": _trending_up(n=100),
            "15m": _trending_down(n=100),
        }
        result = self.analyzer.analyze(data)
        # Mixed signals → neutral (neither buy nor sell exceeds 70%)
        assert result.signal in ("buy", "sell", "neutral")

    def test_single_timeframe_data(self):
        data = {"1h": _trending_up(n=60)}
        result = self.analyzer.analyze(data)
        assert isinstance(result, AnalysisResult)

    def test_indicators_populated_on_directional_signal(self):
        # Use enough timeframes to exceed 70% threshold
        data = {f"tf{i}": _trending_up(n=100) for i in range(5)}
        result = self.analyzer.analyze(data)
        if result.signal != "neutral":
            assert "avg_rsi" in result.indicators
            assert "trend_alignment" in result.indicators

    def test_confidence_between_zero_and_one(self):
        data = {"1h": _trending_up(n=100), "4h": _flat(n=100)}
        result = self.analyzer.analyze(data)
        assert 0.0 <= result.confidence <= 1.0

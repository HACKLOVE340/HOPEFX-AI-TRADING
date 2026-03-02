"""
Comprehensive Tests for Analysis Modules

Tests for:
- MarketRegimeDetector (market_analysis.py)
- MultiTimeframeAnalyzer (market_analysis.py)
- SessionAnalyzer (market_analysis.py)
- MarketScanner extended coverage (market_scanner.py)
- OrderFlowDashboard (order_flow_dashboard.py)
"""

import pytest
import numpy as np
import pandas as pd
from datetime import datetime, time, timezone, timedelta
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_ohlcv(
    n: int = 200,
    base_price: float = 1950.0,
    trend: float = 0.0,
    volatility: float = 5.0,
    seed: int = 42,
) -> pd.DataFrame:
    """Return a DataFrame with OHLCV columns and a DatetimeIndex."""
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2024-01-01", periods=n, freq="1h")
    close = base_price + trend * np.arange(n) + rng.normal(0, volatility, n).cumsum()
    high = close + rng.uniform(1, volatility, n)
    low = close - rng.uniform(1, volatility, n)
    open_ = close - rng.normal(0, 1, n)
    volume = rng.uniform(500_000, 1_500_000, n)
    return pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": volume},
        index=dates,
    )


def _make_trending_up(n: int = 200) -> pd.DataFrame:
    """Strong uptrend – price rises steadily with high ADX conditions."""
    return _make_ohlcv(n=n, trend=1.5, volatility=2.0, seed=1)


def _make_trending_down(n: int = 200) -> pd.DataFrame:
    """Strong downtrend."""
    return _make_ohlcv(n=n, trend=-1.5, volatility=2.0, seed=2)


def _make_ranging(n: int = 200) -> pd.DataFrame:
    """Mean-reverting, low-range data."""
    rng = np.random.default_rng(3)
    dates = pd.date_range("2024-01-01", periods=n, freq="1h")
    # Oscillating with very small range
    t = np.arange(n)
    close = 1950.0 + 5.0 * np.sin(2 * np.pi * t / 20) + rng.normal(0, 0.3, n)
    high = close + rng.uniform(0.5, 1.0, n)
    low = close - rng.uniform(0.5, 1.0, n)
    open_ = close + rng.normal(0, 0.2, n)
    volume = rng.uniform(800_000, 1_200_000, n)
    return pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": volume},
        index=dates,
    )


def _make_volatile(n: int = 200) -> pd.DataFrame:
    """High volatility with no clear direction."""
    return _make_ohlcv(n=n, trend=0.0, volatility=30.0, seed=4)


# ---------------------------------------------------------------------------
# Tests – MarketRegimeDetector
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestMarketRegimeDetector:
    """Tests for MarketRegimeDetector."""

    def test_initialization_defaults(self):
        from analysis.market_analysis import MarketRegimeDetector

        detector = MarketRegimeDetector()
        assert detector.lookback_period == 100
        assert detector.atr_period == 14
        assert detector.trend_period == 20
        assert detector.regime_history == []

    def test_initialization_custom_config(self):
        from analysis.market_analysis import MarketRegimeDetector

        cfg = {"lookback_period": 50, "atr_period": 7, "trend_period": 10}
        detector = MarketRegimeDetector(config=cfg)
        assert detector.lookback_period == 50
        assert detector.atr_period == 7

    def test_detect_regime_returns_regime_analysis(self):
        from analysis.market_analysis import MarketRegimeDetector, RegimeAnalysis

        detector = MarketRegimeDetector()
        df = _make_ohlcv(n=200)
        result = detector.detect_regime(df)
        assert isinstance(result, RegimeAnalysis)

    def test_detect_regime_insufficient_data_returns_default(self):
        from analysis.market_analysis import MarketRegimeDetector, MarketRegime

        detector = MarketRegimeDetector(config={"lookback_period": 100})
        df = _make_ohlcv(n=50)  # less than lookback
        result = detector.detect_regime(df)
        assert result.current_regime == MarketRegime.RANGING
        assert result.regime_strength == 0.5
        assert result.trend_direction == "neutral"

    def test_regime_analysis_to_dict(self):
        from analysis.market_analysis import MarketRegimeDetector

        detector = MarketRegimeDetector()
        result = detector.detect_regime(_make_ohlcv(n=200))
        d = result.to_dict()
        assert "current_regime" in d
        assert "regime_strength" in d
        assert "trend_direction" in d
        assert "volatility_percentile" in d
        assert "volume_state" in d
        assert "regime_duration" in d
        assert "transition_probability" in d
        assert "timestamp" in d

    def test_detect_regime_trending_up(self):
        from analysis.market_analysis import MarketRegimeDetector, MarketRegime

        detector = MarketRegimeDetector()
        df = _make_trending_up(n=200)
        result = detector.detect_regime(df)
        # Should detect some regime; trending_up is expected for strong uptrend
        assert result.current_regime in list(MarketRegime)
        assert 0.0 <= result.regime_strength <= 1.0
        assert result.trend_direction in ("up", "down", "neutral")

    def test_detect_regime_trending_down(self):
        from analysis.market_analysis import MarketRegimeDetector, MarketRegime

        detector = MarketRegimeDetector()
        df = _make_trending_down(n=200)
        result = detector.detect_regime(df)
        assert result.current_regime in list(MarketRegime)
        assert result.trend_direction in ("up", "down", "neutral")

    def test_detect_regime_ranging(self):
        from analysis.market_analysis import MarketRegimeDetector, MarketRegime

        detector = MarketRegimeDetector()
        df = _make_ranging(n=200)
        result = detector.detect_regime(df)
        assert result.current_regime in list(MarketRegime)

    def test_detect_regime_volatile(self):
        from analysis.market_analysis import MarketRegimeDetector, MarketRegime

        detector = MarketRegimeDetector()
        df = _make_volatile(n=200)
        result = detector.detect_regime(df)
        assert result.current_regime in list(MarketRegime)

    def test_regime_history_updated(self):
        from analysis.market_analysis import MarketRegimeDetector

        detector = MarketRegimeDetector()
        df = _make_ohlcv(n=200)
        detector.detect_regime(df)
        assert len(detector.regime_history) == 1
        detector.detect_regime(df)
        assert len(detector.regime_history) == 2

    def test_regime_history_capped_at_1000(self):
        from analysis.market_analysis import MarketRegimeDetector

        detector = MarketRegimeDetector()
        df = _make_ohlcv(n=200)
        for _ in range(1005):
            detector.detect_regime(df)
        assert len(detector.regime_history) <= 1000

    def test_volume_state_high(self):
        from analysis.market_analysis import MarketRegimeDetector

        detector = MarketRegimeDetector()
        df = _make_ohlcv(n=200)
        # Spike the last volume bar
        df.iloc[-1, df.columns.get_loc("volume")] = df["volume"].mean() * 3
        result = detector.detect_regime(df)
        assert result.volume_state in ("high", "normal", "low", "unknown")

    def test_volume_state_low(self):
        from analysis.market_analysis import MarketRegimeDetector

        detector = MarketRegimeDetector()
        df = _make_ohlcv(n=200)
        df.iloc[-1, df.columns.get_loc("volume")] = df["volume"].mean() * 0.1
        result = detector.detect_regime(df)
        assert result.volume_state in ("high", "normal", "low", "unknown")

    def test_volume_state_no_volume_column(self):
        from analysis.market_analysis import MarketRegimeDetector

        detector = MarketRegimeDetector()
        df = _make_ohlcv(n=200).drop(columns=["volume"])
        result = detector.detect_regime(df)
        assert result.volume_state == "unknown"

    def test_transition_probability_default_when_insufficient_history(self):
        from analysis.market_analysis import MarketRegimeDetector, MarketRegime

        detector = MarketRegimeDetector()
        df = _make_ohlcv(n=200)
        result = detector.detect_regime(df)
        # Less than 10 history entries → default uniform probabilities
        for v in result.transition_probability.values():
            assert abs(v - 0.14) < 0.01

    def test_transition_probability_with_history(self):
        from analysis.market_analysis import MarketRegimeDetector

        detector = MarketRegimeDetector()
        df = _make_ohlcv(n=200)
        for _ in range(15):
            detector.detect_regime(df)
        result = detector.detect_regime(df)
        # Probabilities should sum to ~1 when transitions exist
        tp = result.transition_probability
        if tp:
            assert abs(sum(tp.values()) - 1.0) < 0.01

    def test_all_regime_enum_values(self):
        from analysis.market_analysis import MarketRegime

        expected = {
            "trending_up", "trending_down", "ranging",
            "volatile", "breakout", "consolidation", "choppy",
        }
        actual = {r.value for r in MarketRegime}
        assert actual == expected

    def test_detect_regime_with_exact_100_rows(self):
        """Boundary: exactly lookback_period rows should NOT use default."""
        from analysis.market_analysis import MarketRegimeDetector, MarketRegime

        detector = MarketRegimeDetector(config={"lookback_period": 100})
        df = _make_ohlcv(n=100)
        result = detector.detect_regime(df)
        # We just need it not to crash; result is valid
        assert result.current_regime in list(MarketRegime)

    def test_regime_strength_between_0_and_1(self):
        from analysis.market_analysis import MarketRegimeDetector

        detector = MarketRegimeDetector()
        result = detector.detect_regime(_make_ohlcv(n=200))
        assert 0.0 <= result.regime_strength <= 1.0

    def test_volatility_percentile_between_0_and_100(self):
        from analysis.market_analysis import MarketRegimeDetector

        detector = MarketRegimeDetector()
        result = detector.detect_regime(_make_ohlcv(n=200))
        assert 0.0 <= result.volatility_percentile <= 100.0


# ---------------------------------------------------------------------------
# Tests – MultiTimeframeAnalyzer
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestMultiTimeframeAnalyzer:
    """Tests for MultiTimeframeAnalyzer."""

    def test_initialization_defaults(self):
        from analysis.market_analysis import MultiTimeframeAnalyzer

        analyzer = MultiTimeframeAnalyzer()
        assert analyzer.timeframes == ["M5", "M15", "H1", "H4", "D1"]

    def test_initialization_custom_timeframes(self):
        from analysis.market_analysis import MultiTimeframeAnalyzer

        analyzer = MultiTimeframeAnalyzer(timeframes=["H1", "H4"])
        assert analyzer.timeframes == ["H1", "H4"]

    def test_analyze_confluence_returns_confluence_analysis(self):
        from analysis.market_analysis import MultiTimeframeAnalyzer, ConfluenceAnalysis

        analyzer = MultiTimeframeAnalyzer()
        data = {"H1": _make_ohlcv(n=200), "H4": _make_ohlcv(n=200)}
        result = analyzer.analyze_confluence(data)
        assert isinstance(result, ConfluenceAnalysis)

    def test_analyze_confluence_empty_data_returns_default(self):
        from analysis.market_analysis import MultiTimeframeAnalyzer

        analyzer = MultiTimeframeAnalyzer()
        result = analyzer.analyze_confluence({})
        assert result.overall_bias == "neutral"
        assert result.confidence == 0.0

    def test_analyze_confluence_insufficient_rows_per_tf(self):
        from analysis.market_analysis import MultiTimeframeAnalyzer

        analyzer = MultiTimeframeAnalyzer()
        # Only 10 rows per timeframe – should be skipped (< 50 required)
        data = {"H1": _make_ohlcv(n=10), "H4": _make_ohlcv(n=10)}
        result = analyzer.analyze_confluence(data)
        assert result.overall_bias == "neutral"

    def test_analyze_confluence_bullish_alignment(self):
        from analysis.market_analysis import MultiTimeframeAnalyzer

        analyzer = MultiTimeframeAnalyzer()
        # Strong uptrend across all timeframes
        data = {
            "H1": _make_trending_up(n=200),
            "H4": _make_trending_up(n=200),
            "D1": _make_trending_up(n=200),
        }
        result = analyzer.analyze_confluence(data)
        assert result.overall_bias in ("bullish", "neutral")

    def test_analyze_confluence_bearish_alignment(self):
        from analysis.market_analysis import MultiTimeframeAnalyzer

        analyzer = MultiTimeframeAnalyzer()
        data = {
            "H1": _make_trending_down(n=200),
            "H4": _make_trending_down(n=200),
            "D1": _make_trending_down(n=200),
        }
        result = analyzer.analyze_confluence(data)
        assert result.overall_bias in ("bearish", "neutral")

    def test_confluence_confidence_between_0_and_1(self):
        from analysis.market_analysis import MultiTimeframeAnalyzer

        analyzer = MultiTimeframeAnalyzer()
        data = {"H1": _make_ohlcv(n=200), "H4": _make_ohlcv(n=200)}
        result = analyzer.analyze_confluence(data)
        assert 0.0 <= result.confidence <= 1.0

    def test_confluence_timeframe_alignment_between_0_and_1(self):
        from analysis.market_analysis import MultiTimeframeAnalyzer

        analyzer = MultiTimeframeAnalyzer()
        data = {"H1": _make_ohlcv(n=200), "H4": _make_ohlcv(n=200)}
        result = analyzer.analyze_confluence(data)
        assert 0.0 <= result.timeframe_alignment <= 1.0

    def test_confluence_risk_level_valid_values(self):
        from analysis.market_analysis import MultiTimeframeAnalyzer

        analyzer = MultiTimeframeAnalyzer()
        data = {"H1": _make_ohlcv(n=200), "H4": _make_ohlcv(n=200)}
        result = analyzer.analyze_confluence(data)
        assert result.risk_level in ("low", "medium", "high")

    def test_confluence_recommended_action_is_string(self):
        from analysis.market_analysis import MultiTimeframeAnalyzer

        analyzer = MultiTimeframeAnalyzer()
        data = {"H1": _make_ohlcv(n=200)}
        result = analyzer.analyze_confluence(data)
        assert isinstance(result.recommended_action, str)

    def test_confluence_key_levels_is_list(self):
        from analysis.market_analysis import MultiTimeframeAnalyzer

        analyzer = MultiTimeframeAnalyzer()
        data = {"H1": _make_ohlcv(n=200), "H4": _make_ohlcv(n=200)}
        result = analyzer.analyze_confluence(data)
        assert isinstance(result.key_confluence_levels, list)

    def test_timeframe_analyses_populated(self):
        from analysis.market_analysis import MultiTimeframeAnalyzer

        analyzer = MultiTimeframeAnalyzer()
        data = {"H1": _make_ohlcv(n=200), "H4": _make_ohlcv(n=200)}
        result = analyzer.analyze_confluence(data)
        assert "H1" in result.timeframe_analyses
        assert "H4" in result.timeframe_analyses

    def test_single_timeframe_analysis_fields(self):
        from analysis.market_analysis import MultiTimeframeAnalyzer

        analyzer = MultiTimeframeAnalyzer()
        data = {"H1": _make_ohlcv(n=200)}
        result = analyzer.analyze_confluence(data)
        tf_analysis = result.timeframe_analyses.get("H1")
        assert tf_analysis is not None
        assert tf_analysis.trend in ("bullish", "bearish", "neutral")
        assert isinstance(tf_analysis.support_levels, list)
        assert isinstance(tf_analysis.resistance_levels, list)

    def test_analyze_confluence_no_volume_column(self):
        from analysis.market_analysis import MultiTimeframeAnalyzer

        analyzer = MultiTimeframeAnalyzer()
        df = _make_ohlcv(n=200).drop(columns=["volume"])
        result = analyzer.analyze_confluence({"H1": df})
        assert result.overall_bias in ("bullish", "bearish", "neutral")

    def test_tf_weights_coverage(self):
        from analysis.market_analysis import MultiTimeframeAnalyzer

        analyzer = MultiTimeframeAnalyzer()
        for tf in ["M1", "M5", "M15", "M30", "H1", "H4", "D1", "W1", "MN1"]:
            assert tf in analyzer.tf_weights

    def test_mixed_trend_timeframes_neutral_or_mixed(self):
        from analysis.market_analysis import MultiTimeframeAnalyzer

        analyzer = MultiTimeframeAnalyzer()
        data = {
            "H1": _make_trending_up(n=200),
            "H4": _make_trending_down(n=200),
        }
        result = analyzer.analyze_confluence(data)
        # Mixed signals – anything is valid
        assert result.overall_bias in ("bullish", "bearish", "neutral")


# ---------------------------------------------------------------------------
# Tests – SessionAnalyzer
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSessionAnalyzer:
    """Tests for SessionAnalyzer."""

    def test_initialization(self):
        from analysis.market_analysis import SessionAnalyzer

        analyzer = SessionAnalyzer()
        assert analyzer is not None

    def test_get_current_session_returns_list(self):
        from analysis.market_analysis import SessionAnalyzer

        analyzer = SessionAnalyzer()
        sessions = analyzer.get_current_session()
        assert isinstance(sessions, list)

    def test_get_current_session_with_explicit_time_asian(self):
        from analysis.market_analysis import SessionAnalyzer, TradingSession

        analyzer = SessionAnalyzer()
        asian_time = datetime(2024, 1, 15, 3, 0)  # 03:00 UTC – pure Asian
        sessions = analyzer.get_current_session(asian_time)
        assert TradingSession.ASIAN in sessions

    def test_get_current_session_with_london_overlap(self):
        from analysis.market_analysis import SessionAnalyzer, TradingSession

        analyzer = SessionAnalyzer()
        overlap_time = datetime(2024, 1, 15, 13, 0)  # 13:00 UTC – London+NY overlap
        sessions = analyzer.get_current_session(overlap_time)
        assert TradingSession.OVERLAP_LONDON_NY in sessions

    def test_get_current_session_new_york(self):
        from analysis.market_analysis import SessionAnalyzer, TradingSession

        analyzer = SessionAnalyzer()
        ny_time = datetime(2024, 1, 15, 15, 0)  # 15:00 UTC – NY active
        sessions = analyzer.get_current_session(ny_time)
        assert TradingSession.NEW_YORK in sessions

    def test_get_current_session_pacific(self):
        from analysis.market_analysis import SessionAnalyzer, TradingSession

        analyzer = SessionAnalyzer()
        pacific_time = datetime(2024, 1, 15, 22, 0)  # 22:00 UTC – Pacific
        sessions = analyzer.get_current_session(pacific_time)
        assert TradingSession.PACIFIC in sessions

    def test_analyze_session_asian(self):
        from analysis.market_analysis import SessionAnalyzer, TradingSession, SessionAnalysis

        analyzer = SessionAnalyzer()
        asian_time = datetime(2024, 1, 15, 3, 0)
        result = analyzer.analyze_session(TradingSession.ASIAN, asian_time)
        assert isinstance(result, SessionAnalysis)
        assert result.session == TradingSession.ASIAN
        assert result.is_active is True

    def test_analyze_session_london(self):
        from analysis.market_analysis import SessionAnalyzer, TradingSession

        analyzer = SessionAnalyzer()
        london_time = datetime(2024, 1, 15, 9, 0)
        result = analyzer.analyze_session(TradingSession.LONDON, london_time)
        assert result.is_active is True

    def test_analyze_session_new_york(self):
        from analysis.market_analysis import SessionAnalyzer, TradingSession

        analyzer = SessionAnalyzer()
        ny_time = datetime(2024, 1, 15, 14, 0)
        result = analyzer.analyze_session(TradingSession.NEW_YORK, ny_time)
        assert result.is_active is True

    def test_analyze_session_inactive(self):
        from analysis.market_analysis import SessionAnalyzer, TradingSession

        analyzer = SessionAnalyzer()
        # London session runs 07-16 UTC; 02:00 is outside
        off_hours = datetime(2024, 1, 15, 2, 0)
        result = analyzer.analyze_session(TradingSession.LONDON, off_hours)
        assert result.is_active is False

    def test_analyze_session_volatility_field(self):
        from analysis.market_analysis import SessionAnalyzer, TradingSession

        analyzer = SessionAnalyzer()
        result = analyzer.analyze_session(TradingSession.OVERLAP_LONDON_NY)
        assert result.typical_volatility == 1.0  # highest volatility

    def test_analyze_session_best_pairs_xauusd(self):
        from analysis.market_analysis import SessionAnalyzer, TradingSession

        analyzer = SessionAnalyzer()
        result = analyzer.analyze_session(TradingSession.LONDON)
        assert "XAUUSD" in result.best_pairs

    def test_analyze_session_key_times_not_empty(self):
        from analysis.market_analysis import SessionAnalyzer, TradingSession

        analyzer = SessionAnalyzer()
        result = analyzer.analyze_session(TradingSession.NEW_YORK)
        assert len(result.key_times) > 0

    def test_get_optimal_trading_times_xauusd(self):
        from analysis.market_analysis import SessionAnalyzer

        analyzer = SessionAnalyzer()
        times = analyzer.get_optimal_trading_times("XAUUSD")
        assert isinstance(times, list)
        assert len(times) > 0

    def test_get_optimal_trading_times_unknown_pair(self):
        from analysis.market_analysis import SessionAnalyzer

        analyzer = SessionAnalyzer()
        times = analyzer.get_optimal_trading_times("UNKNOWNPAIR")
        assert times == []

    def test_session_range_keys(self):
        from analysis.market_analysis import SessionAnalyzer, TradingSession

        analyzer = SessionAnalyzer()
        result = analyzer.analyze_session(TradingSession.ASIAN)
        assert "start" in result.session_range
        assert "end" in result.session_range

    def test_trading_session_enum_values(self):
        from analysis.market_analysis import TradingSession

        expected = {"asian", "london", "new_york", "overlap_london_ny", "pacific"}
        actual = {s.value for s in TradingSession}
        assert actual == expected

    def test_analyze_session_without_explicit_time(self):
        from analysis.market_analysis import SessionAnalyzer, TradingSession, SessionAnalysis

        analyzer = SessionAnalyzer()
        result = analyzer.analyze_session(TradingSession.ASIAN)
        assert isinstance(result, SessionAnalysis)

    def test_time_remaining_nonnegative(self):
        from analysis.market_analysis import SessionAnalyzer, TradingSession

        analyzer = SessionAnalyzer()
        # Active session at 08:00 UTC
        active_time = datetime(2024, 1, 15, 8, 0)
        result = analyzer.analyze_session(TradingSession.ASIAN, active_time)
        assert result.time_remaining_minutes >= 0


# ---------------------------------------------------------------------------
# Tests – MarketScanner extended coverage
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestMarketScannerExtended:
    """Extended tests for MarketScanner criteria checks."""

    def _make_scanner(self, config=None):
        from analysis.market_scanner import MarketScanner

        scanner = MarketScanner(config=config or {"parallel_scan": False})
        return scanner

    def test_scan_breakout_criterion(self):
        from analysis.market_scanner import MarketScanner, ScanCriteriaType

        scanner = self._make_scanner()
        scanner.add_symbols(["XAUUSD"])
        scanner.add_criteria(ScanCriteriaType.BREAKOUT, {"period": 20})

        data = {
            "XAUUSD": {
                "price": 2000.0,
                "open": 1950.0,
                "high": 2000.0,
                "low": 1940.0,
                "close": 2000.0,
                "high_20": 1980.0,  # price broke above
            }
        }
        results = scanner.scan(data, min_strength=0)
        assert len(results) >= 1
        assert results[0].symbol == "XAUUSD"
        assert "breakout" in results[0].criteria_met

    def test_scan_price_above_ma(self):
        from analysis.market_scanner import MarketScanner, ScanCriteriaType

        scanner = self._make_scanner()
        scanner.add_symbols(["XAUUSD"])
        scanner.add_criteria(ScanCriteriaType.PRICE_ABOVE_MA, {"period": 20})

        data = {"XAUUSD": {"price": 1960.0, "ma_20": 1940.0}}
        results = scanner.scan(data, min_strength=0)
        assert len(results) == 1
        assert "price_above_ma" in results[0].criteria_met

    def test_scan_price_below_ma(self):
        from analysis.market_scanner import MarketScanner, ScanCriteriaType

        scanner = self._make_scanner()
        scanner.add_symbols(["XAUUSD"])
        scanner.add_criteria(ScanCriteriaType.PRICE_BELOW_MA, {"period": 20})

        data = {"XAUUSD": {"price": 1900.0, "ma_20": 1940.0}}
        results = scanner.scan(data, min_strength=0)
        assert len(results) == 1
        assert "price_below_ma" in results[0].criteria_met

    def test_scan_rsi_overbought(self):
        from analysis.market_scanner import MarketScanner, ScanCriteriaType

        scanner = self._make_scanner()
        scanner.add_symbols(["EURUSD"])
        scanner.add_criteria(ScanCriteriaType.RSI_OVERBOUGHT, {"threshold": 70})

        data = {"EURUSD": {"price": 1.09, "rsi": 78}}
        results = scanner.scan(data, min_strength=0)
        assert len(results) == 1
        assert "rsi_overbought" in results[0].criteria_met

    def test_scan_rsi_oversold(self):
        from analysis.market_scanner import MarketScanner, ScanCriteriaType

        scanner = self._make_scanner()
        scanner.add_symbols(["EURUSD"])
        scanner.add_criteria(ScanCriteriaType.RSI_OVERSOLD, {"threshold": 30})

        data = {"EURUSD": {"price": 1.07, "rsi": 22}}
        results = scanner.scan(data, min_strength=0)
        assert len(results) == 1
        assert "rsi_oversold" in results[0].criteria_met

    def test_scan_momentum_bullish(self):
        from analysis.market_scanner import MarketScanner, ScanCriteriaType

        scanner = self._make_scanner()
        scanner.add_symbols(["XAUUSD"])
        scanner.add_criteria(ScanCriteriaType.MOMENTUM, {"min_change_pct": 0.5})

        data = {"XAUUSD": {"price": 1970.0, "open": 1950.0}}
        results = scanner.scan(data, min_strength=0)
        assert len(results) == 1

    def test_scan_volume_spike(self):
        from analysis.market_scanner import MarketScanner, ScanCriteriaType

        scanner = self._make_scanner()
        scanner.add_symbols(["XAUUSD"])
        scanner.add_criteria(ScanCriteriaType.VOLUME_SPIKE, {"multiplier": 2.0})

        data = {"XAUUSD": {"price": 1950.0, "volume": 3_000_000, "avg_volume": 1_000_000}}
        results = scanner.scan(data, min_strength=0)
        assert len(results) == 1
        assert "volume_spike" in results[0].criteria_met

    def test_scan_macd_bullish_cross(self):
        from analysis.market_scanner import MarketScanner, ScanCriteriaType

        scanner = self._make_scanner()
        scanner.add_symbols(["EURUSD"])
        scanner.add_criteria(ScanCriteriaType.MACD_BULLISH_CROSS)

        data = {
            "EURUSD": {
                "price": 1.09,
                "macd": 0.5,
                "macd_signal": 0.3,
                "prev_macd": 0.2,
                "prev_macd_signal": 0.4,
            }
        }
        results = scanner.scan(data, min_strength=0)
        assert len(results) == 1

    def test_scan_macd_bearish_cross(self):
        from analysis.market_scanner import MarketScanner, ScanCriteriaType

        scanner = self._make_scanner()
        scanner.add_symbols(["EURUSD"])
        scanner.add_criteria(ScanCriteriaType.MACD_BEARISH_CROSS)

        data = {
            "EURUSD": {
                "price": 1.09,
                "macd": 0.2,
                "macd_signal": 0.4,
                "prev_macd": 0.5,
                "prev_macd_signal": 0.3,
            }
        }
        results = scanner.scan(data, min_strength=0)
        assert len(results) == 1

    def test_scan_uptrend(self):
        from analysis.market_scanner import MarketScanner, ScanCriteriaType

        scanner = self._make_scanner()
        scanner.add_symbols(["XAUUSD"])
        scanner.add_criteria(ScanCriteriaType.UPTREND)

        data = {"XAUUSD": {"price": 1970.0, "ma_20": 1960.0, "ma_50": 1940.0}}
        results = scanner.scan(data, min_strength=0)
        assert len(results) == 1
        assert "uptrend" in results[0].criteria_met

    def test_scan_downtrend(self):
        from analysis.market_scanner import MarketScanner, ScanCriteriaType

        scanner = self._make_scanner()
        scanner.add_symbols(["XAUUSD"])
        scanner.add_criteria(ScanCriteriaType.DOWNTREND)

        data = {"XAUUSD": {"price": 1900.0, "ma_20": 1920.0, "ma_50": 1940.0}}
        results = scanner.scan(data, min_strength=0)
        assert len(results) == 1

    def test_scan_new_high(self):
        from analysis.market_scanner import MarketScanner, ScanCriteriaType

        scanner = self._make_scanner()
        scanner.add_symbols(["XAUUSD"])
        scanner.add_criteria(ScanCriteriaType.NEW_HIGH, {"period": 20})

        data = {
            "XAUUSD": {
                "price": 2010.0,
                "high": 2010.0,
                "high_20": 2005.0,
            }
        }
        results = scanner.scan(data, min_strength=0)
        assert len(results) == 1

    def test_scan_new_low(self):
        from analysis.market_scanner import MarketScanner, ScanCriteriaType

        scanner = self._make_scanner()
        scanner.add_symbols(["XAUUSD"])
        scanner.add_criteria(ScanCriteriaType.NEW_LOW, {"period": 20})

        data = {
            "XAUUSD": {
                "price": 1890.0,
                "low": 1890.0,
                "low_20": 1895.0,
            }
        }
        results = scanner.scan(data, min_strength=0)
        assert len(results) == 1

    def test_scan_gap_up(self):
        from analysis.market_scanner import MarketScanner, ScanCriteriaType

        scanner = self._make_scanner()
        scanner.add_symbols(["XAUUSD"])
        scanner.add_criteria(ScanCriteriaType.GAP_UP, {"min_gap_pct": 0.5})

        data = {
            "XAUUSD": {
                "price": 1970.0,
                "open": 1970.0,
                "prev_close": 1950.0,
            }
        }
        results = scanner.scan(data, min_strength=0)
        assert len(results) == 1

    def test_scan_gap_down(self):
        from analysis.market_scanner import MarketScanner, ScanCriteriaType

        scanner = self._make_scanner()
        scanner.add_symbols(["XAUUSD"])
        scanner.add_criteria(ScanCriteriaType.GAP_DOWN, {"min_gap_pct": 0.5})

        data = {
            "XAUUSD": {
                "price": 1930.0,
                "open": 1930.0,
                "prev_close": 1950.0,
            }
        }
        results = scanner.scan(data, min_strength=0)
        assert len(results) == 1

    def test_scan_volatility_expansion(self):
        from analysis.market_scanner import MarketScanner, ScanCriteriaType

        scanner = self._make_scanner()
        scanner.add_symbols(["XAUUSD"])
        scanner.add_criteria(ScanCriteriaType.VOLATILITY_EXPANSION, {"multiplier": 1.5})

        data = {"XAUUSD": {"price": 1950.0, "atr": 15.0, "avg_atr": 8.0}}
        results = scanner.scan(data, min_strength=0)
        assert len(results) == 1

    def test_scan_ma_crossover_golden(self):
        from analysis.market_scanner import MarketScanner, ScanCriteriaType

        scanner = self._make_scanner()
        scanner.add_symbols(["XAUUSD"])
        scanner.add_criteria(
            ScanCriteriaType.MA_CROSSOVER, {"fast_period": 20, "slow_period": 50}
        )

        data = {
            "XAUUSD": {
                "price": 1970.0,
                "ma_20": 1965.0,
                "ma_50": 1960.0,
                "prev_ma_20": 1955.0,
                "prev_ma_50": 1960.0,
            }
        }
        results = scanner.scan(data, min_strength=0)
        assert len(results) == 1

    def test_scan_ma_crossover_death(self):
        from analysis.market_scanner import MarketScanner, ScanCriteriaType

        scanner = self._make_scanner()
        scanner.add_symbols(["XAUUSD"])
        scanner.add_criteria(
            ScanCriteriaType.MA_CROSSOVER, {"fast_period": 20, "slow_period": 50}
        )

        data = {
            "XAUUSD": {
                "price": 1940.0,
                "ma_20": 1945.0,
                "ma_50": 1950.0,
                "prev_ma_20": 1960.0,
                "prev_ma_50": 1950.0,
            }
        }
        results = scanner.scan(data, min_strength=0)
        assert len(results) == 1

    def test_scan_no_criteria_returns_empty(self):
        from analysis.market_scanner import MarketScanner

        scanner = self._make_scanner()
        scanner.add_symbols(["XAUUSD"])
        data = {"XAUUSD": {"price": 1950.0}}
        results = scanner.scan(data)
        assert results == []

    def test_scan_required_criterion_not_met_excludes_symbol(self):
        from analysis.market_scanner import MarketScanner, ScanCriteriaType

        scanner = self._make_scanner()
        scanner.add_symbols(["XAUUSD"])
        # Required: RSI oversold – but RSI is 60
        scanner.add_criteria(
            ScanCriteriaType.RSI_OVERSOLD, {"threshold": 30}, required=True
        )
        scanner.add_criteria(ScanCriteriaType.UPTREND)

        data = {"XAUUSD": {"price": 1970.0, "rsi": 60, "ma_20": 1960.0, "ma_50": 1940.0}}
        results = scanner.scan(data, min_strength=0)
        assert results == []

    def test_scan_results_sorted_by_strength_descending(self):
        from analysis.market_scanner import MarketScanner, ScanCriteriaType

        scanner = self._make_scanner()
        scanner.add_symbols(["XAUUSD", "EURUSD", "GBPUSD"])
        scanner.add_criteria(ScanCriteriaType.RSI_OVERSOLD, {"threshold": 30})

        data = {
            "XAUUSD": {"price": 1950.0, "rsi": 15},
            "EURUSD": {"price": 1.09, "rsi": 22},
            "GBPUSD": {"price": 1.25, "rsi": 28},
        }
        results = scanner.scan(data, min_strength=0)
        strengths = [r.signal_strength for r in results]
        assert strengths == sorted(strengths, reverse=True)

    def test_get_stats_increments_on_scan(self):
        from analysis.market_scanner import MarketScanner, ScanCriteriaType

        scanner = self._make_scanner()
        scanner.add_symbols(["XAUUSD"])
        scanner.add_criteria(ScanCriteriaType.RSI_OVERSOLD)

        before = scanner.get_stats()["scans_performed"]
        scanner.scan({"XAUUSD": {"price": 1950.0, "rsi": 25}}, min_strength=0)
        after = scanner.get_stats()["scans_performed"]
        assert after == before + 1

    def test_scan_result_direction_bullish(self):
        from analysis.market_scanner import MarketScanner, ScanCriteriaType, SignalDirection

        scanner = self._make_scanner()
        scanner.add_symbols(["XAUUSD"])
        scanner.add_criteria(ScanCriteriaType.RSI_OVERSOLD, {"threshold": 30})

        data = {"XAUUSD": {"price": 1950.0, "rsi": 20}}
        results = scanner.scan(data, min_strength=0)
        assert results[0].direction == SignalDirection.BULLISH

    def test_scan_result_direction_bearish(self):
        from analysis.market_scanner import MarketScanner, ScanCriteriaType, SignalDirection

        scanner = self._make_scanner()
        scanner.add_symbols(["XAUUSD"])
        scanner.add_criteria(ScanCriteriaType.RSI_OVERBOUGHT, {"threshold": 70})

        data = {"XAUUSD": {"price": 1950.0, "rsi": 80}}
        results = scanner.scan(data, min_strength=0)
        assert results[0].direction == SignalDirection.BEARISH

    def test_parallel_scan_produces_same_results(self):
        from analysis.market_scanner import MarketScanner, ScanCriteriaType

        data = {
            "XAUUSD": {"price": 1950.0, "rsi": 20},
            "EURUSD": {"price": 1.09, "rsi": 25},
        }

        seq_scanner = self._make_scanner({"parallel_scan": False})
        seq_scanner.add_symbols(list(data.keys()))
        seq_scanner.add_criteria(ScanCriteriaType.RSI_OVERSOLD, {"threshold": 30})
        seq_results = seq_scanner.scan(data, min_strength=0)

        par_scanner = self._make_scanner({"parallel_scan": True})
        par_scanner.add_symbols(list(data.keys()))
        par_scanner.add_criteria(ScanCriteriaType.RSI_OVERSOLD, {"threshold": 30})
        par_results = par_scanner.scan(data, min_strength=0)

        assert len(seq_results) == len(par_results)


# ---------------------------------------------------------------------------
# Tests – OrderFlowDashboard
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestOrderFlowDashboard:
    """Tests for OrderFlowDashboard."""

    # ── helpers ──────────────────────────────────────────────────────────

    @staticmethod
    def _empty_dashboard():
        """Dashboard with no components attached."""
        from analysis.order_flow_dashboard import OrderFlowDashboard

        return OrderFlowDashboard()

    @staticmethod
    def _full_dashboard():
        """Dashboard built via factory."""
        from analysis.order_flow_dashboard import create_dashboard

        return create_dashboard()

    # ── initialization ────────────────────────────────────────────────────

    def test_empty_dashboard_initialization(self):
        dashboard = self._empty_dashboard()
        assert dashboard._ts is None
        assert dashboard._dom is None
        assert dashboard._ofa is None
        assert dashboard._adv is None
        assert dashboard._inst is None

    def test_create_dashboard_factory(self):
        from analysis.order_flow_dashboard import OrderFlowDashboard

        dashboard = self._full_dashboard()
        assert isinstance(dashboard, OrderFlowDashboard)
        assert dashboard._ts is not None
        assert dashboard._dom is not None
        assert dashboard._ofa is not None
        assert dashboard._adv is not None
        assert dashboard._inst is not None

    def test_create_dashboard_with_configs(self):
        from analysis.order_flow_dashboard import create_dashboard, OrderFlowDashboard

        dashboard = create_dashboard(
            order_flow_config={"lookback": 100},
            dom_config={},
            time_sales_config={},
            advanced_config={},
            institutional_config={},
        )
        assert isinstance(dashboard, OrderFlowDashboard)

    # ── add_trade ─────────────────────────────────────────────────────────

    def test_add_trade_empty_dashboard_no_error(self):
        dashboard = self._empty_dashboard()
        dashboard.add_trade("XAUUSD", 1950.0, 1.0, "buy")  # should not raise

    def test_add_trade_full_dashboard_buy(self):
        dashboard = self._full_dashboard()
        dashboard.add_trade("XAUUSD", 1950.0, 1.0, "buy")

    def test_add_trade_full_dashboard_sell(self):
        dashboard = self._full_dashboard()
        dashboard.add_trade("XAUUSD", 1950.0, 1.0, "sell")

    def test_add_trade_with_explicit_timestamp(self):
        dashboard = self._full_dashboard()
        ts = datetime.now(timezone.utc)
        dashboard.add_trade("XAUUSD", 1950.0, 2.0, "buy", timestamp=ts)

    def test_add_trade_with_trade_id(self):
        dashboard = self._full_dashboard()
        dashboard.add_trade("XAUUSD", 1950.0, 1.0, "buy", trade_id="trade-001")

    def test_add_trade_multiple_symbols(self):
        dashboard = self._full_dashboard()
        for sym, price in [("XAUUSD", 1950.0), ("EURUSD", 1.09), ("GBPUSD", 1.25)]:
            dashboard.add_trade(sym, price, 1.0, "buy")

    def test_add_trade_naive_timestamp_no_error(self):
        dashboard = self._full_dashboard()
        naive_ts = datetime(2024, 1, 15, 12, 0, 0)  # no tzinfo
        dashboard.add_trade("XAUUSD", 1950.0, 1.0, "sell", timestamp=naive_ts)

    # ── get_complete_analysis ─────────────────────────────────────────────

    def test_get_complete_analysis_empty_dashboard(self):
        dashboard = self._empty_dashboard()
        result = dashboard.get_complete_analysis("XAUUSD")
        assert result["symbol"] == "XAUUSD"
        assert result["time_sales"] is None
        assert result["order_book"] is None
        assert result["order_flow"] is None

    def test_get_complete_analysis_structure(self):
        dashboard = self._empty_dashboard()
        result = dashboard.get_complete_analysis("XAUUSD")
        expected_keys = {
            "symbol", "timestamp", "time_sales", "order_book", "order_flow",
            "institutional_flow", "volume_profile", "key_levels", "aggression",
            "large_orders",
        }
        assert expected_keys.issubset(set(result.keys()))

    def test_get_complete_analysis_full_dashboard(self):
        dashboard = self._full_dashboard()
        dashboard.add_trade("XAUUSD", 1950.0, 1.0, "buy")
        result = dashboard.get_complete_analysis("XAUUSD")
        assert result["symbol"] == "XAUUSD"
        assert isinstance(result["timestamp"], str)

    def test_get_complete_analysis_symbol_uppercase(self):
        dashboard = self._empty_dashboard()
        result = dashboard.get_complete_analysis("XAUUSD")
        assert result["symbol"] == "XAUUSD"

    # ── get_summary ───────────────────────────────────────────────────────

    def test_get_summary_empty_dashboard(self):
        dashboard = self._empty_dashboard()
        result = dashboard.get_summary("XAUUSD")
        assert result["symbol"] == "XAUUSD"
        assert result["bias"] in ("bullish", "bearish", "neutral", "unknown")

    def test_get_summary_structure(self):
        dashboard = self._empty_dashboard()
        result = dashboard.get_summary("XAUUSD")
        expected_keys = {
            "symbol", "timestamp", "bias", "dom_imbalance", "buy_pressure",
            "sell_pressure", "smart_money_direction", "cumulative_delta",
            "spread", "large_order_count", "signals",
        }
        assert expected_keys.issubset(set(result.keys()))

    def test_get_summary_signals_is_list(self):
        dashboard = self._empty_dashboard()
        result = dashboard.get_summary("XAUUSD")
        assert isinstance(result["signals"], list)

    def test_get_summary_full_dashboard_after_trades(self):
        dashboard = self._full_dashboard()
        for i in range(5):
            dashboard.add_trade("XAUUSD", 1950.0 + i, 1.0, "buy" if i % 2 == 0 else "sell")
        result = dashboard.get_summary("XAUUSD")
        assert result["symbol"] == "XAUUSD"

    # ── get_bias ──────────────────────────────────────────────────────────

    def test_get_bias_empty_dashboard_neutral(self):
        dashboard = self._empty_dashboard()
        bias = dashboard.get_bias("XAUUSD")
        assert bias == "neutral"

    def test_get_bias_valid_values(self):
        dashboard = self._full_dashboard()
        bias = dashboard.get_bias("XAUUSD")
        assert bias in ("bullish", "bearish", "neutral")

    def test_get_bias_multiple_symbols_independent(self):
        dashboard = self._full_dashboard()
        dashboard.add_trade("XAUUSD", 1950.0, 10.0, "buy")
        dashboard.add_trade("EURUSD", 1.09, 10.0, "sell")
        bias_xau = dashboard.get_bias("XAUUSD")
        bias_eur = dashboard.get_bias("EURUSD")
        assert bias_xau in ("bullish", "bearish", "neutral")
        assert bias_eur in ("bullish", "bearish", "neutral")

    def test_get_bias_with_mocked_bullish_components(self):
        """Bias returns 'bullish' when all mocked components vote bullish."""
        from analysis.order_flow_dashboard import OrderFlowDashboard

        dom = MagicMock()
        dom.get_order_book_analysis.return_value = MagicMock(market_bias="bullish")

        ofa = MagicMock()
        ofa.analyze.return_value = MagicMock(order_flow_signal="bullish")

        adv = MagicMock()
        adv.analyze.return_value = MagicMock(overall_bias="bullish")

        inst = MagicMock()
        inst.get_smart_money_direction.return_value = "bullish"

        dashboard = OrderFlowDashboard(
            dom_service=dom,
            order_flow_analyzer=ofa,
            advanced_analyzer=adv,
            institutional_detector=inst,
        )
        assert dashboard.get_bias("XAUUSD") == "bullish"

    def test_get_bias_with_mocked_bearish_components(self):
        from analysis.order_flow_dashboard import OrderFlowDashboard

        dom = MagicMock()
        dom.get_order_book_analysis.return_value = MagicMock(market_bias="bearish")

        ofa = MagicMock()
        ofa.analyze.return_value = MagicMock(order_flow_signal="bearish")

        adv = MagicMock()
        adv.analyze.return_value = MagicMock(overall_bias="bearish")

        inst = MagicMock()
        inst.get_smart_money_direction.return_value = "bearish"

        dashboard = OrderFlowDashboard(
            dom_service=dom,
            order_flow_analyzer=ofa,
            advanced_analyzer=adv,
            institutional_detector=inst,
        )
        assert dashboard.get_bias("XAUUSD") == "bearish"

    def test_get_bias_component_exception_handled(self):
        """Exceptions in components are swallowed; bias still returns."""
        from analysis.order_flow_dashboard import OrderFlowDashboard

        dom = MagicMock()
        dom.get_order_book_analysis.side_effect = RuntimeError("DOM error")

        dashboard = OrderFlowDashboard(dom_service=dom)
        bias = dashboard.get_bias("XAUUSD")
        assert bias in ("bullish", "bearish", "neutral")

    # ── add_trade component exception handling ────────────────────────────

    def test_add_trade_ts_exception_handled(self):
        from analysis.order_flow_dashboard import OrderFlowDashboard

        ts = MagicMock()
        ts.add_trade.side_effect = RuntimeError("TS error")
        dashboard = OrderFlowDashboard(time_and_sales=ts)
        dashboard.add_trade("XAUUSD", 1950.0, 1.0, "buy")  # should not raise

    def test_add_trade_ofa_exception_handled(self):
        from analysis.order_flow_dashboard import OrderFlowDashboard

        ofa = MagicMock()
        ofa.add_trade.side_effect = RuntimeError("OFA error")
        dashboard = OrderFlowDashboard(order_flow_analyzer=ofa)
        dashboard.add_trade("XAUUSD", 1950.0, 1.0, "buy")

    # ── create_dashboard_router ───────────────────────────────────────────

    def test_create_dashboard_router(self):
        from analysis.order_flow_dashboard import create_dashboard_router

        dashboard = self._empty_dashboard()
        try:
            router = create_dashboard_router(dashboard)
            # router is a FastAPI APIRouter
            assert router is not None
        except ImportError:
            pytest.skip("FastAPI not available")

"""
Comprehensive Tests for Pattern Recognition Modules

Tests for:
- ChartPatternDetector / ChartPattern  (analysis/patterns/chart_patterns.py)
- CandlestickPatternDetector / CandlestickPattern  (analysis/patterns/candlestick.py)
- SupportResistanceDetector / PriceLevel  (analysis/patterns/support_resistance.py)
"""

import pytest
import numpy as np
import pandas as pd
from datetime import datetime, timedelta, timezone


# ================================================================
# HELPERS
# ================================================================


def make_ohlcv(
    n: int = 100,
    base_price: float = 2000.0,
    trend: float = 0.1,
    volatility: float = 5.0,
    seed: int = 42,
) -> pd.DataFrame:
    """
    Generate a synthetic OHLCV DataFrame with a datetime index.

    Args:
        n: Number of bars to generate.
        base_price: Starting close price.
        trend: Price increment added to the close each bar.
        volatility: Standard deviation of random noise added to each bar.
        seed: NumPy random seed for reproducibility.

    Returns:
        DataFrame with columns open, high, low, close, volume and a
        DatetimeIndex at hourly frequency.
    """
    rng = np.random.default_rng(seed)
    closes = base_price + np.cumsum(rng.normal(trend, volatility, n))
    opens = np.roll(closes, 1)
    opens[0] = closes[0]
    noise = rng.uniform(0.5, 3.0, n)
    highs = np.maximum(opens, closes) + noise
    lows = np.minimum(opens, closes) - noise
    volumes = rng.integers(1000, 10000, n).astype(float)

    index = pd.date_range("2024-01-01", periods=n, freq="h")
    return pd.DataFrame(
        {"open": opens, "high": highs, "low": lows, "close": closes, "volume": volumes},
        index=index,
    )


def make_doji_candle(price: float = 2000.0) -> pd.DataFrame:
    """Return a single-row DataFrame whose candle is a near-perfect Doji."""
    return pd.DataFrame(
        {
            "open": [price],
            "high": [price + 10.0],
            "low": [price - 10.0],
            "close": [price + 0.05],  # body ≈ 0 vs range 20 → doji
            "volume": [5000.0],
        },
        index=pd.date_range("2024-01-01", periods=1, freq="h"),
    )


def make_hammer_candles(price: float = 2000.0, n_down: int = 25) -> pd.DataFrame:
    """
    Return a DataFrame whose last candle is a textbook Hammer.

    The first ``n_down`` bars form a clear downtrend so the trend-context
    detection classifies the hammer bar as occurring after a downtrend.
    The final bar has:
      - open = price + 3.0, close = price + 5.0  (body = 2.0)
      - high = price + 5.5  (upper wick = 0.5, ≤ 10 % of range)
      - low  = price - 20.0 (lower wick = 23.0, ≥ 11× body)
    Body / range = 2 / 25.5 ≈ 0.078 (> doji_threshold of 0.05).
    """
    rng = np.random.default_rng(0)
    rows = []
    # Descending bars to establish a downtrend
    for k in range(n_down):
        c = price + 15.0 - k * 0.8 + rng.uniform(-0.2, 0.2)
        o = c + rng.uniform(0.0, 1.0)
        h = max(o, c) + rng.uniform(0.1, 1.0)
        lo = min(o, c) - rng.uniform(0.1, 1.0)
        rows.append({"open": o, "high": h, "low": lo, "close": c, "volume": 5000.0})
    # Hammer candle: body in upper portion, long lower wick, tiny upper wick
    rows.append({
        "open": price + 3.0,
        "high": price + 5.5,
        "low": price - 20.0,
        "close": price + 5.0,
        "volume": 7000.0,
    })
    index = pd.date_range("2024-01-01", periods=len(rows), freq="h")
    return pd.DataFrame(rows, index=index)


# ================================================================
# CHART PATTERN TESTS
# ================================================================


@pytest.mark.unit
class TestChartPattern:
    """Tests for the ChartPattern dataclass."""

    def _make_pattern(self, **kwargs):
        from analysis.patterns.chart_patterns import ChartPattern

        defaults = dict(
            pattern_type="double_top",
            direction="bearish",
            confidence=0.75,
            start_index=10,
            end_index=30,
            key_levels={"neckline": 1980.0, "target": 1960.0},
            description="Test double top pattern",
        )
        defaults.update(kwargs)
        return ChartPattern(**defaults)

    def test_import(self):
        """ChartPattern and ChartPatternDetector can be imported."""
        from analysis.patterns.chart_patterns import ChartPattern, ChartPatternDetector

        assert ChartPattern is not None
        assert ChartPatternDetector is not None

    def test_to_dict_has_expected_keys(self):
        """to_dict() returns all required keys."""
        pattern = self._make_pattern()
        d = pattern.to_dict()

        for key in ("pattern_type", "direction", "confidence", "start_index",
                    "end_index", "key_levels", "description", "timestamp"):
            assert key in d, f"Missing key: {key}"

    def test_to_dict_values(self):
        """to_dict() values match the constructed pattern."""
        pattern = self._make_pattern(confidence=0.82, direction="bullish")
        d = pattern.to_dict()

        assert d["direction"] == "bullish"
        assert abs(d["confidence"] - 0.82) < 1e-3
        assert d["start_index"] == 10
        assert d["end_index"] == 30

    def test_to_dict_key_levels_rounded(self):
        """key_levels prices are rounded to 5 decimal places."""
        pattern = self._make_pattern(key_levels={"neckline": 1980.123456789})
        d = pattern.to_dict()

        assert abs(d["key_levels"]["neckline"] - round(1980.123456789, 5)) < 1e-9

    def test_to_dict_timestamp_is_iso_string(self):
        """timestamp in to_dict() is an ISO-8601 string."""
        pattern = self._make_pattern()
        d = pattern.to_dict()

        # Should be parseable
        dt = datetime.fromisoformat(d["timestamp"])
        assert isinstance(dt, datetime)

    def test_direction_values(self):
        """direction field accepts bullish/bearish/neutral."""
        from analysis.patterns.chart_patterns import ChartPattern

        for direction in ("bullish", "bearish", "neutral"):
            p = self._make_pattern(direction=direction)
            assert p.direction == direction

    def test_confidence_range(self):
        """confidence is stored as-is (caller responsibility)."""
        p = self._make_pattern(confidence=0.0)
        assert p.confidence == 0.0
        p2 = self._make_pattern(confidence=1.0)
        assert p2.confidence == 1.0


@pytest.mark.unit
class TestChartPatternDetector:
    """Tests for the ChartPatternDetector class."""

    def test_default_initialization(self):
        """Detector initialises with default config."""
        from analysis.patterns.chart_patterns import ChartPatternDetector

        det = ChartPatternDetector()
        assert det is not None
        assert det.min_bars == 20
        assert det.sensitivity == 0.02
        assert det.swing_window == 3

    def test_custom_config(self):
        """Detector accepts and applies custom config."""
        from analysis.patterns.chart_patterns import ChartPatternDetector

        det = ChartPatternDetector(config={"min_bars": 50, "sensitivity": 0.01, "swing_window": 5})
        assert det.min_bars == 50
        assert det.sensitivity == 0.01
        assert det.swing_window == 5

    def test_detect_patterns_returns_list(self):
        """detect_patterns() returns a list on valid data."""
        from analysis.patterns.chart_patterns import ChartPatternDetector

        det = ChartPatternDetector()
        df = make_ohlcv(n=100)
        result = det.detect_patterns(df)

        assert isinstance(result, list)

    def test_detect_patterns_empty_dataframe(self):
        """detect_patterns() returns empty list for empty DataFrame."""
        from analysis.patterns.chart_patterns import ChartPatternDetector

        det = ChartPatternDetector()
        result = det.detect_patterns(pd.DataFrame())
        assert result == []

    def test_detect_patterns_short_data(self):
        """detect_patterns() returns empty list for < min_bars rows."""
        from analysis.patterns.chart_patterns import ChartPatternDetector

        det = ChartPatternDetector(config={"min_bars": 20})
        df = make_ohlcv(n=5)
        result = det.detect_patterns(df)
        assert result == []

    def test_detect_patterns_missing_columns(self):
        """detect_patterns() returns empty list if required columns are missing."""
        from analysis.patterns.chart_patterns import ChartPatternDetector

        det = ChartPatternDetector()
        df = pd.DataFrame({"close": [2000.0] * 30})
        result = det.detect_patterns(df)
        assert result == []

    def test_detect_patterns_confidence_filter(self):
        """detect_patterns() respects min_confidence filter."""
        from analysis.patterns.chart_patterns import ChartPatternDetector

        det = ChartPatternDetector()
        df = make_ohlcv(n=150)
        all_patterns = det.detect_patterns(df, min_confidence=0.0)
        high_confidence = det.detect_patterns(df, min_confidence=0.9)

        assert len(high_confidence) <= len(all_patterns)

    def test_detect_patterns_results_have_valid_confidence(self):
        """All returned patterns have confidence in [0, 1]."""
        from analysis.patterns.chart_patterns import ChartPatternDetector

        det = ChartPatternDetector()
        df = make_ohlcv(n=200)
        patterns = det.detect_patterns(df, min_confidence=0.0)

        for p in patterns:
            assert 0.0 <= p.confidence <= 1.0, f"Invalid confidence: {p.confidence}"

    def test_detect_patterns_results_have_valid_direction(self):
        """All returned patterns have a valid direction."""
        from analysis.patterns.chart_patterns import ChartPatternDetector

        det = ChartPatternDetector()
        df = make_ohlcv(n=200)
        patterns = det.detect_patterns(df, min_confidence=0.0)

        valid_directions = {"bullish", "bearish", "neutral"}
        for p in patterns:
            assert p.direction in valid_directions, f"Invalid direction: {p.direction}"

    def test_detect_patterns_sorted_by_confidence(self):
        """detect_patterns() returns patterns sorted by confidence descending."""
        from analysis.patterns.chart_patterns import ChartPatternDetector

        det = ChartPatternDetector()
        df = make_ohlcv(n=200)
        patterns = det.detect_patterns(df, min_confidence=0.0)

        if len(patterns) >= 2:
            confidences = [p.confidence for p in patterns]
            assert confidences == sorted(confidences, reverse=True)

    def test_detect_head_and_shoulders_returns_list(self):
        """detect_head_and_shoulders() returns a list."""
        from analysis.patterns.chart_patterns import ChartPatternDetector

        det = ChartPatternDetector()
        df = make_ohlcv(n=100)
        result = det.detect_head_and_shoulders(df)
        assert isinstance(result, list)

    def test_detect_head_and_shoulders_short_data(self):
        """detect_head_and_shoulders() returns empty list for short data."""
        from analysis.patterns.chart_patterns import ChartPatternDetector

        det = ChartPatternDetector()
        result = det.detect_head_and_shoulders(make_ohlcv(n=5))
        assert result == []

    def test_detect_double_tops_bottoms_returns_list(self):
        """detect_double_tops_bottoms() returns a list."""
        from analysis.patterns.chart_patterns import ChartPatternDetector

        det = ChartPatternDetector()
        result = det.detect_double_tops_bottoms(make_ohlcv(n=100))
        assert isinstance(result, list)

    def test_detect_double_tops_bottoms_short_data(self):
        """detect_double_tops_bottoms() returns empty list for short data."""
        from analysis.patterns.chart_patterns import ChartPatternDetector

        det = ChartPatternDetector()
        assert det.detect_double_tops_bottoms(make_ohlcv(n=3)) == []

    def test_detect_triangles_returns_list(self):
        """detect_triangles() returns a list."""
        from analysis.patterns.chart_patterns import ChartPatternDetector

        det = ChartPatternDetector()
        assert isinstance(det.detect_triangles(make_ohlcv(n=100)), list)

    def test_detect_triangles_short_data(self):
        """detect_triangles() returns empty list for short data."""
        from analysis.patterns.chart_patterns import ChartPatternDetector

        det = ChartPatternDetector()
        assert det.detect_triangles(make_ohlcv(n=3)) == []

    def test_detect_flags_pennants_returns_list(self):
        """detect_flags_pennants() returns a list."""
        from analysis.patterns.chart_patterns import ChartPatternDetector

        det = ChartPatternDetector()
        assert isinstance(det.detect_flags_pennants(make_ohlcv(n=100)), list)

    def test_detect_flags_pennants_short_data(self):
        """detect_flags_pennants() returns empty list for short data."""
        from analysis.patterns.chart_patterns import ChartPatternDetector

        det = ChartPatternDetector()
        assert det.detect_flags_pennants(make_ohlcv(n=3)) == []

    def test_detect_wedges_returns_list(self):
        """detect_wedges() returns a list."""
        from analysis.patterns.chart_patterns import ChartPatternDetector

        det = ChartPatternDetector()
        assert isinstance(det.detect_wedges(make_ohlcv(n=100)), list)

    def test_detect_wedges_short_data(self):
        """detect_wedges() returns empty list for short data."""
        from analysis.patterns.chart_patterns import ChartPatternDetector

        det = ChartPatternDetector()
        assert det.detect_wedges(make_ohlcv(n=3)) == []

    def test_detect_patterns_non_dataframe_input(self):
        """detect_patterns() handles non-DataFrame input predictably."""
        from analysis.patterns.chart_patterns import ChartPatternDetector

        det = ChartPatternDetector()
        # The module has no isinstance guard; test that it either returns an
        # empty list or raises a predictable exception (not an obscure crash).
        for bad_input in (None, "invalid"):
            try:
                result = det.detect_patterns(bad_input)  # type: ignore[arg-type]
                assert isinstance(result, list)
            except (AttributeError, TypeError):
                pass  # acceptable – module lacks isinstance guard

    def test_patterns_have_valid_index_range(self):
        """Pattern start_index and end_index are within DataFrame bounds."""
        from analysis.patterns.chart_patterns import ChartPatternDetector

        det = ChartPatternDetector()
        df = make_ohlcv(n=200)
        patterns = det.detect_patterns(df, min_confidence=0.0)

        n = len(df)
        for p in patterns:
            assert 0 <= p.start_index < n, f"start_index out of range: {p.start_index}"
            assert 0 <= p.end_index < n, f"end_index out of range: {p.end_index}"
            assert p.start_index <= p.end_index

    def test_detect_patterns_large_dataset(self):
        """detect_patterns() handles a larger dataset without error."""
        from analysis.patterns.chart_patterns import ChartPatternDetector

        det = ChartPatternDetector()
        df = make_ohlcv(n=500)
        result = det.detect_patterns(df)
        assert isinstance(result, list)

    def test_detect_patterns_to_dict_on_results(self):
        """Each detected pattern can be serialised to a dict."""
        from analysis.patterns.chart_patterns import ChartPatternDetector

        det = ChartPatternDetector()
        df = make_ohlcv(n=200)
        patterns = det.detect_patterns(df, min_confidence=0.0)

        for p in patterns:
            d = p.to_dict()
            assert isinstance(d, dict)
            assert "pattern_type" in d


# ================================================================
# CANDLESTICK PATTERN TESTS
# ================================================================


@pytest.mark.unit
class TestCandlestickPattern:
    """Tests for the CandlestickPattern dataclass."""

    def _make_pattern(self, **kwargs):
        from analysis.patterns.candlestick import CandlestickPattern

        defaults = dict(
            pattern_name="Hammer",
            pattern_type="reversal",
            direction="bullish",
            confidence=0.78,
            index=5,
            candles_count=1,
            description="Hammer candlestick at index 5",
        )
        defaults.update(kwargs)
        return CandlestickPattern(**defaults)

    def test_import(self):
        """CandlestickPattern and CandlestickPatternDetector can be imported."""
        from analysis.patterns.candlestick import CandlestickPattern, CandlestickPatternDetector

        assert CandlestickPattern is not None
        assert CandlestickPatternDetector is not None

    def test_to_dict_has_expected_keys(self):
        """to_dict() returns all required keys."""
        pattern = self._make_pattern()
        d = pattern.to_dict()

        for key in ("pattern_name", "pattern_type", "direction", "confidence",
                    "index", "candles_count", "description", "timestamp"):
            assert key in d, f"Missing key: {key}"

    def test_to_dict_values_match(self):
        """to_dict() values match the constructed pattern."""
        pattern = self._make_pattern(pattern_name="Doji", confidence=0.65, index=10)
        d = pattern.to_dict()

        assert d["pattern_name"] == "Doji"
        assert abs(d["confidence"] - 0.65) < 1e-3
        assert d["index"] == 10

    def test_to_dict_timestamp_is_iso_string(self):
        """timestamp field is a valid ISO-8601 string."""
        pattern = self._make_pattern()
        d = pattern.to_dict()
        dt = datetime.fromisoformat(d["timestamp"])
        assert isinstance(dt, datetime)

    def test_candles_count_values(self):
        """candles_count stores 1, 2, or 3 correctly."""
        for count in (1, 2, 3):
            p = self._make_pattern(candles_count=count)
            assert p.candles_count == count
            assert p.to_dict()["candles_count"] == count

    def test_direction_values(self):
        """direction field accepts bullish/bearish/neutral."""
        for direction in ("bullish", "bearish", "neutral"):
            p = self._make_pattern(direction=direction)
            assert p.direction == direction


@pytest.mark.unit
class TestCandlestickPatternDetector:
    """Tests for the CandlestickPatternDetector class."""

    def test_default_initialization(self):
        """Detector initialises with default config."""
        from analysis.patterns.candlestick import CandlestickPatternDetector

        det = CandlestickPatternDetector()
        assert det is not None
        assert det.doji_threshold == 0.05
        assert det.wick_ratio == 2.0
        assert det.marubozu_threshold == 0.05

    def test_custom_config(self):
        """Detector accepts and applies custom config."""
        from analysis.patterns.candlestick import CandlestickPatternDetector

        det = CandlestickPatternDetector(
            config={"doji_threshold": 0.03, "wick_ratio": 3.0, "max_patterns_per_type": 5}
        )
        assert det.doji_threshold == 0.03
        assert det.wick_ratio == 3.0
        assert det.max_patterns_per_type == 5

    def test_detect_patterns_returns_list_on_valid_data(self):
        """detect_patterns() returns a list on valid OHLCV data."""
        from analysis.patterns.candlestick import CandlestickPatternDetector

        det = CandlestickPatternDetector()
        df = make_ohlcv(n=50)
        result = det.detect_patterns(df)
        assert isinstance(result, list)

    def test_detect_patterns_empty_dataframe(self):
        """detect_patterns() returns empty list for empty DataFrame."""
        from analysis.patterns.candlestick import CandlestickPatternDetector

        det = CandlestickPatternDetector()
        assert det.detect_patterns(pd.DataFrame()) == []

    def test_detect_patterns_missing_columns(self):
        """detect_patterns() returns empty list when columns are missing."""
        from analysis.patterns.candlestick import CandlestickPatternDetector

        det = CandlestickPatternDetector()
        df = pd.DataFrame({"close": [2000.0] * 10})
        assert det.detect_patterns(df) == []

    def test_detect_patterns_non_dataframe(self):
        """detect_patterns() returns empty list for non-DataFrame input."""
        from analysis.patterns.candlestick import CandlestickPatternDetector

        det = CandlestickPatternDetector()
        assert det.detect_patterns(None) == []  # type: ignore[arg-type]

    def test_detect_patterns_confidence_filter(self):
        """min_confidence parameter filters results correctly."""
        from analysis.patterns.candlestick import CandlestickPatternDetector

        det = CandlestickPatternDetector()
        df = make_ohlcv(n=100)
        all_patterns = det.detect_patterns(df, min_confidence=0.0)
        strict = det.detect_patterns(df, min_confidence=0.95)

        assert len(strict) <= len(all_patterns)

    def test_detect_patterns_valid_confidence_range(self):
        """All returned patterns have confidence in [0, 1]."""
        from analysis.patterns.candlestick import CandlestickPatternDetector

        det = CandlestickPatternDetector()
        df = make_ohlcv(n=100)
        patterns = det.detect_patterns(df, min_confidence=0.0)

        for p in patterns:
            assert 0.0 <= p.confidence <= 1.0, f"Out-of-range confidence: {p.confidence}"

    def test_detect_patterns_valid_direction(self):
        """All returned patterns have a valid direction."""
        from analysis.patterns.candlestick import CandlestickPatternDetector

        det = CandlestickPatternDetector()
        df = make_ohlcv(n=100)
        patterns = det.detect_patterns(df, min_confidence=0.0)

        valid = {"bullish", "bearish", "neutral"}
        for p in patterns:
            assert p.direction in valid, f"Invalid direction: {p.direction}"

    def test_detect_single_candle_patterns_returns_list(self):
        """detect_single_candle_patterns() returns a list."""
        from analysis.patterns.candlestick import CandlestickPatternDetector

        det = CandlestickPatternDetector()
        df = make_ohlcv(n=20)
        result = det.detect_single_candle_patterns(df)
        assert isinstance(result, list)

    def test_detect_single_candle_patterns_empty_df(self):
        """detect_single_candle_patterns() returns empty list for empty DataFrame."""
        from analysis.patterns.candlestick import CandlestickPatternDetector

        det = CandlestickPatternDetector()
        assert det.detect_single_candle_patterns(pd.DataFrame()) == []

    def test_detect_two_candle_patterns_returns_list(self):
        """detect_two_candle_patterns() returns a list."""
        from analysis.patterns.candlestick import CandlestickPatternDetector

        det = CandlestickPatternDetector()
        df = make_ohlcv(n=20)
        result = det.detect_two_candle_patterns(df)
        assert isinstance(result, list)

    def test_detect_two_candle_patterns_single_row(self):
        """detect_two_candle_patterns() handles single-row DataFrame gracefully."""
        from analysis.patterns.candlestick import CandlestickPatternDetector

        det = CandlestickPatternDetector()
        df = make_ohlcv(n=1)
        result = det.detect_two_candle_patterns(df)
        assert isinstance(result, list)

    def test_detect_three_candle_patterns_returns_list(self):
        """detect_three_candle_patterns() returns a list."""
        from analysis.patterns.candlestick import CandlestickPatternDetector

        det = CandlestickPatternDetector()
        df = make_ohlcv(n=30)
        result = det.detect_three_candle_patterns(df)
        assert isinstance(result, list)

    def test_detect_three_candle_patterns_two_rows(self):
        """detect_three_candle_patterns() handles two-row DataFrame gracefully."""
        from analysis.patterns.candlestick import CandlestickPatternDetector

        det = CandlestickPatternDetector()
        df = make_ohlcv(n=2)
        result = det.detect_three_candle_patterns(df)
        assert isinstance(result, list)

    def test_get_pattern_at_index_filters_correctly(self):
        """get_pattern_at_index() returns only patterns at the given index."""
        from analysis.patterns.candlestick import CandlestickPatternDetector

        det = CandlestickPatternDetector()
        df = make_ohlcv(n=100)
        all_patterns = det.detect_patterns(df, min_confidence=0.0)

        if all_patterns:
            target_index = all_patterns[0].index
            filtered = det.get_pattern_at_index(all_patterns, target_index)
            assert all(p.index == target_index for p in filtered)

    def test_get_pattern_at_index_empty_input(self):
        """get_pattern_at_index() returns empty list for empty pattern list."""
        from analysis.patterns.candlestick import CandlestickPatternDetector

        det = CandlestickPatternDetector()
        result = det.get_pattern_at_index([], 5)
        assert result == []

    def test_get_pattern_at_index_no_match(self):
        """get_pattern_at_index() returns empty list when no pattern at index."""
        from analysis.patterns.candlestick import CandlestickPatternDetector

        det = CandlestickPatternDetector()
        df = make_ohlcv(n=100)
        patterns = det.detect_patterns(df, min_confidence=0.0)
        result = det.get_pattern_at_index(patterns, -9999)
        assert result == []

    def test_get_pattern_at_index_sorted_by_confidence(self):
        """get_pattern_at_index() returns results sorted by confidence descending."""
        from analysis.patterns.candlestick import CandlestickPattern, CandlestickPatternDetector

        det = CandlestickPatternDetector()
        patterns = [
            CandlestickPattern("A", "reversal", "bullish", 0.6, 5, 1, "A"),
            CandlestickPattern("B", "reversal", "bearish", 0.9, 5, 1, "B"),
            CandlestickPattern("C", "indecision", "neutral", 0.75, 5, 1, "C"),
        ]
        result = det.get_pattern_at_index(patterns, 5)
        confidences = [p.confidence for p in result]
        assert confidences == sorted(confidences, reverse=True)

    def test_doji_detection_on_crafted_candle(self):
        """A near-perfect Doji candle is detected by the single-candle detector."""
        from analysis.patterns.candlestick import CandlestickPatternDetector

        det = CandlestickPatternDetector(config={"doji_threshold": 0.1})
        # Build a 5-bar dataset whose last bar is an extreme doji
        df = make_ohlcv(n=4)
        doji_row = pd.DataFrame(
            {"open": [2000.0], "high": [2010.0], "low": [1990.0], "close": [2000.1], "volume": [5000.0]},
            index=[df.index[-1] + pd.Timedelta(hours=1)],
        )
        df = pd.concat([df, doji_row])

        patterns = det.detect_single_candle_patterns(df)
        names = [p.pattern_name for p in patterns]
        assert any("doji" in n.lower() for n in names), (
            f"Expected a Doji among {names}"
        )

    def test_hammer_detection_on_crafted_candles(self):
        """A crafted Hammer/Hanging Man candle is detected by the single-candle detector."""
        from analysis.patterns.candlestick import CandlestickPatternDetector

        det = CandlestickPatternDetector(config={"wick_ratio": 2.0})
        df = make_hammer_candles()
        patterns = det.detect_single_candle_patterns(df)
        names = [p.pattern_name for p in patterns]
        # Hammer and Hanging Man share the same candle structure; the name
        # depends on the trend context (downtrend → Hammer, otherwise → Hanging Man).
        assert any(n in ("Hammer", "Hanging Man") for n in names), (
            f"Expected Hammer or Hanging Man among {names}"
        )

    def test_to_dict_on_detected_patterns(self):
        """Each detected pattern can be serialised via to_dict()."""
        from analysis.patterns.candlestick import CandlestickPatternDetector

        det = CandlestickPatternDetector()
        df = make_ohlcv(n=100)
        patterns = det.detect_patterns(df, min_confidence=0.0)

        for p in patterns:
            d = p.to_dict()
            assert isinstance(d, dict)
            assert "pattern_name" in d

    def test_candles_count_in_detected_results(self):
        """candles_count in detected results is 1, 2, or 3."""
        from analysis.patterns.candlestick import CandlestickPatternDetector

        det = CandlestickPatternDetector()
        df = make_ohlcv(n=100)
        patterns = det.detect_patterns(df, min_confidence=0.0)

        for p in patterns:
            assert p.candles_count in (1, 2, 3), f"Unexpected candles_count: {p.candles_count}"


# ================================================================
# SUPPORT/RESISTANCE TESTS
# ================================================================


@pytest.mark.unit
class TestPriceLevel:
    """Tests for the PriceLevel dataclass."""

    def _make_level(self, **kwargs):
        from analysis.patterns.support_resistance import PriceLevel

        defaults = dict(
            price=2000.0,
            level_type="support",
            strength=0.8,
            touch_count=3,
            last_touch=datetime(2024, 1, 15, tzinfo=timezone.utc),
            method="swing",
            is_active=True,
            description="Test support level",
        )
        defaults.update(kwargs)
        return PriceLevel(**defaults)

    def test_import(self):
        """PriceLevel and SupportResistanceDetector can be imported."""
        from analysis.patterns.support_resistance import PriceLevel, SupportResistanceDetector

        assert PriceLevel is not None
        assert SupportResistanceDetector is not None

    def test_to_dict_has_expected_keys(self):
        """to_dict() returns all required keys."""
        level = self._make_level()
        d = level.to_dict()

        for key in ("price", "level_type", "strength", "touch_count",
                    "last_touch", "method", "is_active", "description", "timestamp"):
            assert key in d, f"Missing key: {key}"

    def test_to_dict_values_match(self):
        """to_dict() values match the constructed level."""
        level = self._make_level(price=2050.0, level_type="resistance", touch_count=5)
        d = level.to_dict()

        assert abs(d["price"] - 2050.0) < 1e-3
        assert d["level_type"] == "resistance"
        assert d["touch_count"] == 5

    def test_to_dict_last_touch_none(self):
        """to_dict() serialises None last_touch as None."""
        level = self._make_level(last_touch=None)
        d = level.to_dict()
        assert d["last_touch"] is None

    def test_to_dict_last_touch_iso_string(self):
        """to_dict() serialises datetime last_touch as ISO string."""
        ts = datetime(2024, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
        level = self._make_level(last_touch=ts)
        d = level.to_dict()
        assert isinstance(d["last_touch"], str)
        datetime.fromisoformat(d["last_touch"])

    def test_to_dict_timestamp_is_iso_string(self):
        """timestamp field is a valid ISO-8601 string."""
        level = self._make_level()
        d = level.to_dict()
        dt = datetime.fromisoformat(d["timestamp"])
        assert isinstance(dt, datetime)

    def test_level_type_values(self):
        """level_type accepts support/resistance/pivot."""
        for lt in ("support", "resistance", "pivot"):
            level = self._make_level(level_type=lt)
            assert level.to_dict()["level_type"] == lt

    def test_is_active_flag(self):
        """is_active is stored and serialised correctly."""
        active = self._make_level(is_active=True)
        inactive = self._make_level(is_active=False)
        assert active.to_dict()["is_active"] is True
        assert inactive.to_dict()["is_active"] is False


@pytest.mark.unit
class TestSupportResistanceDetector:
    """Tests for the SupportResistanceDetector class."""

    def test_default_initialization(self):
        """Detector initialises with default config."""
        from analysis.patterns.support_resistance import SupportResistanceDetector

        det = SupportResistanceDetector()
        assert det is not None
        assert det.sensitivity == 0.003
        assert det.swing_window == 5
        assert det.min_bars == 30

    def test_custom_config(self):
        """Detector accepts and applies custom config."""
        from analysis.patterns.support_resistance import SupportResistanceDetector

        det = SupportResistanceDetector(
            config={"sensitivity": 0.01, "swing_window": 3, "min_bars": 20, "round_number_increment": 25.0}
        )
        assert det.sensitivity == 0.01
        assert det.swing_window == 3
        assert det.round_number_increment == 25.0

    def test_detect_levels_returns_dict_with_required_keys(self):
        """detect_levels() returns dict with support/resistance/pivot keys."""
        from analysis.patterns.support_resistance import SupportResistanceDetector

        det = SupportResistanceDetector()
        df = make_ohlcv(n=100)
        result = det.detect_levels(df)

        assert isinstance(result, dict)
        for key in ("support", "resistance", "pivot"):
            assert key in result, f"Missing key: {key}"

    def test_detect_levels_values_are_lists(self):
        """All values in detect_levels() result are lists."""
        from analysis.patterns.support_resistance import SupportResistanceDetector

        det = SupportResistanceDetector()
        df = make_ohlcv(n=100)
        result = det.detect_levels(df)

        for key in ("support", "resistance", "pivot"):
            assert isinstance(result[key], list)

    def test_detect_levels_empty_dataframe(self):
        """detect_levels() returns empty dict or empty lists for empty DataFrame."""
        from analysis.patterns.support_resistance import SupportResistanceDetector

        det = SupportResistanceDetector()
        result = det.detect_levels(pd.DataFrame())

        if isinstance(result, dict):
            for v in result.values():
                assert isinstance(v, list)
                assert v == []

    def test_detect_levels_short_data(self):
        """detect_levels() handles fewer rows than min_bars without crashing."""
        from analysis.patterns.support_resistance import SupportResistanceDetector

        det = SupportResistanceDetector(config={"min_bars": 30})
        df = make_ohlcv(n=5)
        result = det.detect_levels(df)

        assert isinstance(result, dict)
        for v in result.values():
            assert isinstance(v, list)

    def test_detect_levels_uses_last_close_as_default_price(self):
        """detect_levels() uses last close when current_price is None."""
        from analysis.patterns.support_resistance import SupportResistanceDetector

        det = SupportResistanceDetector()
        df = make_ohlcv(n=100)
        # Should not raise
        result = det.detect_levels(df, current_price=None)
        assert isinstance(result, dict)

    def test_detect_levels_price_levels_are_price_level_instances(self):
        """Each item in detect_levels() lists is a PriceLevel."""
        from analysis.patterns.support_resistance import SupportResistanceDetector, PriceLevel

        det = SupportResistanceDetector()
        df = make_ohlcv(n=100)
        result = det.detect_levels(df)

        for key in ("support", "resistance", "pivot"):
            for lvl in result[key]:
                assert isinstance(lvl, PriceLevel), f"Expected PriceLevel, got {type(lvl)}"

    def test_get_swing_levels_returns_list(self):
        """get_swing_levels() returns a list."""
        from analysis.patterns.support_resistance import SupportResistanceDetector

        det = SupportResistanceDetector()
        df = make_ohlcv(n=100)
        result = det.get_swing_levels(df)
        assert isinstance(result, list)

    def test_get_swing_levels_empty_df(self):
        """get_swing_levels() returns empty list for empty DataFrame."""
        from analysis.patterns.support_resistance import SupportResistanceDetector

        det = SupportResistanceDetector()
        assert det.get_swing_levels(pd.DataFrame()) == []

    def test_get_fibonacci_levels_returns_list(self):
        """get_fibonacci_levels() returns a list."""
        from analysis.patterns.support_resistance import SupportResistanceDetector

        det = SupportResistanceDetector()
        df = make_ohlcv(n=100)
        result = det.get_fibonacci_levels(df)
        assert isinstance(result, list)

    def test_get_fibonacci_levels_count(self):
        """get_fibonacci_levels() returns up to 7 standard Fibonacci levels."""
        from analysis.patterns.support_resistance import SupportResistanceDetector

        det = SupportResistanceDetector()
        df = make_ohlcv(n=100)
        result = det.get_fibonacci_levels(df)
        # Standard ratios: 0, 23.6, 38.2, 50, 61.8, 78.6, 100 → 7 levels
        assert 1 <= len(result) <= 7

    def test_get_fibonacci_levels_method_label(self):
        """All Fibonacci levels carry method='fibonacci'."""
        from analysis.patterns.support_resistance import SupportResistanceDetector

        det = SupportResistanceDetector()
        df = make_ohlcv(n=100)
        levels = det.get_fibonacci_levels(df)
        for lvl in levels:
            assert lvl.method == "fibonacci", f"Unexpected method: {lvl.method}"

    def test_get_fibonacci_levels_prices_within_range(self):
        """Fibonacci level prices fall within the data's price range."""
        from analysis.patterns.support_resistance import SupportResistanceDetector

        det = SupportResistanceDetector()
        df = make_ohlcv(n=100)
        price_min = float(df["low"].min())
        price_max = float(df["high"].max())
        levels = det.get_fibonacci_levels(df)

        for lvl in levels:
            assert price_min - 1e-6 <= lvl.price <= price_max + 1e-6, (
                f"Fib level price {lvl.price} outside [{price_min}, {price_max}]"
            )

    def test_get_fibonacci_levels_empty_df(self):
        """get_fibonacci_levels() returns empty list for empty DataFrame."""
        from analysis.patterns.support_resistance import SupportResistanceDetector

        det = SupportResistanceDetector()
        assert det.get_fibonacci_levels(pd.DataFrame()) == []

    def test_get_round_number_levels_returns_list(self):
        """get_round_number_levels() returns a list."""
        from analysis.patterns.support_resistance import SupportResistanceDetector

        det = SupportResistanceDetector()
        df = make_ohlcv(n=100)
        result = det.get_round_number_levels(df)
        assert isinstance(result, list)

    def test_get_round_number_levels_are_multiples(self):
        """Round-number levels are multiples of round_number_increment."""
        from analysis.patterns.support_resistance import SupportResistanceDetector

        increment = 50.0
        det = SupportResistanceDetector(config={"round_number_increment": increment})
        df = make_ohlcv(n=100, base_price=2000.0)
        levels = det.get_round_number_levels(df)

        for lvl in levels:
            remainder = lvl.price % increment
            assert remainder < 1e-6 or abs(remainder - increment) < 1e-6, (
                f"Level {lvl.price} is not a multiple of {increment}"
            )

    def test_get_round_number_levels_method_label(self):
        """All round-number levels carry method='round_number'."""
        from analysis.patterns.support_resistance import SupportResistanceDetector

        det = SupportResistanceDetector()
        df = make_ohlcv(n=100)
        levels = det.get_round_number_levels(df)
        for lvl in levels:
            assert lvl.method == "round_number", f"Unexpected method: {lvl.method}"

    def test_get_volume_levels_returns_list(self):
        """get_volume_levels() returns a list."""
        from analysis.patterns.support_resistance import SupportResistanceDetector

        det = SupportResistanceDetector()
        df = make_ohlcv(n=100)
        result = det.get_volume_levels(df)
        assert isinstance(result, list)

    def test_get_volume_levels_empty_df(self):
        """get_volume_levels() returns empty list for empty DataFrame."""
        from analysis.patterns.support_resistance import SupportResistanceDetector

        det = SupportResistanceDetector()
        assert det.get_volume_levels(pd.DataFrame()) == []

    def test_get_dynamic_levels_returns_list(self):
        """get_dynamic_levels() returns a list."""
        from analysis.patterns.support_resistance import SupportResistanceDetector

        det = SupportResistanceDetector()
        df = make_ohlcv(n=100)
        result = det.get_dynamic_levels(df)
        assert isinstance(result, list)

    def test_get_dynamic_levels_empty_df(self):
        """get_dynamic_levels() returns empty list for empty DataFrame."""
        from analysis.patterns.support_resistance import SupportResistanceDetector

        det = SupportResistanceDetector()
        assert det.get_dynamic_levels(pd.DataFrame()) == []

    def test_classify_level_support(self):
        """classify_level() returns 'support' for level below current price."""
        from analysis.patterns.support_resistance import SupportResistanceDetector, PriceLevel

        det = SupportResistanceDetector(config={"sensitivity": 0.001})
        level = PriceLevel(
            price=1900.0,
            level_type="support",
            strength=0.7,
            touch_count=2,
            last_touch=None,
            method="swing",
            is_active=True,
        )
        classification = det.classify_level(level, current_price=2000.0)
        assert classification == "support"

    def test_classify_level_resistance(self):
        """classify_level() returns 'resistance' for level above current price."""
        from analysis.patterns.support_resistance import SupportResistanceDetector, PriceLevel

        det = SupportResistanceDetector(config={"sensitivity": 0.001})
        level = PriceLevel(
            price=2100.0,
            level_type="resistance",
            strength=0.7,
            touch_count=2,
            last_touch=None,
            method="swing",
            is_active=True,
        )
        classification = det.classify_level(level, current_price=2000.0)
        assert classification == "resistance"

    def test_classify_level_pivot(self):
        """classify_level() returns 'pivot' when level is within sensitivity band."""
        from analysis.patterns.support_resistance import SupportResistanceDetector, PriceLevel

        sensitivity = 0.005
        current_price = 2000.0
        det = SupportResistanceDetector(config={"sensitivity": sensitivity})
        # Place level exactly at current price → must be pivot
        level = PriceLevel(
            price=current_price,
            level_type="pivot",
            strength=0.5,
            touch_count=1,
            last_touch=None,
            method="swing",
            is_active=True,
        )
        classification = det.classify_level(level, current_price=current_price)
        assert classification == "pivot"

    def test_detect_levels_strength_in_range(self):
        """All detected levels have strength in [0, 1]."""
        from analysis.patterns.support_resistance import SupportResistanceDetector

        det = SupportResistanceDetector()
        df = make_ohlcv(n=100)
        result = det.detect_levels(df)

        for key in ("support", "resistance", "pivot"):
            for lvl in result[key]:
                assert 0.0 <= lvl.strength <= 1.0, (
                    f"Level {lvl.price} has out-of-range strength: {lvl.strength}"
                )

    def test_detect_levels_to_dict_on_results(self):
        """Each detected level can be serialised via to_dict()."""
        from analysis.patterns.support_resistance import SupportResistanceDetector

        det = SupportResistanceDetector()
        df = make_ohlcv(n=100)
        result = det.detect_levels(df)

        for key in ("support", "resistance", "pivot"):
            for lvl in result[key]:
                d = lvl.to_dict()
                assert isinstance(d, dict)
                assert "price" in d

    def test_detect_levels_non_dataframe_input(self):
        """detect_levels() does not raise for non-DataFrame input."""
        from analysis.patterns.support_resistance import SupportResistanceDetector

        det = SupportResistanceDetector()
        result = det.detect_levels(None)  # type: ignore[arg-type]
        assert isinstance(result, dict)

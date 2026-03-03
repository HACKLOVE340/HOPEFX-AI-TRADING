"""
Candlestick Pattern Detection

Identifies common single, dual, and multi-candlestick reversal and
continuation patterns in OHLCV price data.
"""

import logging
from dataclasses import dataclass
from typing import Dict, List, Optional

try:
    import pandas as pd  # type: ignore[import]
    HAS_PANDAS = True
except ImportError:
    pd = None  # type: ignore[assignment]
    HAS_PANDAS = False

logger = logging.getLogger(__name__)


@dataclass
class CandlestickPattern:
    """Detected candlestick pattern."""

    name: str
    pattern_type: str          # 'bullish', 'bearish', 'neutral'
    start_index: int
    end_index: int
    confidence: float          # 0.0 – 1.0
    description: str = ""

    def to_dict(self) -> Dict:
        return {
            "name": self.name,
            "pattern_type": self.pattern_type,
            "start_index": self.start_index,
            "end_index": self.end_index,
            "confidence": self.confidence,
            "description": self.description,
        }


# ---------------------------------------------------------------------------
# Candle helpers
# ---------------------------------------------------------------------------

def _candle_body(open_: float, close: float) -> float:
    """Absolute body size."""
    return abs(close - open_)


def _candle_range(high: float, low: float) -> float:
    """Total candle range."""
    return high - low


def _upper_shadow(open_: float, high: float, close: float) -> float:
    """Upper shadow length."""
    return high - max(open_, close)


def _lower_shadow(open_: float, low: float, close: float) -> float:
    """Lower shadow length."""
    return min(open_, close) - low


def _is_bullish(open_: float, close: float) -> bool:
    return close > open_


def _is_bearish(open_: float, close: float) -> bool:
    return close < open_


def _body_ratio(open_: float, close: float, high: float, low: float) -> float:
    """Body as a fraction of total range (0 if range is zero)."""
    total = _candle_range(high, low)
    if total == 0:
        return 0.0
    return _candle_body(open_, close) / total


# ---------------------------------------------------------------------------
# Doji helpers
# ---------------------------------------------------------------------------

def _is_doji(open_: float, close: float, high: float, low: float,
             threshold: float = 0.05) -> bool:
    """Body is less than *threshold* of the total range."""
    return _body_ratio(open_, close, high, low) < threshold


# ---------------------------------------------------------------------------
# Single-candle patterns
# ---------------------------------------------------------------------------

def _detect_hammer(
    opens: List[float],
    highs: List[float],
    lows: List[float],
    closes: List[float],
    i: int,
) -> Optional[CandlestickPattern]:
    """Hammer / Hanging Man detection at index *i*."""
    body = _candle_body(opens[i], closes[i])
    total = _candle_range(highs[i], lows[i])
    if total == 0:
        return None

    lower = _lower_shadow(opens[i], lows[i], closes[i])
    upper = _upper_shadow(opens[i], highs[i], closes[i])

    long_lower = lower >= 2 * body
    small_upper = upper <= body * 0.3
    decent_body = 0.1 < body / total < 0.5

    if not (long_lower and small_upper and decent_body):
        return None

    pattern_type = "bullish" if _is_bullish(opens[i], closes[i]) else "neutral"
    return CandlestickPattern(
        name="Hammer",
        pattern_type=pattern_type,
        start_index=i,
        end_index=i,
        confidence=0.65,
        description="Long lower shadow with small body near top of range",
    )


def _detect_shooting_star(
    opens: List[float],
    highs: List[float],
    lows: List[float],
    closes: List[float],
    i: int,
) -> Optional[CandlestickPattern]:
    """Shooting Star detection at index *i*."""
    body = _candle_body(opens[i], closes[i])
    total = _candle_range(highs[i], lows[i])
    if total == 0:
        return None

    upper = _upper_shadow(opens[i], highs[i], closes[i])
    lower = _lower_shadow(opens[i], lows[i], closes[i])

    long_upper = upper >= 2 * body
    small_lower = lower <= body * 0.3
    decent_body = 0.1 < body / total < 0.5

    if not (long_upper and small_lower and decent_body):
        return None

    return CandlestickPattern(
        name="Shooting Star",
        pattern_type="bearish",
        start_index=i,
        end_index=i,
        confidence=0.65,
        description="Long upper shadow with small body near bottom of range",
    )


def _detect_marubozu(
    opens: List[float],
    highs: List[float],
    lows: List[float],
    closes: List[float],
    i: int,
) -> Optional[CandlestickPattern]:
    """Marubozu (almost no shadows) detection at index *i*."""
    body = _candle_body(opens[i], closes[i])
    total = _candle_range(highs[i], lows[i])
    if total == 0:
        return None

    ratio = body / total
    if ratio < 0.9:
        return None

    if _is_bullish(opens[i], closes[i]):
        return CandlestickPattern(
            name="Bullish Marubozu",
            pattern_type="bullish",
            start_index=i,
            end_index=i,
            confidence=0.75,
            description="Full-range bullish candle with minimal shadows",
        )
    return CandlestickPattern(
        name="Bearish Marubozu",
        pattern_type="bearish",
        start_index=i,
        end_index=i,
        confidence=0.75,
        description="Full-range bearish candle with minimal shadows",
    )


def _detect_doji_pattern(
    opens: List[float],
    highs: List[float],
    lows: List[float],
    closes: List[float],
    i: int,
) -> Optional[CandlestickPattern]:
    """Doji detection at index *i*."""
    if not _is_doji(opens[i], closes[i], highs[i], lows[i]):
        return None

    upper = _upper_shadow(opens[i], highs[i], closes[i])
    lower = _lower_shadow(opens[i], lows[i], closes[i])
    total = _candle_range(highs[i], lows[i])

    if total == 0:
        return None

    upper_ratio = upper / total
    lower_ratio = lower / total

    # Dragonfly Doji: almost all range in lower shadow
    if lower_ratio > 0.8 and upper_ratio < 0.1:
        return CandlestickPattern(
            name="Dragonfly Doji",
            pattern_type="bullish",
            start_index=i,
            end_index=i,
            confidence=0.70,
            description="Doji with very long lower shadow (bullish reversal signal)",
        )

    # Gravestone Doji: almost all range in upper shadow
    if upper_ratio > 0.8 and lower_ratio < 0.1:
        return CandlestickPattern(
            name="Gravestone Doji",
            pattern_type="bearish",
            start_index=i,
            end_index=i,
            confidence=0.70,
            description="Doji with very long upper shadow (bearish reversal signal)",
        )

    return CandlestickPattern(
        name="Doji",
        pattern_type="neutral",
        start_index=i,
        end_index=i,
        confidence=0.55,
        description="Very small body indicating indecision",
    )


# ---------------------------------------------------------------------------
# Two-candle patterns
# ---------------------------------------------------------------------------

def _detect_engulfing(
    opens: List[float],
    closes: List[float],
    i: int,
) -> Optional[CandlestickPattern]:
    """Bullish / Bearish Engulfing detection ending at index *i*."""
    if i < 1:
        return None

    prev_body = _candle_body(opens[i - 1], closes[i - 1])
    curr_body = _candle_body(opens[i], closes[i])

    if prev_body == 0 or curr_body <= prev_body:
        return None

    prev_bearish = _is_bearish(opens[i - 1], closes[i - 1])
    curr_bullish = _is_bullish(opens[i], closes[i])
    curr_open_below = opens[i] < closes[i - 1]
    curr_close_above = closes[i] > opens[i - 1]

    is_bullish_engulfing = (
        prev_bearish and curr_bullish
        and curr_open_below and curr_close_above
    )
    if is_bullish_engulfing:
        return CandlestickPattern(
            name="Bullish Engulfing",
            pattern_type="bullish",
            start_index=i - 1,
            end_index=i,
            confidence=0.75,
            description="Current bullish candle fully engulfs the previous bearish candle",
        )

    prev_bullish = _is_bullish(opens[i - 1], closes[i - 1])
    curr_bearish = _is_bearish(opens[i], closes[i])
    curr_open_above = opens[i] > closes[i - 1]
    curr_close_below = closes[i] < opens[i - 1]

    is_bearish_engulfing = (
        prev_bullish and curr_bearish
        and curr_open_above and curr_close_below
    )
    if is_bearish_engulfing:
        return CandlestickPattern(
            name="Bearish Engulfing",
            pattern_type="bearish",
            start_index=i - 1,
            end_index=i,
            confidence=0.75,
            description="Current bearish candle fully engulfs the previous bullish candle",
        )

    return None


def _detect_harami(
    opens: List[float],
    closes: List[float],
    i: int,
) -> Optional[CandlestickPattern]:
    """Bullish / Bearish Harami detection ending at index *i*."""
    if i < 1:
        return None

    prev_body = _candle_body(opens[i - 1], closes[i - 1])
    curr_body = _candle_body(opens[i], closes[i])

    if prev_body == 0 or curr_body >= prev_body:
        return None

    prev_high_body = max(opens[i - 1], closes[i - 1])
    prev_low_body = min(opens[i - 1], closes[i - 1])
    curr_inside = (
        prev_low_body <= opens[i] <= prev_high_body
        and prev_low_body <= closes[i] <= prev_high_body
    )

    if not curr_inside:
        return None

    prev_bearish = _is_bearish(opens[i - 1], closes[i - 1])
    if prev_bearish:
        return CandlestickPattern(
            name="Bullish Harami",
            pattern_type="bullish",
            start_index=i - 1,
            end_index=i,
            confidence=0.60,
            description="Small bullish candle contained within previous bearish candle",
        )

    return CandlestickPattern(
        name="Bearish Harami",
        pattern_type="bearish",
        start_index=i - 1,
        end_index=i,
        confidence=0.60,
        description="Small bearish candle contained within previous bullish candle",
    )


def _detect_piercing_dark_cloud(
    opens: List[float],
    closes: List[float],
    i: int,
) -> Optional[CandlestickPattern]:
    """Piercing Line / Dark Cloud Cover ending at index *i*."""
    if i < 1:
        return None

    prev_bearish = _is_bearish(opens[i - 1], closes[i - 1])
    curr_bullish = _is_bullish(opens[i], closes[i])

    if prev_bearish and curr_bullish:
        prev_mid = (opens[i - 1] + closes[i - 1]) / 2
        opens_below = opens[i] < closes[i - 1]
        closes_above_mid = closes[i] > prev_mid
        closes_below_prev_open = closes[i] < opens[i - 1]

        if opens_below and closes_above_mid and closes_below_prev_open:
            return CandlestickPattern(
                name="Piercing Line",
                pattern_type="bullish",
                start_index=i - 1,
                end_index=i,
                confidence=0.65,
                description="Bullish candle closes above midpoint of previous bearish candle",
            )

    prev_bullish = _is_bullish(opens[i - 1], closes[i - 1])
    curr_bearish = _is_bearish(opens[i], closes[i])

    if prev_bullish and curr_bearish:
        prev_mid = (opens[i - 1] + closes[i - 1]) / 2
        opens_above = opens[i] > closes[i - 1]
        closes_below_mid = closes[i] < prev_mid
        closes_above_prev_open = closes[i] > opens[i - 1]

        if opens_above and closes_below_mid and closes_above_prev_open:
            return CandlestickPattern(
                name="Dark Cloud Cover",
                pattern_type="bearish",
                start_index=i - 1,
                end_index=i,
                confidence=0.65,
                description="Bearish candle closes below midpoint of previous bullish candle",
            )

    return None


# ---------------------------------------------------------------------------
# Three-candle patterns
# ---------------------------------------------------------------------------

def _three_candle_trend(
    opens: List[float],
    closes: List[float],
    i: int,
) -> tuple:
    """Return (all_bullish, all_bearish, rising_closes, falling_closes)."""
    all_bullish = all(
        _is_bullish(opens[j], closes[j]) for j in range(i - 2, i + 1)
    )
    all_bearish = all(
        _is_bearish(opens[j], closes[j]) for j in range(i - 2, i + 1)
    )
    rising_closes = closes[i - 1] > closes[i - 2] and closes[i] > closes[i - 1]
    falling_closes = closes[i - 1] < closes[i - 2] and closes[i] < closes[i - 1]
    return all_bullish, all_bearish, rising_closes, falling_closes


def _detect_three_soldiers_crows(
    opens: List[float],
    closes: List[float],
    i: int,
) -> Optional[CandlestickPattern]:
    """Three White Soldiers / Three Black Crows ending at index *i*."""
    if i < 2:
        return None

    all_bullish, all_bearish, rising, falling = _three_candle_trend(
        opens, closes, i
    )

    if all_bullish and rising:
        return CandlestickPattern(
            name="Three White Soldiers",
            pattern_type="bullish",
            start_index=i - 2,
            end_index=i,
            confidence=0.80,
            description="Three consecutive bullish candles with rising closes",
        )

    if all_bearish and falling:
        return CandlestickPattern(
            name="Three Black Crows",
            pattern_type="bearish",
            start_index=i - 2,
            end_index=i,
            confidence=0.80,
            description="Three consecutive bearish candles with falling closes",
        )

    return None


def _detect_morning_evening_star(
    opens: List[float],
    closes: List[float],
    i: int,
) -> Optional[CandlestickPattern]:
    """Morning Star / Evening Star ending at index *i*."""
    if i < 2:
        return None

    first_body = _candle_body(opens[i - 2], closes[i - 2])
    mid_body = _candle_body(opens[i - 1], closes[i - 1])
    last_body = _candle_body(opens[i], closes[i])

    if first_body == 0 or last_body == 0:
        return None

    mid_is_small = mid_body < first_body * 0.4
    last_is_large = last_body >= first_body * 0.5

    if not (mid_is_small and last_is_large):
        return None

    first_bearish = _is_bearish(opens[i - 2], closes[i - 2])
    last_bullish = _is_bullish(opens[i], closes[i])
    last_close_deep = closes[i] > (opens[i - 2] + closes[i - 2]) / 2

    if first_bearish and last_bullish and last_close_deep:
        return CandlestickPattern(
            name="Morning Star",
            pattern_type="bullish",
            start_index=i - 2,
            end_index=i,
            confidence=0.80,
            description="Bearish candle, indecision candle, then strong bullish candle",
        )

    first_bullish = _is_bullish(opens[i - 2], closes[i - 2])
    last_bearish = _is_bearish(opens[i], closes[i])
    last_close_high = closes[i] < (opens[i - 2] + closes[i - 2]) / 2

    if first_bullish and last_bearish and last_close_high:
        return CandlestickPattern(
            name="Evening Star",
            pattern_type="bearish",
            start_index=i - 2,
            end_index=i,
            confidence=0.80,
            description="Bullish candle, indecision candle, then strong bearish candle",
        )

    return None


# ---------------------------------------------------------------------------
# Pattern detector
# ---------------------------------------------------------------------------

_SINGLE_DETECTORS = [
    _detect_doji_pattern,
    _detect_hammer,
    _detect_shooting_star,
    _detect_marubozu,
]

_TWO_CANDLE_DETECTORS = [
    _detect_engulfing,
    _detect_harami,
    _detect_piercing_dark_cloud,
]

_THREE_CANDLE_DETECTORS = [
    _detect_three_soldiers_crows,
    _detect_morning_evening_star,
]


class CandlestickPatternDetector:
    """
    Detects candlestick patterns in OHLCV price data.

    Supports both list-based and pandas-DataFrame input.

    Usage::

        detector = CandlestickPatternDetector()
        patterns = detector.detect(opens, highs, lows, closes)
        for p in patterns:
            print(p.name, p.pattern_type, p.confidence)
    """

    def detect(
        self,
        opens: List[float],
        highs: List[float],
        lows: List[float],
        closes: List[float],
    ) -> List[CandlestickPattern]:
        """
        Detect all candlestick patterns in the given OHLC lists.

        Args:
            opens: List of open prices.
            highs: List of high prices.
            lows: List of low prices.
            closes: List of close prices.

        Returns:
            List of detected CandlestickPattern objects.
        """
        n = len(closes)
        if n == 0:
            return []

        patterns: List[CandlestickPattern] = []

        for i in range(n):
            for detector in _SINGLE_DETECTORS:
                p = detector(opens, highs, lows, closes, i)
                if p:
                    patterns.append(p)
                    break  # One pattern per candle for single-candle set

            if i >= 1:
                for detector in _TWO_CANDLE_DETECTORS:
                    p = detector(opens, closes, i)
                    if p:
                        patterns.append(p)
                        break

            if i >= 2:
                for detector in _THREE_CANDLE_DETECTORS:
                    p = detector(opens, closes, i)
                    if p:
                        patterns.append(p)
                        break

        return patterns

    def detect_from_dataframe(self, df: "pd.DataFrame") -> List[CandlestickPattern]:
        """
        Detect patterns from a pandas DataFrame.

        The DataFrame must have columns: open, high, low, close (case-insensitive).

        Args:
            df: OHLC DataFrame.

        Returns:
            List of detected CandlestickPattern objects.
        """
        cols = {c.lower(): c for c in df.columns}
        opens = df[cols["open"]].tolist()
        highs = df[cols["high"]].tolist()
        lows = df[cols["low"]].tolist()
        closes = df[cols["close"]].tolist()
        return self.detect(opens, highs, lows, closes)

    def get_latest_signals(
        self,
        opens: List[float],
        highs: List[float],
        lows: List[float],
        closes: List[float],
        lookback: int = 5,
    ) -> List[CandlestickPattern]:
        """
        Return only patterns that end within the last *lookback* candles.

        Args:
            opens: Open prices.
            highs: High prices.
            lows: Low prices.
            closes: Close prices.
            lookback: Number of recent bars to include.

        Returns:
            Filtered list of recent CandlestickPattern objects.
        """
        all_patterns = self.detect(opens, highs, lows, closes)
        cutoff = len(closes) - lookback
        return [p for p in all_patterns if p.end_index >= cutoff]

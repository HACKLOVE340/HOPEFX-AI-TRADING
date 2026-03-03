"""
Chart Pattern Detection

Identifies classic chart patterns in price series:
- Head and Shoulders (and Inverse)
- Double Top / Double Bottom
- Triple Top / Triple Bottom
- Ascending / Descending / Symmetrical Triangles
- Bullish / Bearish Wedge
- Rising / Falling Channel
"""

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

try:
    import pandas as pd  # type: ignore[import]
    HAS_PANDAS = True
except ImportError:
    pd = None  # type: ignore[assignment]
    HAS_PANDAS = False

logger = logging.getLogger(__name__)


@dataclass
class ChartPattern:
    """Detected chart pattern."""

    name: str
    pattern_type: str        # 'bullish', 'bearish', 'neutral'
    start_index: int
    end_index: int
    confidence: float        # 0.0 – 1.0
    target_price: Optional[float] = None
    stop_price: Optional[float] = None
    key_levels: List[float] = field(default_factory=list)
    description: str = ""

    def to_dict(self) -> Dict:
        return {
            "name": self.name,
            "pattern_type": self.pattern_type,
            "start_index": self.start_index,
            "end_index": self.end_index,
            "confidence": self.confidence,
            "target_price": self.target_price,
            "stop_price": self.stop_price,
            "key_levels": self.key_levels,
            "description": self.description,
        }


# ---------------------------------------------------------------------------
# Utility helpers
# ---------------------------------------------------------------------------

def _find_peaks(prices: List[float], window: int = 3) -> List[int]:
    """Return indices of local highs within *window* on each side."""
    peaks = []
    for i in range(window, len(prices) - window):
        price_window = prices[i - window: i + window + 1]
        if prices[i] == max(price_window):
            peaks.append(i)
    return peaks


def _find_troughs(prices: List[float], window: int = 3) -> List[int]:
    """Return indices of local lows within *window* on each side."""
    troughs = []
    for i in range(window, len(prices) - window):
        price_window = prices[i - window: i + window + 1]
        if prices[i] == min(price_window):
            troughs.append(i)
    return troughs


def _linear_slope(xs: List[float], ys: List[float]) -> Tuple[float, float]:
    """Return (slope, intercept) via least-squares."""
    n = len(xs)
    if n < 2:
        return 0.0, ys[0] if ys else 0.0
    sx = sum(xs)
    sy = sum(ys)
    sxy = sum(x * y for x, y in zip(xs, ys))
    sxx = sum(x * x for x in xs)
    denom = n * sxx - sx * sx
    if denom == 0:
        return 0.0, sy / n
    slope = (n * sxy - sx * sy) / denom
    intercept = (sy - slope * sx) / n
    return slope, intercept


def _price_symmetry(a: float, b: float, tolerance: float = 0.02) -> bool:
    """True if *a* and *b* are within *tolerance* fraction of each other."""
    if a == 0:
        return b == 0
    return abs(a - b) / abs(a) <= tolerance


# ---------------------------------------------------------------------------
# Head and Shoulders
# ---------------------------------------------------------------------------

def _detect_head_and_shoulders(
    prices: List[float],
    peaks: List[int],
    troughs: List[int],
) -> Optional[ChartPattern]:
    """Detect Head and Shoulders (bearish) from peak indices."""
    if len(peaks) < 3 or len(troughs) < 2:
        return None

    # Take the three most prominent peaks
    for k in range(len(peaks) - 2):
        left_idx = peaks[k]
        head_idx = peaks[k + 1]
        right_idx = peaks[k + 2]

        left_h = prices[left_idx]
        head_h = prices[head_idx]
        right_h = prices[right_idx]

        shoulders_similar = _price_symmetry(left_h, right_h, tolerance=0.03)
        head_higher = head_h > left_h and head_h > right_h

        if not (shoulders_similar and head_higher):
            continue

        # Neckline from the troughs between peaks
        between = [t for t in troughs if left_idx < t < right_idx]
        if len(between) < 2:
            continue

        neck1_idx = between[0]
        neck2_idx = between[-1]
        neckline = (prices[neck1_idx] + prices[neck2_idx]) / 2
        pattern_height = head_h - neckline
        target = neckline - pattern_height

        return ChartPattern(
            name="Head and Shoulders",
            pattern_type="bearish",
            start_index=left_idx,
            end_index=right_idx,
            confidence=0.75,
            target_price=round(target, 5),
            stop_price=round(head_h * 1.005, 5),
            key_levels=[round(left_h, 5), round(head_h, 5), round(right_h, 5),
                        round(neckline, 5)],
            description="Classic bearish reversal pattern with three peaks",
        )

    return None


def _detect_inverse_head_and_shoulders(
    prices: List[float],
    peaks: List[int],
    troughs: List[int],
) -> Optional[ChartPattern]:
    """Detect Inverse Head and Shoulders (bullish) from trough indices."""
    if len(troughs) < 3 or len(peaks) < 2:
        return None

    for k in range(len(troughs) - 2):
        left_idx = troughs[k]
        head_idx = troughs[k + 1]
        right_idx = troughs[k + 2]

        left_l = prices[left_idx]
        head_l = prices[head_idx]
        right_l = prices[right_idx]

        shoulders_similar = _price_symmetry(left_l, right_l, tolerance=0.03)
        head_lower = head_l < left_l and head_l < right_l

        if not (shoulders_similar and head_lower):
            continue

        between = [p for p in peaks if left_idx < p < right_idx]
        if len(between) < 2:
            continue

        neck1_idx = between[0]
        neck2_idx = between[-1]
        neckline = (prices[neck1_idx] + prices[neck2_idx]) / 2
        pattern_height = neckline - head_l
        target = neckline + pattern_height

        return ChartPattern(
            name="Inverse Head and Shoulders",
            pattern_type="bullish",
            start_index=left_idx,
            end_index=right_idx,
            confidence=0.75,
            target_price=round(target, 5),
            stop_price=round(head_l * 0.995, 5),
            key_levels=[round(left_l, 5), round(head_l, 5), round(right_l, 5),
                        round(neckline, 5)],
            description="Classic bullish reversal pattern with three troughs",
        )

    return None


# ---------------------------------------------------------------------------
# Double / Triple Top & Bottom
# ---------------------------------------------------------------------------

def _detect_double_top(
    prices: List[float],
    peaks: List[int],
) -> Optional[ChartPattern]:
    """Detect Double Top (bearish) from peak indices."""
    if len(peaks) < 2:
        return None

    for k in range(len(peaks) - 1):
        idx1 = peaks[k]
        idx2 = peaks[k + 1]

        if not _price_symmetry(prices[idx1], prices[idx2], tolerance=0.02):
            continue

        trough_prices = prices[idx1: idx2 + 1]
        support = min(trough_prices)
        height = prices[idx1] - support
        target = support - height

        return ChartPattern(
            name="Double Top",
            pattern_type="bearish",
            start_index=idx1,
            end_index=idx2,
            confidence=0.70,
            target_price=round(target, 5),
            stop_price=round(prices[idx1] * 1.005, 5),
            key_levels=[round(prices[idx1], 5), round(prices[idx2], 5),
                        round(support, 5)],
            description="Two similar highs forming a resistance level",
        )

    return None


def _detect_double_bottom(
    prices: List[float],
    troughs: List[int],
) -> Optional[ChartPattern]:
    """Detect Double Bottom (bullish) from trough indices."""
    if len(troughs) < 2:
        return None

    for k in range(len(troughs) - 1):
        idx1 = troughs[k]
        idx2 = troughs[k + 1]

        if not _price_symmetry(prices[idx1], prices[idx2], tolerance=0.02):
            continue

        peak_prices = prices[idx1: idx2 + 1]
        resistance = max(peak_prices)
        height = resistance - prices[idx1]
        target = resistance + height

        return ChartPattern(
            name="Double Bottom",
            pattern_type="bullish",
            start_index=idx1,
            end_index=idx2,
            confidence=0.70,
            target_price=round(target, 5),
            stop_price=round(prices[idx1] * 0.995, 5),
            key_levels=[round(prices[idx1], 5), round(prices[idx2], 5),
                        round(resistance, 5)],
            description="Two similar lows forming a support level",
        )

    return None


# ---------------------------------------------------------------------------
# Triangle patterns
# ---------------------------------------------------------------------------

def _classify_triangle(
    high_slope: float,
    low_slope: float,
    prices: List[float],
    start: int,
    end: int,
) -> Optional[ChartPattern]:
    """Return a triangle ChartPattern based on trendline slopes."""
    flat = 1e-6
    both_converge = high_slope < 0 and low_slope > 0

    if both_converge:
        apex = prices[start] + (prices[end] - prices[start]) / 2
        return ChartPattern(
            name="Symmetrical Triangle",
            pattern_type="neutral",
            start_index=start,
            end_index=end,
            confidence=0.65,
            key_levels=[round(apex, 5)],
            description="Converging trendlines — breakout direction uncertain",
        )

    high_flat = abs(high_slope) < flat
    low_rising = low_slope > flat
    if high_flat and low_rising:
        return ChartPattern(
            name="Ascending Triangle",
            pattern_type="bullish",
            start_index=start,
            end_index=end,
            confidence=0.70,
            description="Flat resistance with rising support — bullish breakout likely",
        )

    low_flat = abs(low_slope) < flat
    high_falling = high_slope < -flat
    if low_flat and high_falling:
        return ChartPattern(
            name="Descending Triangle",
            pattern_type="bearish",
            start_index=start,
            end_index=end,
            confidence=0.70,
            description="Flat support with falling resistance — bearish breakout likely",
        )

    return None


def _detect_triangle(
    prices: List[float],
    peaks: List[int],
    troughs: List[int],
) -> Optional[ChartPattern]:
    """Detect triangle patterns using peak and trough trendlines."""
    if len(peaks) < 2 or len(troughs) < 2:
        return None

    peak_xs = [float(p) for p in peaks[-3:]]
    peak_ys = [prices[p] for p in peaks[-3:]]
    trough_xs = [float(t) for t in troughs[-3:]]
    trough_ys = [prices[t] for t in troughs[-3:]]

    high_slope, _ = _linear_slope(peak_xs, peak_ys)
    low_slope, _ = _linear_slope(trough_xs, trough_ys)

    start = min(peaks[0], troughs[0])
    end = max(peaks[-1], troughs[-1])

    return _classify_triangle(high_slope, low_slope, prices, start, end)


# ---------------------------------------------------------------------------
# Wedge patterns
# ---------------------------------------------------------------------------

def _detect_wedge(
    prices: List[float],
    peaks: List[int],
    troughs: List[int],
) -> Optional[ChartPattern]:
    """Detect Rising (bearish) or Falling (bullish) Wedge."""
    if len(peaks) < 2 or len(troughs) < 2:
        return None

    peak_xs = [float(p) for p in peaks[-3:]]
    peak_ys = [prices[p] for p in peaks[-3:]]
    trough_xs = [float(t) for t in troughs[-3:]]
    trough_ys = [prices[t] for t in troughs[-3:]]

    high_slope, _ = _linear_slope(peak_xs, peak_ys)
    low_slope, _ = _linear_slope(trough_xs, trough_ys)

    start = min(peaks[0], troughs[0])
    end = max(peaks[-1], troughs[-1])

    # Rising wedge: both trendlines slope up but converge
    both_rising = high_slope > 0 and low_slope > 0
    rising_converge = low_slope > high_slope > 0

    if both_rising and rising_converge:
        return ChartPattern(
            name="Rising Wedge",
            pattern_type="bearish",
            start_index=start,
            end_index=end,
            confidence=0.65,
            description="Both trendlines rising but converging — bearish reversal signal",
        )

    # Falling wedge: both trendlines slope down but converge
    both_falling = high_slope < 0 and low_slope < 0
    falling_converge = high_slope < low_slope < 0

    if both_falling and falling_converge:
        return ChartPattern(
            name="Falling Wedge",
            pattern_type="bullish",
            start_index=start,
            end_index=end,
            confidence=0.65,
            description="Both trendlines falling but converging — bullish reversal signal",
        )

    return None


# ---------------------------------------------------------------------------
# Channel patterns
# ---------------------------------------------------------------------------

def _compute_channel_params(
    prices: List[float],
    peaks: List[int],
    troughs: List[int],
) -> Tuple[float, float, float, float]:
    """Return (high_slope, high_intercept, low_slope, low_intercept)."""
    peak_xs = [float(p) for p in peaks[-4:]]
    peak_ys = [prices[p] for p in peaks[-4:]]
    trough_xs = [float(t) for t in troughs[-4:]]
    trough_ys = [prices[t] for t in troughs[-4:]]

    high_slope, high_intercept = _linear_slope(peak_xs, peak_ys)
    low_slope, low_intercept = _linear_slope(trough_xs, trough_ys)
    return high_slope, high_intercept, low_slope, low_intercept


def _detect_channel(
    prices: List[float],
    peaks: List[int],
    troughs: List[int],
) -> Optional[ChartPattern]:
    """Detect Rising or Falling Channel (parallel trendlines)."""
    if len(peaks) < 2 or len(troughs) < 2:
        return None

    high_slope, _, low_slope, _ = _compute_channel_params(prices, peaks, troughs)

    slopes_parallel = abs(high_slope - low_slope) < abs(high_slope) * 0.3

    if not slopes_parallel:
        return None

    start = min(peaks[0], troughs[0])
    end = max(peaks[-1], troughs[-1])

    if high_slope > 0:
        return ChartPattern(
            name="Rising Channel",
            pattern_type="bullish",
            start_index=start,
            end_index=end,
            confidence=0.60,
            description="Parallel rising trendlines — trend continuation upward",
        )

    if high_slope < 0:
        return ChartPattern(
            name="Falling Channel",
            pattern_type="bearish",
            start_index=start,
            end_index=end,
            confidence=0.60,
            description="Parallel falling trendlines — trend continuation downward",
        )

    return None


# ---------------------------------------------------------------------------
# Detector class
# ---------------------------------------------------------------------------

class ChartPatternDetector:
    """
    Detects chart patterns in a price series.

    Usage::

        detector = ChartPatternDetector()
        patterns = detector.detect(closes)
        for p in patterns:
            print(p.name, p.pattern_type, p.confidence)
    """

    def __init__(self, window: int = 5):
        """
        Initialise detector.

        Args:
            window: Half-window used when finding local peaks/troughs.
        """
        self._window = window

    def detect(self, closes: List[float]) -> List[ChartPattern]:
        """
        Detect chart patterns in the close price series.

        Args:
            closes: List of closing prices.

        Returns:
            List of detected ChartPattern objects.
        """
        if len(closes) < self._window * 4:
            return []

        peaks = _find_peaks(closes, self._window)
        troughs = _find_troughs(closes, self._window)

        candidates: List[Optional[ChartPattern]] = [
            _detect_head_and_shoulders(closes, peaks, troughs),
            _detect_inverse_head_and_shoulders(closes, peaks, troughs),
            _detect_double_top(closes, peaks),
            _detect_double_bottom(closes, troughs),
            _detect_triangle(closes, peaks, troughs),
            _detect_wedge(closes, peaks, troughs),
            _detect_channel(closes, peaks, troughs),
        ]

        return [p for p in candidates if p is not None]

    def detect_from_dataframe(self, df: "pd.DataFrame") -> List[ChartPattern]:
        """
        Detect patterns from a pandas DataFrame with a 'close' column.

        Args:
            df: DataFrame containing at least a 'close' (case-insensitive) column.

        Returns:
            List of detected ChartPattern objects.
        """
        cols = {c.lower(): c for c in df.columns}
        closes = df[cols["close"]].tolist()
        return self.detect(closes)

    def get_active_patterns(
        self,
        closes: List[float],
        lookback: int = 20,
    ) -> List[ChartPattern]:
        """
        Return patterns whose end_index falls within the last *lookback* bars.

        Args:
            closes: Close price series.
            lookback: Number of recent bars to consider active.

        Returns:
            Filtered list of recent ChartPattern objects.
        """
        patterns = self.detect(closes)
        cutoff = len(closes) - lookback
        return [p for p in patterns if p.end_index >= cutoff]

    def get_summary(self, closes: List[float]) -> Dict:
        """
        Return a summary of detected patterns.

        Args:
            closes: Close price series.

        Returns:
            Dict with lists of bullish, bearish, and neutral patterns.
        """
        patterns = self.detect(closes)
        return {
            "bullish": [p.to_dict() for p in patterns if p.pattern_type == "bullish"],
            "bearish": [p.to_dict() for p in patterns if p.pattern_type == "bearish"],
            "neutral": [p.to_dict() for p in patterns if p.pattern_type == "neutral"],
            "total": len(patterns),
        }

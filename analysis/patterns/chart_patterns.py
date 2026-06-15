# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""Chart Pattern Detection

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
from datetime import datetime, timezone

UTC = timezone.utc

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

    pattern_type: str  # e.g. 'head_and_shoulders', 'double_top', etc.
    direction: str  # 'bullish', 'bearish', 'neutral'
    confidence: float  # 0.0 – 1.0
    start_index: int
    end_index: int
    key_levels: dict = field(default_factory=dict)
    description: str = ""
    # Actionable price levels derived from the pattern geometry. Populated by
    # the reversal detectors so the API can return entry/target/stop directly
    # rather than reporting 0.0 for every pattern.
    entry_price: float = 0.0
    target_price: float = 0.0
    stop_loss: float = 0.0

    def to_dict(self) -> dict:
        return {
            "pattern_type": self.pattern_type,
            "direction": self.direction,
            "confidence": self.confidence,
            "start_index": self.start_index,
            "end_index": self.end_index,
            "key_levels": {k: round(float(v), 5) for k, v in self.key_levels.items()},
            "description": self.description,
            "timestamp": datetime.now(UTC).isoformat(),
        }


# ---------------------------------------------------------------------------
# Utility helpers
# ---------------------------------------------------------------------------


def _find_peaks(prices: list[float], window: int = 3) -> list[int]:
    """Return indices of local highs within *window* on each side."""
    peaks = []
    for i in range(window, len(prices) - window):
        price_window = prices[i - window : i + window + 1]
        if prices[i] == max(price_window):
            peaks.append(i)
    return peaks


def _find_troughs(prices: list[float], window: int = 3) -> list[int]:
    """Return indices of local lows within *window* on each side."""
    troughs = []
    for i in range(window, len(prices) - window):
        price_window = prices[i - window : i + window + 1]
        if prices[i] == min(price_window):
            troughs.append(i)
    return troughs


def _linear_slope(xs: list[float], ys: list[float]) -> tuple[float, float]:
    """Return (slope, intercept) via least-squares."""
    n = len(xs)
    if n < 2:
        return 0.0, ys[0] if ys else 0.0
    sx = sum(xs)
    sy = sum(ys)
    sxy = sum(x * y for x, y in zip(xs, ys, strict=False))
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


def _clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    """Clamp *x* into the [lo, hi] interval."""
    return max(lo, min(hi, x))


def _similarity_score(a: float, b: float, cap: float = 0.10) -> float:
    """Score how close two prices are: 1.0 when equal, 0.0 at *cap* fractional gap.

    Used to turn shoulder/peak symmetry into a continuous confidence input
    instead of a binary pass/fail, so the reported confidence reflects how
    well the pattern actually fits.
    """
    if a == 0:
        return 1.0 if b == 0 else 0.0
    rel = abs(a - b) / abs(a)
    return _clamp(1.0 - rel / cap)


def _prominence_score(height: float, reference: float, cap: float = 0.05) -> float:
    """Score the prominence of a structure (e.g. valley depth) relative to price.

    A deeper valley between two tops (or taller head over shoulders) is a
    stronger, more tradable pattern. Saturates at *cap* (default 5% of price).
    """
    if reference == 0:
        return 0.0
    return _clamp(abs(height) / reference / cap)


# ---------------------------------------------------------------------------
# Head and Shoulders
# ---------------------------------------------------------------------------


def _detect_head_and_shoulders(
    prices: list[float],
    peaks: list[int],
    troughs: list[int],
    symmetry_tolerance: float = 0.03,
) -> list[ChartPattern]:
    """Detect every Head and Shoulders (bearish) occurrence from peak indices.

    Scans all consecutive peak triples (not just the first match) and scores
    each by shoulder symmetry and head prominence, so multiple real patterns
    on the same series are surfaced with meaningful confidence.

    Args:
        symmetry_tolerance: Maximum fractional difference allowed between
                            the two shoulder heights to be considered similar.
    """
    if len(peaks) < 3 or len(troughs) < 2:
        return []

    results: list[ChartPattern] = []
    for k in range(len(peaks) - 2):
        left_idx, head_idx, right_idx = peaks[k], peaks[k + 1], peaks[k + 2]
        left_h, head_h, right_h = prices[left_idx], prices[head_idx], prices[right_idx]

        if not (
            _price_symmetry(left_h, right_h, tolerance=symmetry_tolerance) and head_h > left_h and head_h > right_h
        ):
            continue

        between = [t for t in troughs if left_idx < t < right_idx]
        if len(between) < 2:
            continue

        neckline = (prices[between[0]] + prices[between[-1]]) / 2
        if neckline <= 0 or head_h <= neckline:
            continue
        pattern_height = head_h - neckline
        target = neckline - pattern_height

        # Confidence from shoulder symmetry + head prominence over the shoulders.
        sym = _similarity_score(left_h, right_h)
        prom = _prominence_score(head_h - max(left_h, right_h), neckline)
        confidence = _clamp(0.45 + 0.35 * sym + 0.20 * prom)

        results.append(
            ChartPattern(
                pattern_type="head_and_shoulders",
                direction="bearish",
                start_index=left_idx,
                end_index=right_idx,
                confidence=round(confidence, 4),
                key_levels={
                    "left_shoulder": round(left_h, 5),
                    "head": round(head_h, 5),
                    "right_shoulder": round(right_h, 5),
                    "neckline": round(neckline, 5),
                    "target": round(target, 5),
                },
                description="Bearish reversal: three peaks with a higher central head; breaks down through the neckline",
                entry_price=round(neckline, 5),
                target_price=round(target, 5),
                stop_loss=round(head_h, 5),
            )
        )

    return results


def _detect_inverse_head_and_shoulders(
    prices: list[float],
    peaks: list[int],
    troughs: list[int],
    symmetry_tolerance: float = 0.03,
) -> list[ChartPattern]:
    """Detect every Inverse Head and Shoulders (bullish) occurrence.

    Args:
        symmetry_tolerance: Maximum fractional difference allowed between
                            the two shoulder lows to be considered similar.
    """
    if len(troughs) < 3 or len(peaks) < 2:
        return []

    results: list[ChartPattern] = []
    for k in range(len(troughs) - 2):
        left_idx, head_idx, right_idx = troughs[k], troughs[k + 1], troughs[k + 2]
        left_l, head_l, right_l = prices[left_idx], prices[head_idx], prices[right_idx]

        if not (
            _price_symmetry(left_l, right_l, tolerance=symmetry_tolerance) and head_l < left_l and head_l < right_l
        ):
            continue

        between = [p for p in peaks if left_idx < p < right_idx]
        if len(between) < 2:
            continue

        neckline = (prices[between[0]] + prices[between[-1]]) / 2
        if neckline <= 0 or head_l >= neckline:
            continue
        pattern_height = neckline - head_l
        target = neckline + pattern_height

        sym = _similarity_score(left_l, right_l)
        prom = _prominence_score(min(left_l, right_l) - head_l, neckline)
        confidence = _clamp(0.45 + 0.35 * sym + 0.20 * prom)

        results.append(
            ChartPattern(
                pattern_type="inverse_head_and_shoulders",
                direction="bullish",
                start_index=left_idx,
                end_index=right_idx,
                confidence=round(confidence, 4),
                key_levels={
                    "left_shoulder": round(left_l, 5),
                    "head": round(head_l, 5),
                    "right_shoulder": round(right_l, 5),
                    "neckline": round(neckline, 5),
                    "target": round(target, 5),
                },
                description="Bullish reversal: three troughs with a lower central head; breaks up through the neckline",
                entry_price=round(neckline, 5),
                target_price=round(target, 5),
                stop_loss=round(head_l, 5),
            )
        )

    return results


# ---------------------------------------------------------------------------
# Double / Triple Top & Bottom
# ---------------------------------------------------------------------------


def _detect_double_top(
    prices: list[float],
    peaks: list[int],
    symmetry_tolerance: float = 0.02,
    min_separation: int = 5,
) -> list[ChartPattern]:
    """Detect every Double Top (bearish) occurrence from peak indices.

    Requires the two highs to be similar, adequately separated, and to have a
    genuine valley between them (confidence scales with valley depth) so that
    adjacent noise is not reported as a pattern.

    Args:
        symmetry_tolerance: Maximum fractional difference between the two highs.
        min_separation: Minimum number of bars between the two highs.
    """
    if len(peaks) < 2:
        return []

    results: list[ChartPattern] = []
    for k in range(len(peaks) - 1):
        idx1, idx2 = peaks[k], peaks[k + 1]
        if idx2 - idx1 < min_separation:
            continue
        if not _price_symmetry(prices[idx1], prices[idx2], tolerance=symmetry_tolerance):
            continue

        support = min(prices[idx1 : idx2 + 1])
        top = max(prices[idx1], prices[idx2])
        height = top - support
        # Reject a "double top" with no meaningful trough between the highs.
        if height <= 0 or _prominence_score(height, top, cap=0.01) <= 0.0:
            continue
        target = support - height

        sym = _similarity_score(prices[idx1], prices[idx2])
        depth = _prominence_score(height, top)
        confidence = _clamp(0.45 + 0.30 * sym + 0.25 * depth)

        results.append(
            ChartPattern(
                pattern_type="double_top",
                direction="bearish",
                start_index=idx1,
                end_index=idx2,
                confidence=round(confidence, 4),
                key_levels={
                    "top1": round(prices[idx1], 5),
                    "top2": round(prices[idx2], 5),
                    "support": round(support, 5),
                    "target": round(target, 5),
                },
                description="Bearish reversal: two similar highs and a valley; breaks down through the support",
                entry_price=round(support, 5),
                target_price=round(target, 5),
                stop_loss=round(top, 5),
            )
        )

    return results


def _detect_double_bottom(
    prices: list[float],
    troughs: list[int],
    symmetry_tolerance: float = 0.02,
    min_separation: int = 5,
) -> list[ChartPattern]:
    """Detect every Double Bottom (bullish) occurrence from trough indices.

    Args:
        symmetry_tolerance: Maximum fractional difference between the two lows.
        min_separation: Minimum number of bars between the two lows.
    """
    if len(troughs) < 2:
        return []

    results: list[ChartPattern] = []
    for k in range(len(troughs) - 1):
        idx1, idx2 = troughs[k], troughs[k + 1]
        if idx2 - idx1 < min_separation:
            continue
        if not _price_symmetry(prices[idx1], prices[idx2], tolerance=symmetry_tolerance):
            continue

        resistance = max(prices[idx1 : idx2 + 1])
        bottom = min(prices[idx1], prices[idx2])
        height = resistance - bottom
        if height <= 0 or _prominence_score(height, resistance, cap=0.01) <= 0.0:
            continue
        target = resistance + height

        sym = _similarity_score(prices[idx1], prices[idx2])
        depth = _prominence_score(height, resistance)
        confidence = _clamp(0.45 + 0.30 * sym + 0.25 * depth)

        results.append(
            ChartPattern(
                pattern_type="double_bottom",
                direction="bullish",
                start_index=idx1,
                end_index=idx2,
                confidence=round(confidence, 4),
                key_levels={
                    "bottom1": round(prices[idx1], 5),
                    "bottom2": round(prices[idx2], 5),
                    "resistance": round(resistance, 5),
                    "target": round(target, 5),
                },
                description="Bullish reversal: two similar lows and a peak; breaks up through the resistance",
                entry_price=round(resistance, 5),
                target_price=round(target, 5),
                stop_loss=round(bottom, 5),
            )
        )

    return results


# ---------------------------------------------------------------------------
# Triangle patterns
# ---------------------------------------------------------------------------


def _classify_triangle(
    high_slope: float,
    low_slope: float,
    prices: list[float],
    start: int,
    end: int,
) -> ChartPattern | None:
    """Return a triangle ChartPattern based on trendline slopes."""
    flat = 1e-6
    both_converge = high_slope < 0 and low_slope > 0

    if both_converge:
        apex = prices[start] + (prices[end] - prices[start]) / 2
        return ChartPattern(
            pattern_type="symmetrical_triangle",
            direction="neutral",
            start_index=start,
            end_index=end,
            confidence=0.65,
            key_levels={"apex": round(apex, 5)},
            description="Converging trendlines — breakout direction uncertain",
        )

    high_flat = abs(high_slope) < flat
    low_rising = low_slope > flat
    if high_flat and low_rising:
        return ChartPattern(
            pattern_type="ascending_triangle",
            direction="bullish",
            start_index=start,
            end_index=end,
            confidence=0.70,
            description="Flat resistance with rising support — bullish breakout likely",
        )

    low_flat = abs(low_slope) < flat
    high_falling = high_slope < -flat
    if low_flat and high_falling:
        return ChartPattern(
            pattern_type="descending_triangle",
            direction="bearish",
            start_index=start,
            end_index=end,
            confidence=0.70,
            description="Flat support with falling resistance — bearish breakout likely",
        )

    return None


def _detect_triangle(
    prices: list[float],
    peaks: list[int],
    troughs: list[int],
) -> ChartPattern | None:
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
    prices: list[float],
    peaks: list[int],
    troughs: list[int],
) -> ChartPattern | None:
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
            pattern_type="rising_wedge",
            direction="bearish",
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
            pattern_type="falling_wedge",
            direction="bullish",
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
    prices: list[float],
    peaks: list[int],
    troughs: list[int],
) -> tuple[float, float, float, float]:
    """Return (high_slope, high_intercept, low_slope, low_intercept)."""
    peak_xs = [float(p) for p in peaks[-4:]]
    peak_ys = [prices[p] for p in peaks[-4:]]
    trough_xs = [float(t) for t in troughs[-4:]]
    trough_ys = [prices[t] for t in troughs[-4:]]

    high_slope, high_intercept = _linear_slope(peak_xs, peak_ys)
    low_slope, low_intercept = _linear_slope(trough_xs, trough_ys)
    return high_slope, high_intercept, low_slope, low_intercept


def _detect_channel(
    prices: list[float],
    peaks: list[int],
    troughs: list[int],
) -> ChartPattern | None:
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
            pattern_type="rising_channel",
            direction="bullish",
            start_index=start,
            end_index=end,
            confidence=0.60,
            description="Parallel rising trendlines — trend continuation upward",
        )

    if high_slope < 0:
        return ChartPattern(
            pattern_type="falling_channel",
            direction="bearish",
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
        patterns = detector.detect_patterns(df)
        for p in patterns:
            logger.info(p.pattern_type, p.direction, p.confidence)
    """

    def __init__(self, config: dict | None = None):
        """
        Initialise detector.

        Args:
            config: Optional dict with keys min_bars, sensitivity, swing_window.
        """
        cfg = config or {}
        self.min_bars: int = int(cfg.get("min_bars", 20))
        self.sensitivity: float = float(cfg.get("sensitivity", 0.02))
        self.swing_window: int = int(cfg.get("swing_window", 3))

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_closes(self, df: "pd.DataFrame") -> list[float] | None:
        """Extract close prices from DataFrame; return None on failure."""
        if not HAS_PANDAS:
            logger.warning("pandas is not available; DataFrame input cannot be processed.")
            return None
        if not isinstance(df, pd.DataFrame) or df.empty:
            return None
        cols = {c.lower(): c for c in df.columns}
        required = {"open", "high", "low", "close"}
        if not required.issubset(cols):
            return None
        return df[cols["close"]].tolist()

    def _peaks_and_troughs(self, closes: list[float]) -> tuple[list[int], list[int]]:
        return _find_peaks(closes, self.swing_window), _find_troughs(closes, self.swing_window)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def detect_patterns(
        self,
        df: "pd.DataFrame",
        min_confidence: float = 0.5,
    ) -> list[ChartPattern]:
        """
        Detect all chart patterns in the DataFrame.

        Args:
            df: OHLCV DataFrame with open, high, low, close columns.
            min_confidence: Minimum confidence threshold for returned patterns.

        Returns:
            List of ChartPattern objects sorted by confidence descending.
        """
        if not HAS_PANDAS:
            logger.warning("pandas is not available; detect_patterns cannot process DataFrame input.")
            return []
        if not isinstance(df, pd.DataFrame) or df.empty:
            return []
        if len(df) < self.min_bars:
            return []
        closes = self._get_closes(df)
        if closes is None:
            return []

        patterns: list[ChartPattern] = []
        patterns.extend(self.detect_head_and_shoulders(df))
        patterns.extend(self.detect_double_tops_bottoms(df))
        patterns.extend(self.detect_triangles(df))
        patterns.extend(self.detect_flags_pennants(df))
        patterns.extend(self.detect_wedges(df))

        patterns = [p for p in patterns if p.confidence >= min_confidence]
        patterns.sort(key=lambda p: p.confidence, reverse=True)
        return self._dedupe(patterns)

    @staticmethod
    def _dedupe(patterns: list[ChartPattern]) -> list[ChartPattern]:
        """Drop lower-confidence detections that overlap a kept one of the same type.

        The scan can flag the same structure from several adjacent peak/trough
        combinations; keeping only the strongest non-overlapping instance per
        type avoids showing the trader duplicate cards for one formation.
        Input is assumed already sorted by confidence descending.
        """
        kept: list[ChartPattern] = []
        for p in patterns:
            overlaps = any(
                p.pattern_type == q.pattern_type and p.start_index <= q.end_index and q.start_index <= p.end_index
                for q in kept
            )
            if not overlaps:
                kept.append(p)
        return kept

    def detect_head_and_shoulders(self, df: "pd.DataFrame") -> list[ChartPattern]:
        """
        Detect Head and Shoulders and Inverse Head and Shoulders patterns.

        Args:
            df: OHLCV DataFrame.

        Returns:
            List of detected ChartPattern objects.
        """
        closes = self._get_closes(df)
        if closes is None or len(closes) < self.min_bars:
            return []
        peaks, troughs = self._peaks_and_troughs(closes)
        results: list[ChartPattern] = []
        results.extend(_detect_head_and_shoulders(closes, peaks, troughs, symmetry_tolerance=self.sensitivity))
        results.extend(_detect_inverse_head_and_shoulders(closes, peaks, troughs, symmetry_tolerance=self.sensitivity))
        return results

    def detect_double_tops_bottoms(self, df: "pd.DataFrame") -> list[ChartPattern]:
        """
        Detect Double Top and Double Bottom patterns.

        Args:
            df: OHLCV DataFrame.

        Returns:
            List of detected ChartPattern objects.
        """
        closes = self._get_closes(df)
        if closes is None or len(closes) < self.min_bars:
            return []
        peaks, troughs = self._peaks_and_troughs(closes)
        results: list[ChartPattern] = []
        results.extend(_detect_double_top(closes, peaks, symmetry_tolerance=self.sensitivity))
        results.extend(_detect_double_bottom(closes, troughs, symmetry_tolerance=self.sensitivity))
        return results

    def detect_triangles(self, df: "pd.DataFrame") -> list[ChartPattern]:
        """
        Detect triangle patterns (ascending, descending, symmetrical).

        Args:
            df: OHLCV DataFrame.

        Returns:
            List of detected ChartPattern objects.
        """
        closes = self._get_closes(df)
        if closes is None or len(closes) < self.min_bars:
            return []
        peaks, troughs = self._peaks_and_troughs(closes)
        results = []
        p = _detect_triangle(closes, peaks, troughs)
        if p:
            results.append(p)
        return results

    def detect_flags_pennants(self, df: "pd.DataFrame") -> list[ChartPattern]:
        """
        Detect bull/bear flag and pennant patterns.

        Algorithm:
          1. Scan for a strong pole: a directional move of ≥ pole_pct in
             ≤ pole_bars consecutive bars.
          2. After the pole, look for a consolidation window of
             consol_bars bars where the price range is ≤ consol_range_pct
             of the pole height.
          3. Classify the consolidation:
             - Flag:    high and low trendlines are roughly parallel
               (|high_slope - low_slope| < slope_tol).
             - Pennant: trendlines converge (high_slope < 0 and low_slope > 0
               for bull pennant; reversed for bear pennant).

        Args:
            df: OHLCV DataFrame with open, high, low, close columns.

        Returns:
            List of detected ChartPattern objects.
        """
        if not HAS_PANDAS:
            logger.warning("pandas not available; detect_flags_pennants skipped.")
            return []
        if not isinstance(df, pd.DataFrame) or df.empty:
            return []

        cols = {c.lower(): c for c in df.columns}
        required = {"open", "high", "low", "close"}
        if not required.issubset(cols):
            return []

        closes = df[cols["close"]].tolist()
        highs = df[cols["high"]].tolist()
        lows = df[cols["low"]].tolist()
        n = len(closes)

        if n < self.min_bars:
            return []

        # Tuning parameters
        pole_bars = max(5, self.swing_window * 2)  # max bars for the pole
        pole_pct = 0.02  # min pole move (2 %)
        consol_bars = max(5, self.swing_window * 2)  # consolidation window
        consol_range_pct = 0.50  # consol range ≤ 50 % of pole
        slope_tol = 0.0002  # parallel-slope tolerance

        results: list[ChartPattern] = []
        seen_ends: set[int] = set()  # deduplicate overlapping patterns

        for pole_start in range(0, n - pole_bars - consol_bars):
            for pole_end in range(pole_start + 2, pole_start + pole_bars + 1):
                if pole_end >= n:
                    break

                pole_move = closes[pole_end] - closes[pole_start]
                pole_pct_move = pole_move / closes[pole_start] if closes[pole_start] != 0 else 0.0

                # Must be a strong directional move
                if abs(pole_pct_move) < pole_pct:
                    continue

                bullish_pole = pole_pct_move > 0

                # Consolidation window immediately after the pole
                c_start = pole_end
                c_end = min(c_start + consol_bars, n - 1)
                if c_end <= c_start + 2:
                    continue

                c_highs = highs[c_start : c_end + 1]
                c_lows = lows[c_start : c_end + 1]
                c_range = max(c_highs) - min(c_lows)
                pole_height = abs(pole_move)

                # Consolidation must be tight relative to the pole
                if pole_height == 0 or c_range > consol_range_pct * pole_height:
                    continue

                # Deduplicate: skip if we already emitted a pattern ending here
                if c_end in seen_ends:
                    continue

                # Fit trendlines through consolidation highs and lows
                xs = list(range(len(c_highs)))
                high_slope, high_intercept = _linear_slope([float(x) for x in xs], c_highs)
                low_slope, low_intercept = _linear_slope([float(x) for x in xs], c_lows)

                # Classify: flag vs pennant
                slope_diff = abs(high_slope - low_slope)
                is_parallel = slope_diff < slope_tol
                is_converging = (bullish_pole and high_slope < 0 and low_slope > 0) or (
                    not bullish_pole and high_slope > 0 and low_slope < 0
                )

                if not (is_parallel or is_converging):
                    continue

                pattern_type = (
                    ("bull_flag" if bullish_pole else "bear_flag")
                    if is_parallel
                    else ("bull_pennant" if bullish_pole else "bear_pennant")
                )
                direction = "bullish" if bullish_pole else "bearish"

                # Breakout target: pole height projected from consolidation end
                entry_price = c_highs[-1] if bullish_pole else c_lows[-1]
                target = entry_price + pole_height if bullish_pole else entry_price - pole_height
                stop_loss = min(c_lows) if bullish_pole else max(c_highs)

                rr = (
                    abs(target - entry_price) / abs(entry_price - stop_loss)
                    if abs(entry_price - stop_loss) > 0
                    else 0.0
                )

                # Confidence: higher for tighter consolidation and stronger pole
                tightness = 1.0 - (c_range / (consol_range_pct * pole_height))
                pole_strength = min(abs(pole_pct_move) / 0.05, 1.0)  # cap at 5 %
                confidence = round(min(0.55 + 0.20 * tightness + 0.10 * pole_strength, 0.85), 3)

                results.append(
                    ChartPattern(
                        pattern_type=pattern_type,
                        direction=direction,
                        confidence=confidence,
                        start_index=pole_start,
                        end_index=c_end,
                        key_levels={
                            "pole_start": round(closes[pole_start], 5),
                            "pole_end": round(closes[pole_end], 5),
                            "consol_high": round(max(c_highs), 5),
                            "consol_low": round(min(c_lows), 5),
                            "entry": round(entry_price, 5),
                            "target": round(target, 5),
                            "stop_loss": round(stop_loss, 5),
                        },
                        description=(
                            f"{'Bull' if bullish_pole else 'Bear'} "
                            f"{'flag' if is_parallel else 'pennant'}: "
                            f"pole {pole_pct_move:+.1%}, "
                            f"R:R {rr:.1f}"
                        ),
                    )
                )
                seen_ends.add(c_end)
                break  # one pattern per pole_start

        # Return highest-confidence patterns, capped to avoid noise
        results.sort(key=lambda p: p.confidence, reverse=True)
        return results[:10]

    def detect_wedges(self, df: "pd.DataFrame") -> list[ChartPattern]:
        """
        Detect rising and falling wedge patterns.

        Args:
            df: OHLCV DataFrame.

        Returns:
            List of detected ChartPattern objects.
        """
        closes = self._get_closes(df)
        if closes is None or len(closes) < self.min_bars:
            return []
        peaks, troughs = self._peaks_and_troughs(closes)
        results = []
        p = _detect_wedge(closes, peaks, troughs)
        if p:
            results.append(p)
        return results

    # ------------------------------------------------------------------
    # Legacy helpers kept for backward compatibility
    # ------------------------------------------------------------------

    def detect(self, closes: list[float]) -> list[ChartPattern]:
        """
        Detect chart patterns in the close price series.

        Args:
            closes: List of closing prices.

        Returns:
            List of detected ChartPattern objects.
        """
        if len(closes) < self.swing_window * 4:
            return []

        peaks = _find_peaks(closes, self.swing_window)
        troughs = _find_troughs(closes, self.swing_window)

        candidates: list[ChartPattern | None] = [
            _detect_head_and_shoulders(closes, peaks, troughs),
            _detect_inverse_head_and_shoulders(closes, peaks, troughs),
            _detect_double_top(closes, peaks),
            _detect_double_bottom(closes, troughs),
            _detect_triangle(closes, peaks, troughs),
            _detect_wedge(closes, peaks, troughs),
            _detect_channel(closes, peaks, troughs),
        ]

        return [p for p in candidates if p is not None]

    def get_summary(self, closes: list[float]) -> dict:
        """
        Return a summary of detected patterns.

        Args:
            closes: Close price series.

        Returns:
            Dict with lists of bullish, bearish, and neutral patterns.
        """
        patterns = self.detect(closes)
        return {
            "bullish": [p.to_dict() for p in patterns if p.direction == "bullish"],
            "bearish": [p.to_dict() for p in patterns if p.direction == "bearish"],
            "neutral": [p.to_dict() for p in patterns if p.direction == "neutral"],
            "total": len(patterns),
        }

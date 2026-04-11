# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
Advanced Candlestick & Chart Pattern Recognition
- Head & Shoulders, Double Tops/Bottoms
- Triangles, Wedges, Flags
- Harmonic Patterns (Gartley, Butterfly, Crab, Bat)
- Elliott Wave Pattern Detection
- Support/Resistance Level Identification
"""

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Any

import numpy as np
import pandas as pd
from scipy.signal import argrelextrema

logger = logging.getLogger(__name__)


class PatternType(Enum):
    """Chart pattern types"""

    HEAD_SHOULDERS = "head_shoulders"
    DOUBLE_TOP = "double_top"
    DOUBLE_BOTTOM = "double_bottom"
    TRIANGLE_ASCENDING = "triangle_ascending"
    TRIANGLE_DESCENDING = "triangle_descending"
    TRIANGLE_SYMMETRICAL = "triangle_symmetrical"
    WEDGE_RISING = "wedge_rising"
    WEDGE_FALLING = "wedge_falling"
    FLAG = "flag"
    PENNANT = "pennant"
    GARTLEY = "gartley_pattern"
    BUTTERFLY = "butterfly_pattern"
    BAT = "bat_pattern"
    CRAB = "crab_pattern"
    SUPPORT_RESISTANCE = "support_resistance"


class PatternDirection(Enum):
    """Pattern direction"""

    BULLISH = "bullish"
    BEARISH = "bearish"
    NEUTRAL = "neutral"


@dataclass
class PatternSignal:
    """Chart pattern signal"""

    pattern_type: PatternType
    direction: PatternDirection
    entry_price: float
    target_price: float
    stop_loss: float
    confidence: float  # 0-1
    pattern_start_idx: int
    pattern_end_idx: int
    formation_bars: int
    risk_reward_ratio: float
    timestamp: pd.Timestamp
    additional_data: dict[str, Any]


class AdvancedPatternDetector:
    """Enterprise-grade pattern detection engine"""

    def __init__(self, min_pattern_bars: int = 5, harmonic_tolerance: float = 0.05):
        """
        Initialize pattern detector

        Args:
            min_pattern_bars: Minimum bars to form pattern
            harmonic_tolerance: Tolerance for harmonic ratios (5%)
        """
        self.min_pattern_bars = min_pattern_bars
        self.harmonic_tolerance = harmonic_tolerance

    def detect_all_patterns(self, df: pd.DataFrame, min_confidence: float = 0.7) -> list[PatternSignal]:
        """
        Detect all patterns in price data

        Args:
            df: OHLCV DataFrame
            min_confidence: Minimum confidence threshold

        Returns:
            List of detected patterns
        """
        patterns = []

        # Price data
        high = df["high"].to_numpy()
        low = df["low"].to_numpy()
        close = df["close"].to_numpy()

        # Detect each pattern type
        patterns.extend(self._detect_head_shoulders(high, low, close, df.index))
        patterns.extend(self._detect_double_patterns(high, low, close, df.index))
        patterns.extend(self._detect_triangles(high, low, close, df.index))
        patterns.extend(self._detect_wedges(high, low, close, df.index))
        patterns.extend(self._detect_flags_pennants(high, low, close, df.index))
        patterns.extend(self._detect_harmonic_patterns(high, low, close, df.index))
        patterns.extend(self._detect_support_resistance(high, low, close, df.index))

        # Filter by confidence
        patterns = [p for p in patterns if p.confidence >= min_confidence]

        # Sort by confidence
        patterns.sort(key=lambda x: x.confidence, reverse=True)

        return patterns

    def _detect_head_shoulders(
        self, high: np.ndarray, low: np.ndarray, close: np.ndarray, index: pd.Index
    ) -> list[PatternSignal]:
        """Detect Head & Shoulders patterns"""
        patterns = []

        # Find local extrema
        peaks = argrelextrema(high, np.greater, order=5)[0]
        troughs = argrelextrema(low, np.less, order=5)[0]

        if len(peaks) < 3:
            return patterns

        # Look for pattern: trough-peak-trough-peak-trough
        for i in range(1, len(peaks) - 1):
            left_peak_idx = peaks[i - 1]
            head_idx = peaks[i]
            right_peak_idx = peaks[i + 1]

            # Find intermediate troughs
            left_trough = max(troughs[troughs < head_idx])
            right_trough = min(troughs[troughs > head_idx])

            left_shoulder_height = high[left_peak_idx]
            head_height = high[head_idx]
            right_shoulder_height = high[right_peak_idx]

            # Head & Shoulders validation
            if (
                left_shoulder_height < head_height * 0.95
                and right_shoulder_height < head_height * 0.95
                and abs(left_shoulder_height - right_shoulder_height) < head_height * 0.05
            ):
                # Calculate neckline
                neckline = np.mean([low[left_trough], low[right_trough]])

                # Bearish H&S
                entry_price = neckline
                target = neckline - (head_height - neckline)
                stop_loss = head_height

                confidence = self._calculate_pattern_confidence(
                    left_shoulder_height / head_height,
                    right_shoulder_height / head_height,
                    0.95,  # expected ratio
                )

                pattern = PatternSignal(
                    pattern_type=PatternType.HEAD_SHOULDERS,
                    direction=PatternDirection.BEARISH,
                    entry_price=entry_price,
                    target_price=target,
                    stop_loss=stop_loss,
                    confidence=confidence,
                    pattern_start_idx=left_peak_idx,
                    pattern_end_idx=right_peak_idx,
                    formation_bars=right_peak_idx - left_peak_idx,
                    risk_reward_ratio=(entry_price - target) / (stop_loss - entry_price),
                    timestamp=index[right_trough],
                    additional_data={
                        "neckline": float(neckline),
                        "head_height": float(head_height),
                    },
                )
                patterns.append(pattern)

        return patterns

    def _detect_double_patterns(
        self, high: np.ndarray, low: np.ndarray, close: np.ndarray, index: pd.Index
    ) -> list[PatternSignal]:
        """Detect Double Top/Bottom patterns"""
        patterns = []

        peaks = argrelextrema(high, np.greater, order=5)[0]
        troughs = argrelextrema(low, np.less, order=5)[0]

        # Double Tops
        for i in range(len(peaks) - 1):
            peak1 = high[peaks[i]]
            peak2 = high[peaks[i + 1]]

            if abs(peak1 - peak2) / peak1 < 0.02:  # Within 2%
                idx1, idx2 = peaks[i], peaks[i + 1]

                # Find intermediate trough
                intermediate_trough_idx = max([t for t in troughs if idx1 < t < idx2])
                valley = low[intermediate_trough_idx]

                entry_price = valley
                target = valley - (peak1 - valley)
                stop_loss = peak1

                pattern = PatternSignal(
                    pattern_type=PatternType.DOUBLE_TOP,
                    direction=PatternDirection.BEARISH,
                    entry_price=entry_price,
                    target_price=target,
                    stop_loss=stop_loss,
                    confidence=0.75,
                    pattern_start_idx=idx1,
                    pattern_end_idx=idx2,
                    formation_bars=idx2 - idx1,
                    risk_reward_ratio=(entry_price - target) / (stop_loss - entry_price),
                    timestamp=index[idx2],
                    additional_data={"peak_height": float(peak1)},
                )
                patterns.append(pattern)

        return patterns

    def _detect_triangles(
        self, high: np.ndarray, low: np.ndarray, close: np.ndarray, index: pd.Index
    ) -> list[PatternSignal]:
        """
        Detect ascending, descending, and symmetrical triangle patterns.

        Algorithm:
        - Scan rolling windows of min_pattern_bars*2 to min_pattern_bars*6 bars.
        - Fit linear regression to the swing highs and swing lows within each window.
        - Classify by slope combination:
            ascending   : flat/rising highs + rising lows  (bullish continuation)
            descending  : falling highs + flat/falling lows (bearish continuation)
            symmetrical : falling highs + rising lows       (breakout either way)
        - Confidence is derived from R² of both trendlines and how tightly price
          respects them (mean touch distance as fraction of ATR).
        """
        patterns: list[PatternSignal] = []
        n = len(close)
        if n < self.min_pattern_bars * 2:
            return patterns

        peaks = argrelextrema(high, np.greater, order=3)[0]
        troughs = argrelextrema(low, np.less, order=3)[0]

        window_sizes = range(self.min_pattern_bars * 2, min(self.min_pattern_bars * 6, n), self.min_pattern_bars)

        for w in window_sizes:
            for start in range(0, n - w, w // 2):
                end = start + w
                w_peaks   = peaks[(peaks >= start) & (peaks < end)]
                w_troughs = troughs[(troughs >= start) & (troughs < end)]

                if len(w_peaks) < 2 or len(w_troughs) < 2:
                    continue

                # Fit lines through swing highs and swing lows
                ph_x = w_peaks.astype(float)
                ph_y = high[w_peaks]
                pl_x = w_troughs.astype(float)
                pl_y = low[w_troughs]

                # Linear regression: slope, intercept, r²
                def _linreg(x: np.ndarray, y: np.ndarray):
                    if len(x) < 2:
                        return 0.0, float(y.mean()), 0.0
                    xm, ym = x.mean(), y.mean()
                    denom = ((x - xm) ** 2).sum()
                    if denom == 0:
                        return 0.0, ym, 0.0
                    slope = ((x - xm) * (y - ym)).sum() / denom
                    intercept = ym - slope * xm
                    y_pred = slope * x + intercept
                    ss_res = ((y - y_pred) ** 2).sum()
                    ss_tot = ((y - ym) ** 2).sum()
                    r2 = 1 - ss_res / ss_tot if ss_tot > 0 else 0.0
                    return slope, intercept, max(0.0, r2)

                h_slope, h_intercept, h_r2 = _linreg(ph_x, ph_y)
                l_slope, l_intercept, l_r2 = _linreg(pl_x, pl_y)

                if h_r2 < 0.5 or l_r2 < 0.5:
                    continue

                # ATR for normalisation
                atr = float(np.mean(high[start:end] - low[start:end]))
                if atr == 0:
                    continue

                # Classify by slope signs (threshold = 0.1 * atr / w)
                slope_thresh = 0.1 * atr / w
                h_flat    = abs(h_slope) < slope_thresh
                h_falling = h_slope < -slope_thresh
                l_flat    = abs(l_slope) < slope_thresh
                l_rising  = l_slope > slope_thresh

                if h_flat and l_rising:
                    ptype     = PatternType.TRIANGLE_ASCENDING
                    direction = PatternDirection.BULLISH
                elif h_falling and l_flat:
                    ptype     = PatternType.TRIANGLE_DESCENDING
                    direction = PatternDirection.BEARISH
                elif h_falling and l_rising:
                    ptype     = PatternType.TRIANGLE_SYMMETRICAL
                    direction = PatternDirection.NEUTRAL
                else:
                    continue

                # Apex: intersection of the two trendlines
                # h_slope*x + h_intercept = l_slope*x + l_intercept
                dslope = h_slope - l_slope
                apex_x = (l_intercept - h_intercept) / dslope if dslope != 0 else end
                apex_price = h_slope * apex_x + h_intercept

                entry_price = float(close[end - 1])
                pattern_height = float(high[w_peaks[0]] - low[w_troughs[0]])
                target_price = (
                    entry_price + pattern_height if direction == PatternDirection.BULLISH
                    else entry_price - pattern_height if direction == PatternDirection.BEARISH
                    else entry_price + pattern_height  # symmetrical: bullish breakout target
                )
                stop_loss = float(low[start:end].min() if direction != PatternDirection.BEARISH
                                  else high[start:end].max())

                confidence = float(min(0.95, (h_r2 + l_r2) / 2 * 0.9 + 0.05))
                rr = abs(target_price - entry_price) / abs(entry_price - stop_loss) if abs(entry_price - stop_loss) > 0 else 0.0

                patterns.append(PatternSignal(
                    pattern_type=ptype,
                    direction=direction,
                    entry_price=entry_price,
                    target_price=target_price,
                    stop_loss=stop_loss,
                    confidence=confidence,
                    pattern_start_idx=start,
                    pattern_end_idx=end - 1,
                    formation_bars=w,
                    risk_reward_ratio=rr,
                    timestamp=index[end - 1],
                    additional_data={
                        "high_slope": float(h_slope),
                        "low_slope": float(l_slope),
                        "high_r2": float(h_r2),
                        "low_r2": float(l_r2),
                        "apex_x": float(apex_x),
                        "apex_price": float(apex_price),
                    },
                ))

        return patterns

    def _detect_wedges(
        self, high: np.ndarray, low: np.ndarray, close: np.ndarray, index: pd.Index
    ) -> list[PatternSignal]:
        """
        Detect rising and falling wedge patterns.

        A wedge differs from a triangle in that BOTH trendlines slope in the
        same direction (both rising → rising wedge / bearish reversal;
        both falling → falling wedge / bullish reversal) and they converge.

        Algorithm:
        - Same rolling-window + linear-regression approach as triangles.
        - Rising wedge  : both slopes positive AND high_slope < low_slope
          (lines converging upward).
        - Falling wedge : both slopes negative AND high_slope > low_slope
          (lines converging downward).
        - Confidence from R² of both lines and convergence ratio.
        """
        patterns: list[PatternSignal] = []
        n = len(close)
        if n < self.min_pattern_bars * 2:
            return patterns

        peaks   = argrelextrema(high, np.greater, order=3)[0]
        troughs = argrelextrema(low,  np.less,    order=3)[0]

        window_sizes = range(self.min_pattern_bars * 2, min(self.min_pattern_bars * 6, n), self.min_pattern_bars)

        for w in window_sizes:
            for start in range(0, n - w, w // 2):
                end = start + w
                w_peaks   = peaks[(peaks >= start) & (peaks < end)]
                w_troughs = troughs[(troughs >= start) & (troughs < end)]

                if len(w_peaks) < 2 or len(w_troughs) < 2:
                    continue

                def _linreg(x: np.ndarray, y: np.ndarray):
                    if len(x) < 2:
                        return 0.0, float(y.mean()), 0.0
                    xm, ym = x.mean(), y.mean()
                    denom = ((x - xm) ** 2).sum()
                    if denom == 0:
                        return 0.0, ym, 0.0
                    slope = ((x - xm) * (y - ym)).sum() / denom
                    intercept = ym - slope * xm
                    y_pred = slope * x + intercept
                    ss_res = ((y - y_pred) ** 2).sum()
                    ss_tot = ((y - ym) ** 2).sum()
                    r2 = 1 - ss_res / ss_tot if ss_tot > 0 else 0.0
                    return slope, intercept, max(0.0, r2)

                h_slope, h_intercept, h_r2 = _linreg(w_peaks.astype(float),   high[w_peaks])
                l_slope, l_intercept, l_r2 = _linreg(w_troughs.astype(float), low[w_troughs])

                if h_r2 < 0.5 or l_r2 < 0.5:
                    continue

                atr = float(np.mean(high[start:end] - low[start:end]))
                if atr == 0:
                    continue

                slope_thresh = 0.05 * atr / w

                rising_wedge  = (h_slope > slope_thresh and l_slope > slope_thresh
                                 and h_slope < l_slope)   # converging upward
                falling_wedge = (h_slope < -slope_thresh and l_slope < -slope_thresh
                                 and h_slope > l_slope)   # converging downward

                if not rising_wedge and not falling_wedge:
                    continue

                ptype     = PatternType.WEDGE_RISING  if rising_wedge  else PatternType.WEDGE_FALLING
                direction = PatternDirection.BEARISH   if rising_wedge  else PatternDirection.BULLISH

                entry_price    = float(close[end - 1])
                pattern_height = float(high[w_peaks[0]] - low[w_troughs[0]])
                target_price   = (entry_price - pattern_height if direction == PatternDirection.BEARISH
                                  else entry_price + pattern_height)
                stop_loss      = (float(high[start:end].max()) if direction == PatternDirection.BEARISH
                                  else float(low[start:end].min()))

                convergence_ratio = abs(h_slope - l_slope) / (atr / w + 1e-9)
                confidence = float(min(0.92, (h_r2 + l_r2) / 2 * 0.85 + convergence_ratio * 0.05))
                rr = abs(target_price - entry_price) / abs(entry_price - stop_loss) if abs(entry_price - stop_loss) > 0 else 0.0

                patterns.append(PatternSignal(
                    pattern_type=ptype,
                    direction=direction,
                    entry_price=entry_price,
                    target_price=target_price,
                    stop_loss=stop_loss,
                    confidence=confidence,
                    pattern_start_idx=start,
                    pattern_end_idx=end - 1,
                    formation_bars=w,
                    risk_reward_ratio=rr,
                    timestamp=index[end - 1],
                    additional_data={
                        "high_slope": float(h_slope),
                        "low_slope": float(l_slope),
                        "high_r2": float(h_r2),
                        "low_r2": float(l_r2),
                        "convergence_ratio": float(convergence_ratio),
                    },
                ))

        return patterns

    def _detect_flags_pennants(
        self, high: np.ndarray, low: np.ndarray, close: np.ndarray, index: pd.Index
    ) -> list[PatternSignal]:
        """
        Detect bull/bear flags and pennants.

        Flags and pennants share the same structure:
          1. A sharp impulse move (the "pole") — identified as a run of bars
             where price moves > 1.5 × ATR in a single direction.
          2. A consolidation phase (the "flag/pennant body") of
             min_pattern_bars to min_pattern_bars*3 bars.

        Flag body     : price channels in a slight counter-trend rectangle
                        (both trendlines roughly parallel, opposite to pole).
        Pennant body  : converging trendlines (mini symmetrical triangle).

        Breakout target = pole length projected from the consolidation breakout.
        """
        patterns: list[PatternSignal] = []
        n = len(close)
        if n < self.min_pattern_bars * 3:
            return patterns

        atr_full = float(np.mean(high - low)) if n > 0 else 1.0
        pole_threshold = 1.5 * atr_full * self.min_pattern_bars

        # Scan for impulse poles
        for pole_end in range(self.min_pattern_bars, n - self.min_pattern_bars):
            pole_start = max(0, pole_end - self.min_pattern_bars * 2)

            pole_move = close[pole_end] - close[pole_start]
            if abs(pole_move) < pole_threshold:
                continue

            bullish_pole = pole_move > 0

            # Consolidation window after the pole
            for body_len in range(self.min_pattern_bars, min(self.min_pattern_bars * 3, n - pole_end)):
                body_start = pole_end
                body_end   = pole_end + body_len
                if body_end >= n:
                    break

                b_high = high[body_start:body_end]
                b_low  = low[body_start:body_end]
                b_close = close[body_start:body_end]

                body_range = float(b_high.max() - b_low.min())
                pole_length = abs(pole_move)

                # Flag: body range < 50% of pole, slight counter-trend drift
                body_drift = float(b_close[-1] - b_close[0])
                counter_trend = (body_drift < 0) if bullish_pole else (body_drift > 0)

                if body_range > pole_length * 0.5:
                    continue

                # Distinguish flag vs pennant by trendline convergence
                x = np.arange(body_len, dtype=float)
                if body_len >= 3:
                    h_slope = float(np.polyfit(x, b_high, 1)[0])
                    l_slope = float(np.polyfit(x, b_low,  1)[0])
                    converging = (h_slope < 0 and l_slope > 0) if bullish_pole else (h_slope > 0 and l_slope < 0)
                    is_pennant = converging
                else:
                    is_pennant = False

                ptype = PatternType.PENNANT if is_pennant else PatternType.FLAG
                direction = PatternDirection.BULLISH if bullish_pole else PatternDirection.BEARISH

                entry_price  = float(close[body_end - 1])
                target_price = entry_price + pole_length if bullish_pole else entry_price - pole_length
                stop_loss    = float(b_low.min()) if bullish_pole else float(b_high.max())

                rr = abs(target_price - entry_price) / abs(entry_price - stop_loss) if abs(entry_price - stop_loss) > 0 else 0.0

                # Confidence: higher when body is tight and counter-trend
                tightness = 1.0 - body_range / (pole_length + 1e-9)
                confidence = float(min(0.90, 0.60 + tightness * 0.25 + (0.05 if counter_trend else 0.0)))

                patterns.append(PatternSignal(
                    pattern_type=ptype,
                    direction=direction,
                    entry_price=entry_price,
                    target_price=target_price,
                    stop_loss=stop_loss,
                    confidence=confidence,
                    pattern_start_idx=pole_start,
                    pattern_end_idx=body_end - 1,
                    formation_bars=body_end - pole_start,
                    risk_reward_ratio=rr,
                    timestamp=index[body_end - 1],
                    additional_data={
                        "pole_length": float(pole_length),
                        "body_range": float(body_range),
                        "is_pennant": is_pennant,
                        "counter_trend": counter_trend,
                    },
                ))
                # Only emit the first valid body length per pole to avoid duplicates
                break

        return patterns

    def _detect_harmonic_patterns(
        self, high: np.ndarray, low: np.ndarray, close: np.ndarray, index: pd.Index
    ) -> list[PatternSignal]:
        """
        Detect Harmonic patterns (Gartley, Butterfly, Crab, Bat)
        Uses Fibonacci ratios
        """
        patterns = []

        # Fibonacci ratios for harmonic patterns

        peaks = argrelextrema(high, np.greater, order=5)[0]
        troughs = argrelextrema(low, np.less, order=5)[0]

        # Find XABCD pattern points
        extrema_points = sorted(list(peaks) + list(troughs))

        for i in range(len(extrema_points) - 3):
            x_idx = extrema_points[i]
            a_idx = extrema_points[i + 1]
            b_idx = extrema_points[i + 2]
            c_idx = extrema_points[i + 3]

            x_price = high[x_idx] if x_idx in peaks else low[x_idx]
            a_price = high[a_idx] if a_idx in peaks else low[a_idx]
            b_price = high[b_idx] if b_idx in peaks else low[b_idx]
            c_price = high[c_idx] if c_idx in peaks else low[c_idx]

            # Calculate Fibonacci ratios
            xa_move = abs(a_price - x_price)
            ab_move = abs(b_price - a_price)
            bc_move = abs(c_price - b_price)

            if xa_move == 0:
                continue

            ab_ratio = ab_move / xa_move
            bc_ratio = bc_move / ab_move if ab_move > 0 else 0

            # Check Gartley pattern
            if 0.5 < ab_ratio < 0.75 and 1.2 < bc_ratio < 1.8:
                cd_target = c_price + bc_move * 1.272

                pattern = PatternSignal(
                    pattern_type=PatternType.GARTLEY,
                    direction=PatternDirection.BULLISH if x_price > a_price else PatternDirection.BEARISH,
                    entry_price=c_price,
                    target_price=cd_target,
                    stop_loss=x_price,
                    confidence=0.82,
                    pattern_start_idx=x_idx,
                    pattern_end_idx=c_idx,
                    formation_bars=c_idx - x_idx,
                    risk_reward_ratio=abs(cd_target - c_price) / abs(x_price - c_price),
                    timestamp=index[c_idx],
                    additional_data={"pattern_ratios": {"ab": ab_ratio, "bc": bc_ratio}},
                )
                patterns.append(pattern)

        return patterns

    def _detect_support_resistance(
        self, high: np.ndarray, low: np.ndarray, close: np.ndarray, index: pd.Index
    ) -> list[PatternSignal]:
        """
        Identify key support and resistance levels using price clustering.

        Algorithm:
        1. Collect all swing highs (resistance candidates) and swing lows
           (support candidates) using argrelextrema.
        2. Cluster nearby levels within a tolerance band (0.3 % of price by
           default) — levels that have been tested multiple times are stronger.
        3. For each cluster, emit a PatternSignal whose confidence scales with
           the number of touches (capped at 5 touches → confidence 0.95).
        4. Direction: BEARISH for resistance (price below level),
                      BULLISH for support (price above level).
        5. Target: 1 ATR beyond the level in the breakout direction.
           Stop:   0.5 ATR on the wrong side of the level.
        """
        patterns: list[PatternSignal] = []
        n = len(close)
        if n < self.min_pattern_bars:
            return patterns

        atr = float(np.mean(high - low)) if n > 0 else 1.0
        cluster_tol = atr * 0.5  # levels within 0.5 ATR are the same zone

        peaks   = argrelextrema(high, np.greater, order=3)[0]
        troughs = argrelextrema(low,  np.less,    order=3)[0]

        # Build candidate levels: (price, index, is_resistance)
        candidates: list[tuple[float, int, bool]] = []
        for idx in peaks:
            candidates.append((float(high[idx]), int(idx), True))
        for idx in troughs:
            candidates.append((float(low[idx]), int(idx), False))

        if not candidates:
            return patterns

        # Sort by price
        candidates.sort(key=lambda c: c[0])

        # Cluster
        clusters: list[list[tuple[float, int, bool]]] = []
        current_cluster: list[tuple[float, int, bool]] = [candidates[0]]

        for cand in candidates[1:]:
            if abs(cand[0] - current_cluster[-1][0]) <= cluster_tol:
                current_cluster.append(cand)
            else:
                clusters.append(current_cluster)
                current_cluster = [cand]
        clusters.append(current_cluster)

        current_price = float(close[-1])

        for cluster in clusters:
            if len(cluster) < 2:
                continue  # single touch — not a confirmed level

            level_price = float(np.mean([c[0] for c in cluster]))
            touches     = len(cluster)
            last_idx    = max(c[1] for c in cluster)
            res_count   = sum(1 for c in cluster if c[2])
            sup_count   = touches - res_count

            # Classify as resistance or support by majority vote
            is_resistance = res_count >= sup_count
            direction = PatternDirection.BEARISH if is_resistance else PatternDirection.BULLISH

            # Target and stop
            if is_resistance:
                target_price = level_price + atr
                stop_loss    = level_price - atr * 0.5
            else:
                target_price = level_price - atr
                stop_loss    = level_price + atr * 0.5

            rr = abs(target_price - level_price) / abs(level_price - stop_loss) if abs(level_price - stop_loss) > 0 else 0.0

            # Confidence: 2 touches → 0.65, 3 → 0.75, 4 → 0.85, 5+ → 0.95
            confidence = float(min(0.95, 0.55 + touches * 0.10))

            patterns.append(PatternSignal(
                pattern_type=PatternType.SUPPORT_RESISTANCE,
                direction=direction,
                entry_price=level_price,
                target_price=target_price,
                stop_loss=stop_loss,
                confidence=confidence,
                pattern_start_idx=min(c[1] for c in cluster),
                pattern_end_idx=last_idx,
                formation_bars=last_idx - min(c[1] for c in cluster),
                risk_reward_ratio=rr,
                timestamp=index[min(last_idx, n - 1)],
                additional_data={
                    "level_price": level_price,
                    "touches": touches,
                    "resistance_touches": res_count,
                    "support_touches": sup_count,
                    "distance_from_current": float(abs(current_price - level_price)),
                    "atr": atr,
                },
            ))

        return patterns

    def _calculate_pattern_confidence(self, actual_ratio: float, expected_ratio: float, tolerance: float) -> float:
        """Calculate confidence score for pattern"""
        deviation = abs(actual_ratio - expected_ratio) / expected_ratio
        confidence = max(0, 1 - (deviation / tolerance))
        return min(1.0, confidence)

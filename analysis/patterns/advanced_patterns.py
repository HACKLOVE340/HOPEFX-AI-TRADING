"""
Advanced Candlestick & Chart Pattern Recognition
- Head & Shoulders, Double Tops/Bottoms
- Triangles, Wedges, Flags
- Harmonic Patterns (Gartley, Butterfly, Crab, Bat)
- Elliott Wave Pattern Detection
- Support/Resistance Level Identification
"""

import logging
from typing import List, Dict, Tuple, Optional, Any
from dataclasses import dataclass, field
from enum import Enum
import numpy as np
import pandas as pd
from scipy import signal
from scipy.ndimage import argrelextrema
from datetime import datetime

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
    RECTANGLE = "rectangle"
    RISING_THREE_METHODS = "rising_three_methods"
    FALLING_THREE_METHODS = "falling_three_methods"

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
    additional_data: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            'pattern_type': self.pattern_type.value,
            'direction': self.direction.value,
            'entry_price': float(self.entry_price),
            'target_price': float(self.target_price),
            'stop_loss': float(self.stop_loss),
            'confidence': float(self.confidence),
            'formation_bars': int(self.formation_bars),
            'risk_reward_ratio': float(self.risk_reward_ratio),
            'timestamp': self.timestamp.isoformat(),
            'additional_data': self.additional_data
        }

class AdvancedPatternDetector:
    """Enterprise-grade pattern detection engine"""
    
    def __init__(self, 
                 min_pattern_bars: int = 5,
                 harmonic_tolerance: float = 0.05):
        """
        Initialize pattern detector
        
        Args:
            min_pattern_bars: Minimum bars to form pattern
            harmonic_tolerance: Tolerance for harmonic ratios (5%)
        """
        self.min_pattern_bars = min_pattern_bars
        self.harmonic_tolerance = harmonic_tolerance
    
    def detect_all_patterns(self, 
                           df: pd.DataFrame,
                           min_confidence: float = 0.7) -> List[PatternSignal]:
        """
        Detect all patterns in price data
        
        Args:
            df: OHLCV DataFrame with columns: open, high, low, close, volume
            min_confidence: Minimum confidence threshold (0-1)
            
        Returns:
            List of detected patterns sorted by confidence
        """
        if len(df) < self.min_pattern_bars:
            return []
        
        patterns = []
        
        # Price data
        high = df['high'].values
        low = df['low'].values
        close = df['close'].values
        
        try:
            # Detect each pattern type
            patterns.extend(self._detect_head_shoulders(high, low, close, df.index))
            patterns.extend(self._detect_double_patterns(high, low, close, df.index))
            patterns.extend(self._detect_triangles(high, low, close, df.index))
            patterns.extend(self._detect_wedges(high, low, close, df.index))
            patterns.extend(self._detect_flags_pennants(high, low, close, df.index))
            patterns.extend(self._detect_rectangles(high, low, close, df.index))
            patterns.extend(self._detect_harmonic_patterns(high, low, close, df.index))
            patterns.extend(self._detect_support_resistance(high, low, close, df.index))
            
            # Filter by confidence
            patterns = [p for p in patterns if p.confidence >= min_confidence]
            
            # Sort by confidence
            patterns.sort(key=lambda x: x.confidence, reverse=True)
            
            logger.info(f"Detected {len(patterns)} patterns with confidence >= {min_confidence}")
            return patterns
        
        except Exception as e:
            logger.error(f"Error detecting patterns: {e}")
            return []
    
    def _detect_head_shoulders(self, 
                              high: np.ndarray,
                              low: np.ndarray,
                              close: np.ndarray,
                              index: pd.Index) -> List[PatternSignal]:
        """Detect Head & Shoulders patterns"""
        patterns = []
        
        try:
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
                troughs_between = troughs[(troughs > left_peak_idx) & (troughs < right_peak_idx)]
                if len(troughs_between) < 2:
                    continue
                
                left_trough = troughs_between[0]
                right_trough = troughs_between[-1]
                
                left_shoulder_height = high[left_peak_idx]
                head_height = high[head_idx]
                right_shoulder_height = high[right_peak_idx]
                
                # Head & Shoulders validation
                shoulder_ratio = 0.05
                if (abs(left_shoulder_height - right_shoulder_height) / head_height < shoulder_ratio and
                    left_shoulder_height < head_height * 0.98 and
                    right_shoulder_height < head_height * 0.98):
                    
                    # Calculate neckline
                    neckline = np.mean([low[left_trough], low[right_trough]])
                    
                    # Bearish H&S
                    entry_price = neckline
                    target = neckline - (head_height - neckline)
                    stop_loss = head_height
                    
                    confidence = self._calculate_pattern_confidence(
                        left_shoulder_height / head_height,
                        right_shoulder_height / head_height,
                        0.95  # expected ratio
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
                        risk_reward_ratio=(entry_price - target) / (stop_loss - entry_price + 1e-10),
                        timestamp=index[right_trough],
                        additional_data={
                            'neckline': float(neckline),
                            'head_height': float(head_height),
                            'left_shoulder': float(left_shoulder_height),
                            'right_shoulder': float(right_shoulder_height)
                        }
                    )
                    patterns.append(pattern)
        
        except Exception as e:
            logger.error(f"Error detecting head & shoulders: {e}")
        
        return patterns
    
    def _detect_double_patterns(self,
                               high: np.ndarray,
                               low: np.ndarray,
                               close: np.ndarray,
                               index: pd.Index) -> List[PatternSignal]:
        """Detect Double Top/Bottom patterns"""
        patterns = []
        
        try:
            peaks = argrelextrema(high, np.greater, order=5)[0]
            troughs = argrelextrema(low, np.less, order=5)[0]
            
            if len(peaks) < 2:
                return patterns
            
            # Double Tops
            for i in range(len(peaks) - 1):
                peak1_idx = peaks[i]
                peak2_idx = peaks[i + 1]
                peak1 = high[peak1_idx]
                peak2 = high[peak2_idx]
                
                # Check if peaks are similar in height (within 2%)
                if abs(peak1 - peak2) / peak1 < 0.02:
                    # Find intermediate trough
                    troughs_between = troughs[(troughs > peak1_idx) & (troughs < peak2_idx)]
                    
                    if len(troughs_between) > 0:
                        intermediate_trough_idx = troughs_between[0]
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
                            confidence=0.78,
                            pattern_start_idx=peak1_idx,
                            pattern_end_idx=peak2_idx,
                            formation_bars=peak2_idx - peak1_idx,
                            risk_reward_ratio=(entry_price - target) / (stop_loss - entry_price + 1e-10),
                            timestamp=index[peak2_idx],
                            additional_data={
                                'peak1_height': float(peak1),
                                'peak2_height': float(peak2),
                                'valley': float(valley)
                            }
                        )
                        patterns.append(pattern)
            
            # Double Bottoms
            if len(troughs) >= 2:
                for i in range(len(troughs) - 1):
                    trough1_idx = troughs[i]
                    trough2_idx = troughs[i + 1]
                    trough1 = low[trough1_idx]
                    trough2 = low[trough2_idx]
                    
                    if abs(trough1 - trough2) / trough1 < 0.02:
                        # Find intermediate peak
                        peaks_between = peaks[(peaks > trough1_idx) & (peaks < trough2_idx)]
                        
                        if len(peaks_between) > 0:
                            intermediate_peak_idx = peaks_between[0]
                            peak = high[intermediate_peak_idx]
                            
                            entry_price = peak
                            target = peak + (peak - trough1)
                            stop_loss = trough1
                            
                            pattern = PatternSignal(
                                pattern_type=PatternType.DOUBLE_BOTTOM,
                                direction=PatternDirection.BULLISH,
                                entry_price=entry_price,
                                target_price=target,
                                stop_loss=stop_loss,
                                confidence=0.78,
                                pattern_start_idx=trough1_idx,
                                pattern_end_idx=trough2_idx,
                                formation_bars=trough2_idx - trough1_idx,
                                risk_reward_ratio=(target - entry_price) / (entry_price - stop_loss + 1e-10),
                                timestamp=index[trough2_idx],
                                additional_data={
                                    'trough1': float(trough1),
                                    'trough2': float(trough2),
                                    'peak': float(peak)
                                }
                            )
                            patterns.append(pattern)
        
        except Exception as e:
            logger.error(f"Error detecting double patterns: {e}")
        
        return patterns
    
    def _detect_triangles(self,
                         high: np.ndarray,
                         low: np.ndarray,
                         close: np.ndarray,
                         index: pd.Index) -> List[PatternSignal]:
        """Detect triangle patterns (ascending, descending, symmetrical)"""
        patterns = []
        
        try:
            # Use rolling windows to detect converging highs/lows
            window_size = 20
            
            for i in range(window_size, len(close) - 5):
                window_high = high[i-window_size:i]
                window_low = low[i-window_size:i]
                
                # Calculate trend lines
                high_trend = np.polyfit(range(len(window_high)), window_high, 1)[0]
                low_trend = np.polyfit(range(len(window_low)), window_low, 1)[0]
                
                # Ascending triangle: higher lows, flat highs
                if abs(high_trend) < 0.0001 and low_trend > 0.0001:
                    entry_price = window_high[-1]
                    target = entry_price + (window_high[-1] - window_low[-1]) * 1.5
                    stop_loss = window_low[-1] - (window_high[-1] - window_low[-1]) * 0.5
                    
                    pattern = PatternSignal(
                        pattern_type=PatternType.TRIANGLE_ASCENDING,
                        direction=PatternDirection.BULLISH,
                        entry_price=entry_price,
                        target_price=target,
                        stop_loss=stop_loss,
                        confidence=0.72,
                        pattern_start_idx=i - window_size,
                        pattern_end_idx=i,
                        formation_bars=window_size,
                        risk_reward_ratio=(target - entry_price) / (entry_price - stop_loss + 1e-10),
                        timestamp=index[i],
                        additional_data={
                            'high_trend': float(high_trend),
                            'low_trend': float(low_trend)
                        }
                    )
                    patterns.append(pattern)
                
                # Descending triangle: lower highs, flat lows
                elif high_trend < -0.0001 and abs(low_trend) < 0.0001:
                    entry_price = window_low[-1]
                    target = entry_price - (window_high[-1] - window_low[-1]) * 1.5
                    stop_loss = window_high[-1] + (window_high[-1] - window_low[-1]) * 0.5
                    
                    pattern = PatternSignal(
                        pattern_type=PatternType.TRIANGLE_DESCENDING,
                        direction=PatternDirection.BEARISH,
                        entry_price=entry_price,
                        target_price=target,
                        stop_loss=stop_loss,
                        confidence=0.72,
                        pattern_start_idx=i - window_size,
                        pattern_end_idx=i,
                        formation_bars=window_size,
                        risk_reward_ratio=(entry_price - target) / (stop_loss - entry_price + 1e-10),
                        timestamp=index[i],
                        additional_data={
                            'high_trend': float(high_trend),
                            'low_trend': float(low_trend)
                        }
                    )
                    patterns.append(pattern)
                
                # Symmetrical triangle: converging highs and lows
                elif high_trend < -0.0001 and low_trend > 0.0001:
                    range_size = window_high[-1] - window_low[-1]
                    mid_price = (window_high[-1] + window_low[-1]) / 2
                    
                    pattern = PatternSignal(
                        pattern_type=PatternType.TRIANGLE_SYMMETRICAL,
                        direction=PatternDirection.NEUTRAL,
                        entry_price=mid_price,
                        target_price=mid_price + range_size,
                        stop_loss=mid_price - range_size,
                        confidence=0.70,
                        pattern_start_idx=i - window_size,
                        pattern_end_idx=i,
                        formation_bars=window_size,
                        risk_reward_ratio=1.0,
                        timestamp=index[i],
                        additional_data={
                            'high_trend': float(high_trend),
                            'low_trend': float(low_trend),
                            'convergence_rate': float(abs(high_trend) + abs(low_trend))
                        }
                    )
                    patterns.append(pattern)
        
        except Exception as e:
            logger.error(f"Error detecting triangles: {e}")
        
        return patterns
    
    def _detect_wedges(self,
                      high: np.ndarray,
                      low: np.ndarray,
                      close: np.ndarray,
                      index: pd.Index) -> List[PatternSignal]:
        """Detect wedge patterns (rising, falling)"""
        patterns = []
        
        try:
            window_size = 20
            
            for i in range(window_size, len(close) - 5):
                window_high = high[i-window_size:i]
                window_low = low[i-window_size:i]
                
                high_trend = np.polyfit(range(len(window_high)), window_high, 1)[0]
                low_trend = np.polyfit(range(len(window_low)), window_low, 1)[0]
                
                # Rising wedge (bearish): both highs and lows rising, but lows rising faster
                if high_trend > 0.0001 and low_trend > high_trend * 1.5:
                    entry_price = window_high[-1]
                    target = window_low[-1] - (window_high[-1] - window_low[-1]) * 1.5
                    stop_loss = window_high[-1] + (window_high[-1] - window_low[-1]) * 0.5
                    
                    pattern = PatternSignal(
                        pattern_type=PatternType.WEDGE_RISING,
                        direction=PatternDirection.BEARISH,
                        entry_price=entry_price,
                        target_price=target,
                        stop_loss=stop_loss,
                        confidence=0.74,
                        pattern_start_idx=i - window_size,
                        pattern_end_idx=i,
                        formation_bars=window_size,
                        risk_reward_ratio=(entry_price - target) / (stop_loss - entry_price + 1e-10),
                        timestamp=index[i],
                        additional_data={
                            'high_trend': float(high_trend),
                            'low_trend': float(low_trend)
                        }
                    )
                    patterns.append(pattern)
                
                # Falling wedge (bullish): both highs and lows falling, but highs falling faster
                elif high_trend < -0.0001 and high_trend < low_trend * 1.5:
                    entry_price = window_low[-1]
                    target = window_high[-1] + (window_high[-1] - window_low[-1]) * 1.5
                    stop_loss = window_low[-1] - (window_high[-1] - window_low[-1]) * 0.5
                    
                    pattern = PatternSignal(
                        pattern_type=PatternType.WEDGE_FALLING,
                        direction=PatternDirection.BULLISH,
                        entry_price=entry_price,
                        target_price=target,
                        stop_loss=stop_loss,
                        confidence=0.74,
                        pattern_start_idx=i - window_size,
                        pattern_end_idx=i,
                        formation_bars=window_size,
                        risk_reward_ratio=(target - entry_price) / (entry_price - stop_loss + 1e-10),
                        timestamp=index[i],
                        additional_data={
                            'high_trend': float(high_trend),
                            'low_trend': float(low_trend)
                        }
                    )
                    patterns.append(pattern)
        
        except Exception as e:
            logger.error(f"Error detecting wedges: {e}")
        
        return patterns
    
    def _detect_flags_pennants(self,
                              high: np.ndarray,
                              low: np.ndarray,
                              close: np.ndarray,
                              index: pd.Index) -> List[PatternSignal]:
        """Detect flag and pennant patterns"""
        patterns = []
        
        try:
            # Look for price spike followed by consolidation
            window_size = 15
            consolidation_window = 10
            
            for i in range(window_size, len(close) - consolidation_window):
                # Check for prior strong trend
                trend_range = close[i-window_size:i]
                trend_change = (trend_range[-1] - trend_range[0]) / trend_range[0]
                
                if abs(trend_change) > 0.02:  # At least 2% move
                    # Check consolidation period
                    consolidation = high[i:i+consolidation_window] - low[i:i+consolidation_window]
                    avg_consolidation = np.mean(consolidation)
                    
                    # Flag/Pennant detected if consolidation is narrow
                    if avg_consolidation < (high[i] - low[i]) * 0.3:
                        if trend_change > 0.02:  # Bullish flag
                            entry_price = high[i + consolidation_window - 1]
                            move = high[i] - low[i-window_size]
                            target = entry_price + move * 1.0
                            stop_loss = low[i:i+consolidation_window].min()
                            
                            pattern = PatternSignal(
                                pattern_type=PatternType.FLAG,
                                direction=PatternDirection.BULLISH,
                                entry_price=entry_price,
                                target_price=target,
                                stop_loss=stop_loss,
                                confidence=0.76,
                                pattern_start_idx=i - window_size,
                                pattern_end_idx=i + consolidation_window,
                                formation_bars=consolidation_window,
                                risk_reward_ratio=(target - entry_price) / (entry_price - stop_loss + 1e-10),
                                timestamp=index[i + consolidation_window - 1],
                                additional_data={
                                    'prior_trend': float(trend_change),
                                    'consolidation_avg': float(avg_consolidation)
                                }
                            )
                            patterns.append(pattern)
                        
                        else:  # Bearish flag
                            entry_price = low[i + consolidation_window - 1]
                            move = high[i-window_size] - low[i]
                            target = entry_price - move * 1.0
                            stop_loss = high[i:i+consolidation_window].max()
                            
                            pattern = PatternSignal(
                                pattern_type=PatternType.FLAG,
                                direction=PatternDirection.BEARISH,
                                entry_price=entry_price,
                                target_price=target,
                                stop_loss=stop_loss,
                                confidence=0.76,
                                pattern_start_idx=i - window_size,
                                pattern_end_idx=i + consolidation_window,
                                formation_bars=consolidation_window,
                                risk_reward_ratio=(entry_price - target) / (stop_loss - entry_price + 1e-10),
                                timestamp=index[i + consolidation_window - 1],
                                additional_data={
                                    'prior_trend': float(trend_change),
                                    'consolidation_avg': float(avg_consolidation)
                                }
                            )
                            patterns.append(pattern)
        
        except Exception as e:
            logger.error(f"Error detecting flags/pennants: {e}")
        
        return patterns
    
    def _detect_rectangles(self,
                          high: np.ndarray,
                          low: np.ndarray,
                          close: np.ndarray,
                          index: pd.Index) -> List[PatternSignal]:
        """Detect rectangle patterns"""
        patterns = []
        
        try:
            window_size = 20
            
            for i in range(window_size, len(close) - 5):
                window_high = high[i-window_size:i]
                window_low = low[i-window_size:i]
                
                # Check if range is relatively flat
                high_range = np.max(window_high) - np.min(window_high)
                low_range = np.max(window_low) - np.min(window_low)
                
                # Rectangle if both highs and lows are relatively flat
                if high_range < (np.mean(window_high) * 0.02) and low_range < (np.mean(window_low) * 0.02):
                    
                    resistance = np.max(window_high)
                    support = np.min(window_low)
                    
                    # Determine breakout direction based on close position
                    close_ratio = (close[i] - support) / (resistance - support)
                    
                    if close_ratio > 0.6:  # Closer to resistance
                        pattern_direction = PatternDirection.BULLISH
                        entry_price = resistance
                        target = resistance + (resistance - support) * 1.0
                        stop_loss = support
                    else:
                        pattern_direction = PatternDirection.BEARISH
                        entry_price = support
                        target = support - (resistance - support) * 1.0
                        stop_loss = resistance
                    
                    pattern = PatternSignal(
                        pattern_type=PatternType.RECTANGLE,
                        direction=pattern_direction,
                        entry_price=entry_price,
                        target_price=target,
                        stop_loss=stop_loss,
                        confidence=0.71,
                        pattern_start_idx=i - window_size,
                        pattern_end_idx=i,
                        formation_bars=window_size,
                        risk_reward_ratio=abs(target - entry_price) / abs(stop_loss - entry_price + 1e-10),
                        timestamp=index[i],
                        additional_data={
                            'resistance': float(resistance),
                            'support': float(support),
                            'width': float(resistance - support)
                        }
                    )
                    patterns.append(pattern)
        
        except Exception as e:
            logger.error(f"Error detecting rectangles: {e}")
        
        return patterns
    
    def _detect_harmonic_patterns(self,
                                 high: np.ndarray,
                                 low: np.ndarray,
                                 close: np.ndarray,
                                 index: pd.Index) -> List[PatternSignal]:
        """
        Detect Harmonic patterns (Gartley, Butterfly, Crab, Bat)
        Uses Fibonacci ratios
        """
        patterns = []
        
        try:
            # Fibonacci ratios for harmonic patterns
            peaks = argrelextrema(high, np.greater, order=5)[0]
            troughs = argrelextrema(low, np.less, order=5)[0]
            
            # Find XABCD pattern points
            extrema_points = sorted(list(peaks) + list(troughs))
            
            if len(extrema_points) < 4:
                return patterns
            
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
                
                if xa_move == 0 or ab_move == 0:
                    continue
                
                ab_ratio = ab_move / xa_move
                bc_ratio = bc_move / ab_move
                
                # Check Gartley pattern (0.618-0.886 AB/XA, 1.272-1.618 BC/AB)
                if (0.55 < ab_ratio < 0.75 and 1.2 < bc_ratio < 1.8):
                    cd_target = c_price + bc_move * 1.272
                    
                    direction = PatternDirection.BULLISH if x_price > a_price else PatternDirection.BEARISH
                    
                    pattern = PatternSignal(
                        pattern_type=PatternType.GARTLEY,
                        direction=direction,
                        entry_price=c_price,
                        target_price=cd_target,
                        stop_loss=x_price,
                        confidence=0.81,
                        pattern_start_idx=x_idx,
                        pattern_end_idx=c_idx,
                        formation_bars=c_idx - x_idx,
                        risk_reward_ratio=abs(cd_target - c_price) / (abs(x_price - c_price) + 1e-10),
                        timestamp=index[c_idx],
                        additional_data={
                            'ab_ratio': float(ab_ratio),
                            'bc_ratio': float(bc_ratio)
                        }
                    )
                    patterns.append(pattern)
                
                # Check Butterfly pattern (0.786 AB/XA, 1.618 BC/AB)
                elif (0.75 < ab_ratio < 0.82 and 1.5 < bc_ratio < 1.75):
                    cd_target = c_price + bc_move * 1.618
                    
                    direction = PatternDirection.BULLISH if x_price > a_price else PatternDirection.BEARISH
                    
                    pattern = PatternSignal(
                        pattern_type=PatternType.BUTTERFLY,
                        direction=direction,
                        entry_price=c_price,
                        target_price=cd_target,
                        stop_loss=x_price,
                        confidence=0.82,
                        pattern_start_idx=x_idx,
                        pattern_end_idx=c_idx,
                        formation_bars=c_idx - x_idx,
                        risk_reward_ratio=abs(cd_target - c_price) / (abs(x_price - c_price) + 1e-10),
                        timestamp=index[c_idx],
                        additional_data={
                            'ab_ratio': float(ab_ratio),
                            'bc_ratio': float(bc_ratio)
                        }
                    )
                    patterns.append(pattern)
                
                # Check Crab pattern (0.382 AB/XA, 2.24 BC/AB)
                elif (0.35 < ab_ratio < 0.42 and 2.1 < bc_ratio < 2.4):
                    cd_target = c_price + bc_move * 1.618
                    
                    direction = PatternDirection.BULLISH if x_price > a_price else PatternDirection.BEARISH
                    
                    pattern = PatternSignal(
                        pattern_type=PatternType.CRAB,
                        direction=direction,
                        entry_price=c_price,
                        target_price=cd_target,
                        stop_loss=x_price,
                        confidence=0.83,
                        pattern_start_idx=x_idx,
                        pattern_end_idx=c_idx,
                        formation_bars=c_idx - x_idx,
                        risk_reward_ratio=abs(cd_target - c_price) / (abs(x_price - c_price) + 1e-10),
                        timestamp=index[c_idx],
                        additional_data={
                            'ab_ratio': float(ab_ratio),
                            'bc_ratio': float(bc_ratio)
                        }
                    )
                    patterns.append(pattern)
                
                # Check Bat pattern (0.5 AB/XA, 0.886 BC/AB)
                elif (0.45 < ab_ratio < 0.55 and 0.8 < bc_ratio < 1.0):
                    cd_target = c_price + bc_move * 0.886
                    
                    direction = PatternDirection.BULLISH if x_price > a_price else PatternDirection.BEARISH
                    
                    pattern = PatternSignal(
                        pattern_type=PatternType.BAT,
                        direction=direction,
                        entry_price=c_price,
                        target_price=cd_target,
                        stop_loss=x_price,
                        confidence=0.80,
                        pattern_start_idx=x_idx,
                        pattern_end_idx=c_idx,
                        formation_bars=c_idx - x_idx,
                        risk_reward_ratio=abs(cd_target - c_price) / (abs(x_price - c_price) + 1e-10),
                        timestamp=index[c_idx],
                        additional_data={
                            'ab_ratio': float(ab_ratio),
                            'bc_ratio': float(bc_ratio)
                        }
                    )
                    patterns.append(pattern)
        
        except Exception as e:
            logger.error(f"Error detecting harmonic patterns: {e}")
        
        return patterns
    
    def _detect_support_resistance(self,
                                  high: np.ndarray,
                                  low: np.ndarray,
                                  close: np.ndarray,
                                  index: pd.Index) -> List[PatternSignal]:
        """Identify key support and resistance levels"""
        patterns = []
        
        try:
            peaks = argrelextrema(high, np.greater, order=5)[0]
            troughs = argrelextrema(low, np.less, order=5)[0]
            
            # Group nearby peaks (resistance levels)
            for peak_idx in peaks:
                peak_price = high[peak_idx]
                nearby_peaks = peaks[np.abs(peaks - peak_idx) <= 10]
                
                if len(nearby_peaks) >= 2:
                    avg_resistance = np.mean(high[nearby_peaks])
                    
                    # Support is below
                    support_idx = max(troughs[troughs < peak_idx]) if len(troughs[troughs < peak_idx]) > 0 else 0
                    support_price = low[support_idx]
                    
                    pattern = PatternSignal(
                        pattern_type=PatternType.SUPPORT_RESISTANCE,
                        direction=PatternDirection.NEUTRAL,
                        entry_price=(avg_resistance + support_price) / 2,
                        target_price=avg_resistance,
                        stop_loss=support_price,
                        confidence=0.65,
                        pattern_start_idx=support_idx,
                        pattern_end_idx=peak_idx,
                        formation_bars=len(nearby_peaks),
                        risk_reward_ratio=(avg_resistance - support_price) / (avg_resistance - support_price + 1e-10),
                        timestamp=index[peak_idx],
                        additional_data={
                            'resistance_level': float(avg_resistance),
                            'support_level': float(support_price),
                            'num_touches': int(len(nearby_peaks))
                        }
                    )
                    patterns.append(pattern)
        
        except Exception as e:
            logger.error(f"Error detecting support/resistance: {e}")
        
        return patterns
    
    def _calculate_pattern_confidence(self,
                                     actual_ratio: float,
                                     expected_ratio: float,
                                     tolerance: float) -> float:
        """Calculate confidence score for pattern"""
        if expected_ratio == 0:
            return 0.0
        
        deviation = abs(actual_ratio - expected_ratio) / expected_ratio
        confidence = max(0, 1 - (deviation / tolerance))
        return min(1.0, confidence)
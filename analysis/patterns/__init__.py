"""
Pattern Recognition Module

Includes chart patterns, candlestick patterns, and support/resistance detection.
"""

from analysis.patterns.chart_patterns import ChartPatternDetector, ChartPattern
from analysis.patterns.candlestick import CandlestickPatternDetector, CandlestickPattern
from analysis.patterns.support_resistance import SupportResistanceDetector

__all__ = [
    'ChartPatternDetector',
    'ChartPattern',
    'CandlestickPatternDetector',
    'CandlestickPattern',
    'SupportResistanceDetector',
]

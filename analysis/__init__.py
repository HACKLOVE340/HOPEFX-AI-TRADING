"""
Analysis Module

Advanced analysis tools for trading including:
- Pattern recognition (chart and candlestick patterns)
- Support/Resistance detection
- Technical analysis utilities
"""

from analysis.patterns.chart_patterns import ChartPatternDetector
from analysis.patterns.candlestick import CandlestickPatternDetector
from analysis.patterns.support_resistance import SupportResistanceDetector

__all__ = [
    'ChartPatternDetector',
    'CandlestickPatternDetector',
    'SupportResistanceDetector',
]

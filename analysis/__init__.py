"""
Analysis Module

Advanced analysis tools for trading including:
- Pattern recognition (chart and candlestick patterns)
- Support/Resistance detection
- Technical analysis utilities
- Market regime detection
- Multi-timeframe confluence analysis
- Session-based analysis
"""

from analysis.patterns.chart_patterns import ChartPatternDetector
from analysis.patterns.candlestick import CandlestickPatternDetector
from analysis.patterns.support_resistance import SupportResistanceDetector
from analysis.market_analysis import (
    MarketRegimeDetector,
    MultiTimeframeAnalyzer,
    SessionAnalyzer,
    MarketRegime,
    TradingSession,
    RegimeAnalysis,
    ConfluenceAnalysis,
    SessionAnalysis,
)

__all__ = [
    'ChartPatternDetector',
    'CandlestickPatternDetector',
    'SupportResistanceDetector',
    'MarketRegimeDetector',
    'MultiTimeframeAnalyzer',
    'SessionAnalyzer',
    'MarketRegime',
    'TradingSession',
    'RegimeAnalysis',
    'ConfluenceAnalysis',
    'SessionAnalysis',
]

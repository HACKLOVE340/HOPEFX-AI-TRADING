"""
Analysis Module

Advanced analysis tools for trading including:
- Pattern recognition (chart and candlestick patterns)
- Support/Resistance detection
- Technical analysis utilities
- Market regime detection
- Multi-timeframe confluence analysis
- Session-based analysis
- Order flow analysis (volume profile, delta, footprint)
- Market scanning and opportunity detection
"""

# Core analysis imports (may not be available in all environments)
try:
    from analysis.patterns.chart_patterns import ChartPatternDetector
    from analysis.patterns.candlestick import CandlestickPatternDetector
    from analysis.patterns.support_resistance import SupportResistanceDetector
except ImportError:
    # Patterns module not fully implemented
    ChartPatternDetector = None
    CandlestickPatternDetector = None
    SupportResistanceDetector = None

try:
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
except ImportError:
    MarketRegimeDetector = None
    MultiTimeframeAnalyzer = None
    SessionAnalyzer = None
    MarketRegime = None
    TradingSession = None
    RegimeAnalysis = None
    ConfluenceAnalysis = None
    SessionAnalysis = None

# Order flow analysis - NEW
from analysis.order_flow import (
    OrderFlowAnalyzer,
    VolumeProfile,
    VolumeProfileLevel,
    OrderFlowAnalysis,
    Footprint,
    Trade,
    get_order_flow_analyzer,
    create_order_flow_router,
)

# Market scanner - NEW
from analysis.market_scanner import (
    MarketScanner,
    ScanCriteriaType,
    ScanCriteria,
    ScanResult,
    MarketOpportunity,
    SignalDirection as ScannerSignalDirection,
    get_market_scanner,
    create_scanner_router,
)

__all__ = [
    # Pattern detection (optional)
    'ChartPatternDetector',
    'CandlestickPatternDetector',
    'SupportResistanceDetector',
    # Market analysis (optional)
    'MarketRegimeDetector',
    'MultiTimeframeAnalyzer',
    'SessionAnalyzer',
    'MarketRegime',
    'TradingSession',
    'RegimeAnalysis',
    'ConfluenceAnalysis',
    'SessionAnalysis',
    # Order flow analysis (NEW)
    'OrderFlowAnalyzer',
    'VolumeProfile',
    'VolumeProfileLevel',
    'OrderFlowAnalysis',
    'Footprint',
    'Trade',
    'get_order_flow_analyzer',
    'create_order_flow_router',
    # Market scanner (NEW)
    'MarketScanner',
    'ScanCriteriaType',
    'ScanCriteria',
    'ScanResult',
    'MarketOpportunity',
    'ScannerSignalDirection',
    'get_market_scanner',
    'create_scanner_router',
]

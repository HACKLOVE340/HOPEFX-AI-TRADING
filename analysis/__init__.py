# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
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
    from analysis.patterns.candlestick import CandlestickPatternDetector
    from analysis.patterns.chart_patterns import ChartPatternDetector
    from analysis.patterns.support_resistance import SupportResistanceDetector
except ImportError:
    # Patterns module not fully implemented
    ChartPatternDetector = None
    CandlestickPatternDetector = None
    SupportResistanceDetector = None

try:
    from analysis.market_analysis import (
        ConfluenceAnalysis,
        MarketRegime,
        MarketRegimeDetector,
        MultiTimeframeAnalyzer,
        RegimeAnalysis,
        SessionAnalysis,
        SessionAnalyzer,
        TradingSession,
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
# Advanced order flow - NEW
from analysis.advanced_order_flow import (
    AdvancedOrderFlowAnalyzer,
    AggressionMetrics,
    DeltaDivergence,
    OrderFlowOscillator,
    StackedImbalance,
    VolumeCluster,
    get_advanced_order_flow_analyzer,
)

# Institutional flow detection - NEW
from analysis.institutional_flow import (
    FlowSignal,
    InstitutionalFlowDetector,
    InstitutionalTrade,
    SmartMoneyDirection,
    get_institutional_detector,
)

# Market scanner - NEW
from analysis.market_scanner import (
    MarketOpportunity,
    MarketScanner,
    ScanCriteria,
    ScanCriteriaType,
    ScanResult,
    create_scanner_router,
    get_market_scanner,
)
from analysis.market_scanner import (
    SignalDirection as ScannerSignalDirection,
)
from analysis.order_flow import (
    Footprint,
    OrderFlowAnalysis,
    OrderFlowAnalyzer,
    Trade,
    VolumeProfile,
    VolumeProfileLevel,
    create_order_flow_router,
    get_order_flow_analyzer,
)

# Order flow dashboard - NEW
from analysis.order_flow_dashboard import (
    OrderFlowDashboard,
    create_dashboard_router,
    get_order_flow_dashboard,
)

__all__ = [
    # Advanced order flow (NEW)
    "AdvancedOrderFlowAnalyzer",
    "AggressionMetrics",
    "CandlestickPatternDetector",
    # Pattern detection (optional)
    "ChartPatternDetector",
    "ConfluenceAnalysis",
    "DeltaDivergence",
    "FlowSignal",
    "Footprint",
    # Institutional flow (NEW)
    "InstitutionalFlowDetector",
    "InstitutionalTrade",
    "MarketOpportunity",
    "MarketRegime",
    # Market analysis (optional)
    "MarketRegimeDetector",
    # Market scanner (NEW)
    "MarketScanner",
    "MultiTimeframeAnalyzer",
    "OrderFlowAnalysis",
    # Order flow analysis (NEW)
    "OrderFlowAnalyzer",
    # Dashboard (NEW)
    "OrderFlowDashboard",
    "OrderFlowOscillator",
    "RegimeAnalysis",
    "ScanCriteria",
    "ScanCriteriaType",
    "ScanResult",
    "ScannerSignalDirection",
    "SessionAnalysis",
    "SessionAnalyzer",
    "SmartMoneyDirection",
    "StackedImbalance",
    "SupportResistanceDetector",
    "Trade",
    "TradingSession",
    "VolumeCluster",
    "VolumeProfile",
    "VolumeProfileLevel",
    "create_dashboard_router",
    "create_order_flow_router",
    "create_scanner_router",
    "get_advanced_order_flow_analyzer",
    "get_institutional_detector",
    "get_market_scanner",
    "get_order_flow_analyzer",
    "get_order_flow_dashboard",
]

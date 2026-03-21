"""
Risk management package.
"""

from .manager import (
    RiskManager,
    RiskConfig,
    RiskLevel,
    RiskAssessment,
    PositionSizingResult,
)
from .advanced_analytics import (
    RiskMetricType,
    VaRResult,
    MonteCarloResult,
    StressTestResult,
    DrawdownAnalysis,
)

# Backwards-compat aliases expected by old callers
PositionSize = PositionSizingResult

class PositionSizeMethod:
    """Stub enum — sizing method is determined by RiskConfig."""
    FIXED = "fixed"
    PERCENT_EQUITY = "percent_equity"
    KELLY = "kelly"
    VOLATILITY = "volatility"

__all__ = [
    "RiskManager", "RiskConfig", "RiskLevel", "RiskAssessment",
    "PositionSizingResult", "PositionSize", "PositionSizeMethod",
    "RiskMetricType", "VaRResult", "MonteCarloResult",
    "StressTestResult", "DrawdownAnalysis",
]

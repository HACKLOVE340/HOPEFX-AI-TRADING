# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
Risk management package.
"""

from .advanced_analytics import (
    DrawdownAnalysis,
    MonteCarloResult,
    RiskMetricType,
    StressTestResult,
    VaRResult,
)
from .manager import (
    PositionSizingResult,
    RiskAssessment,
    RiskConfig,
    RiskLevel,
    RiskManager,
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
    "RiskManager",
    "RiskConfig",
    "RiskLevel",
    "RiskAssessment",
    "PositionSizingResult",
    "PositionSize",
    "PositionSizeMethod",
    "RiskMetricType",
    "VaRResult",
    "MonteCarloResult",
    "StressTestResult",
    "DrawdownAnalysis",
]

__version__ = "1.0.0"

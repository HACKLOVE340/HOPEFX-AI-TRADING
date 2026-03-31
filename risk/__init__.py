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
from .orchestrator import RiskOrchestrator, risk_orchestrator
from .intra_trade_monitor import IntraTradeMonitor, OpenPosition, UnwindSignal
from .post_trade_analyzer import PostTradeAnalyzer, FillRecord

# Backwards-compat aliases expected by old callers
PositionSize = PositionSizingResult


class PositionSizeMethod:
    """Backwards-compat sizing method constants. Sizing logic lives in RiskConfig."""

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
    "RiskOrchestrator",
    "risk_orchestrator",
    "IntraTradeMonitor",
    "OpenPosition",
    "UnwindSignal",
    "PostTradeAnalyzer",
    "FillRecord",
]

__version__ = "1.0.0"

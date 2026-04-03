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
from .intra_trade_monitor import IntraTradeMonitor, OpenPosition, UnwindSignal
from .manager import (
    PositionSizingResult,
    RiskAssessment,
    RiskConfig,
    RiskLevel,
    RiskManager,
)
from .orchestrator import RiskOrchestrator, risk_orchestrator
from .post_trade_analyzer import FillRecord, PostTradeAnalyzer

# Backwards-compat aliases expected by old callers
PositionSize = PositionSizingResult


class PositionSizeMethod:
    """Backwards-compat sizing method constants. Sizing logic lives in RiskConfig."""

    FIXED = "fixed"
    PERCENT_EQUITY = "percent_equity"
    KELLY = "kelly"
    VOLATILITY = "volatility"


__all__ = [
    "DrawdownAnalysis",
    "FillRecord",
    "IntraTradeMonitor",
    "MonteCarloResult",
    "OpenPosition",
    "PositionSize",
    "PositionSizeMethod",
    "PositionSizingResult",
    "PostTradeAnalyzer",
    "RiskAssessment",
    "RiskConfig",
    "RiskLevel",
    "RiskManager",
    "RiskMetricType",
    "RiskOrchestrator",
    "StressTestResult",
    "UnwindSignal",
    "VaRResult",
    "risk_orchestrator",
]

__version__ = "1.0.0"

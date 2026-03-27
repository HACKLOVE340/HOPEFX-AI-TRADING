# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026 Opeyemi (HACKLOVE340)
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
Advanced risk engine — Monte Carlo simulation with GARCH volatility and copula correlation.

The implementation lives in core/acceleration/gpu_engine.py (historical placement).
This module re-exports the public classes so imports work from either location.
"""

from core.acceleration.gpu_engine import (  # noqa: F401
    CopulaRiskModel,
    GARCHModel,
    MonteCarloRiskEngine,
    RealTimeRiskMonitor,
    RiskMetrics,
)

__all__ = [
    "GARCHModel",
    "CopulaRiskModel",
    "MonteCarloRiskEngine",
    "RealTimeRiskMonitor",
    "RiskMetrics",
]

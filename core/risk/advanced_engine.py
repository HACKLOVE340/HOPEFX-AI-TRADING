"""
Advanced risk engine — Monte Carlo simulation with GARCH volatility and copula correlation.

The implementation lives in core/acceleration/gpu_engine.py (historical placement).
This module re-exports the public classes so imports work from either location.
"""
from core.acceleration.gpu_engine import (  # noqa: F401
    GARCHModel,
    CopulaRiskModel,
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

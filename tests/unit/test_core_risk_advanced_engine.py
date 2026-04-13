# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
tests/unit/test_core_risk_advanced_engine.py
=============================================
Coverage tests for core/risk/advanced_engine.py.

This module re-exports Monte Carlo / GARCH / Copula classes from
core/acceleration/gpu_engine.py. Tests verify the re-exports are
importable and the public API is intact.
"""

from __future__ import annotations

import pytest


def test_import_advanced_engine():
    """Module must be importable without GPU hardware."""
    import core.risk.advanced_engine as ae  # noqa: F401

    assert ae is not None


def test_exports_monte_carlo_risk_engine():
    from core.risk.advanced_engine import MonteCarloRiskEngine

    assert MonteCarloRiskEngine is not None


def test_exports_garch_model():
    from core.risk.advanced_engine import GARCHModel

    assert GARCHModel is not None


def test_exports_copula_risk_model():
    from core.risk.advanced_engine import CopulaRiskModel

    assert CopulaRiskModel is not None


def test_exports_real_time_risk_monitor():
    from core.risk.advanced_engine import RealTimeRiskMonitor

    assert RealTimeRiskMonitor is not None


def test_exports_risk_metrics():
    from core.risk.advanced_engine import RiskMetrics

    assert RiskMetrics is not None


def test_all_exports_listed():
    import core.risk.advanced_engine as ae

    expected = {
        "CopulaRiskModel",
        "GARCHModel",
        "MonteCarloRiskEngine",
        "RealTimeRiskMonitor",
        "RiskMetrics",
    }
    assert set(ae.__all__) == expected

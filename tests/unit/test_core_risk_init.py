# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
tests/unit/test_core_risk_init.py
==================================
Coverage tests for core/risk/__init__.py.

Uses real numpy/scipy/pandas — no mocking of the module under test.
"""

from __future__ import annotations

from decimal import Decimal

import numpy as np
import pandas as pd
import pytest

from core.risk import (
    CopulaRiskModel,
    GARCHModel,
    MonteCarloRiskEngine,
    RealTimeRiskMonitor,
    RiskMetrics,
)


# ── RiskMetrics ───────────────────────────────────────────────────────────────


def test_risk_metrics_fields():
    m = RiskMetrics(
        var_95=-0.02,
        var_99=-0.04,
        cvar_95=-0.03,
        cvar_99=-0.05,
        volatility=0.01,
        max_drawdown=-0.08,
        tail_risk=2.0,
        correlation_stress=0.6,
    )
    assert m.var_95 == -0.02
    assert m.var_99 == -0.04
    assert m.tail_risk == 2.0


# ── GARCHModel ────────────────────────────────────────────────────────────────


def test_garch_model_defaults():
    g = GARCHModel()
    assert g.alpha + g.beta < 1.0  # stationarity
    assert g.omega > 0
    assert g.nu > 2


def test_garch_model_fit_returns_self():
    rng = np.random.default_rng(42)
    returns = rng.normal(0, 0.01, 200)
    g = GARCHModel()
    result = g.fit(returns)
    assert result is g


def test_garch_model_forecast():
    rng = np.random.default_rng(42)
    returns = rng.normal(0, 0.01, 200)
    g = GARCHModel()
    g.fit(returns)
    forecasts = g.forecast(horizon=5)
    assert len(forecasts) == 5
    assert all(f > 0 for f in forecasts)


def test_garch_model_simulate():
    rng = np.random.default_rng(42)
    returns = rng.normal(0, 0.01, 200)
    g = GARCHModel()
    g.fit(returns)
    sims = g.simulate(n_sims=100, horizon=3)
    assert sims.shape == (100, 3)


# ── CopulaRiskModel ───────────────────────────────────────────────────────────


def test_copula_model_fit_and_simulate():
    rng = np.random.default_rng(7)
    df = pd.DataFrame({
        "XAUUSD": rng.normal(0.0002, 0.01, 300),
        "EURUSD": rng.normal(0.0001, 0.008, 300),
    })
    copula = CopulaRiskModel()
    copula.fit(df)
    sims = copula.simulate(n_sims=100)
    assert len(sims) == 100
    assert set(sims.columns) == {"XAUUSD", "EURUSD"}


def test_copula_model_defaults():
    copula = CopulaRiskModel()
    assert copula.marginals == {}
    assert copula.correlation.shape == (2, 2)


# ── MonteCarloRiskEngine ──────────────────────────────────────────────────────


def _make_engine_with_assets(n_sims: int = 200) -> MonteCarloRiskEngine:
    rng = np.random.default_rng(0)
    engine = MonteCarloRiskEngine(n_sims=n_sims)
    returns_data = {}
    for sym in ["XAUUSD", "EURUSD"]:
        r = rng.normal(0.0002, 0.01, 300)
        engine.add_asset(sym, r)
        returns_data[sym] = r
    # Fit the copula so simulate() works
    engine.copula.fit(pd.DataFrame(returns_data))
    return engine


def test_monte_carlo_engine_init():
    engine = MonteCarloRiskEngine(n_sims=100)
    assert engine.n_sims == 100
    assert engine.garch_models == {}


def test_monte_carlo_add_asset():
    rng = np.random.default_rng(1)
    engine = MonteCarloRiskEngine(n_sims=100)
    returns = rng.normal(0, 0.01, 200)
    engine.add_asset("XAUUSD", returns)
    assert "XAUUSD" in engine.garch_models
    assert "XAUUSD" in engine.historical_returns.columns


def test_monte_carlo_calculate_portfolio_risk():
    engine = _make_engine_with_assets(n_sims=200)
    weights = {"XAUUSD": 0.6, "EURUSD": 0.4}
    metrics = engine.calculate_portfolio_risk(weights)
    assert isinstance(metrics, RiskMetrics)
    assert metrics.volatility >= 0


def test_monte_carlo_stress_correlation_few_data():
    engine = MonteCarloRiskEngine(n_sims=100)
    # historical_returns is empty — should return 0.5
    result = engine._stress_correlation({"X": 1.0})
    assert result == 0.5


# ── RealTimeRiskMonitor ───────────────────────────────────────────────────────


def test_real_time_monitor_init():
    engine = _make_engine_with_assets(n_sims=200)
    monitor = RealTimeRiskMonitor(engine)
    assert monitor.kill_switch_triggered is False
    assert monitor.current_risk is None


def test_real_time_monitor_update_portfolio():
    engine = _make_engine_with_assets(n_sims=200)
    monitor = RealTimeRiskMonitor(engine)
    positions = {"XAUUSD": Decimal("1.0"), "EURUSD": Decimal("10000")}
    prices = {"XAUUSD": Decimal("1900"), "EURUSD": Decimal("1.08")}
    violations = monitor.update_portfolio(positions, prices)
    assert isinstance(violations, list)
    assert monitor.current_risk is not None


def test_real_time_monitor_no_violations_loose_limits():
    engine = _make_engine_with_assets(n_sims=200)
    monitor = RealTimeRiskMonitor(engine)
    monitor.limits = {
        "var_95_daily": -1.0,
        "cvar_95_daily": -1.0,
        "max_drawdown": -1.0,
        "tail_risk": 999.0,
    }
    positions = {"XAUUSD": Decimal("1.0"), "EURUSD": Decimal("10000")}
    prices = {"XAUUSD": Decimal("1900"), "EURUSD": Decimal("1.08")}
    violations = monitor.update_portfolio(positions, prices)
    assert violations == []
    assert not monitor.kill_switch_triggered


def test_real_time_monitor_triggers_kill_switch_on_breach():
    engine = _make_engine_with_assets(n_sims=200)
    monitor = RealTimeRiskMonitor(engine)
    monitor.limits = {
        "var_95_daily": 999.0,
        "cvar_95_daily": 999.0,
        "max_drawdown": 999.0,
        "tail_risk": -999.0,
    }
    positions = {"XAUUSD": Decimal("1.0"), "EURUSD": Decimal("10000")}
    prices = {"XAUUSD": Decimal("1900"), "EURUSD": Decimal("1.08")}
    violations = monitor.update_portfolio(positions, prices)
    assert len(violations) > 0
    assert monitor.kill_switch_triggered


def test_check_limits_no_current_risk():
    engine = _make_engine_with_assets(n_sims=200)
    monitor = RealTimeRiskMonitor(engine)
    assert monitor._check_limits() == []

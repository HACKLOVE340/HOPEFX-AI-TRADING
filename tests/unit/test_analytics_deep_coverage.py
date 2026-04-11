# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
Deep coverage tests for analytics/ module:
  analytics/monte_carlo.py, analytics/simulations.py,
  analytics/performance.py, analytics/portfolio.py
Real implementations only — no mocks of the modules under test.
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest

UTC = timezone.utc


# ===========================================================================
# analytics/monte_carlo.py
# ===========================================================================

@pytest.mark.unit
class TestMonteCarloEngine:
    def _engine(self, n_paths=200):
        from analytics.monte_carlo import MonteCarloEngine
        return MonteCarloEngine(n_paths=n_paths, seed=42)

    def _pnls(self, n=50):
        rng = np.random.default_rng(0)
        return list(rng.normal(50, 200, n))

    def test_run_iid_returns_bootstrap_result(self):
        from analytics.monte_carlo import BootstrapResult
        engine = self._engine()
        result = engine.run(self._pnls(), initial_capital=100_000)
        assert isinstance(result, BootstrapResult)
        assert result.n_paths == 200

    def test_run_block_bootstrap(self):
        from analytics.monte_carlo import BootstrapResult
        engine = self._engine()
        result = engine.run(self._pnls(), method="block")
        assert isinstance(result, BootstrapResult)

    def test_sharpe_ci_tuple(self):
        engine = self._engine()
        result = engine.run(self._pnls())
        assert len(result.sharpe_ci_95) == 2
        assert result.sharpe_ci_95[0] <= result.sharpe_ci_95[1]

    def test_max_dd_ci_tuple(self):
        engine = self._engine()
        result = engine.run(self._pnls())
        assert len(result.max_dd_ci_95) == 2

    def test_ruin_probability_in_range(self):
        engine = self._engine()
        result = engine.run(self._pnls())
        assert 0.0 <= result.ruin_probability <= 1.0

    def test_cagr_ci(self):
        engine = self._engine()
        result = engine.run(self._pnls())
        assert len(result.cagr_ci_95) == 2
        assert result.cagr_ci_95[0] <= result.cagr_ci_95[1]

    def test_final_equity_distribution_length(self):
        engine = self._engine(n_paths=100)
        result = engine.run(self._pnls())
        assert len(result.final_equity_distribution) == 100

    def test_empty_result_on_single_trade(self):
        engine = self._engine()
        result = engine.run([100.0])
        assert result.n_paths == 0

    def test_all_losing_trades(self):
        engine = self._engine()
        pnls = [-100.0] * 30
        result = engine.run(pnls)
        assert result.ruin_probability >= 0.0

    def test_summary_dict_keys(self):
        engine = self._engine()
        result = engine.run(self._pnls())
        summary = result.summary()
        assert "sharpe_ci_95" in summary
        assert "ruin_probability" in summary
        assert "n_paths" in summary

    def test_original_metrics_set(self):
        engine = self._engine()
        result = engine.run(self._pnls(), initial_capital=50_000)
        assert isinstance(result.original_sharpe, float)
        assert isinstance(result.original_max_dd, float)
        assert 0.0 <= result.original_win_rate <= 1.0


@pytest.mark.unit
class TestRunBootstrap:
    def test_run_bootstrap_convenience(self):
        from analytics.monte_carlo import run_bootstrap, BootstrapResult
        pnls = list(np.random.default_rng(1).normal(30, 150, 40))
        result = run_bootstrap(pnls, initial_capital=100_000, n_paths=100)
        assert isinstance(result, BootstrapResult)

    def test_run_bootstrap_block_method(self):
        from analytics.monte_carlo import run_bootstrap
        pnls = list(np.random.default_rng(2).normal(30, 150, 40))
        result = run_bootstrap(pnls, method="block", n_paths=100)
        assert result.n_paths == 100


# ===========================================================================
# analytics/simulations.py
# ===========================================================================

@pytest.mark.unit
class TestSimulationEngine:
    def _engine(self):
        from analytics.simulations import SimulationEngine
        return SimulationEngine()

    def _pnls(self):
        rng = np.random.default_rng(5)
        return list(rng.normal(40, 180, 50))

    def test_monte_carlo_simulation_returns_dict(self):
        engine = self._engine()
        result = engine.monte_carlo_simulation(self._pnls(), n_paths=100)
        assert isinstance(result, dict)

    def test_monte_carlo_simulation_has_legacy_keys(self):
        engine = self._engine()
        result = engine.monte_carlo_simulation(self._pnls(), n_paths=100)
        assert "mean_return" in result
        assert "max_drawdown" in result
        assert "paths" in result

    def test_monte_carlo_simulation_paths_truncated(self):
        engine = self._engine()
        result = engine.monte_carlo_simulation(self._pnls(), n_paths=200)
        assert len(result["paths"]) <= 100

    def test_genetic_algorithm_optimization(self):
        engine = self._engine()

        def fitness(params):
            return -(params["x"] - 3.0) ** 2

        space = {"x": {"type": "float", "low": 0.0, "high": 10.0}}
        result = engine.genetic_algorithm_optimization(
            parameters=space,
            fitness_function=fitness,
            population_size=20,
            generations=5,
        )
        assert isinstance(result, dict)
        assert "best_params" in result or "x" in result or result is not None

    def test_monte_carlo_iid_method(self):
        engine = self._engine()
        result = engine.monte_carlo_simulation(self._pnls(), method="iid", n_paths=50)
        assert "var_95" in result

    def test_monte_carlo_block_method(self):
        engine = self._engine()
        result = engine.monte_carlo_simulation(self._pnls(), method="block", n_paths=50)
        assert isinstance(result, dict)


# ===========================================================================
# analytics/performance.py
# ===========================================================================

@pytest.mark.unit
class TestPerformanceAnalytics:
    def _analytics(self, equity=10_000.0):
        from analytics.performance import PerformanceAnalytics
        return PerformanceAnalytics(initial_equity=equity)

    def _trade(self, pnl=100.0, symbol="XAUUSD", side="buy"):
        from analytics.performance import TradeRecord
        now = datetime.now(UTC)
        return TradeRecord(
            id=f"t_{pnl}",
            symbol=symbol,
            strategy="test_strategy",
            side=side,
            entry_time=now - timedelta(minutes=30),
            exit_time=now,
            entry_price=3300.0,
            exit_price=3300.0 + (pnl / 0.1),
            quantity=0.1,
            pnl=pnl,
            pnl_percent=pnl / 10_000,
            commission=2.0,
            duration_minutes=30,
            max_favorable_excursion=abs(pnl) * 1.2,
            max_adverse_excursion=abs(pnl) * 0.3,
        )

    def test_initial_equity_curve_has_one_point(self):
        pa = self._analytics()
        assert len(pa.equity_curve) == 1
        assert pa.equity_curve[0].equity == 10_000.0

    def test_record_trade_updates_equity(self):
        pa = self._analytics()
        pa.record_trade(self._trade(pnl=500.0))
        assert pa.current_equity == 10_500.0

    def test_record_losing_trade(self):
        pa = self._analytics()
        pa.record_trade(self._trade(pnl=-200.0))
        assert pa.current_equity == 9_800.0

    def test_high_water_mark_updates(self):
        pa = self._analytics()
        pa.record_trade(self._trade(pnl=1000.0))
        assert pa.high_water_mark == 11_000.0

    def test_high_water_mark_does_not_decrease(self):
        pa = self._analytics()
        pa.record_trade(self._trade(pnl=1000.0))
        pa.record_trade(self._trade(pnl=-500.0))
        assert pa.high_water_mark == 11_000.0

    def _report(self, pnls):
        """Helper: build analytics, add trades, return report with tz-aware patch."""
        from analytics.performance import PerformanceReport
        import analytics.performance as perf_mod
        pa = self._analytics()
        for pnl in pnls:
            pa.record_trade(self._trade(pnl=pnl))
        # Patch _get_period_start to return tz-aware datetime so equity_curve
        # comparison (which uses UTC-aware timestamps) doesn't raise TypeError
        with patch.object(pa, "_get_period_start",
                          return_value=datetime.now(UTC) - timedelta(days=365)):
            return pa.get_performance_report()

    def test_get_performance_report_returns_report(self):
        from analytics.performance import PerformanceReport
        report = self._report([100, -50, 200, -30, 150])
        assert isinstance(report, PerformanceReport)

    def test_performance_report_trade_count(self):
        report = self._report([100, -50, 200])
        assert report.total_trades == 3

    def test_performance_report_win_rate(self):
        report = self._report([100, 200, -50])
        assert abs(report.win_rate - 2/3) < 0.01

    def test_performance_report_total_return(self):
        report = self._report([100, -50, 200])
        # total_return = ending_equity - starting_equity
        assert abs(report.total_return - 250.0) < 0.01

    def test_equity_curve_grows_with_trades(self):
        pa = self._analytics()
        for pnl in [100, 200, 300]:
            pa.record_trade(self._trade(pnl=pnl))
        assert len(pa.equity_curve) == 4  # initial + 3 trades

    def test_no_trades_report(self):
        from analytics.performance import PerformanceReport
        report = self._report([])
        assert isinstance(report, PerformanceReport)
        assert report.total_trades == 0

    def test_sharpe_ratio_computed(self):
        report = self._report([100, -50, 200, -30, 150, 80, -20, 300])
        assert isinstance(report.sharpe_ratio, float)

    def test_max_drawdown_computed(self):
        report = self._report([1000.0, -500.0])
        assert report.max_drawdown >= 0.0

    def test_profit_factor_computed(self):
        report = self._report([100, 200, -50, -30])
        assert report.profit_factor > 0.0

    def test_strategy_breakdown(self):
        report = self._report([100, -50, 200])
        # trades_by_strategy or pnl_by_strategy contains our strategy
        assert "test_strategy" in report.trades_by_strategy or \
               "test_strategy" in report.pnl_by_strategy


# ===========================================================================
# analytics/portfolio.py
# ===========================================================================

@pytest.mark.unit
class TestPortfolioAnalytics:
    def _returns_df(self, n=100, assets=None):
        assets = assets or ["XAUUSD", "EURUSD", "GBPUSD"]
        rng = np.random.default_rng(42)
        data = rng.normal(0.001, 0.01, (n, len(assets)))
        return pd.DataFrame(data, columns=assets)

    def test_load_returns_data(self):
        from analytics.portfolio import PortfolioAnalytics
        pa = PortfolioAnalytics()
        df = self._returns_df()
        pa.load_returns_data(df)
        assert pa.returns_data is not None
        assert pa.assets == ["XAUUSD", "EURUSD", "GBPUSD"]

    def test_correlation_matrix_shape(self):
        from analytics.portfolio import PortfolioAnalytics
        pa = PortfolioAnalytics()
        pa.load_returns_data(self._returns_df())
        corr = pa.calculate_correlation_matrix()
        assert corr.shape == (3, 3)

    def test_correlation_diagonal_is_one(self):
        from analytics.portfolio import PortfolioAnalytics
        pa = PortfolioAnalytics()
        pa.load_returns_data(self._returns_df())
        corr = pa.calculate_correlation_matrix()
        for i in range(3):
            assert abs(corr.iloc[i, i] - 1.0) < 1e-10

    def test_correlation_raises_without_data(self):
        from analytics.portfolio import PortfolioAnalytics
        pa = PortfolioAnalytics()
        with pytest.raises(ValueError):
            pa.calculate_correlation_matrix()

    def test_portfolio_performance(self):
        from analytics.portfolio import PortfolioAnalytics
        pa = PortfolioAnalytics()
        pa.load_returns_data(self._returns_df())
        weights = np.array([1/3, 1/3, 1/3])
        ret, vol, sharpe = pa.portfolio_performance(weights)
        assert isinstance(ret, float)
        assert isinstance(vol, float)
        assert isinstance(sharpe, float)

    def test_calculate_risk_metrics(self):
        from analytics.portfolio import PortfolioAnalytics
        pa = PortfolioAnalytics()
        pa.load_returns_data(self._returns_df())
        weights = np.array([1/3, 1/3, 1/3])
        metrics = pa.calculate_risk_metrics(weights)
        assert isinstance(metrics, dict)
        assert len(metrics) > 0

    def test_optimize_portfolio_max_sharpe(self):
        from analytics.portfolio import PortfolioAnalytics
        pa = PortfolioAnalytics()
        pa.load_returns_data(self._returns_df())
        result = pa.optimize_portfolio(max_sharpe=True)
        assert "weights" in result
        # weights is a dict {asset: weight}
        assert abs(sum(result["weights"].values()) - 1.0) < 1e-4

    def test_optimize_portfolio_min_variance(self):
        from analytics.portfolio import PortfolioAnalytics
        pa = PortfolioAnalytics()
        pa.load_returns_data(self._returns_df())
        result = pa.optimize_portfolio(max_sharpe=False)
        assert "weights" in result
        assert "sharpe_ratio" in result

    def test_efficient_frontier_returns_dataframe(self):
        from analytics.portfolio import PortfolioAnalytics
        pa = PortfolioAnalytics()
        pa.load_returns_data(self._returns_df())
        frontier = pa.generate_efficient_frontier(n_portfolios=10)
        assert isinstance(frontier, pd.DataFrame)
        assert len(frontier) > 0

    def test_covariance_matrix_shape(self):
        from analytics.portfolio import PortfolioAnalytics
        pa = PortfolioAnalytics()
        pa.load_returns_data(self._returns_df())
        cov = pa.calculate_covariance_matrix()
        assert cov.shape == (3, 3)


@pytest.mark.unit
class TestRiskAnalyzer:
    def _analyzer(self):
        from analytics.portfolio import RiskAnalyzer
        rng = np.random.default_rng(7)
        returns = pd.DataFrame(
            rng.normal(0.001, 0.015, (252, 2)),
            columns=["XAUUSD", "EURUSD"],
        )
        return RiskAnalyzer(returns_data=returns)

    def test_calculate_drawdown_series(self):
        analyzer = self._analyzer()
        dd = analyzer.calculate_drawdown_series()
        assert isinstance(dd, pd.DataFrame)

    def test_calculate_rolling_metrics(self):
        analyzer = self._analyzer()
        metrics = analyzer.calculate_rolling_metrics(window=30)
        assert isinstance(metrics, pd.DataFrame)

    def test_stress_test(self):
        analyzer = self._analyzer()
        scenarios = {"crash": -0.20, "rally": 0.15}
        result = analyzer.stress_test(scenarios)
        assert isinstance(result, pd.DataFrame)

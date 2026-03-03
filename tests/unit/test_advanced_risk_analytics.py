"""
Comprehensive tests for Advanced Risk Analytics module.

Tests VaR calculations, Monte Carlo simulations, stress testing,
drawdown analysis, and risk-adjusted performance metrics.
"""

import pytest
import numpy as np
from datetime import datetime


def _make_returns(n: int = 500, seed: int = 42, mean: float = 0.0005, std: float = 0.01):
    """Create realistic daily returns array."""
    np.random.seed(seed)
    return np.random.normal(mean, std, n)


def _make_equity_curve(returns: np.ndarray, start: float = 10000.0) -> np.ndarray:
    """Build equity curve from returns."""
    return start * np.cumprod(1 + returns)


class TestRiskMetricType:
    """Tests for RiskMetricType enum."""

    def test_all_values(self):
        from risk.advanced_analytics import RiskMetricType
        assert RiskMetricType.VAR_HISTORICAL.value == "var_historical"
        assert RiskMetricType.VAR_PARAMETRIC.value == "var_parametric"
        assert RiskMetricType.VAR_MONTE_CARLO.value == "var_monte_carlo"
        assert RiskMetricType.CVAR.value == "cvar"
        assert RiskMetricType.MAX_DRAWDOWN.value == "max_drawdown"
        assert RiskMetricType.SHARPE_RATIO.value == "sharpe_ratio"
        assert RiskMetricType.SORTINO_RATIO.value == "sortino_ratio"
        assert RiskMetricType.CALMAR_RATIO.value == "calmar_ratio"


class TestVaRResult:
    """Tests for VaRResult dataclass."""

    def test_to_dict(self):
        from risk.advanced_analytics import VaRResult
        result = VaRResult(
            var_value=1000.0,
            confidence_level=0.95,
            time_horizon=1,
            method='historical'
        )
        d = result.to_dict()
        assert d['var_value'] == 1000.0
        assert d['confidence_level'] == 0.95
        assert d['time_horizon'] == 1
        assert d['method'] == 'historical'
        assert 'timestamp' in d


class TestMonteCarloResult:
    """Tests for MonteCarloResult dataclass."""

    def test_to_dict(self):
        from risk.advanced_analytics import MonteCarloResult
        result = MonteCarloResult(
            expected_return=0.05,
            expected_volatility=0.15,
            var_95=0.02,
            var_99=0.03,
            cvar_95=0.025,
            max_gain=0.50,
            max_loss=-0.30,
            num_simulations=1000
        )
        d = result.to_dict()
        assert d['expected_return'] == 0.05
        assert d['var_95'] == 0.02
        assert d['num_simulations'] == 1000
        assert 'timestamp' in d


class TestAdvancedRiskAnalytics:
    """Tests for AdvancedRiskAnalytics class."""

    @pytest.fixture
    def analytics(self):
        from risk.advanced_analytics import AdvancedRiskAnalytics
        return AdvancedRiskAnalytics()

    @pytest.fixture
    def analytics_custom(self):
        from risk.advanced_analytics import AdvancedRiskAnalytics
        return AdvancedRiskAnalytics(config={
            'var_confidence': 0.99,
            'mc_simulations': 500,
            'risk_free_rate': 0.03
        })

    @pytest.fixture
    def returns(self):
        return _make_returns()

    @pytest.fixture
    def equity_curve(self, returns):
        return _make_equity_curve(returns)

    def test_initialization_defaults(self, analytics):
        assert analytics.var_confidence == 0.95
        assert analytics.mc_simulations == 10000
        assert analytics.risk_free_rate == 0.05

    def test_initialization_custom_config(self, analytics_custom):
        assert analytics_custom.var_confidence == 0.99
        assert analytics_custom.mc_simulations == 500
        assert analytics_custom.risk_free_rate == 0.03

    def test_stress_scenarios_initialized(self, analytics):
        scenarios = analytics.stress_scenarios
        assert 'market_crash_2008' in scenarios
        assert 'flash_crash' in scenarios
        assert 'rate_hike_shock' in scenarios
        assert 'geopolitical_crisis' in scenarios
        assert 'crypto_winter' in scenarios
        assert 'dollar_collapse' in scenarios
        assert 'best_case' in scenarios

    # ----- VaR Tests -----

    def test_calculate_var_historical_basic(self, analytics, returns):
        from risk.advanced_analytics import VaRResult
        result = analytics.calculate_var_historical(returns)
        assert isinstance(result, VaRResult)
        assert result.var_value > 0
        assert result.confidence_level == 0.95
        assert result.time_horizon == 1
        assert result.method == 'historical'

    def test_calculate_var_historical_with_portfolio_value(self, analytics, returns):
        result = analytics.calculate_var_historical(returns, portfolio_value=100000)
        assert result.var_value > 1  # Should be dollar value, not percentage

    def test_calculate_var_historical_custom_confidence(self, analytics, returns):
        result_95 = analytics.calculate_var_historical(returns, confidence_level=0.95)
        result_99 = analytics.calculate_var_historical(returns, confidence_level=0.99)
        assert result_99.var_value >= result_95.var_value

    def test_calculate_var_historical_multi_day(self, analytics, returns):
        result_1d = analytics.calculate_var_historical(returns, time_horizon=1)
        result_10d = analytics.calculate_var_historical(returns, time_horizon=10)
        assert result_10d.var_value > result_1d.var_value

    def test_calculate_var_parametric_basic(self, analytics, returns):
        from risk.advanced_analytics import VaRResult
        result = analytics.calculate_var_parametric(returns)
        assert isinstance(result, VaRResult)
        assert result.var_value > 0
        assert result.method == 'parametric'

    def test_calculate_var_parametric_with_portfolio_value(self, analytics, returns):
        result = analytics.calculate_var_parametric(returns, portfolio_value=50000)
        assert result.var_value > 1

    def test_calculate_var_parametric_custom_confidence(self, analytics, returns):
        result_95 = analytics.calculate_var_parametric(returns, confidence_level=0.95)
        result_99 = analytics.calculate_var_parametric(returns, confidence_level=0.99)
        assert result_99.var_value >= result_95.var_value

    def test_calculate_var_monte_carlo_basic(self, analytics, returns):
        from risk.advanced_analytics import VaRResult
        result = analytics.calculate_var_monte_carlo(returns, num_simulations=1000)
        assert isinstance(result, VaRResult)
        assert result.var_value > 0
        assert result.method == 'monte_carlo'

    def test_calculate_var_monte_carlo_with_portfolio_value(self, analytics, returns):
        result = analytics.calculate_var_monte_carlo(
            returns, portfolio_value=100000, num_simulations=500
        )
        assert result.var_value > 1

    def test_calculate_var_monte_carlo_multi_day(self, analytics, returns):
        result_1d = analytics.calculate_var_monte_carlo(returns, time_horizon=1, num_simulations=500)
        result_5d = analytics.calculate_var_monte_carlo(returns, time_horizon=5, num_simulations=500)
        assert result_5d.var_value > result_1d.var_value

    def test_calculate_cvar_basic(self, analytics, returns):
        cvar = analytics.calculate_cvar(returns)
        assert isinstance(cvar, float)
        assert cvar > 0

    def test_calculate_cvar_with_portfolio_value(self, analytics, returns):
        cvar = analytics.calculate_cvar(returns, portfolio_value=100000)
        assert cvar > 1

    def test_calculate_cvar_custom_confidence(self, analytics, returns):
        cvar_95 = analytics.calculate_cvar(returns, confidence_level=0.95)
        cvar_99 = analytics.calculate_cvar(returns, confidence_level=0.99)
        assert cvar_99 >= cvar_95

    def test_cvar_with_no_tail_returns(self, analytics):
        # All positive returns - tail might be empty
        positive_returns = np.abs(_make_returns()) + 0.05
        cvar = analytics.calculate_cvar(positive_returns, confidence_level=0.99)
        assert isinstance(cvar, float)
        assert cvar >= 0

    # ----- Monte Carlo Simulation -----

    def test_run_monte_carlo_simulation_basic(self, analytics):
        from risk.advanced_analytics import MonteCarloResult
        result = analytics.run_monte_carlo_simulation(
            initial_value=10000,
            expected_return=0.10,
            volatility=0.20,
            time_horizon=252,
            num_simulations=500
        )
        assert isinstance(result, MonteCarloResult)
        assert result.num_simulations == 500
        assert result.max_gain > result.max_loss
        assert 0 < result.var_95

    def test_run_monte_carlo_with_paths(self, analytics):
        result = analytics.run_monte_carlo_simulation(
            initial_value=10000,
            expected_return=0.10,
            volatility=0.20,
            time_horizon=30,
            num_simulations=100,
            return_paths=True
        )
        assert result.simulated_paths is not None
        assert result.simulated_paths.shape[0] == 100

    def test_run_monte_carlo_without_paths(self, analytics):
        result = analytics.run_monte_carlo_simulation(
            initial_value=10000,
            expected_return=0.10,
            volatility=0.20,
            num_simulations=100,
            return_paths=False
        )
        assert result.simulated_paths is None

    def test_simulate_portfolio_scenarios_basic(self, analytics):
        positions = {
            'stock_a': {'value': 50000, 'expected_return': 0.10, 'volatility': 0.20, 'asset_class': 'equities'},
            'gold': {'value': 20000, 'expected_return': 0.05, 'volatility': 0.15, 'asset_class': 'gold'},
        }
        result = analytics.simulate_portfolio_scenarios(
            positions, time_horizon=30, num_simulations=200
        )
        assert 'initial_value' in result
        assert result['initial_value'] == 70000
        assert 'expected_final_value' in result
        assert 'var_95' in result
        assert 'probability_loss' in result
        assert 0 <= result['probability_loss'] <= 1

    def test_simulate_portfolio_with_correlation(self, analytics):
        positions = {
            'a': {'value': 50000, 'expected_return': 0.10, 'volatility': 0.20},
            'b': {'value': 30000, 'expected_return': 0.08, 'volatility': 0.15},
        }
        correlations = np.array([[1.0, 0.5], [0.5, 1.0]])
        result = analytics.simulate_portfolio_scenarios(
            positions, correlations=correlations, time_horizon=10, num_simulations=100
        )
        assert 'expected_return' in result

    # ----- Stress Testing -----

    def test_run_stress_test_market_crash(self, analytics):
        from risk.advanced_analytics import StressTestResult
        portfolio = {
            'equities': {'value': 50000, 'asset_class': 'equities'},
            'crypto': {'value': 10000, 'asset_class': 'crypto'},
            'bonds': {'value': 20000, 'asset_class': 'bonds'},
        }
        result = analytics.run_stress_test(portfolio, 'market_crash_2008')
        assert isinstance(result, StressTestResult)
        assert result.portfolio_impact < 0  # Market crash = negative
        assert result.dollar_impact < 0
        assert result.risk_level in ('low', 'medium', 'high', 'severe')
        assert len(result.recommendation) > 0

    def test_run_stress_test_best_case(self, analytics):
        portfolio = {
            'equities': {'value': 100000, 'asset_class': 'equities'},
        }
        result = analytics.run_stress_test(portfolio, 'best_case')
        assert result.portfolio_impact > 0
        assert result.risk_level in ('low', 'medium', 'high', 'severe')

    def test_run_stress_test_unknown_scenario(self, analytics):
        portfolio = {'pos': {'value': 100000, 'asset_class': 'equities'}}
        with pytest.raises(ValueError, match="Unknown scenario"):
            analytics.run_stress_test(portfolio, 'nonexistent_scenario')

    def test_run_stress_test_flash_crash(self, analytics):
        portfolio = {'gold': {'value': 30000, 'asset_class': 'gold'}}
        result = analytics.run_stress_test(portfolio, 'flash_crash')
        assert result.risk_level in ('low', 'medium', 'high', 'severe')

    def test_run_stress_test_geopolitical(self, analytics):
        portfolio = {'equities': {'value': 80000, 'asset_class': 'equities'}}
        result = analytics.run_stress_test(portfolio, 'geopolitical_crisis')
        assert result.risk_level in ('low', 'medium', 'high', 'severe')

    def test_run_stress_test_dollar_collapse(self, analytics):
        portfolio = {'forex': {'value': 60000, 'asset_class': 'forex'}}
        result = analytics.run_stress_test(portfolio, 'dollar_collapse')
        assert result.portfolio_impact > 0  # Gold/forex benefit

    def test_run_stress_test_rate_hike(self, analytics):
        portfolio = {'bonds': {'value': 100000, 'asset_class': 'bonds'}}
        result = analytics.run_stress_test(portfolio, 'rate_hike_shock')
        assert result.risk_level in ('low', 'medium', 'high', 'severe')

    def test_run_stress_test_crypto_winter(self, analytics):
        portfolio = {
            'crypto': {'value': 100000, 'asset_class': 'crypto'},
        }
        result = analytics.run_stress_test(portfolio, 'crypto_winter')
        assert result.risk_level == 'severe'  # -80% impact

    def test_run_stress_test_medium_risk(self, analytics):
        portfolio = {
            'equities': {'value': 100000, 'asset_class': 'equities'},
        }
        result = analytics.run_stress_test(portfolio, 'geopolitical_crisis')
        assert result.risk_level in ('medium', 'high')

    def test_run_stress_test_high_risk(self, analytics):
        portfolio = {
            'equities': {'value': 100000, 'asset_class': 'equities'},
        }
        result = analytics.run_stress_test(portfolio, 'market_crash_2008')
        assert result.risk_level in ('high', 'severe')

    def test_run_all_stress_tests(self, analytics):
        portfolio = {
            'equities': {'value': 50000, 'asset_class': 'equities'},
            'gold': {'value': 20000, 'asset_class': 'gold'},
        }
        results = analytics.run_all_stress_tests(portfolio)
        assert len(results) == len(analytics.stress_scenarios)
        for result in results:
            assert hasattr(result, 'scenario_name')
            assert hasattr(result, 'risk_level')

    def test_run_stress_test_empty_portfolio(self, analytics):
        portfolio = {}
        result = analytics.run_stress_test(portfolio, 'flash_crash')
        assert result.portfolio_impact == 0

    # ----- Drawdown Analysis -----

    def test_analyze_drawdowns_basic(self, analytics, equity_curve):
        from risk.advanced_analytics import DrawdownAnalysis
        result = analytics.analyze_drawdowns(equity_curve)
        assert isinstance(result, DrawdownAnalysis)
        assert result.max_drawdown <= 0
        assert result.current_drawdown <= 0
        assert result.max_drawdown_duration >= 0
        assert 0 <= result.recovery_rate <= 1

    def test_analyze_drawdowns_flat_curve(self, analytics):
        equity_curve = np.ones(100) * 10000
        result = analytics.analyze_drawdowns(equity_curve)
        assert result.max_drawdown == 0.0
        assert result.recovery_rate == 1.0

    def test_analyze_drawdowns_trending_up(self, analytics):
        equity_curve = np.linspace(10000, 20000, 200)
        result = analytics.analyze_drawdowns(equity_curve)
        assert result.max_drawdown == 0.0

    def test_analyze_drawdowns_big_crash(self, analytics):
        # Crash then recovery
        up = np.linspace(10000, 20000, 100)
        down = np.linspace(20000, 12000, 50)
        recovery = np.linspace(12000, 22000, 100)
        equity_curve = np.concatenate([up, down, recovery])
        result = analytics.analyze_drawdowns(equity_curve)
        assert result.max_drawdown < -0.20  # More than 20% drawdown
        assert result.recovery_rate >= 0.0

    def test_identify_drawdown_events(self, analytics):
        # Build drawdown array with clear event
        drawdown = np.array([0, 0, -0.06, -0.10, -0.08, -0.03, 0, 0])
        events = analytics._identify_drawdown_events(drawdown, threshold=-0.05)
        assert len(events) >= 1
        assert events[0]['recovered'] is True

    def test_identify_drawdown_events_ongoing(self, analytics):
        # Drawdown that doesn't recover
        drawdown = np.array([0, 0, -0.06, -0.10, -0.12])
        events = analytics._identify_drawdown_events(drawdown, threshold=-0.05)
        assert len(events) >= 1
        assert events[-1]['recovered'] is False

    def test_calculate_recovery_rate_empty(self, analytics):
        rate = analytics._calculate_recovery_rate([])
        assert rate == 1.0

    def test_calculate_recovery_rate_all_recovered(self, analytics):
        events = [
            {'recovered': True},
            {'recovered': True},
        ]
        rate = analytics._calculate_recovery_rate(events)
        assert rate == 1.0

    def test_calculate_recovery_rate_mixed(self, analytics):
        events = [
            {'recovered': True},
            {'recovered': False},
        ]
        rate = analytics._calculate_recovery_rate(events)
        assert rate == 0.5

    def test_calculate_underwater_periods(self, analytics):
        drawdown = np.array([0, -0.05, -0.10, 0, 0, -0.03, 0])
        periods = analytics._calculate_underwater_periods(drawdown)
        assert len(periods) == 2

    def test_calculate_underwater_ongoing(self, analytics):
        drawdown = np.array([0, 0, -0.05, -0.10])
        periods = analytics._calculate_underwater_periods(drawdown)
        assert len(periods) == 1
        assert periods[0]['duration'] == 2

    # ----- Risk-Adjusted Metrics -----

    def test_calculate_sharpe_ratio_basic(self, analytics, returns):
        sharpe = analytics.calculate_sharpe_ratio(returns)
        assert isinstance(sharpe, float)

    def test_calculate_sharpe_ratio_zero_std(self, analytics):
        constant_returns = np.zeros(100)
        sharpe = analytics.calculate_sharpe_ratio(constant_returns)
        assert sharpe == 0.0

    def test_calculate_sortino_ratio_basic(self, analytics, returns):
        sortino = analytics.calculate_sortino_ratio(returns)
        assert isinstance(sortino, float)

    def test_calculate_sortino_ratio_all_positive_returns_inf(self, analytics):
        """When there are no downside returns, Sortino ratio is infinite."""
        positive_returns = np.abs(_make_returns()) + 0.001
        sortino = analytics.calculate_sortino_ratio(positive_returns)
        assert sortino == float('inf') or sortino > 0

    def test_calculate_sortino_ratio_negative_mean(self, analytics):
        bad_returns = _make_returns(mean=-0.001)
        sortino = analytics.calculate_sortino_ratio(bad_returns)
        assert sortino == 0.0 or sortino < 0

    def test_calculate_calmar_ratio_basic(self, analytics, returns, equity_curve):
        calmar = analytics.calculate_calmar_ratio(returns, equity_curve=equity_curve)
        assert isinstance(calmar, float)

    def test_calculate_calmar_ratio_no_equity_curve(self, analytics, returns):
        calmar = analytics.calculate_calmar_ratio(returns)
        assert isinstance(calmar, float)

    def test_calculate_calmar_ratio_zero_drawdown(self, analytics):
        uptrend_returns = np.abs(_make_returns()) + 0.002
        calmar = analytics.calculate_calmar_ratio(uptrend_returns)
        assert calmar == float('inf') or calmar > 0

    # ----- Full Metrics Suite -----

    def test_calculate_all_metrics_basic(self, analytics, returns):
        metrics = analytics.calculate_all_metrics(returns)
        required_keys = [
            'var_historical_95', 'var_parametric_95', 'var_monte_carlo_95',
            'cvar_95', 'max_drawdown', 'sharpe_ratio', 'sortino_ratio',
            'calmar_ratio', 'total_return', 'annual_return',
            'annual_volatility', 'positive_days', 'recovery_rate'
        ]
        for key in required_keys:
            assert key in metrics, f"Missing key: {key}"

    def test_calculate_all_metrics_with_portfolio_value(self, analytics, returns):
        metrics = analytics.calculate_all_metrics(returns, portfolio_value=100000)
        assert metrics['var_historical_95'] > 1  # Dollar value

    def test_calculate_all_metrics_with_equity_curve(self, analytics, returns, equity_curve):
        metrics = analytics.calculate_all_metrics(returns, equity_curve=equity_curve)
        assert 'total_return' in metrics

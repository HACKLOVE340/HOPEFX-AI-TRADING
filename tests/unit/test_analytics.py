# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
Tests for the analytics module.
"""

import numpy as np

from analytics.portfolio import PortfolioOptimizer
from analytics.risk import RiskAnalyzer
from analytics.simulations import SimulationEngine
from analytics.options import OptionsAnalyzer


class TestPortfolioOptimizer:
    """Tests for PortfolioOptimizer class."""

    def test_portfolio_optimizer_initialization(self):
        """Test PortfolioOptimizer can be initialized."""
        optimizer = PortfolioOptimizer()
        assert optimizer is not None

    def test_optimize_portfolio_basic(self):
        """Test basic portfolio optimization."""
        optimizer = PortfolioOptimizer()

        assets = ["AAPL", "GOOGL", "MSFT", "AMZN"]
        returns = np.random.randn(100, 4) * 0.02  # 100 days, 4 assets

        result = optimizer.optimize_portfolio(assets, returns)

        assert "weights" in result
        assert "expected_return" in result
        assert "risk" in result
        assert "sharpe_ratio" in result

        # Weights should sum to approximately 1
        total_weight = sum(result["weights"].values())
        assert abs(total_weight - 1.0) < 0.01

    def test_optimize_portfolio_with_method(self):
        """Test portfolio optimization with specific method."""
        optimizer = PortfolioOptimizer()

        assets = ["BTC", "ETH"]
        returns = np.random.randn(50, 2) * 0.05

        result = optimizer.optimize_portfolio(assets, returns, method="max_sharpe")

        assert result["method"] == "max_sharpe"

    def test_efficient_frontier(self):
        """Test efficient frontier calculation."""
        optimizer = PortfolioOptimizer()

        assets = ["A", "B", "C"]
        returns = np.random.randn(200, 3) * 0.01

        frontier = optimizer.efficient_frontier(assets, returns, num_portfolios=50)

        assert len(frontier) == 50
        assert all("risk" in p and "return" in p for p in frontier)


class TestRiskAnalyzer:
    """Tests for RiskAnalyzer class."""

    def test_risk_analyzer_initialization(self):
        """Test RiskAnalyzer can be initialized."""
        analyzer = RiskAnalyzer()
        assert analyzer is not None

    def test_calculate_var_historical(self):
        """Test historical VaR calculation."""
        analyzer = RiskAnalyzer()

        # Generate returns with some negative values
        np.random.seed(42)
        returns = list(np.random.randn(100) * 0.02)

        var_95 = analyzer.calculate_var(returns, confidence_level=0.95, method="historical")

        assert isinstance(var_95, float | np.floating)
        assert var_95 < 0  # VaR should be negative for losses

    def test_calculate_var_parametric(self):
        """Test parametric VaR calculation."""
        analyzer = RiskAnalyzer()

        np.random.seed(42)
        returns = list(np.random.randn(100) * 0.02)

        var_95 = analyzer.calculate_var(returns, confidence_level=0.95, method="parametric")

        assert isinstance(var_95, float | np.floating)

    def test_calculate_cvar(self):
        """Test CVaR (Expected Shortfall) calculation."""
        analyzer = RiskAnalyzer()

        np.random.seed(42)
        returns = list(np.random.randn(100) * 0.02)

        cvar = analyzer.calculate_cvar(returns, confidence_level=0.95)
        var = analyzer.calculate_var(returns, confidence_level=0.95, method="historical")

        # CVaR should be at least as negative as VaR (worse case)
        assert cvar <= var

    def test_risk_attribution(self):
        """Test risk attribution calculation."""
        analyzer = RiskAnalyzer()

        weights = np.array([0.4, 0.3, 0.3])
        # Simple covariance matrix
        cov_matrix = np.array([[0.04, 0.01, 0.01], [0.01, 0.02, 0.005], [0.01, 0.005, 0.03]])

        result = analyzer.risk_attribution(weights, cov_matrix)

        assert "total_risk" in result
        assert "marginal_risk" in result
        assert "component_risk" in result
        assert result["total_risk"] > 0


class TestSimulationEngine:
    """Tests for SimulationEngine class."""

    def test_simulation_engine_initialization(self):
        """Test SimulationEngine can be initialized."""
        engine = SimulationEngine()
        assert engine is not None

    def test_monte_carlo_simulation_basic(self):
        """Test basic Monte Carlo simulation."""
        engine = SimulationEngine()

        # Provide a realistic trade P&L sequence (100 trades, small random returns)
        import numpy as np

        rng = np.random.default_rng(42)
        trade_pnls = list(rng.normal(50, 200, 100).tolist())

        result = engine.monte_carlo_simulation(
            trade_pnls=trade_pnls,
            initial_capital=100_000.0,
            n_paths=1000,
        )

        assert "mean_return" in result
        assert "std_dev" in result
        assert "var_95" in result
        assert "var_99" in result
        assert "paths" in result
        # paths is truncated to 100 entries max
        assert len(result["paths"]) <= 1000

    def test_monte_carlo_simulation_statistics(self):
        """Test Monte Carlo simulation statistics are reasonable."""
        engine = SimulationEngine()

        import numpy as np

        rng = np.random.default_rng(7)
        trade_pnls = list(rng.normal(100, 500, 200).tolist())

        result = engine.monte_carlo_simulation(
            trade_pnls=trade_pnls,
            initial_capital=100_000.0,
            n_paths=500,
        )

        # Standard deviation should be non-negative
        assert result["std_dev"] >= 0

        # var_95 and var_99 are equity confidence-interval bounds — both present
        assert "var_95" in result
        assert "var_99" in result

    def test_genetic_algorithm_optimization(self):
        """Test genetic algorithm optimization."""
        engine = SimulationEngine()

        parameters = {"param1": 10, "param2": 20}

        def fitness_func(x):
            return x["param1"] + x["param2"]

        result = engine.genetic_algorithm_optimization(
            parameters=parameters,
            fitness_function=fitness_func,
            population_size=50,
            generations=20,
        )

        assert "best_parameters" in result
        assert "fitness_score" in result
        assert "generations" in result
        assert result["generations"] == 20
        assert result["fitness_score"] >= 0


class TestOptionsAnalyzer:
    """Tests for OptionsAnalyzer class."""

    def test_options_analyzer_initialization(self):
        """Test OptionsAnalyzer can be initialized."""
        analyzer = OptionsAnalyzer()
        assert analyzer is not None

    def test_price_call_option(self):
        """Test call option pricing."""
        analyzer = OptionsAnalyzer()

        price = analyzer.price_option(
            option_type="call",
            spot_price=100.0,
            strike_price=100.0,
            time_to_expiry=1.0,
            volatility=0.20,
        )

        assert isinstance(price, float)
        assert price > 0  # Option should have positive value

    def test_price_put_option(self):
        """Test put option pricing."""
        analyzer = OptionsAnalyzer()

        price = analyzer.price_option(
            option_type="put",
            spot_price=100.0,
            strike_price=100.0,
            time_to_expiry=1.0,
            volatility=0.20,
        )

        assert isinstance(price, float)
        assert price > 0  # Option should have positive value

    def test_call_price_increases_with_volatility(self):
        """Test that call option price increases with volatility."""
        analyzer = OptionsAnalyzer()

        price_low_vol = analyzer.price_option(
            option_type="call",
            spot_price=100.0,
            strike_price=100.0,
            time_to_expiry=1.0,
            volatility=0.10,
        )

        price_high_vol = analyzer.price_option(
            option_type="call",
            spot_price=100.0,
            strike_price=100.0,
            time_to_expiry=1.0,
            volatility=0.30,
        )

        assert price_high_vol > price_low_vol

    def test_calculate_greeks(self):
        """Test Greeks calculation."""
        analyzer = OptionsAnalyzer()

        greeks = analyzer.calculate_greeks(
            option_type="call",
            spot_price=100.0,
            strike_price=100.0,
            time_to_expiry=1.0,
            volatility=0.20,
        )

        assert "delta" in greeks
        assert "gamma" in greeks
        assert "theta" in greeks
        assert "vega" in greeks
        assert "rho" in greeks

    def test_norm_cdf(self):
        """Test normal CDF calculation."""
        analyzer = OptionsAnalyzer()

        # CDF(0) should be 0.5
        assert abs(analyzer._norm_cdf(0) - 0.5) < 0.001

        # CDF(-infinity) should approach 0
        assert analyzer._norm_cdf(-10) < 0.001

        # CDF(+infinity) should approach 1
        assert analyzer._norm_cdf(10) > 0.999

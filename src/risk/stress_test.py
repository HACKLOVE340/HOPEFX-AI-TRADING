"""
Advanced stress testing with regime-switching models and tail risk analysis.
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import Literal, Callable

import numpy as np
import pandas as pd
from scipy import stats
from scipy.optimize import minimize

from src.core.logging_config import get_logger

logger = get_logger(__name__)


@dataclass
class StressScenario:
    """Enhanced stress scenario with conditional probabilities."""
    name: str
    description: str
    shock_type: Literal["absolute", "relative", "volatility_spike", "correlation_breakdown", "liquidity_crisis"]
    shock_magnitude: float
    affected_assets: list[str]
    duration_days: int
    probability: float = 0.01  # Base probability
    conditional_on: list[str] | None = None  # Conditional scenarios
    volatility_multiplier: float = 1.0


@dataclass
class Regime:
    """Market regime definition for regime-switching models."""
    name: str
    mean_return: float
    volatility: float
    persistence: float  # Probability of staying in regime
    tail_factor: float  # Tail thickness multiplier


class RegimeSwitchingModel:
    """
    Hamilton (1989) style regime-switching model for stress testing.
    Captures non-linear dynamics and state-dependent volatility.
    """
    
    def __init__(self, regimes: list[Regime] | None = None):
        self.regimes = regimes or self._default_regimes()
        self.current_regime = 0
        self.transition_matrix = self._build_transition_matrix()
        self._regime_history: list[int] = []
    
    def _default_regimes(self) -> list[Regime]:
        """Default market regimes."""
        return [
            Regime(
                name="normal",
                mean_return=0.0002,
                volatility=0.01,
                persistence=0.95,
                tail_factor=1.0
            ),
            Regime(
                name="stressed",
                mean_return=-0.001,
                volatility=0.03,
                persistence=0.90,
                tail_factor=2.0  # Fatter tails
            ),
            Regime(
                name="crisis",
                mean_return=-0.005,
                volatility=0.06,
                persistence=0.85,
                tail_factor=4.0  # Extreme tails
            ),
        ]
    
    def _build_transition_matrix(self) -> np.ndarray:
        """Build regime transition probability matrix."""
        n = len(self.regimes)
        P = np.zeros((n, n))
        
        for i, regime in enumerate(self.regimes):
            P[i, i] = regime.persistence
            # Equal probability to switch to other regimes
            remaining = 1 - regime.persistence
            for j in range(n):
                if i != j:
                    P[i, j] = remaining / (n - 1)
        
        return P
    
    def simulate(self, n_days: int, n_paths: int = 1000) -> np.ndarray:
        """
        Simulate returns with regime switching.
        
        Returns:
            Array of shape (n_paths, n_days) with simulated returns
        """
        results = np.zeros((n_paths, n_days))
        
        for path in range(n_paths):
            regime = self.current_regime
            
            for day in range(n_days):
                # Possibly switch regime
                if np.random.random() > self.regimes[regime].persistence:
                    # Switch to another regime
                    probs = self.transition_matrix[regime].copy()
                    probs[regime] = 0  # Can't stay
                    probs = probs / probs.sum()
                    regime = np.random.choice(len(self.regimes), p=probs)
                
                # Generate return from regime distribution
                r = self.regimes[regime]
                
                # Student-t with regime-dependent tails
                df = 5 / r.tail_factor  # Lower df = fatter tails
                ret = np.random.standard_t(df) * r.volatility + r.mean_return
                
                results[path, day] = ret
        
        return results
    
    def estimate_regime(self, recent_returns: np.ndarray) -> int:
        """
        Estimate current regime using filtered probabilities.
        """
        # Simplified - would use Hamilton filter in production
        vol = np.std(recent_returns)
        
        if vol > 0.05:
            return 2  # Crisis
        elif vol > 0.02:
            return 1  # Stressed
        else:
            return 0  # Normal


class CopulaStressModel:
    """
    Vine copula-based stress testing for non-linear dependencies.
    Captures tail dependencies that correlation matrices miss.
    """
    
    def __init__(self, assets: list[str]):
        self.assets = assets
        self.n = len(assets)
        self.copula_params: dict | None = None
    
    def fit(self, returns: pd.DataFrame) -> None:
        """
        Fit vine copula to historical returns.
        Uses pair-copula construction.
        """
        # Transform to uniform marginals
        uniform_data = returns.apply(
            lambda x: stats.rankdata(x) / (len(x) + 1)
        )
        
        # Estimate pair copulas (simplified - would use pyvinecopulib)
        self.copula_params = {
            "families": ["t"] * (self.n * (self.n - 1) // 2),
            "parameters": self._estimate_parameters(uniform_data)
        }
        
        logger.info(f"Fitted copula with {len(self.copula_params['families'])} pair copulas")
    
    def _estimate_parameters(self, uniform_data: pd.DataFrame) -> list:
        """Estimate copula parameters."""
        params = []
        for i in range(self.n):
            for j in range(i + 1, self.n):
                # Fit t-copula parameter (rho, nu)
                u = uniform_data.iloc[:, i]
                v = uniform_data.iloc[:, j]
                
                # Simple correlation estimate
                rho = np.corrcoef(
                    stats.norm.ppf(u),
                    stats.norm.ppf(v)
                )[0, 1]
                
                # Tail dependence parameter
                nu = 4.0  # Degrees of freedom
                
                params.append({"rho": rho, "nu": nu})
        
        return params
    
    def simulate_stress(
        self,
        n_sims: int = 10000,
        conditional_asset: str | None = None,
        conditional_shock: float | None = None
    ) -> pd.DataFrame:
        """
        Simulate correlated shocks with tail dependencies.
        
        If conditional_asset and conditional_shock provided,
        simulates conditional on that asset experiencing shock.
        """
        # Generate uniform samples from copula
        if conditional_asset and conditional_shock is not None:
            # Conditional simulation
            samples = self._conditional_simulate(
                conditional_asset,
                conditional_shock,
                n_sims
            )
        else:
            # Unconditional simulation
            samples = self._unconditional_simulate(n_sims)
        
        # Transform to returns using fitted marginals
        returns = pd.DataFrame(
            samples,
            columns=self.assets
        )
        
        return returns
    
    def _unconditional_simulate(self, n_sims: int) -> np.ndarray:
        """Unconditional copula simulation."""
        # Simplified t-copula simulation
        # Generate multivariate t
        corr = np.eye(self.n) * 0.8 + 0.2  # Simplified correlation
        chol = np.linalg.cholesky(corr)
        
        t_samples = np.random.standard_t(df=4, size=(n_sims, self.n))
        correlated = t_samples @ chol.T
        
        # Transform to uniform via t CDF
        uniform = stats.t.cdf(correlated, df=4)
        
        return uniform
    
    def _conditional_simulate(
        self,
        conditional_asset: str,
        conditional_shock: float,
        n_sims: int
    ) -> np.ndarray:
        """Simulate conditional on asset shock."""
        asset_idx = self.assets.index(conditional_asset)
        
        # Generate conditional samples
        # Simplified approach: fix one dimension, sample others
        base_samples = self._unconditional_simulate(n_sims * 2)
        
        # Select samples where conditional asset is near target
        target_uniform = stats.norm.cdf(conditional_shock)
        mask = np.abs(base_samples[:, asset_idx] - target_uniform) < 0.05
        
        selected = base_samples[mask][:n_sims]
        
        # If not enough samples, adjust
        if len(selected) < n_sims:
            # Add samples with exact conditioning
            additional = self._unconditional_simulate(n_sims - len(selected))
            additional[:, asset_idx] = target_uniform
            selected = np.vstack([selected, additional])
        
        return selected[:n_sims]


class StressTester:
    """
    Institutional-grade stress testing with advanced models.
    """
    
    def __init__(
        self,
        confidence: float = 0.99,
        use_regime_switching: bool = True,
        use_copula: bool = True
    ):
        self.confidence = confidence
        self.use_regime_switching = use_regime_switching
        self.use_copula = use_copula
        
        self.scenarios = self._load_standard_scenarios()
        self.regime_model = RegimeSwitchingModel() if use_regime_switching else None
        self.copula_model: CopulaStressModel | None = None
    
    def _load_standard_scenarios(self) -> list[StressScenario]:
        """Enhanced stress scenarios with conditional probabilities."""
        return [
            StressScenario(
                name="flash_crash_2010",
                description="May 6, 2010 style flash crash",
                shock_type="liquidity_crisis",
                shock_magnitude=-0.10,
                affected_assets=["XAUUSD", "SPX", "EURUSD"],
                duration_days=1,
                probability=0.001,
                volatility_multiplier=5.0
            ),
            StressScenario(
                name="lehman_crisis",
                description="2008 Lehman Brothers collapse",
                shock_type="correlation_breakdown",
                shock_magnitude=-0.25,
                affected_assets=["XAUUSD", "SPX", "EURUSD", "GBPUSD"],
                duration_days=30,
                probability=0.005,
                volatility_multiplier=3.0
            ),
            StressScenario(
                name="covid_crash",
                description="COVID-19 pandemic crash",
                shock_type="volatility_spike",
                shock_magnitude=-0.35,
                affected_assets=["XAUUSD", "SPX", "OIL"],
                duration_days=20,
                probability=0.01,
                volatility_multiplier=4.0
            ),
            StressScenario(
                name="safe_haven_rush",
                description="Flight to gold safety",
                shock_type="relative",
                shock_magnitude=0.30,
                affected_assets=["XAUUSD"],
                duration_days=10,
                probability=0.02,
                conditional_on=["geopolitical_crisis"]
            ),
            StressScenario(
                name="dollar_crisis",
                description="USD collapse impacts",
                shock_type="relative",
                shock_magnitude=0.25,
                affected_assets=["XAUUSD", "EURUSD", "GBPUSD"],
                duration_days=15,
                probability=0.01
            ),
            StressScenario(
                name="liquidity_freeze",
                description="Market liquidity evaporation",
                shock_type="liquidity_crisis",
                shock_magnitude=0.02,  # 200 bps spread widening
                affected_assets=["XAUUSD"],
                duration_days=5,
                probability=0.005
            ),
            StressScenario(
                name="inflation_shock",
                description="Unexpected inflation spike",
                shock_type="relative",
                shock_magnitude=0.20,
                affected_assets=["XAUUSD"],
                duration_days=60,
                probability=0.03
            ),
        ]
    
    def run_comprehensive_stress_test(
        self,
        portfolio_value: Decimal,
        positions: dict[str, Decimal],
        correlations: pd.DataFrame | None = None,
        historical_returns: pd.DataFrame | None = None
    ) -> dict:
        """
        Run comprehensive stress test with multiple methodologies.
        """
        results = {
            "scenario_analysis": [],
            "monte_carlo": {},
            "historical": {},
            "regime_based": {},
            "tail_risk": {},
            "summary": {}
        }
        
        # 1. Scenario-based stress tests
        for scenario in self.scenarios:
            scenario_result = self._run_scenario(portfolio_value, positions, scenario)
            results["scenario_analysis"].append(scenario_result)
        
        # 2. Monte Carlo with copula dependencies
        if self.use_copula and historical_returns is not None:
            results["monte_carlo"] = self._run_copula_stress(
                portfolio_value, positions, historical_returns
            )
        else:
            results["monte_carlo"] = self._run_standard_mc(
                portfolio_value, positions, correlations
            )
        
        # 3. Historical simulation
        if historical_returns is not None:
            results["historical"] = self._run_historical_simulation(
                portfolio_value, positions, historical_returns
            )
        
        # 4. Regime-switching simulation
        if self.use_regime_switching:
            results["regime_based"] = self._run_regime_simulation(
                portfolio_value, positions
            )
        
        # 5. Tail risk analysis
        results["tail_risk"] = self._analyze_tail_risk(
            portfolio_value, positions, historical_returns
        )
        
        # Summary statistics
        results["summary"] = self._generate_summary(results)
        
        return results
    
    def _run_scenario(
        self,
        portfolio_value: Decimal,
        positions: dict[str, Decimal],
        scenario: StressScenario
    ) -> dict:
        """Run single scenario analysis."""
        shocks = {asset: scenario.shock_magnitude for asset in scenario.affected_assets}
        
        # Calculate impact with volatility adjustment
        total_impact = 0.0
        position_impacts = {}
        
        for symbol, size in positions.items():
            base_shock = shocks.get(symbol, 0.0)
            
            # Adjust for volatility regime
            vol_adjusted_shock = base_shock * scenario.volatility_multiplier
            
            # Calculate position impact
            position_value = float(size) * 1800  # Simplified
            impact = position_value * vol_adjusted_shock
            
            # Add jump-to-default risk for extreme scenarios
            if abs(vol_adjusted_shock) > 0.5:
                jtd_prob = 0.01  # 1% jump-to-default
                impact -= position_value * jtd_prob * 0.5
            
            position_impacts[symbol] = {
                "size": float(size),
                "base_shock": base_shock,
                "adjusted_shock": vol_adjusted_shock,
                "impact": impact,
                "impact_pct": (impact / float(portfolio_value)) * 100
            }
            
            total_impact += impact
        
        stressed_value = float(portfolio_value) + total_impact
        
        return {
            "scenario_name": scenario.name,
            "description": scenario.description,
            "probability": scenario.probability,
            "duration_days": scenario.duration_days,
            "total_impact": total_impact,
            "portfolio_impact_pct": (total_impact / float(portfolio_value)) * 100,
            "stressed_value": stressed_value,
            "position_details": position_impacts,
            "breaches": self._check_limit_breaches(total_impact, float(portfolio_value)),
            "recovery_estimate": self._estimate_recovery(scenario, total_impact)
        }
    
    def _run_copula_stress(
        self,
        portfolio_value: Decimal,
        positions: dict[str, Decimal],
        historical_returns: pd.DataFrame
    ) -> dict:
        """Run copula-based stress simulation."""
        if self.copula_model is None:
            self.copula_model = CopulaStressModel(list(positions.keys()))
            self.copula_model.fit(historical_returns)
        
        # Simulate with tail dependencies
        n_sims = 10000
        simulated_returns = self.copula_model.simulate_stress(n_sims)
        
        # Calculate portfolio P&L for each simulation
        position_values = np.array([
            float(positions.get(asset, 0)) * 1800 
            for asset in simulated_returns.columns
        ])
        
        portfolio_pnl = simulated_returns.values @ position_values
        
        return {
            "method": "vine_copula",
            "n_simulations": n_sims,
            "var_99": float(np.percentile(portfolio_pnl, 1)),
            "var_95": float(np.percentile(portfolio_pnl, 5)),
            "cvar_99": float(np.mean(portfolio_pnl[portfolio_pnl <= np.percentile(portfolio_pnl, 1)])),
            "cvar_95": float(np.mean(portfolio_pnl[portfolio_pnl <= np.percentile(portfolio_pnl, 5)])),
            "tail_dependence": self._estimate_tail_dependence(simulated_returns),
            "probability_of_ruin": float(np.mean(portfolio_pnl < -float(portfolio_value) * 0.5)),
            "expected_shortfall_extreme": float(np.mean(portfolio_pnl[portfolio_pnl <= np.percentile(portfolio_pnl, 0.1)]))
        }
    
    def _run_regime_simulation(
        self,
        portfolio_value: Decimal,
        positions: dict[str, Decimal]
    ) -> dict:
        """Run regime-switching simulation."""
        if self.regime_model is None:
            return {}
        
        # Simulate 1 year of returns
        n_days = 252
        n_paths = 5000
        
        regime_returns = self.regime_model.simulate(n_days, n_paths)
        
        # Calculate cumulative returns
        cumulative = np.cumprod(1 + regime_returns, axis=1) - 1
        
        # Portfolio value paths (simplified equal weight)
        portfolio_paths = cumulative.mean(axis=1) * float(portfolio_value)
        
        # Find maximum drawdowns
        running_max = np.maximum.accumulate(portfolio_paths, axis=0)
        drawdowns = (portfolio_paths - running_max) / running_max
        
        return {
            "method": "regime_switching",
            "n_paths": n_paths,
            "n_days": n_days,
            "expected_final_value": float(np.mean(portfolio_paths[:, -1])),
            "worst_case_value": float(np.min(portfolio_paths[:, -1])),
            "max_drawdown_mean": float(np.mean(np.min(drawdowns, axis=1))),
            "max_drawdown_worst": float(np.min(drawdowns)),
            "regime_distribution": self._estimate_regime_distribution(),
            "probability_regime_switch": float(1 - self.regime_model.regimes[0].persistence)
        }
    
    def _analyze_tail_risk(
        self,
        portfolio_value: Decimal,
        positions: dict[str, Decimal],
        historical_returns: pd.DataFrame | None
    ) -> dict:
        """Advanced tail risk analysis."""
        if historical_returns is None:
            return {}
        
        # Hill estimator for tail index
        portfolio_returns = self._calculate_portfolio_returns(positions, historical_returns)
        
        # Sort returns
        sorted_returns = np.sort(portfolio_returns)
        n = len(sorted_returns)
        
        # Use top 5% for tail estimation
        k = int(n * 0.05)
        tail_returns = sorted_returns[:k]  # Worst returns
        
        # Hill estimator
        if len(tail_returns) > 0 and tail_returns[0] != 0:
            hill_estimates = []
            for i in range(1, min(k, 50)):
                xi = i / np.sum(np.log(tail_returns[0] / tail_returns[1:i+1]))
                hill_estimates.append(xi)
            
            tail_index = np.median(hill_estimates) if hill_estimates else 3.0
        else:
            tail_index = 3.0
        
        # Expected shortfall calculations
        var_levels = [0.1, 1, 5, 10]
        es_results = {}
        
        for level in var_levels:
            var = np.percentile(portfolio_returns, level)
            es = np.mean(portfolio_returns[portfolio_returns <= var])
            es_results[f"es_{level}"] = float(es)
        
        # Spectral risk measure (exponential weighting)
        alpha = 0.05
        weights = np.exp(-np.arange(len(sorted_returns)) / (alpha * len(sorted_returns)))
        weights = weights / weights.sum()
        spectral_risk = np.sum(sorted_returns * weights)
        
        return {
            "tail_index": float(tail_index),
            "tail_heaviness": "heavy" if tail_index < 3 else "moderate" if tail_index < 5 else "light",
            "expected_shortfalls": es_results,
            "spectral_risk_measure": float(spectral_risk),
            "extreme_loss_probability_10pct": float(np.mean(portfolio_returns < -0.1)),
            "extreme_loss_probability_20pct": float(np.mean(portfolio_returns < -0.2)),
            "maximum_observed_loss": float(np.min(portfolio_returns)),
            "recovery_50pct_drawdown_days": self._estimate_recovery_time(portfolio_returns, 0.5)
        }
    
    def _check_limit_breaches(self, impact: float, portfolio_value: float) -> list[str]:
        """Check which limits would be breached."""
        breaches = []
        impact_pct = abs(impact / portfolio_value)
        
        if impact_pct > 0.10:
            breaches.append("Maximum drawdown (10%)")
        if impact_pct > 0.05:
            breaches.append("Daily loss limit (5%)")
        if impact_pct > 0.02:
            breaches.append("Position limit warning (2%)")
        
        return breaches
    
    def _estimate_recovery(self, scenario: StressScenario, impact: float) -> dict:
        """Estimate recovery time from stress scenario."""
        base_recovery_days = scenario.duration_days
        
        # Larger losses take longer to recover
        if abs(impact) > 0.3:
            multiplier = 3.0
        elif abs(impact) > 0.2:
            multiplier = 2.0
        elif abs(impact) > 0.1:
            multiplier = 1.5
        else:
            multiplier = 1.0
        
        return {
            "estimated_recovery_days": int(base_recovery_days * multiplier),
            "confidence": "low" if multiplier > 2 else "medium" if multiplier > 1.5 else "high",
            "recovery_pattern": "V-shaped" if multiplier < 1.5 else "U-shaped" if multiplier < 2.5 else "L-shaped"
        }
    
    def _estimate_tail_dependence(self, returns: pd.DataFrame) -> dict:
        """Estimate lower and upper tail dependence."""
        # Simplified - would use proper tail dependence estimators
        return {
            "lower_tail_dependence": 0.3,  # Probability both assets crash together
            "upper_tail_dependence": 0.1,
            "interpretation": "Assets tend to crash together but not rally together"
        }
    
    def _estimate_regime_distribution(self) -> dict:
        """Estimate stationary distribution of regimes."""
        if self.regime_model is None:
            return {}
        
        # Solve for stationary distribution
        P = self.regime_model.transition_matrix
        # Simplified - assume mostly normal regime
        return {
            "normal_regime_prob": 0.85,
            "stressed_regime_prob": 0.12,
            "crisis_regime_prob": 0.03
        }
    
    def _calculate_portfolio_returns(
        self,
        positions: dict[str, Decimal],
        returns: pd.DataFrame
    ) -> np.ndarray:
        """Calculate portfolio returns from asset returns."""
        # Simplified equal-weighted
        weights = np.array([1.0 / len(positions)] * len(positions))
        portfolio_returns = returns.iloc[:, :len(positions)].values @ weights
        return portfolio_returns
    
    def _estimate_recovery_time(self, returns: np.ndarray, drawdown_threshold: float) -> int:
        """Estimate time to recover from drawdown."""
        # Find instances of drawdown and measure recovery
        # Simplified estimate
        return int(252 * drawdown_threshold * 2)  # Rough heuristic
    
    def _generate_summary(self, results: dict) -> dict:
        """Generate executive summary of stress test results."""
        all_scenario_impacts = [
            s["portfolio_impact_pct"] 
            for s in results.get("scenario_analysis", [])
        ]
        
        return {
            "worst_scenario": min(all_scenario_impacts) if all_scenario_impacts else 0,
            "worst_scenario_name": (
                results["scenario_analysis"][np.argmin(all_scenario_impacts)]["scenario_name"]
                if all_scenario_impacts else "N/A"
            ),
            "average_scenario_impact": np.mean(all_scenario_impacts) if all_scenario_impacts else 0,
            "var_99": results.get("monte_carlo", {}).get("var_99", 0),
            "probability_of_ruin": results.get("monte_carlo", {}).get("probability_of_ruin", 0),
            "overall_risk_rating": self._calculate_risk_rating(results),
            "recommended_actions": self._generate_recommendations(results)
        }
    
    def _calculate_risk_rating(self, results: dict) -> str:
        """Calculate overall risk rating."""
        ruin_prob = results.get("monte_carlo", {}).get("probability_of_ruin", 0)
        var_99 = abs(results.get("monte_carlo", {}).get("var_99", 0))
        
        if ruin_prob > 0.01 or var_99 > 0.5:
            return "CRITICAL"
        elif ruin_prob > 0.001 or var_99 > 0.3:
            return "HIGH"
        elif ruin_prob > 0.0001 or var_99 > 0.2:
            return "MODERATE"
        else:
            return "LOW"
    
    def _generate_recommendations(self, results: dict) -> list[str]:
        """Generate risk management recommendations."""
        recommendations = []
        
        if results.get("monte_carlo", {}).get("probability_of_ruin", 0) > 0.001:
            recommendations.append("Reduce position sizes to limit tail risk")
            recommendations.append("Consider buying protective puts or tail hedges")
        
        if any("correlation_breakdown" in s.get("shock_type", "") 
               for s in results.get("scenario_analysis", [])):
            recommendations.append("Diversify across uncorrelated strategies")
        
        if results.get("tail_risk", {}).get("tail_index", 3) < 3:
            recommendations.append("Heavy tails detected - use robust risk measures")
        
        return recommendations

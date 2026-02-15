"""
Advanced Risk Analytics

Professional-grade risk management tools:
- Value at Risk (VaR) calculations
- Monte Carlo simulations
- Stress testing framework
- Drawdown analysis
- Risk-adjusted performance metrics
"""

from typing import Dict, List, Optional, Any, Tuple
import numpy as np
import pandas as pd
from dataclasses import dataclass, field
from datetime import datetime
import logging
from enum import Enum

logger = logging.getLogger(__name__)


class RiskMetricType(Enum):
    """Types of risk metrics."""
    VAR_HISTORICAL = "var_historical"
    VAR_PARAMETRIC = "var_parametric"
    VAR_MONTE_CARLO = "var_monte_carlo"
    CVAR = "cvar"  # Conditional VaR / Expected Shortfall
    MAX_DRAWDOWN = "max_drawdown"
    SHARPE_RATIO = "sharpe_ratio"
    SORTINO_RATIO = "sortino_ratio"
    CALMAR_RATIO = "calmar_ratio"


@dataclass
class VaRResult:
    """Value at Risk calculation result."""
    var_value: float  # Dollar or percent loss
    confidence_level: float  # e.g., 0.95 for 95%
    time_horizon: int  # Days
    method: str
    timestamp: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> Dict:
        return {
            'var_value': self.var_value,
            'confidence_level': self.confidence_level,
            'time_horizon': self.time_horizon,
            'method': self.method,
            'timestamp': self.timestamp.isoformat()
        }


@dataclass
class MonteCarloResult:
    """Monte Carlo simulation result."""
    expected_return: float
    expected_volatility: float
    var_95: float
    var_99: float
    cvar_95: float
    max_gain: float
    max_loss: float
    simulated_paths: Optional[np.ndarray] = None
    num_simulations: int = 10000
    timestamp: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> Dict:
        return {
            'expected_return': self.expected_return,
            'expected_volatility': self.expected_volatility,
            'var_95': self.var_95,
            'var_99': self.var_99,
            'cvar_95': self.cvar_95,
            'max_gain': self.max_gain,
            'max_loss': self.max_loss,
            'num_simulations': self.num_simulations,
            'timestamp': self.timestamp.isoformat()
        }


@dataclass
class StressTestResult:
    """Stress test scenario result."""
    scenario_name: str
    portfolio_impact: float  # Percentage impact
    dollar_impact: float  # Dollar impact
    affected_positions: List[str]
    risk_level: str  # 'low', 'medium', 'high', 'severe'
    recommendation: str
    timestamp: datetime = field(default_factory=datetime.utcnow)


@dataclass
class DrawdownAnalysis:
    """Drawdown analysis result."""
    current_drawdown: float
    max_drawdown: float
    max_drawdown_duration: int  # Days
    current_drawdown_duration: int
    recovery_rate: float  # Historical recovery rate
    drawdown_events: List[Dict]
    underwater_periods: List[Dict]


class AdvancedRiskAnalytics:
    """
    Professional risk analytics engine.

    Features:
    - Multiple VaR calculation methods
    - Monte Carlo portfolio simulation
    - Stress testing scenarios
    - Comprehensive drawdown analysis
    - Risk-adjusted performance metrics
    """

    def __init__(self, config: Optional[Dict] = None):
        """
        Initialize risk analytics.

        Args:
            config: Configuration dict with:
                - var_confidence: VaR confidence level (default: 0.95)
                - mc_simulations: Monte Carlo simulations (default: 10000)
                - risk_free_rate: Annual risk-free rate (default: 0.05)
        """
        self.config = config or {}
        self.var_confidence = self.config.get('var_confidence', 0.95)
        self.mc_simulations = self.config.get('mc_simulations', 10000)
        self.risk_free_rate = self.config.get('risk_free_rate', 0.05)

        # Stress test scenarios
        self.stress_scenarios = self._initialize_stress_scenarios()

        logger.info("Advanced Risk Analytics initialized")

    def _initialize_stress_scenarios(self) -> Dict[str, Dict]:
        """Initialize predefined stress test scenarios."""
        return {
            'market_crash_2008': {
                'name': 'Market Crash (2008 Style)',
                'equities': -0.50,
                'forex': -0.15,
                'gold': 0.10,
                'crypto': -0.60,
                'bonds': 0.05,
                'description': 'Severe market downturn similar to 2008 financial crisis'
            },
            'flash_crash': {
                'name': 'Flash Crash',
                'equities': -0.10,
                'forex': -0.05,
                'gold': 0.02,
                'crypto': -0.25,
                'bonds': 0.01,
                'description': 'Sudden sharp decline with quick recovery'
            },
            'rate_hike_shock': {
                'name': 'Interest Rate Shock (+200bps)',
                'equities': -0.15,
                'forex': 0.05,
                'gold': -0.10,
                'crypto': -0.20,
                'bonds': -0.12,
                'description': 'Unexpected aggressive rate hike by central banks'
            },
            'geopolitical_crisis': {
                'name': 'Geopolitical Crisis',
                'equities': -0.20,
                'forex': -0.08,
                'gold': 0.15,
                'crypto': -0.15,
                'bonds': 0.03,
                'description': 'Major geopolitical event causing market uncertainty'
            },
            'crypto_winter': {
                'name': 'Crypto Winter',
                'equities': -0.05,
                'forex': 0.00,
                'gold': 0.02,
                'crypto': -0.80,
                'bonds': 0.00,
                'description': 'Severe cryptocurrency market downturn'
            },
            'dollar_collapse': {
                'name': 'USD Collapse',
                'equities': -0.10,
                'forex': 0.20,  # Non-USD pairs benefit
                'gold': 0.30,
                'crypto': 0.15,
                'bonds': -0.05,
                'description': 'Sharp devaluation of US Dollar'
            },
            'best_case': {
                'name': 'Bull Market Rally',
                'equities': 0.30,
                'forex': 0.05,
                'gold': -0.05,
                'crypto': 0.50,
                'bonds': -0.02,
                'description': 'Strong bull market across assets'
            },
        }

    # ============================================================
    # VALUE AT RISK (VaR)
    # ============================================================

    def calculate_var_historical(
        self,
        returns: np.ndarray,
        confidence_level: float = None,
        time_horizon: int = 1,
        portfolio_value: float = None
    ) -> VaRResult:
        """
        Calculate Historical VaR.

        Uses historical returns to estimate potential losses.

        Args:
            returns: Array of historical returns
            confidence_level: VaR confidence (default from config)
            time_horizon: Time horizon in days
            portfolio_value: Optional portfolio value for dollar VaR

        Returns:
            VaRResult object
        """
        confidence_level = confidence_level or self.var_confidence

        # Calculate VaR percentile
        var_percentile = np.percentile(returns, (1 - confidence_level) * 100)

        # Scale for time horizon (assuming sqrt(t) scaling)
        var_scaled = var_percentile * np.sqrt(time_horizon)

        # Convert to dollar value if portfolio value provided
        if portfolio_value:
            var_value = abs(var_scaled * portfolio_value)
        else:
            var_value = abs(var_scaled)

        return VaRResult(
            var_value=var_value,
            confidence_level=confidence_level,
            time_horizon=time_horizon,
            method='historical'
        )

    def calculate_var_parametric(
        self,
        returns: np.ndarray,
        confidence_level: float = None,
        time_horizon: int = 1,
        portfolio_value: float = None
    ) -> VaRResult:
        """
        Calculate Parametric (Variance-Covariance) VaR.

        Assumes normal distribution of returns.

        Args:
            returns: Array of historical returns
            confidence_level: VaR confidence (default from config)
            time_horizon: Time horizon in days
            portfolio_value: Optional portfolio value for dollar VaR

        Returns:
            VaRResult object
        """
        from scipy import stats

        confidence_level = confidence_level or self.var_confidence

        # Calculate mean and std
        mean_return = np.mean(returns)
        std_return = np.std(returns)

        # Z-score for confidence level
        z_score = stats.norm.ppf(1 - confidence_level)

        # Calculate VaR
        var_value = -(mean_return + z_score * std_return)

        # Scale for time horizon
        var_scaled = var_value * np.sqrt(time_horizon)

        # Convert to dollar value if portfolio value provided
        if portfolio_value:
            var_final = abs(var_scaled * portfolio_value)
        else:
            var_final = abs(var_scaled)

        return VaRResult(
            var_value=var_final,
            confidence_level=confidence_level,
            time_horizon=time_horizon,
            method='parametric'
        )

    def calculate_var_monte_carlo(
        self,
        returns: np.ndarray,
        confidence_level: float = None,
        time_horizon: int = 1,
        num_simulations: int = None,
        portfolio_value: float = None
    ) -> VaRResult:
        """
        Calculate Monte Carlo VaR.

        Uses simulated returns based on historical distribution.

        Args:
            returns: Array of historical returns
            confidence_level: VaR confidence (default from config)
            time_horizon: Time horizon in days
            num_simulations: Number of simulations
            portfolio_value: Optional portfolio value for dollar VaR

        Returns:
            VaRResult object
        """
        confidence_level = confidence_level or self.var_confidence
        num_simulations = num_simulations or self.mc_simulations

        # Estimate distribution parameters
        mean_return = np.mean(returns)
        std_return = np.std(returns)

        # Simulate returns
        np.random.seed(42)  # For reproducibility
        simulated_returns = np.random.normal(
            mean_return * time_horizon,
            std_return * np.sqrt(time_horizon),
            num_simulations
        )

        # Calculate VaR from simulations
        var_value = -np.percentile(simulated_returns, (1 - confidence_level) * 100)

        # Convert to dollar value if portfolio value provided
        if portfolio_value:
            var_final = abs(var_value * portfolio_value)
        else:
            var_final = abs(var_value)

        return VaRResult(
            var_value=var_final,
            confidence_level=confidence_level,
            time_horizon=time_horizon,
            method='monte_carlo'
        )

    def calculate_cvar(
        self,
        returns: np.ndarray,
        confidence_level: float = None,
        portfolio_value: float = None
    ) -> float:
        """
        Calculate Conditional VaR (Expected Shortfall).

        CVaR is the expected loss given that loss exceeds VaR.

        Args:
            returns: Array of historical returns
            confidence_level: Confidence level
            portfolio_value: Optional portfolio value

        Returns:
            CVaR value
        """
        confidence_level = confidence_level or self.var_confidence

        # Find VaR threshold
        var_threshold = np.percentile(returns, (1 - confidence_level) * 100)

        # Calculate expected shortfall (average of returns below VaR)
        tail_returns = returns[returns <= var_threshold]

        if len(tail_returns) == 0:
            cvar = abs(var_threshold)
        else:
            cvar = abs(np.mean(tail_returns))

        if portfolio_value:
            cvar = cvar * portfolio_value

        return cvar

    # ============================================================
    # MONTE CARLO SIMULATION
    # ============================================================

    def run_monte_carlo_simulation(
        self,
        initial_value: float,
        expected_return: float,
        volatility: float,
        time_horizon: int = 252,  # Trading days
        num_simulations: int = None,
        return_paths: bool = False
    ) -> MonteCarloResult:
        """
        Run Monte Carlo simulation for portfolio projection.

        Args:
            initial_value: Starting portfolio value
            expected_return: Annual expected return
            volatility: Annual volatility
            time_horizon: Simulation horizon in trading days
            num_simulations: Number of simulations
            return_paths: Whether to return all simulated paths

        Returns:
            MonteCarloResult object
        """
        num_simulations = num_simulations or self.mc_simulations

        # Daily parameters
        daily_return = expected_return / 252
        daily_vol = volatility / np.sqrt(252)

        # Generate random walks
        np.random.seed(42)  # Reproducibility
        random_returns = np.random.normal(
            daily_return,
            daily_vol,
            (num_simulations, time_horizon)
        )

        # Calculate cumulative returns (geometric)
        cumulative_returns = np.cumprod(1 + random_returns, axis=1)

        # Final portfolio values
        final_values = initial_value * cumulative_returns[:, -1]

        # Calculate statistics
        final_returns = (final_values - initial_value) / initial_value

        result = MonteCarloResult(
            expected_return=np.mean(final_returns),
            expected_volatility=np.std(final_returns),
            var_95=-np.percentile(final_returns, 5),
            var_99=-np.percentile(final_returns, 1),
            cvar_95=self.calculate_cvar(final_returns, 0.95),
            max_gain=np.max(final_returns),
            max_loss=np.min(final_returns),
            simulated_paths=cumulative_returns if return_paths else None,
            num_simulations=num_simulations
        )

        return result

    def simulate_portfolio_scenarios(
        self,
        positions: Dict[str, Dict],
        correlations: Optional[np.ndarray] = None,
        time_horizon: int = 30,
        num_simulations: int = None
    ) -> Dict[str, Any]:
        """
        Simulate portfolio scenarios with correlated assets.

        Args:
            positions: Dict of positions with 'value', 'expected_return', 'volatility'
            correlations: Correlation matrix (optional)
            time_horizon: Days to simulate
            num_simulations: Number of simulations

        Returns:
            Simulation results
        """
        num_simulations = num_simulations or self.mc_simulations
        n_assets = len(positions)
        asset_names = list(positions.keys())

        # Extract parameters
        values = np.array([positions[a]['value'] for a in asset_names])
        returns = np.array([positions[a].get('expected_return', 0.0) for a in asset_names])
        vols = np.array([positions[a].get('volatility', 0.20) for a in asset_names])

        # Default to identity correlation if not provided
        if correlations is None:
            correlations = np.eye(n_assets)

        # Daily parameters
        daily_returns = returns / 252
        daily_vols = vols / np.sqrt(252)

        # Cholesky decomposition for correlated random variables
        L = np.linalg.cholesky(correlations)

        # Generate correlated random returns
        np.random.seed(42)
        uncorrelated = np.random.normal(0, 1, (num_simulations, time_horizon, n_assets))
        correlated = np.einsum('ijk,lk->ijl', uncorrelated, L)

        # Apply mean and volatility
        simulated_returns = daily_returns + daily_vols * correlated

        # Calculate portfolio paths
        asset_paths = np.cumprod(1 + simulated_returns, axis=1)
        portfolio_paths = np.sum(values * asset_paths, axis=2)

        # Final values
        final_portfolio_values = portfolio_paths[:, -1]
        initial_portfolio_value = np.sum(values)

        # Calculate metrics
        portfolio_returns = (final_portfolio_values - initial_portfolio_value) / initial_portfolio_value

        return {
            'initial_value': initial_portfolio_value,
            'expected_final_value': np.mean(final_portfolio_values),
            'expected_return': np.mean(portfolio_returns),
            'volatility': np.std(portfolio_returns),
            'var_95': -np.percentile(portfolio_returns, 5) * initial_portfolio_value,
            'var_99': -np.percentile(portfolio_returns, 1) * initial_portfolio_value,
            'best_case': np.percentile(final_portfolio_values, 95),
            'worst_case': np.percentile(final_portfolio_values, 5),
            'probability_loss': np.mean(portfolio_returns < 0),
            'probability_gain_10pct': np.mean(portfolio_returns > 0.10),
        }

    # ============================================================
    # STRESS TESTING
    # ============================================================

    def run_stress_test(
        self,
        portfolio: Dict[str, Dict],
        scenario_name: str
    ) -> StressTestResult:
        """
        Run a stress test scenario on portfolio.

        Args:
            portfolio: Portfolio positions with 'value' and 'asset_class'
            scenario_name: Name of stress scenario

        Returns:
            StressTestResult object
        """
        if scenario_name not in self.stress_scenarios:
            raise ValueError(f"Unknown scenario: {scenario_name}")

        scenario = self.stress_scenarios[scenario_name]
        total_value = sum(p['value'] for p in portfolio.values())

        # Calculate impact on each position
        total_impact = 0.0
        affected = []

        for position_name, position in portfolio.items():
            asset_class = position.get('asset_class', 'equities')
            value = position['value']

            # Get shock for asset class
            shock = scenario.get(asset_class, 0.0)
            position_impact = value * shock
            total_impact += position_impact

            if shock != 0:
                affected.append(position_name)

        # Calculate percentage impact
        pct_impact = total_impact / total_value if total_value > 0 else 0

        # Determine risk level
        if abs(pct_impact) < 0.05:
            risk_level = 'low'
            recommendation = 'Portfolio is resilient to this scenario'
        elif abs(pct_impact) < 0.15:
            risk_level = 'medium'
            recommendation = 'Consider hedging or reducing exposure'
        elif abs(pct_impact) < 0.30:
            risk_level = 'high'
            recommendation = 'Significant risk - implement protective measures'
        else:
            risk_level = 'severe'
            recommendation = 'Critical exposure - immediate risk reduction required'

        return StressTestResult(
            scenario_name=scenario['name'],
            portfolio_impact=pct_impact,
            dollar_impact=total_impact,
            affected_positions=affected,
            risk_level=risk_level,
            recommendation=recommendation
        )

    def run_all_stress_tests(self, portfolio: Dict[str, Dict]) -> List[StressTestResult]:
        """Run all stress test scenarios."""
        results = []
        for scenario_name in self.stress_scenarios.keys():
            result = self.run_stress_test(portfolio, scenario_name)
            results.append(result)
        return results

    # ============================================================
    # DRAWDOWN ANALYSIS
    # ============================================================

    def analyze_drawdowns(self, equity_curve: np.ndarray) -> DrawdownAnalysis:
        """
        Comprehensive drawdown analysis.

        Args:
            equity_curve: Array of portfolio values over time

        Returns:
            DrawdownAnalysis object
        """
        # Calculate running maximum
        running_max = np.maximum.accumulate(equity_curve)

        # Calculate drawdown series
        drawdown = (equity_curve - running_max) / running_max

        # Current drawdown
        current_drawdown = drawdown[-1]

        # Maximum drawdown
        max_drawdown = np.min(drawdown)
        max_drawdown_idx = np.argmin(drawdown)

        # Find drawdown start (last peak before max drawdown)
        max_drawdown_start = np.argmax(equity_curve[:max_drawdown_idx+1] == running_max[max_drawdown_idx])
        max_drawdown_duration = max_drawdown_idx - max_drawdown_start

        # Current drawdown duration
        current_peak_idx = np.argmax(equity_curve == running_max[-1])
        current_drawdown_duration = len(equity_curve) - 1 - current_peak_idx

        # Identify all drawdown events
        drawdown_events = self._identify_drawdown_events(drawdown, threshold=-0.05)

        # Calculate recovery rate
        recovery_rate = self._calculate_recovery_rate(drawdown_events)

        # Underwater periods
        underwater_periods = self._calculate_underwater_periods(drawdown)

        return DrawdownAnalysis(
            current_drawdown=current_drawdown,
            max_drawdown=max_drawdown,
            max_drawdown_duration=max_drawdown_duration,
            current_drawdown_duration=current_drawdown_duration,
            recovery_rate=recovery_rate,
            drawdown_events=drawdown_events,
            underwater_periods=underwater_periods
        )

    def _identify_drawdown_events(
        self,
        drawdown: np.ndarray,
        threshold: float = -0.05
    ) -> List[Dict]:
        """Identify significant drawdown events."""
        events = []
        in_drawdown = False
        start_idx = 0

        for i, dd in enumerate(drawdown):
            if dd < threshold and not in_drawdown:
                in_drawdown = True
                start_idx = i
            elif dd >= 0 and in_drawdown:
                in_drawdown = False
                events.append({
                    'start_idx': start_idx,
                    'end_idx': i,
                    'duration': i - start_idx,
                    'max_drawdown': float(np.min(drawdown[start_idx:i+1])),
                    'recovered': True
                })

        # Handle ongoing drawdown
        if in_drawdown:
            events.append({
                'start_idx': start_idx,
                'end_idx': len(drawdown) - 1,
                'duration': len(drawdown) - start_idx,
                'max_drawdown': float(np.min(drawdown[start_idx:])),
                'recovered': False
            })

        return events

    def _calculate_recovery_rate(self, drawdown_events: List[Dict]) -> float:
        """Calculate historical recovery rate."""
        if not drawdown_events:
            return 1.0

        recovered = sum(1 for e in drawdown_events if e['recovered'])
        return recovered / len(drawdown_events)

    def _calculate_underwater_periods(self, drawdown: np.ndarray) -> List[Dict]:
        """Calculate time spent underwater."""
        underwater = drawdown < 0
        periods = []

        in_period = False
        start_idx = 0

        for i, uw in enumerate(underwater):
            if uw and not in_period:
                in_period = True
                start_idx = i
            elif not uw and in_period:
                in_period = False
                periods.append({
                    'start_idx': start_idx,
                    'end_idx': i,
                    'duration': i - start_idx
                })

        if in_period:
            periods.append({
                'start_idx': start_idx,
                'end_idx': len(drawdown) - 1,
                'duration': len(drawdown) - start_idx
            })

        return periods

    # ============================================================
    # RISK-ADJUSTED METRICS
    # ============================================================

    def calculate_sharpe_ratio(
        self,
        returns: np.ndarray,
        periods_per_year: int = 252
    ) -> float:
        """Calculate annualized Sharpe ratio."""
        excess_returns = returns - self.risk_free_rate / periods_per_year
        if np.std(returns) == 0:
            return 0.0
        return np.sqrt(periods_per_year) * np.mean(excess_returns) / np.std(returns)

    def calculate_sortino_ratio(
        self,
        returns: np.ndarray,
        periods_per_year: int = 252
    ) -> float:
        """Calculate annualized Sortino ratio (using downside deviation)."""
        excess_returns = returns - self.risk_free_rate / periods_per_year
        downside_returns = returns[returns < 0]

        if len(downside_returns) == 0 or np.std(downside_returns) == 0:
            return float('inf') if np.mean(excess_returns) > 0 else 0.0

        downside_std = np.std(downside_returns)
        return np.sqrt(periods_per_year) * np.mean(excess_returns) / downside_std

    def calculate_calmar_ratio(
        self,
        returns: np.ndarray,
        equity_curve: np.ndarray = None
    ) -> float:
        """Calculate Calmar ratio (annual return / max drawdown)."""
        annual_return = np.mean(returns) * 252

        if equity_curve is None:
            # Reconstruct equity curve from returns
            equity_curve = np.cumprod(1 + returns)

        analysis = self.analyze_drawdowns(equity_curve)
        max_dd = abs(analysis.max_drawdown)

        if max_dd == 0:
            return float('inf') if annual_return > 0 else 0.0

        return annual_return / max_dd

    def calculate_all_metrics(
        self,
        returns: np.ndarray,
        equity_curve: np.ndarray = None,
        portfolio_value: float = None
    ) -> Dict[str, Any]:
        """Calculate comprehensive risk metrics."""

        if equity_curve is None:
            equity_curve = np.cumprod(1 + returns) * (portfolio_value or 10000)

        # VaR calculations
        var_hist = self.calculate_var_historical(returns, portfolio_value=portfolio_value)
        var_param = self.calculate_var_parametric(returns, portfolio_value=portfolio_value)
        var_mc = self.calculate_var_monte_carlo(returns, portfolio_value=portfolio_value)
        cvar = self.calculate_cvar(returns, portfolio_value=portfolio_value)

        # Drawdown analysis
        drawdown = self.analyze_drawdowns(equity_curve)

        # Risk-adjusted metrics
        sharpe = self.calculate_sharpe_ratio(returns)
        sortino = self.calculate_sortino_ratio(returns)
        calmar = self.calculate_calmar_ratio(returns, equity_curve)

        return {
            'var_historical_95': var_hist.var_value,
            'var_parametric_95': var_param.var_value,
            'var_monte_carlo_95': var_mc.var_value,
            'cvar_95': cvar,
            'max_drawdown': drawdown.max_drawdown,
            'max_drawdown_duration': drawdown.max_drawdown_duration,
            'current_drawdown': drawdown.current_drawdown,
            'sharpe_ratio': sharpe,
            'sortino_ratio': sortino,
            'calmar_ratio': calmar,
            'total_return': float((equity_curve[-1] / equity_curve[0]) - 1),
            'annual_return': float(np.mean(returns) * 252),
            'annual_volatility': float(np.std(returns) * np.sqrt(252)),
            'positive_days': float(np.mean(returns > 0)),
            'recovery_rate': drawdown.recovery_rate,
        }

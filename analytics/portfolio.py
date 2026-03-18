
# Phase 5: Portfolio Analytics Module

code = '''"""
HOPEFX Portfolio Analytics Module
Multi-asset backtesting, portfolio optimization, correlation analysis, risk metrics
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any
from pathlib import Path
import json
import warnings
warnings.filterwarnings('ignore')

# Visualization
import matplotlib.pyplot as plt
import seaborn as sns
from matplotlib.gridspec import GridSpec

# Optimization
try:
    from scipy.optimize import minimize
    SCIPY_AVAILABLE = True
except ImportError:
    SCIPY_AVAILABLE = False


class PortfolioAnalytics:
    """
    Comprehensive portfolio analytics for multi-asset strategies
    """
    
    def __init__(self, risk_free_rate: float = 0.02):
        self.risk_free_rate = risk_free_rate
        self.returns_data: Optional[pd.DataFrame] = None
        self.weights: Optional[np.ndarray] = None
        self.assets: List[str] = []
    
    def load_returns_data(self, returns_df: pd.DataFrame):
        """Load historical returns data for analysis"""
        self.returns_data = returns_df.dropna()
        self.assets = list(returns_df.columns)
        print(f"Loaded returns data: {len(self.returns_data)} periods, {len(self.assets)} assets")
    
    def calculate_correlation_matrix(self, save_path: Optional[str] = None) -> pd.DataFrame:
        """Calculate and visualize correlation matrix"""
        if self.returns_data is None:
            raise ValueError("No returns data loaded")
        
        corr_matrix = self.returns_data.corr()
        
        # Plot
        plt.figure(figsize=(12, 10))
        mask = np.triu(np.ones_like(corr_matrix, dtype=bool))
        sns.heatmap(corr_matrix, mask=mask, annot=True, fmt='.2f', cmap='RdYlBu_r',
                   center=0, square=True, linewidths=0.5, cbar_kws={"shrink": 0.8})
        plt.title('Asset Correlation Matrix', fontsize=14, fontweight='bold')
        plt.tight_layout()
        
        if save_path:
            Path(save_path).parent.mkdir(parents=True, exist_ok=True)
            plt.savefig(save_path, dpi=300, bbox_inches='tight')
            print(f"Correlation matrix saved: {save_path}")
        
        plt.show()
        return corr_matrix
    
    def calculate_covariance_matrix(self) -> pd.DataFrame:
        """Calculate covariance matrix"""
        if self.returns_data is None:
            raise ValueError("No returns data loaded")
        return self.returns_data.cov()
    
    def portfolio_performance(self, weights: np.ndarray) -> Tuple[float, float, float]:
        """
        Calculate portfolio return, volatility, and Sharpe ratio
        
        Returns:
            (expected_return, volatility, sharpe_ratio)
        """
        if self.returns_data is None:
            raise ValueError("No returns data loaded")
        
        returns = self.returns_data.mean() * 252  # Annualized
        cov_matrix = self.returns_data.cov() * 252  # Annualized
        
        portfolio_return = np.dot(weights, returns)
        portfolio_volatility = np.sqrt(np.dot(weights.T, np.dot(cov_matrix, weights)))
        sharpe_ratio = (portfolio_return - self.risk_free_rate) / portfolio_volatility
        
        return portfolio_return, portfolio_volatility, sharpe_ratio
    
    def negative_sharpe(self, weights: np.ndarray) -> float:
        """Negative Sharpe ratio for optimization"""
        return -self.portfolio_performance(weights)[2]
    
    def portfolio_volatility(self, weights: np.ndarray) -> float:
        """Portfolio volatility for optimization"""
        return self.portfolio_performance(weights)[1]
    
    def optimize_portfolio(
        self,
        target_return: Optional[float] = None,
        target_risk: Optional[float] = None,
        max_sharpe: bool = True,
        allow_short: bool = False,
        max_position_size: float = 0.5
    ) -> Dict[str, Any]:
        """
        Optimize portfolio weights using mean-variance optimization
        
        Args:
            target_return: Target annualized return (optional)
            target_risk: Target annualized volatility (optional)
            max_sharpe: Maximize Sharpe ratio (default True)
            allow_short: Allow short positions
            max_position_size: Maximum weight for any single asset
        
        Returns:
            Dictionary with optimal weights and performance metrics
        """
        if not SCIPY_AVAILABLE:
            raise ImportError("scipy not installed. Run: pip install scipy")
        
        if self.returns_data is None:
            raise ValueError("No returns data loaded")
        
        n_assets = len(self.assets)
        
        # Constraints
        constraints = [{'type': 'eq', 'fun': lambda x: np.sum(x) - 1}]  # Sum of weights = 1
        
        if target_return is not None:
            constraints.append({
                'type': 'eq',
                'fun': lambda x: self.portfolio_performance(x)[0] - target_return
            })
        
        # Bounds
        if allow_short:
            bounds = [(-max_position_size, max_position_size) for _ in range(n_assets)]
        else:
            bounds = [(0, max_position_size) for _ in range(n_assets)]
        
        # Initial guess
        x0 = np.array([1/n_assets] * n_assets)
        
        # Optimization
        if max_sharpe and target_return is None and target_risk is None:
            # Maximize Sharpe ratio
            result = minimize(
                self.negative_sharpe,
                x0,
                method='SLSQP',
                bounds=bounds,
                constraints=constraints
            )
        elif target_risk is not None:
            # Minimize risk for target return
            result = minimize(
                self.portfolio_volatility,
                x0,
                method='SLSQP',
                bounds=bounds,
                constraints=constraints
            )
        else:
            # Minimize volatility
            result = minimize(
                self.portfolio_volatility,
                x0,
                method='SLSQP',
                bounds=bounds,
                constraints=constraints
            )
        
        if result.success:
            optimal_weights = result.x
            ret, vol, sharpe = self.portfolio_performance(optimal_weights)
            
            return {
                'success': True,
                'weights': dict(zip(self.assets, optimal_weights.round(4))),
                'expected_return': ret,
                'volatility': vol,
                'sharpe_ratio': sharpe,
                'allocation': pd.Series(optimal_weights, index=self.assets).sort_values(ascending=False)
            }
        else:
            return {'success': False, 'message': result.message}
    
    def generate_efficient_frontier(
        self,
        n_portfolios: int = 100,
        save_path: Optional[str] = None
    ) -> pd.DataFrame:
        """
        Generate efficient frontier by simulating random portfolios
        
        Returns:
            DataFrame with portfolio returns, volatility, and Sharpe ratios
        """
        if self.returns_data is None:
            raise ValueError("No returns data loaded")
        
        n_assets = len(self.assets)
        
        results = []
        for _ in range(n_portfolios):
            # Random weights
            weights = np.random.random(n_assets)
            weights /= np.sum(weights)
            
            ret, vol, sharpe = self.portfolio_performance(weights)
            
            results.append({
                'return': ret,
                'volatility': vol,
                'sharpe': sharpe,
                **dict(zip(self.assets, weights))
            })
        
        df = pd.DataFrame(results)
        
        # Plot efficient frontier
        plt.figure(figsize=(12, 8))
        scatter = plt.scatter(df['volatility'], df['return'], c=df['sharpe'], 
                             cmap='viridis', alpha=0.6, s=30)
        plt.colorbar(scatter, label='Sharpe Ratio')
        
        # Highlight max Sharpe portfolio
        max_sharpe_idx = df['sharpe'].idxmax()
        plt.scatter(df.loc[max_sharpe_idx, 'volatility'], 
                   df.loc[max_sharpe_idx, 'return'],
                   c='red', s=200, marker='*', label='Max Sharpe', edgecolors='black')
        
        # Highlight min volatility portfolio
        min_vol_idx = df['volatility'].idxmin()
        plt.scatter(df.loc[min_vol_idx, 'volatility'],
                   df.loc[min_vol_idx, 'return'],
                   c='blue', s=200, marker='*', label='Min Volatility', edgecolors='black')
        
        plt.xlabel('Annualized Volatility')
        plt.ylabel('Annualized Return')
        plt.title('Efficient Frontier')
        plt.legend()
        plt.grid(True, alpha=0.3)
        
        if save_path:
            Path(save_path).parent.mkdir(parents=True, exist_ok=True)
            plt.savefig(save_path, dpi=300, bbox_inches='tight')
            print(f"Efficient frontier saved: {save_path}")
        
        plt.show()
        return df
    
    def calculate_risk_metrics(self, weights: np.ndarray) -> Dict[str, float]:
        """
        Calculate comprehensive risk metrics for portfolio
        """
        if self.returns_data is None:
            raise ValueError("No returns data loaded")
        
        # Portfolio returns series
        portfolio_returns = (self.returns_data * weights).sum(axis=1)
        
        # Basic metrics
        total_return = (1 + portfolio_returns).prod() - 1
        annualized_return = portfolio_returns.mean() * 252
        volatility = portfolio_returns.std() * np.sqrt(252)
        
        # Sharpe ratio
        sharpe = (annualized_return - self.risk_free_rate) / volatility if volatility > 0 else 0
        
        # Sortino ratio (downside deviation)
        downside_returns = portfolio_returns[portfolio_returns < 0]
        downside_std = downside_returns.std() * np.sqrt(252) if len(downside_returns) > 0 else 0
        sortino = (annualized_return - self.risk_free_rate) / downside_std if downside_std > 0 else 0
        
        # Maximum drawdown
        cumulative = (1 + portfolio_returns).cumprod()
        rolling_max = cumulative.expanding().max()
        drawdown = (cumulative - rolling_max) / rolling_max
        max_drawdown = drawdown.min()
        
        # Calmar ratio
        calmar = annualized_return / abs(max_drawdown) if max_drawdown != 0 else 0
        
        # VaR (Value at Risk) - 95% confidence
        var_95 = np.percentile(portfolio_returns, 5)
        
        # CVaR (Conditional VaR)
        cvar_95 = portfolio_returns[portfolio_returns <= var_95].mean()
        
        # Beta (market correlation) - assumes first asset is market
        if len(self.assets) > 1:
            market_returns = self.returns_data.iloc[:, 0]
            covariance = np.cov(portfolio_returns, market_returns)[0][1]
            market_variance = market_returns.var()
            beta = covariance / market_variance if market_variance > 0 else 1.0
        else:
            beta = 1.0
        
        # Treynor ratio
        treynor = (annualized_return - self.risk_free_rate) / beta if beta != 0 else 0
        
        # Information ratio (vs equal weight benchmark)
        benchmark_returns = self.returns_data.mean(axis=1)
        active_returns = portfolio_returns - benchmark_returns
        tracking_error = active_returns.std() * np.sqrt(252)
        information_ratio = active_returns.mean() * 252 / tracking_error if tracking_error > 0 else 0
        
        return {
            'total_return': total_return,
            'annualized_return': annualized_return,
            'volatility': volatility,
            'sharpe_ratio': sharpe,
            'sortino_ratio': sortino,
            'max_drawdown': max_drawdown,
            'calmar_ratio': calmar,
            'var_95': var_95,
            'cvar_95': cvar_95,
            'beta': beta,
            'treynor_ratio': treynor,
            'information_ratio': information_ratio,
            'skewness': portfolio_returns.skew(),
            'kurtosis': portfolio_returns.kurtosis(),
            'downside_deviation': downside_std
        }
    
    def generate_report(self, weights: np.ndarray, output_dir: str = "analytics/outputs") -> str:
        """Generate comprehensive portfolio report"""
        Path(output_dir).mkdir(parents=True, exist_ok=True)
        
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        
        # Calculate metrics
        metrics = self.calculate_risk_metrics(weights)
        
        # Performance
        perf = self.portfolio_performance(weights)
        
        # Create report
        report = {
            'timestamp': datetime.now().isoformat(),
            'assets': self.assets,
            'weights': dict(zip(self.assets, weights.round(4))),
            'performance': {
                'expected_return': perf[0],
                'volatility': perf[1],
                'sharpe_ratio': perf[2]
            },
            'risk_metrics': metrics,
            'correlation_matrix': self.calculate_correlation_matrix().to_dict()
        }
        
        # Save JSON report
        report_path = Path(output_dir) / f"portfolio_report_{timestamp}.json"
        with open(report_path, 'w') as f:
            json.dump(report, f, indent=2, default=str)
        
        # Save metrics CSV
        metrics_df = pd.DataFrame([metrics])
        metrics_path = Path(output_dir) / f"risk_metrics_{timestamp}.csv"
        metrics_df.to_csv(metrics_path, index=False)
        
        # Save weights CSV
        weights_df = pd.DataFrame({
            'asset': self.assets,
            'weight': weights,
            'percentage': (weights * 100).round(2)
        }).sort_values('weight', ascending=False)
        weights_path = Path(output_dir) / f"portfolio_weights_{timestamp}.csv"
        weights_df.to_csv(weights_path, index=False)
        
        print(f"Portfolio report saved to {output_dir}/")
        return str(report_path)


class MultiAssetBacktester:
    """
    Event-driven backtester for multi-asset portfolios
    """
    
    def __init__(self, initial_capital: float = 100000.0, commission_rate: float = 0.001):
        self.initial_capital = initial_capital
        self.commission_rate = commission_rate
        
        self.positions: Dict[str, float] = {}
        self.cash = initial_capital
        self.equity_history: List[Dict] = []
        self.trades: List[Dict] = []
    
    def run_backtest(
        self,
        prices_df: pd.DataFrame,
        weights_df: pd.DataFrame,
        rebalance_freq: str = 'M'  # 'D' daily, 'W' weekly, 'M' monthly
    ) -> pd.DataFrame:
        """
        Run multi-asset backtest with periodic rebalancing
        
        Args:
            prices_df: DataFrame with price data for each asset
            weights_df: DataFrame with target weights over time
            rebalance_freq: Rebalancing frequency
        """
        print(f"Starting multi-asset backtest: ${self.initial_capital:,.2f}")
        print(f"Assets: {list(prices_df.columns)}")
        print(f"Rebalancing: {rebalance_freq}")
        
        # Initialize positions
        for asset in prices_df.columns:
            self.positions[asset] = 0.0
        
        # Resample weights to rebalancing frequency
        if rebalance_freq == 'M':
            rebalance_dates = weights_df.resample('M').last().index
        elif rebalance_freq == 'W':
            rebalance_dates = weights_df.resample('W').last().index
        else:
            rebalance_dates = weights_df.index
        
        # Iterate through dates
        for date in prices_df.index:
            current_prices = prices_df.loc[date]
            
            # Check if rebalancing needed
            if date in rebalance_dates or date == prices_df.index[0]:
                # Get target weights for this date
                if date in weights_df.index:
                    target_weights = weights_df.loc[date]
                else:
                    # Forward fill last known weights
                    target_weights = weights_df.loc[:date].iloc[-1]
                
                self._rebalance(date, current_prices, target_weights)
            
            # Calculate portfolio value
            portfolio_value = self._calculate_portfolio_value(current_prices)
            
            self.equity_history.append({
                'timestamp': date,
                'equity': portfolio_value,
                'cash': self.cash,
                'positions': self.positions.copy()
            })
        
        # Convert to DataFrame
        equity_df = pd.DataFrame(self.equity_history)
        equity_df.set_index('timestamp', inplace=True)
        
        # Calculate performance metrics
        returns = equity_df['equity'].pct_change().dropna()
        
        print(f"\\nBacktest complete:")
        print(f"  Final equity: ${equity_df['equity'].iloc[-1]:,.2f}")
        print(f"  Total return: {(equity_df['equity'].iloc[-1] / self.initial_capital - 1):.2%}")
        print(f"  Sharpe ratio: {(returns.mean() * 252) / (returns.std() * np.sqrt(252)):.2f}")
        
        return equity_df
    
    def _rebalance(self, date: datetime, prices: pd.Series, target_weights: pd.Series):
        """Rebalance portfolio to target weights"""
        # Calculate current portfolio value
        current_value = self._calculate_portfolio_value(prices)
        
        # Calculate target dollar values
        target_values = current_value * target_weights
        
        # Calculate current dollar values
        current_values = pd.Series({
            asset: self.positions.get(asset, 0) * prices[asset]
            for asset in prices.index
        })
        
        # Calculate trades needed
        trades = target_values - current_values
        
        # Execute trades
        for asset, trade_value in trades.items():
            if abs(trade_value) > 0.01:  # Minimum trade size
                trade_quantity = trade_value / prices[asset]
                commission = abs(trade_value) * self.commission_rate
                
                # Update positions
                self.positions[asset] = self.positions.get(asset, 0) + trade_quantity
                
                # Update cash
                self.cash -= trade_value + commission
                
                # Record trade
                self.trades.append({
                    'timestamp': date,
                    'asset': asset,
                    'quantity': trade_quantity,
                    'price': prices[asset],
                    'value': trade_value,
                    'commission': commission,
                    'action': 'buy' if trade_quantity > 0 else 'sell'
                })
    
    def _calculate_portfolio_value(self, prices: pd.Series) -> float:
        """Calculate total portfolio value"""
        position_value = sum(
            self.positions.get(asset, 0) * price
            for asset, price in prices.items()
        )
        return self.cash + position_value
    
    def save_results(self, output_dir: str = "analytics/outputs"):
        """Save backtest results"""
        Path(output_dir).mkdir(parents=True, exist_ok=True)
        
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        
        # Save equity curve
        equity_df = pd.DataFrame(self.equity_history)
        equity_path = Path(output_dir) / f"multi_asset_equity_{timestamp}.csv"
        equity_df.to_csv(equity_path, index=False)
        
        # Save trades
        trades_df = pd.DataFrame(self.trades)
        trades_path = Path(output_dir) / f"multi_asset_trades_{timestamp}.csv"
        trades_df.to_csv(trades_path, index=False)
        
        print(f"Backtest results saved to {output_dir}/")


class RiskAnalyzer:
    """
    Advanced risk analysis for portfolios
    """
    
    def __init__(self, returns_data: pd.DataFrame):
        self.returns_data = returns_data
    
    def calculate_drawdown_series(self) -> pd.DataFrame:
        """Calculate drawdown series for each asset"""
        cumulative = (1 + self.returns_data).cumprod()
        rolling_max = cumulative.expanding().max()
        drawdown = (cumulative - rolling_max) / rolling_max
        return drawdown
    
    def plot_drawdowns(self, save_path: Optional[str] = None):
        """Plot drawdown chart"""
        drawdown = self.calculate_drawdown_series()
        
        plt.figure(figsize=(14, 8))
        for col in drawdown.columns:
            plt.plot(drawdown.index, drawdown[col], label=col, alpha=0.7)
        
        plt.fill_between(drawdown.index, drawdown.min(axis=1), 0, alpha=0.3, color='red')
        plt.axhline(y=0, color='black', linestyle='-', linewidth=0.5)
        
        plt.title('Portfolio Drawdowns', fontsize=14, fontweight='bold')
        plt.xlabel('Date')
        plt.ylabel('Drawdown')
        plt.legend()
        plt.grid(True, alpha=0.3)
        
        if save_path:
            Path(save_path).parent.mkdir(parents=True, exist_ok=True)
            plt.savefig(save_path, dpi=300, bbox_inches='tight')
        
        plt.show()
    
    def calculate_rolling_metrics(
        self,
        window: int = 63,  # 3 months
        metric: str = 'sharpe'
    ) -> pd.DataFrame:
        """Calculate rolling risk metrics"""
        if metric == 'sharpe':
            rolling_returns = self.returns_data.rolling(window).mean() * 252
            rolling_std = self.returns_data.rolling(window).std() * np.sqrt(252)
            result = rolling_returns / rolling_std
        elif metric == 'volatility':
            result = self.returns_data.rolling(window).std() * np.sqrt(252)
        elif metric == 'var':
            result = self.returns_data.rolling(window).quantile(0.05)
        else:
            raise ValueError(f"Unknown metric: {metric}")
        
        return result
    
    def stress_test(self, scenarios: Dict[str, float]) -> pd.DataFrame:
        """
        Run stress tests on portfolio
        
        Args:
            scenarios: Dict of scenario name -> market shock percentage
        
        Returns:
            DataFrame with stress test results
        """
        results = []
        
        for scenario_name, shock in scenarios.items():
            # Apply shock to all assets
            shocked_returns = self.returns_data + shock
            
            # Calculate metrics under stress
            total_return = (1 + shocked_returns).prod() - 1
            volatility = shocked_returns.std() * np.sqrt(252)
            max_dd = ((1 + shocked_returns).cumprod() - (1 + shocked_returns).cumprod().expanding().max()).min()
            
            results.append({
                'scenario': scenario_name,
                'shock': shock,
                'total_return': total_return.mean(),
                'volatility': volatility.mean(),
                'max_drawdown': max_dd.mean()
            })
        
        return pd.DataFrame(results)


# Convenience functions
def create_portfolio_report(
    returns_df: pd.DataFrame,
    weights: Optional[np.ndarray] = None,
    output_dir: str = "analytics/outputs"
) -> str:
    """
    Generate complete portfolio analysis report
    
    Args:
        returns_df: DataFrame of asset returns
        weights: Portfolio weights (optional, will optimize if not provided)
        output_dir: Output directory
    
    Returns:
        Path to report file
    """
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    
    # Initialize analytics
    analytics = PortfolioAnalytics()
    analytics.load_returns_data(returns_df)
    
    # Optimize if no weights provided
    if weights is None:
        opt_result = analytics.optimize_portfolio(max_sharpe=True)
        weights = np.array(list(opt_result['weights'].values()))
        print(f"Optimized portfolio - Sharpe: {opt_result['sharpe_ratio']:.2f}")
    
    # Generate correlation matrix
    corr_path = Path(output_dir) / "correlation_matrix.png"
    analytics.calculate_correlation_matrix(save_path=str(corr_path))
    
    # Generate efficient frontier
    ef_path = Path(output_dir) / "efficient_frontier.png"
    analytics.generate_efficient_frontier(save_path=str(ef_path))
    
    # Calculate risk metrics
    metrics = analytics.calculate_risk_metrics(weights)
    
    # Generate report
    report_path = analytics.generate_report(weights, output_dir)
    
    # Risk analysis
    risk_analyzer = RiskAnalyzer(returns_df)
    dd_path = Path(output_dir) / "drawdown_analysis.png"
    risk_analyzer.plot_drawdowns(save_path=str(dd_path))
    
    print(f"\\nPortfolio report complete: {report_path}")
    print(f"Key metrics:")
    print(f"  Sharpe Ratio: {metrics['sharpe_ratio']:.2f}")
    print(f"  Sortino Ratio: {metrics['sortino_ratio']:.2f}")
    print(f"  Max Drawdown: {metrics['max_drawdown']:.2%}")
    print(f"  Calmar Ratio: {metrics['calmar_ratio']:.2f}")
    
    return report_path


if __name__ == "__main__":
    print("HOPEFX Portfolio Analytics Module")
    print("Features:")
    print("  - Multi-asset portfolio optimization")
    print("  - Efficient frontier generation")
    print("  - Correlation analysis")
    print("  - Risk metrics (Sharpe, Sortino, Calmar, Max DD, VaR, CVaR)")
    print("  - Multi-asset backtesting with rebalancing")
    print("  - Stress testing")
    print("  - Rolling performance metrics")
    print("\\nUsage:")
    print("  from analytics.portfolio import PortfolioAnalytics, create_portfolio_report")
    print("  report = create_portfolio_report(returns_df)")
'''

# Save the file
with open('analytics/portfolio.py', 'w') as f:
    f.write(code)

print("✅ Created: analytics/portfolio.py")
print(f"   Lines: {len(code.splitlines())}")
print(f"   Size: {len(code)} bytes")
print("\n📊 Portfolio Analytics Summary:")
print("   ✅ Multi-asset portfolio optimization (max Sharpe, min volatility)")
print("   ✅ Efficient frontier generation with visualization")
print("   ✅ Correlation matrix heatmaps")
print("   ✅ Risk metrics: Sharpe, Sortino, Calmar, Max DD, VaR(95%), CVaR")
print("   ✅ Beta, Treynor ratio, Information ratio")
print("   ✅ Multi-asset backtesting with rebalancing")
print("   ✅ Stress testing scenarios")
print("   ✅ Rolling performance metrics")
print("   ✅ JSON/CSV report generation")

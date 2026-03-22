"""
Comprehensive backtest metrics calculation.
"""

import numpy as np
import pandas as pd
from scipy import stats


class PerformanceMetrics:
    """
    Institutional-grade performance analytics.
    """
    
    @staticmethod
    def calculate_all(equity_curve: pd.Series, trades: list[dict]) -> dict[str, float]:
        """Calculate full metrics suite."""
        returns = equity_curve.pct_change().dropna()
        
        metrics = {
            **PerformanceMetrics.returns_metrics(equity_curve, returns),
            **PerformanceMetrics.risk_metrics(equity_curve, returns),
            **PerformanceMetrics.trade_metrics(trades),
            **PerformanceMetrics.statistical_metrics(returns),
        }
        
        return metrics
    
    @staticmethod
    def returns_metrics(equity: pd.Series, returns: pd.Series) -> dict[str, float]:
        """Return-based metrics."""
        total_return = (equity.iloc[-1] / equity.iloc[0]) - 1
        
        # Annualized return
        years = len(equity) / 252  # Assuming daily data
        cagr = (1 + total_return) ** (1 / years) - 1 if years > 0 else 0
        
        return {
            "total_return": float(total_return),
            "cagr": float(cagr),
            "avg_daily_return": float(returns.mean()),
            "avg_monthly_return": float(returns.mean() * 21),
            "best_day": float(returns.max()),
            "worst_day": float(returns.min()),
        }
    
    @staticmethod
    def risk_metrics(equity: pd.Series, returns: pd.Series) -> dict[str, float]:
        """Risk metrics."""
        # Volatility
        volatility = returns.std() * np.sqrt(252)
        
        # Drawdown
        running_max = equity.cummax()
        drawdown = (equity - running_max) / running_max
        max_dd = drawdown.min()
        
        # Underwater periods
        underwater = drawdown[drawdown < 0]
        avg_underwater = underwater.mean() if len(underwater) > 0 else 0
        
        # VaR/CVaR
        var_95 = np.percentile(returns, 5)
        cvar_95 = returns[returns <= var_95].mean() if len(returns[returns <= var_95]) > 0 else var_95
        
        return {
            "volatility": float(volatility),
            "max_drawdown": float(max_dd),
            "avg_drawdown": float(avg_underwater),
            "var_95": float(var_95),
            "cvar_95": float(cvar_95),
            "downside_deviation": float(returns[returns < 0].std() * np.sqrt(252)),
        }
    
    @staticmethod
    def trade_metrics(trades: list[dict]) -> dict[str, float]:
        """Trade-level metrics."""
        if not trades:
            return {
                "num_trades": 0,
                "win_rate": 0.0,
                "profit_factor": 0.0,
                "avg_trade": 0.0,
            }
        
        # Simplified - in production would track actual P&L per trade
        num_trades = len(trades)
        
        return {
            "num_trades": num_trades,
            "win_rate": 0.5,  # Placeholder
            "profit_factor": 1.2,  # Placeholder
            "avg_trade": 0.0,  # Placeholder
            "avg_holding_period": 0.0,  # Placeholder
        }
    
    @staticmethod
    def statistical_metrics(returns: pd.Series) -> dict[str, float]:
        """Statistical quality metrics."""
        # Sharpe
        sharpe = (returns.mean() / returns.std()) * np.sqrt(252) if returns.std() > 0 else 0
        
        # Sortino
        downside = returns[returns < 0]
        sortino = (returns.mean() / downside.std()) * np.sqrt(252) if len(downside) > 0 and downside.std() > 0 else 0
        
        # Skewness and kurtosis
        skew = stats.skew(returns)
        kurt = stats.kurtosis(returns)
        
        # Omega ratio
        threshold = 0
        upside = returns[returns > threshold].sum()
        downside = abs(returns[returns < threshold].sum())
        omega = upside / downside if downside > 0 else 0
        
        return {
            "sharpe_ratio": float(sharpe),
            "sortino_ratio": float(sortino),
            "skewness": float(skew),
            "kurtosis": float(kurt),
            "omega_ratio": float(omega),
            "tail_ratio": float(abs(np.percentile(returns, 95) / np.percentile(returns, 5))),
        }

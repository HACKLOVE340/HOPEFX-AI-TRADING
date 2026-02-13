"""
Performance Metrics Calculator

Calculates comprehensive trading performance metrics.
"""

import pandas as pd
import numpy as np
from typing import Dict, Optional
import logging

logger = logging.getLogger(__name__)


class PerformanceMetrics:
    """
    Calculate trading performance metrics.
    
    Provides comprehensive performance analysis including returns,
    risk metrics, and trade statistics.
    """
    
    def __init__(self, equity_curve: pd.DataFrame, trade_history: pd.DataFrame,
                 initial_capital: float, risk_free_rate: float = 0.02):
        """
        Initialize metrics calculator.
        
        Args:
            equity_curve: DataFrame with equity over time
            trade_history: DataFrame with individual trades
            initial_capital: Starting capital
            risk_free_rate: Annual risk-free rate (default 2%)
        """
        self.equity_curve = equity_curve
        self.trade_history = trade_history
        self.initial_capital = initial_capital
        self.risk_free_rate = risk_free_rate
        
    def calculate_all_metrics(self) -> Dict:
        """Calculate all available metrics."""
        metrics = {}
        
        # Return metrics
        metrics['total_return'] = self.calculate_total_return()
        metrics['annual_return'] = self.calculate_annual_return()
        metrics['monthly_return'] = self.calculate_monthly_return()
        
        # Risk metrics
        metrics['sharpe_ratio'] = self.calculate_sharpe_ratio()
        metrics['sortino_ratio'] = self.calculate_sortino_ratio()
        metrics['max_drawdown'] = self.calculate_max_drawdown()
        metrics['calmar_ratio'] = self.calculate_calmar_ratio()
        metrics['volatility'] = self.calculate_volatility()
        
        # Trade statistics
        metrics['total_trades'] = self.calculate_total_trades()
        metrics['winning_trades'] = self.calculate_winning_trades()
        metrics['losing_trades'] = self.calculate_losing_trades()
        metrics['win_rate'] = self.calculate_win_rate()
        metrics['profit_factor'] = self.calculate_profit_factor()
        metrics['avg_win'] = self.calculate_avg_win()
        metrics['avg_loss'] = self.calculate_avg_loss()
        metrics['largest_win'] = self.calculate_largest_win()
        metrics['largest_loss'] = self.calculate_largest_loss()
        metrics['avg_trade_duration'] = self.calculate_avg_trade_duration()
        
        # Portfolio metrics
        metrics['final_equity'] = self.equity_curve['equity'].iloc[-1] if not self.equity_curve.empty else self.initial_capital
        metrics['peak_equity'] = self.equity_curve['equity'].max() if not self.equity_curve.empty else self.initial_capital
        
        return metrics
        
    def calculate_total_return(self) -> float:
        """Calculate total return percentage."""
        if self.equity_curve.empty:
            return 0.0
        final_equity = self.equity_curve['equity'].iloc[-1]
        return ((final_equity - self.initial_capital) / self.initial_capital) * 100
        
    def calculate_annual_return(self) -> float:
        """Calculate annualized return."""
        if self.equity_curve.empty or len(self.equity_curve) < 2:
            return 0.0
            
        days = (self.equity_curve.index[-1] - self.equity_curve.index[0]).days
        if days == 0:
            return 0.0
            
        years = days / 365.25
        total_return = self.calculate_total_return() / 100
        
        return ((1 + total_return) ** (1 / years) - 1) * 100
        
    def calculate_monthly_return(self) -> float:
        """Calculate average monthly return."""
        annual = self.calculate_annual_return()
        return annual / 12
        
    def calculate_sharpe_ratio(self) -> float:
        """Calculate Sharpe ratio."""
        if self.equity_curve.empty or len(self.equity_curve) < 2:
            return 0.0
            
        returns = self.equity_curve['equity'].pct_change().dropna()
        
        if returns.std() == 0:
            return 0.0
            
        excess_returns = returns - (self.risk_free_rate / 252)  # Daily risk-free rate
        
        return np.sqrt(252) * (excess_returns.mean() / returns.std())
        
    def calculate_sortino_ratio(self) -> float:
        """Calculate Sortino ratio (downside deviation)."""
        if self.equity_curve.empty or len(self.equity_curve) < 2:
            return 0.0
            
        returns = self.equity_curve['equity'].pct_change().dropna()
        downside_returns = returns[returns < 0]
        
        if len(downside_returns) == 0 or downside_returns.std() == 0:
            return 0.0
            
        excess_returns = returns - (self.risk_free_rate / 252)
        
        return np.sqrt(252) * (excess_returns.mean() / downside_returns.std())
        
    def calculate_max_drawdown(self) -> float:
        """Calculate maximum drawdown percentage."""
        if self.equity_curve.empty:
            return 0.0
            
        equity = self.equity_curve['equity']
        cummax = equity.cummax()
        drawdown = (equity - cummax) / cummax * 100
        
        return drawdown.min()
        
    def calculate_calmar_ratio(self) -> float:
        """Calculate Calmar ratio (annual return / max drawdown)."""
        annual_return = self.calculate_annual_return()
        max_dd = abs(self.calculate_max_drawdown())
        
        if max_dd == 0:
            return 0.0
            
        return annual_return / max_dd
        
    def calculate_volatility(self) -> float:
        """Calculate annualized volatility."""
        if self.equity_curve.empty or len(self.equity_curve) < 2:
            return 0.0
            
        returns = self.equity_curve['equity'].pct_change().dropna()
        return returns.std() * np.sqrt(252) * 100
        
    def calculate_total_trades(self) -> int:
        """Calculate total number of trades."""
        return len(self.trade_history)
        
    def calculate_winning_trades(self) -> int:
        """Calculate number of winning trades."""
        if self.trade_history.empty:
            return 0
        return len(self.trade_history[self.trade_history['pnl'] > 0])
        
    def calculate_losing_trades(self) -> int:
        """Calculate number of losing trades."""
        if self.trade_history.empty:
            return 0
        return len(self.trade_history[self.trade_history['pnl'] < 0])
        
    def calculate_win_rate(self) -> float:
        """Calculate win rate percentage."""
        total = self.calculate_total_trades()
        if total == 0:
            return 0.0
        winning = self.calculate_winning_trades()
        return (winning / total) * 100
        
    def calculate_profit_factor(self) -> float:
        """Calculate profit factor (gross profit / gross loss)."""
        if self.trade_history.empty:
            return 0.0
            
        gross_profit = self.trade_history[self.trade_history['pnl'] > 0]['pnl'].sum()
        gross_loss = abs(self.trade_history[self.trade_history['pnl'] < 0]['pnl'].sum())
        
        if gross_loss == 0:
            return float('inf') if gross_profit > 0 else 0.0
            
        return gross_profit / gross_loss
        
    def calculate_avg_win(self) -> float:
        """Calculate average winning trade."""
        if self.trade_history.empty:
            return 0.0
        winning_trades = self.trade_history[self.trade_history['pnl'] > 0]['pnl']
        return winning_trades.mean() if len(winning_trades) > 0 else 0.0
        
    def calculate_avg_loss(self) -> float:
        """Calculate average losing trade."""
        if self.trade_history.empty:
            return 0.0
        losing_trades = self.trade_history[self.trade_history['pnl'] < 0]['pnl']
        return losing_trades.mean() if len(losing_trades) > 0 else 0.0
        
    def calculate_largest_win(self) -> float:
        """Calculate largest winning trade."""
        if self.trade_history.empty:
            return 0.0
        winning_trades = self.trade_history[self.trade_history['pnl'] > 0]['pnl']
        return winning_trades.max() if len(winning_trades) > 0 else 0.0
        
    def calculate_largest_loss(self) -> float:
        """Calculate largest losing trade."""
        if self.trade_history.empty:
            return 0.0
        losing_trades = self.trade_history[self.trade_history['pnl'] < 0]['pnl']
        return losing_trades.min() if len(losing_trades) > 0 else 0.0
        
    def calculate_avg_trade_duration(self) -> Optional[float]:
        """Calculate average trade duration in days."""
        # This would require entry/exit timestamps in trade history
        # Simplified implementation
        return None

# backtesting/walk_forward.py
"""
HOPEFX Walk-Forward Backtesting Engine
Prevents overfitting with rolling train/test splits
"""

import pandas as pd
import numpy as np
from typing import List, Dict, Callable, Optional, Tuple
from dataclasses import dataclass
from datetime import datetime, timedelta


@dataclass
class WalkForwardResult:
    """Results from walk-forward test"""
    train_start: datetime
    train_end: datetime
    test_start: datetime
    test_end: datetime
    train_performance: Dict
    test_performance: Dict
    parameter_values: Dict
    is_overfit: bool


class WalkForwardEngine:
    """
    Walk-forward optimization with purged cross-validation.
    The gold standard for strategy validation.
    """
    
    def __init__(self, 
                 train_size: int = 1000,
                 test_size: int = 200,
                 purge_size: int = 50,  # Embargo period
                 step_size: int = 200):
        self.train_size = train_size
        self.test_size = test_size
        self.purge_size = purge_size
        self.step_size = step_size
        self.results: List[WalkForwardResult] = []
    
    def run(self, 
           data: pd.DataFrame,
           strategy_factory: Callable,
           parameter_grid: List[Dict]) -> List[WalkForwardResult]:
        """
        Run walk-forward optimization.
        
        Args:
            data: Price data with datetime index
            strategy_factory: Function that creates strategy with parameters
            parameter_grid: List of parameter sets to test
        """
        n_samples = len(data)
        window_start = 0
        
        while window_start + self.train_size + self.purge_size + self.test_size <= n_samples:
            # Define windows with purge/embargo
            train_start = window_start
            train_end = train_start + self.train_size
            purge_start = train_end
            purge_end = purge_start + self.purge_size
            test_start = purge_end
            test_end = test_start + self.test_size
            
            # Extract data
            train_data = data.iloc[train_start:train_end]
            purge_data = data.iloc[purge_start:purge_end]  # Not used (embargo)
            test_data = data.iloc[test_start:test_end]
            
            print(f"\nWindow: Train {train_start}-{train_end}, "
                  f"Test {test_start}-{test_end} (purge: {purge_start}-{purge_end})")
            
            # Optimize on training data
            best_params, train_perf = self._optimize_parameters(
                train_data, strategy_factory, parameter_grid
            )
            
            # Test on out-of-sample data
            test_strategy = strategy_factory(**best_params)
            test_perf = self._evaluate_strategy(test_data, test_strategy)
            
            # Check for overfitting
            is_overfit = self._detect_overfit(train_perf, test_perf)
            
            result = WalkForwardResult(
                train_start=data.index[train_start],
                train_end=data.index[train_end],
                test_start=data.index[test_start],
                test_end=data.index[test_end],
                train_performance=train_perf,
                test_performance=test_perf,
                parameter_values=best_params,
                is_overfit=is_overfit
            )
            
            self.results.append(result)
            
            # Move window
            window_start += self.step_size
        
        return self.results
    
    def _optimize_parameters(self, 
                            train_data: pd.DataFrame,
                            strategy_factory: Callable,
                            parameter_grid: List[Dict]) -> Tuple[Dict, Dict]:
        """Find best parameters on training data"""
        best_score = -np.inf
        best_params = None
        best_perf = None
        
        for params in parameter_grid:
            strategy = strategy_factory(**params)
            performance = self._evaluate_strategy(train_data, strategy)
            
            score = performance.get('sharpe_ratio', 0)
            
            if score > best_score:
                best_score = score
                best_params = params
                best_perf = performance
        
        return best_params, best_perf
    
    def _evaluate_strategy(self, data: pd.DataFrame, strategy) -> Dict:
        """Evaluate strategy performance"""
        trades = []
        position = 0
        equity = [1.0]
        
        for i, row in data.iterrows():
            # Generate signal
            signal = strategy.on_tick(row)
            
            if signal and signal['action'] in ['BUY', 'SELL']:
                # Simulate execution
                trade = {
                    'timestamp': i,
                    'action': signal['action'],
                    'price': row['close'],
                    'size': 1.0
                }
                trades.append(trade)
                
                # Update position
                if signal['action'] == 'BUY':
                    position += 1
                else:
                    position -= 1
            
            # Mark to market
            pnl = position * (row['close'] - data.iloc[0]['close']) / data.iloc[0]['close']
            equity.append(1.0 + pnl)
        
        # Calculate metrics
        returns = pd.Series(equity).pct_change().dropna()
        
        return {
            'total_return': equity[-1] - 1,
            'sharpe_ratio': returns.mean() / returns.std() * np.sqrt(252) if len(returns) > 1 else 0,
            'max_drawdown': self._calculate_max_drawdown(equity),
            'num_trades': len(trades),
            'win_rate': len([t for t in trades if t.get('pnl', 0) > 0]) / len(trades) if trades else 0
        }
    
    def _calculate_max_drawdown(self, equity: List[float]) -> float:
        """Calculate maximum drawdown"""
        peak = equity[0]
        max_dd = 0
        
        for value in equity:
            if value > peak:
                peak = value
            dd = (peak - value) / peak
            if dd > max_dd:
                max_dd = dd
        
        return max_dd
    
    def _detect_overfit(self, train_perf: Dict, test_perf: Dict) -> bool:
        """Detect if strategy is overfit"""
        # Sharpe ratio degradation
        train_sharpe = train_perf.get('sharpe_ratio', 0)
        test_sharpe = test_perf.get('sharpe_ratio', 0)
        
        if train_sharpe > 0 and test_sharpe < train_sharpe * 0.5:
            return True
        
        # Return degradation
        train_return = train_perf.get('total_return', 0)
        test_return = test_perf.get('total_return', 0)
        
        if train_return > 0 and test_return < train_return * 0.3:
            return True
        
        return False
    
    def get_aggregate_stats(self) -> Dict:
        """Aggregate statistics across all windows"""
        if not self.results:
            return {}
        
        test_returns = [r.test_performance.get('total_return', 0) for r in self.results]
        test_sharpes = [r.test_performance.get('sharpe_ratio', 0) for r in self.results]
        
        return {
            'num_windows': len(self.results),
            'overfit_windows': sum(1 for r in self.results if r.is_overfit),
            'avg_test_return': np.mean(test_returns),
            'avg_test_sharpe': np.mean(test_sharpes),
            'consistency': 1 - np.std(test_returns) / (np.mean(test_returns) + 1e-10),
            'is_robust': np.mean(test_sharpes) > 0.5 and sum(1 for r in self.results if r.is_overfit) < len(self.results) * 0.3
        }

WalkForwardAnalysis = WalkForwardEngine

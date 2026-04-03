# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
Parameter Optimizer for Backtesting

Optimizes strategy parameters using grid search and other methods.
"""

import itertools
import logging
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)


class ParameterOptimizer:
    """
    Optimize strategy parameters through systematic search.
    """

    def __init__(self, strategy_class, data_handler, initial_capital: float = 100000.0):
        """
        Initialize optimizer.

        Args:
            strategy_class: Strategy class to optimize
            data_handler: DataHandler instance
            initial_capital: Starting capital for backtests
        """
        self.strategy_class = strategy_class
        self.data_handler = data_handler
        self.initial_capital = initial_capital

        logger.info("Initialized parameter optimizer for %s", strategy_class.__name__)

    def grid_search(self, param_grid: dict[str, list[Any]], metric: str = "sharpe_ratio") -> dict:
        """
        Perform grid search over parameter space.

        Args:
            param_grid: Dict of parameter names to lists of values
            metric: Metric to optimize

        Returns:
            Dict with best parameters and results
        """
        from backtesting.engine import BacktestEngine

        # Generate all parameter combinations
        param_names = list(param_grid.keys())
        param_values = list(param_grid.values())
        combinations = list(itertools.product(*param_values))

        logger.info("Testing %s parameter combinations...", len(combinations))

        results = []
        best_score = float("-inf")
        best_params = None

        for combination in combinations:
            params = dict(zip(param_names, combination, strict=False))

            try:
                # Create strategy with these parameters
                self.strategy_class(**params)

                # Run backtest using the strategy's signal generator
                engine = BacktestEngine(initial_capital=self.initial_capital)

                data = self.data_handler.get_data() if hasattr(self.data_handler, "get_data") else None
                if data is None or data.empty:
                    continue
                backtest_result = engine.run_backtest(data, signals=strategy)
                backtest_results = {
                    "metrics": {
                        "sharpe_ratio": backtest_result.sharpe_ratio,
                        "total_return": backtest_result.total_return,
                        "max_drawdown": backtest_result.max_drawdown,
                    }
                }
                score = backtest_results["metrics"].get(metric, 0)

                results.append(
                    {
                        "params": params,
                        "score": score,
                        "metrics": backtest_results["metrics"],
                    }
                )

                if score > best_score:
                    best_score = score
                    best_params = params

                logger.debug("Params: %s, %s: %s", params, metric, score)

            except Exception as e:
                logger.error("Error testing params %s: %s", params, e)

        logger.info("Best %s: %s with params: %s", metric, best_score, best_params)

        return {
            "best_params": best_params,
            "best_score": best_score,
            "all_results": pd.DataFrame(results),
        }

# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
# backtesting/walk_forward.py
"""
HOPEFX Walk-Forward Backtesting Engine
Prevents overfitting with rolling train/test splits
"""

import logging
import math
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


@dataclass
class WalkForwardResult:
    """Results from walk-forward test"""

    train_start: datetime
    train_end: datetime
    test_start: datetime
    test_end: datetime
    train_performance: dict
    test_performance: dict
    parameter_values: dict
    is_overfit: bool


class WalkForwardEngine:
    """
    Walk-forward optimization with purged cross-validation.
    The gold standard for strategy validation.
    """

    def __init__(
        self,
        train_size: int = 1000,
        test_size: int = 200,
        purge_size: int = 50,  # Embargo period
        step_size: int = 200,
    ):
        self.train_size = train_size
        self.test_size = test_size
        self.purge_size = purge_size
        self.step_size = step_size
        self.results: list[WalkForwardResult] = []

    def run(
        self,
        data: pd.DataFrame,
        strategy_factory: Callable[..., Any],
        parameter_grid: list[dict[str, Any]],
    ) -> list[WalkForwardResult]:
        """
        Run walk-forward optimization.

        Args:
            data: Price data with datetime index.
            strategy_factory: Callable that accepts parameter kwargs and returns a strategy.
            parameter_grid: List of parameter dicts to evaluate on each training window.
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

            # Extract data (purge_start:purge_end is the embargo gap between train and test)
            train_data = data.iloc[train_start:train_end]
            test_data = data.iloc[test_start:test_end]

            logger.info(
                "Window: Train %d-%d, Test %d-%d (purge: %d-%d)",
                train_start,
                train_end,
                test_start,
                test_end,
                purge_start,
                purge_end,
            )

            # Optimize on training data
            best_params, train_perf = self._optimize_parameters(train_data, strategy_factory, parameter_grid)

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
                is_overfit=is_overfit,
            )

            self.results.append(result)

            # Move window
            window_start += self.step_size

        return self.results

    def _optimize_parameters(
        self,
        train_data: pd.DataFrame,
        strategy_factory: Callable[..., Any],
        parameter_grid: list[dict[str, Any]],
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """Find best parameters on training data."""
        best_score = -np.inf
        best_params = None
        best_perf = None

        for params in parameter_grid:
            strategy = strategy_factory(**params)
            performance = self._evaluate_strategy(train_data, strategy)

            score = performance.get("sharpe_ratio", 0)

            if score > best_score:
                best_score = score
                best_params = params
                best_perf = performance

        return best_params, best_perf

    def _evaluate_strategy(self, data: pd.DataFrame, strategy: Any) -> dict[str, Any]:
        """
        Evaluate strategy performance using trade-level metrics.

        Sharpe is computed at trade level — mean(net_pnl) / std(net_pnl) *
        sqrt(252 / avg_hold_days) — not at bar level.  Bar-level Sharpe is
        inflated 3-5x on daily-bar strategies because flat no-trade bars
        suppress the return standard deviation.
        """
        completed_trades: list[dict] = []
        open_trades: list[dict] = []   # stack of open positions
        equity = [1.0]
        position = 0
        bar_idx = 0

        for i, row in data.iterrows():
            signal = strategy.on_tick(row)

            if signal and signal["action"] in ["BUY", "SELL"]:
                price = float(row["close"])

                if signal["action"] == "BUY":
                    open_trades.append({"entry_price": price, "entry_bar": bar_idx, "side": "long"})
                    position += 1
                else:
                    # Close the oldest open long, or open a short
                    long_open = [t for t in open_trades if t["side"] == "long"]
                    if long_open:
                        entry = long_open[0]
                        open_trades.remove(entry)
                        hold_bars = max(1, bar_idx - entry["entry_bar"])
                        pnl_pct = (price - entry["entry_price"]) / entry["entry_price"]
                        completed_trades.append(
                            {
                                "pnl_pct": pnl_pct,
                                "hold_bars": hold_bars,
                                "win": pnl_pct > 0,
                            }
                        )
                    else:
                        open_trades.append({"entry_price": price, "entry_bar": bar_idx, "side": "short"})
                    position -= 1

            # Mark to market for equity curve and drawdown
            ref_price = float(data.iloc[0]["close"])
            cur_price = float(row["close"])
            pnl = position * (cur_price - ref_price) / ref_price
            equity.append(1.0 + pnl)
            bar_idx += 1

        # Force-close any remaining open positions at last bar price
        last_price = float(data.iloc[-1]["close"])
        for entry in open_trades:
            hold_bars = max(1, bar_idx - entry["entry_bar"])
            if entry["side"] == "long":
                pnl_pct = (last_price - entry["entry_price"]) / entry["entry_price"]
            else:
                pnl_pct = (entry["entry_price"] - last_price) / entry["entry_price"]
            completed_trades.append({"pnl_pct": pnl_pct, "hold_bars": hold_bars, "win": pnl_pct > 0})

        # ── Trade-level Sharpe (corrected) ────────────────────────────────
        sharpe = _trade_level_sharpe(completed_trades)

        n = len(completed_trades)
        win_rate = sum(1 for t in completed_trades if t["win"]) / n if n > 0 else 0.0

        return {
            "total_return": equity[-1] - 1.0,
            "sharpe_ratio": sharpe,
            "max_drawdown": self._calculate_max_drawdown(equity),
            "num_trades": n,
            "win_rate": win_rate,
        }

    def _calculate_max_drawdown(self, equity: list[float]) -> float:
        """Calculate maximum drawdown."""
        peak = equity[0]
        max_dd = 0

        for value in equity:
            peak = max(peak, value)
            dd = (peak - value) / peak
            max_dd = max(max_dd, dd)

        return max_dd

    def _detect_overfit(self, train_perf: dict[str, Any], test_perf: dict[str, Any]) -> bool:
        """Detect if strategy is overfit."""
        # Sharpe ratio degradation
        train_sharpe = train_perf.get("sharpe_ratio", 0)
        test_sharpe = test_perf.get("sharpe_ratio", 0)

        if train_sharpe > 0 and test_sharpe < train_sharpe * 0.5:
            return True

        # Return degradation
        train_return = train_perf.get("total_return", 0)
        test_return = test_perf.get("total_return", 0)

        return train_return > 0 and test_return < train_return * 0.3

    def get_aggregate_stats(self) -> dict[str, Any]:
        """Aggregate statistics across all windows."""
        if not self.results:
            return {}

        test_returns = [r.test_performance.get("total_return", 0) for r in self.results]
        test_sharpes = [r.test_performance.get("sharpe_ratio", 0) for r in self.results]

        return {
            "num_windows": len(self.results),
            "overfit_windows": sum(1 for r in self.results if r.is_overfit),
            "avg_test_return": np.mean(test_returns),
            "avg_test_sharpe": np.mean(test_sharpes),
            "consistency": 1 - np.std(test_returns) / (np.mean(test_returns) + 1e-10),
            "is_robust": np.mean(test_sharpes) > 0.5
            and sum(1 for r in self.results if r.is_overfit) < len(self.results) * 0.3,
        }


def _trade_level_sharpe(trades: list[dict], bars_per_day: int = 1) -> float:
    """
    Compute annualised trade-level Sharpe ratio.

    Formula: mean(pnl_pct) / std(pnl_pct) * sqrt(252 / avg_hold_days)

    Uses pnl_pct (return per trade) rather than absolute PnL so the ratio
    is position-size independent.  avg_hold_days is derived from hold_bars
    and bars_per_day so the annualisation factor is correct for any bar
    frequency (D1, H4, H1, etc.).

    Returns 0.0 when fewer than 2 trades are available.
    """
    if len(trades) < 2:
        return 0.0
    pnls = np.array([t["pnl_pct"] for t in trades], dtype=float)
    std = float(np.std(pnls, ddof=1))
    if abs(std) < 1e-12:
        return 0.0
    hold_bars = np.array([t.get("hold_bars", bars_per_day) for t in trades], dtype=float)
    avg_hold_days = float(np.mean(hold_bars)) / max(bars_per_day, 1)
    ann_factor = math.sqrt(252.0 / max(avg_hold_days, 1.0 / 252))
    return float(np.mean(pnls) / std * ann_factor)


WalkForwardAnalysis = WalkForwardEngine

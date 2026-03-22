"""
Backtesting engine — runs signal-based backtests on OHLCV DataFrames.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class BacktestResult:
    total_return: float
    sharpe_ratio: float
    max_drawdown: float
    win_rate: float
    total_trades: int
    equity_curve: List[float] = field(default_factory=list)
    trades: List[dict] = field(default_factory=list)


class BacktestEngine:
    """
    Simple vectorised backtester.

    Signals: +1 = long, -1 = short, 0 = flat.
    Positions are sized as a fixed fraction of equity (default 10%).
    """

    def __init__(
        self,
        initial_balance: float = 100_000.0,
        position_size_pct: float = 0.10,
        commission_pct: float = 0.0002,
    ):
        self.initial_balance = initial_balance
        self.balance = initial_balance
        self.position_size_pct = position_size_pct
        self.commission_pct = commission_pct
        self.trades: List[dict] = []
        self.equity_curve: List[float] = [initial_balance]

    # ------------------------------------------------------------------
    def run_backtest(
        self,
        data: pd.DataFrame,
        signals,          # pd.Series or callable(data) -> pd.Series
    ) -> BacktestResult:
        """
        Run a backtest.

        Parameters
        ----------
        data    : OHLCV DataFrame with columns open/high/low/close/volume
        signals : pd.Series of {-1, 0, 1} aligned to data.index,
                  OR a callable that receives data and returns such a Series
        """
        if callable(signals):
            signals = signals(data)

        signals = pd.Series(signals, index=data.index).fillna(0)

        # Reset state
        self.balance = self.initial_balance
        self.trades = []
        equity = [self.initial_balance]

        position = 0        # current position size (units)
        entry_price = 0.0
        entry_signal = 0

        for i in range(1, len(data)):
            prev_sig = signals.iloc[i - 1]
            price    = data["close"].iloc[i]
            prev_price = data["close"].iloc[i - 1]

            # Close existing position on signal flip or exit
            if position != 0 and (prev_sig == 0 or prev_sig != entry_signal):
                pnl = position * (price - entry_price)
                commission = abs(position) * price * self.commission_pct
                net_pnl = pnl - commission
                self.balance += net_pnl
                self.trades.append({
                    "entry_price": entry_price,
                    "exit_price":  price,
                    "size":        position,
                    "pnl":         net_pnl,
                    "win":         net_pnl > 0,
                })
                position = 0

            # Open new position
            if prev_sig != 0 and position == 0:
                size = (self.balance * self.position_size_pct) / price
                position = size if prev_sig == 1 else -size
                entry_price  = price
                entry_signal = prev_sig

            equity.append(self.balance)

        # Force-close at end
        if position != 0:
            price = data["close"].iloc[-1]
            pnl = position * (price - entry_price)
            commission = abs(position) * price * self.commission_pct
            net_pnl = pnl - commission
            self.balance += net_pnl
            self.trades.append({
                "entry_price": entry_price,
                "exit_price":  price,
                "size":        position,
                "pnl":         net_pnl,
                "win":         net_pnl > 0,
            })
            equity[-1] = self.balance

        self.equity_curve = equity

        # Metrics
        eq = np.array(equity, dtype=float)
        total_return = (eq[-1] - eq[0]) / eq[0]

        daily_ret = np.diff(eq) / eq[:-1]
        sharpe = (
            float(np.mean(daily_ret) / np.std(daily_ret) * np.sqrt(252))
            if np.std(daily_ret) > 0 else 0.0
        )

        roll_max = np.maximum.accumulate(eq)
        drawdowns = (eq - roll_max) / roll_max
        max_drawdown = float(drawdowns.min())

        n = len(self.trades)
        win_rate = sum(1 for t in self.trades if t["win"]) / n if n > 0 else 0.0

        return BacktestResult(
            total_return=float(total_return),
            sharpe_ratio=float(sharpe),
            max_drawdown=float(max_drawdown),
            win_rate=float(win_rate),
            total_trades=n,
            equity_curve=equity,
            trades=self.trades,
        )

    # ------------------------------------------------------------------
    def monte_carlo_analysis(self, n_simulations: int = 1000) -> dict:
        """
        Bootstrap-resample trade PnLs to estimate return distribution.
        Returns empty dict if no trades have been run.
        """
        if not self.trades:
            return {}

        pnls = np.array([t["pnl"] for t in self.trades])
        sim_returns = []

        rng = np.random.default_rng(42)
        for _ in range(n_simulations):
            sample = rng.choice(pnls, size=len(pnls), replace=True)
            total = float(np.sum(sample) / self.initial_balance)
            sim_returns.append(total)

        sim_returns = np.array(sim_returns)
        return {
            "mean_return":   float(np.mean(sim_returns)),
            "std_return":    float(np.std(sim_returns)),
            "percentile_5":  float(np.percentile(sim_returns, 5)),
            "percentile_95": float(np.percentile(sim_returns, 95)),
            "n_simulations": n_simulations,
        }


# Alias kept for backward compatibility
Backtest = BacktestEngine

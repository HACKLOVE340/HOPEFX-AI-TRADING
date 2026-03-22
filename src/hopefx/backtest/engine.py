from __future__ import annotations

import asyncio
from dataclasses import dataclass
from decimal import Decimal
from typing import Callable

import numpy as np
import pandas as pd
import structlog

from hopefx.config.settings import settings
from hopefx.data.feature_store import FeatureStore
from hopefx.events.schemas import TickData
from hopefx.risk.sizing import PositionSizer

logger = structlog.get_logger()


@dataclass
class BacktestConfig:
    initial_capital: Decimal = Decimal("100000")
    commission_per_lot: Decimal = Decimal("3.5")  # XAUUSD typical
    spread: Decimal = Decimal("0.02")  # Typical spread
    slippage_model: str = "uniform"  # uniform, normal
    allow_partial_fills: bool = True


@dataclass
class Trade:
    entry_time: pd.Timestamp
    exit_time: pd.Timestamp | None
    symbol: str
    side: str
    entry_price: Decimal
    exit_price: Decimal | None
    qty: Decimal
    pnl: Decimal = Decimal("0")
    commission: Decimal = Decimal("0")
    exit_reason: str = ""


class EventDrivenBacktest:
    """High-fidelity event-driven backtesting."""

    def __init__(self, config: BacktestConfig | None = None) -> None:
        self.config = config or BacktestConfig()
        self.equity_curve: list[tuple[pd.Timestamp, Decimal]] = []
        self.trades: list[Trade] = []
        self._current_equity = self.config.initial_capital
        self._cash = self.config.initial_capital
        self._position: Trade | None = None
        self._feature_store = FeatureStore()

    async def run(
        self,
        ticks: list[TickData],
        strategy: Callable[[TickData, dict], str | None],
    ) -> dict:
        """Run backtest on tick data."""
        logger.info("backtest.started", ticks=len(ticks))

        for tick in ticks:
            # Update features
            await self._feature_store._on_tick(
                type("Event", (), {"payload": tick})()
            )

            features = self._feature_store.get_latest_features(tick.symbol)
            if not features:
                continue

            # Get strategy signal
            signal = strategy(tick, features.features)

            # Execute signal
            if signal == "buy" and not self._position:
                await self._open_position(tick, "buy")
            elif signal == "sell" and not self._position:
                await self._open_position(tick, "sell")
            elif signal == "close" and self._position:
                await self._close_position(tick, "signal")

            # Check stop loss / take profit
            if self._position:
                await self._check_exits(tick)

            # Record equity
            self.equity_curve.append((pd.Timestamp(tick.timestamp), self._current_equity))

        # Close any open position at end
        if self._position and ticks:
            await self._close_position(ticks[-1], "end_of_data")

        return self._compute_metrics()

    async def _open_position(self, tick: TickData, side: str) -> None:
        """Open position."""
        # Apply slippage
        fill_price = self._apply_slippage(tick.ask if side == "buy" else tick.bid, side)

        # Position sizing
        sizer = PositionSizer()
        qty = sizer.calculate(
            equity=self._current_equity,
            risk_per_trade=Decimal("0.01"),
            stop_loss=Decimal("0.5"),
            symbol=tick.symbol,
        )

        commission = qty * self.config.commission_per_lot

        self._position = Trade(
            entry_time=pd.Timestamp(tick.timestamp),
            exit_time=None,
            symbol=tick.symbol,
            side=side,
            entry_price=fill_price,
            exit_price=None,
            qty=qty,
            commission=commission,
        )

        self._cash -= commission

    async def _close_position(self, tick: TickData, reason: str) -> None:
        """Close position."""
        if not self._position:
            return

        # Apply slippage and spread
        if self._position.side == "buy":
            fill_price = self._apply_slippage(tick.bid, "sell")
        else:
            fill_price = self._apply_slippage(tick.ask, "buy")

        # Calculate P&L
        if self._position.side == "buy":
            pnl = (fill_price - self._position.entry_price) * self._position.qty
        else:
            pnl = (self._position.entry_price - fill_price) * self._position.qty

        commission = self._position.qty * self.config.commission_per_lot

        self._position.exit_time = pd.Timestamp(tick.timestamp)
        self._position.exit_price = fill_price
        self._position.pnl = pnl - self._position.commission - commission
        self._position.exit_reason = reason

        self.trades.append(self._position)

        # Update equity
        self._current_equity += self._position.pnl
        self._cash = self._current_equity
        self._position = None

    async def _check_exits(self, tick: TickData) -> None:
        """Check stop loss and take profit."""
        if not self._position:
            return

        # Simple stop loss check (50 pips default)
        stop_distance = Decimal("0.5")

        if self._position.side == "buy":
            if tick.bid <= self._position.entry_price - stop_distance:
                await self._close_position(tick, "stop_loss")
        else:
            if tick.ask >= self._position.entry_price + stop_distance:
                await self._close_position(tick, "stop_loss")

    def _apply_slippage(self, price: Decimal, side: str) -> Decimal:
        """Apply realistic slippage."""
        if self.config.slippage_model == "uniform":
            slip = Decimal(str(np.random.uniform(-0.01, 0.01)))
        else:
            slip = Decimal(str(np.random.normal(0, 0.005)))

        if side == "buy":
            return price + slip
        return price - slip

    def _compute_metrics(self) -> dict:
        """Compute performance metrics."""
        if not self.trades:
            return {"error": "No trades executed"}

        pnls = [float(t.pnl) for t in self.trades]
        returns = pd.Series(pnls).cumsum()

        winning_trades = [p for p in pnls if p > 0]
        losing_trades = [p for p in pnls if p < 0]

        total_return = sum(pnls)
        equity_series = pd.Series([e for _, e in self.equity_curve])

        # Max drawdown
        rolling_max = equity_series.expanding().max()
        drawdown = (equity_series - rolling_max) / rolling_max
        max_dd = drawdown.min()

        # Sharpe (simplified, assuming risk-free rate 0)
        if len(pnls) > 1:
            sharpe = np.mean(pnls) / (np.std(pnls) + 1e-10) * np.sqrt(252)
        else:
            sharpe = 0

        return {
            "total_return": total_return,
            "total_trades": len(self.trades),
            "winning_trades": len(winning_trades),
            "losing_trades": len(losing_trades),
            "win_rate": len(winning_trades) / len(self.trades) if self.trades else 0,
            "profit_factor": abs(sum(winning_trades) / sum(losing_trades)) if losing_trades else float('inf'),
            "max_drawdown": float(max_dd),
            "sharpe_ratio": float(sharpe),
            "avg_trade": np.mean(pnls),
            "final_equity": float(self._current_equity),
        }

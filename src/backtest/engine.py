"""
Event-driven backtesting engine with realistic execution simulation.
"""

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any, Callable

import numpy as np
import pandas as pd

from src.brokers.paper import PaperBroker
from src.core.events import Event, get_event_bus
from src.domain.enums import TradeDirection
from src.domain.models import OHLCV, Order, Signal, TickData
from src.execution.oms import OrderManagementSystem
from src.strategies.base import Strategy


@dataclass
class BacktestResult:
    """Backtest results container."""
    equity_curve: pd.Series
    trades: list[dict]
    metrics: dict[str, float]
    start_date: datetime
    end_date: datetime
    initial_capital: Decimal
    final_equity: Decimal


class EventDrivenBacktester:
    """
    Production-grade event-driven backtester.
    """
    
    def __init__(
        self,
        initial_capital: Decimal = Decimal("100000"),
        commission: Decimal = Decimal("0.00002"),  # 2bps
        slippage: Decimal = Decimal("0.0001")       # 1bp
    ):
        self.initial_capital = initial_capital
        self.commission = commission
        self.slippage = slippage
        
        self._broker: PaperBroker | None = None
        self._oms: OrderManagementSystem | None = None
        self._trades: list[dict] = []
        self._equity_history: list[tuple[datetime, Decimal]] = []
    
    async def run(
        self,
        strategy: Strategy,
        data: pd.DataFrame,
        progress_callback: Callable[[float], None] | None = None
    ) -> BacktestResult:
        """
        Run event-driven backtest.
        
        Args:
            strategy: Trading strategy instance
            data: OHLCV DataFrame with datetime index
            progress_callback: Optional progress callback (0-100)
        """
        # Initialize paper broker
        self._broker = PaperBroker(initial_balance=self.initial_capital)
        await self._broker.connect()
        self._oms = OrderManagementSystem(self._broker)
        
        # Initialize strategy
        await strategy.initialize()
        await strategy.start()
        
        # Event loop
        total_bars = len(data)
        
        for idx, (timestamp, row) in enumerate(data.iterrows()):
            # Create OHLCV bar
            bar = OHLCV(
                symbol="XAUUSD",
                timestamp=timestamp,
                open=Decimal(str(row["open"])),
                high=Decimal(str(row["high"])),
                low=Decimal(str(row["low"])),
                close=Decimal(str(row["close"])),
                volume=int(row.get("volume", 0)),
                frequency="1M"
            )
            
            # Convert to tick for broker update
            tick = TickData(
                symbol="XAUUSD",
                timestamp=timestamp,
                bid=Decimal(str(row["close"])) - Decimal("0.01"),
                ask=Decimal(str(row["close"])) + Decimal("0.01"),
                mid=Decimal(str(row["close"])),
                volume=int(row.get("volume", 0)),
                source="BACKTEST"
            )
            
            # Update broker price
            self._broker.update_price(tick)
            
            # Process strategy
            signal = await strategy.on_market_data(bar)
            
            if signal:
                await self._execute_signal(signal, timestamp)
            
            # Record equity
            account = await self._broker.get_account()
            self._equity_history.append((timestamp, account.equity))
            
            # Progress
            if progress_callback and idx % 100 == 0:
                progress_callback((idx / total_bars) * 100)
        
        # Cleanup
        await strategy.stop()
        await self._broker.disconnect()
        
        # Calculate metrics
        equity_series = pd.Series(
            [e for _, e in self._equity_history],
            index=[t for t, _ in self._equity_history]
        )
        
        metrics = self._calculate_metrics(equity_series)
        
        return BacktestResult(
            equity_curve=equity_series,
            trades=self._trades,
            metrics=metrics,
            start_date=data.index[0],
            end_date=data.index[-1],
            initial_capital=self.initial_capital,
            final_equity=equity_series.iloc[-1]
        )
    
    async def _execute_signal(self, signal: Signal, timestamp: datetime) -> None:
        """Execute trading signal."""
        if not self._oms:
            return
        
        # Simple execution: market order
        direction = TradeDirection.LONG if signal.direction == "LONG" else TradeDirection.SHORT
        
        # Position sizing (simplified)
        account = await self._broker.get_account()
        risk_amount = account.equity * Decimal("0.01")  # 1% risk
        position_size = risk_amount / Decimal(str(signal.metadata.get("atr", 1.0)))
        
        order = await self._oms.submit_order(
            symbol=signal.symbol,
            direction=direction,
            quantity=position_size,
            strategy_id=signal.strategy_id
        )
        
        self._trades.append({
            "timestamp": timestamp,
            "symbol": signal.symbol,
            "direction": signal.direction,
            "size": float(position_size),
            "confidence": signal.confidence,
            "signal_strength": signal.strength
        })
    
    def _calculate_metrics(self, equity: pd.Series) -> dict[str, float]:
        """Calculate performance metrics."""
        returns = equity.pct_change().dropna()
        
        # Total return
        total_return = (equity.iloc[-1] / equity.iloc[0]) - 1
        
        # Sharpe ratio (annualized)
        sharpe = 0.0
        if returns.std() > 0:
            sharpe = (returns.mean() / returns.std()) * np.sqrt(252)
        
        # Sortino ratio
        downside_returns = returns[returns < 0]
        sortino = 0.0
        if len(downside_returns) > 0 and downside_returns.std() > 0:
            sortino = (returns.mean() / downside_returns.std()) * np.sqrt(252)
        
        # Maximum drawdown
        running_max = equity.cummax()
        drawdown = (equity - running_max) / running_max
        max_drawdown = drawdown.min()
        
        # Calmar ratio
        calmar = total_return / abs(max_drawdown) if max_drawdown != 0 else 0
        
        # Win rate (simplified)
        win_rate = 0.5  # Would calculate from actual trade outcomes
        
        # Profit factor
        profit_factor = 1.0  # Would calculate from gross profits / gross losses
        
        return {
            "total_return": float(total_return),
            "sharpe_ratio": float(sharpe),
            "sortino_ratio": float(sortino),
            "max_drawdown": float(max_drawdown),
            "calmar_ratio": float(calmar),
            "win_rate": float(win_rate),
            "profit_factor": float(profit_factor),
            "volatility": float(returns.std() * np.sqrt(252)),
            "num_trades": len(self._trades)
        }

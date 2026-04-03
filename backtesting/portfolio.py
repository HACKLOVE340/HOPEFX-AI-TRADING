# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
Portfolio Tracker for Backtesting

Tracks positions, equity, and generates performance history.
"""

import logging
from datetime import datetime

import pandas as pd

from backtesting.events import FillEvent

logger = logging.getLogger(__name__)


class Portfolio:
    """
    Tracks portfolio state during backtesting.

    Maintains positions, cash, equity curve, and trade history.
    """

    def __init__(self, initial_capital: float = 100000.0):
        """
        Initialize portfolio.

        Args:
            initial_capital: Starting capital
        """
        self.initial_capital = initial_capital
        self.cash = initial_capital
        self.equity = initial_capital

        self.positions: dict[str, float] = {}  # symbol -> quantity
        self.avg_prices: dict[str, float] = {}  # symbol -> avg entry price

        self.equity_curve: list[dict] = []
        self.trade_history: list[dict] = []

        self.total_trades = 0
        self.winning_trades = 0
        self.losing_trades = 0

        logger.info("Initialized portfolio with $%s", initial_capital)

    def update_fill(self, fill: FillEvent, current_prices: dict[str, float]):
        """
        Update portfolio based on fill event.

        Args:
            fill: FillEvent with trade details
            current_prices: Dict of current prices for all symbols
        """
        direction_multiplier = 1 if fill.direction == "BUY" else -1
        fill_cost = fill.fill_price * fill.quantity

        # Update cash
        self.cash -= direction_multiplier * (fill_cost + fill.commission)

        # Update position
        if fill.symbol not in self.positions:
            self.positions[fill.symbol] = 0

        old_position = self.positions[fill.symbol]
        new_position = old_position + (direction_multiplier * fill.quantity)

        # Update average price
        if fill.direction == "BUY":
            if fill.symbol in self.avg_prices and old_position > 0:
                # Average up
                total_cost = (self.avg_prices[fill.symbol] * old_position) + fill_cost
                self.avg_prices[fill.symbol] = total_cost / new_position
            else:
                self.avg_prices[fill.symbol] = fill.fill_price
        # Selling - check if closing position
        elif new_position == 0:
            # Position closed
            pnl = (fill.fill_price - self.avg_prices.get(fill.symbol, fill.fill_price)) * fill.quantity
            self._record_trade(fill, pnl)
            if fill.symbol in self.avg_prices:
                del self.avg_prices[fill.symbol]
        elif new_position < 0 and old_position >= 0:
            # Flipped to short
            self.avg_prices[fill.symbol] = fill.fill_price

        self.positions[fill.symbol] = new_position

        # Update equity
        self._update_equity(current_prices)

        logger.debug("Updated portfolio: %s %s %s @ %s", fill.direction, fill.quantity, fill.symbol, fill.fill_price)

    def _record_trade(self, fill: FillEvent, pnl: float):
        """Record completed trade."""
        self.total_trades += 1

        if pnl > 0:
            self.winning_trades += 1
        elif pnl < 0:
            self.losing_trades += 1

        trade = {
            "timestamp": fill.timestamp,
            "symbol": fill.symbol,
            "quantity": fill.quantity,
            "price": fill.fill_price,
            "pnl": pnl,
            "commission": fill.commission,
        }

        self.trade_history.append(trade)

    def _update_equity(self, current_prices: dict[str, float]):
        """Update total equity based on current prices."""
        position_value = 0

        for symbol, quantity in self.positions.items():
            if quantity != 0 and symbol in current_prices:
                position_value += quantity * current_prices[symbol]

        self.equity = self.cash + position_value

    def update_timeindex(self, timestamp: datetime, current_prices: dict[str, float]):
        """
        Update equity curve at each time step.

        Args:
            timestamp: Current timestamp
            current_prices: Dict of current prices
        """
        self._update_equity(current_prices)

        self.equity_curve.append(
            {
                "timestamp": timestamp,
                "equity": self.equity,
                "cash": self.cash,
                "positions_value": self.equity - self.cash,
            }
        )

    def get_equity_curve(self) -> pd.DataFrame:
        """Get equity curve as DataFrame."""
        if not self.equity_curve:
            return pd.DataFrame()

        df = pd.DataFrame(self.equity_curve)
        df.set_index("timestamp", inplace=True)
        return df

    def get_trade_history(self) -> pd.DataFrame:
        """Get trade history as DataFrame."""
        if not self.trade_history:
            return pd.DataFrame()

        return pd.DataFrame(self.trade_history)

    def get_holdings(self) -> dict[str, dict]:
        """Get current holdings details."""
        holdings = {}

        for symbol, quantity in self.positions.items():
            if quantity != 0:
                holdings[symbol] = {
                    "quantity": quantity,
                    "avg_price": self.avg_prices.get(symbol, 0),
                }

        return holdings

    def get_total_pnl(self) -> float:
        """Get total profit/loss."""
        return self.equity - self.initial_capital

    def get_total_return(self) -> float:
        """Get total return percentage."""
        return ((self.equity - self.initial_capital) / self.initial_capital) * 100

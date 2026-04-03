# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
Base Strategy Class

This module provides the base class for all trading strategies.
All strategies should inherit from this base class.
"""

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class SignalType(Enum):
    """Trading signal types"""

    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"
    CLOSE_LONG = "CLOSE_LONG"
    CLOSE_SHORT = "CLOSE_SHORT"


class StrategyStatus(Enum):
    """Strategy execution status"""

    IDLE = "IDLE"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    STOPPED = "STOPPED"
    ERROR = "ERROR"


@dataclass
class Signal:
    """Trading signal data structure"""

    signal_type: SignalType
    symbol: str
    price: float
    timestamp: datetime
    confidence: float  # 0.0 to 1.0
    metadata: dict[str, Any] | None = None

    def __post_init__(self):
        """Validate signal data"""
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("Confidence must be between 0.0 and 1.0")


@dataclass
class StrategyConfig:
    """Strategy configuration"""

    name: str
    symbol: str
    timeframe: str
    enabled: bool = True
    risk_per_trade: float = 1.0  # Percentage
    max_positions: int = 3
    parameters: dict[str, Any] | None = None


class BaseStrategy(ABC):
    """
    Base class for all trading strategies.

    All strategies must implement:
    - analyze(): Analyze market data
    - generate_signal(): Generate trading signals
    - on_bar(): Process new bar data
    """

    def __init__(self, config_or_name, symbol: str | None = None, config: "StrategyConfig | None" = None):
        """
        Initialize strategy.

        Accepts two call signatures:
          - BaseStrategy(config)                  — single StrategyConfig object
          - BaseStrategy(name, symbol, config)    — legacy 3-arg form used by some subclasses
        """
        if isinstance(config_or_name, str):
            # 3-arg form: (name, symbol, config)
            if config is None:
                raise ValueError("config must be provided when using 3-arg form")
            self.config = config
        else:
            # 1-arg form: (config,)
            self.config = config_or_name
        self.status = StrategyStatus.IDLE
        self.positions = []
        self.signals_history = []
        self.logger = logging.getLogger(f"{__name__}.{self.config.name}")
        self.performance_metrics = {
            "total_signals": 0,
            "winning_signals": 0,
            "losing_signals": 0,
            "winning_trades": 0,
            "losing_trades": 0,
            "total_pnl": 0.0,
            "win_rate": 0.0,
        }

        logger.info("Initialized strategy: %s for %s", self.config.name, self.config.symbol)

    @property
    def name(self) -> str:
        return self.config.name

    @property
    def symbol(self) -> str:
        return self.config.symbol

    @property
    def is_active(self) -> bool:
        return self.status == StrategyStatus.RUNNING

    @property
    def performance(self) -> dict:
        """Alias for performance_metrics."""
        return self.performance_metrics

    @abstractmethod
    def analyze(self, data: dict[str, Any]) -> dict[str, Any]:
        """
        Analyze market data.

        Args:
            data: Market data (OHLCV, indicators, etc.)

        Returns:
            Analysis results
        """

    @abstractmethod
    def generate_signal(self, analysis: dict[str, Any]) -> Signal | None:
        """
        Generate trading signal based on analysis.

        Args:
            analysis: Analysis results from analyze()

        Returns:
            Signal if conditions are met, None otherwise
        """

    def on_bar(self, bar: dict[str, Any]) -> Signal | None:
        """
        Process new bar data.

        Args:
            bar: OHLCV bar data — must contain a non-zero 'close' price.

        Returns:
            Signal if generated, None otherwise.
            Returns None (without error) when the bar has no valid price,
            preventing zero-price signals from reaching the execution engine.
        """
        # Guard: reject bars with no real price before analysis.
        # Strategies default to price=0.0 when the key is missing; a zero-price
        # signal would produce a zero-price order at the broker.
        close = bar.get("close") or bar.get("price") or bar.get("mid")
        if not close or float(close) <= 0:
            logger.warning(
                "%s.on_bar: bar has no valid price (close=%s) — skipping",
                self.config.name,
                close,
            )
            return None

        try:
            # Analyze market data
            analysis = self.analyze(bar)

            # Generate signal
            signal = self.generate_signal(analysis)

            if signal:
                # Guard: reject zero-price signals regardless of how they were built.
                if signal.price <= 0:
                    logger.error(
                        "%s.generate_signal returned price=%.6f for %s — discarding signal to prevent zero-price order",
                        self.config.name,
                        signal.price,
                        signal.symbol,
                    )
                    return None
                self._record_signal(signal)
                logger.info(
                    f"{self.config.name}: Generated {signal.signal_type.value} "
                    f"signal for {signal.symbol} at {signal.price}",
                )

            return signal

        except Exception as e:
            logger.error("Error processing bar in %s: %s", self.config.name, e)

            self.status = StrategyStatus.ERROR
            return None

    def start(self):
        """Start strategy execution"""
        self.status = StrategyStatus.RUNNING
        logger.info("Started strategy: %s", self.config.name)


    def stop(self):
        """Stop strategy execution"""
        self.status = StrategyStatus.STOPPED
        logger.info("Stopped strategy: %s", self.config.name)


    def pause(self):
        """Pause strategy execution"""
        self.status = StrategyStatus.PAUSED
        logger.info("Paused strategy: %s", self.config.name)


    def resume(self):
        """Resume strategy execution"""
        self.status = StrategyStatus.RUNNING
        logger.info("Resumed strategy: %s", self.config.name)


    def _record_signal(self, signal: Signal):
        """Record signal in history"""
        self.signals_history.append(signal)
        self.performance_metrics["total_signals"] += 1

    def get_performance_metrics(self) -> dict[str, Any]:
        """
        Get strategy performance metrics.

        Returns:
            Dictionary of performance metrics
        """
        metrics = self.performance_metrics.copy()

        if metrics["total_signals"] > 0:
            metrics["win_rate"] = metrics["winning_signals"] / metrics["total_signals"] * 100
        else:
            metrics["win_rate"] = 0.0

        return metrics

    def update_performance(
        self,
        signal_id_or_pnl=None,
        pnl_or_side=None,
        is_winner=None,
        profit_loss=None,
        pnl=None,
        signal_type=None,
    ):
        """
        Update performance metrics after trade completion.

        Args:
            signal_id: Signal identifier
            pnl: Profit/Loss from trade
            is_winner: Whether trade was profitable
        """
        # Support multiple calling conventions:
        # (profit_loss=X, signal_type=Y)  — keyword style
        # (pnl, side_str)                 — positional 2-arg
        # (signal_id, pnl, is_winner)     — positional 3-arg
        if pnl is not None and profit_loss is None:
            profit_loss = pnl
        if profit_loss is not None:
            pnl = float(profit_loss)
            is_winner = pnl > 0 if is_winner is None else is_winner
        elif is_winner is None and pnl_or_side is not None:
            pnl = float(signal_id_or_pnl)
            is_winner = pnl > 0
        elif is_winner is None:
            pnl = float(signal_id_or_pnl) if signal_id_or_pnl is not None else 0.0
            is_winner = pnl > 0
        else:
            pnl = float(pnl_or_side) if pnl_or_side is not None else 0.0

        self.performance_metrics["total_signals"] += 1
        self.performance_metrics["total_pnl"] += pnl

        if is_winner:
            self.performance_metrics["winning_signals"] += 1
            self.performance_metrics["winning_trades"] += 1
        else:
            self.performance_metrics["losing_signals"] += 1
            self.performance_metrics["losing_trades"] += 1

        total = self.performance_metrics["total_signals"]
        wins = self.performance_metrics["winning_trades"]
        self.performance_metrics["win_rate"] = (wins / total * 100.0) if total > 0 else 0.0

    def __repr__(self) -> str:
        return (
            f"{self.__class__.__name__}("
            f"name={self.config.name}, "
            f"symbol={self.config.symbol}, "
            f"status={self.status.value})"
        )

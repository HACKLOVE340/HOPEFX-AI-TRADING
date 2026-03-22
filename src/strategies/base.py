"""
Abstract strategy interface with lifecycle management.
"""

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any

from src.domain.enums import StrategyState
from src.domain.models import Account, MarketData, Signal


class Strategy(ABC):
    """
    Base class for all trading strategies.
    """
    
    def __init__(self, strategy_id: str, parameters: dict[str, Any] | None = None):
        self.strategy_id = strategy_id
        self.parameters = parameters or {}
        self.state = StrategyState.INITIALIZING
        self._initialized = False
        self._metrics: dict[str, Any] = {
            "signals_generated": 0,
            "trades_taken": 0,
            "last_signal": None
        }
    
    @abstractmethod
    async def initialize(self) -> None:
        """Initialize strategy resources."""
        pass
    
    @abstractmethod
    async def on_market_data(self, data: MarketData) -> Signal | None:
        """Process new market data."""
        pass
    
    @abstractmethod
    async def on_fill(self, order_id: str, fill_price: float, quantity: float) -> None:
        """Handle order fill."""
        pass
    
    async def start(self) -> None:
        """Start strategy."""
        if not self._initialized:
            await self.initialize()
            self._initialized = True
        self.state = StrategyState.ACTIVE
    
    async def stop(self) -> None:
        """Stop strategy."""
        self.state = StrategyState.STOPPED
    
    async def pause(self) -> None:
        """Pause strategy."""
        self.state = StrategyState.PAUSED
    
    def get_metrics(self) -> dict[str, Any]:
        """Return strategy performance metrics."""
        return {
            "strategy_id": self.strategy_id,
            "state": self.state.value,
            **self._metrics
        }
    
    def update_parameters(self, parameters: dict[str, Any]) -> None:
        """Update strategy parameters."""
        self.parameters.update(parameters)

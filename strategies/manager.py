"""
Strategy Manager

Manages multiple trading strategies, execution, and coordination.
"""

from typing import Dict, List, Optional, Any
import logging
from datetime import datetime

from .base import BaseStrategy, Signal, StrategyStatus

logger = logging.getLogger(__name__)


class StrategyManager:
    """
    Manages multiple trading strategies.
    
    Responsibilities:
    - Load and register strategies
    - Start/stop strategy execution
    - Coordinate signal generation
    - Track performance across strategies
    """
    
    def __init__(self):
        """Initialize strategy manager"""
        self.strategies: Dict[str, BaseStrategy] = {}
        self.active_signals: List[Signal] = []
        self.performance_summary = {
            'total_strategies': 0,
            'active_strategies': 0,
            'total_signals': 0,
            'total_pnl': 0.0,
        }
        
        logger.info("Strategy Manager initialized")
    
    def register_strategy(self, strategy: BaseStrategy):
        """
        Register a new strategy.
        
        Args:
            strategy: Strategy instance to register
        """
        if strategy.config.name in self.strategies:
            logger.warning(
                f"Strategy {strategy.config.name} already registered. "
                "Replacing existing strategy."
            )
        
        self.strategies[strategy.config.name] = strategy
        self.performance_summary['total_strategies'] = len(self.strategies)
        
        logger.info(f"Registered strategy: {strategy.config.name}")
    
    def unregister_strategy(self, strategy_name: str):
        """
        Unregister a strategy.
        
        Args:
            strategy_name: Name of strategy to remove
        """
        if strategy_name in self.strategies:
            # Stop strategy if running
            strategy = self.strategies[strategy_name]
            if strategy.status == StrategyStatus.RUNNING:
                strategy.stop()
            
            del self.strategies[strategy_name]
            self.performance_summary['total_strategies'] = len(self.strategies)
            logger.info(f"Unregistered strategy: {strategy_name}")
        else:
            logger.warning(f"Strategy {strategy_name} not found")
    
    def get_strategy(self, strategy_name: str) -> Optional[BaseStrategy]:
        """
        Get strategy by name.
        
        Args:
            strategy_name: Name of strategy
            
        Returns:
            Strategy instance or None if not found
        """
        return self.strategies.get(strategy_name)
    
    def list_strategies(self) -> List[Dict[str, Any]]:
        """
        List all registered strategies.
        
        Returns:
            List of strategy information dictionaries
        """
        return [
            {
                'name': strategy.config.name,
                'symbol': strategy.config.symbol,
                'timeframe': strategy.config.timeframe,
                'status': strategy.status.value,
                'enabled': strategy.config.enabled,
                'performance': strategy.get_performance_metrics(),
            }
            for strategy in self.strategies.values()
        ]
    
    def start_strategy(self, strategy_name: str):
        """
        Start a specific strategy.
        
        Args:
            strategy_name: Name of strategy to start
        """
        strategy = self.get_strategy(strategy_name)
        if strategy:
            strategy.start()
            self._update_active_count()
            logger.info(f"Started strategy: {strategy_name}")
        else:
            logger.error(f"Strategy {strategy_name} not found")
    
    def stop_strategy(self, strategy_name: str):
        """
        Stop a specific strategy.
        
        Args:
            strategy_name: Name of strategy to stop
        """
        strategy = self.get_strategy(strategy_name)
        if strategy:
            strategy.stop()
            self._update_active_count()
            logger.info(f"Stopped strategy: {strategy_name}")
        else:
            logger.error(f"Strategy {strategy_name} not found")
    
    def start_all(self):
        """Start all enabled strategies"""
        for strategy in self.strategies.values():
            if strategy.config.enabled:
                strategy.start()
        
        self._update_active_count()
        logger.info(f"Started all enabled strategies")
    
    def stop_all(self):
        """Stop all strategies"""
        for strategy in self.strategies.values():
            strategy.stop()
        
        self._update_active_count()
        logger.info("Stopped all strategies")
    
    def process_bar(self, symbol: str, bar: Dict[str, Any]) -> List[Signal]:
        """
        Process new bar data for all relevant strategies.
        
        Args:
            symbol: Trading symbol
            bar: OHLCV bar data
            
        Returns:
            List of generated signals
        """
        signals = []
        
        for strategy in self.strategies.values():
            # Only process if strategy is running and matches symbol
            if (strategy.status == StrategyStatus.RUNNING and 
                strategy.config.symbol == symbol and
                strategy.config.enabled):
                
                signal = strategy.on_bar(bar)
                if signal:
                    signals.append(signal)
                    self.active_signals.append(signal)
                    self.performance_summary['total_signals'] += 1
        
        return signals
    
    def get_performance_summary(self) -> Dict[str, Any]:
        """
        Get overall performance summary.
        
        Returns:
            Performance summary dictionary
        """
        summary = self.performance_summary.copy()
        
        # Aggregate metrics from all strategies
        total_pnl = sum(
            strategy.performance_metrics['total_pnl']
            for strategy in self.strategies.values()
        )
        
        summary['total_pnl'] = total_pnl
        summary['timestamp'] = datetime.utcnow().isoformat()
        
        return summary
    
    def get_strategy_performance(self, strategy_name: str) -> Optional[Dict[str, Any]]:
        """
        Get performance metrics for specific strategy.
        
        Args:
            strategy_name: Name of strategy
            
        Returns:
            Performance metrics or None if not found
        """
        strategy = self.get_strategy(strategy_name)
        if strategy:
            return strategy.get_performance_metrics()
        return None
    
    def _update_active_count(self):
        """Update count of active strategies"""
        active_count = sum(
            1 for strategy in self.strategies.values()
            if strategy.status == StrategyStatus.RUNNING
        )
        self.performance_summary['active_strategies'] = active_count
    
    def get_status(self) -> Dict[str, Any]:
        """
        Get manager status.
        
        Returns:
            Status dictionary
        """
        return {
            'total_strategies': len(self.strategies),
            'active_strategies': self.performance_summary['active_strategies'],
            'strategies': self.list_strategies(),
            'performance': self.get_performance_summary(),
        }

"""
Base Strategy Class

This module provides the base class for all trading strategies.
All strategies should inherit from this base class.
"""

from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
import logging

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
    metadata: Optional[Dict[str, Any]] = None
    
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
    parameters: Optional[Dict[str, Any]] = None


class BaseStrategy(ABC):
    """
    Base class for all trading strategies.
    
    All strategies must implement:
    - analyze(): Analyze market data
    - generate_signal(): Generate trading signals
    - on_bar(): Process new bar data
    """
    
    def __init__(self, config: StrategyConfig):
        """
        Initialize strategy.
        
        Args:
            config: Strategy configuration
        """
        self.config = config
        self.status = StrategyStatus.IDLE
        self.positions = []
        self.signals_history = []
        self.performance_metrics = {
            'total_signals': 0,
            'winning_signals': 0,
            'losing_signals': 0,
            'total_pnl': 0.0,
        }
        
        logger.info(f"Initialized strategy: {config.name} for {config.symbol}")
    
    @abstractmethod
    def analyze(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Analyze market data.
        
        Args:
            data: Market data (OHLCV, indicators, etc.)
            
        Returns:
            Analysis results
        """
        pass
    
    @abstractmethod
    def generate_signal(self, analysis: Dict[str, Any]) -> Optional[Signal]:
        """
        Generate trading signal based on analysis.
        
        Args:
            analysis: Analysis results from analyze()
            
        Returns:
            Signal if conditions are met, None otherwise
        """
        pass
    
    def on_bar(self, bar: Dict[str, Any]) -> Optional[Signal]:
        """
        Process new bar data.
        
        Args:
            bar: OHLCV bar data
            
        Returns:
            Signal if generated, None otherwise
        """
        try:
            # Analyze market data
            analysis = self.analyze(bar)
            
            # Generate signal
            signal = self.generate_signal(analysis)
            
            if signal:
                self._record_signal(signal)
                logger.info(
                    f"{self.config.name}: Generated {signal.signal_type.value} "
                    f"signal for {signal.symbol} at {signal.price}"
                )
            
            return signal
            
        except Exception as e:
            logger.error(f"Error processing bar in {self.config.name}: {e}")
            self.status = StrategyStatus.ERROR
            return None
    
    def start(self):
        """Start strategy execution"""
        self.status = StrategyStatus.RUNNING
        logger.info(f"Started strategy: {self.config.name}")
    
    def stop(self):
        """Stop strategy execution"""
        self.status = StrategyStatus.STOPPED
        logger.info(f"Stopped strategy: {self.config.name}")
    
    def pause(self):
        """Pause strategy execution"""
        self.status = StrategyStatus.PAUSED
        logger.info(f"Paused strategy: {self.config.name}")
    
    def resume(self):
        """Resume strategy execution"""
        self.status = StrategyStatus.RUNNING
        logger.info(f"Resumed strategy: {self.config.name}")
    
    def _record_signal(self, signal: Signal):
        """Record signal in history"""
        self.signals_history.append(signal)
        self.performance_metrics['total_signals'] += 1
    
    def get_performance_metrics(self) -> Dict[str, Any]:
        """
        Get strategy performance metrics.
        
        Returns:
            Dictionary of performance metrics
        """
        metrics = self.performance_metrics.copy()
        
        if metrics['total_signals'] > 0:
            metrics['win_rate'] = (
                metrics['winning_signals'] / metrics['total_signals'] * 100
            )
        else:
            metrics['win_rate'] = 0.0
        
        return metrics
    
    def update_performance(self, signal_id: int, pnl: float, is_winner: bool):
        """
        Update performance metrics after trade completion.
        
        Args:
            signal_id: Signal identifier
            pnl: Profit/Loss from trade
            is_winner: Whether trade was profitable
        """
        self.performance_metrics['total_pnl'] += pnl
        
        if is_winner:
            self.performance_metrics['winning_signals'] += 1
        else:
            self.performance_metrics['losing_signals'] += 1
    
    def __repr__(self) -> str:
        return (
            f"{self.__class__.__name__}("
            f"name={self.config.name}, "
            f"symbol={self.config.symbol}, "
            f"status={self.status.value})"
        )

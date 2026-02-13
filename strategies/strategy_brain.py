"""
Strategy Brain - Multi-Strategy Joint Analysis Core

This module provides the central intelligence for combining signals from
multiple strategies into unified, high-confidence trading decisions.

Features:
- Multi-strategy signal aggregation
- Confidence weighting system
- Consensus-based decision making
- Signal correlation analysis
- Risk-adjusted signal combining
- Real-time strategy coordination
- Performance-weighted voting
"""

from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime
import logging
import numpy as np

from .base import BaseStrategy, Signal, SignalType, StrategyConfig, StrategyStatus

logger = logging.getLogger(__name__)


class StrategyBrain:
    """
    Central intelligence for multi-strategy coordination and joint analysis.
    
    Combines signals from multiple strategies using:
    - Weighted voting based on historical performance
    - Confidence score aggregation
    - Correlation analysis between strategies
    - Risk-adjusted position sizing recommendations
    """
    
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        Initialize Strategy Brain.
        
        Args:
            config: Brain configuration
        """
        self.config = config or {}
        
        # Brain parameters
        self.min_strategies_required = self.config.get('min_strategies_required', 2)
        self.consensus_threshold = self.config.get('consensus_threshold', 0.6)  # 60%
        self.performance_weight = self.config.get('performance_weight', 0.4)  # 40% weight to performance
        self.confidence_weight = self.config.get('confidence_weight', 0.6)  # 60% weight to signal confidence
        
        # Strategy tracking
        self.strategies: Dict[str, BaseStrategy] = {}
        self.strategy_performance: Dict[str, Dict[str, float]] = {}
        self.strategy_weights: Dict[str, float] = {}
        
        # Signal history
        self.signal_history: List[Dict[str, Any]] = []
        self.consensus_signals: List[Signal] = []
        
        # Statistics
        self.stats = {
            'total_analyses': 0,
            'consensus_reached': 0,
            'bullish_consensus': 0,
            'bearish_consensus': 0,
            'neutral_count': 0,
            'average_confidence': 0.0,
        }
        
        logger.info("Strategy Brain initialized")
    
    def register_strategy(self, strategy: BaseStrategy):
        """
        Register a strategy with the brain.
        
        Args:
            strategy: Strategy instance to register
        """
        strategy_name = strategy.config.name
        self.strategies[strategy_name] = strategy
        
        # Initialize performance tracking
        if strategy_name not in self.strategy_performance:
            self.strategy_performance[strategy_name] = {
                'total_signals': 0,
                'correct_signals': 0,
                'win_rate': 0.5,  # Start at 50%
                'average_confidence': 0.5,
                'total_pnl': 0.0,
            }
        
        # Calculate initial weight (equal weight, updated by performance)
        self._recalculate_weights()
        
        logger.info(f"Strategy Brain: Registered {strategy_name}")
    
    def unregister_strategy(self, strategy_name: str):
        """
        Unregister a strategy from the brain.
        
        Args:
            strategy_name: Name of strategy to remove
        """
        if strategy_name in self.strategies:
            del self.strategies[strategy_name]
            self._recalculate_weights()
            logger.info(f"Strategy Brain: Unregistered {strategy_name}")
    
    def analyze_joint(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Perform joint analysis using all registered strategies.
        
        Args:
            data: Market data to analyze
            
        Returns:
            Joint analysis results with consensus signal
        """
        self.stats['total_analyses'] += 1
        
        try:
            # Collect signals from all active strategies
            strategy_signals = {}
            
            for name, strategy in self.strategies.items():
                if strategy.status != StrategyStatus.RUNNING:
                    continue
                
                try:
                    # Get signal from strategy
                    signal = strategy.on_bar(data)
                    if signal:
                        strategy_signals[name] = signal
                except Exception as e:
                    logger.error(f"Error getting signal from {name}: {e}")
            
            # If not enough strategies provided signals, return neutral
            if len(strategy_signals) < self.min_strategies_required:
                self.stats['neutral_count'] += 1
                return {
                    'consensus_reached': False,
                    'reason': f'Insufficient strategies ({len(strategy_signals)} < {self.min_strategies_required})',
                    'signal': None,
                }
            
            # Analyze signals for consensus
            consensus_result = self._calculate_consensus(strategy_signals, data)
            
            if consensus_result['consensus_reached']:
                self.stats['consensus_reached'] += 1
                if consensus_result['consensus_signal'].signal_type == SignalType.BUY:
                    self.stats['bullish_consensus'] += 1
                elif consensus_result['consensus_signal'].signal_type == SignalType.SELL:
                    self.stats['bearish_consensus'] += 1
                
                # Update average confidence
                self.stats['average_confidence'] = (
                    (self.stats['average_confidence'] * (self.stats['total_analyses'] - 1) +
                     consensus_result['consensus_signal'].confidence) /
                    self.stats['total_analyses']
                )
                
                # Record consensus signal
                self.consensus_signals.append(consensus_result['consensus_signal'])
            else:
                self.stats['neutral_count'] += 1
            
            # Record in history
            self.signal_history.append({
                'timestamp': datetime.utcnow(),
                'strategy_signals': strategy_signals,
                'consensus': consensus_result,
                'data_snapshot': data.get('prices', [])[-1] if data.get('prices') else {},
            })
            
            return consensus_result
            
        except Exception as e:
            logger.error(f"Error in joint analysis: {e}")
            return {
                'consensus_reached': False,
                'reason': f'Analysis error: {str(e)}',
                'signal': None,
            }
    
    def _calculate_consensus(
        self, 
        strategy_signals: Dict[str, Signal],
        data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Calculate consensus from multiple strategy signals.
        
        Args:
            strategy_signals: Signals from different strategies
            data: Market data context
            
        Returns:
            Consensus analysis result
        """
        try:
            # Categorize signals by type
            buy_signals = []
            sell_signals = []
            
            for strategy_name, signal in strategy_signals.items():
                weight = self.strategy_weights.get(strategy_name, 1.0 / len(self.strategies))
                
                # Weight the signal by strategy performance and confidence
                weighted_confidence = (
                    signal.confidence * self.confidence_weight +
                    self.strategy_performance[strategy_name]['win_rate'] * self.performance_weight
                ) * weight
                
                if signal.signal_type == SignalType.BUY:
                    buy_signals.append({
                        'strategy': strategy_name,
                        'signal': signal,
                        'weight': weight,
                        'weighted_confidence': weighted_confidence,
                    })
                elif signal.signal_type == SignalType.SELL:
                    sell_signals.append({
                        'strategy': strategy_name,
                        'signal': signal,
                        'weight': weight,
                        'weighted_confidence': weighted_confidence,
                    })
            
            # Calculate total weighted confidence for each direction
            total_buy_confidence = sum(s['weighted_confidence'] for s in buy_signals)
            total_sell_confidence = sum(s['weighted_confidence'] for s in sell_signals)
            
            # Calculate consensus
            total_confidence = total_buy_confidence + total_sell_confidence
            
            if total_confidence == 0:
                return {
                    'consensus_reached': False,
                    'reason': 'No directional signals',
                    'signal': None,
                }
            
            # Determine if consensus is reached
            buy_ratio = total_buy_confidence / total_confidence
            sell_ratio = total_sell_confidence / total_confidence
            
            consensus_signal = None
            consensus_reached = False
            reason = ""
            
            # BULLISH CONSENSUS
            if buy_ratio >= self.consensus_threshold:
                consensus_reached = True
                
                # Create consensus signal
                avg_price = np.mean([s['signal'].price for s in buy_signals])
                consensus_confidence = total_buy_confidence / len(buy_signals) if buy_signals else 0
                
                consensus_signal = Signal(
                    signal_type=SignalType.BUY,
                    symbol=list(strategy_signals.values())[0].symbol,
                    price=avg_price,
                    timestamp=datetime.utcnow(),
                    confidence=min(consensus_confidence, 1.0),
                    metadata={
                        'type': 'consensus',
                        'agreeing_strategies': [s['strategy'] for s in buy_signals],
                        'total_strategies': len(strategy_signals),
                        'buy_ratio': buy_ratio,
                        'weighted_confidence': total_buy_confidence,
                        'strategy_details': {
                            s['strategy']: {
                                'confidence': s['signal'].confidence,
                                'weight': s['weight'],
                                'metadata': s['signal'].metadata,
                            }
                            for s in buy_signals
                        },
                    }
                )
                reason = f"Bullish consensus: {len(buy_signals)}/{len(strategy_signals)} strategies agree"
            
            # BEARISH CONSENSUS
            elif sell_ratio >= self.consensus_threshold:
                consensus_reached = True
                
                # Create consensus signal
                avg_price = np.mean([s['signal'].price for s in sell_signals])
                consensus_confidence = total_sell_confidence / len(sell_signals) if sell_signals else 0
                
                consensus_signal = Signal(
                    signal_type=SignalType.SELL,
                    symbol=list(strategy_signals.values())[0].symbol,
                    price=avg_price,
                    timestamp=datetime.utcnow(),
                    confidence=min(consensus_confidence, 1.0),
                    metadata={
                        'type': 'consensus',
                        'agreeing_strategies': [s['strategy'] for s in sell_signals],
                        'total_strategies': len(strategy_signals),
                        'sell_ratio': sell_ratio,
                        'weighted_confidence': total_sell_confidence,
                        'strategy_details': {
                            s['strategy']: {
                                'confidence': s['signal'].confidence,
                                'weight': s['weight'],
                                'metadata': s['signal'].metadata,
                            }
                            for s in sell_signals
                        },
                    }
                )
                reason = f"Bearish consensus: {len(sell_signals)}/{len(strategy_signals)} strategies agree"
            
            else:
                reason = f"No consensus: Buy {buy_ratio:.1%}, Sell {sell_ratio:.1%}"
            
            return {
                'consensus_reached': consensus_reached,
                'consensus_signal': consensus_signal,
                'buy_signals': len(buy_signals),
                'sell_signals': len(sell_signals),
                'total_signals': len(strategy_signals),
                'buy_ratio': buy_ratio,
                'sell_ratio': sell_ratio,
                'reason': reason,
                'analysis_details': {
                    'buy_confidence': total_buy_confidence,
                    'sell_confidence': total_sell_confidence,
                    'buy_strategies': [s['strategy'] for s in buy_signals],
                    'sell_strategies': [s['strategy'] for s in sell_signals],
                },
            }
            
        except Exception as e:
            logger.error(f"Error calculating consensus: {e}")
            return {
                'consensus_reached': False,
                'reason': f'Consensus calculation error: {str(e)}',
                'signal': None,
            }
    
    def update_strategy_performance(
        self,
        strategy_name: str,
        signal_correct: bool,
        pnl: float
    ):
        """
        Update performance metrics for a strategy.
        
        Args:
            strategy_name: Name of strategy
            signal_correct: Whether signal was correct
            pnl: Profit/loss from signal
        """
        if strategy_name not in self.strategy_performance:
            return
        
        perf = self.strategy_performance[strategy_name]
        
        # Update metrics
        perf['total_signals'] += 1
        if signal_correct:
            perf['correct_signals'] += 1
        perf['total_pnl'] += pnl
        
        # Recalculate win rate
        perf['win_rate'] = perf['correct_signals'] / perf['total_signals']
        
        # Recalculate strategy weights
        self._recalculate_weights()
        
        logger.info(
            f"Updated performance for {strategy_name}: "
            f"Win rate: {perf['win_rate']:.2%}, PnL: ${perf['total_pnl']:.2f}"
        )
    
    def _recalculate_weights(self):
        """Recalculate strategy weights based on performance"""
        if not self.strategies:
            return
        
        # Calculate weights based on win rate and PnL
        total_performance = 0.0
        strategy_scores = {}
        
        for name in self.strategies.keys():
            if name in self.strategy_performance:
                perf = self.strategy_performance[name]
                # Combine win rate and normalized PnL for score
                score = (perf['win_rate'] * 0.7 + min(perf['total_pnl'] / 1000, 1.0) * 0.3)
            else:
                score = 0.5  # Default score for new strategies
            
            strategy_scores[name] = max(score, 0.1)  # Minimum weight of 0.1
            total_performance += strategy_scores[name]
        
        # Normalize weights
        if total_performance > 0:
            self.strategy_weights = {
                name: score / total_performance
                for name, score in strategy_scores.items()
            }
        else:
            # Equal weights if no performance data
            equal_weight = 1.0 / len(self.strategies)
            self.strategy_weights = {name: equal_weight for name in self.strategies.keys()}
    
    def get_statistics(self) -> Dict[str, Any]:
        """
        Get brain statistics.
        
        Returns:
            Statistics dictionary
        """
        consensus_rate = (
            self.stats['consensus_reached'] / self.stats['total_analyses']
            if self.stats['total_analyses'] > 0 else 0
        )
        
        return {
            'total_analyses': self.stats['total_analyses'],
            'consensus_reached': self.stats['consensus_reached'],
            'consensus_rate': consensus_rate,
            'bullish_consensus': self.stats['bullish_consensus'],
            'bearish_consensus': self.stats['bearish_consensus'],
            'neutral_count': self.stats['neutral_count'],
            'average_confidence': self.stats['average_confidence'],
            'registered_strategies': len(self.strategies),
            'strategy_weights': self.strategy_weights.copy(),
            'strategy_performance': self.strategy_performance.copy(),
        }
    
    def get_strategy_correlations(self) -> Dict[str, Dict[str, float]]:
        """
        Calculate correlation between strategies based on signal history.
        
        Returns:
            Correlation matrix
        """
        correlations = {}
        strategy_names = list(self.strategies.keys())
        
        # Build signal agreement matrix
        for strategy1 in strategy_names:
            correlations[strategy1] = {}
            for strategy2 in strategy_names:
                if strategy1 == strategy2:
                    correlations[strategy1][strategy2] = 1.0
                else:
                    # Calculate how often they agree
                    agreements = 0
                    total_comparisons = 0
                    
                    for history_entry in self.signal_history:
                        signals = history_entry['strategy_signals']
                        if strategy1 in signals and strategy2 in signals:
                            total_comparisons += 1
                            if signals[strategy1].signal_type == signals[strategy2].signal_type:
                                agreements += 1
                    
                    correlation = agreements / total_comparisons if total_comparisons > 0 else 0.5
                    correlations[strategy1][strategy2] = correlation
        
        return correlations
    
    def __repr__(self) -> str:
        return (
            f"StrategyBrain("
            f"strategies={len(self.strategies)}, "
            f"consensus_rate={self.stats['consensus_reached']}/{self.stats['total_analyses']})"
        )

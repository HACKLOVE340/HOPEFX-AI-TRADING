# analysis/technical_analyzer.py
"""
Advanced technical analysis with multi-timeframe confirmation
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Tuple
from dataclasses import dataclass

@dataclass
class AnalysisResult:
    signal: str  # 'buy', 'sell', 'neutral'
    confidence: float  # 0.0 to 1.0
    indicators: Dict[str, float]
    timeframe: str

class MultiTimeframeAnalyzer:
    """Analyze multiple timeframes for confluence."""
    
    TIMEFRAMES = ['1m', '5m', '15m', '1h', '4h', '1d']
    
    def __init__(self):
        self.indicators = {}
    
    def analyze(self, data: Dict[str, pd.DataFrame]) -> AnalysisResult:
        """
        Analyze all timeframes and return confluence signal.
        """
        signals = {}
        
        for tf, df in data.items():
            signals[tf] = self._analyze_single_timeframe(df)
        
        # Calculate confluence
        buy_votes = sum(1 for s in signals.values() if s['signal'] == 'buy')
        sell_votes = sum(1 for s in signals.values() if s['signal'] == 'sell')
        
        total = len(signals)
        buy_strength = buy_votes / total
        sell_strength = sell_votes / total
        
        if buy_strength > 0.7:
            return AnalysisResult(
                signal='buy',
                confidence=buy_strength,
                indicators=self._aggregate_indicators(signals),
                timeframe='multi'
            )
        elif sell_strength > 0.7:
            return AnalysisResult(
                signal='sell',
                confidence=sell_strength,
                indicators=self._aggregate_indicators(signals),
                timeframe='multi'
            )
        
        return AnalysisResult('neutral', 0.0, {}, 'multi')
    
    def _analyze_single_timeframe(self, df: pd.DataFrame) -> Dict:
        """Analyze single timeframe."""
        # Calculate indicators
        sma_20 = df['close'].rolling(20).mean().iloc[-1]
        sma_50 = df['close'].rolling(50).mean().iloc[-1]
        rsi = self._calculate_rsi(df['close'], 14)
        
        signal = 'neutral'
        if df['close'].iloc[-1] > sma_20 > sma_50 and rsi < 70:
            signal = 'buy'
        elif df['close'].iloc[-1] < sma_20 < sma_50 and rsi > 30:
            signal = 'sell'
        
        return {
            'signal': signal,
            'rsi': rsi,
            'trend': 'up' if sma_20 > sma_50 else 'down'
        }
    
    def _calculate_rsi(self, prices: pd.Series, period: int = 14) -> float:
        """Calculate RSI."""
        delta = prices.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
        rs = gain / loss
        return float(100 - (100 / (1 + rs)).iloc[-1])
    
    def _aggregate_indicators(self, signals: Dict) -> Dict:
        """Aggregate indicators across timeframes."""
        return {
            'avg_rsi': np.mean([s['rsi'] for s in signals.values()]),
            'trend_alignment': sum(1 for s in signals.values() if s['trend'] == 'up') / len(signals)
        }

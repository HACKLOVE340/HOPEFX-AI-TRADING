# core/analytics/realtime_heatmap.py
"""
HOPEFX Real-Time Heatmap Analytics
Live correlation, regime detection, and risk visualization
"""

import numpy as np
from typing import Dict, List
from dataclasses import dataclass
from datetime import datetime, timedelta
from collections import deque


class RealtimeHeatmapEngine:
    """Generate real-time heatmap data for dashboard"""
    
    def __init__(self, orchestra, risk_engine, event_bus):
        self.orchestra = orchestra
        self.risk_engine = risk_engine
        self.event_bus = event_bus
        
        # Data buffers
        self.price_history: Dict[str, deque] = {}
        self.returns_history: Dict[str, deque] = {}
        self.regime_history: deque = deque(maxlen=1000)
        
        # Configuration
        self.lookback_windows = {
            '1m': 12,      # 5-sec bars
            '5m': 60,
            '1h': 720,
            '1d': 8640
        }
    
    def on_price(self, symbol: str, price: float, timestamp: datetime):
        """Process new price data"""
        if symbol not in self.price_history:
            self.price_history[symbol] = deque(maxlen=10000)
            self.returns_history[symbol] = deque(maxlen=10000)
        
        self.price_history[symbol].append((timestamp, price))
        
        # Calculate return
        if len(self.price_history[symbol]) > 1:
            prev_price = self.price_history[symbol][-2][1]
            ret = (price - prev_price) / prev_price
            self.returns_history[symbol].append(ret)
        
        # Detect regime
        self._detect_regime(symbol)
    
    def _detect_regime(self, symbol: str):
        """Detect current market regime"""
        if len(self.price_history[symbol]) < 50:
            return
        
        prices = [p for _, p in self.price_history[symbol]]
        returns = [(prices[i] - prices[i-1]) / prices[i-1] for i in range(1, len(prices))]
        
        # Calculate metrics
        volatility = np.std(returns[-50:])
        trend = np.mean(returns[-50:])
        adx = self._calculate_adx(prices[-50:])
        
        # Classify regime
        if volatility > 0.001:
            if abs(trend) > 0.0005 and adx > 25:
                regime = "trending_up" if trend > 0 else "trending_down"
            else:
                regime = "volatile"
        else:
            regime = "ranging"
        
        if regime != self.orchestra.current_regime:
            self.orchestra.current_regime = regime
            self.regime_history.append((datetime.utcnow(), regime))
    
    def _calculate_adx(self, prices: List[float], period: int = 14) -> float:
        """Average Directional Index"""
        if len(prices) < period + 1:
            return 0
        
        highs = [max(prices[i], prices[i-1]) for i in range(1, len(prices))]
        lows = [min(prices[i], prices[i-1]) for i in range(1, len(prices))]
        closes = prices[1:]
        
        plus_dm = [highs[i] - highs[i-1] if highs[i] - highs[i-1] > lows[i-1] - lows[i] else 0 
                  for i in range(1, len(highs))]
        minus_dm = [lows[i-1] - lows[i] if lows[i-1] - lows[i] > highs[i] - highs[i-1] else 0 
                   for i in range(1, len(lows))]
        
        tr = [max(highs[i] - lows[i], 
                  abs(highs[i] - closes[i-1]), 
                  abs(lows[i] - closes[i-1])) 
              for i in range(len(highs))]
        
        atr = np.mean(tr[-period:])
        plus_di = 100 * np.mean(plus_dm[-period:]) / atr if atr > 0 else 0
        minus_di = 100 * np.mean(minus_dm[-period:]) / atr if atr > 0 else 0
        
        dx = 100 * abs(plus_di - minus_di) / (plus_di + minus_di) if (plus_di + minus_di) > 0 else 0
        return dx
    
    def get_correlation_matrix(self, symbols: List[str]) -> np.ndarray:
        """Calculate real-time correlation matrix"""
        if len(symbols) < 2:
            return np.eye(1)
        
        # Build returns matrix
        returns_list = []
        for sym in symbols:
            if sym in self.returns_history and len(self.returns_history[sym]) > 10:
                returns_list.append(list(self.returns_history[sym])[-100:])
        
        if len(returns_list) < 2:
            return np.eye(len(symbols))
        
        # Pad to same length
        min_len = min(len(r) for r in returns_list)
        matrix = np.array([r[:min_len] for r in returns_list])
        
        return np.corrcoef(matrix)
    
    def get_heatmap_data(self) -> Dict:
        """Generate comprehensive heatmap data"""
        symbols = list(self.price_history.keys())
        
        # Strategy performance heatmap
        strategy_data = self.orchestra.get_heatmap_data()
        
        # Correlation heatmap
        corr_matrix = self.get_correlation_matrix(symbols)
        
        # Risk heatmap
        risk_data = {}
        if self.risk_engine.current_risk:
            risk_data = {
                'var_95': self.risk_engine.current_risk.var_95,
                'cvar_95': self.risk_engine.current_risk.cvar_95,
                'volatility': self.risk_engine.current_risk.volatility,
                'max_dd': self.risk_engine.current_risk.max_drawdown
            }
        
        # Regime timeline
        regime_timeline = [
            {'time': ts.isoformat(), 'regime': reg}
            for ts, reg in self.regime_history
        ]
        
        return {
            'strategies': strategy_data,
            'correlation': {
                'symbols': symbols,
                'matrix': corr_matrix.tolist()
            },
            'risk': risk_data,
            'regime_timeline': regime_timeline,
            'timestamp': datetime.utcnow().isoformat()
        }

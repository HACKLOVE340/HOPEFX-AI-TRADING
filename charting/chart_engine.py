"""
Chart Rendering Engine
- Candlestick charts
- Line charts
- Volume bars
"""

from typing import Dict, List, Optional
import json
import logging

logger = logging.getLogger(__name__)

class ChartEngine:
    """Chart rendering and management"""
    
    def __init__(self, symbol: str, timeframe: str = "1h"):
        self.symbol = symbol
        self.timeframe = timeframe
        self.candles = []
        self.indicators = {}
        self.annotations = []
    
    def add_candle(self, open_price: float, high: float, low: float, 
                   close: float, volume: float, timestamp: str):
        """Add candlestick data"""
        candle = {
            'o': open_price,
            'h': high,
            'l': low,
            'c': close,
            'v': volume,
            't': timestamp
        }
        self.candles.append(candle)
        logger.debug(f"Candle added for {self.symbol}")
    
    def add_indicator(self, name: str, data: List[float]):
        """Add indicator to chart"""
        self.indicators[name] = data
    
    def add_annotation(self, x: int, y: float, text: str, color: str = "red"):
        """Add annotation to chart"""
        self.annotations.append({
            'x': x,
            'y': y,
            'text': text,
            'color': color
        })
    
    def get_chart_data(self) -> Dict:
        """Get chart data for rendering"""
        return {
            'symbol': self.symbol,
            'timeframe': self.timeframe,
            'candles': self.candles,
            'indicators': self.indicators,
            'annotations': self.annotations
        }
    
    def export_to_json(self, filepath: str):
        """Export chart data to JSON"""
        data = self.get_chart_data()
        with open(filepath, 'w') as f:
            json.dump(data, f, indent=2)
        logger.info(f"Chart exported to {filepath}")
    
    def clear(self):
        """Clear chart data"""
        self.candles = []
        self.indicators = {}
        self.annotations = []
        logger.info("Chart cleared")
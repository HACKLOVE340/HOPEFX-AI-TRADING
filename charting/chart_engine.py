"""
Chart Engine - Core charting functionality
"""

from typing import Dict, List, Any
from datetime import datetime


class ChartType:
    CANDLESTICK = "candlestick"
    LINE = "line"
    BAR = "bar"
    AREA = "area"
    HEIKIN_ASHI = "heikin_ashi"


class Chart:
    """Represents a trading chart"""
    def __init__(self, symbol: str, timeframe: str, chart_type: str = ChartType.CANDLESTICK):
        self.symbol = symbol
        self.timeframe = timeframe
        self.chart_type = chart_type
        self.indicators = []
        self.drawings = []
        self.created_at = datetime.utcnow()
    
    def add_indicator(self, indicator_name: str, **params):
        """Add technical indicator to chart"""
        self.indicators.append({
            'name': indicator_name,
            'params': params
        })
    
    def render(self, output_format: str = 'plotly') -> Dict:
        """Render chart data"""
        return {
            'symbol': self.symbol,
            'timeframe': self.timeframe,
            'type': self.chart_type,
            'indicators': self.indicators,
            'format': output_format
        }


class ChartEngine:
    """Main chart engine"""
    
    def __init__(self):
        self.charts: Dict[str, Chart] = {}
    
    def create_chart(
        self,
        symbol: str,
        timeframe: str,
        chart_type: str = ChartType.CANDLESTICK
    ) -> Chart:
        """Create a new chart"""
        chart = Chart(symbol, timeframe, chart_type)
        chart_id = f"{symbol}_{timeframe}_{datetime.utcnow().timestamp()}"
        self.charts[chart_id] = chart
        return chart
    
    def get_chart(self, chart_id: str) -> Chart:
        """Get existing chart"""
        return self.charts.get(chart_id)

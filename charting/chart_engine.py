"""Chart engine — Chart and ChartEngine classes."""

import enum as _enum
import json
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class ChartType(str, _enum.Enum):
    """Chart type enum. Inherits from str so values compare equal to strings."""
    CANDLESTICK = "candlestick"
    LINE = "line"
    BAR = "bar"
    AREA = "area"
    HEIKIN_ASHI = "heikin_ashi"


class Chart:
    """Single chart with indicators and drawings."""

    def __init__(self, symbol: str, timeframe: str = "1H",
                 chart_type: ChartType = ChartType.CANDLESTICK):
        self.symbol = symbol
        self.timeframe = timeframe
        self.chart_type = chart_type
        self.indicators: List[Dict[str, Any]] = []
        self.drawings: List[Dict[str, Any]] = []
        self.candles: List[Dict[str, Any]] = []

    def add_indicator(self, name: str, **params) -> None:
        self.indicators.append({"name": name, "params": params})

    def add_drawing(self, drawing_type: str, **params) -> None:
        self.drawings.append({"type": drawing_type, "params": params})

    def add_candle(self, open_price: float, high: float, low: float,
                   close: float, volume: float = 0, timestamp=None) -> None:
        self.candles.append({
            "open": open_price, "high": high, "low": low,
            "close": close, "volume": volume, "timestamp": timestamp,
        })

    def render(self, output_format: str = "plotly") -> Dict[str, Any]:
        return {
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "type": self.chart_type,
            "format": output_format,
            "indicators": self.indicators,
            "drawings": self.drawings,
            "candles": self.candles,
        }

    def export_to_json(self, filepath: str) -> None:
        with open(filepath, "w") as f:
            json.dump(self.render(), f, indent=2, default=str)

    def clear(self) -> None:
        self.candles.clear()
        self.indicators.clear()
        self.drawings.clear()


class ChartEngine:
    """Manages multiple Chart instances."""

    def __init__(self):
        self.charts: Dict[str, Chart] = {}

    def create_chart(self, symbol: str, timeframe: str = "1H",
                     chart_type: ChartType = ChartType.CANDLESTICK) -> Chart:
        chart = Chart(symbol, timeframe, chart_type)
        key = f"{symbol}_{timeframe}"
        self.charts[key] = chart
        return chart

    def get_chart(self, key: str) -> Optional[Chart]:
        return self.charts.get(key)

    def remove_chart(self, key: str) -> bool:
        if key in self.charts:
            del self.charts[key]
            return True
        return False

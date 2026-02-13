"""
Drawing Tools for Charts
"""

from typing import Dict, List, Any
from datetime import datetime


class DrawingType:
    TRENDLINE = "trendline"
    HORIZONTAL_LINE = "horizontal_line"
    RECTANGLE = "rectangle"
    FIBONACCI = "fibonacci"
    TEXT = "text"


class Drawing:
    """Base drawing object"""
    def __init__(self, drawing_type: str):
        self.drawing_type = drawing_type
        self.created_at = datetime.utcnow()
        self.properties = {}


class DrawingToolkit:
    """Toolkit for chart drawings"""

    def __init__(self):
        self.drawings: Dict[str, Drawing] = {}

    def draw_trendline(
        self,
        start_time: datetime,
        start_price: float,
        end_time: datetime,
        end_price: float,
        **kwargs
    ) -> Drawing:
        """Draw a trendline"""
        drawing = Drawing(DrawingType.TRENDLINE)
        drawing.properties = {
            'start_time': start_time,
            'start_price': start_price,
            'end_time': end_time,
            'end_price': end_price,
            **kwargs
        }

        drawing_id = f"TL_{start_time.timestamp()}"
        self.drawings[drawing_id] = drawing
        return drawing

    def draw_fibonacci(
        self,
        start_time: datetime,
        start_price: float,
        end_time: datetime,
        end_price: float,
        levels: List[float] = None
    ) -> Drawing:
        """Draw Fibonacci retracement"""
        if levels is None:
            levels = [0.236, 0.382, 0.5, 0.618, 0.786]

        drawing = Drawing(DrawingType.FIBONACCI)
        drawing.properties = {
            'start_time': start_time,
            'start_price': start_price,
            'end_time': end_time,
            'end_price': end_price,
            'levels': levels
        }

        drawing_id = f"FIB_{start_time.timestamp()}"
        self.drawings[drawing_id] = drawing
        return drawing

    def get_drawings(self) -> List[Drawing]:
        """Get all drawings"""
        return list(self.drawings.values())

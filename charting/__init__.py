"""
Advanced Charting Module

Provides professional-grade charting capabilities.
"""

from .chart_engine import ChartEngine
from .indicators import TechnicalIndicators as IndicatorLibrary
from .drawing_tools import DrawingToolkit, Drawing, DrawingType
from .timeframes import TimeframeManager
from .templates import TemplateManager

chart_engine = ChartEngine(symbol="XAUUSD")
indicator_library = IndicatorLibrary()
drawing_toolkit = DrawingToolkit()
timeframe_manager = TimeframeManager()
template_manager = TemplateManager()

__all__ = [
    'ChartEngine',
    'IndicatorLibrary',
    'DrawingToolkit',
    'Drawing',
    'DrawingType',
    'TimeframeManager',
    'TemplateManager',
    'chart_engine',
    'indicator_library',
    'drawing_toolkit',
    'timeframe_manager',
    'template_manager',
]

# Module metadata
__version__ = '1.0.0'
__author__ = 'HOPEFX Development Team'
__description__ = 'Professional charting with indicators, drawing tools, and templates'

"""
Drawing Tools for Charts

Provides a toolkit for annotating price charts with trendlines,
horizontal lines, rectangles, Fibonacci retracements, text labels,
channels, arc/circle annotations, pitchforks, and Elliott Wave labels.

All multi-parameter drawing methods accept a dedicated config dataclass
to keep the public API clean and extensible.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List

# Default Fibonacci retracement and extension levels
DEFAULT_FIB_LEVELS: List[float] = [0.0, 0.236, 0.382, 0.5, 0.618, 0.786, 1.0]
DEFAULT_FIB_EXTENSIONS: List[float] = [1.272, 1.618, 2.0, 2.618]


# ---------------------------------------------------------------------------
# Drawing type constants
# ---------------------------------------------------------------------------

class DrawingType:
    """String constants for drawing type identifiers."""

    TRENDLINE = "trendline"
    HORIZONTAL_LINE = "horizontal_line"
    VERTICAL_LINE = "vertical_line"
    RECTANGLE = "rectangle"
    FIBONACCI = "fibonacci"
    FIBONACCI_FAN = "fibonacci_fan"
    FIBONACCI_ARC = "fibonacci_arc"
    TEXT = "text"
    CHANNEL = "channel"
    PITCHFORK = "pitchfork"
    ELLIOTT_WAVE = "elliott_wave"
    ARROW = "arrow"
    CIRCLE = "circle"


# ---------------------------------------------------------------------------
# Style / config dataclasses
# ---------------------------------------------------------------------------

@dataclass
class LineStyle:
    """Visual style for line-based drawings."""

    color: str = "#2196F3"
    width: int = 1
    dash: str = "solid"          # 'solid', 'dashed', 'dotted'
    opacity: float = 1.0
    extend: bool = False          # extend line beyond endpoints


@dataclass
class TrendlineConfig:
    """Configuration for a trendline drawing."""

    start_time: datetime
    start_price: float
    end_time: datetime
    end_price: float
    style: LineStyle = field(default_factory=LineStyle)
    label: str = ""


@dataclass
class HorizontalLineConfig:
    """Configuration for a horizontal line drawing."""

    price: float
    label: str = ""
    style: LineStyle = field(default_factory=LineStyle)
    extend_left: bool = True
    extend_right: bool = True


@dataclass
class VerticalLineConfig:
    """Configuration for a vertical line drawing."""

    time: datetime
    label: str = ""
    style: LineStyle = field(default_factory=LineStyle)


@dataclass
class RectangleConfig:
    """Configuration for a rectangle / zone drawing."""

    start_time: datetime
    end_time: datetime
    top_price: float
    bottom_price: float
    fill_color: str = "#2196F380"
    border_style: LineStyle = field(default_factory=LineStyle)
    label: str = ""


@dataclass
class FibonacciConfig:
    """Configuration for Fibonacci retracement / extension."""

    start_time: datetime
    start_price: float
    end_time: datetime
    end_price: float
    levels: List[float] = field(
        default_factory=lambda: list(DEFAULT_FIB_LEVELS)
    )
    extension_levels: List[float] = field(
        default_factory=lambda: list(DEFAULT_FIB_EXTENSIONS)
    )
    style: LineStyle = field(default_factory=LineStyle)


@dataclass
class TextConfig:
    """Configuration for a text annotation."""

    time: datetime
    price: float
    text: str
    font_size: int = 12
    color: str = "#FFFFFF"
    background: str = "#00000080"
    anchor: str = "left"         # 'left', 'center', 'right'


@dataclass
class ChannelConfig:
    """Configuration for a parallel channel drawing."""

    start_time: datetime
    start_price: float
    end_time: datetime
    end_price: float
    channel_width: float         # price-distance between upper and lower band
    style: LineStyle = field(default_factory=LineStyle)
    label: str = ""


@dataclass
class PitchforkConfig:
    """Configuration for an Andrews Pitchfork drawing."""

    pivot_time: datetime
    pivot_price: float
    high_time: datetime
    high_price: float
    low_time: datetime
    low_price: float
    style: LineStyle = field(default_factory=LineStyle)


@dataclass
class ElliottWaveConfig:
    """Configuration for an Elliott Wave annotation."""

    points: List[Dict]           # [{'time': datetime, 'price': float}, ...]
    wave_labels: List[str] = field(
        default_factory=lambda: ["1", "2", "3", "4", "5"]
    )
    style: LineStyle = field(default_factory=LineStyle)
    is_impulse: bool = True      # True = impulse, False = corrective (A-B-C)


@dataclass
class CircleConfig:
    """Configuration for a circle / arc annotation."""

    center_time: datetime
    center_price: float
    radius_bars: int = 5
    radius_price: float = 0.0
    style: LineStyle = field(default_factory=LineStyle)
    label: str = ""


@dataclass
class ArrowConfig:
    """Configuration for an arrow annotation."""

    start_time: datetime
    start_price: float
    end_time: datetime
    end_price: float
    style: LineStyle = field(default_factory=LineStyle)
    label: str = ""


# ---------------------------------------------------------------------------
# Drawing object
# ---------------------------------------------------------------------------

class Drawing:
    """Base drawing object stored in the toolkit."""

    def __init__(self, drawing_type: str):
        self.drawing_type = drawing_type
        self.created_at = datetime.utcnow()
        self.properties: Dict = {}

    def to_dict(self) -> Dict:
        return {
            "drawing_type": self.drawing_type,
            "created_at": self.created_at.isoformat(),
            "properties": self.properties,
        }


# ---------------------------------------------------------------------------
# Toolkit
# ---------------------------------------------------------------------------

class DrawingToolkit:
    """
    Toolkit for annotating price charts.

    Each ``draw_*`` method accepts a typed config dataclass that groups
    related parameters, keeping function signatures concise.

    Usage::

        toolkit = DrawingToolkit()
        cfg = TrendlineConfig(start_time=t0, start_price=1800.0,
                              end_time=t1, end_price=1850.0)
        drawing = toolkit.draw_trendline(cfg)
    """

    def __init__(self):
        self.drawings: Dict[str, Drawing] = {}

    # ------------------------------------------------------------------
    # Primitive helpers
    # ------------------------------------------------------------------

    def _store(self, drawing_id: str, drawing: Drawing) -> Drawing:
        self.drawings[drawing_id] = drawing
        return drawing

    def _ts(self, dt: datetime) -> str:
        return str(int(dt.timestamp() * 1000))

    # ------------------------------------------------------------------
    # Trendline
    # ------------------------------------------------------------------

    def draw_trendline(self, config: TrendlineConfig) -> Drawing:
        """
        Add a trendline annotation.

        Args:
            config: TrendlineConfig with start/end price-time coordinates
                    and optional visual style.

        Returns:
            The created Drawing object.
        """
        drawing = Drawing(DrawingType.TRENDLINE)
        drawing.properties = {
            "start_time": config.start_time,
            "start_price": config.start_price,
            "end_time": config.end_time,
            "end_price": config.end_price,
            "style": config.style,
            "label": config.label,
        }
        return self._store(f"TL_{self._ts(config.start_time)}", drawing)

    # ------------------------------------------------------------------
    # Horizontal line
    # ------------------------------------------------------------------

    def draw_horizontal_line(self, config: HorizontalLineConfig) -> Drawing:
        """
        Add a horizontal line at the given price.

        Args:
            config: HorizontalLineConfig with price and display options.

        Returns:
            The created Drawing object.
        """
        drawing = Drawing(DrawingType.HORIZONTAL_LINE)
        drawing.properties = {
            "price": config.price,
            "label": config.label,
            "style": config.style,
            "extend_left": config.extend_left,
            "extend_right": config.extend_right,
        }
        return self._store(f"HL_{config.price}", drawing)

    # ------------------------------------------------------------------
    # Vertical line
    # ------------------------------------------------------------------

    def draw_vertical_line(self, config: VerticalLineConfig) -> Drawing:
        """
        Add a vertical line at the given timestamp.

        Args:
            config: VerticalLineConfig with timestamp and style.

        Returns:
            The created Drawing object.
        """
        drawing = Drawing(DrawingType.VERTICAL_LINE)
        drawing.properties = {
            "time": config.time,
            "label": config.label,
            "style": config.style,
        }
        return self._store(f"VL_{self._ts(config.time)}", drawing)

    # ------------------------------------------------------------------
    # Rectangle
    # ------------------------------------------------------------------

    def draw_rectangle(self, config: RectangleConfig) -> Drawing:
        """
        Add a rectangle / price zone annotation.

        Args:
            config: RectangleConfig with corner coordinates and fill colour.

        Returns:
            The created Drawing object.
        """
        drawing = Drawing(DrawingType.RECTANGLE)
        drawing.properties = {
            "start_time": config.start_time,
            "end_time": config.end_time,
            "top_price": config.top_price,
            "bottom_price": config.bottom_price,
            "fill_color": config.fill_color,
            "border_style": config.border_style,
            "label": config.label,
        }
        return self._store(f"RECT_{self._ts(config.start_time)}", drawing)

    # ------------------------------------------------------------------
    # Fibonacci retracement
    # ------------------------------------------------------------------

    def draw_fibonacci(self, config: FibonacciConfig) -> Drawing:
        """
        Add a Fibonacci retracement / extension drawing.

        Args:
            config: FibonacciConfig with anchor prices and level lists.

        Returns:
            The created Drawing object.
        """
        drawing = Drawing(DrawingType.FIBONACCI)
        drawing.properties = {
            "start_time": config.start_time,
            "start_price": config.start_price,
            "end_time": config.end_time,
            "end_price": config.end_price,
            "levels": config.levels,
            "extension_levels": config.extension_levels,
            "style": config.style,
        }
        return self._store(f"FIB_{self._ts(config.start_time)}", drawing)

    # ------------------------------------------------------------------
    # Text label
    # ------------------------------------------------------------------

    def draw_text(self, config: TextConfig) -> Drawing:
        """
        Add a text annotation at the given price/time location.

        Args:
            config: TextConfig with position and display options.

        Returns:
            The created Drawing object.
        """
        drawing = Drawing(DrawingType.TEXT)
        drawing.properties = {
            "time": config.time,
            "price": config.price,
            "text": config.text,
            "font_size": config.font_size,
            "color": config.color,
            "background": config.background,
            "anchor": config.anchor,
        }
        return self._store(f"TXT_{self._ts(config.time)}_{config.text[:8]}", drawing)

    # ------------------------------------------------------------------
    # Channel
    # ------------------------------------------------------------------

    def draw_channel(self, config: ChannelConfig) -> Drawing:
        """
        Add a parallel channel (upper and lower trendlines).

        Args:
            config: ChannelConfig with anchor points and channel width.

        Returns:
            The created Drawing object.
        """
        drawing = Drawing(DrawingType.CHANNEL)
        drawing.properties = {
            "start_time": config.start_time,
            "start_price": config.start_price,
            "end_time": config.end_time,
            "end_price": config.end_price,
            "channel_width": config.channel_width,
            "style": config.style,
            "label": config.label,
        }
        return self._store(f"CH_{self._ts(config.start_time)}", drawing)

    # ------------------------------------------------------------------
    # Pitchfork
    # ------------------------------------------------------------------

    def draw_pitchfork(self, config: PitchforkConfig) -> Drawing:
        """
        Add an Andrews Pitchfork annotation.

        Args:
            config: PitchforkConfig with pivot and two swing points.

        Returns:
            The created Drawing object.
        """
        drawing = Drawing(DrawingType.PITCHFORK)
        drawing.properties = {
            "pivot_time": config.pivot_time,
            "pivot_price": config.pivot_price,
            "high_time": config.high_time,
            "high_price": config.high_price,
            "low_time": config.low_time,
            "low_price": config.low_price,
            "style": config.style,
        }
        return self._store(f"PF_{self._ts(config.pivot_time)}", drawing)

    # ------------------------------------------------------------------
    # Elliott Wave
    # ------------------------------------------------------------------

    def draw_elliott_wave(self, config: ElliottWaveConfig) -> Drawing:
        """
        Add an Elliott Wave label sequence.

        Args:
            config: ElliottWaveConfig with wave pivot points and labels.

        Returns:
            The created Drawing object.
        """
        drawing = Drawing(DrawingType.ELLIOTT_WAVE)
        drawing.properties = {
            "points": config.points,
            "wave_labels": config.wave_labels,
            "is_impulse": config.is_impulse,
            "style": config.style,
        }
        first_time = config.points[0]["time"] if config.points else datetime.utcnow()
        return self._store(f"EW_{self._ts(first_time)}", drawing)

    # ------------------------------------------------------------------
    # Circle / Arc
    # ------------------------------------------------------------------

    def draw_circle(self, config: CircleConfig) -> Drawing:
        """
        Add a circle or arc annotation.

        Args:
            config: CircleConfig with centre coordinates and radius.

        Returns:
            The created Drawing object.
        """
        drawing = Drawing(DrawingType.CIRCLE)
        drawing.properties = {
            "center_time": config.center_time,
            "center_price": config.center_price,
            "radius_bars": config.radius_bars,
            "radius_price": config.radius_price,
            "style": config.style,
            "label": config.label,
        }
        return self._store(f"CIR_{self._ts(config.center_time)}", drawing)

    # ------------------------------------------------------------------
    # Arrow
    # ------------------------------------------------------------------

    def draw_arrow(self, config: ArrowConfig) -> Drawing:
        """
        Add an arrow annotation.

        Args:
            config: ArrowConfig with start/end coordinates.

        Returns:
            The created Drawing object.
        """
        drawing = Drawing(DrawingType.ARROW)
        drawing.properties = {
            "start_time": config.start_time,
            "start_price": config.start_price,
            "end_time": config.end_time,
            "end_price": config.end_price,
            "style": config.style,
            "label": config.label,
        }
        return self._store(f"ARR_{self._ts(config.start_time)}", drawing)

    # ------------------------------------------------------------------
    # Fibonacci fan
    # ------------------------------------------------------------------

    def draw_fibonacci_fan(self, config: FibonacciConfig) -> Drawing:
        """
        Add a Fibonacci fan drawing.

        Args:
            config: FibonacciConfig with anchor points and fan levels.

        Returns:
            The created Drawing object.
        """
        drawing = Drawing(DrawingType.FIBONACCI_FAN)
        drawing.properties = {
            "start_time": config.start_time,
            "start_price": config.start_price,
            "end_time": config.end_time,
            "end_price": config.end_price,
            "levels": config.levels,
            "style": config.style,
        }
        return self._store(f"FIBF_{self._ts(config.start_time)}", drawing)

    # ------------------------------------------------------------------
    # Query helpers
    # ------------------------------------------------------------------

    def get_drawings(self) -> List[Drawing]:
        """Return all stored drawings."""
        return list(self.drawings.values())

    def get_drawings_by_type(self, drawing_type: str) -> List[Drawing]:
        """
        Return drawings of a specific type.

        Args:
            drawing_type: One of the DrawingType constants.

        Returns:
            Filtered list of Drawing objects.
        """
        return [d for d in self.drawings.values() if d.drawing_type == drawing_type]

    def remove_drawing(self, drawing_id: str) -> bool:
        """
        Remove a drawing by ID.

        Args:
            drawing_id: The key used when the drawing was stored.

        Returns:
            True if the drawing was found and removed, False otherwise.
        """
        if drawing_id in self.drawings:
            del self.drawings[drawing_id]
            return True
        return False

    def clear(self) -> None:
        """Remove all drawings."""
        self.drawings.clear()

    def to_dict(self) -> Dict:
        """Serialise all drawings to a dictionary."""
        return {k: v.to_dict() for k, v in self.drawings.items()}

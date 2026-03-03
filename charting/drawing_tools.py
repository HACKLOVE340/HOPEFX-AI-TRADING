"""
Drawing Tools for Charts

Provides a toolkit for annotating price charts with trendlines,
horizontal lines, rectangles, Fibonacci retracements, text labels,
channels, arc/circle annotations, pitchforks, and Elliott Wave labels.
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

# Default Fibonacci retracement and extension levels
DEFAULT_FIB_LEVELS: List[float] = [0.0, 0.236, 0.382, 0.5, 0.618, 0.786, 1.0]
DEFAULT_FIB_EXTENSIONS: List[float] = [1.272, 1.618, 2.0, 2.618]

_VALID_ARROW_DIRECTIONS = ("up", "down")


# ---------------------------------------------------------------------------
# Drawing type constants
# ---------------------------------------------------------------------------

class DrawingType:
    """String constants for drawing type identifiers."""

    TRENDLINE = "trendline"
    HORIZONTAL_LINE = "horizontal_line"
    VERTICAL_LINE = "vertical_line"
    RECTANGLE = "rectangle"
    HORIZONTAL_BAND = "horizontal_band"
    FIBONACCI_RETRACEMENT = "fibonacci_retracement"
    FIBONACCI_EXTENSION = "fibonacci_extension"
    FIBONACCI_FAN = "fibonacci_fan"
    TEXT = "text"
    CHANNEL = "channel"
    PITCHFORK = "pitchfork"
    ELLIOTT_WAVE = "elliott_wave"
    ARROW = "arrow"
    CIRCLE = "circle"


# ---------------------------------------------------------------------------
# Drawing object
# ---------------------------------------------------------------------------

class Drawing:
    """A single chart annotation stored in the toolkit."""

    def __init__(
        self,
        drawing_type: str,
        drawing_id: Optional[str] = None,
        color: str = "#2196F3",
        line_width: int = 1,
    ) -> None:
        self.drawing_type = drawing_type
        self.drawing_id = (
            drawing_id
            if drawing_id is not None
            else f"{drawing_type}_{datetime.now(timezone.utc).timestamp()}"
        )
        self.color = color
        self.line_width = line_width
        self.visible: bool = True
        self.properties: Dict[str, Any] = {}
        self.created_at: datetime = datetime.now(timezone.utc)

    def __repr__(self) -> str:
        return f"Drawing(type={self.drawing_type!r}, id={self.drawing_id!r})"

    def to_dict(self) -> Dict[str, Any]:
        """Serialise the drawing to a plain dictionary."""
        return {
            "drawing_id": self.drawing_id,
            "drawing_type": self.drawing_type,
            "color": self.color,
            "line_width": self.line_width,
            "visible": self.visible,
            "properties": self.properties,
            "created_at": self.created_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Drawing":
        """Restore a Drawing from a serialised dictionary."""
        drawing = cls(
            drawing_type=data["drawing_type"],
            drawing_id=data.get("drawing_id"),
            color=data.get("color", "#2196F3"),
            line_width=data.get("line_width", 1),
        )
        drawing.visible = data.get("visible", True)
        drawing.properties = data.get("properties", {})
        return drawing


# ---------------------------------------------------------------------------
# Toolkit
# ---------------------------------------------------------------------------

class DrawingToolkit:
    """
    Toolkit for annotating price charts.

    Usage::

        toolkit = DrawingToolkit()
        drawing = toolkit.draw_trendline(t0, 1800.0, t1, 1850.0)
    """

    def __init__(self) -> None:
        self.drawings: Dict[str, Drawing] = {}

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _store(self, drawing: Drawing) -> Drawing:
        self.drawings[drawing.drawing_id] = drawing
        return drawing

    def _ts(self, dt: datetime) -> str:
        return str(int(dt.timestamp() * 1000))

    # ------------------------------------------------------------------
    # Trendline
    # ------------------------------------------------------------------

    def draw_trendline(
        self,
        start_time: datetime,
        start_price: float,
        end_time: datetime,
        end_price: float,
        extend: bool = False,
        label: str = "",
    ) -> Drawing:
        """
        Add a trendline annotation.

        Args:
            start_time: Start timestamp.
            start_price: Price at the start point.
            end_time: End timestamp.
            end_price: Price at the end point.
            extend: Whether to extend the line beyond its endpoints.
            label: Optional label text.

        Returns:
            The created Drawing object.
        """
        dt_secs = (end_time - start_time).total_seconds()
        slope = (end_price - start_price) / dt_secs if dt_secs != 0 else 0.0
        drawing = Drawing(DrawingType.TRENDLINE)
        drawing.properties = {
            "start_time": start_time,
            "start_price": start_price,
            "end_time": end_time,
            "end_price": end_price,
            "extend": extend,
            "slope": slope,
            "label": label,
        }
        drawing.drawing_id = f"TL_{self._ts(start_time)}"
        return self._store(drawing)

    # ------------------------------------------------------------------
    # Horizontal line
    # ------------------------------------------------------------------

    def draw_horizontal_line(
        self,
        price: float,
        label: Optional[str] = None,
        style: str = "solid",
    ) -> Drawing:
        """
        Add a horizontal line at the given price.

        Args:
            price: The price level for the line.
            label: Optional label; defaults to the price value as a string.
            style: Line dash style (e.g. 'solid', 'dashed').

        Returns:
            The created Drawing object.
        """
        drawing = Drawing(DrawingType.HORIZONTAL_LINE)
        drawing.properties = {
            "price": price,
            "label": label if label is not None else str(price),
            "style": style,
        }
        drawing.drawing_id = f"HL_{price}"
        return self._store(drawing)

    # ------------------------------------------------------------------
    # Vertical line
    # ------------------------------------------------------------------

    def draw_vertical_line(
        self,
        time: datetime,
        label: str = "",
    ) -> Drawing:
        """
        Add a vertical line at the given timestamp.

        Args:
            time: The timestamp for the vertical line.
            label: Optional label text.

        Returns:
            The created Drawing object.
        """
        drawing = Drawing(DrawingType.VERTICAL_LINE)
        drawing.properties = {
            "time": time.isoformat(),
            "label": label,
        }
        drawing.drawing_id = f"VL_{self._ts(time)}"
        return self._store(drawing)

    # ------------------------------------------------------------------
    # Rectangle
    # ------------------------------------------------------------------

    def draw_rectangle(
        self,
        start_time: datetime,
        start_price: float,
        end_time: datetime,
        end_price: float,
        fill_opacity: float = 0.1,
        label: str = "",
    ) -> Drawing:
        """
        Add a rectangle / price zone annotation.

        Args:
            start_time: Top-left corner timestamp.
            start_price: Price at the start corner.
            end_time: Bottom-right corner timestamp.
            end_price: Price at the end corner.
            fill_opacity: Fill opacity clamped to [0.0, 1.0].
            label: Optional label text.

        Returns:
            The created Drawing object.
        """
        fill_opacity = max(0.0, min(1.0, fill_opacity))
        drawing = Drawing(DrawingType.RECTANGLE)
        drawing.properties = {
            "start_time": start_time,
            "start_price": start_price,
            "end_time": end_time,
            "end_price": end_price,
            "fill_opacity": fill_opacity,
            "label": label,
        }
        drawing.drawing_id = f"RECT_{self._ts(start_time)}"
        return self._store(drawing)

    # ------------------------------------------------------------------
    # Horizontal band
    # ------------------------------------------------------------------

    def draw_horizontal_band(
        self,
        price_a: float,
        price_b: float,
        label: Optional[str] = None,
    ) -> Drawing:
        """
        Add a horizontal price band between two price levels.

        Args:
            price_a: First price boundary (order does not matter).
            price_b: Second price boundary.
            label: Optional label; defaults to a string showing both prices.

        Returns:
            The created Drawing object.
        """
        upper_price = max(price_a, price_b)
        lower_price = min(price_a, price_b)
        drawing = Drawing(DrawingType.HORIZONTAL_BAND)
        drawing.properties = {
            "upper_price": upper_price,
            "lower_price": lower_price,
            "label": (
                label
                if label is not None
                else f"{lower_price}-{upper_price}"
            ),
        }
        drawing.drawing_id = f"HB_{lower_price}_{upper_price}"
        return self._store(drawing)

    # ------------------------------------------------------------------
    # Fibonacci retracement
    # ------------------------------------------------------------------

    def draw_fibonacci(
        self,
        start_time: datetime,
        start_price: float,
        end_time: datetime,
        end_price: float,
        levels: Optional[List[float]] = None,
    ) -> Drawing:
        """
        Add a Fibonacci retracement drawing.

        Args:
            start_time: Swing-low timestamp.
            start_price: Swing-low price.
            end_time: Swing-high timestamp.
            end_price: Swing-high price.
            levels: Retracement levels (0–1); defaults to DEFAULT_FIB_LEVELS.

        Returns:
            The created Drawing object.
        """
        if levels is None:
            levels = list(DEFAULT_FIB_LEVELS)
        price_range = end_price - start_price
        level_prices: Dict[str, float] = {}
        for lvl in levels:
            pct = lvl * 100
            key = f"{int(pct)}%" if pct % 1 == 0 else f"{pct}%"
            level_prices[key] = end_price - lvl * price_range
        drawing = Drawing(DrawingType.FIBONACCI_RETRACEMENT)
        drawing.properties = {
            "start_time": start_time,
            "start_price": start_price,
            "end_time": end_time,
            "end_price": end_price,
            "levels": levels,
            "level_prices": level_prices,
        }
        drawing.drawing_id = f"FIB_{self._ts(start_time)}"
        return self._store(drawing)

    # ------------------------------------------------------------------
    # Fibonacci extension
    # ------------------------------------------------------------------

    def draw_fibonacci_extension(
        self,
        time_a: datetime,
        price_a: float,
        time_b: datetime,
        price_b: float,
        time_c: datetime,
        price_c: float,
        levels: Optional[List[float]] = None,
    ) -> Drawing:
        """
        Add a Fibonacci extension drawing using three swing points (A, B, C).

        Args:
            time_a: Timestamp of swing point A.
            price_a: Price of swing point A.
            time_b: Timestamp of swing point B.
            price_b: Price of swing point B.
            time_c: Timestamp of swing point C.
            price_c: Price of swing point C.
            levels: Extension levels; defaults to DEFAULT_FIB_EXTENSIONS.

        Returns:
            The created Drawing object.
        """
        if levels is None:
            levels = list(DEFAULT_FIB_EXTENSIONS)
        swing = price_b - price_a
        level_prices: Dict[str, float] = {
            str(lvl): price_c + lvl * swing for lvl in levels
        }
        drawing = Drawing(DrawingType.FIBONACCI_EXTENSION)
        drawing.properties = {
            "time_a": time_a,
            "price_a": price_a,
            "time_b": time_b,
            "price_b": price_b,
            "time_c": time_c,
            "price_c": price_c,
            "levels": levels,
            "level_prices": level_prices,
        }
        drawing.drawing_id = f"FIBE_{self._ts(time_a)}"
        return self._store(drawing)

    # ------------------------------------------------------------------
    # Channel
    # ------------------------------------------------------------------

    def draw_channel(
        self,
        start_time: datetime,
        start_price: float,
        end_time: datetime,
        end_price: float,
        channel_width: float = 0.0,
        label: str = "",
    ) -> Drawing:
        """
        Add a parallel channel (upper and lower trendlines).

        Args:
            start_time: Start timestamp of the midline.
            start_price: Midline price at the start.
            end_time: End timestamp of the midline.
            end_price: Midline price at the end.
            channel_width: Offset from the midline to each band (i.e. half
                the total visual channel width).
            label: Optional label text.

        Returns:
            The created Drawing object.
        """
        drawing = Drawing(DrawingType.CHANNEL)
        drawing.properties = {
            "start_time": start_time,
            "start_price": start_price,
            "end_time": end_time,
            "end_price": end_price,
            "channel_width": channel_width,
            "upper_start": start_price + channel_width,
            "lower_start": start_price - channel_width,
            "upper_end": end_price + channel_width,
            "lower_end": end_price - channel_width,
            "label": label,
        }
        drawing.drawing_id = f"CH_{self._ts(start_time)}"
        return self._store(drawing)

    # ------------------------------------------------------------------
    # Pitchfork
    # ------------------------------------------------------------------

    def draw_pitchfork(
        self,
        pivot_time: datetime,
        pivot_price: float,
        high_time: datetime,
        high_price: float,
        low_time: datetime,
        low_price: float,
    ) -> Drawing:
        """
        Add an Andrews Pitchfork annotation.

        Args:
            pivot_time: Timestamp of the pivot point.
            pivot_price: Price of the pivot point.
            high_time: Timestamp of the high swing point.
            high_price: Price of the high swing point.
            low_time: Timestamp of the low swing point.
            low_price: Price of the low swing point.

        Returns:
            The created Drawing object.
        """
        midpoint_price = (high_price + low_price) / 2.0
        drawing = Drawing(DrawingType.PITCHFORK)
        drawing.properties = {
            "pivot_time": pivot_time,
            "pivot_price": pivot_price,
            "high_time": high_time,
            "high_price": high_price,
            "low_time": low_time,
            "low_price": low_price,
            "midpoint_price": midpoint_price,
        }
        drawing.drawing_id = f"PF_{self._ts(pivot_time)}"
        return self._store(drawing)

    # ------------------------------------------------------------------
    # Elliott Wave
    # ------------------------------------------------------------------

    def draw_elliott_wave(
        self,
        points: List[Dict],
        wave_type: str = "impulse",
    ) -> Drawing:
        """
        Add an Elliott Wave label sequence.

        Args:
            points: List of wave pivot dicts with 'time', 'price', 'label'.
            wave_type: 'impulse' or 'corrective'.

        Returns:
            The created Drawing object.

        Raises:
            ValueError: If fewer than 2 points are provided.
        """
        if len(points) < 2:
            raise ValueError("At least 2 points are required for an Elliott Wave.")
        drawing = Drawing(DrawingType.ELLIOTT_WAVE)
        drawing.properties = {
            "points": points,
            "wave_count": len(points),
            "wave_type": wave_type,
        }
        drawing.drawing_id = f"EW_{datetime.now(timezone.utc).timestamp()}"
        return self._store(drawing)

    # ------------------------------------------------------------------
    # Text label
    # ------------------------------------------------------------------

    def draw_text(
        self,
        time: datetime,
        price: float,
        text: str,
        font_size: int = 12,
        color: str = "#FFFFFF",
        background: str = "#00000080",
        anchor: str = "left",
    ) -> Drawing:
        """
        Add a text annotation at the given price/time location.

        Args:
            time: Timestamp for the annotation.
            price: Price level for the annotation.
            text: Display text.
            font_size: Font size in points.
            color: Text colour.
            background: Background colour.
            anchor: Text alignment ('left', 'center', 'right').

        Returns:
            The created Drawing object.
        """
        drawing = Drawing(DrawingType.TEXT)
        drawing.properties = {
            "time": time,
            "price": price,
            "text": text,
            "font_size": font_size,
            "color": color,
            "background": background,
            "anchor": anchor,
        }
        drawing.drawing_id = f"TXT_{self._ts(time)}_{text[:8]}"
        return self._store(drawing)

    # ------------------------------------------------------------------
    # Arrow
    # ------------------------------------------------------------------

    def draw_arrow(
        self,
        time: datetime,
        price: float,
        direction: str,
        label: str = "",
    ) -> Drawing:
        """
        Add an arrow annotation.

        Args:
            time: Timestamp for the arrow.
            price: Price level for the arrow.
            direction: 'up' or 'down'.
            label: Optional label text.

        Returns:
            The created Drawing object.

        Raises:
            ValueError: If direction is not 'up' or 'down'.
        """
        if direction not in _VALID_ARROW_DIRECTIONS:
            raise ValueError(
                f"Invalid direction {direction!r}; must be one of {_VALID_ARROW_DIRECTIONS}."
            )
        drawing = Drawing(DrawingType.ARROW)
        drawing.properties = {
            "time": time,
            "price": price,
            "direction": direction,
            "label": label,
        }
        drawing.drawing_id = f"ARR_{self._ts(time)}_{direction}"
        return self._store(drawing)

    # ------------------------------------------------------------------
    # Query helpers
    # ------------------------------------------------------------------

    def get_drawings(self, drawing_type: Optional[str] = None) -> List[Drawing]:
        """
        Return stored drawings, optionally filtered by type.

        Args:
            drawing_type: If provided, only drawings of this type are returned.

        Returns:
            List of Drawing objects.
        """
        drawings = list(self.drawings.values())
        if drawing_type is not None:
            drawings = [d for d in drawings if d.drawing_type == drawing_type]
        return drawings

    def get_drawing(self, drawing_id: str) -> Optional[Drawing]:
        """
        Return the drawing with the given ID, or None.

        Args:
            drawing_id: The unique drawing identifier.

        Returns:
            The Drawing object, or None if not found.
        """
        return self.drawings.get(drawing_id)

    def get_drawings_count(self) -> int:
        """Return the total number of stored drawings."""
        return len(self.drawings)

    def remove_drawing(self, drawing_id: str) -> bool:
        """
        Remove a drawing by ID.

        Args:
            drawing_id: The unique drawing identifier.

        Returns:
            True if the drawing was found and removed, False otherwise.
        """
        if drawing_id in self.drawings:
            del self.drawings[drawing_id]
            return True
        return False

    def clear_drawings(self, drawing_type: Optional[str] = None) -> int:
        """
        Remove drawings, optionally filtered by type.

        Args:
            drawing_type: If provided, only drawings of this type are removed.

        Returns:
            The number of drawings removed.
        """
        if drawing_type is None:
            count = len(self.drawings)
            self.drawings.clear()
            return count
        to_remove = [
            k for k, d in self.drawings.items() if d.drawing_type == drawing_type
        ]
        for key in to_remove:
            del self.drawings[key]
        return len(to_remove)

    def hide_drawing(self, drawing_id: str) -> bool:
        """
        Set a drawing's visibility to False.

        Returns:
            True if the drawing was found, False otherwise.
        """
        drawing = self.drawings.get(drawing_id)
        if drawing is None:
            return False
        drawing.visible = False
        return True

    def show_drawing(self, drawing_id: str) -> bool:
        """
        Set a drawing's visibility to True.

        Returns:
            True if the drawing was found, False otherwise.
        """
        drawing = self.drawings.get(drawing_id)
        if drawing is None:
            return False
        drawing.visible = True
        return True

    def update_drawing(self, drawing_id: str, **kwargs: Any) -> bool:
        """
        Update attributes of a drawing.

        The ``color`` keyword updates ``drawing.color`` directly.
        All other keywords are stored in ``drawing.properties``.

        Returns:
            True if the drawing was found, False otherwise.
        """
        drawing = self.drawings.get(drawing_id)
        if drawing is None:
            return False
        for key, value in kwargs.items():
            if key == "color":
                drawing.color = value
            else:
                drawing.properties[key] = value
        return True

    def export_drawings(self) -> List[Dict[str, Any]]:
        """Export all drawings as a list of serialised dictionaries."""
        return [d.to_dict() for d in self.drawings.values()]

    def import_drawings(self, data: List[Dict[str, Any]]) -> int:
        """
        Import drawings from a list of serialised dictionaries.

        Entries that are missing the 'drawing_type' key are silently skipped.

        Args:
            data: List of dicts as produced by export_drawings().

        Returns:
            The number of drawings successfully imported.
        """
        count = 0
        for item in data:
            if "drawing_type" not in item:
                continue
            drawing = Drawing.from_dict(item)
            self.drawings[drawing.drawing_id] = drawing
            count += 1
        return count

    def to_dict(self) -> Dict[str, Any]:
        """Serialise all drawings to a dictionary keyed by drawing ID."""
        return {k: v.to_dict() for k, v in self.drawings.items()}

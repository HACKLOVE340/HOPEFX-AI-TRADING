"""
Tests for Phase 20: Enhanced Drawing Tools (charting/drawing_tools.py)
and Phase 26: White-Label Module (whitelabel/).
"""

import pytest
from datetime import datetime, timedelta, timezone


# ===========================================================================
# Phase 20: Enhanced Drawing Tools
# ===========================================================================

@pytest.mark.unit
class TestDrawingType:
    """Test DrawingType constants."""

    def test_all_drawing_types_defined(self):
        from charting.drawing_tools import DrawingType
        assert DrawingType.TRENDLINE == "trendline"
        assert DrawingType.HORIZONTAL_LINE == "horizontal_line"
        assert DrawingType.VERTICAL_LINE == "vertical_line"
        assert DrawingType.RECTANGLE == "rectangle"
        assert DrawingType.HORIZONTAL_BAND == "horizontal_band"
        assert DrawingType.FIBONACCI_RETRACEMENT == "fibonacci_retracement"
        assert DrawingType.FIBONACCI_EXTENSION == "fibonacci_extension"
        assert DrawingType.PITCHFORK == "pitchfork"
        assert DrawingType.CHANNEL == "channel"
        assert DrawingType.ELLIOTT_WAVE == "elliott_wave"
        assert DrawingType.TEXT == "text"
        assert DrawingType.ARROW == "arrow"


@pytest.mark.unit
class TestDrawing:
    """Test the Drawing dataclass."""

    def test_drawing_creation_defaults(self):
        from charting.drawing_tools import Drawing, DrawingType
        d = Drawing(DrawingType.TRENDLINE)
        assert d.drawing_type == DrawingType.TRENDLINE
        assert d.visible is True
        assert d.color == "#2196F3"
        assert d.line_width == 1
        assert isinstance(d.properties, dict)

    def test_drawing_custom_attrs(self):
        from charting.drawing_tools import Drawing, DrawingType
        d = Drawing(DrawingType.HORIZONTAL_LINE, color="#FF0000", line_width=2)
        assert d.color == "#FF0000"
        assert d.line_width == 2

    def test_drawing_custom_id(self):
        from charting.drawing_tools import Drawing, DrawingType
        d = Drawing(DrawingType.TEXT, drawing_id="my_id_123")
        assert d.drawing_id == "my_id_123"

    def test_drawing_auto_id(self):
        from charting.drawing_tools import Drawing, DrawingType
        d = Drawing(DrawingType.ARROW)
        assert DrawingType.ARROW in d.drawing_id

    def test_to_dict(self):
        from charting.drawing_tools import Drawing, DrawingType
        d = Drawing(DrawingType.RECTANGLE, drawing_id="rect_1")
        d.properties = {"start_price": 1900.0}
        result = d.to_dict()
        assert result["drawing_id"] == "rect_1"
        assert result["drawing_type"] == DrawingType.RECTANGLE
        assert result["visible"] is True
        assert result["properties"]["start_price"] == 1900.0
        assert "created_at" in result

    def test_from_dict_roundtrip(self):
        from charting.drawing_tools import Drawing, DrawingType
        d = Drawing(DrawingType.FIBONACCI_RETRACEMENT, drawing_id="fib_1", color="#FF5722")
        d.properties = {"levels": [0.382, 0.618]}
        d.visible = False
        data = d.to_dict()
        restored = Drawing.from_dict(data)
        assert restored.drawing_id == "fib_1"
        assert restored.color == "#FF5722"
        assert restored.visible is False
        assert restored.properties["levels"] == [0.382, 0.618]

    def test_repr(self):
        from charting.drawing_tools import Drawing, DrawingType
        d = Drawing(DrawingType.TEXT, drawing_id="txt_1")
        r = repr(d)
        assert "text" in r
        assert "txt_1" in r


@pytest.mark.unit
class TestDrawingToolkitTrendline:
    """Tests for trendline drawing."""

    @pytest.fixture
    def toolkit(self):
        from charting.drawing_tools import DrawingToolkit
        return DrawingToolkit()

    def test_draw_trendline_basic(self, toolkit):
        from charting.drawing_tools import DrawingType
        t0 = datetime(2024, 1, 1, 9, 0)
        t1 = datetime(2024, 1, 1, 12, 0)
        d = toolkit.draw_trendline(t0, 1900.0, t1, 1920.0)
        assert d.drawing_type == DrawingType.TRENDLINE
        assert d.properties["start_price"] == 1900.0
        assert d.properties["end_price"] == 1920.0
        assert d.properties["extend"] is False

    def test_draw_trendline_extended(self, toolkit):
        t0 = datetime(2024, 1, 1, 9, 0)
        t1 = datetime(2024, 1, 1, 12, 0)
        d = toolkit.draw_trendline(t0, 1900.0, t1, 1920.0, extend=True)
        assert d.properties["extend"] is True

    def test_trendline_slope_calculated(self, toolkit):
        t0 = datetime(2024, 1, 1, 0, 0)
        t1 = datetime(2024, 1, 1, 1, 0)  # 1 hour = 3600s
        d = toolkit.draw_trendline(t0, 1000.0, t1, 1036.0)
        # slope = (1036 - 1000) / 3600
        assert abs(d.properties["slope"] - 36 / 3600) < 1e-9

    def test_trendline_stored(self, toolkit):
        t0 = datetime(2024, 1, 1, 9, 0)
        t1 = datetime(2024, 1, 1, 12, 0)
        d = toolkit.draw_trendline(t0, 1900.0, t1, 1920.0)
        assert d.drawing_id in toolkit.drawings


@pytest.mark.unit
class TestDrawingToolkitHorizontalLine:
    """Tests for horizontal line drawing."""

    @pytest.fixture
    def toolkit(self):
        from charting.drawing_tools import DrawingToolkit
        return DrawingToolkit()

    def test_draw_horizontal_line(self, toolkit):
        from charting.drawing_tools import DrawingType
        d = toolkit.draw_horizontal_line(1950.0)
        assert d.drawing_type == DrawingType.HORIZONTAL_LINE
        assert d.properties["price"] == 1950.0

    def test_horizontal_line_custom_label(self, toolkit):
        d = toolkit.draw_horizontal_line(2000.0, label="Resistance")
        assert d.properties["label"] == "Resistance"

    def test_horizontal_line_default_label(self, toolkit):
        d = toolkit.draw_horizontal_line(1234.56789)
        assert "1234.56789" in d.properties["label"]

    def test_horizontal_line_style(self, toolkit):
        d = toolkit.draw_horizontal_line(1950.0, style="dashed")
        assert d.properties["style"] == "dashed"


@pytest.mark.unit
class TestDrawingToolkitVerticalLine:
    """Tests for vertical line drawing."""

    @pytest.fixture
    def toolkit(self):
        from charting.drawing_tools import DrawingToolkit
        return DrawingToolkit()

    def test_draw_vertical_line(self, toolkit):
        from charting.drawing_tools import DrawingType
        t = datetime(2024, 6, 1, 14, 0)
        d = toolkit.draw_vertical_line(t)
        assert d.drawing_type == DrawingType.VERTICAL_LINE
        assert "2024-06-01" in d.properties["time"]

    def test_vertical_line_label(self, toolkit):
        t = datetime(2024, 6, 1, 14, 0)
        d = toolkit.draw_vertical_line(t, label="NFP")
        assert d.properties["label"] == "NFP"


@pytest.mark.unit
class TestDrawingToolkitRectangle:
    """Tests for rectangle drawing."""

    @pytest.fixture
    def toolkit(self):
        from charting.drawing_tools import DrawingToolkit
        return DrawingToolkit()

    def test_draw_rectangle(self, toolkit):
        from charting.drawing_tools import DrawingType
        t0 = datetime(2024, 1, 1)
        t1 = datetime(2024, 1, 5)
        d = toolkit.draw_rectangle(t0, 1900.0, t1, 1950.0)
        assert d.drawing_type == DrawingType.RECTANGLE
        assert d.properties["start_price"] == 1900.0
        assert d.properties["end_price"] == 1950.0
        assert d.properties["fill_opacity"] == 0.1

    def test_rectangle_fill_opacity_clamped(self, toolkit):
        t0 = datetime(2024, 1, 1)
        t1 = datetime(2024, 1, 5)
        d = toolkit.draw_rectangle(t0, 1900.0, t1, 1950.0, fill_opacity=5.0)
        assert d.properties["fill_opacity"] == 1.0

        d2 = toolkit.draw_rectangle(t0, 1900.0, t1, 1950.0, fill_opacity=-1.0)
        assert d2.properties["fill_opacity"] == 0.0


@pytest.mark.unit
class TestDrawingToolkitHorizontalBand:
    """Tests for horizontal band drawing."""

    @pytest.fixture
    def toolkit(self):
        from charting.drawing_tools import DrawingToolkit
        return DrawingToolkit()

    def test_draw_horizontal_band(self, toolkit):
        from charting.drawing_tools import DrawingType
        d = toolkit.draw_horizontal_band(1960.0, 1940.0)
        assert d.drawing_type == DrawingType.HORIZONTAL_BAND
        assert d.properties["upper_price"] == 1960.0
        assert d.properties["lower_price"] == 1940.0

    def test_horizontal_band_auto_sort(self, toolkit):
        # Passing lower value first should auto-sort
        d = toolkit.draw_horizontal_band(1940.0, 1960.0)
        assert d.properties["upper_price"] == 1960.0
        assert d.properties["lower_price"] == 1940.0

    def test_horizontal_band_label(self, toolkit):
        d = toolkit.draw_horizontal_band(1960.0, 1940.0, label="Support Zone")
        assert d.properties["label"] == "Support Zone"

    def test_horizontal_band_default_label(self, toolkit):
        d = toolkit.draw_horizontal_band(1960.0, 1940.0)
        assert "1940" in d.properties["label"] or "1960" in d.properties["label"]


@pytest.mark.unit
class TestDrawingToolkitFibonacci:
    """Tests for Fibonacci retracement drawing."""

    @pytest.fixture
    def toolkit(self):
        from charting.drawing_tools import DrawingToolkit
        return DrawingToolkit()

    def test_draw_fibonacci_defaults(self, toolkit):
        from charting.drawing_tools import DrawingType
        t0 = datetime(2024, 1, 1)
        t1 = datetime(2024, 1, 10)
        d = toolkit.draw_fibonacci(t0, 1800.0, t1, 2000.0)
        assert d.drawing_type == DrawingType.FIBONACCI_RETRACEMENT
        assert 0.618 in d.properties["levels"]
        assert 0.382 in d.properties["levels"]

    def test_fibonacci_level_prices_calculated(self, toolkit):
        t0 = datetime(2024, 1, 1)
        t1 = datetime(2024, 1, 10)
        # Swing: 1800 → 2000 (range = 200)
        d = toolkit.draw_fibonacci(t0, 1800.0, t1, 2000.0, levels=[0.0, 0.5, 1.0])
        level_prices = d.properties["level_prices"]
        assert level_prices["0%"] == pytest.approx(2000.0)
        assert level_prices["50%"] == pytest.approx(1900.0)
        assert level_prices["100%"] == pytest.approx(1800.0)

    def test_fibonacci_custom_levels(self, toolkit):
        t0 = datetime(2024, 1, 1)
        t1 = datetime(2024, 1, 10)
        custom = [0.25, 0.75]
        d = toolkit.draw_fibonacci(t0, 1800.0, t1, 2000.0, levels=custom)
        assert d.properties["levels"] == custom


@pytest.mark.unit
class TestDrawingToolkitFibonacciExtension:
    """Tests for Fibonacci extension drawing."""

    @pytest.fixture
    def toolkit(self):
        from charting.drawing_tools import DrawingToolkit
        return DrawingToolkit()

    def test_draw_fibonacci_extension(self, toolkit):
        from charting.drawing_tools import DrawingType
        ta = datetime(2024, 1, 1)
        tb = datetime(2024, 1, 5)
        tc = datetime(2024, 1, 8)
        d = toolkit.draw_fibonacci_extension(ta, 1800.0, tb, 2000.0, tc, 1900.0)
        assert d.drawing_type == DrawingType.FIBONACCI_EXTENSION
        # Default levels include 1.618
        assert 1.618 in d.properties["levels"]

    def test_fibonacci_extension_prices(self, toolkit):
        ta = datetime(2024, 1, 1)
        tb = datetime(2024, 1, 5)
        tc = datetime(2024, 1, 8)
        # A=1800, B=2000, C=1900; swing=200
        # 1.618 extension: 1900 + 1.618*200 = 2223.6
        d = toolkit.draw_fibonacci_extension(ta, 1800.0, tb, 2000.0, tc, 1900.0, levels=[1.618])
        level_prices = d.properties["level_prices"]
        assert level_prices["1.618"] == pytest.approx(1900.0 + 1.618 * 200.0, rel=1e-4)


@pytest.mark.unit
class TestDrawingToolkitPitchfork:
    """Tests for Andrews' Pitchfork drawing."""

    @pytest.fixture
    def toolkit(self):
        from charting.drawing_tools import DrawingToolkit
        return DrawingToolkit()

    def test_draw_pitchfork(self, toolkit):
        from charting.drawing_tools import DrawingType
        tp = datetime(2024, 1, 1)
        th = datetime(2024, 1, 5)
        tl = datetime(2024, 1, 5)
        d = toolkit.draw_pitchfork(tp, 1900.0, th, 1950.0, tl, 1860.0)
        assert d.drawing_type == DrawingType.PITCHFORK
        assert d.properties["pivot_price"] == 1900.0
        assert d.properties["midpoint_price"] == pytest.approx((1950.0 + 1860.0) / 2)

    def test_pitchfork_midpoint(self, toolkit):
        tp = datetime(2024, 1, 1)
        th = datetime(2024, 1, 5)
        tl = datetime(2024, 1, 5)
        d = toolkit.draw_pitchfork(tp, 1900.0, th, 2000.0, tl, 1800.0)
        assert d.properties["midpoint_price"] == pytest.approx(1900.0)


@pytest.mark.unit
class TestDrawingToolkitChannel:
    """Tests for channel drawing."""

    @pytest.fixture
    def toolkit(self):
        from charting.drawing_tools import DrawingToolkit
        return DrawingToolkit()

    def test_draw_channel(self, toolkit):
        from charting.drawing_tools import DrawingType
        t0 = datetime(2024, 1, 1)
        t1 = datetime(2024, 1, 10)
        d = toolkit.draw_channel(t0, 1900.0, t1, 1950.0, channel_width=20.0)
        assert d.drawing_type == DrawingType.CHANNEL
        assert d.properties["upper_start"] == pytest.approx(1920.0)
        assert d.properties["lower_start"] == pytest.approx(1880.0)
        assert d.properties["upper_end"] == pytest.approx(1970.0)
        assert d.properties["lower_end"] == pytest.approx(1930.0)


@pytest.mark.unit
class TestDrawingToolkitElliottWave:
    """Tests for Elliott Wave annotation."""

    @pytest.fixture
    def toolkit(self):
        from charting.drawing_tools import DrawingToolkit
        return DrawingToolkit()

    def test_draw_elliott_wave(self, toolkit):
        from charting.drawing_tools import DrawingType
        points = [
            {"time": "2024-01-01", "price": 1800.0, "label": "0"},
            {"time": "2024-01-05", "price": 1900.0, "label": "1"},
            {"time": "2024-01-08", "price": 1850.0, "label": "2"},
            {"time": "2024-01-15", "price": 2000.0, "label": "3"},
            {"time": "2024-01-18", "price": 1950.0, "label": "4"},
            {"time": "2024-01-25", "price": 2100.0, "label": "5"},
        ]
        d = toolkit.draw_elliott_wave(points, wave_type="impulse")
        assert d.drawing_type == DrawingType.ELLIOTT_WAVE
        assert d.properties["wave_count"] == 6
        assert d.properties["wave_type"] == "impulse"

    def test_elliott_wave_too_few_points(self, toolkit):
        with pytest.raises(ValueError, match="At least 2"):
            toolkit.draw_elliott_wave([{"time": "2024-01-01", "price": 1800.0, "label": "0"}])

    def test_elliott_wave_corrective(self, toolkit):
        points = [
            {"time": "2024-01-01", "price": 2000.0, "label": "A"},
            {"time": "2024-01-05", "price": 1900.0, "label": "B"},
            {"time": "2024-01-10", "price": 1850.0, "label": "C"},
        ]
        d = toolkit.draw_elliott_wave(points, wave_type="corrective")
        assert d.properties["wave_type"] == "corrective"


@pytest.mark.unit
class TestDrawingToolkitText:
    """Tests for text annotation."""

    @pytest.fixture
    def toolkit(self):
        from charting.drawing_tools import DrawingToolkit
        return DrawingToolkit()

    def test_draw_text(self, toolkit):
        from charting.drawing_tools import DrawingType
        t = datetime(2024, 3, 1, 10, 0)
        d = toolkit.draw_text(t, 1950.0, "Key level")
        assert d.drawing_type == DrawingType.TEXT
        assert d.properties["text"] == "Key level"
        assert d.properties["price"] == 1950.0
        assert d.properties["font_size"] == 12

    def test_draw_text_custom_font(self, toolkit):
        t = datetime(2024, 3, 1, 10, 0)
        d = toolkit.draw_text(t, 1950.0, "Big label", font_size=18)
        assert d.properties["font_size"] == 18

    def test_draw_text_background(self, toolkit):
        t = datetime(2024, 3, 1, 10, 0)
        d = toolkit.draw_text(t, 1950.0, "Alert", background="#FF0000")
        assert d.properties["background"] == "#FF0000"


@pytest.mark.unit
class TestDrawingToolkitArrow:
    """Tests for arrow annotation."""

    @pytest.fixture
    def toolkit(self):
        from charting.drawing_tools import DrawingToolkit
        return DrawingToolkit()

    def test_draw_arrow_up(self, toolkit):
        from charting.drawing_tools import DrawingType
        t = datetime(2024, 3, 1, 10, 0)
        d = toolkit.draw_arrow(t, 1900.0, direction="up")
        assert d.drawing_type == DrawingType.ARROW
        assert d.properties["direction"] == "up"

    def test_draw_arrow_down(self, toolkit):
        t = datetime(2024, 3, 1, 10, 0)
        d = toolkit.draw_arrow(t, 1950.0, direction="down")
        assert d.properties["direction"] == "down"

    def test_draw_arrow_invalid_direction(self, toolkit):
        t = datetime(2024, 3, 1, 10, 0)
        with pytest.raises(ValueError, match="direction"):
            toolkit.draw_arrow(t, 1900.0, direction="left")

    def test_draw_arrow_label(self, toolkit):
        t = datetime(2024, 3, 1, 10, 0)
        d = toolkit.draw_arrow(t, 1900.0, direction="up", label="Buy Signal")
        assert d.properties["label"] == "Buy Signal"


@pytest.mark.unit
class TestDrawingToolkitManagement:
    """Tests for drawing management methods."""

    @pytest.fixture
    def toolkit(self):
        from charting.drawing_tools import DrawingToolkit
        return DrawingToolkit()

    @pytest.fixture
    def populated_toolkit(self, toolkit):
        """Toolkit with a variety of drawings."""
        t0 = datetime(2024, 1, 1)
        t1 = datetime(2024, 1, 5)
        toolkit.draw_trendline(t0, 1900.0, t1, 1950.0)
        toolkit.draw_horizontal_line(2000.0)
        toolkit.draw_horizontal_line(1800.0)
        toolkit.draw_text(t0, 1920.0, "Note")
        return toolkit

    def test_get_drawings_all(self, populated_toolkit):
        drawings = populated_toolkit.get_drawings()
        assert len(drawings) == 4

    def test_get_drawings_filtered(self, populated_toolkit):
        from charting.drawing_tools import DrawingType
        h_lines = populated_toolkit.get_drawings(DrawingType.HORIZONTAL_LINE)
        assert len(h_lines) == 2

    def test_get_drawing_by_id(self, populated_toolkit):
        drawings = populated_toolkit.get_drawings()
        d = populated_toolkit.get_drawing(drawings[0].drawing_id)
        assert d is not None
        assert d.drawing_id == drawings[0].drawing_id

    def test_get_drawing_nonexistent(self, populated_toolkit):
        assert populated_toolkit.get_drawing("nonexistent_id") is None

    def test_remove_drawing(self, populated_toolkit):
        drawings = populated_toolkit.get_drawings()
        did = drawings[0].drawing_id
        result = populated_toolkit.remove_drawing(did)
        assert result is True
        assert populated_toolkit.get_drawing(did) is None
        assert populated_toolkit.get_drawings_count() == 3

    def test_remove_nonexistent_drawing(self, toolkit):
        assert toolkit.remove_drawing("ghost_id") is False

    def test_clear_all_drawings(self, populated_toolkit):
        count = populated_toolkit.clear_drawings()
        assert count == 4
        assert populated_toolkit.get_drawings_count() == 0

    def test_clear_drawings_by_type(self, populated_toolkit):
        from charting.drawing_tools import DrawingType
        removed = populated_toolkit.clear_drawings(DrawingType.HORIZONTAL_LINE)
        assert removed == 2
        assert populated_toolkit.get_drawings_count() == 2

    def test_show_hide_drawing(self, populated_toolkit):
        drawings = populated_toolkit.get_drawings()
        did = drawings[0].drawing_id
        assert populated_toolkit.hide_drawing(did) is True
        assert populated_toolkit.get_drawing(did).visible is False
        assert populated_toolkit.show_drawing(did) is True
        assert populated_toolkit.get_drawing(did).visible is True

    def test_hide_nonexistent(self, toolkit):
        assert toolkit.hide_drawing("ghost") is False

    def test_show_nonexistent(self, toolkit):
        assert toolkit.show_drawing("ghost") is False

    def test_update_drawing_color(self, populated_toolkit):
        drawings = populated_toolkit.get_drawings()
        did = drawings[0].drawing_id
        result = populated_toolkit.update_drawing(did, color="#FF0000")
        assert result is True
        assert populated_toolkit.get_drawing(did).color == "#FF0000"

    def test_update_drawing_custom_property(self, populated_toolkit):
        drawings = populated_toolkit.get_drawings()
        did = drawings[0].drawing_id
        populated_toolkit.update_drawing(did, custom_key="custom_val")
        assert populated_toolkit.get_drawing(did).properties.get("custom_key") == "custom_val"

    def test_update_nonexistent_drawing(self, toolkit):
        assert toolkit.update_drawing("ghost", color="#000") is False

    def test_export_import_drawings(self, populated_toolkit):
        exported = populated_toolkit.export_drawings()
        assert isinstance(exported, list)
        assert len(exported) == 4

        from charting.drawing_tools import DrawingToolkit
        fresh = DrawingToolkit()
        count = fresh.import_drawings(exported)
        assert count == 4
        assert fresh.get_drawings_count() == 4

    def test_import_invalid_data_skipped(self, toolkit):
        bad_data = [{"invalid": "no drawing_type key"}]
        count = toolkit.import_drawings(bad_data)
        assert count == 0
        assert toolkit.get_drawings_count() == 0

    def test_get_drawings_count(self, populated_toolkit):
        assert populated_toolkit.get_drawings_count() == 4

    def test_empty_toolkit_count(self):
        from charting.drawing_tools import DrawingToolkit
        assert DrawingToolkit().get_drawings_count() == 0


# ===========================================================================
# Phase 26: White-Label Module
# ===========================================================================

@pytest.mark.unit
class TestBrandTheme:
    """Tests for BrandTheme."""

    def test_default_values(self):
        from whitelabel import BrandTheme
        theme = BrandTheme()
        assert theme.primary_color == "#1976D2"
        assert theme.app_name == "Trading Platform"
        assert theme.font_family == "Inter, sans-serif"
        assert theme.custom_css == ""

    def test_to_dict(self):
        from whitelabel import BrandTheme
        theme = BrandTheme(primary_color="#FF0000", app_name="MyApp")
        d = theme.to_dict()
        assert d["primary_color"] == "#FF0000"
        assert d["app_name"] == "MyApp"

    def test_from_dict_roundtrip(self):
        from whitelabel import BrandTheme
        original = BrandTheme(primary_color="#ABCDEF", tagline="Trade smart")
        restored = BrandTheme.from_dict(original.to_dict())
        assert restored.primary_color == "#ABCDEF"
        assert restored.tagline == "Trade smart"

    def test_to_css_variables_contains_primary(self):
        from whitelabel import BrandTheme
        theme = BrandTheme(primary_color="#1976D2")
        css = theme.to_css_variables()
        assert "--color-primary: #1976D2" in css
        assert ":root {" in css

    def test_to_css_variables_includes_custom_css(self):
        from whitelabel import BrandTheme
        theme = BrandTheme(custom_css="body { margin: 0; }")
        css = theme.to_css_variables()
        assert "body { margin: 0; }" in css


@pytest.mark.unit
class TestTenant:
    """Tests for Tenant dataclass."""

    @pytest.fixture
    def sample_tenant(self):
        from whitelabel import Tenant, TenantStatus
        return Tenant(
            tenant_id="t001",
            name="Acme Trading",
            owner_email="admin@acme.com",
            status=TenantStatus.ACTIVE,
        )

    def test_tenant_creation(self, sample_tenant):
        assert sample_tenant.tenant_id == "t001"
        assert sample_tenant.name == "Acme Trading"

    def test_tenant_is_active_active_status(self, sample_tenant):
        assert sample_tenant.is_active() is True

    def test_tenant_is_active_suspended(self, sample_tenant):
        from whitelabel import TenantStatus
        sample_tenant.status = TenantStatus.SUSPENDED
        assert sample_tenant.is_active() is False

    def test_tenant_is_active_trial(self, sample_tenant):
        from whitelabel import TenantStatus
        sample_tenant.status = TenantStatus.TRIAL
        assert sample_tenant.is_active() is True

    def test_tenant_is_active_expired(self, sample_tenant):
        sample_tenant.expires_at = datetime.now(timezone.utc) - timedelta(days=1)
        assert sample_tenant.is_active() is False

    def test_tenant_is_active_not_yet_expired(self, sample_tenant):
        sample_tenant.expires_at = datetime.now(timezone.utc) + timedelta(days=7)
        assert sample_tenant.is_active() is True

    def test_tenant_has_feature(self, sample_tenant):
        from whitelabel import FeatureFlag
        sample_tenant.features = [FeatureFlag.TRADING, FeatureFlag.BACKTESTING]
        assert sample_tenant.has_feature(FeatureFlag.TRADING) is True
        assert sample_tenant.has_feature(FeatureFlag.SOCIAL_TRADING) is False

    def test_tenant_can_add_user_below_limit(self, sample_tenant):
        sample_tenant.max_users = 10
        sample_tenant.user_count = 5
        assert sample_tenant.can_add_user() is True

    def test_tenant_can_add_user_at_limit(self, sample_tenant):
        sample_tenant.max_users = 10
        sample_tenant.user_count = 10
        assert sample_tenant.can_add_user() is False


@pytest.mark.unit
class TestReseller:
    """Tests for Reseller dataclass."""

    def test_reseller_creation(self):
        from whitelabel import Reseller, ResellerTier
        r = Reseller(
            reseller_id="r001",
            company_name="BrokerCo",
            contact_email="support@brokerco.com",
        )
        assert r.reseller_id == "r001"
        assert r.tier == ResellerTier.STANDARD
        assert r.commission_rate == 0.15
        assert r.is_active is True
        assert len(r.referral_code) > 4

    def test_reseller_gold_tier(self):
        from whitelabel import Reseller, ResellerTier
        r = Reseller(
            reseller_id="r002",
            company_name="GoldBroker",
            contact_email="vip@gold.com",
            tier=ResellerTier.GOLD,
            commission_rate=0.25,
        )
        assert r.tier == ResellerTier.GOLD
        assert r.commission_rate == 0.25


@pytest.mark.unit
class TestWhiteLabelManagerTenants:
    """Tests for WhiteLabelManager tenant operations."""

    @pytest.fixture
    def manager(self):
        from whitelabel import WhiteLabelManager
        return WhiteLabelManager()

    def test_create_tenant(self, manager):
        t = manager.create_tenant("Acme", "admin@acme.com")
        assert t is not None
        assert t.name == "Acme"
        assert t.owner_email == "admin@acme.com"
        assert t.tenant_id in manager.tenants

    def test_create_tenant_trial_has_expiry(self, manager):
        t = manager.create_tenant("Trial Co", "x@x.com", trial_days=14)
        assert t.expires_at is not None
        assert t.expires_at > datetime.now(timezone.utc)

    def test_create_tenant_no_trial(self, manager):
        from whitelabel import TenantStatus
        t = manager.create_tenant("Perm Co", "y@y.com", trial_days=0)
        assert t.expires_at is None
        assert t.status == TenantStatus.ACTIVE

    def test_get_tenant(self, manager):
        t = manager.create_tenant("Foo", "foo@foo.com")
        fetched = manager.get_tenant(t.tenant_id)
        assert fetched is t

    def test_get_tenant_nonexistent(self, manager):
        assert manager.get_tenant("bad_id") is None

    def test_activate_tenant(self, manager):
        from whitelabel import TenantStatus
        t = manager.create_tenant("Activatable", "a@a.com", trial_days=7)
        result = manager.activate_tenant(t.tenant_id)
        assert result is True
        assert t.status == TenantStatus.ACTIVE
        assert t.expires_at is None

    def test_activate_nonexistent_tenant(self, manager):
        assert manager.activate_tenant("ghost") is False

    def test_suspend_tenant(self, manager):
        from whitelabel import TenantStatus
        t = manager.create_tenant("SuspendMe", "s@s.com")
        manager.activate_tenant(t.tenant_id)
        result = manager.suspend_tenant(t.tenant_id)
        assert result is True
        assert t.status == TenantStatus.SUSPENDED

    def test_suspend_nonexistent_tenant(self, manager):
        assert manager.suspend_tenant("ghost") is False

    def test_delete_tenant(self, manager):
        t = manager.create_tenant("DeleteMe", "d@d.com")
        tid = t.tenant_id
        result = manager.delete_tenant(tid)
        assert result is True
        assert manager.get_tenant(tid) is None

    def test_delete_nonexistent_tenant(self, manager):
        assert manager.delete_tenant("ghost") is False

    def test_delete_tenant_removes_domain(self, manager):
        t = manager.create_tenant("DomainTest", "dm@dm.com")
        manager.set_custom_domain(t.tenant_id, "platform.dm.com")
        manager.delete_tenant(t.tenant_id)
        assert manager.resolve_domain("platform.dm.com") is None

    def test_list_tenants_all(self, manager):
        manager.create_tenant("A", "a@a.com")
        manager.create_tenant("B", "b@b.com")
        tenants = manager.list_tenants()
        assert len(tenants) == 2

    def test_list_tenants_filtered_by_status(self, manager):
        from whitelabel import TenantStatus
        t = manager.create_tenant("Trial", "t@t.com", trial_days=7)
        t2 = manager.create_tenant("Active", "ac@ac.com", trial_days=0)
        trial_list = manager.list_tenants(status=TenantStatus.TRIAL)
        assert t in trial_list
        assert t2 not in trial_list


@pytest.mark.unit
class TestWhiteLabelManagerTheme:
    """Tests for brand theme management."""

    @pytest.fixture
    def manager_with_tenant(self):
        from whitelabel import WhiteLabelManager
        mgr = WhiteLabelManager()
        t = mgr.create_tenant("Branded", "b@b.com")
        return mgr, t

    def test_update_theme(self, manager_with_tenant):
        mgr, t = manager_with_tenant
        result = mgr.update_theme(t.tenant_id, {"primary_color": "#FF0000", "app_name": "MyBrand"})
        assert result is True
        assert t.theme.primary_color == "#FF0000"
        assert t.theme.app_name == "MyBrand"

    def test_update_theme_nonexistent(self, manager_with_tenant):
        mgr, _ = manager_with_tenant
        assert mgr.update_theme("ghost", {"primary_color": "#000"}) is False

    def test_get_theme(self, manager_with_tenant):
        from whitelabel import BrandTheme
        mgr, t = manager_with_tenant
        theme = mgr.get_theme(t.tenant_id)
        assert isinstance(theme, BrandTheme)

    def test_get_theme_nonexistent(self, manager_with_tenant):
        mgr, _ = manager_with_tenant
        assert mgr.get_theme("ghost") is None


@pytest.mark.unit
class TestWhiteLabelManagerFeatures:
    """Tests for feature flag management."""

    @pytest.fixture
    def manager_with_tenant(self):
        from whitelabel import WhiteLabelManager, FeatureFlag
        mgr = WhiteLabelManager()
        t = mgr.create_tenant("FeatureTenant", "ft@ft.com",
                               features=[FeatureFlag.TRADING])
        return mgr, t

    def test_enable_feature(self, manager_with_tenant):
        from whitelabel import FeatureFlag
        mgr, t = manager_with_tenant
        result = mgr.enable_feature(t.tenant_id, FeatureFlag.SOCIAL_TRADING)
        assert result is True
        assert FeatureFlag.SOCIAL_TRADING in t.features

    def test_enable_feature_idempotent(self, manager_with_tenant):
        from whitelabel import FeatureFlag
        mgr, t = manager_with_tenant
        mgr.enable_feature(t.tenant_id, FeatureFlag.TRADING)
        mgr.enable_feature(t.tenant_id, FeatureFlag.TRADING)
        # Should not duplicate
        count = sum(1 for f in t.features if f == FeatureFlag.TRADING)
        assert count == 1

    def test_disable_feature(self, manager_with_tenant):
        from whitelabel import FeatureFlag
        mgr, t = manager_with_tenant
        result = mgr.disable_feature(t.tenant_id, FeatureFlag.TRADING)
        assert result is True
        assert FeatureFlag.TRADING not in t.features

    def test_disable_nonexistent_feature_is_noop(self, manager_with_tenant):
        from whitelabel import FeatureFlag
        mgr, t = manager_with_tenant
        result = mgr.disable_feature(t.tenant_id, FeatureFlag.SOCIAL_TRADING)
        assert result is True  # No error, just a no-op

    def test_enable_feature_nonexistent_tenant(self, manager_with_tenant):
        from whitelabel import FeatureFlag
        mgr, _ = manager_with_tenant
        assert mgr.enable_feature("ghost", FeatureFlag.TRADING) is False

    def test_disable_feature_nonexistent_tenant(self, manager_with_tenant):
        from whitelabel import FeatureFlag
        mgr, _ = manager_with_tenant
        assert mgr.disable_feature("ghost", FeatureFlag.TRADING) is False

    def test_get_tenant_features(self, manager_with_tenant):
        from whitelabel import FeatureFlag
        mgr, t = manager_with_tenant
        features = mgr.get_tenant_features(t.tenant_id)
        assert FeatureFlag.TRADING in features

    def test_get_features_nonexistent(self, manager_with_tenant):
        mgr, _ = manager_with_tenant
        features = mgr.get_tenant_features("ghost")
        assert features == []


@pytest.mark.unit
class TestWhiteLabelManagerDomain:
    """Tests for custom domain management."""

    @pytest.fixture
    def manager(self):
        from whitelabel import WhiteLabelManager
        return WhiteLabelManager()

    def test_set_custom_domain(self, manager):
        t = manager.create_tenant("DomainCo", "d@d.com")
        result = manager.set_custom_domain(t.tenant_id, "trade.domainco.com")
        assert result is True
        assert t.custom_domain == "trade.domainco.com"

    def test_resolve_domain(self, manager):
        t = manager.create_tenant("ResolveCo", "r@r.com")
        manager.set_custom_domain(t.tenant_id, "app.resolveco.com")
        resolved = manager.resolve_domain("app.resolveco.com")
        assert resolved is t

    def test_resolve_unknown_domain(self, manager):
        assert manager.resolve_domain("unknown.example.com") is None

    def test_domain_conflict(self, manager):
        t1 = manager.create_tenant("Co1", "a@a.com")
        t2 = manager.create_tenant("Co2", "b@b.com")
        manager.set_custom_domain(t1.tenant_id, "shared.com")
        result = manager.set_custom_domain(t2.tenant_id, "shared.com")
        assert result is False

    def test_reassign_own_domain(self, manager):
        t = manager.create_tenant("Reassign", "x@x.com")
        manager.set_custom_domain(t.tenant_id, "old.example.com")
        result = manager.set_custom_domain(t.tenant_id, "old.example.com")
        assert result is True

    def test_set_domain_updates_old_mapping(self, manager):
        t = manager.create_tenant("Redomained", "y@y.com")
        manager.set_custom_domain(t.tenant_id, "old.example.com")
        manager.set_custom_domain(t.tenant_id, "new.example.com")
        assert manager.resolve_domain("old.example.com") is None
        assert manager.resolve_domain("new.example.com") is t


@pytest.mark.unit
class TestWhiteLabelManagerResellers:
    """Tests for reseller management."""

    @pytest.fixture
    def manager(self):
        from whitelabel import WhiteLabelManager
        return WhiteLabelManager()

    def test_create_reseller(self, manager):
        from whitelabel import ResellerTier
        r = manager.create_reseller("BrokerCo", "support@brokerco.com")
        assert r is not None
        assert r.company_name == "BrokerCo"
        assert r.tier == ResellerTier.STANDARD
        assert r.commission_rate == 0.15

    def test_create_reseller_gold_tier(self, manager):
        from whitelabel import ResellerTier
        r = manager.create_reseller("VIPBroker", "vip@vip.com", tier=ResellerTier.GOLD)
        assert r.commission_rate == 0.25

    def test_get_reseller(self, manager):
        r = manager.create_reseller("GetMe", "g@g.com")
        fetched = manager.get_reseller(r.reseller_id)
        assert fetched is r

    def test_get_reseller_nonexistent(self, manager):
        assert manager.get_reseller("ghost") is None

    def test_calculate_commission(self, manager):
        r = manager.create_reseller("CommCo", "c@c.com")
        commission = manager.calculate_commission(r.reseller_id, 1000.0)
        assert commission == pytest.approx(150.0)  # 15% of 1000

    def test_calculate_commission_platinum(self, manager):
        from whitelabel import ResellerTier
        r = manager.create_reseller("PlatCo", "p@p.com", tier=ResellerTier.PLATINUM)
        commission = manager.calculate_commission(r.reseller_id, 1000.0)
        assert commission == pytest.approx(300.0)  # 30% of 1000

    def test_calculate_commission_updates_revenue(self, manager):
        r = manager.create_reseller("Rev", "rv@rv.com")
        manager.calculate_commission(r.reseller_id, 500.0)
        manager.calculate_commission(r.reseller_id, 300.0)
        assert r.total_revenue == pytest.approx(800.0)

    def test_calculate_commission_inactive_reseller(self, manager):
        r = manager.create_reseller("Inactive", "i@i.com")
        r.is_active = False
        commission = manager.calculate_commission(r.reseller_id, 1000.0)
        assert commission == 0.0

    def test_calculate_commission_nonexistent(self, manager):
        commission = manager.calculate_commission("ghost", 1000.0)
        assert commission == 0.0

    def test_upgrade_reseller_tier(self, manager):
        from whitelabel import ResellerTier
        r = manager.create_reseller("UpgradeCo", "u@u.com")
        r.total_tenants = 5  # Meets Silver threshold
        new_tier = manager.upgrade_reseller_tier(r.reseller_id)
        assert new_tier == ResellerTier.SILVER
        assert r.commission_rate == pytest.approx(0.20)

    def test_upgrade_reseller_tier_platinum(self, manager):
        from whitelabel import ResellerTier
        r = manager.create_reseller("PlatinumCo", "pt@pt.com")
        r.total_tenants = 30
        new_tier = manager.upgrade_reseller_tier(r.reseller_id)
        assert new_tier == ResellerTier.PLATINUM

    def test_upgrade_reseller_tier_no_change(self, manager):
        from whitelabel import ResellerTier
        r = manager.create_reseller("SameCo", "sc@sc.com")
        r.total_tenants = 0  # Already at STANDARD threshold
        result = manager.upgrade_reseller_tier(r.reseller_id)
        assert result is None  # No upgrade needed

    def test_upgrade_nonexistent_reseller(self, manager):
        assert manager.upgrade_reseller_tier("ghost") is None

    def test_tenant_linked_to_reseller(self, manager):
        r = manager.create_reseller("LinkedBroker", "lb@lb.com")
        t = manager.create_tenant("Client", "cl@cl.com", reseller_id=r.reseller_id)
        assert t.reseller_id == r.reseller_id
        assert r.total_tenants == 1


@pytest.mark.unit
class TestWhiteLabelManagerExportImport:
    """Tests for tenant export/import."""

    @pytest.fixture
    def manager(self):
        from whitelabel import WhiteLabelManager
        return WhiteLabelManager()

    def test_export_tenant_config(self, manager):
        from whitelabel import FeatureFlag
        t = manager.create_tenant("ExportTest", "et@et.com")
        manager.update_theme(t.tenant_id, {"app_name": "ExportApp"})
        config = manager.export_tenant_config(t.tenant_id)
        assert config is not None
        assert config["name"] == "ExportTest"
        assert config["theme"]["app_name"] == "ExportApp"
        assert "features" in config

    def test_export_nonexistent_tenant(self, manager):
        assert manager.export_tenant_config("ghost") is None

    def test_import_tenant_config(self, manager):
        from whitelabel import FeatureFlag
        t = manager.create_tenant("Original", "or@or.com")
        manager.enable_feature(t.tenant_id, FeatureFlag.SOCIAL_TRADING)
        config = manager.export_tenant_config(t.tenant_id)

        # Import into a fresh manager
        from whitelabel import WhiteLabelManager
        fresh_mgr = WhiteLabelManager()
        imported = fresh_mgr.import_tenant_config(config)
        assert imported.name == "Original"
        assert FeatureFlag.SOCIAL_TRADING in imported.features

    def test_import_with_custom_domain(self, manager):
        t = manager.create_tenant("DomainExport", "de@de.com")
        manager.set_custom_domain(t.tenant_id, "export.example.com")
        config = manager.export_tenant_config(t.tenant_id)

        from whitelabel import WhiteLabelManager
        fresh = WhiteLabelManager()
        fresh.import_tenant_config(config)
        resolved = fresh.resolve_domain("export.example.com")
        assert resolved is not None


@pytest.mark.unit
class TestWhiteLabelManagerSummary:
    """Tests for platform summary."""

    @pytest.fixture
    def manager(self):
        from whitelabel import WhiteLabelManager, TenantStatus
        mgr = WhiteLabelManager()
        t1 = mgr.create_tenant("A", "a@a.com", trial_days=0)  # ACTIVE
        t2 = mgr.create_tenant("B", "b@b.com", trial_days=7)  # TRIAL
        t1.user_count = 5
        t2.user_count = 3
        mgr.create_reseller("R1", "r1@r1.com")
        return mgr

    def test_get_platform_summary(self, manager):
        summary = manager.get_platform_summary()
        assert summary["total_tenants"] == 2
        assert summary["active_tenants"] == 1
        assert summary["trial_tenants"] == 1
        assert summary["total_resellers"] == 1
        assert summary["total_users"] == 8


@pytest.mark.unit
class TestWhiteLabelConstants:
    """Test tier constants are correct."""

    def test_tier_commission_rates(self):
        from whitelabel import TIER_COMMISSION_RATES, ResellerTier
        assert TIER_COMMISSION_RATES[ResellerTier.STANDARD] == 0.15
        assert TIER_COMMISSION_RATES[ResellerTier.SILVER] == 0.20
        assert TIER_COMMISSION_RATES[ResellerTier.GOLD] == 0.25
        assert TIER_COMMISSION_RATES[ResellerTier.PLATINUM] == 0.30

    def test_tier_tenant_thresholds(self):
        from whitelabel import TIER_TENANT_THRESHOLDS, ResellerTier
        assert TIER_TENANT_THRESHOLDS[ResellerTier.STANDARD] == 0
        assert TIER_TENANT_THRESHOLDS[ResellerTier.SILVER] == 5
        assert TIER_TENANT_THRESHOLDS[ResellerTier.GOLD] == 15
        assert TIER_TENANT_THRESHOLDS[ResellerTier.PLATINUM] == 30

    def test_all_feature_flags_accessible(self):
        from whitelabel import FeatureFlag
        flags = list(FeatureFlag)
        assert len(flags) >= 13  # All defined flags

    def test_module_singleton_accessible(self):
        from whitelabel import white_label_manager, WhiteLabelManager
        assert isinstance(white_label_manager, WhiteLabelManager)

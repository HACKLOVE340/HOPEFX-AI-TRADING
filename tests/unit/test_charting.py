"""
Tests for the charting module.
"""

import pytest
import numpy as np
from datetime import datetime

from charting.chart_engine import Chart, ChartEngine, ChartType
from charting.indicators import Indicator, SMA, EMA, RSI, IndicatorLibrary


class TestChartType:
    """Tests for ChartType constants."""
    
    def test_chart_type_values(self):
        """Test ChartType constant values."""
        assert ChartType.CANDLESTICK == "candlestick"
        assert ChartType.LINE == "line"
        assert ChartType.BAR == "bar"
        assert ChartType.AREA == "area"
        assert ChartType.HEIKIN_ASHI == "heikin_ashi"


class TestChart:
    """Tests for Chart class."""
    
    def test_chart_creation(self):
        """Test creating a chart."""
        chart = Chart('EUR/USD', '1H')
        
        assert chart.symbol == 'EUR/USD'
        assert chart.timeframe == '1H'
        assert chart.chart_type == ChartType.CANDLESTICK
        assert chart.indicators == []
        assert chart.drawings == []
    
    def test_chart_custom_type(self):
        """Test creating chart with custom type."""
        chart = Chart('BTC/USD', '4H', ChartType.LINE)
        
        assert chart.chart_type == ChartType.LINE
    
    def test_add_indicator(self):
        """Test adding indicator to chart."""
        chart = Chart('EUR/USD', '1H')
        
        chart.add_indicator('SMA', period=20)
        
        assert len(chart.indicators) == 1
        assert chart.indicators[0]['name'] == 'SMA'
        assert chart.indicators[0]['params']['period'] == 20
    
    def test_add_multiple_indicators(self):
        """Test adding multiple indicators."""
        chart = Chart('EUR/USD', '1H')
        
        chart.add_indicator('SMA', period=20)
        chart.add_indicator('EMA', period=50)
        chart.add_indicator('RSI', period=14)
        
        assert len(chart.indicators) == 3
    
    def test_render_chart(self):
        """Test rendering chart."""
        chart = Chart('EUR/USD', '1H', ChartType.CANDLESTICK)
        chart.add_indicator('SMA', period=20)
        
        result = chart.render()
        
        assert result['symbol'] == 'EUR/USD'
        assert result['timeframe'] == '1H'
        assert result['type'] == ChartType.CANDLESTICK
        assert result['format'] == 'plotly'
        assert len(result['indicators']) == 1
    
    def test_render_custom_format(self):
        """Test rendering with custom format."""
        chart = Chart('EUR/USD', '1H')
        
        result = chart.render(output_format='json')
        
        assert result['format'] == 'json'


class TestChartEngine:
    """Tests for ChartEngine class."""
    
    def test_engine_initialization(self):
        """Test ChartEngine initialization."""
        engine = ChartEngine()
        
        assert engine is not None
        assert len(engine.charts) == 0
    
    def test_create_chart(self):
        """Test creating a chart via engine."""
        engine = ChartEngine()
        
        chart = engine.create_chart('EUR/USD', '1H')
        
        assert chart is not None
        assert chart.symbol == 'EUR/USD'
        assert len(engine.charts) == 1
    
    def test_create_chart_with_type(self):
        """Test creating chart with specific type."""
        engine = ChartEngine()
        
        chart = engine.create_chart('BTC/USD', '4H', ChartType.LINE)
        
        assert chart.chart_type == ChartType.LINE
    
    def test_get_chart_nonexistent(self):
        """Test getting non-existent chart."""
        engine = ChartEngine()
        
        chart = engine.get_chart('nonexistent')
        
        assert chart is None


class TestIndicator:
    """Tests for base Indicator class."""
    
    def test_indicator_initialization(self):
        """Test Indicator initialization."""
        indicator = SMA('SMA', 20)
        
        assert indicator.name == 'SMA'
        assert indicator.period == 20
    
    def test_base_indicator_not_implemented(self):
        """Test that base Indicator.calculate raises NotImplementedError."""
        indicator = Indicator('test', 10)
        
        with pytest.raises(NotImplementedError):
            indicator.calculate([1, 2, 3])


class TestSMA:
    """Tests for Simple Moving Average indicator."""
    
    def test_sma_calculation(self):
        """Test SMA calculation."""
        sma = SMA('SMA', 3)
        data = [1.0, 2.0, 3.0, 4.0, 5.0]
        
        result = sma.calculate(data)
        
        assert len(result) == 3
        assert result[0] == 2.0  # (1+2+3)/3
        assert result[1] == 3.0  # (2+3+4)/3
        assert result[2] == 4.0  # (3+4+5)/3
    
    def test_sma_insufficient_data(self):
        """Test SMA with insufficient data."""
        sma = SMA('SMA', 10)
        data = [1.0, 2.0, 3.0]
        
        result = sma.calculate(data)
        
        assert result == []
    
    def test_sma_exact_period(self):
        """Test SMA with data length equal to period."""
        sma = SMA('SMA', 3)
        data = [1.0, 2.0, 3.0]
        
        result = sma.calculate(data)
        
        assert len(result) == 1
        assert result[0] == 2.0


class TestEMA:
    """Tests for Exponential Moving Average indicator."""
    
    def test_ema_calculation(self):
        """Test EMA calculation."""
        ema = EMA('EMA', 3)
        data = [1.0, 2.0, 3.0, 4.0, 5.0]
        
        result = ema.calculate(data)
        
        assert len(result) > 0
        # First value is SMA
        assert result[0] == 2.0  # (1+2+3)/3
    
    def test_ema_insufficient_data(self):
        """Test EMA with insufficient data."""
        ema = EMA('EMA', 10)
        data = [1.0, 2.0, 3.0]
        
        result = ema.calculate(data)
        
        assert result == []
    
    def test_ema_smoothing(self):
        """Test EMA values are smoothed."""
        ema = EMA('EMA', 5)
        data = [10.0, 11.0, 12.0, 13.0, 14.0, 15.0, 16.0]
        
        result = ema.calculate(data)
        
        # Each EMA value should be influenced by previous values
        assert len(result) == 3


class TestRSI:
    """Tests for Relative Strength Index indicator."""
    
    def test_rsi_calculation(self):
        """Test RSI calculation."""
        rsi = RSI('RSI', 5)
        # Rising prices should give high RSI
        data = [10.0, 11.0, 12.0, 13.0, 14.0, 15.0, 16.0]
        
        result = rsi.calculate(data)
        
        assert len(result) > 0
        # RSI should be high (>50) in uptrend
        assert result[-1] > 50
    
    def test_rsi_range(self):
        """Test RSI values are in valid range (0-100)."""
        rsi = RSI('RSI', 3)
        data = [10.0, 11.0, 9.0, 12.0, 8.0, 13.0, 7.0, 14.0]
        
        result = rsi.calculate(data)
        
        for value in result:
            assert 0 <= value <= 100
    
    def test_rsi_insufficient_data(self):
        """Test RSI with insufficient data."""
        rsi = RSI('RSI', 14)
        data = [1.0, 2.0, 3.0]
        
        result = rsi.calculate(data)
        
        assert result == []


class TestIndicatorLibrary:
    """Tests for IndicatorLibrary class."""
    
    def test_library_initialization(self):
        """Test IndicatorLibrary initialization."""
        library = IndicatorLibrary()
        
        assert library is not None
        assert 'SMA' in library.indicators
        assert 'EMA' in library.indicators
        assert 'RSI' in library.indicators
    
    def test_get_indicator(self):
        """Test getting indicator from library."""
        library = IndicatorLibrary()
        
        sma = library.get_indicator('SMA', period=20)
        
        assert isinstance(sma, SMA)
        assert sma.period == 20
    
    def test_get_indicator_unknown(self):
        """Test getting unknown indicator raises error."""
        library = IndicatorLibrary()
        
        with pytest.raises(ValueError) as exc_info:
            library.get_indicator('UNKNOWN')
        
        assert "Unknown indicator" in str(exc_info.value)
    
    def test_list_indicators(self):
        """Test listing available indicators."""
        library = IndicatorLibrary()
        
        indicators = library.list_indicators()
        
        assert 'SMA' in indicators
        assert 'EMA' in indicators
        assert 'RSI' in indicators

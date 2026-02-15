"""
Chart Engine - Core charting functionality

Enhanced charting with:
- Interactive HTML charts via Plotly
- Multiple chart types (candlestick, line, bar, area, Heikin-Ashi)
- Technical indicator overlays
- Responsive design
- Export to HTML/PNG/PDF
"""

from typing import Dict, List, Any, Optional
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

try:
    import pandas as pd
    PANDAS_AVAILABLE = True
except ImportError:
    PANDAS_AVAILABLE = False

try:
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots
    PLOTLY_AVAILABLE = True
except ImportError:
    PLOTLY_AVAILABLE = False
    logger.warning("Plotly not installed. Interactive charts unavailable. Install with: pip install plotly")


class ChartType:
    CANDLESTICK = "candlestick"
    LINE = "line"
    BAR = "bar"
    AREA = "area"
    HEIKIN_ASHI = "heikin_ashi"


class ChartTheme:
    """Chart color themes (TradingView-inspired)."""
    DARK = {
        'bg_color': '#131722',
        'grid_color': '#2a2e39',
        'text_color': '#d1d4dc',
        'up_color': '#26a69a',
        'down_color': '#ef5350',
        'volume_color': '#5d606b',
        'ma_colors': ['#2962FF', '#FF6D00', '#7B1FA2', '#00BCD4'],
    }
    LIGHT = {
        'bg_color': '#ffffff',
        'grid_color': '#e1e3eb',
        'text_color': '#131722',
        'up_color': '#26a69a',
        'down_color': '#ef5350',
        'volume_color': '#b2b5be',
        'ma_colors': ['#2962FF', '#FF6D00', '#7B1FA2', '#00BCD4'],
    }


class Chart:
    """
    Represents a trading chart with interactive capabilities.

    Features:
    - Candlestick, line, bar, area chart types
    - Technical indicator overlays
    - Drawing tools support
    - Export to HTML/PNG
    """

    def __init__(
        self,
        symbol: str,
        timeframe: str,
        chart_type: str = ChartType.CANDLESTICK,
        theme: str = 'dark'
    ):
        self.symbol = symbol
        self.timeframe = timeframe
        self.chart_type = chart_type
        self.theme = ChartTheme.DARK if theme == 'dark' else ChartTheme.LIGHT
        self.indicators = []
        self.drawings = []
        self.data = None
        self.created_at = datetime.utcnow()

    def set_data(self, data):
        """
        Set OHLCV data for the chart.

        Args:
            data: DataFrame with columns: open, high, low, close, volume (optional)
        """
        self.data = data

    def add_indicator(self, indicator_name: str, **params):
        """Add technical indicator to chart."""
        self.indicators.append({
            'name': indicator_name,
            'params': params
        })

    def add_sma(self, period: int = 20, color: str = None):
        """Add Simple Moving Average."""
        self.add_indicator('SMA', period=period, color=color)

    def add_ema(self, period: int = 20, color: str = None):
        """Add Exponential Moving Average."""
        self.add_indicator('EMA', period=period, color=color)

    def add_bollinger_bands(self, period: int = 20, std_dev: float = 2.0):
        """Add Bollinger Bands."""
        self.add_indicator('BB', period=period, std_dev=std_dev)

    def add_rsi(self, period: int = 14):
        """Add RSI in separate panel."""
        self.add_indicator('RSI', period=period)

    def add_macd(self, fast: int = 12, slow: int = 26, signal: int = 9):
        """Add MACD in separate panel."""
        self.add_indicator('MACD', fast=fast, slow=slow, signal=signal)

    def render(self, output_format: str = 'plotly') -> Dict:
        """Render chart data as dictionary."""
        return {
            'symbol': self.symbol,
            'timeframe': self.timeframe,
            'type': self.chart_type,
            'indicators': self.indicators,
            'format': output_format
        }

    def to_html(self, include_volume: bool = True, height: int = 600) -> str:
        """
        Render chart as interactive HTML using Plotly.

        Args:
            include_volume: Include volume subplot
            height: Chart height in pixels

        Returns:
            HTML string with embedded chart
        """
        if not PLOTLY_AVAILABLE:
            return self._fallback_html()

        if self.data is None:
            return self._empty_chart_html()

        # Check if data is empty (handle both pandas DataFrame and other data types)
        if PANDAS_AVAILABLE:
            try:
                if hasattr(self.data, 'empty') and self.data.empty:
                    return self._empty_chart_html()
            except Exception:
                pass

        # Create figure with subplots
        has_volume = False
        if PANDAS_AVAILABLE and hasattr(self.data, 'columns'):
            has_volume = 'volume' in self.data.columns
        has_rsi = any(ind['name'] == 'RSI' for ind in self.indicators)
        has_macd = any(ind['name'] == 'MACD' for ind in self.indicators)

        rows = 1 + (1 if include_volume and has_volume else 0) + (1 if has_rsi else 0) + (1 if has_macd else 0)
        row_heights = [0.6] + [0.15] * (rows - 1) if rows > 1 else [1.0]

        fig = make_subplots(
            rows=rows,
            cols=1,
            shared_xaxes=True,
            vertical_spacing=0.03,
            row_heights=row_heights
        )

        # Main chart
        if self.chart_type == ChartType.CANDLESTICK:
            fig.add_trace(
                go.Candlestick(
                    x=self.data.index,
                    open=self.data['open'],
                    high=self.data['high'],
                    low=self.data['low'],
                    close=self.data['close'],
                    name='OHLC',
                    increasing_line_color=self.theme['up_color'],
                    decreasing_line_color=self.theme['down_color'],
                ),
                row=1, col=1
            )
        elif self.chart_type == ChartType.LINE:
            fig.add_trace(
                go.Scatter(
                    x=self.data.index,
                    y=self.data['close'],
                    mode='lines',
                    name='Close',
                    line=dict(color=self.theme['up_color'])
                ),
                row=1, col=1
            )
        elif self.chart_type == ChartType.AREA:
            fig.add_trace(
                go.Scatter(
                    x=self.data.index,
                    y=self.data['close'],
                    fill='tozeroy',
                    name='Close',
                    line=dict(color=self.theme['up_color'])
                ),
                row=1, col=1
            )

        # Add indicators
        self._add_indicators_to_figure(fig, rows)

        # Add volume
        current_row = 2
        if include_volume and has_volume:
            colors = [self.theme['up_color'] if c >= o else self.theme['down_color']
                      for c, o in zip(self.data['close'], self.data['open'])]
            fig.add_trace(
                go.Bar(
                    x=self.data.index,
                    y=self.data['volume'],
                    name='Volume',
                    marker_color=colors,
                    opacity=0.5
                ),
                row=current_row, col=1
            )
            current_row += 1

        # Style the chart
        fig.update_layout(
            title=f'{self.symbol} - {self.timeframe}',
            template='plotly_dark' if self.theme == ChartTheme.DARK else 'plotly_white',
            xaxis_rangeslider_visible=False,
            height=height,
            showlegend=True,
            legend=dict(
                orientation="h",
                yanchor="bottom",
                y=1.02,
                xanchor="right",
                x=1
            ),
            paper_bgcolor=self.theme['bg_color'],
            plot_bgcolor=self.theme['bg_color'],
            font=dict(color=self.theme['text_color']),
        )

        # Grid styling
        fig.update_xaxes(gridcolor=self.theme['grid_color'], gridwidth=1)
        fig.update_yaxes(gridcolor=self.theme['grid_color'], gridwidth=1)

        return fig.to_html(include_plotlyjs=True, full_html=True)

    def _add_indicators_to_figure(self, fig, total_rows: int):
        """Add technical indicators to the figure."""
        if not PANDAS_AVAILABLE:
            return

        ma_color_idx = 0

        for indicator in self.indicators:
            name = indicator['name']
            params = indicator['params']

            if name == 'SMA':
                period = params.get('period', 20)
                sma = self.data['close'].rolling(window=period).mean()
                color = params.get('color') or self.theme['ma_colors'][ma_color_idx % len(self.theme['ma_colors'])]
                fig.add_trace(
                    go.Scatter(x=self.data.index, y=sma, mode='lines',
                               name=f'SMA({period})', line=dict(color=color, width=1)),
                    row=1, col=1
                )
                ma_color_idx += 1

            elif name == 'EMA':
                period = params.get('period', 20)
                ema = self.data['close'].ewm(span=period, adjust=False).mean()
                color = params.get('color') or self.theme['ma_colors'][ma_color_idx % len(self.theme['ma_colors'])]
                fig.add_trace(
                    go.Scatter(x=self.data.index, y=ema, mode='lines',
                               name=f'EMA({period})', line=dict(color=color, width=1)),
                    row=1, col=1
                )
                ma_color_idx += 1

            elif name == 'BB':
                period = params.get('period', 20)
                std_dev = params.get('std_dev', 2.0)
                sma = self.data['close'].rolling(window=period).mean()
                std = self.data['close'].rolling(window=period).std()
                upper = sma + (std * std_dev)
                lower = sma - (std * std_dev)

                fig.add_trace(
                    go.Scatter(x=self.data.index, y=upper, mode='lines',
                               name='BB Upper', line=dict(color='#5d606b', width=1, dash='dot')),
                    row=1, col=1
                )
                fig.add_trace(
                    go.Scatter(x=self.data.index, y=sma, mode='lines',
                               name='BB Mid', line=dict(color='#5d606b', width=1)),
                    row=1, col=1
                )
                fig.add_trace(
                    go.Scatter(x=self.data.index, y=lower, mode='lines',
                               name='BB Lower', line=dict(color='#5d606b', width=1, dash='dot'),
                               fill='tonexty', fillcolor='rgba(93, 96, 107, 0.1)'),
                    row=1, col=1
                )

    def _fallback_html(self) -> str:
        """Return fallback HTML when Plotly is not available."""
        return f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>{self.symbol} Chart</title>
            <style>
                body {{ font-family: Arial, sans-serif; background: #131722; color: #d1d4dc; padding: 20px; }}
                .chart-placeholder {{
                    border: 2px dashed #2a2e39;
                    padding: 40px;
                    text-align: center;
                    border-radius: 8px;
                }}
            </style>
        </head>
        <body>
            <div class="chart-placeholder">
                <h2>📊 {self.symbol} - {self.timeframe}</h2>
                <p>Interactive charts require Plotly.</p>
                <p>Install with: <code>pip install plotly</code></p>
            </div>
        </body>
        </html>
        """

    def _empty_chart_html(self) -> str:
        """Return HTML for empty chart."""
        return f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>{self.symbol} Chart</title>
            <style>
                body {{ font-family: Arial, sans-serif; background: #131722; color: #d1d4dc; padding: 20px; }}
                .chart-placeholder {{
                    border: 2px dashed #2a2e39;
                    padding: 40px;
                    text-align: center;
                    border-radius: 8px;
                }}
            </style>
        </head>
        <body>
            <div class="chart-placeholder">
                <h2>📊 {self.symbol} - {self.timeframe}</h2>
                <p>No data available. Use chart.set_data(df) to add data.</p>
            </div>
        </body>
        </html>
        """

    def save_html(self, filepath: str, **kwargs):
        """Save chart to HTML file."""
        html = self.to_html(**kwargs)
        with open(filepath, 'w') as f:
            f.write(html)
        logger.info(f"Chart saved to {filepath}")


class ChartEngine:
    """
    Main chart engine for creating and managing charts.

    Example:
        engine = ChartEngine()
        chart = engine.create_chart('XAUUSD', '1H')
        chart.set_data(df)  # DataFrame with OHLCV
        chart.add_sma(20)
        chart.add_ema(50)
        html = chart.to_html()
    """

    def __init__(self, default_theme: str = 'dark'):
        self.charts: Dict[str, Chart] = {}
        self.default_theme = default_theme

    def create_chart(
        self,
        symbol: str,
        timeframe: str,
        chart_type: str = ChartType.CANDLESTICK,
        theme: str = None
    ) -> Chart:
        """Create a new chart."""
        chart = Chart(
            symbol,
            timeframe,
            chart_type,
            theme=theme or self.default_theme
        )
        chart_id = f"{symbol}_{timeframe}_{datetime.utcnow().timestamp()}"
        self.charts[chart_id] = chart
        return chart

    def get_chart(self, chart_id: str) -> Optional[Chart]:
        """Get existing chart by ID."""
        return self.charts.get(chart_id)

    def list_charts(self) -> List[str]:
        """Get list of chart IDs."""
        return list(self.charts.keys())

    def delete_chart(self, chart_id: str) -> bool:
        """Delete a chart."""
        if chart_id in self.charts:
            del self.charts[chart_id]
            return True
        return False

    def quick_chart(
        self,
        data,
        symbol: str = 'CHART',
        timeframe: str = '1D',
        indicators: List[str] = None
    ) -> str:
        """
        Quick chart creation with data.

        Args:
            data: DataFrame with OHLCV data
            symbol: Symbol name
            timeframe: Timeframe string
            indicators: List of indicators like ['SMA:20', 'EMA:50', 'BB:20']

        Returns:
            HTML string
        """
        chart = self.create_chart(symbol, timeframe)
        chart.set_data(data)

        # Parse and add indicators
        if indicators:
            for ind in indicators:
                if ':' in ind:
                    name, param = ind.split(':')
                    if name.upper() == 'SMA':
                        chart.add_sma(int(param))
                    elif name.upper() == 'EMA':
                        chart.add_ema(int(param))
                    elif name.upper() == 'BB':
                        chart.add_bollinger_bands(int(param))
                elif ind.upper() == 'RSI':
                    chart.add_rsi()
                elif ind.upper() == 'MACD':
                    chart.add_macd()

        return chart.to_html()

"""
Production equity curve visualization with headless support.
"""
import os
import json
from typing import List, Dict, Optional, Union
from datetime import datetime
from decimal import Decimal
from dataclasses import dataclass
from pathlib import Path

import plotly.graph_objects as go
from plotly.subplots import make_subplots
import plotly.io as pio

# Set headless backend BEFORE importing matplotlib
os.environ['MPLBACKEND'] = 'Agg'

import matplotlib
matplotlib.use('Agg')  # Force non-interactive backend
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import numpy as np

import structlog

logger = structlog.get_logger()


@dataclass
class TradeRecord:
    """Trade record for equity curve calculation."""
    entry_time: datetime
    exit_time: Optional[datetime]
    pnl: Decimal
    pnl_pct: Decimal
    symbol: str = "XAUUSD"


class EquityCurveGenerator:
    """
    Generate institutional-grade equity curves and performance reports.
    Supports both Plotly (interactive) and Matplotlib (static) outputs.
    """
    
    def __init__(self, initial_capital: Decimal = Decimal("10000.00")):
        self.initial_capital = initial_capital
        self.trades: List[TradeRecord] = []
        self.equity_curve: List[Dict] = []
        
    def add_trade(self, trade: TradeRecord) -> None:
        """Add trade to history."""
        self.trades.append(trade)
        
    def add_trades(self, trades: List[TradeRecord]) -> None:
        """Add multiple trades."""
        self.trades.extend(trades)
        
    def calculate_equity_curve(self) -> List[Dict]:
        """
        Calculate equity curve from trade history.
        Returns list of {timestamp, equity, drawdown, drawdown_pct}.
        """
        if not self.trades:
            return []
        
        # Sort by exit time
        sorted_trades = sorted(
            [t for t in self.trades if t.exit_time is not None],
            key=lambda x: x.exit_time
        )
        
        equity = self.initial_capital
        peak = equity
        curve = []
        
        # Starting point
        curve.append({
            "timestamp": sorted_trades[0].entry_time,
            "equity": float(equity),
            "drawdown": 0.0,
            "drawdown_pct": 0.0,
            "trade_pnl": 0.0
        })
        
        for trade in sorted_trades:
            equity += trade.pnl
            if equity > peak:
                peak = equity
            
            drawdown = peak - equity
            drawdown_pct = (drawdown / peak * 100) if peak > 0 else 0
            
            curve.append({
                "timestamp": trade.exit_time,
                "equity": float(equity),
                "drawdown": float(drawdown),
                "drawdown_pct": float(drawdown_pct),
                "trade_pnl": float(trade.pnl)
            })
        
        self.equity_curve = curve
        return curve
    
    def calculate_metrics(self) -> Dict:
        """Calculate comprehensive performance metrics."""
        if not self.equity_curve:
            return {}
        
        equities = [p["equity"] for p in self.equity_curve]
        returns = [p["trade_pnl"] for p in self.equity_curve[1:]]
        
        total_return = (equities[-1] - self.initial_capital) / self.initial_capital * 100
        
        # Sharpe ratio (assuming risk-free rate 0)
        if len(returns) > 1 and np.std(returns) > 0:
            sharpe = np.mean(returns) / np.std(returns) * np.sqrt(252)  # Annualized
        else:
            sharpe = 0
        
        # Max drawdown
        max_dd = max(p["drawdown_pct"] for p in self.equity_curve)
        
        # Win rate
        winning_trades = sum(1 for r in returns if r > 0)
        win_rate = winning_trades / len(returns) * 100 if returns else 0
        
        # Profit factor
        gross_profit = sum(r for r in returns if r > 0)
        gross_loss = abs(sum(r for r in returns if r < 0))
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else float('inf')
        
        # Calmar ratio
        calmar = (total_return / max_dd) if max_dd > 0 else float('inf')
        
        return {
            "total_return_pct": round(total_return, 2),
            "sharpe_ratio": round(sharpe, 2),
            "max_drawdown_pct": round(max_dd, 2),
            "win_rate_pct": round(win_rate, 2),
            "profit_factor": round(profit_factor, 2),
            "calmar_ratio": round(calmar, 2),
            "total_trades": len(self.trades),
            "final_equity": round(equities[-1], 2),
            "avg_trade_return": round(np.mean(returns), 2) if returns else 0,
        }
    
    def plot_plotly(self, 
                    title: str = "HOPEFX Equity Curve",
                    include_drawdown: bool = True) -> go.Figure:
        """
        Generate interactive Plotly equity curve.
        Safe for headless environments.
        """
        if not self.equity_curve:
            self.calculate_equity_curve()
        
        df = self.equity_curve
        timestamps = [p["timestamp"] for p in df]
        equities = [p["equity"] for p in df]
        drawdowns = [p["drawdown_pct"] for p in df]
        
        if include_drawdown:
            fig = make_subplots(
                rows=2, cols=1,
                shared_xaxes=True,
                vertical_spacing=0.03,
                row_heights=[0.7, 0.3],
                subplot_titles=("Equity Curve", "Drawdown %")
            )
        else:
            fig = go.Figure()
        
        # Equity curve
        fig.add_trace(
            go.Scatter(
                x=timestamps,
                y=equities,
                mode='lines',
                name='Equity',
                line=dict(color='#00C851', width=2),
                fill='tonexty',
                fillcolor='rgba(0, 200, 81, 0.1)'
            ),
            row=1, col=1
        )
        
        # Add initial capital line
        fig.add_trace(
            go.Scatter(
                x=[timestamps[0], timestamps[-1]],
                y=[float(self.initial_capital), float(self.initial_capital)],
                mode='lines',
                name='Initial Capital',
                line=dict(color='gray', width=1, dash='dash')
            ),
            row=1, col=1
        )
        
        if include_drawdown:
            # Drawdown
            fig.add_trace(
                go.Scatter(
                    x=timestamps,
                    y=drawdowns,
                    mode='lines',
                    name='Drawdown %',
                    line=dict(color='#ff4444', width=1.5),
                    fill='tozeroy',
                    fillcolor='rgba(255, 68, 68, 0.2)'
                ),
                row=2, col=1
            )
        
        # Layout
        fig.update_layout(
            title=dict(
                text=f"{title}<br><sub>Total Return: {self.calculate_metrics().get('total_return_pct', 0)}% | Max DD: {self.calculate_metrics().get('max_drawdown_pct', 0)}%</sub>",
                x=0.5
            ),
            template='plotly_dark',
            height=800 if include_drawdown else 600,
            showlegend=True,
            hovermode='x unified'
        )
        
        fig.update_yaxes(title_text="Equity ($)", row=1, col=1)
        if include_drawdown:
            fig.update_yaxes(title_text="Drawdown %", row=2, col=1)
            fig.update_xaxes(title_text="Date", row=2, col=1)
        
        return fig
    
    def save_plotly(self, 
                    filepath: Union[str, Path],
                    title: str = "HOPEFX Equity Curve",
                    format: str = "html") -> str:
        """
        Save Plotly figure to file.
        Supports html, png, jpeg, pdf, svg.
        """
        fig = self.plot_plotly(title)
        filepath = Path(filepath)
        
        if format == "html":
            fig.write_html(str(filepath))
        else:
            # For static formats, use kaleido
            fig.write_image(str(filepath), format=format, scale=2)
        
        logger.info("equity_curve_saved", path=str(filepath), format=format)
        return str(filepath)
    
    def plot_matplotlib(self,
                       title: str = "HOPEFX Equity Curve",
                       figsize: tuple = (12, 8)) -> plt.Figure:
        """
        Generate static matplotlib equity curve (headless safe).
        """
        if not self.equity_curve:
            self.calculate_equity_curve()
        
        df = self.equity_curve
        timestamps = [p["timestamp"] for p in df]
        equities = [p["equity"] for p in df]
        drawdowns = [p["drawdown_pct"] for p in df]
        
        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=figsize, 
                                        gridspec_kw={'height_ratios': [3, 1]},
                                        sharex=True)
        
        # Equity curve
        ax1.plot(timestamps, equities, color='#2E7D32', linewidth=2, label='Equity')
        ax1.axhline(y=float(self.initial_capital), color='gray', 
                   linestyle='--', alpha=0.5, label='Initial Capital')
        ax1.fill_between(timestamps, equities, float(self.initial_capital), 
                        alpha=0.3, color='#4CAF50')
        ax1.set_ylabel('Equity ($)', fontsize=11)
        ax1.set_title(title, fontsize=14, fontweight='bold')
        ax1.legend(loc='upper left')
        ax1.grid(True, alpha=0.3)
        
        # Format y-axis as currency
        ax1.yaxis.set_major_formatter(
            plt.FuncFormatter(lambda x, p: f'${x:,.0f}')
        )
        
        # Drawdown
        ax2.fill_between(timestamps, drawdowns, 0, color='#D32F2F', alpha=0.4)
        ax2.plot(timestamps, drawdowns, color='#D32F2F', linewidth=1)
        ax2.set_ylabel('Drawdown (%)', fontsize=11)
        ax2.set_xlabel('Date', fontsize=11)
        ax2.grid(True, alpha=0.3)
        
        # Rotate x-axis labels
        plt.xticks(rotation=45)
        plt.tight_layout()
        
        return fig
    
    def save_matplotlib(self,
                       filepath: Union[str, Path],
                       title: str = "HOPEFX Equity Curve",
                       dpi: int = 150) -> str:
        """
        Save matplotlib figure (headless safe).
        """
        fig = self.plot_matplotlib(title)
        filepath = Path(filepath)
        fig.savefig(str(filepath), dpi=dpi, bbox_inches='tight', 
                   facecolor='white', edgecolor='none')
        plt.close(fig)  # Clean up memory
        
        logger.info("equity_curve_saved", path=str(filepath))
        return str(filepath)
    
        def generate_report(self, 
                       output_dir: Union[str, Path],
                       strategy_name: str = "XAUUSD_ML_Strategy") -> Dict:
        """
        Generate comprehensive HTML report with metrics and charts.
        """
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        
        # Calculate everything
        self.calculate_equity_curve()
        metrics = self.calculate_metrics()
        
        # Save plots
        plotly_path = output_dir / "equity_curve.html"
        png_path = output_dir / "equity_curve.png"
        
        self.save_plotly(plotly_path, title=f"{strategy_name} - Equity Curve")
        self.save_matplotlib(png_path, title=f"{strategy_name} - Equity Curve")
        
        # Monthly returns heatmap data
        monthly_returns = self._calculate_monthly_returns()
        
        # Generate HTML report
        html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>HOPEFX Backtest Report - {strategy_name}</title>
    <script src="https://cdn.plot.ly/plotly-latest.min.js"></script>
    <style>
        body {{ font-family: 'Segoe UI', system-ui, -apple-system, sans-serif; margin: 0; padding: 40px 20px; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); min-height: 100vh; }}
        .container {{ max-width: 1400px; margin: 0 auto; background: white; padding: 40px; border-radius: 20px; box-shadow: 0 20px 60px rgba(0,0,0,0.3); }}
        h1 {{ color: #1a237e; border-bottom: 4px solid #667eea; padding-bottom: 15px; margin-bottom: 30px; font-size: 2.5em; }}
        .subtitle {{ color: #666; font-size: 1.1em; margin-top: -20px; margin-bottom: 30px; }}
        .metrics {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 20px; margin: 30px 0; }}
        .metric {{ background: linear-gradient(135deg, #f5f7fa 0%, #c3cfe2 100%); padding: 25px; border-radius: 15px; text-align: center; border-left: 5px solid #667eea; transition: transform 0.2s; }}
        .metric:hover {{ transform: translateY(-5px); box-shadow: 0 10px 30px rgba(0,0,0,0.1); }}
        .metric-value {{ font-size: 32px; font-weight: bold; color: #1a237e; margin: 10px 0; }}
        .metric-label {{ font-size: 13px; color: #555; text-transform: uppercase; letter-spacing: 1px; font-weight: 600; }}
        .metric.positive {{ border-left-color: #00c853; }}
        .metric.negative {{ border-left-color: #ff1744; }}
        .metric.neutral {{ border-left-color: #ffd600; }}
        .chart-container {{ margin: 40px 0; padding: 20px; background: #fafafa; border-radius: 15px; }}
        .chart-title {{ font-size: 1.5em; color: #1a237e; margin-bottom: 20px; font-weight: 600; }}
        table {{ width: 100%; border-collapse: collapse; margin: 20px 0; }}
        th, td {{ padding: 15px; text-align: left; border-bottom: 1px solid #ddd; }}
        th {{ background: #667eea; color: white; font-weight: 600; text-transform: uppercase; font-size: 12px; letter-spacing: 1px; }}
        tr:hover {{ background: #f5f5f5; }}
        .footer {{ margin-top: 50px; padding-top: 20px; border-top: 2px solid #eee; color: #999; font-size: 12px; text-align: center; }}
        .badge {{ display: inline-block; padding: 5px 15px; border-radius: 20px; font-size: 12px; font-weight: bold; text-transform: uppercase; }}
        .badge.success {{ background: #00c853; color: white; }}
        .badge.warning {{ background: #ffd600; color: black; }}
        .badge.danger {{ background: #ff1744; color: white; }}
        @media print {{ body {{ background: white; }} .container {{ box-shadow: none; }} }}
    </style>
</head>
<body>
    <div class="container">
        <h1>📊 HOPEFX Backtest Report</h1>
        <p class="subtitle">Strategy: <strong>{strategy_name}</strong> | Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} UTC</p>
        
        <div style="margin-bottom: 30px;">
            <span class="badge {'success' if metrics.get('total_return_pct', 0) > 0 else 'danger'}">
                {'PROFITABLE' if metrics.get('total_return_pct', 0) > 0 else 'UNPROFITABLE'}
            </span>
            <span class="badge {'success' if metrics.get('sharpe_ratio', 0) > 1 else 'warning' if metrics.get('sharpe_ratio', 0) > 0.5 else 'danger'}">
                SHARPE: {metrics.get('sharpe_ratio', 0):.2f}
            </span>
        </div>

        <div class="metrics">
            <div class="metric {'positive' if metrics.get('total_return_pct', 0) > 0 else 'negative'}">
                <div class="metric-label">Total Return</div>
                <div class="metric-value">{metrics.get('total_return_pct', 0):.2f}%</div>
            </div>
            <div class="metric">
                <div class="metric-label">Sharpe Ratio</div>
                <div class="metric-value">{metrics.get('sharpe_ratio', 0):.2f}</div>
            </div>
            <div class="metric negative">
                <div class="metric-label">Max Drawdown</div>
                <div class="metric-value">{metrics.get('max_drawdown_pct', 0):.2f}%</div>
            </div>
            <div class="metric">
                <div class="metric-label">Win Rate</div>
                <div class="metric-value">{metrics.get('win_rate_pct', 0):.1f}%</div>
            </div>
            <div class="metric">
                <div class="metric-label">Profit Factor</div>
                <div class="metric-value">{metrics.get('profit_factor', 0):.2f}</div>
            </div>
            <div class="metric">
                <div class="metric-label">Calmar Ratio</div>
                <div class="metric-value">{metrics.get('calmar_ratio', 0):.2f}</div>
            </div>
            <div class="metric">
                <div class="metric-label">Total Trades</div>
                <div class="metric-value">{metrics.get('total_trades', 0)}</div>
            </div>
            <div class="metric">
                <div class="metric-label">Final Equity</div>
                <div class="metric-value">${metrics.get('final_equity', 0):,.2f}</div>
            </div>
        </div>

        <div class="chart-container">
            <div class="chart-title">📈 Equity Curve</div>
            <iframe src="equity_curve.html" width="100%" height="600" frameborder="0"></iframe>
        </div>

        <div class="chart-container">
            <div class="chart-title">📅 Monthly Returns</div>
            <div id="monthly-heatmap"></div>
        </div>

        <h2>Trade Statistics</h2>
        <table>
            <tr>
                <th>Metric</th>
                <th>Value</th>
                <th>Benchmark</th>
            </tr>
            <tr>
                <td>Average Trade Return</td>
                <td>${metrics.get('avg_trade_return', 0):.2f}</td>
                <td>>$0 (Profitable)</td>
            </tr>
            <tr>
                <td>Risk-Adjusted Return</td>
                <td>{metrics.get('total_return_pct', 0) / metrics.get('max_drawdown_pct', 1):.2f}</td>
                <td>>2.0 (Good)</td>
            </tr>
        </table>

        <div class="footer">
            <p>Generated by HOPEFX Institutional Trading Platform v3.0.0</p>
            <p>⚠️ Past performance does not guarantee future results. Trade at your own risk.</p>
        </div>
    </div>

    <script>
        // Monthly returns heatmap
        var monthlyData = {json.dumps(monthly_returns)};
        
        var data = [{{
            z: monthlyData.values,
            x: monthlyData.months,
            y: monthlyData.years,
            type: 'heatmap',
            colorscale: [[0, '#ff1744'], [0.5, '#ffd600'], [1, '#00c853']],
            showscale: true
        }}];
        
        var layout = {{
            title: 'Monthly Returns Heatmap (%)',
            xaxis: {{title: 'Month'}},
            yaxis: {{title: 'Year'}},
            paper_bgcolor: 'rgba(0,0,0,0)',
            plot_bgcolor: 'rgba(0,0,0,0)'
        }};
        
        Plotly.newPlot('monthly-heatmap', data, layout);
    </script>
</body>
</html>"""
        
        report_path = output_dir / "report.html"
        with open(report_path, "w") as f:
            f.write(html_content)
        
        # Save JSON metrics
        json_path = output_dir / "metrics.json"
        with open(json_path, "w") as f:
            json.dump(metrics, f, indent=2)
        
        logger.info("report_generated", 
                   strategy=strategy_name,
                   output_dir=str(output_dir),
                   total_return=metrics.get('total_return_pct'))
        
        return {
            "metrics": metrics,
            "report_path": str(report_path),
            "plotly_path": str(plotly_path),
            "png_path": str(png_path),
            "json_path": str(json_path)
        }
    
    def _calculate_monthly_returns(self) -> Dict:
        """Calculate monthly returns for heatmap."""
        if not self.equity_curve:
            return {"years": [], "months": [], "values": []}
        
        # Group by month
        monthly_data = {}
        for point in self.equity_curve[1:]:  # Skip first point
            ts = point["timestamp"]
            key = (ts.year, ts.month)
            if key not in monthly_data:
                monthly_data[key] = []
            monthly_data[key].append(point["trade_pnl"])
        
        # Calculate monthly returns
        years = sorted(set(k[0] for k in monthly_data.keys()))
        months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", 
                 "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
        
        values = []
        for year in years:
            row = []
            for month in range(1, 13):
                pnl_list = monthly_data.get((year, month), [])
                total_pnl = sum(pnl_list) if pnl_list else 0
                # Convert to percentage return
                row.append(round(total_pnl / float(self.initial_capital) * 100, 2))
            values.append(row)
        
        return {
            "years": [str(y) for y in years],
            "months": months,
            "values": values
        }
    
    def get_drawdown_periods(self, threshold_pct: float = 5.0) -> List[Dict]:
        """
        Identify significant drawdown periods for analysis.
        """
        if not self.equity_curve:
            self.calculate_equity_curve()
        
        periods = []
        in_drawdown = False
        start_idx = 0
        
        for i, point in enumerate(self.equity_curve):
            dd_pct = point["drawdown_pct"]
            
            if not in_drawdown and dd_pct > threshold_pct:
                in_drawdown = True
                start_idx = i
            elif in_drawdown and dd_pct < threshold_pct:
                in_drawdown = False
                periods.append({
                    "start": self.equity_curve[start_idx]["timestamp"],
                    "end": point["timestamp"],
                    "max_drawdown_pct": max(p["drawdown_pct"] for p in self.equity_curve[start_idx:i+1]),
                    "duration_days": (point["timestamp"] - self.equity_curve[start_idx]["timestamp"]).days,
                    "recovery_equity": point["equity"]
                })
        
        return periods
    
    def plot_rolling_metrics(self, window: int = 30) -> go.Figure:
        """
        Plot rolling Sharpe and win rate.
        """
        if len(self.equity_curve) < window:
            return go.Figure()
        
        timestamps = [p["timestamp"] for p in self.equity_curve[window:]]
        equities = [p["equity"] for p in self.equity_curve]
        
        rolling_returns = []
        rolling_sharpe = []
        rolling_winrate = []
        

"""
Backtest report generation in HTML/JSON formats.
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import plotly.graph_objects as go
from plotly.subplots import make_subplots

from src.backtest.engine import BacktestResult


class BacktestReport:
    """
    Generate comprehensive backtest reports.
    """
    
    def __init__(self, result: BacktestResult):
        self.result = result
    
    def generate_html(self, output_path: Path) -> None:
        """Generate interactive HTML report."""
        fig = make_subplots(
            rows=3, cols=2,
            subplot_titles=(
                "Equity Curve", "Drawdown",
                "Returns Distribution", "Monthly Returns",
                "Trade Analysis", "Rolling Sharpe"
            ),
            specs=[
                [{"type": "scatter"}, {"type": "scatter"}],
                [{"type": "histogram"}, {"type": "bar"}],
                [{"type": "scatter"}, {"type": "scatter"}]
            ],
            vertical_spacing=0.1
        )
        
        # Equity curve
        equity = self.result.equity_curve
        fig.add_trace(
            go.Scatter(
                x=equity.index,
                y=equity.values,
                name="Equity",
                line=dict(color="#00ff88", width=2)
            ),
            row=1, col=1
        )
        
        # Drawdown
        running_max = equity.cummax()
        drawdown = (equity - running_max) / running_max * 100
        fig.add_trace(
            go.Scatter(
                x=drawdown.index,
                y=drawdown.values,
                name="Drawdown %",
                fill="tozeroy",
                line=dict(color="#ff4444")
            ),
            row=1, col=2
        )
        
        # Returns distribution
        returns = equity.pct_change().dropna() * 100
        fig.add_trace(
            go.Histogram(
                x=returns.values,
                nbinsx=50,
                name="Returns %",
                marker_color="#4488ff"
            ),
            row=2, col=1
        )
        
        # Monthly returns
        monthly = equity.resample('ME').last().pct_change().dropna() * 100
        colors = ['green' if r > 0 else 'red' for r in monthly]
        fig.add_trace(
            go.Bar(
                x=monthly.index,
                y=monthly.values,
                marker_color=colors,
                name="Monthly %"
            ),
            row=2, col=2
        )
        
        # Update layout
        fig.update_layout(
            title=f"Backtest Report: {self.result.start_date.date()} to {self.result.end_date.date()}",
            template="plotly_dark",
            height=1200,
            showlegend=False
        )
        
        # Save
        fig.write_html(str(output_path))
    
    def generate_json(self, output_path: Path) -> None:
        """Generate JSON report."""
        report = {
            "metadata": {
                "generated_at": datetime.now().isoformat(),
                "start_date": self.result.start_date.isoformat(),
                "end_date": self.result.end_date.isoformat(),
                "initial_capital": float(self.result.initial_capital),
                "final_equity": float(self.result.final_equity),
            },
            "metrics": self.result.metrics,
            "trades": self.result.trades,
            "equity_curve": [
                {"timestamp": t.isoformat(), "equity": float(e)}
                for t, e in self.result.equity_curve.items()
            ]
        }
        
        with open(output_path, 'w') as f:
            json.dump(report, f, indent=2)

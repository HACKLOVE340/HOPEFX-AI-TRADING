
 # Phase 1.2: Visualization Module - Equity Curves & Performance Charts

code = '''"""
HOPEFX Visualization Module
Equity curves, drawdown charts, and performance reporting
Supports Matplotlib (static) and Plotly (interactive)
"""

import pandas as pd
import numpy as np
from datetime import datetime
from typing import Dict, List, Optional, Tuple, Any
from pathlib import Path
import json

# Matplotlib imports
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.gridspec import GridSpec
from matplotlib.ticker import FuncFormatter

# Plotly imports
try:
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots
    import plotly.express as px
    PLOTLY_AVAILABLE = True
except ImportError:
    PLOTLY_AVAILABLE = False


class EquityCurvePlotter:
    """Generate professional equity curve visualizations"""
    
    def __init__(self, style: str = 'seaborn-v0_8-darkgrid', figsize: Tuple[int, int] = (14, 10)):
        self.figsize = figsize
        self.colors = {
            'equity': '#2E86AB',
            'drawdown': '#E94F37',
            'benchmark': '#6B7280',
            'positive': '#10B981',
            'negative': '#EF4444',
            'grid': '#E5E7EB',
            'background': '#F9FAFB'
        }
        try:
            plt.style.use(style)
        except:
            plt.style.use('seaborn-darkgrid')
    
    def plot_equity_curve(
        self,
        equity_df: pd.DataFrame,
        trades: Optional[List[Dict]] = None,
        benchmark: Optional[pd.Series] = None,
        title: str = "Strategy Performance",
        save_path: Optional[str] = None,
        show_plot: bool = True
    ) -> plt.Figure:
        """
        Create comprehensive equity curve chart with drawdown
        
        Args:
            equity_df: DataFrame with columns [timestamp, total_equity, drawdown]
            trades: List of trade dictionaries for entry/exit markers
            benchmark: Optional benchmark series (e.g., buy & hold)
            title: Chart title
            save_path: Path to save figure (PNG/SVG/PDF)
            show_plot: Whether to display the plot
        """
        # Prepare data
        if 'timestamp' in equity_df.columns:
            equity_df = equity_df.set_index('timestamp')
        
        equity_series = equity_df['total_equity']
        drawdown_series = equity_df['drawdown'] if 'drawdown' in equity_df.columns else self._calculate_drawdown(equity_series)
        
        # Create figure with subplots
        fig = plt.figure(figsize=self.figsize)
        gs = GridSpec(3, 1, height_ratios=[3, 1, 1], hspace=0.05)
        
        # Main equity curve
        ax1 = fig.add_subplot(gs[0])
        ax1.plot(equity_series.index, equity_series.values, 
                color=self.colors['equity'], linewidth=2, label='Strategy Equity')
        
        # Add benchmark if provided
        if benchmark is not None:
            # Normalize benchmark to same starting value
            normalized_benchmark = benchmark * (equity_series.iloc[0] / benchmark.iloc[0])
            ax1.plot(normalized_benchmark.index, normalized_benchmark.values,
                    color=self.colors['benchmark'], linewidth=1.5, 
                    linestyle='--', alpha=0.7, label='Benchmark')
        
        # Formatting
        ax1.set_title(title, fontsize=16, fontweight='bold', pad=20)
        ax1.set_ylabel('Portfolio Value ($)', fontsize=12)
        ax1.legend(loc='upper left', fontsize=10)
        ax1.grid(True, alpha=0.3)
        ax1.yaxis.set_major_formatter(FuncFormatter(self._currency_formatter))
        
        # Add trade markers
        if trades:
            self._add_trade_markers(ax1, equity_series, trades)
        
        # Drawdown chart
        ax2 = fig.add_subplot(gs[1], sharex=ax1)
        ax2.fill_between(drawdown_series.index, drawdown_series.values * 100, 0,
                        color=self.colors['drawdown'], alpha=0.3)
        ax2.plot(drawdown_series.index, drawdown_series.values * 100,
                color=self.colors['drawdown'], linewidth=1)
        ax2.set_ylabel('Drawdown (%)', fontsize=10)
        ax2.grid(True, alpha=0.3)
        
        # Highlight max drawdown
        max_dd_idx = drawdown_series.idxmax()
        max_dd_val = drawdown_series.max()
        ax2.axhline(y=max_dd_val * 100, color='red', linestyle='--', alpha=0.5)
        ax2.text(0.02, 0.95, f'Max DD: {max_dd_val:.2%}', 
                transform=ax2.transAxes, fontsize=9, verticalalignment='top',
                bbox=dict(boxstyle='round', facecolor='white', alpha=0.8))
        
        # Returns distribution
        ax3 = fig.add_subplot(gs[2], sharex=ax1)
        if 'daily_return' in equity_df.columns:
            returns = equity_df['daily_return'].dropna() * 100
        else:
            returns = equity_series.pct_change().dropna() * 100
        
        colors = [self.colors['positive'] if r >= 0 else self.colors['negative'] for r in returns]
        ax3.bar(returns.index, returns.values, color=colors, alpha=0.6, width=0.8)
        ax3.axhline(y=0, color='black', linewidth=0.5)
        ax3.set_ylabel('Daily Return (%)', fontsize=10)
        ax3.set_xlabel('Date', fontsize=12)
        ax3.grid(True, alpha=0.3)
        
        # Format x-axis
        ax3.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))
        ax3.xaxis.set_major_locator(mdates.MonthLocator(interval=3))
        plt.setp(ax1.get_xticklabels(), visible=False)
        plt.setp(ax2.get_xticklabels(), visible=False)
        plt.xticks(rotation=45)
        
        plt.tight_layout()
        
        # Save if path provided
        if save_path:
            self._save_figure(fig, save_path)
        
        if show_plot:
            plt.show()
        
        return fig
    
    def plot_performance_dashboard(
        self,
        metrics: Dict[str, Any],
        equity_df: pd.DataFrame,
        trades_df: Optional[pd.DataFrame] = None,
        save_path: Optional[str] = None,
        show_plot: bool = True
    ) -> plt.Figure:
        """
        Create comprehensive performance dashboard
        """
        fig = plt.figure(figsize=(16, 12))
        gs = GridSpec(3, 3, hspace=0.3, wspace=0.3)
        
        # 1. Equity curve (top row, spans 2 columns)
        ax1 = fig.add_subplot(gs[0, :2])
        if 'timestamp' in equity_df.columns:
            equity_df = equity_df.set_index('timestamp')
        
        equity_series = equity_df['total_equity']
        ax1.plot(equity_series.index, equity_series.values, 
                color=self.colors['equity'], linewidth=2)
        ax1.set_title('Equity Curve', fontsize=14, fontweight='bold')
        ax1.set_ylabel('Portfolio Value ($)')
        ax1.grid(True, alpha=0.3)
        ax1.yaxis.set_major_formatter(FuncFormatter(self._currency_formatter))
        
        # 2. Key metrics (top right)
        ax2 = fig.add_subplot(gs[0, 2])
        ax2.axis('off')
        
        metrics_text = f"""
        PERFORMANCE METRICS
        
        Total Return: {metrics.get('total_return', 0):.2%}
        Annualized Return: {metrics.get('annualized_return', 0):.2%}
        
        Sharpe Ratio: {metrics.get('sharpe_ratio', 0):.2f}
        Sortino Ratio: {metrics.get('sortino_ratio', 0):.2f}
        Calmar Ratio: {metrics.get('calmar_ratio', 0):.2f}
        
        Max Drawdown: {metrics.get('max_drawdown', 0):.2%}
        Max DD Duration: {metrics.get('max_drawdown_duration', 0)} days
        
        Total Trades: {metrics.get('total_trades', 0)}
        Win Rate: {metrics.get('win_rate', 0):.1%}
        Profit Factor: {metrics.get('profit_factor', 0):.2f}
        Expectancy: ${metrics.get('expectancy', 0):.2f}
        """
        
        ax2.text(0.1, 0.5, metrics_text, transform=ax2.transAxes,
                fontsize=10, verticalalignment='center',
                fontfamily='monospace',
                bbox=dict(boxstyle='round', facecolor='white', 
                         edgecolor='gray', alpha=0.9))
        
        # 3. Monthly returns heatmap (middle left)
        ax3 = fig.add_subplot(gs[1, 0])
        monthly_returns = self._calculate_monthly_returns(equity_series)
        if not monthly_returns.empty:
            monthly_pivot = monthly_returns.pivot(index='year', columns='month', values='return')
            im = ax3.imshow(monthly_pivot.values, cmap='RdYlGn', aspect='auto', vmin=-0.1, vmax=0.1)
            ax3.set_title('Monthly Returns Heatmap', fontsize=12)
            ax3.set_xlabel('Month')
            ax3.set_ylabel('Year')
            plt.colorbar(im, ax=ax3, format='%.1%')
        
        # 4. Drawdown chart (middle center)
        ax4 = fig.add_subplot(gs[1, 1])
        drawdown = self._calculate_drawdown(equity_series)
        ax4.fill_between(drawdown.index, drawdown.values * 100, 0,
                        color=self.colors['drawdown'], alpha=0.3)
        ax4.plot(drawdown.index, drawdown.values * 100,
                color=self.colors['drawdown'], linewidth=1)
        ax4.set_title('Drawdown', fontsize=12)
        ax4.set_ylabel('Drawdown (%)')
        ax4.grid(True, alpha=0.3)
        
        # 5. Trade distribution (middle right)
        ax5 = fig.add_subplot(gs[1, 2])
        if trades_df is not None and not trades_df.empty:
            pnl_values = trades_df['pnl'].values
            colors = [self.colors['positive'] if p > 0 else self.colors['negative'] for p in pnl_values]
            ax5.bar(range(len(pnl_values)), pnl_values, color=colors, alpha=0.7)
            ax5.axhline(y=0, color='black', linewidth=0.5)
            ax5.set_title('Trade P&L Distribution', fontsize=12)
            ax5.set_xlabel('Trade Number')
            ax5.set_ylabel('P&L ($)')
            ax5.grid(True, alpha=0.3)
        
        # 6. Rolling Sharpe (bottom left)
        ax6 = fig.add_subplot(gs[2, 0])
        rolling_sharpe = self._calculate_rolling_sharpe(equity_series, window=63)  # 3 months
        ax6.plot(rolling_sharpe.index, rolling_sharpe.values, 
                color=self.colors['equity'], linewidth=1.5)
        ax6.axhline(y=1.0, color='orange', linestyle='--', alpha=0.7, label='Good (1.0)')
        ax6.axhline(y=2.0, color='green', linestyle='--', alpha=0.7, label='Excellent (2.0)')
        ax6.set_title('Rolling Sharpe Ratio (3M)', fontsize=12)
        ax6.set_ylabel('Sharpe Ratio')
        ax6.legend(fontsize=8)
        ax6.grid(True, alpha=0.3)
        
        # 7. Win/Loss distribution (bottom center)
        ax7 = fig.add_subplot(gs[2, 1])
        if trades_df is not None and not trades_df.empty:
            wins = trades_df[trades_df['pnl'] > 0]['pnl']
            losses = trades_df[trades_df['pnl'] <= 0]['pnl']
            
            ax7.hist(wins, bins=20, color=self.colors['positive'], 
                    alpha=0.7, label=f'Wins ({len(wins)})')
            ax7.hist(losses, bins=20, color=self.colors['negative'], 
                    alpha=0.7, label=f'Losses ({len(losses)})')
            ax7.set_title('P&L Distribution', fontsize=12)
            ax7.set_xlabel('P&L ($)')
            ax7.set_ylabel('Frequency')
            ax7.legend(fontsize=8)
            ax7.grid(True, alpha=0.3)
        
        # 8. Underwater plot (bottom right)
        ax8 = fig.add_subplot(gs[2, 2])
        underwater = self._calculate_underwater_plot(equity_series)
        ax8.fill_between(underwater.index, underwater.values, 0,
                        color=self.colors['drawdown'], alpha=0.3)
        ax8.plot(underwater.index, underwater.values,
                color=self.colors['drawdown'], linewidth=1)
        ax8.set_title('Underwater Plot (Days to Recovery)', fontsize=12)
        ax8.set_ylabel('Days')
        ax8.grid(True, alpha=0.3)
        
        plt.suptitle('HOPEFX Strategy Performance Dashboard', 
                    fontsize=16, fontweight='bold', y=0.98)
        
        if save_path:
            self._save_figure(fig, save_path)
        
        if show_plot:
            plt.show()
        
        return fig
    
    def create_interactive_plotly(
        self,
        equity_df: pd.DataFrame,
        trades: Optional[List[Dict]] = None,
        title: str = "HOPEFX Interactive Equity Curve",
        save_path: Optional[str] = None
    ) -> Optional[Any]:
        """
        Create interactive Plotly chart
        """
        if not PLOTLY_AVAILABLE:
            print("Plotly not installed. Run: pip install plotly")
            return None
        
        if 'timestamp' in equity_df.columns:
            equity_df = equity_df.set_index('timestamp')
        
        equity_series = equity_df['total_equity']
        drawdown_series = equity_df['drawdown'] if 'drawdown' in equity_df.columns else self._calculate_drawdown(equity_series)
        
        # Create subplots
        fig = make_subplots(
            rows=3, cols=1,
            shared_xaxes=True,
            vertical_spacing=0.05,
            row_heights=[0.6, 0.2, 0.2],
            subplot_titles=('Equity Curve', 'Drawdown', 'Daily Returns')
        )
        
        # Equity curve
        fig.add_trace(
            go.Scatter(
                x=equity_series.index,
                y=equity_series.values,
                mode='lines',
                name='Equity',
                line=dict(color=self.colors['equity'], width=2),
                hovertemplate='%{x}<br>$%{y:,.2f}<extra></extra>'
            ),
            row=1, col=1
        )
        
        # Add trade markers
        if trades:
            entry_times = [t['entry_time'] for t in trades]
            entry_prices = [t['entry_price'] for t in trades]
            exit_times = [t['exit_time'] for t in trades]
            exit_prices = [t['exit_price'] for t in trades]
            
            fig.add_trace(
                go.Scatter(
                    x=entry_times,
                    y=entry_prices,
                    mode='markers',
                    name='Entries',
                    marker=dict(color='green', size=8, symbol='triangle-up'),
                    hovertemplate='Entry<br>%{x}<br>$%{y:,.2f}<extra></extra>'
                ),
                row=1, col=1
            )
            
            fig.add_trace(
                go.Scatter(
                    x=exit_times,
                    y=exit_prices,
                    mode='markers',
                    name='Exits',
                    marker=dict(color='red', size=8, symbol='triangle-down'),
                    hovertemplate='Exit<br>%{x}<br>$%{y:,.2f}<extra></extra>'
                ),
                row=1, col=1
            )
        
        # Drawdown
        fig.add_trace(
            go.Scatter(
                x=drawdown_series.index,
                y=drawdown_series.values * 100,
                mode='lines',
                name='Drawdown',
                fill='tozeroy',
                line=dict(color=self.colors['drawdown'], width=1),
                hovertemplate='%{x}<br>DD: %{y:.2f}%<extra></extra>'
            ),
            row=2, col=1
        )
        
        # Daily returns
        if 'daily_return' in equity_df.columns:
            returns = equity_df['daily_return'].dropna() * 100
        else:
            returns = equity_series.pct_change().dropna() * 100
        
        colors = [self.colors['positive'] if r >= 0 else self.colors['negative'] for r in returns]
        
        fig.add_trace(
            go.Bar(
                x=returns.index,
                y=returns.values,
                name='Daily Return',
                marker_color=colors,
                hovertemplate='%{x}<br>%{y:.2f}%<extra></extra>'
            ),
            row=3, col=1
        )
        
        # Layout
        fig.update_layout(
            title=dict(text=title, x=0.5, xanchor='center'),
            showlegend=True,
            hovermode='x unified',
            template='plotly_white',
            height=800
        )
        
        fig.update_yaxes(title_text="Portfolio Value ($)", row=1, col=1)
        fig.update_yaxes(title_text="Drawdown (%)", row=2, col=1)
        fig.update_yaxes(title_text="Return (%)", row=3, col=1)
        fig.update_xaxes(title_text="Date", row=3, col=1)
        
        # Save if path provided
        if save_path:
            if save_path.endswith('.html'):
                fig.write_html(save_path)
            elif save_path.endswith('.png') or save_path.endswith('.jpg'):
                fig.write_image(save_path, scale=2)
            else:
                fig.write_html(save_path + '.html')
            print(f"Interactive chart saved to {save_path}")
        
        return fig
    
    def generate_report(
        self,
        metrics: Dict[str, Any],
        equity_df: pd.DataFrame,
        trades_df: Optional[pd.DataFrame] = None,
        output_dir: str = "visualization/outputs",
        report_name: str = "backtest_report"
    ) -> Dict[str, str]:
        """
        Generate comprehensive report with multiple outputs
        
        Returns:
            Dictionary of generated file paths
        """
        Path(output_dir).mkdir(parents=True, exist_ok=True)
        
        generated_files = {}
        
        # 1. Static dashboard (PNG)
        dashboard_path = f"{output_dir}/{report_name}_dashboard.png"
        self.plot_performance_dashboard(
            metrics=metrics,
            equity_df=equity_df,
            trades_df=trades_df,
            save_path=dashboard_path,
            show_plot=False
        )
        generated_files['dashboard_png'] = dashboard_path
        
        # 2. Interactive Plotly (HTML)
        if PLOTLY_AVAILABLE:
            trades_list = trades_df.to_dict('records') if trades_df is not None else None
            plotly_path = f"{output_dir}/{report_name}_interactive.html"
            self.create_interactive_plotly(
                equity_df=equity_df,
                trades=trades_list,
                title=f"HOPEFX - {report_name}",
                save_path=plotly_path
            )
            generated_files['interactive_html'] = plotly_path
        
        # 3. Equity curve only (SVG for high quality)
        equity_path = f"{output_dir}/{report_name}_equity.svg"
        self.plot_equity_curve(
            equity_df=equity_df,
            title=f"Equity Curve - {report_name}",
            save_path=equity_path,
            show_plot=False
        )
        generated_files['equity_svg'] = equity_path
        
        # 4. Metrics JSON
        metrics_path = f"{output_dir}/{report_name}_metrics.json"
        with open(metrics_path, 'w') as f:
            json.dump(metrics, f, indent=2, default=str)
        generated_files['metrics_json'] = metrics_path
        
        print(f"Report generated: {report_name}")
        for key, path in generated_files.items():
            print(f"  - {key}: {path}")
        
        return generated_files
    
    # Helper methods
    def _calculate_drawdown(self, equity_series: pd.Series) -> pd.Series:
        """Calculate drawdown series"""
        rolling_max = equity_series.expanding().max()
        return (equity_series - rolling_max) / rolling_max
    
    def _calculate_monthly_returns(self, equity_series: pd.Series) -> pd.DataFrame:
        """Calculate monthly returns for heatmap"""
        daily_returns = equity_series.pct_change().dropna()
        monthly = daily_returns.resample('M').apply(lambda x: (1 + x).prod() - 1)
        
        df = pd.DataFrame({
            'year': monthly.index.year,
            'month': monthly.index.month,
            'return': monthly.values
        })
        return df
    
    def _calculate_rolling_sharpe(self, equity_series: pd.Series, window: int = 63) -> pd.Series:
        """Calculate rolling Sharpe ratio"""
        returns = equity_series.pct_change().dropna()
        rolling_mean = returns.rolling(window=window).mean() * 252
        rolling_std = returns.rolling(window=window).std() * np.sqrt(252)
        return rolling_mean / rolling_std
    
    def _calculate_underwater_plot(self, equity_series: pd.Series) -> pd.Series:
        """Calculate days underwater (time to recover from drawdowns)"""
        rolling_max = equity_series.expanding().max()
        underwater = equity_series < rolling_max
        
        days_underwater = pd.Series(0, index=equity_series.index)
        count = 0
        for i, is_under in enumerate(underwater):
            if is_under:
                count += 1
            else:
                count = 0
            days_underwater.iloc[i] = count
        
        return days_underwater
    
    def _add_trade_markers(self, ax, equity_series: pd.Series, trades: List[Dict]):
        """Add entry/exit markers to equity curve"""
        for trade in trades:
            try:
                entry_time = pd.to_datetime(trade['entry_time'])
                exit_time = pd.to_datetime(trade['exit_time'])
                
                # Find closest equity values
                entry_equity = equity_series.asof(entry_time)
                exit_equity = equity_series.asof(exit_time)
                
                color = self.colors['positive'] if trade['pnl'] > 0 else self.colors['negative']
                
                # Entry marker
                ax.scatter(entry_time, entry_equity, 
                          color='green', marker='^', s=100, zorder=5, alpha=0.7)
                
                # Exit marker
                ax.scatter(exit_time, exit_equity,
                          color='red', marker='v', s=100, zorder=5, alpha=0.7)
                
                # Connect with line
                ax.plot([entry_time, exit_time], [entry_equity, exit_equity],
                       color=color, linewidth=1, alpha=0.3)
            except:
                continue
    
    def _currency_formatter(self, x, pos):
        """Format currency values"""
        if x >= 1e6:
            return f'${x/1e6:.1f}M'
        elif x >= 1e3:
            return f'${x/1e3:.1f}k'
        return f'${x:.0f}'
    
    def _save_figure(self, fig: plt.Figure, path: str):
        """Save figure with proper format"""
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        
        if path.endswith('.svg'):
            fig.savefig(path, format='svg', bbox_inches='tight', dpi=300)
        elif path.endswith('.png'):
            fig.savefig(path, format='png', bbox_inches='tight', dpi=300)
        elif path.endswith('.pdf'):
            fig.savefig(path, format='pdf', bbox_inches='tight')
        else:
            fig.savefig(path + '.png', format='png', bbox_inches='tight', dpi=300)
            path = path + '.png'
        
        print(f"Figure saved: {path}")


class ReportGenerator:
    """Generate HTML/PDF reports from backtest results"""
    
    def __init__(self, template_dir: Optional[str] = None):
        self.template_dir = template_dir
    
    def generate_html_report(
        self,
        metrics: Dict[str, Any],
        equity_df: pd.DataFrame,
        trades_df: Optional[pd.DataFrame] = None,
        strategy_name: str = "Strategy",
        output_path: str = "report.html"
    ) -> str:
        """Generate standalone HTML report"""
        
        html = f"""
<!DOCTYPE html>
<html>
<head>
    <title>HOPEFX Backtest Report - {strategy_name}</title>
    <style>
        body {{ font-family: 'Segoe UI', Arial, sans-serif; margin: 40px; background: #f5f5f5; }}
        .container {{ max-width: 1200px; margin: 0 auto; background: white; padding: 30px; border-radius: 10px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }}
        h1 {{ color: #2E86AB; border-bottom: 3px solid #2E86AB; padding-bottom: 10px; }}
        h2 {{ color: #333; margin-top: 30px; }}
        .metrics-grid {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 20px; margin: 20px 0; }}
        .metric-card {{ background: #f8f9fa; padding: 15px; border-radius: 8px; border-left: 4px solid #2E86AB; }}
        .metric-label {{ font-size: 12px; color: #666; text-transform: uppercase; }}
        .metric-value {{ font-size: 24px; font-weight: bold; color: #333; margin-top: 5px; }}
        .positive {{ color: #10B981; }}
        .negative {{ color: #EF4444; }}
        table {{ width: 100%; border-collapse: collapse; margin: 20px 0; }}
        th, td {{ padding: 12px; text-align: left; border-bottom: 1px solid #ddd; }}
        th {{ background: #2E86AB; color: white; }}
        tr:hover {{ background: #f5f5f5; }}
        .chart-container {{ margin: 30px 0; text-align: center; }}
        .footer {{ margin-top: 40px; padding-top: 20px; border-top: 1px solid #ddd; color: #666; font-size: 12px; }}
    </style>
</head>
<body>
    <div class="container">
        <h1>🏆 HOPEFX Backtest Report</h1>
        <p><strong>Strategy:</strong> {strategy_name}</p>
        <p><strong>Period:</strong> {metrics.get('start_date', 'N/A')} to {metrics.get('end_date', 'N/A')}</p>
        <p><strong>Generated:</strong> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
        
        <h2>📊 Performance Metrics</h2>
        <div class="metrics-grid">
            <div class="metric-card">
                <div class="metric-label">Total Return</div>
                <div class="metric-value {'positive' if metrics.get('total_return', 0) > 0 else 'negative'}">
                    {metrics.get('total_return', 0):.2%}
                </div>
            </div>
            <div class="metric-card">
                <div class="metric-label">Sharpe Ratio</div>
                <div class="metric-value">{metrics.get('sharpe_ratio', 0):.2f}</div>
            </div>
            <div class="metric-card">
                <div class="metric-label">Max Drawdown</div>
                <div class="metric-value negative">{metrics.get('max_drawdown', 0):.2%}</div>
            </div>
            <div class="metric-card">
                <div class="metric-label">Win Rate</div>
                <div class="metric-value">{metrics.get('win_rate', 0):.1%}</div>
            </div>
            <div class="metric-card">
                <div class="metric-label">Total Trades</div>
                <div class="metric-value">{metrics.get('total_trades', 0)}</div>
            </div>
            <div class="metric-card">
                <div class="metric-label">Profit Factor</div>
                <div class="metric-value">{metrics.get('profit_factor', 0):.2f}</div>
            </div>
        </div>
        
        <h2>📈 Equity Curve</h2>
        <div class="chart-container">
            <img src="equity_curve.png" alt="Equity Curve" style="max-width: 100%; height: auto;">
        </div>
        
        <h2>📋 Trade History</h2>
        {self._generate_trades_table(trades_df) if trades_df is not None else '<p>No trades executed</p>'}
        
        <div class="footer">
            <p>Generated by HOPEFX AI Trading Platform</p>
            <p>⚠️ For educational purposes only. Past performance does not guarantee future results.</p>
        </div>
    </div>
</body>
</html>
"""
        
        with open(output_path, 'w') as f:
            f.write(html)
        
        print(f"HTML report saved: {output_path}")
        return output_path
    
    def _generate_trades_table(self, trades_df: pd.DataFrame) -> str:
        """Generate HTML table from trades DataFrame"""
        if trades_df.empty:
            return "<p>No trades executed</p>"
        
        # Take last 20 trades
        recent_trades = trades_df.tail(20)
        
        rows = ""
        for _, trade in recent_trades.iterrows():
            pnl_class = "positive" if trade['pnl'] > 0 else "negative"
            rows += f"""
            <tr>
                <td>{trade['trade_id']}</td>
                <td>{trade['symbol']}</td>
                <td>{trade['side']}</td>
                <td>{trade['entry_time']}</td>
                <td>${trade['entry_price']:.2f}</td>
                <td>{trade['exit_time']}</td>
                <td>${trade['exit_price']:.2f}</td>
                <td class="{pnl_class}">${trade['pnl']:.2f}</td>
            </tr>
            """
        
        return f"""
        <table>
            <tr>
                <th>Trade ID</th>
                <th>Symbol</th>
                <th>Side</th>
                <th>Entry Time</th>
                <th>Entry Price</th>
                <th>Exit Time</th>
                <th>Exit Price</th>
                <th>P&L</th>
            </tr>
            {rows}
        </table>
        """


if __name__ == "__main__":
    print("HOPEFX Visualization Module")
    print("Import EquityCurvePlotter and ReportGenerator to create charts and reports")
'''

# Save the file
with open('visualization/equity_curve.py', 'w') as f:
    f.write(code)

print("✅ Created: visualization/equity_curve.py")
print(f"   Lines: {len(code.splitlines())}")
print(f"   Size: {len(code)} bytes")

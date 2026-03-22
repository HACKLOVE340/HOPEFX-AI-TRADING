"""
Centralized artifact generation and management
Handles: equity curves, ML models, reports, tick data
"""

import json
import pickle
import joblib
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, Optional, List
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import kaleido  # For static image export

class ArtifactManager:
    """Manages all output artifacts with versioning and metadata."""
    
    BASE_DIRS = {
        'equity_curves': 'outputs/equity_curves',
        'models': 'outputs/models',
        'reports': 'outputs/reports',
        'tick_data': 'data/ticks',
        'backtests': 'outputs/backtests',
        'websocket_logs': 'logs/websocket'
    }
    
    def __init__(self, run_id: Optional[str] = None):
        self.run_id = run_id or datetime.now().strftime('%Y%m%d_%H%M%S')
        self._ensure_directories()
        
    def _ensure_directories(self):
        """Create output directories."""
        for dir_path in self.BASE_DIRS.values():
            Path(dir_path).mkdir(parents=True, exist_ok=True)
    
    def save_equity_curve(
        self,
        equity_data: pd.DataFrame,
        trades: List[Dict],
        metadata: Dict[str, Any],
        format: str = 'both'  # 'html', 'png', or 'both'
    ) -> Dict[str, Path]:
        """
        Generate and save equity curve visualization.
        
        Args:
            equity_data: DataFrame with 'timestamp', 'equity', 'drawdown' columns
            trades: List of trade dicts with entry/exit points
            metadata: Strategy name, parameters, performance metrics
        """
        output_paths = {}
        base_name = f"{metadata['strategy_name']}_{self.run_id}"
        
        # Create interactive Plotly figure
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
                x=equity_data['timestamp'],
                y=equity_data['equity'],
                mode='lines',
                name='Equity',
                line=dict(color='#00C851', width=2)
            ),
            row=1, col=1
        )
        
        # Add trade markers
        for trade in trades:
            color = '#00C851' if trade['pnl'] > 0 else '#ff4444'
            fig.add_trace(
                go.Scatter(
                    x=[trade['exit_time']],
                    y=[trade['exit_equity']],
                    mode='markers',
                    marker=dict(color=color, size=10, symbol='x'),
                    name=f"Trade {trade['id']}",
                    showlegend=False
                ),
                row=1, col=1
            )
        
        # Drawdown
        fig.add_trace(
            go.Scatter(
                x=equity_data['timestamp'],
                y=equity_data['drawdown'] * 100,
                fill='tozeroy',
                fillcolor='rgba(255, 68, 68, 0.2)',
                line=dict(color='#ff4444'),
                name='Drawdown %'
            ),
            row=2, col=1
        )
        
        # Daily returns distribution
        daily_returns = equity_data['equity'].pct_change().dropna()
        fig.add_trace(
            go.Histogram(
                x=daily_returns * 100,
                nbinsx=50,
                name='Returns %',
                marker_color='#33b5e5'
            ),
            row=3, col=1
        )
        
        # Layout
        fig.update_layout(
            title=f"Equity Curve: {metadata['strategy_name']} | "
                  f"Sharpe: {metadata.get('sharpe', 'N/A')} | "
                  f"Max DD: {metadata.get('max_drawdown', 'N/A')}%",
            template='plotly_dark',
            height=1000,
            showlegend=False
        )
        
        # Save HTML (interactive)
        if format in ['html', 'both']:
            html_path = Path(self.BASE_DIRS['equity_curves']) / f"{base_name}.html"
            fig.write_html(str(html_path))
            output_paths['html'] = html_path
        
        # Save PNG (static)
        if format in ['png', 'both']:
            png_path = Path(self.BASE_DIRS['equity_curves']) / f"{base_name}.png"
            fig.write_image(str(png_path), width=1920, height=1080, scale=2)
            output_paths['png'] = png_path
        
        # Save metadata JSON
        meta_path = Path(self.BASE_DIRS['equity_curves']) / f"{base_name}.json"
        with open(meta_path, 'w') as f:
            json.dump({
                'run_id': self.run_id,
                'created_at': datetime.now().isoformat(),
                'metadata': metadata,
                'trades_count': len(trades),
                'final_equity': float(equity_data['equity'].iloc[-1]),
                'max_drawdown': float(equity_data['drawdown'].max()),
                'files': {k: str(v) for k, v in output_paths.items()}
            }, f, indent=2)
        
        output_paths['metadata'] = meta_path
        return output_paths
    
    def save_model(
        self,
        model: Any,
        model_type: str,
        performance: Dict[str, float],
        feature_importance: Optional[Dict] = None,
        preprocessing_pipeline: Optional[Any] = None
    ) -> Path:
        """
        Save ML model with versioning and metadata.
        
        Args:
            model: Trained model object
            model_type: 'xgboost', 'lstm', 'random_forest'
            performance: Dict with accuracy, precision, recall, f1, etc.
        """
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f"{model_type}_{timestamp}.joblib"
        model_path = Path(self.BASE_DIRS['models']) / filename
        
        # Save model
        joblib.dump(model, model_path)
        
        # Save metadata
        meta = {
            'model_type': model_type,
            'created_at': timestamp,
            'performance': performance,
            'feature_importance': feature_importance,
            'file_size_mb': model_path.stat().st_size / (1024 * 1024),
            'scikit_learn_version': sklearn.__version__ if 'sklearn' in str(type(model)) else None
        }
        
        meta_path = model_path.with_suffix('.json')
        with open(meta_path, 'w') as f:
            json.dump(meta, f, indent=2)
        
        # Save preprocessing if provided
        if preprocessing_pipeline:
            prep_path = model_path.with_suffix('.preprocessing.joblib')
            joblib.dump(preprocessing_pipeline, prep_path)
        
        return model_path
    
    def save_tick_data(
        self,
        ticks: pd.DataFrame,
        symbol: str,
        date: datetime,
        broker: str
    ) -> Path:
        """Save websocket tick data with efficient compression."""
        date_str = date.strftime('%Y%m%d')
        filename = f"{symbol}_{broker}_{date_str}.parquet"
        file_path = Path(self.BASE_DIRS['tick_data']) / filename
        
        # Save as parquet (efficient compression)
        ticks.to_parquet(file_path, compression='zstd')
        
        # Update index
        index_path = Path(self.BASE_DIRS['tick_data']) / 'index.json'
        index = {}
        if index_path.exists():
            with open(index_path) as f:
                index = json.load(f)
        
        index[filename] = {
            'symbol': symbol,
            'date': date_str,
            'broker': broker,
            'rows': len(ticks),
            'size_mb': file_path.stat().st_size / (1024 * 1024)
        }
        
        with open(index_path, 'w') as f:
            json.dump(index, f, indent=2)
        
        return file_path
    
    def generate_report(
        self,
        backtest_results: Dict,
        output_format: str = 'html'
    ) -> Path:
        """Generate comprehensive backtest report."""
        report_name = f"report_{self.run_id}.{output_format}"
        report_path = Path(self.BASE_DIRS['reports']) / report_name
        
        if output_format == 'html':
            self._generate_html_report(backtest_results, report_path)
        elif output_format == 'pdf':
            self._generate_pdf_report(backtest_results, report_path)
        
        return report_path
    
    def _generate_html_report(self, results: Dict, path: Path):
        """Generate interactive HTML report."""
        html_template = """
        <!DOCTYPE html>
        <html>
        <head>
            <title>HOPEFX Backtest Report</title>
            <style>
                body { font-family: Arial, sans-serif; margin: 40px; background: #1a1a1a; color: #fff; }
                .metric { display: inline-block; margin: 20px; padding: 20px; background: #2d2d2d; border-radius: 8px; }
                .positive { color: #00C851; }
                .negative { color: #ff4444; }
                table { width: 100%; border-collapse: collapse; margin: 20px 0; }
                th, td { padding: 12px; text-align: left; border-bottom: 1px solid #444; }
                th { background: #333; }
            </style>
        </head>
        <body>
            <h1>Backtest Report: {strategy_name}</h1>
            <div class="metrics">
                <div class="metric">
                    <h3>Total Return</h3>
                    <p class="{return_class}">{total_return:.2f}%</p>
                </div>
                <div class="metric">
                    <h3>Sharpe Ratio</h3>
                    <p>{sharpe:.2f}</p>
                </div>
                <div class="metric">
                    <h3>Max Drawdown</h3>
                    <p class="negative">{max_dd:.2f}%</p>
                </div>
            </div>
            <h2>Trade List</h2>
            <table>
                <tr><th>Entry Time</th><th>Exit Time</th><th>Side</th><th>PnL</th></tr>
                {trade_rows}
            </table>
        </body>
        </html>
        """
        
        trades_html = ''.join([
            f"<tr><td>{t['entry_time']}</td><td>{t['exit_time']}</td>"
            f"<td>{t['side']}</td><td class='{'positive' if t['pnl'] > 0 else 'negative'}'>"
            f"{t['pnl']:.2f}</td></tr>"
            for t in results['trades']
        ])
        
        html = html_template.format(
            strategy_name=results['strategy_name'],
            total_return=results['total_return'] * 100,
            return_class='positive' if results['total_return'] > 0 else 'negative',
            sharpe=results['sharpe_ratio'],
            max_dd=results['max_drawdown'] * 100,
            trade_rows=trades_html
        )
        
        with open(path, 'w') as f:
            f.write(html)

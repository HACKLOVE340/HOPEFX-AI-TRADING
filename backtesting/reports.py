"""
Report Generator

Generates comprehensive backtest reports.
"""

import logging
from typing import Dict
import pandas as pd

logger = logging.getLogger(__name__)


class ReportGenerator:
    """
    Generate backtest reports in various formats.
    """
    
    def __init__(self, results: Dict):
        """
        Initialize report generator.
        
        Args:
            results: Backtest results dict
        """
        self.results = results
        
    def generate_text_report(self) -> str:
        """Generate text report."""
        metrics = self.results['metrics']
        
        report = []
        report.append("="*60)
        report.append("BACKTEST REPORT")
        report.append("="*60)
        report.append("")
        
        report.append("PERFORMANCE METRICS")
        report.append("-" * 60)
        report.append(f"Total Return: {metrics['total_return']:.2f}%")
        report.append(f"Annual Return: {metrics['annual_return']:.2f}%")
        report.append(f"Sharpe Ratio: {metrics['sharpe_ratio']:.2f}")
        report.append(f"Sortino Ratio: {metrics['sortino_ratio']:.2f}")
        report.append(f"Max Drawdown: {metrics['max_drawdown']:.2f}%")
        report.append(f"Calmar Ratio: {metrics['calmar_ratio']:.2f}")
        report.append(f"Volatility: {metrics['volatility']:.2f}%")
        report.append("")
        
        report.append("TRADE STATISTICS")
        report.append("-" * 60)
        report.append(f"Total Trades: {metrics['total_trades']}")
        report.append(f"Winning Trades: {metrics['winning_trades']}")
        report.append(f"Losing Trades: {metrics['losing_trades']}")
        report.append(f"Win Rate: {metrics['win_rate']:.2f}%")
        report.append(f"Profit Factor: {metrics['profit_factor']:.2f}")
        report.append(f"Average Win: ${metrics['avg_win']:.2f}")
        report.append(f"Average Loss: ${metrics['avg_loss']:.2f}")
        report.append(f"Largest Win: ${metrics['largest_win']:.2f}")
        report.append(f"Largest Loss: ${metrics['largest_loss']:.2f}")
        report.append("")
        
        report.append("="*60)
        
        return "\n".join(report)
        
    def save_to_file(self, filename: str):
        """Save report to file."""
        report = self.generate_text_report()
        
        with open(filename, 'w') as f:
            f.write(report)
            
        logger.info(f"Report saved to {filename}")

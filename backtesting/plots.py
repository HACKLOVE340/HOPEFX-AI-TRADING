"""
Performance Plotting

Creates visualizations of backtest results.
"""

import logging
import pandas as pd
from typing import Dict, Optional

logger = logging.getLogger(__name__)

try:
    import matplotlib.pyplot as plt
    MATPLOTLIB_AVAILABLE = True
except ImportError:
    MATPLOTLIB_AVAILABLE = False
    logger.warning("matplotlib not available. Plotting disabled.")


class PerformancePlotter:
    """
    Create performance visualizations.
    """
    
    def __init__(self, results: Dict):
        """
        Initialize plotter.
        
        Args:
            results: Backtest results
        """
        self.results = results
        
        if not MATPLOTLIB_AVAILABLE:
            logger.warning("Plotting requires matplotlib")
            
    def plot_equity_curve(self, filename: Optional[str] = None):
        """Plot equity curve."""
        if not MATPLOTLIB_AVAILABLE:
            return
            
        equity_curve = self.results['equity_curve']
        
        plt.figure(figsize=(12, 6))
        plt.plot(equity_curve.index, equity_curve['equity'])
        plt.title('Equity Curve')
        plt.xlabel('Date')
        plt.ylabel('Equity ($)')
        plt.grid(True)
        
        if filename:
            plt.savefig(filename)
            logger.info(f"Equity curve saved to {filename}")
        else:
            plt.show()
            
        plt.close()
        
    def plot_drawdown(self, filename: Optional[str] = None):
        """Plot drawdown."""
        if not MATPLOTLIB_AVAILABLE:
            return
            
        equity_curve = self.results['equity_curve']
        equity = equity_curve['equity']
        cummax = equity.cummax()
        drawdown = (equity - cummax) / cummax * 100
        
        plt.figure(figsize=(12, 6))
        plt.fill_between(drawdown.index, drawdown, 0, alpha=0.3, color='red')
        plt.plot(drawdown.index, drawdown, color='red')
        plt.title('Drawdown')
        plt.xlabel('Date')
        plt.ylabel('Drawdown (%)')
        plt.grid(True)
        
        if filename:
            plt.savefig(filename)
            logger.info(f"Drawdown plot saved to {filename}")
        else:
            plt.show()
            
        plt.close()

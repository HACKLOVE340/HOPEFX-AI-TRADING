# src/hopefx/visualization/equity_curve.py
"""
Equity curve visualization with proper resource cleanup.
"""
from __future__ import annotations

import io
from typing import TYPE_CHECKING

import matplotlib
matplotlib.use('Agg')  # Headless backend
import matplotlib.pyplot as plt
import numpy as np

if TYPE_CHECKING:
    from decimal import Decimal


class EquityCurvePlotter:
    """Generate equity curve plots with memory management."""
    
    def __init__(self):
        self._fig = None
        self._ax = None
    
    def __enter__(self):
        """Context manager entry."""
        self._fig, self._ax = plt.subplots(figsize=(12, 6))
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit with cleanup."""
        plt.close(self._fig)
        self._fig = None
        self._ax = None
        return False
    
    def plot(self, equity_data: list[tuple[float, Decimal]]) -> bytes:
        """Generate equity curve plot."""
        times = [x[0] for x in equity_data]
        equity = [float(x[1]) for x in equity_data]
        
        # Calculate drawdown
        peak = np.maximum.accumulate(equity)
        drawdown = (np.array(equity) - peak) / peak * 100
        
        # Plot equity
        self._ax.plot(times, equity, label='Equity', color='blue', linewidth=2)
        self._ax.set_xlabel('Time')
        self._ax.set_ylabel('Equity ($)', color='blue')
        self._ax.tick_params(axis='y', labelcolor='blue')
        
        # Plot drawdown on secondary axis
        ax2 = self._ax.twinx()
        ax2.fill_between(times, drawdown, 0, alpha=0.3, color='red', label='Drawdown %')
        ax2.set_ylabel('Drawdown (%)', color='red')
        ax2.tick_params(axis='y', labelcolor='red')
        
        # Title and legend
        self._ax.set_title('Equity Curve & Drawdown')
        self._ax.legend(loc='upper left')
        ax2.legend(loc='lower left')
        
        # Save to buffer
        buf = io.BytesIO()
        self._fig.savefig(buf, format='png', dpi=150, bbox_inches='tight')
        buf.seek(0)
        
        return buf.getvalue()


def generate_equity_chart(equity_data: list[tuple[float, Decimal]]) -> bytes:
    """Convenience function with guaranteed cleanup."""
    with EquityCurvePlotter() as plotter:
        return plotter.plot(equity_data)

# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
Performance Plotting

Creates visualizations of backtest results.
"""

import logging

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

    def __init__(self, results: dict):
        """
        Initialize plotter.

        Args:
            results: Backtest results
        """
        self.results = results

        if not MATPLOTLIB_AVAILABLE:
            logger.warning("Plotting requires matplotlib")

    def plot_equity_curve(self, filename: str | None = None):
        """Plot equity curve."""
        if not MATPLOTLIB_AVAILABLE:
            return

        equity_curve = self.results["equity_curve"]

        plt.figure(figsize=(12, 6))
        plt.plot(equity_curve.index, equity_curve["equity"])
        plt.title("Equity Curve")
        plt.xlabel("Date")
        plt.ylabel("Equity ($)")
        plt.grid(True)

        if filename:
            plt.savefig(filename)
            logger.info("Equity curve saved to %s", filename)

        else:
            plt.show()

        plt.close()

    def plot_drawdown(self, filename: str | None = None):
        """Plot drawdown."""
        if not MATPLOTLIB_AVAILABLE:
            return

        equity_curve = self.results["equity_curve"]
        equity = equity_curve["equity"]
        cummax = equity.cummax()
        drawdown = (equity - cummax) / cummax * 100

        plt.figure(figsize=(12, 6))
        plt.fill_between(drawdown.index, drawdown, 0, alpha=0.3, color="red")
        plt.plot(drawdown.index, drawdown, color="red")
        plt.title("Drawdown")
        plt.xlabel("Date")
        plt.ylabel("Drawdown (%)")
        plt.grid(True)

        if filename:
            plt.savefig(filename)
            logger.info("Drawdown plot saved to %s", filename)

        else:
            plt.show()

        plt.close()
